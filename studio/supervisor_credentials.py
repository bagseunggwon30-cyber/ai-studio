"""Owner-only Windows DPAPI storage for a local supervisor capability.

The model-provider login is unrelated. No cleartext token is stored or printed.
"""
from __future__ import annotations
import csv
import base64
import ctypes
import io
import os
from pathlib import Path
import subprocess

from .util import atomic_write_text, no_window_flags

HEADER = b"AI-STUDIO-DPAPI-V1\n"


class CredentialError(ValueError):
    pass


def _crypt(value: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise CredentialError("Windows 사용자 암호화를 사용할 수 없습니다.")
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    # CurrentUser, UI forbidden. Never CRYPTPROTECT_LOCAL_MACHINE.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CredentialError("현재 Windows 사용자로 연결 토큰을 암호화/복호화하지 못했습니다.")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def _owner_only(path: Path):
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                            timeout=10, creationflags=no_window_flags())
    try:
        sid = next(csv.reader(io.StringIO(result.stdout.decode("utf-8", "replace"))))[-1]
    except (StopIteration, IndexError):
        raise CredentialError("연결 토큰의 파일 권한을 설정하지 못했습니다.") from None
    if result.returncode or not sid.startswith("S-1-"):
        raise CredentialError("연결 토큰의 파일 권한을 설정하지 못했습니다.")
    result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F"],
                            capture_output=True, timeout=10, creationflags=no_window_flags())
    if result.returncode:
        raise CredentialError("연결 토큰의 파일 권한을 설정하지 못했습니다.")


def save(path: Path, token: str):
    if not isinstance(token, str) or not 32 <= len(token) <= 512:
        raise CredentialError("연결 토큰 형식 오류")
    encrypted = base64.b64encode(_crypt(token.encode("ascii"))).decode("ascii")
    atomic_write_text(path, HEADER.decode("ascii") + encrypted)
    _owner_only(path)


def load(path: Path) -> str:
    try:
        if path.is_symlink() or path.stat().st_size > 16384:
            raise ValueError()
        data = path.read_bytes()
        if not data.startswith(HEADER):
            raise ValueError()
        token = _crypt(base64.b64decode(data[len(HEADER):], validate=True), decrypt=True).decode("ascii")
        if not 32 <= len(token) <= 512:
            raise ValueError()
        return token
    except (OSError, UnicodeError, ValueError):
        raise CredentialError("연결 토큰을 확인하지 못했습니다. 현재 사용자와 로컬 연결 설정을 확인하세요.") from None
