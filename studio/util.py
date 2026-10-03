"""공용 도우미: 시간, 원자적 파일 쓰기, 해시, 프로세스 종료."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _replace(src: str, dst: Path, attempts: int = 40) -> None:
    """Windows에서는 다른 스레드(화면 요청)가 대상 파일을 읽는 순간 교체가 '액세스 거부'로 실패한다.
    읽기는 금방 끝나므로 잠깐 기다렸다 다시 시도한다 (최대 약 2초)."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05)


def atomic_write_text(path: Path, text: str) -> None:
    """임시 파일에 쓴 뒤 교체한다. 쓰는 도중 꺼져도 반쯤 쓰인 파일이 남지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def atomic_copy(src: Path, dst: Path) -> None:
    """파일 하나(그림 등)를 임시 파일로 복사한 뒤 교체한다. 복사 도중 꺼져도 반쯤 쓰인 그림이 남지 않는다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(dst.parent))
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        _replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any = None) -> Any:
    for i in range(20):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except PermissionError:  # 교체되는 순간과 겹침 (Windows) — 잠깐 뒤 다시 읽는다
            if i == 19:
                raise
            time.sleep(0.02)
    return default


def append_jsonl(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: Path) -> list[dict]:
    """손상된 줄(강제 종료로 잘린 마지막 줄 등)은 건너뛴다."""
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_dir(root: Path) -> tuple[str, list[dict]]:
    """폴더 전체의 해시. 파일 목록(상대경로·해시)도 함께 돌려준다."""
    files = []
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            fh = sha256_file(p)
            files.append({"path": rel, "sha256": fh})
            h.update(rel.encode("utf-8") + b"\0" + fh.encode("ascii") + b"\n")
    return h.hexdigest(), files


def read_text_tail(path: Path, max_chars: int) -> str:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return ""
    text = data.decode("utf-8", "replace")
    return text[-max_chars:] if len(text) > max_chars else text


def kill_tree(pid: int) -> None:
    """프로세스와 자식 프로세스를 모두 종료한다."""
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:  # pragma: no cover - 개발 환경은 Windows
        import signal

        try:
            # Only kill a group created for this child, never our supervisor's.
            if os.getpgid(pid) == pid and pid != os.getpgrp():
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def pid_alive(pid: int) -> bool:
    """Windows에서 os.kill(pid, 0)은 프로세스를 죽이므로 쓰지 않는다."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:  # pragma: no cover
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def clean_child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Do not inherit model keys or the external supervisor's authority into workers."""
    env = dict(os.environ)
    for key in list(env):
        if key.upper() in API_KEY_VARS or key.upper() == "STUDIO_SUPERVISOR_TOKEN":
            env.pop(key)
    env["NO_COLOR"] = "1"
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


API_KEY_VARS = {
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "XAI_API_KEY",  # Grok: 본인 grok.com 로그인만 쓴다
    "GROK_API_KEY",
}


def no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0
