"""다른 아이디로 로그인하기 (CEO 요청 2026-09-29: "코덱스 한도가 얼마 없어서 다른 아이디로 로그인해야 하니, 멈추면 로그인 창을 따로 띄워 줘").

구독 한도(quota)나 로그인 만료(login)로 실행이 멈추면, 엔진이 이 PC에 **새 명령 창**을 띄워 로그아웃 → 로그인
(`codex logout` → `codex login`, Claude는 `claude auth logout` → `claude auth login`)을 실행한다. 로그인은 CEO가 브라우저에서
직접 한다 — AI 스튜디오는 아이디·비밀번호·토큰을 보지도 저장하지도 않는다. API 키로 로그인하는 방법(`--with-api-key`)은 쓰지 않는다.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .config import Config
from .runtimes import find_claude, find_codex
from .util import IS_WINDOWS, clean_child_env

NAMES = {"codex": "Codex", "claude": "Claude Code"}


class LoginError(RuntimeError):
    pass


def login_commands(cfg: Config, runtime: str) -> tuple[list[str], list[str]]:
    """(로그아웃 명령, 로그인 명령)."""
    rcfg = (cfg.runtimes or {}).get(runtime, {}) or {}
    if runtime == "codex":
        info, out, inn = find_codex(str(rcfg.get("path", "") or "")), ["logout"], ["login"]
    elif runtime == "claude":
        info, out, inn = find_claude(str(rcfg.get("path", "") or "")), ["auth", "logout"], ["auth", "login"]
    else:
        raise LoginError(f"로그인 창을 띄울 수 없는 실행기예요: {runtime}")
    if not info.get("found"):
        raise LoginError(f"{NAMES[runtime]} 프로그램을 찾지 못했어요. 점검 화면을 확인해 주세요.")
    return [*info["cmd"], *out], [*info["cmd"], *inn]


def script(runtime: str, logout: list[str], login: list[str]) -> str:
    name = NAMES.get(runtime, runtime)
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        f"title {name} 로그인 - AI 스튜디오",
        "echo.",
        f"echo   {name} 사용 한도가 다 되었거나 로그인이 필요해요.",
        "echo   지금 아이디에서 로그아웃한 뒤, 브라우저가 열리면 다른 아이디로 로그인해 주세요.",
        "echo.",
        subprocess.list2cmdline(logout),
        subprocess.list2cmdline(login),
        "echo.",
        "echo   끝났으면 AI 스튜디오 화면에서 [로그인했어요 - 다시 시작]을 눌러 주세요. 이 창은 닫아도 돼요.",
        "echo.",
        "pause",
        "",
    ])


def open_login_window(cfg: Config, runtime: str) -> None:
    """새 명령 창에서 로그아웃 → 로그인을 실행한다 (윈도우). 창은 CEO가 직접 쓰고 닫는다."""
    logout, login = login_commands(cfg, runtime)
    if not IS_WINDOWS:
        raise LoginError(f"이 PC에서는 터미널을 열고 {subprocess.list2cmdline(login)}을 직접 실행해 주세요.")
    folder = Path(tempfile.gettempdir()) / "ais-login"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{runtime}-login.cmd"
    path.write_text(script(runtime, logout, login), encoding="utf-8")
    try:
        subprocess.Popen(["cmd.exe", "/c", str(path)], cwd=str(Path.home()), env=clean_child_env(),
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0), close_fds=True)
    except OSError as e:
        raise LoginError(f"로그인 창을 열지 못했어요: {e}") from e


def login_runtime(run_runtime: str, role_runtime: str) -> str | None:
    """멈춘 실행이 어느 프로그램의 로그인인지 (가짜 실행기로 시험할 때는 그 직원이 끼운 AI)."""
    for rt in (run_runtime, role_runtime):
        if rt in NAMES:
            return rt
    return None
