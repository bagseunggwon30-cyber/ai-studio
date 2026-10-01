"""휴대폰 리모컨 (CEO 결정 2026-09-29: 같은 와이파이 QR + Tailscale 둘 다, 푸시 알림 없음).

- 기본은 꺼져 있다. PC 대시보드는 지금처럼 127.0.0.1에서만 열린다.
- 같은 와이파이: CEO가 켜면 이 PC의 집 안 주소(예: 192.168.0.10)에 두 번째 서버를 열고 휴대폰 화면(/m)만 내보낸다.
  암호화가 없는 http라 집·회사처럼 믿을 수 있는 와이파이에서만 쓴다 (화면에 안내).
- Tailscale: CEO가 `tailscale serve`로 이 PC를 자기 기기끼리만 보이게 열면(https), 그 주소(*.ts.net)로 온 요청은 휴대폰 화면(/m)만 받는다.
- 짝짓기: PC 화면에서 만든 한 번 쓰는 번호(5분)로 기기 토큰을 받는다. 토큰은 SHA-256 해시로만 저장하고 기기마다 끊을 수 있다.
  번호를 5번 틀리면 1분 동안 받지 않는다.
- 휴대폰이 할 수 있는 것: 보기(결재함·진행·알림·작업 내용), 승인·수정 요청·재시도·실행·취소, 지시 보내기, 긴급 정지·재개.
  MCP·토큰·직원·설정 바꾸기는 PC에서만.
저장: data/remote.json {"lan": bool, "lan_port": int, "ts_hosts": [...], "devices": [{id, name, hash, created, last_seen}]}
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .config import Config
from .util import atomic_write_json, clean_child_env, no_window_flags, now_iso, read_json

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # 헷갈리는 글자(0·O·1·I·L) 뺌
CODE_TTL = 300
MAX_FAILS, LOCK_S = 5, 60
MAX_DEVICES = 10
HOST_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.ts\.net$")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def lan_ip() -> str | None:
    """이 PC의 집 안 네트워크 주소 (UDP 소켓의 나가는 주소를 본다 — 실제로 보내지는 않는다). 사설 주소만."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        return None
    import ipaddress

    return ip if ipaddress.ip_address(ip).is_private and not ipaddress.ip_address(ip).is_loopback else None


def tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for p in (Path(r"C:\Program Files\Tailscale\tailscale.exe"), Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe")):
        if p.is_file():
            return str(p)
    return None


def detect_tailscale() -> dict[str, Any]:
    """Tailscale이 깔려 있고 켜져 있으면 이 PC의 이름(*.ts.net)을 알려 준다. 설정은 바꾸지 않는다 (읽기만)."""
    exe = tailscale_exe()
    if not exe:
        return {"installed": False, "host": "", "error": "Tailscale이 설치되어 있지 않아요."}
    try:
        out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=15, env=clean_child_env(), creationflags=no_window_flags())
        data = json.loads(out.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return {"installed": True, "host": "", "error": f"Tailscale 상태를 읽지 못했어요: {e}"}
    host = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".").lower()
    if data.get("BackendState") != "Running" or not HOST_RE.match(host):
        return {"installed": True, "host": "", "error": "Tailscale이 꺼져 있거나 로그인되지 않았어요."}
    return {"installed": True, "host": host, "error": ""}


_FIREWALL_PS = r"""
$ErrorActionPreference = 'Stop'
$ip = '__IP__'; $exe = '__EXE__'
$ifc = Get-NetIPAddress -IPAddress $ip -AddressFamily IPv4 | Select-Object -First 1
$prof = Get-NetConnectionProfile -InterfaceIndex $ifc.InterfaceIndex | Select-Object -First 1
$rules = @(Get-NetFirewallApplicationFilter | Where-Object { $_.Program -ieq $exe } | Get-NetFirewallRule |
  Where-Object { [string]$_.Direction -eq 'Inbound' -and [string]$_.Enabled -eq 'True' } |
  ForEach-Object { [pscustomobject]@{ action = [string]$_.Action; profile = [string]$_.Profile } })
$json = [pscustomobject]@{ alias = [string]$ifc.InterfaceAlias; category = [string]$prof.NetworkCategory; rules = $rules } | ConvertTo-Json -Compress -Depth 4
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
"""


def _ps_quote(text: str) -> str:
    return text.replace("'", "''")


def _profile_hits(profile: str, category: str) -> bool:
    """방화벽 규칙의 적용 범위(예: 'Public', 'Private, Public', 'Any')가 지금 네트워크 종류에 닿는지."""
    names = {p.strip().lower() for p in re.split(r"[,\s]+", profile) if p.strip()}
    return bool(names & {"any", "all", category.lower()})


def interpret_firewall(raw: dict[str, Any], exe: str) -> dict[str, Any]:
    """PowerShell이 읽어 온 방화벽 규칙을 쉬운 말 점검 결과로. blocked = 이 프로그램의 받는 연결을 막는 규칙이 지금 네트워크에 적용됨."""
    category = str(raw.get("category") or "")
    rules = raw.get("rules") or []
    if isinstance(rules, dict):
        rules = [rules]
    hit = [r for r in rules if _profile_hits(str(r.get("profile", "")), category)]
    blocked = any(str(r.get("action", "")).lower() == "block" for r in hit)
    allowed = any(str(r.get("action", "")).lower() == "allow" for r in hit)
    alias = str(raw.get("alias") or "")
    fix: list[str] = []
    if category.lower() == "public" and alias:
        fix.append(f"Set-NetConnectionProfile -InterfaceAlias '{_ps_quote(alias)}' -NetworkCategory Private")
    if blocked or not allowed or category.lower() == "public":
        # 윈도우 방화벽 창에서 '허용'을 눌렀을 때와 같다: 이 프로그램, 개인 네트워크에서만 (공용 네트워크는 계속 막힘)
        fix.append(f"New-NetFirewallRule -DisplayName 'AI 스튜디오 휴대폰 리모컨' -Direction Inbound -Protocol TCP "
                   f"-Profile Private -Action Allow -Program '{_ps_quote(exe)}'")
    return {"checked": True, "category": category, "alias": alias, "blocked": blocked, "allowed": allowed,
            "fix": "\n".join(fix) if (blocked or category.lower() == "public") else ""}


