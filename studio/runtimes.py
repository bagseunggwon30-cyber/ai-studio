"""에이전트 실행기: 공식 CLI를 하위 프로세스로 돌린다.

- Codex: `codex exec --json`, 본인 ChatGPT 구독 로그인. 사용자 전역 설정(MCP·플러그인·
  full-access 기본값)은 무시하고, 역할마다 샌드박스를 명시한다.
- Claude Code: `claude -p --output-format json`, 본인 구독 로그인. 읽기 도구만 허용한다.
- Grok: `grok --prompt-file … --output-format json`, 본인 grok.com 로그인 (CEO 요청 E, 2026-09-29). 그림 및 제한된 읽기 전용 텍스트에 쓴다. 그림 도구와 파일 읽기만 허용하고, 승인 우회 플래그는 쓰지 않는다.
- Fake: 테스트·화면 확인용. 사용량을 쓰지 않는다.

API 키나 OAuth 토큰은 읽지도, 전달하지도 않는다. 하위 프로세스 환경에서도 지운다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .util import (
    IS_WINDOWS,
    atomic_write_json,
    clean_child_env,
    kill_tree,
    no_window_flags,
    read_jsonl,
    read_text_tail,
)


@dataclass
class RunSpec:
    run_id: str
    role: str
    prompt: str
    cwd: Path
    run_dir: Path
    sandbox: str = "read-only"
    model: str = ""
    effort: str = ""
    timeout_s: int = 1200
    output_schema: dict | None = None
    web_search: bool = False
    skip_git_check: bool = False
    images: list[Path] = field(default_factory=list)  # 참고 그림 (codex exec -i)
    want_image: bool = False  # 그림 생성: 만들어진 그림 파일을 찾아 돌려준다
    # 장착한 MCP (studio/mcp.py for_role). env에 토큰 값이 있으니 이 객체는 파일·기록에 쓰지 않는다
    mcp: list[dict] = field(default_factory=list)


@dataclass
class RunResult:
    ok: bool
    runtime: str
    model: str
    exit_code: int | None
    duration_s: float
    final_message: str = ""
    structured: dict | None = None
    usage: dict = field(default_factory=dict)
    error_kind: str | None = None  # login | quota | model | timeout | stopped | not_found | error
    error: str = ""
    steps: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)  # 만들어진 그림 (want_image)
    host_skills: list[str] = field(default_factory=list)  # 이 PC 사용자의 개인 Codex 스킬 중 직원이 열어 읽은 것 (회사 스킬이 아님)

    side_effects: str = "unknown"  # Only an adapter may assert that no effects were dispatched.
    provider_model: str | None = None  # Only provider response metadata; never the requested model

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ERROR_LABELS = {
    "login": "로그인 필요",
    "quota": "구독 사용 한도 도달",
    "model": "모델 사용 불가",
    "timeout": "시간 초과",
    "stopped": "중지됨",
    "not_found": "CLI를 찾을 수 없음",
    "schema": "출력 형식 오류",
    "policy": "정책 또는 연결 확인 필요",
    "unknown_outcome": "실행 여부 불확실",
    "error": "실행 오류",
}


def classify_error(text: str) -> str | None:
    low = text.lower()
    if any(s in low for s in ("usage limit", "rate limit", "rate_limit", "too many requests", "quota", "limit reached", "hit your limit", " 429")):
        return "quota"
    if any(s in low for s in ("not logged in", "please log in", "unauthorized", " 401", "authentication", "login required", "token expired", "sign in again")):
        return "login"
    if "model" in low and any(s in low for s in ("not supported", "not found", "does not exist", "unknown model", "not available")):
        return "model"
    return None


def parse_json_loose(text: str) -> dict | None:
    """마지막 메시지에서 JSON 객체를 꺼낸다 (코드 펜스로 감싸져 있어도)."""
    if not text:
        return None
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.S)
    if m:
        s = m.group(1)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if 0 <= start < end:
            try:
                obj = json.loads(s[start : end + 1])
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def run_process(
    args: list[str],
    *,
    cwd: Path,
    stdin_text: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_s: int,
    should_stop: Callable[[], bool],
    env: dict[str, str],
) -> tuple[int | None, str | None, float]:
    """프로세스를 실행하고 끝나기를 기다린다. 중지·시간 초과면 자식까지 모두 종료한다."""
    start = time.monotonic()
    flags = no_window_flags()
    if IS_WINDOWS:
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
        if should_stop():
            return None, "stopped", time.monotonic() - start
        proc = subprocess.Popen(
            args, cwd=str(cwd), stdin=subprocess.PIPE, stdout=out, stderr=err, env=env, creationflags=flags,
            start_new_session=not IS_WINDOWS
        )

        def feed() -> None:
            try:
                assert proc.stdin is not None
                proc.stdin.write(stdin_text.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                pass

        threading.Thread(target=feed, daemon=True).start()
        reason = None
        while proc.poll() is None:
            if should_stop():
                reason = "stopped"
            elif time.monotonic() - start > timeout_s:
                reason = "timeout"
            if reason:
                kill_tree(proc.pid)
                try:
                    proc.wait(15)
                except subprocess.TimeoutExpired:
                    # Do not report completion while the child still owns files.
                    kill_tree(proc.pid)
                    proc.kill()
                    proc.wait()
                break
            time.sleep(0.3)
    return proc.returncode, reason, time.monotonic() - start


def _version_tuple(text: str) -> tuple[int, ...]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(x) for x in m.groups()) if m else (0,)


def _probe_version(cmd: list[str]) -> str:
    try:
        p = subprocess.run(cmd + ["--version"], capture_output=True, timeout=30, creationflags=no_window_flags())
        return (p.stdout or p.stderr).decode("utf-8", "replace").strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


# ---------------------------------------------------------------- Codex

_codex_cache: dict[str, Any] = {}


def find_codex(configured: str = "") -> dict[str, Any]:
    """설치된 Codex CLI 중 가장 새 버전을 고른다.

    npm으로 깔린 CLI가 오래되면 새 모델을 못 쓰므로, Codex 데스크톱 앱에 들어 있는
    최신 CLI도 후보로 본다. studio.toml의 runtimes.codex.path로 고정할 수 있다.
    """
    key = configured or "_auto"
    if key in _codex_cache:
        return _codex_cache[key]
    candidates: list[tuple[list[str], str]] = []
    if configured:
        p = Path(configured)
        cmd = [shutil.which("node") or "node", str(p)] if p.suffix == ".js" else [str(p)]
        candidates.append((cmd, "설정"))
    else:
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for exe in (local / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"):
            candidates.append(([str(exe)], "Codex 앱"))
        npm = Path(os.environ.get("APPDATA", "")) / "npm"
        js = npm / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        if js.exists():
            node = npm / "node.exe" if (npm / "node.exe").exists() else Path(shutil.which("node") or "node")
            candidates.append(([str(node), str(js)], "npm"))
        exe = shutil.which("codex.exe")
        if exe:
            candidates.append(([exe], "PATH"))
    best: dict[str, Any] = {"found": False, "cmd": None, "version": "", "source": "", "candidates": []}
    for cmd, source in candidates:
        version = _probe_version(cmd)
        best["candidates"].append({"path": cmd[-1], "version": version, "source": source})
        if version and (not best["found"] or _version_tuple(version) > _version_tuple(best["version"])):
            best.update(found=True, cmd=cmd, version=version, source=source)
    _codex_cache[key] = best
    return best


def codex_mcp_args(specs: list[dict]) -> tuple[list[str], dict[str, str]]:
    """장착한 MCP를 Codex 설정 덮어쓰기(-c)로 (--ignore-user-config 그대로, 사용자 설정은 읽지 않는다).

    토큰 값은 명령줄에 넣지 않는다: 환경변수로 Codex에 주고 설정에는 이름만(env_vars·bearer_token_env_var),
    Codex가 돌리는 셸 명령의 환경에서는 뺀다(shell_environment_policy.exclude). 돌려주는 것: (인자, 넣을 환경변수)."""
    args: list[str] = []
    env: dict[str, str] = {}
    for s in specs:
        key = f"mcp_servers.{s['name']}"
        if s["transport"] == "http":
            args += ["-c", f"{key}.url={json.dumps(s['url'])}"]
            if s.get("bearer_key") and s["env"].get(s["bearer_key"]):
                args += ["-c", f"{key}.bearer_token_env_var={json.dumps(s['bearer_key'])}"]
        else:
            args += ["-c", f"{key}.command={json.dumps(s['command'])}", "-c", f"{key}.args={json.dumps(list(s['args']))}"]
            if s["env"]:
                args += ["-c", f"{key}.env_vars={json.dumps(sorted(s['env']))}"]
        args += ["-c", f"{key}.startup_timeout_sec=60", "-c", f"{key}.tool_timeout_sec=180"]
        env.update(s["env"])
    if env:
        args += ["-c", f"shell_environment_policy.exclude={json.dumps(sorted(env))}"]
    return args, env


def claude_mcp_config(specs: list[dict]) -> dict:
    """장착한 MCP를 Claude Code --mcp-config JSON으로 (토큰이 들어가므로 실행이 끝나면 파일을 지운다)."""
    servers: dict[str, dict] = {}
    for s in specs:
        if s["transport"] == "http":
            item: dict = {"type": "http", "url": s["url"]}
            if s.get("bearer_key") and s["env"].get(s["bearer_key"]):
                item["headers"] = {"Authorization": f"Bearer {s['env'][s['bearer_key']]}"}
        else:
            item = {"type": "stdio", "command": s["command"], "args": list(s["args"]), "env": dict(s["env"])}
        servers[s["name"]] = item
    return {"mcpServers": servers}


# 실행기가 넘기는 옵션. doctor가 설치된 CLI의 `--help`에 이 옵션이 아직 있는지 본다: Codex·Claude는 자동으로 업데이트되며
# 옵션이 바뀔 수 있고, 그러면 첫 진짜 실행이 조용히 실패하기 때문이다. 실행기 코드에 옵션을 더하면 여기에도 더한다.
CODEX_FLAGS = ("--json", "--color", "--ephemeral", "--ignore-user-config", "-s", "-C", "-o", "-m", "-c", "--output-schema",
               "--skip-git-repo-check", "-i")
CLAUDE_FLAGS = ("-p", "--output-format", "--no-session-persistence", "--restricted", "--strict-mcp-config", "--tools",
                "--permission-prompts", "--model", "--effort", "--json-schema", "--mcp-config")


def missing_flags(help_text: str, flags: tuple[str, ...]) -> list[str]:
    """help_text에 없는 옵션. 짧은 옵션(-s)이 다른 글자에 섞여 있는 것으로 잘못 찾히지 않게 앞뒤가 옵션 글자가 아닌 것만 센다."""
    return [f for f in flags if not re.search(rf"(?<![\w-]){re.escape(f)}(?![\w-])", help_text)]


class CodexRuntime:
    name = "codex"

    def __init__(self, rcfg: dict):
        self.rcfg = rcfg
        self.info = find_codex(str(rcfg.get("path", "") or ""))

    def run(self, spec: RunSpec, should_stop: Callable[[], bool]) -> RunResult:
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "prompt.md").write_text(spec.prompt, encoding="utf-8")
        if not self.info["found"]:
            return RunResult(False, self.name, spec.model, None, 0.0, error_kind="not_found", error="Codex CLI를 찾을 수 없습니다.")
        last_path = spec.run_dir / "last_message.md"
        args = [*self.info["cmd"], "exec", "--json", "--color", "never", "--ephemeral"]
        if self.rcfg.get("ignore_user_config", True):
            args.append("--ignore-user-config")
        args += ["-s", spec.sandbox, "-C", str(spec.cwd), "-o", str(last_path)]
        if spec.model:
            args += ["-m", spec.model]
        if spec.effort:
            args += ["-c", f'model_reasoning_effort="{spec.effort}"']
        for kv in self.rcfg.get("extra_config", []):
            args += ["-c", str(kv)]
        if spec.web_search:
            args += ["-c", 'web_search="live"']
        if spec.output_schema:
            schema_path = spec.run_dir / "output_schema.json"
            atomic_write_json(schema_path, spec.output_schema)
            args += ["--output-schema", str(schema_path)]
        if spec.skip_git_check:
            args.append("--skip-git-repo-check")
        for img in spec.images:
            args += ["-i", str(img)]
        if self.rcfg.get("block_host_skills", True):  # 사장님 개인 스킬은 직원에게 보이지 않게 (회사 스킬 효과를 깨끗하게 재기)
            args += codex_skill_block_args(host_skill_files())
        mcp_args, mcp_env = codex_mcp_args(spec.mcp)
        args += mcp_args
        args.append("-")

        events_path = spec.run_dir / "events.jsonl"
        stderr_path = spec.run_dir / "stderr.txt"
        code, reason, duration = run_process(
            args,
            cwd=spec.cwd,
            stdin_text=spec.prompt,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_s=spec.timeout_s,
            should_stop=should_stop,
            env=clean_child_env(mcp_env),
        )
        events = read_jsonl(events_path)
        steps, messages, errors, warnings, usage = summarize_codex_events(events)
        final = last_path.read_text(encoding="utf-8", errors="replace").strip() if last_path.exists() else ""
        if not final and messages:
            final = messages[-1]
        result = RunResult(
            ok=(code == 0 and not reason and not errors),
            runtime=self.name,
            model=spec.model,
            exit_code=code,
            duration_s=round(duration, 1),
            final_message=final,
            usage=usage,
            steps=steps,
            warnings=warnings[:10],
            host_skills=host_skills_read(events),
        )
        result.provider_model = next((e.get("model") for e in events if e.get("type") in ("session.created", "session_meta", "response.completed") and isinstance(e.get("model"),str)),None)
        if reason:
            result.ok, result.error_kind = False, reason
            result.error = ERROR_LABELS[reason]
        elif errors or code != 0:
            text = "\n".join(errors) + "\n" + read_text_tail(stderr_path, 4000)
            result.ok = False
            result.error_kind = classify_error(text) or "error"
            result.error = (errors[-1] if errors else text.strip())[:1000]
        if result.ok and spec.output_schema:
            result.structured = parse_json_loose(final)
            if result.structured is None:
                result.ok, result.error_kind, result.error = False, "schema", "구조화된 JSON 응답을 읽지 못했습니다."
        if spec.want_image and not reason:
            # Codex는 그림을 ~/.codex/generated_images/<thread_id>/에 둔다. "결과가 없다"고 답해도 파일은 있을 때가 많아 폴더를 직접 본다.
            result.images = generated_images(read_jsonl(events_path))
            if result.images:
                result.ok, result.error_kind, result.error = True, None, ""
            elif result.ok:
                result.ok, result.error_kind, result.error = False, "error", "그림이 만들어지지 않았습니다."
        return result


def generated_images(events: list[dict]) -> list[str]:
    """그림 생성 실행이 만든 PNG (새 것부터). 로그인 파일은 보지 않는다 — 그림 폴더만."""
    thread = next((str(e.get("thread_id")) for e in events if e.get("type") == "thread.started" and e.get("thread_id")), "")
    if not re.fullmatch(r"[0-9A-Za-z-]{8,80}", thread):
        return []
    folder = Path.home() / ".codex" / "generated_images" / thread
    if not folder.is_dir():
        return []
    return [str(p) for p in sorted(folder.glob("*.png"), key=lambda q: q.stat().st_mtime, reverse=True)]


# Codex는 `--ignore-user-config`여도 이 PC의 개인 스킬 폴더(~/.codex/skills, ~/.agents/skills)를 찾아 직원에게 보여 준다 (2026-09-29 진짜 실행에서 확인:
# 90개가 보였고 솔은 coding-standards·verification-loop, 루나는 deep-research를 열어 읽었다). 막지는 않되, 어떤 것을 읽었는지 기록에 남긴다.
HOST_SKILL_RE = re.compile(r"[\\/]\.(?:codex|agents|cli-jaw)[\\/]+skills[\\/]+(?:\.system[\\/]+)?([^\\/'\"\s`]+)[\\/]+SKILL\.md", re.IGNORECASE)
BLOCK_ARG_MAX = 20_000  # 막을 스킬 목록 인자 최대 길이 (윈도우 명령줄 한도 32K 안쪽)


def host_skill_files(home: Path | None = None, codex_home: Path | None = None) -> list[str]:
    """사장님 개인 스킬 파일 — `--ignore-user-config`로도 Codex가 직원에게 보여 주는 것 (CEO 결정 2026-09-29: 막는다).

    `$CODEX_HOME/skills`(기본 ~/.codex/skills)와 `~/.agents/skills`(바로가기면 실제 폴더, 이 PC는 ~/.cli-jaw/skills) 아래의
    SKILL.md 경로만 모은다 (폴더·파일 이름만 보고 내용은 읽지 않는다). 점으로 시작하는 폴더(`.system` = 코덱스 기본 스킬)와
    플러그인 스킬(~/.codex/plugins)은 코덱스에 원래 들어 있는 것이라 그대로 둔다."""
    home = home or Path.home()
    codex_home = codex_home or Path(os.environ.get("CODEX_HOME") or home / ".codex")
    out: set[str] = set()
    for root in (codex_home / "skills", home / ".agents" / "skills"):
        try:
            real = root.resolve()
            if not real.is_dir():
                continue
            for f in real.rglob("SKILL.md"):
                rel = f.relative_to(real)
                if not any(part.startswith(".") for part in rel.parts[:-1]):
                    out.add(f.as_posix())
        except OSError:
            continue
    return sorted(out)[:500]


def codex_skill_block_args(paths: list[str]) -> list[str]:
    """개인 스킬을 끄는 Codex 설정 (`skills.config`의 경로별 enabled=false — 이름으로 끄면 같은 이름의 코덱스 기본 스킬까지 꺼진다).
    너무 길면(아주 많은 스킬) 명령줄 한도를 넘지 않게 앞에서부터 담을 수 있는 만큼만."""
    entries: list[str] = []
    size = 0
    for p in paths:
        e = f"{{path={json.dumps(p)}, enabled=false}}"
        if size + len(e) + 2 > BLOCK_ARG_MAX:
            break
        entries.append(e)
        size += len(e) + 2
    return ["-c", f"skills.config=[{', '.join(entries)}]"] if entries else []


def host_skills_read(events: list[dict]) -> list[str]:
    """직원이 명령으로 열어 읽은 개인 스킬 이름 (처음 읽은 순서, 중복 없음). 이름만 남기고 내용은 보지 않는다."""
    found: list[str] = []
    for e in events:
        item = e.get("item") if isinstance(e, dict) else None
        if isinstance(item, dict) and item.get("type") == "command_execution":
            for name in HOST_SKILL_RE.findall(str(item.get("command", ""))):
                if name not in found:
                    found.append(name)
    return found


def summarize_codex_events(events: list[dict]) -> tuple[list[dict], list[str], list[str], list[str], dict]:
    steps: list[dict] = []
    messages: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    usage: dict = {}
    for ev in events:
        t = ev.get("type")
        if t == "item.completed":
            item = ev.get("item") or {}
            it = item.get("type")
            if it == "agent_message":
                text = str(item.get("text", ""))
                messages.append(text)
                steps.append({"kind": "message", "text": text[:600]})
            elif it == "command_execution":
                steps.append({"kind": "command", "text": _short_command(str(item.get("command", ""))), "exit": item.get("exit_code")})
            elif it == "file_change":
                paths = [str(c.get("path", "")) for c in item.get("changes", []) or []]
                steps.append({"kind": "files", "text": ", ".join(Path(p).name for p in paths)[:400]})
            elif it == "web_search":
                steps.append({"kind": "search", "text": str(item.get("query", ""))[:300]})
            elif it == "error":
                warnings.append(str(item.get("message", ""))[:300])
        elif t == "turn.completed":
            usage = ev.get("usage") or {}
        elif t == "turn.failed":
            errors.append(str((ev.get("error") or {}).get("message", "turn failed")))
        elif t == "error":
            errors.append(str(ev.get("message", "error")))
    return steps, messages, errors, warnings, usage


def _short_command(cmd: str) -> str:
    """'...pwsh.exe -Command "실제 명령"' 형태에서 실제 명령만 보여준다."""
    m = re.search(r'-Command\s+"(.*)"\s*$', cmd, re.S)
    text = m.group(1) if m else cmd
    return text.replace("\\\\", "\\")[:300]


# ---------------------------------------------------------------- Claude Code

_claude_cache: dict[str, Any] = {}


def find_claude(configured: str = "") -> dict[str, Any]:
    key = configured or "_auto"
    if key in _claude_cache:
        return _claude_cache[key]
    paths: list[Path] = []
    if configured:
        paths.append(Path(configured))
    else:
        npm = Path(os.environ.get("APPDATA", "")) / "npm"
        paths.append(npm / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe")
        exe = shutil.which("claude.exe")
        if exe:
            paths.append(Path(exe))
        paths.append(Path.home() / ".local" / "bin" / "claude.exe")
    info: dict[str, Any] = {"found": False, "cmd": None, "version": "", "source": ""}
    for p in paths:
        if p.exists():
            version = _probe_version([str(p)])
            if version:
                info.update(found=True, cmd=[str(p)], version=version, source=str(p.parent))
                break
    _claude_cache[key] = info
    return info


class ClaudeRuntime:
    name = "claude"

    def __init__(self, rcfg: dict):
        self.rcfg = rcfg
        self.info = find_claude(str(rcfg.get("path", "") or ""))

    def run(self, spec: RunSpec, should_stop: Callable[[], bool]) -> RunResult:
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "prompt.md").write_text(spec.prompt, encoding="utf-8")
        if not self.info["found"]:
            return RunResult(False, self.name, spec.model, None, 0.0, error_kind="not_found", error="Claude Code CLI를 찾을 수 없습니다.")
        tools = str(self.rcfg.get("tools", "Read,Grep,Glob"))
        args = [
            *self.info["cmd"],
            "-p",
            "--output-format", "json",
            "--no-session-persistence",
            "--restricted",
            "--strict-mcp-config",
            "--tools", tools,
            "--permission-prompts", "none",
        ]
        if spec.model:
            args += ["--model", spec.model]
        if spec.effort:
            args += ["--effort", spec.effort]
        if spec.output_schema:
            args += ["--json-schema", json.dumps(spec.output_schema, ensure_ascii=False, separators=(",", ":"))]
        mcp_file = None
        if spec.mcp:  # 장착한 MCP만 (--strict-mcp-config라 사용자 설정의 MCP는 안 붙는다). 도구는 그 서버 것만 허용
            fd, mcp_file = tempfile.mkstemp(prefix="ais-mcp-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(claude_mcp_config(spec.mcp), f, ensure_ascii=False)
            args += ["--mcp-config", mcp_file, "--allowedTools", ",".join(f"mcp__{s['name']}" for s in spec.mcp)]
        out_path = spec.run_dir / "result.json"
        stderr_path = spec.run_dir / "stderr.txt"
        try:
            code, reason, duration = run_process(
                args,
                cwd=spec.cwd,
                stdin_text=spec.prompt,
                stdout_path=out_path,
                stderr_path=stderr_path,
                timeout_s=spec.timeout_s,
                should_stop=should_stop,
                env=clean_child_env(),
            )
        finally:
            if mcp_file:
                try:
                    os.remove(mcp_file)  # 토큰이 든 임시 설정은 남기지 않는다
                except OSError:
                    pass
        raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
        obj = parse_json_loose(raw) or {}
        final = str(obj.get("result", "") or "")
        (spec.run_dir / "last_message.md").write_text(final, encoding="utf-8")
        usage_raw = obj.get("usage") or {}
        usage = {
            "input_tokens": (usage_raw.get("input_tokens") or 0)
            + (usage_raw.get("cache_creation_input_tokens") or 0)
            + (usage_raw.get("cache_read_input_tokens") or 0),
            "output_tokens": usage_raw.get("output_tokens"),
            "turns": obj.get("num_turns"),
            # 구독 사용자는 이 금액이 청구되지 않는다. CLI가 내는 추정치일 뿐이다.
            "est_cost_usd_not_billed": obj.get("total_cost_usd"),
        }
        result = RunResult(
            ok=(code == 0 and not reason and not obj.get("is_error", False) and bool(obj)),
            runtime=self.name,
            model=spec.model or "기본",
            exit_code=code,
            duration_s=round(duration, 1),
            final_message=final,
            usage=usage,
            steps=[{"kind": "message", "text": final[:600]}] if final else [],
        )
        if reason:
            result.ok, result.error_kind, result.error = False, reason, ERROR_LABELS[reason]
        elif not result.ok:
            text = final + "\n" + read_text_tail(stderr_path, 4000) + "\n" + raw[-2000:]
            result.error_kind = classify_error(text) or "error"
            result.error = (final or read_text_tail(stderr_path, 1000) or "Claude 실행 실패").strip()[:1000]
        if result.ok and spec.output_schema:
            structured = obj.get("structured_output")
            result.structured = structured if isinstance(structured, dict) else parse_json_loose(final)
            if result.structured is None:
                result.ok, result.error_kind, result.error = False, "schema", "구조화된 JSON 응답을 읽지 못했습니다."
        return result


# ---------------------------------------------------------------- Grok (xAI Grok Build CLI)
# 확인한 것 (2026-09-29, grok 1.0.40): 비대화식은 --prompt-file/-p, 결과는 --output-format json의 text·sessionId.
# 그림 도구(image_gen)는 파일을 작업 폴더가 아니라 ~/.grok/sessions/<작업 폴더를 %인코딩한 이름>/<sessionId>/images/<n>.jpg에
# 둔다 (정사각형 1024x1024 JPG). 그래서 sessionId로 그 images 폴더만 찾는다 — 로그인 파일(auth.json)은 보지 않는다.
# 윈도우에서는 그록 샌드박스가 강제되지 않으므로(리눅스·맥만) 도구 허용 목록(--tools)으로 막는다.
# 참고 그림(EDIT)은 작업 폴더에 ref-1.png… 로 복사해 두고 프롬프트에 이름을 적는다 (아직 진짜로 시험하지 않음: 사용량이 없어서).

GROK_IMAGE_TOOLS = "image_gen,image_edit,read_file"
GROK_SESSION_RE = re.compile(r"^[0-9a-fA-F-]{16,64}$")
_grok_cache: dict[str, Any] = {}


def find_grok(configured: str = "") -> dict[str, Any]:
    """설치된 Grok CLI (공식 설치 위치 ~/.grok/bin/grok.exe 또는 PATH의 grok.exe). 다른 이름의 래퍼는 쓰지 않는다."""
    key = configured or "_auto"
    if key in _grok_cache:
        return _grok_cache[key]
    candidates: list[tuple[list[str], str]] = []
    if configured:
        candidates.append(([configured], "설정"))
    else:
        home = Path.home() / ".grok" / "bin" / ("grok.exe" if IS_WINDOWS else "grok")
        if home.is_file():
            candidates.append(([str(home)], "grok 설치"))
        exe = shutil.which("grok.exe" if IS_WINDOWS else "grok")
        if exe and Path(exe).suffix.lower() in ("", ".exe"):
            candidates.append(([exe], "PATH"))
    best: dict[str, Any] = {"found": False, "cmd": None, "version": "", "source": ""}
    for cmd, source in candidates:
        version = _probe_version(cmd)
        if version.lower().startswith("grok"):
            best.update(found=True, cmd=cmd, version=version, source=source)
            break
    _grok_cache[key] = best
    return best


def grok_login(info: dict[str, Any]) -> bool:
    """grok models가 로그인 상태를 알려 준다 ('You are logged in …', 안 되면 종료 코드 5). 토큰은 보지 않는다."""
    if not info.get("found"):
        return False
    try:
        p = subprocess.run([*info["cmd"], "models"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=30, env=clean_child_env(), creationflags=no_window_flags())
    except (OSError, subprocess.SubprocessError):
        return False
    text = (p.stdout + p.stderr).lower()
    return p.returncode == 0 and "logged in" in text and not any(v in text for v in ("not logged in", "not authenticated", "logged out"))


class GrokRuntime:
    name = "grok"

    def __init__(self, rcfg: dict):
        self.rcfg = rcfg
        self.info = find_grok(str(rcfg.get("path", "") or ""))
        # 테스트에서 바꿀 수 있게 (진짜는 ~/.grok/sessions)
        self.sessions = Path(rcfg.get("sessions_dir") or Path.home() / ".grok" / "sessions")

    def run(self, spec: RunSpec, should_stop: Callable[[], bool]) -> RunResult:
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        if not self.info["found"]:
            (spec.run_dir / "prompt.md").write_text(spec.prompt, encoding="utf-8")
            return RunResult(False, self.name, spec.model, None, 0.0, error_kind="not_found", error="Grok CLI를 찾을 수 없습니다.")
        if not spec.want_image:
            (spec.run_dir / "prompt.md").write_text(spec.prompt, encoding="utf-8")
            return RunResult(False, self.name, spec.model, None, 0.0, error_kind="error", error="Grok은 아직 그림 그리기에만 씁니다.")
        # 작업 폴더: 참고 그림을 ref-1.png… 로 복사한다 (그록이 이 폴더 안에서만 일하게)
        work = spec.run_dir / "grok"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        refs = []
        for i, img in enumerate(spec.images, start=1):
            name = f"ref-{i}{Path(img).suffix.lower() or '.png'}"
            shutil.copyfile(img, work / name)
            refs.append(name)
        order = ["FIRST", "SECOND", "THIRD", "FOURTH"]
        note = ""
        if refs:
            note = "\n\nThe attached input images are files in the current folder: " + ", ".join(
                f"{name} ({order[i] if i < len(order) else f'#{i + 1}'})" for i, name in enumerate(refs)
            ) + ". Use your image_edit tool with them as the input reference images. Produce exactly one final image."
        prompt = spec.prompt + note
        prompt_path = spec.run_dir / "prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        args = [*self.info["cmd"], "--prompt-file", str(prompt_path), "--output-format", "json", "--cwd", str(work),
                "--tools", str(self.rcfg.get("tools", GROK_IMAGE_TOOLS)), "--no-auto-update"]
        if spec.model:
            args += ["-m", spec.model]
        out_path = spec.run_dir / "result.json"
        stderr_path = spec.run_dir / "stderr.txt"
        code, reason, duration = run_process(
            args, cwd=work, stdin_text="", stdout_path=out_path, stderr_path=stderr_path,
            timeout_s=spec.timeout_s, should_stop=should_stop, env=clean_child_env(),
        )
        raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
        obj = parse_json_loose(raw) or {}
        final = str(obj.get("text", "") or "")
        (spec.run_dir / "last_message.md").write_text(final, encoding="utf-8")
        usage_raw = obj.get("usage") or {}
        result = RunResult(
            ok=(code == 0 and not reason and bool(obj)),
            runtime=self.name,
            model=spec.model or "기본",
            exit_code=code,
            duration_s=round(duration, 1),
            final_message=final,
            usage={"input_tokens": usage_raw.get("input_tokens"), "output_tokens": usage_raw.get("output_tokens"),
                   "turns": obj.get("num_turns")},
            steps=[{"kind": "message", "text": final[:600]}] if final else [],
        )
        if reason:
            result.ok, result.error_kind, result.error = False, reason, ERROR_LABELS[reason]
            return result
        if not result.ok:
            text = final + "\n" + read_text_tail(stderr_path, 4000) + "\n" + raw[-2000:]
            result.error_kind = classify_error(text) or ("login" if code == 5 else "error")
            result.error = (final or read_text_tail(stderr_path, 1000) or "Grok 실행 실패").strip()[:1000]
            return result
        result.provider_model = obj.get("model") if isinstance(obj.get("model"), str) else None
        result.images = self.session_images(str(obj.get("sessionId", "")))
        if not result.images:
            result.ok, result.error_kind, result.error = False, "error", "그림이 만들어지지 않았습니다."
        return result

    def session_images(self, session: str) -> list[str]:
        """그 세션의 images 폴더에 생긴 그림 (새 것부터). 세션 번호 모양이 아니면 찾지 않는다."""
        if not GROK_SESSION_RE.match(session) or not self.sessions.is_dir():
            return []
        found: list[Path] = []
        for folder in self.sessions.glob(f"*/{session}/images"):
            found += [p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        return [str(p) for p in sorted(found, key=lambda q: q.stat().st_mtime, reverse=True)]


# ---------------------------------------------------------------- Fake (테스트용)

Behavior = Callable[[RunSpec], dict]


class GrokTextRuntime:
    """Grok text over the installed CLI and existing subscription login."""
    name = "grok_text"

    def __init__(self, rcfg):
        self.rcfg = rcfg
        self.info = find_grok(str(rcfg.get("path", "") or ""))

    def preflight(self):
        from .grok_text import preflight
        return preflight(self.info)

    def run(self, spec, should_stop):
        if not self.info.get("found"):
            return RunResult(False,self.name,spec.model,None,0,error_kind="not_found",error="Grok CLI 연결을 찾을 수 없습니다.",side_effects="none")
        from .grok_text import run_text
        return run_text(self,spec,should_stop)


class FakeRuntime:
    """실제 모델을 부르지 않는 실행기. behavior(spec)가 돌려준 대로 파일을 쓰고 응답한다."""

    name = "fake"

    def __init__(self, behavior: Behavior | None = None):
        self.behavior = behavior or default_fake_behavior
        self.info = {"found": True, "cmd": ["fake"], "version": "fake", "source": "test"}

    def run(self, spec: RunSpec, should_stop: Callable[[], bool]) -> RunResult:
        spec.run_dir.mkdir(parents=True, exist_ok=True)
        (spec.run_dir / "prompt.md").write_text(spec.prompt, encoding="utf-8")
        t0 = time.monotonic()
        out = self.behavior(spec) or {}
        delay = float(out.get("delay", 0))
        while delay > 0:
            if should_stop():
                return RunResult(False, self.name, spec.model, None, time.monotonic() - t0, error_kind="stopped", error="중지됨",side_effects="none")
            time.sleep(min(0.1, delay))
            delay -= 0.1
        for rel, content in (out.get("files") or {}).items():
            path = spec.cwd / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        message = str(out.get("message", "완료"))
        (spec.run_dir / "last_message.md").write_text(message, encoding="utf-8")
        error_kind = out.get("error_kind")
        return RunResult(
            ok=not error_kind,
            runtime=self.name,
            model=spec.model or "fake",
            exit_code=0 if not error_kind else 1,
            duration_s=round(time.monotonic() - t0, 2),
            final_message=message,
            structured=out.get("structured"),
            usage={"input_tokens": 0, "output_tokens": 0},
            error_kind=error_kind,
            error=ERROR_LABELS.get(error_kind, "") if error_kind else "",
            steps=[{"kind": "message", "text": message[:600]}],
            images=[str(x) for x in out.get("images") or []],
            side_effects="none" if not out.get("files") and not out.get("images") else "local",
        )


_FAKE_SKILL_RE = re.compile(r"^## .+ \(`([a-z0-9-]+)`\)\n\n언제 쓰나: .*\n\n(?!\(본문은)", re.M)


def _fake_skills_used(prompt: str) -> list[str]:
    """가짜 실행기가 '따랐다'고 알릴 스킬: 프롬프트에 본문까지 붙은 배운 스킬 (진짜 직원처럼 이름으로 알린다)."""
    block = prompt.split("# 배운 스킬", 1)
    if len(block) != 2:
        return []
    # 스킬 구간은 다음 큰 구획(`# …`)에서 끝난다. 코드 블록 안의 `# 주석` 줄에서는 끝나지 않는다.
    kept, fence = [], False
    for line in block[1].split("\n"):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence and line.startswith("# "):
            break
        kept.append(line)
    return _FAKE_SKILL_RE.findall("\n".join(kept))


def _with_skills(out: dict, spec: RunSpec) -> dict:
    """기획·리뷰는 JSON의 skills_used로, 개발·리서치는 보고 마지막 줄로 따른 스킬을 알린다 (배운 스킬이 붙은 일만)."""
    used = _fake_skills_used(spec.prompt)
    if isinstance(out.get("structured"), dict):
        out["structured"]["skills_used"] = used
    elif "# 배운 스킬" in spec.prompt:
        out["message"] = f"{out.get('message', '')}\n\n사용한 스킬: {', '.join(used) or '없음'}"
    return out


def default_fake_behavior(spec: RunSpec) -> dict:
    """가짜 실행기 기본 동작 (_fake_behavior). 스킬 공부·회고도 진짜처럼 따른 스킬을 skills_used로 알린다."""
    out = _fake_behavior(spec)
    if spec.run_id.endswith(("-retro", "-skill")) and isinstance(out.get("structured"), dict):
        out["structured"].setdefault("skills_used", _fake_skills_used(spec.prompt))
    return out


def _fake_behavior(spec: RunSpec) -> dict:
    """화면 확인용 기본 동작: 기획은 작업 2개를 제안하고, 개발은 메모 파일을 쓰고, 리뷰는 승인한다.
    스킬 공부(누가 하든)는 짧은 스킬 하나를 정리해 온다. 회고는 메모 스킬을 배운 직원이면 그 스킬을 고쳐 오고,
    아니면 새 스킬을 만든다. 그림 생성(의상·캐릭터 제조)은 그림을 새로 그리지 않고 참고 그림(지금 모습)을 그대로 돌려준다.
    연습용 회사(--fake)에서는 엔진(`Engine._draw`)이 그 복사본의 옷 색을 돌려 새 옷처럼 보이게 한다."""
    if spec.want_image:
        ref = Path(spec.images[0]) if spec.images else None
        return {"delay": 1.0, "message": "(가짜 실행기) 그림을 그렸습니다.", "images": [str(ref)] if ref else []}
    if spec.run_id.endswith("-retro"):
        if "`memo-writing`" in spec.prompt:
            return {
                "delay": 1.5,
                "message": "메모 스킬을 고쳤습니다.",
                "structured": {
                    "action": "update", "target": "memo-writing",
                    "reason": "(가짜 실행기) 메모를 한 번에 통과하지 못해, 올리기 전에 확인할 것을 스킬에 더했어요.",
                    "change": "올리기 전 확인 순서를 더함",
                    "name": "memo-writing", "title": "메모 정리 요령", "scope": "all", "kinds": ["build", "research"],
                    "description": "docs/ 아래에 작업 메모를 쓸 때 쓴다. (가짜 실행기)",
                    "body": "# 메모 정리 요령\n\n1. 메모는 docs/ 아래에 한 주제씩 쓴다.\n2. 맨 위에 한 줄 요약을 둔다.\n3. 확인하지 못한 내용은 '확인 필요'라고 적는다.\n4. 올리기 전에 수용 기준을 하나씩 다시 읽고 맞는지 확인한다.\n",
                },
            }
        return {
            "delay": 1.5,
            "message": "돌아보고 스킬을 만들었습니다.",
            "structured": {
                "action": "new", "target": "",
                "reason": "(가짜 실행기) 한 번에 통과하지 못한 원인을 다음에 피하려고 정리했어요.",
                "change": "",
                "name": "check-before-submit", "title": "올리기 전 확인", "scope": "all", "kinds": [],
                "description": "작업을 끝내고 결재에 올리기 전에 쓴다. (가짜 실행기)",
                "body": "# 올리기 전 확인\n\n1. 수용 기준을 하나씩 다시 읽는다.\n2. CEO 메모가 있으면 빠짐없이 반영했는지 본다.\n3. 확인하지 못한 것은 보고에 '확인 필요'로 적는다.\n",
            },
        }
    if spec.run_id.endswith("-skill") and "## 고칠 스킬: `memo-writing`" in spec.prompt:
        return {
            "delay": 1.5,
            "message": "메모 스킬을 고쳤습니다.",
            "structured": {
                "action": "update", "target": "memo-writing",
                "reason": "(가짜 실행기) 예시가 없어 처음 보는 직원이 따라 하기 어려웠어요.",
                "change": "예시 메모를 더함",
                "name": "memo-writing", "title": "메모 정리 요령", "scope": "all", "kinds": ["build", "research"],
                "description": "docs/ 아래에 작업 메모를 쓸 때 쓴다. (가짜 실행기)",
                "body": "# 메모 정리 요령\n\n1. 메모는 docs/ 아래에 한 주제씩 쓴다.\n2. 맨 위에 한 줄 요약을 둔다.\n3. 확인하지 못한 내용은 '확인 필요'라고 적는다.\n4. 올리기 전에 수용 기준을 하나씩 다시 읽고 맞는지 확인한다.\n\n## 예시\n\n```\n# 저장 기능 메모\n요약: 저장은 user:// 아래 JSON 한 파일.\n- 확인 필요: 모바일 경로\n```\n",
            },
        }
    if spec.run_id.endswith("-skill"):
        return {
            "delay": 1.5,
            "message": "스킬을 정리했습니다.",
            "structured": {
                "name": "memo-writing",
                "title": "메모 정리 요령",
                "scope": "all",
                "kinds": ["build", "research"],
                "description": "docs/ 아래에 작업 메모를 쓸 때 쓴다. (가짜 실행기)",
                "body": "# 메모 정리 요령\n\n1. 메모는 docs/ 아래에 한 주제씩 쓴다.\n2. 맨 위에 한 줄 요약을 둔다.\n3. 확인하지 못한 내용은 '확인 필요'라고 적는다.\n",
            },
        }
    if "-tool" in spec.run_id:  # MCP 만들기: 폴더 안 파일 개수·줄 수를 세는 작은 도구 (읽기만)
        return _with_skills({"delay": 1.5, "message": "도구를 만들었습니다.", "structured": {
            "name": "file-stats", "title": "파일 세기", "description": "프로젝트 폴더의 파일 종류별 개수와 줄 수를 알려 줘요. 읽기만 해요. (가짜 실행기)",
            "code": FAKE_TOOL_CODE, "tools": [{"name": "count_files", "description": "파일 종류별 개수·줄 수"}],
            "reason": "(가짜 실행기) 작업 전에 프로젝트 크기를 빨리 보려고 만들었어요.", "change": ""}}, spec)
    if spec.role == "producer":
        return _with_skills({
            "delay": 1.0,
            "message": "기획안을 만들었습니다.",
            "structured": {
                "summary": "(가짜 실행기) 지시를 작업 2개로 나눴습니다.",
                "tasks": [
                    {"title": "메모 문서 작성", "brief": "docs/notes.md에 메모를 남긴다.", "acceptance": ["docs/notes.md가 있다"], "allowed_paths": ["docs/**"], "depends_on": [], "kind": "build", "difficulty": 1},
                    {"title": "메모 보강", "brief": "메모에 내용을 덧붙인다.", "acceptance": ["메모가 두 줄 이상이다"], "allowed_paths": ["docs/**"], "depends_on": [0], "kind": "build", "difficulty": 2},
                    {"title": "자료 조사", "brief": "참고 자료를 찾아 보고서로 쓴다.", "acceptance": ["출처가 있다"], "allowed_paths": ["reports/**"], "depends_on": [], "kind": "research", "difficulty": 2},
                ],
                "risks": [],
                "questions": [],
            },
        }, spec)
    if spec.role == "reviewer":
        return _with_skills({"delay": 0.5, "message": "승인", "structured": {"verdict": "approve", "summary": "(가짜 실행기) 문제 없음", "findings": []}}, spec)
    if spec.role == "analyst":
        return _with_skills({"delay": 2.0, "message": "(가짜 실행기) 보고서를 썼습니다.", "files": {f"reports/fake-{spec.run_id[-12:-7]}.md": FAKE_REPORT}}, spec)
    return _with_skills({"delay": 2.0, "message": "(가짜 실행기) 메모를 작성했습니다.", "files": {f"docs/fake-{spec.run_id[-6:]}.md": "# 가짜 실행기 메모\n"}}, spec)


FAKE_TOOL_CODE = '''import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_base import Server, ToolError, setup_stdio

srv = Server("file-stats", "1.0", "프로젝트 폴더의 파일 종류별 개수와 줄 수를 알려 준다. 읽기만 한다.")


@srv.tool("count_files", "지금 폴더(또는 그 안의 하위 폴더)의 파일 종류별 개수와 줄 수를 센다.",
          {"folder": {"type": "string", "description": "지금 폴더 기준 하위 폴더 (비우면 전체)"}})
def count_files(folder: str = "") -> str:
    root = Path.cwd().resolve()
    base = (root / folder).resolve()
    if root != base and root not in base.parents:
        raise ToolError("프로젝트 폴더 밖은 볼 수 없습니다.")
    if not base.is_dir():
        raise ToolError("그런 폴더가 없습니다.")
    count, lines = Counter(), Counter()
    for f in base.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            ext = f.suffix.lower() or "(확장자 없음)"
            count[ext] += 1
            if f.stat().st_size < 2_000_000:
                lines[ext] += f.read_bytes().count(b"\\n")
    rows = [f"{ext}: 파일 {n}개 · {lines[ext]}줄" for ext, n in count.most_common(20)]
    return "\\n".join(rows) or "파일이 없습니다."


if __name__ == "__main__":
    setup_stdio()
    srv.serve()
'''

FAKE_REPORT = """# 가짜 실행기 보고서

