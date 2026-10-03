"""Text-only Grok CLI boundary: private config, no inherited execution surfaces."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .util import atomic_write_json, atomic_write_text, clean_child_env, no_window_flags


PROFILE = '''allowed_mcp_servers = []
[auth]
preferred_method = "oidc"
disable_api_key_auth = true
[managed_mcps]
enabled = false
gateway_tools_enabled = false
[features]
write_file = false
tool_search = false
lsp_tools = false
web_fetch = false
mcp_auto_restart = false
mcp_recursive_config_watch = false
[permission]
rules = [{ action = "deny", tool = "any" }]
[subagents]
enabled = false
[memory]
enabled = false
[models]
max_retries = 0
[cli]
auto_update = false
[compat.claude]
mcps = false
hooks = false
agents = false
rules = false
skills = false
[compat.cursor]
mcps = false
hooks = false
agents = false
rules = false
skills = false
[compat.codex]
hooks = false
skills = false
'''

REQUIRED_FLAGS = ("--prompt-file", "--output-format", "--model", "--tools",
                  "--disallowed-tools", "--deny", "--permission-mode",
                  "--no-subagents", "--disable-web-search", "--max-turns", "--json-schema")


class IsolationError(ValueError):
    pass


def inspect(info, cwd, env):
    try:
        result = subprocess.run([*info["cmd"], "inspect", "--json"], cwd=cwd, env=env,
                                capture_output=True, timeout=20, creationflags=no_window_flags())
        if result.returncode or len(result.stdout) > 1_000_000:
            raise IsolationError("Grok의 적용된 격리 설정을 확인할 수 없습니다.")
        doc = json.loads(result.stdout)
        if not isinstance(doc, dict):
            raise ValueError()
        return doc
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise IsolationError("Grok의 적용된 격리 설정을 확인할 수 없습니다.") from exc


def active(doc, kind):
    rows = doc.get(kind)
    if not isinstance(rows, list):
        raise IsolationError("Grok 설정 검사 응답이 바뀌었습니다.")
    return [row for row in rows if not isinstance(row, dict) or
            not (row.get("disabled") is True or row.get("disabledReason"))]


def validate(doc, home):
    counts = {key: len(active(doc, key)) for key in
              ("mcpServers", "hooks", "plugins", "lspServers", "projectInstructions", "skills")}
    if any(counts.values()):
        raise IsolationError("상속 MCP·훅·플러그인·지침·스킬이 남아 있어 Grok 호출을 차단했습니다.")
    permissions = doc.get("permissions", {})
    pins = permissions.get("mcpLockdownSources", [])
    required = str(home / "requirements.toml").casefold()
    if permissions.get("mcpServerAllowlist") != [] or not any(
            isinstance(pin, dict) and str(pin.get("source", "")).casefold() == required
            and pin.get("advisory") is False for pin in pins):
        raise IsolationError("Grok의 전체 MCP 차단 정책이 적용되지 않았습니다.")
    if doc.get("loginPolicy", {}).get("apiKeyAuthDisabled") is not True:
        raise IsolationError("Grok API 키 인증 차단을 확인하지 못했습니다.")
    return counts


@contextmanager
def isolated_session(info, authenticate=False):
    """Reuse the existing login by a temporary hard link; never read/copy its value.

    The link retains the original file's ACL. It is removed in finally, including
    timeout/cancellation. A process crash can leave this private temp link behind;
    no credential is placed in a task artifact or the repository.
    """
    help_result = subprocess.run([*info["cmd"], "--help"], capture_output=True, timeout=20,
                                 env=clean_child_env(), creationflags=no_window_flags())
    help_text = help_result.stdout.decode("utf-8", "replace")
    if help_result.returncode or any(flag not in help_text for flag in REQUIRED_FLAGS):
        raise IsolationError("설치된 Grok CLI에 필요한 제한 옵션이 없습니다.")
    with tempfile.TemporaryDirectory(prefix="ai-studio-grok-text-") as directory:
        root = Path(directory)
        home, cwd = root / "home", root / "input"
        home.mkdir(); cwd.mkdir()
        env = {key: value for key, value in clean_child_env().items()
               if not key.startswith(("GROK_", "XAI_")) and key != "STUDIO_SUPERVISOR_TOKEN"}
        env.update(GROK_HOME=str(home), GROK_DISABLE_AUTOUPDATER="1",
                   GROK_DISABLE_API_KEY_AUTH="1", GROK_MANAGED_MCPS_ENABLED="0",
                   GROK_MANAGED_MCP_GATEWAY_TOOLS_ENABLED="0", GROK_WEB_FETCH="0",
                   GROK_SUBAGENTS="0", GROK_WRITE_FILE="0", GROK_MEMORY="0", GROK_TOOL_SEARCH="0")
        for vendor in ("CLAUDE", "CURSOR"):
            for surface in ("MCPS", "HOOKS", "AGENTS", "RULES", "SKILLS"):
                env[f"GROK_{vendor}_{surface}_ENABLED"] = "0"
        atomic_write_text(home / "config.toml", PROFILE)
        atomic_write_text(home / "requirements.toml", PROFILE)
        discovered = inspect(info, cwd, env)
        skills = sorted({row["name"] for row in discovered.get("skills", [])
                         if isinstance(row, dict) and isinstance(row.get("name"), str)})
        config = PROFILE + "\n[skills]\ndisabled = " + json.dumps(skills) + "\n"
        atomic_write_text(home / "config.toml", config)
        counts = validate(inspect(info, cwd, env), home)
        receipt = {"version": info.get("version"), "active_surfaces": counts,
                   "profile_sha256": hashlib.sha256(config.encode()).hexdigest(),
                   "mcp_lockdown": True, "api_key_auth_disabled": True,
                   "permission": "deny all; dontAsk", "os_filesystem_sandbox": False,
                   "model_input": "supplied text only", "credential_values_read": False}
        link = home / "auth.json"
        if authenticate:
            existing = Path.home() / ".grok" / "auth.json"
            if not existing.is_file() or existing.is_symlink():
                raise IsolationError("기존 Grok 로그인 파일을 안전하게 재사용할 수 없습니다.")
            try:
                os.link(existing, link)
            except OSError as exc:
                raise IsolationError("기존 로그인 파일의 임시 연결을 지원하지 않아 호출하지 않았습니다.") from exc
        try:
            yield cwd, env, receipt
        finally:
            link.unlink(missing_ok=True)


def preflight(info):
    if not info.get("found"):
        return {"ready": False, "reason": "Grok CLI를 찾을 수 없습니다."}
    try:
        with isolated_session(info) as (_, _, receipt):
            return {"ready": True, **receipt, "model_calls": 0}
    except (IsolationError, OSError, subprocess.SubprocessError) as exc:
        return {"ready": False, "reason": str(exc), "model_calls": 0}


def run_text(runtime, spec, should_stop):
    # Import lazily because runtimes owns the common process/result contract.
    from .runtimes import RunResult, classify_error, parse_json_loose, run_process
    if should_stop():
        return RunResult(False, runtime.name, spec.model, None, 0, error_kind="stopped", side_effects="none")
    if spec.sandbox != "read-only" or spec.want_image or spec.images or spec.mcp or spec.web_search:
        return RunResult(False, runtime.name, spec.model, None, 0, error_kind="policy",
                         error="Grok 텍스트는 도구 없는 읽기 전용 입력만 받습니다.", side_effects="none")
    if not spec.model:
        return RunResult(False, runtime.name, "", None, 0, error_kind="model",
                         error="확인한 Grok 모델 ID를 명시해야 합니다.", side_effects="none")
    spec.run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(spec.run_dir / "prompt.md", spec.prompt)
    try:
        with isolated_session(runtime.info, authenticate=True) as (cwd, env, receipt):
            atomic_write_json(spec.run_dir / "isolation.json", receipt)
            prompt = cwd / "request.txt"
            atomic_write_text(prompt, spec.prompt)
            args = [*runtime.info["cmd"], "--prompt-file", str(prompt), "--cwd", str(cwd),
                    "--model", spec.model, "--output-format", "streaming-json",
                    "--tools", "read_file", "--disallowed-tools", "read_file,search_tool,use_tool",
                    "--deny", "*", "--permission-mode", "dontAsk", "--no-subagents",
                    "--disable-web-search", "--max-turns", "1"]
            if spec.output_schema:
                args += ["--json-schema", json.dumps(spec.output_schema, separators=(",", ":"))]
            code, reason, duration = run_process(args, cwd=cwd, env=env, stdin_text="",
                stdout_path=spec.run_dir / "events.jsonl", stderr_path=spec.run_dir / "stderr.txt",
                timeout_s=spec.timeout_s, should_stop=should_stop)
    except (IsolationError, OSError, subprocess.SubprocessError) as exc:
        return RunResult(False, runtime.name, spec.model, None, 0, error_kind="policy",
                         error=str(exc), side_effects="none")
    raw = (spec.run_dir / "events.jsonl").read_text(encoding="utf-8", errors="replace")
    single = parse_json_loose(raw)
    if isinstance(single,dict) and "text" in single and not single.get("type"):
        # --json-schema implies json output on the installed CLI, even if streaming was requested.
        events = [{"type":"text", "data":single.get("text", "")}, {"type":"end", **single}]
        if single.get("is_error"):events.append({"type":"error","message":"Grok schema response failed"})
        if single.get("tool_calls"):events.append({"type":"tool_call"})
        lines = []
    else:
        events, lines = [], raw.splitlines()
    malformed = False
    for line in lines:
        try:
            event = json.loads(line)
            if not isinstance(event, dict): raise ValueError()
            events.append(event)
        except ValueError:
            malformed = True
    end = next((event for event in reversed(events) if event.get("type") == "end"), {})
    text = "".join(str(event.get("data", "")) for event in events if event.get("type") == "text")
    unsafe = any(event.get("type") == "tool_call" or
                 (event.get("type") == "available_commands" and event.get("tools")) for event in events)
    errors = [str(event.get("message", "")) for event in events if event.get("type") == "error"]
    usage = end.get("usage") if isinstance(end.get("usage"), dict) else {}
    known = {key: usage.get(key) if type(usage.get(key)) is int and usage[key] >= 0 else None
             for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    result = RunResult(code == 0 and not reason and bool(end) and not errors and not unsafe and not malformed,
                       runtime.name, spec.model, code, round(duration, 1), final_message=text,
                       usage=known, side_effects="none", structured=parse_json_loose(text) if spec.output_schema else None)
    # Only explicit response metadata, never a requested model or modelUsage key.
    result.provider_model = next((event["model"] for event in events
                                  if event.get("type") in ("usage", "response_metadata")
                                  and isinstance(event.get("model"), str)), None)
    if reason: result.error_kind, result.error = reason, "Grok 텍스트 실행 중단"
    elif unsafe: result.error_kind, result.error = "policy", "예상하지 않은 도구가 노출되어 결과를 차단했습니다."
    elif malformed: result.error_kind, result.error = "schema", "Grok 출력 형식 오류"
    elif not result.ok:
        stderr = (spec.run_dir / "stderr.txt").read_text(encoding="utf-8", errors="replace")[-5000:]
        result.error_kind = classify_error(" ".join(errors) + " " + stderr) or "error"
        result.error = "Grok 텍스트 호출 실패 (로컬 실행 기록 확인)"
    elif spec.output_schema and result.structured is None:
        result.ok, result.error_kind, result.error = False, "schema", "구조화된 Grok 응답을 확인하지 못했습니다."
    atomic_write_text(spec.run_dir / "last_message.md", text)
    return result
