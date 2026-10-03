"""환경 점검.

필요한 도구가 있는지, 그리고 에이전트가 API 키가 아니라 본인 구독 로그인으로
동작하는지 확인한다. 토큰·계정 정보(이메일 등)는 화면에 내보내지 않는다.
"""

from __future__ import annotations

import json
import os
import platform
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import gitops
from .config import Config
from .qa import suite_hash
from .runtimes import CLAUDE_FLAGS, CODEX_FLAGS, find_claude, find_codex, find_grok, grok_login, host_skill_files, missing_flags
from .util import API_KEY_VARS, clean_child_env, no_window_flags, now_iso, read_json


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=clean_child_env(), creationflags=no_window_flags())
        return p.returncode, (p.stdout + p.stderr).decode("utf-8", "replace").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)


def _flag_check(cmd: list[str], flags: tuple[str, ...]) -> list[str] | None:
    """설치된 CLI가 우리가 넘기는 옵션을 아직 아는지: 없는 옵션 목록 (도움말을 못 읽으면 None)."""
    code, out = _run([*cmd, "--help"], timeout=30)
    return None if code < 0 or not out else missing_flags(out, flags)


def run_doctor(cfg: Config) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(cid: str, label: str, status: str, detail: str, hint: str = "") -> None:
        checks.append({"id": cid, "label": label, "status": status, "detail": detail, "hint": hint})

    # Python
    bits = struct.calcsize("P") * 8
    ok = sys.version_info >= (3, 11)
    add("python", "Python", "ok" if ok else "fail", f"{platform.python_version()} ({bits}bit)", "" if ok else "Python 3.11 이상이 필요합니다.")

    # Git
    code, out = _run(["git", "--version"])
    add("git", "Git", "ok" if code == 0 else "fail", out.splitlines()[0] if out else "없음", "" if code == 0 else "Git을 설치하세요.")

    # Codex
    rc = cfg.runtime_cfg("codex")
    info = find_codex(str(rc.get("path", "") or ""))
    if info["found"]:
        others = ", ".join(f"{c['source']} {c['version'] or '실행 불가'}" for c in info["candidates"])
        add("codex", "Codex CLI", "ok", f"{info['version']} · {info['source']}", f"후보: {others}")
        code, out = _run([*info["cmd"], "login", "status"])
        low = out.lower()
        if "chatgpt" in low:
            add("codex_auth", "Codex 로그인", "ok", "ChatGPT 구독 로그인")
        elif "api key" in low or "api_key" in low:
            add("codex_auth", "Codex 로그인", "fail", "API 키 로그인", "이 회사는 API 키를 쓰지 않습니다. `codex logout` 후 `codex login`으로 ChatGPT 로그인하세요.")
        else:
            add("codex_auth", "Codex 로그인", "fail", out.splitlines()[0] if out else "로그인 안 됨", "터미널에서 `codex login`을 실행해 본인이 로그인하세요.")
        gone = _flag_check([*info["cmd"], "exec"], CODEX_FLAGS)
        if gone:
            add("codex_flags", "Codex 옵션", "fail", "없는 옵션: " + ", ".join(gone),
                "Codex가 업데이트되며 옵션이 바뀐 것 같아요. 진짜 실행 전에 studio/runtimes.py의 CodexRuntime을 고쳐야 해요.")
        elif gone is None:
            add("codex_flags", "Codex 옵션", "warn", "확인하지 못함", "`codex exec --help`가 읽히지 않았어요.")
        else:
            add("codex_flags", "Codex 옵션", "ok", f"{len(CODEX_FLAGS)}개 모두 있음")
        host = host_skill_files()
        if not rc.get("block_host_skills", True):
            add("codex_host_skills", "개인 Codex 스킬", "warn", f"{len(host)}개가 직원에게 보여요 (막지 않음)",
                "studio.toml [runtimes.codex] block_host_skills = false 로 꺼 두었어요.")
        else:
            add("codex_host_skills", "개인 Codex 스킬", "ok", f"{len(host)}개 막음 (직원에게 안 보임)" if host else "없음")
    else:
        add("codex", "Codex CLI", "fail", "찾을 수 없음", "Codex 앱을 설치하거나 `npm i -g @openai/codex`로 설치하세요.")

    # Claude is optional and disabled under the current operating conditions.
    rc = cfg.runtime_cfg("claude")
    if not rc.get("enabled",False):
        add("claude", "Claude", "warn", "현재 사용 불가 · 기획/리뷰는 Codex로 진행합니다.")
    else:
        info = find_claude(str(rc.get("path", "") or ""))
        if info["found"]:
            add("claude", "Claude Code CLI", "ok", info["version"])
            code, out = _run([*info["cmd"], "auth", "status"])
            try:
                st = json.loads(out)
            except json.JSONDecodeError:
                st = {}
            if st.get("loggedIn") and st.get("authMethod") in ("claude.ai", "oauth", "subscription"):
                plan = st.get("subscriptionType") or "구독"
                add("claude_auth", "Claude 로그인", "ok", f"claude.ai 구독 로그인 ({plan})", "Pro 플랜은 대화 사용량과 한도를 같이 씁니다. 리뷰는 짧게 유지합니다.")
            elif st.get("loggedIn"):
                add("claude_auth", "Claude 로그인", "fail", f"인증 방식: {st.get('authMethod')}", "API 키 대신 `claude auth login`으로 구독 로그인하세요.")
            else:
                add("claude_auth", "Claude 로그인", "warn", "로그인 안 됨", "리뷰는 Codex 별도 세션으로 대신합니다. 교차 리뷰를 쓰려면 `claude auth login`.")
            gone = _flag_check(info["cmd"], CLAUDE_FLAGS)
            if gone:
                add("claude_flags", "Claude 옵션", "fail", "없는 옵션: " + ", ".join(gone),
                    "Claude Code가 업데이트되며 옵션이 바뀐 것 같아요. 진짜 실행 전에 studio/runtimes.py의 ClaudeRuntime을 고쳐야 해요.")
            elif gone is None:
                add("claude_flags", "Claude 옵션", "warn", "확인하지 못함", "`claude --help`가 읽히지 않았어요.")
            else:
                add("claude_flags", "Claude 옵션", "ok", f"{len(CLAUDE_FLAGS)}개 모두 있음")
        else:
            add("claude", "Claude Code CLI", "warn", "찾을 수 없음", "리뷰는 Codex 별도 세션으로 대신합니다 (교차 모델 검증 아님).")

    # Grok (선택: 꾸미기 공방·새 직원 그림을 Grok으로 그릴 때만)
    info = find_grok(str(cfg.runtime_cfg("grok").get("path", "") or ""))
    if info["found"]:
        if grok_login(info):
            add("grok", "Grok CLI (그림, 선택)", "ok", f"{info['version']} · grok.com 로그인")
        else:
            add("grok", "Grok CLI (그림, 선택)", "warn", f"{info['version']} · 로그인 확인 불가", "미로그인 또는 연결 지연일 수 있습니다. `grok models` 응답을 먼저 확인하고, 로그인이 필요하다고 나올 때 본인이 `grok login`을 실행하세요.")
    else:
        add("grok", "Grok CLI (그림, 선택)", "ok", "없음 (Codex로 그림)")

    # API 키 환경변수
    present = sorted(k for k in API_KEY_VARS if os.environ.get(k))
    if present:
        add("api_env", "API 키·경로 환경변수", "warn", ", ".join(present), "에이전트를 실행할 때는 이 값들을 빼고 실행하므로 구독 로그인만 쓰입니다. 쓰지 않는다면 시스템 환경변수에서 지우세요.")
    else:
        add("api_env", "API 키·경로 환경변수", "ok", "없음")

    # Godot
    godot = cfg.godot_path()
    if godot and Path(godot).exists():
        code, out = _run([godot, "--version"], timeout=60)
        version = out.splitlines()[-1] if out else "?"
        expected = str(cfg.tools.get("godot_version", "") or "")
        status = "ok" if code == 0 and (not expected or version.startswith(expected)) else "warn"
        add("godot", "Godot", status, version, f"기대 버전 {expected}" if status != "ok" else "")
    else:
        add("godot", "Godot", "fail", godot or "경로 없음", "studio.toml [tools] godot에 콘솔용 Godot 실행 파일 경로를 넣으세요.")

    # 프로젝트
    for p in cfg.projects.values():
        if not gitops.is_repo(p.repo):
            add(f"project_{p.key}", f"프로젝트 {p.title}", "fail", "저장소 없음", "`python studio.py init`을 실행하세요.")
            continue
        try:
            branch = gitops.current_branch(p.repo)
            clean = gitops.is_clean(p.repo)
            head = gitops.head(p.repo)[:7]
        except gitops.GitError as e:
            add(f"project_{p.key}", f"프로젝트 {p.title}", "fail", str(e))
            continue
        status = "ok" if branch == p.main_branch and clean else "warn"
        detail = f"{branch} @ {head}" + ("" if clean else " · 커밋 안 된 변경 있음")
        digest = suite_hash(cfg, p)
        if p.qa.get("commands"):
            count = f"{p.qa['expected_total']}개" if p.qa.get("expected_total") else "형식 검사"
            detail += f" · 신뢰 테스트 {count} ({digest[:8] if digest else '없음'})"
        else:
            detail += " · 자동 검증 없음"
        hint = "" if status == "ok" else f"main({p.main_branch})에 있고 변경이 커밋돼 있어야 병합할 수 있습니다."
        add(f"project_{p.key}", f"프로젝트 {p.title}", status, detail, hint)
        selftest = read_json(cfg.data_dir / "selftest" / p.key / "selftest.json")
        if selftest:
            add(
                f"selftest_{p.key}",
                f"자가 점검 {p.title}",
                "ok" if selftest.get("ok") else "fail",
                f"결함 구현 {len(selftest.get('cases', []))}개를 {'모두 잡아냄' if selftest.get('ok') else '놓침'} · {selftest.get('at', '')[:16]}",
                "" if selftest.get("ok") else "신뢰 테스트가 결함을 못 잡습니다. 테스트를 보강하세요.",
            )

    worst = "ok"
    for c in checks:
        if c["status"] == "fail":
            worst = "fail"
            break
        if c["status"] == "warn":
            worst = "warn"
    return {"at": now_iso(), "overall": worst, "checks": checks}