> 작성: 리서치·문서 담당 · (가짜 실행기)

## 결론 요약

가짜 실행기가 쓴 보고서입니다. 화면 확인용이에요. 실제 내용은 없습니다.

## 핵심 주장

1. 첫 번째 주장입니다 [S1]
2. 두 번째 주장입니다 [S2]
3. 세 번째 주장입니다 [S1][S2]

## 출처

- [S1] 예시 문서 — https://example.com/a (확인 2026-01-01)
- [S2] 다른 예시 문서 — https://example.com/b (확인 2026-01-01)
- [S3] 세 번째 예시 문서 — https://example.com/c (확인 2026-01-01)

## 미확인·한계

- 가짜 실행기라 아무것도 확인하지 않았습니다.
"""


# ---------------------------------------------------------------- 선택

def make_runtime(name: str, runtimes_cfg: dict, fake: bool = False, fake_behavior: Behavior | None = None):
    if fake or name == "fake":
        return FakeRuntime(fake_behavior)
    if name == "codex":
        return CodexRuntime(dict(runtimes_cfg.get("codex", {})))
    if name == "claude":
        return ClaudeRuntime(dict(runtimes_cfg.get("claude", {})))
    if name == "grok_text":
        return GrokTextRuntime(dict(runtimes_cfg.get("grok", {})))
    if name == "grok":
        return GrokRuntime(dict(runtimes_cfg.get("grok", {})))
    raise ValueError(f"알 수 없는 실행기: {name}")