def firewall_check(exe: str, ip: str) -> dict[str, Any]:
    """윈도우 방화벽이 휴대폰의 접속을 막는지 읽기만 한다 (아무것도 바꾸지 않는다). 윈도우가 아니거나 못 읽으면 checked=False."""
    if not sys.platform.startswith("win"):
        return {"checked": False}
    script = _FIREWALL_PS.replace("__IP__", _ps_quote(ip)).replace("__EXE__", _ps_quote(exe))
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return {"checked": False}
    try:
        # 스크립트는 UTF-16 base64로, 결과는 UTF-8 base64로 주고받는다 (한글 어댑터 이름이 코드 페이지에 깨지지 않게)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        out = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True,
                             encoding="ascii", errors="replace", timeout=40, env=clean_child_env(), creationflags=no_window_flags())
        raw = json.loads(base64.b64decode(out.stdout.strip().splitlines()[-1]).decode("utf-8"))
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return {"checked": False}
    if not isinstance(raw, dict) or not raw.get("category"):
        return {"checked": False}
    return interpret_firewall(raw, exe)


class Remote:
    """짝짓기 번호(메모리에만)와 기기 토큰(해시로 저장)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.lock = threading.Lock()
        self._codes: dict[str, float] = {}
        self._fails = 0
        self._locked_until = 0.0

    # ------------------------------------------------------------ 저장
    def _path(self) -> Path:
        return self.cfg.data_dir / "remote.json"

    def settings(self) -> dict[str, Any]:
        data = read_json(self._path(), {}) or {}
        return {"lan": bool(data.get("lan")), "lan_port": int(data.get("lan_port") or 0),
                "ts_hosts": [h for h in data.get("ts_hosts") or [] if HOST_RE.match(str(h))],
                "devices": [d for d in data.get("devices") or [] if isinstance(d, dict) and d.get("hash")]}

    def _save(self, data: dict[str, Any]) -> None:
        atomic_write_json(self._path(), data)

    def update(self, **changes: Any) -> dict[str, Any]:
        with self.lock:
            data = self.settings()
            data.update(changes)
            self._save(data)
            return data

    def remote_hosts(self) -> set[str]:
        """휴대폰 화면만 받는 Host (Tailscale 이름. https라 포트가 없다)."""
        return set(self.settings()["ts_hosts"])

    # ------------------------------------------------------------ 짝짓기
    def new_code(self) -> dict[str, Any]:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        with self.lock:
            now = time.monotonic()
            self._codes = {c: t for c, t in self._codes.items() if t > now}
            self._codes[code] = now + CODE_TTL
        return {"code": f"{code[:4]}-{code[4:]}", "expires_in": CODE_TTL}

    def pair(self, code: str, name: str) -> str:
        """번호가 맞으면 새 기기 토큰을 돌려준다 (번호는 한 번만 쓴다). 틀리면 ValueError."""
        norm = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
        with self.lock:
            now = time.monotonic()
            if now < self._locked_until:
                raise ValueError("잠깐 막혔어요. 1분 뒤에 다시 해 주세요.")
            expires = self._codes.pop(norm, 0)
            if expires <= now:
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    self._fails, self._locked_until = 0, now + LOCK_S
                raise ValueError("짝짓기 번호가 맞지 않거나 시간이 지났어요. PC 화면에서 새로 만들어 주세요.")
            self._fails = 0
            token = secrets.token_urlsafe(32)
            data = self.settings()
            device = {"id": secrets.token_hex(4), "name": " ".join(str(name or "휴대폰").split())[:40] or "휴대폰",
                      "hash": _hash(token), "created": now_iso(), "last_seen": now_iso()}
            data["devices"] = (data["devices"] + [device])[-MAX_DEVICES:]
            self._save(data)
        return token

    def device_for(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        h = _hash(token)
        with self.lock:
            data = self.settings()
            for d in data["devices"]:
                if secrets.compare_digest(d["hash"], h):
                    if str(d.get("last_seen", ""))[:16] != now_iso()[:16]:  # 1분에 한 번만 적는다
                        d["last_seen"] = now_iso()
                        self._save(data)
                    return d
        return None

    def remove_device(self, device_id: str) -> None:
        with self.lock:
            data = self.settings()
            left = [d for d in data["devices"] if d.get("id") != device_id]
            if len(left) == len(data["devices"]):
                raise ValueError("그런 기기가 없어요.")
            data["devices"] = left
            self._save(data)

    def info(self) -> dict[str, Any]:
        """PC 화면용 (토큰 해시는 빼고)."""
        s = self.settings()
        return {"lan": s["lan"], "lan_port": s["lan_port"], "ts_hosts": s["ts_hosts"],
                "devices": [{k: d.get(k) for k in ("id", "name", "created", "last_seen")} for d in s["devices"]]}
