"""MCP 연결 문 (게이트웨이): ChatGPT·Dots 같은 클라우드 에이전트가 AI 스튜디오의 '외부 감독 MCP'를 쓰게 해 주는
OAuth 로그인 + 보호된 MCP 입구 (CEO 승인 대기: docs/MCP_GATEWAY.md).

지키는 것 (모두 시험 `tests/test_gateway.py`가 확인한다)
- 대시보드 서버와 **따로 연** 서버(기본 포트 8767)이고 **127.0.0.1에만** 열린다. 기본은 꺼짐. CEO가 대시보드에서 켠 뒤에만 시작한다.
  인터넷에 닿게 하는 터널은 CEO가 따로 켠다 — 이 프로그램은 터널을 설치·실행하지 않고, **먼저 바깥으로 요청을 보내지도 않는다** (이 파일에는 나가는 연결이 없다).
- 이 서버가 내는 것은 오직: `/.well-known/oauth-protected-resource`(+`/mcp`), `/.well-known/oauth-authorization-server`,
  `POST /oauth/register`, `GET·POST /oauth/authorize`, `POST /oauth/token`, `POST /mcp`, 동의 화면 CSS(`/oauth/consent.css`). 그 밖은 모두 404.
  대시보드 화면·`/api/*`·`/m/*`·세션 토큰·휴대폰 토큰은 이 서버에 없다. CORS 헤더 없음.
- Host는 CEO가 넣은 공개 주소의 호스트와 127.0.0.1·localhost(시험·터널 연결용)만 받는다.
- 코드·토큰은 `secrets.token_urlsafe(32)`, 디스크에는 SHA-256 해시만, 로그·화면·오류에 값을 내지 않는다.
  인증 코드: 60초 · 한 번만 · PKCE(S256 필수) · redirect_uri와 resource에 묶음. 액세스 토큰 1시간, 새로고침 토큰 30일(쓸 때마다 바뀜,
  이미 쓴 새로고침 토큰이 다시 오면 그 연결 전체 폐기).
- 연결 승인은 CEO가 대시보드에서 만든 **연결 번호**(5분 · 한 번 · 5번 틀리면 1분 잠금, `studio/remote.py` 짝짓기와 같은 방식)가 있어야 한다.
- 권한은 CEO가 정한 만큼만: 읽기(`studio:read`) 기본, 일 맡기기(`studio:submit`)는 CEO가 프로젝트·폴더 범위를 골라 허용했을 때만.
  실행 시작(`run_task`)은 그 위에 CEO가 프로젝트마다 따로 켠 곳에서만, 이 앱이 맡긴 일에만, 동시에 3개까지 (결재·병합·완료는 여전히 CEO만).
  새 권한 체계를 만들지 않는다 — 연결마다 `gateway-<번호>` 신분을 만들어 기존 `Supervisor.call_as`가 같은 grant(프로젝트별 read/write/run/paths) 검사를 한다.
  `data/supervisors.json`과 기존 `/mcp`(Bearer 감독 토큰)는 건드리지 않는다.
- 기록: `data/gateway/audit.jsonl`(추가만, 비밀 없음, 분당 상한) + 중요한 일은 `store.event`.
저장: data/gateway.json {enabled, public_url, port, permissions, extra_redirects} · data/gateway/{clients,grants}.json · data/gateway/audit.jsonl
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

from . import projects as projects_mod
from .supervisor import AccessError, Supervisor
from .util import append_jsonl, atomic_write_json, read_json, read_jsonl

# ---------------------------------------------------------------- 상수
DEFAULT_PORT = 8767
SCOPE_READ, SCOPE_SUBMIT = "studio:read", "studio:submit"
SCOPES = (SCOPE_READ, SCOPE_SUBMIT)
READ_TOOLS = ("list_projects", "list_tasks", "task_status", "task_events", "task_result", "task_artifact")
SUBMIT_TOOLS = ("submit_task", "cancel_task", "run_task")  # run_task는 CEO가 '실행 시작'을 켠 프로젝트가 있을 때만 목록에 보인다 (Gateway.tools_for)
TOOL_OP = {"list_projects": "projects", "list_tasks": "tasks", "submit_task": "submit", "task_status": "status", "task_events": "events", "task_result": "result",
           "task_artifact": "artifact", "cancel_task": "cancel", "run_task": "run"}
OP_TOOL = {v: k for k, v in TOOL_OP.items()}

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # remote.py와 같다: 헷갈리는 글자(0·O·1·I·L) 뺌
CODE_TTL = 300
MAX_FAILS, LOCK_S = 5, 60
AUTH_CODE_TTL = 60
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
FORM_TTL = 600
USED_CODE_KEEP = 600
MAX_CLIENTS = 20
MAX_CONNECTIONS = 20
MAX_FORMS = 100
CLIENT_IDLE_NEVER_S = 14 * 86400  # 한 번도 연결을 못 끝낸 등록은 2주 뒤 정리
CLIENT_IDLE_S = 90 * 86400  # 연결이 없고 90일 안 쓴 등록은 정리
MAX_BODY_MCP = 1_000_000  # server.MAX_BODY(대시보드의 MCP 본문 상한)와 같은 값 (시험이 같은지 확인한다)
MAX_BODY_OAUTH = 65_536
MAX_CONCURRENT = 16
AUDIT_PER_MINUTE = 120
LAST_USED_WRITE_S = 60
LIMITS = {"oauth": (60, 60.0), "register": (10, 60.0), "mcp_ip": (600, 60.0), "mcp_conn": (120, 60.0), "bad_auth": (20, 60.0)}

DEFAULT_REDIRECTS = {
    "https://chatgpt.com/connector_platform_oauth_redirect",
    "https://claude.ai/api/mcp/auth_callback",
}
CHATGPT_APP = re.compile(r"https://chatgpt\.com/connector/oauth/[A-Za-z0-9_-]{1,128}")
LOOPBACK = re.compile(r"http://(?:127\.0\.0\.1|localhost):([0-9]{1,5})(/[A-Za-z0-9._~!$&'()*+,;=:%/-]*)")
EXTRA_REDIRECT = re.compile(r"https://[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+(:[0-9]{1,5})?(/[A-Za-z0-9._~!$&'()*+,;=:%/-]*)")
URL_RE = re.compile(r"https://((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?::([0-9]{1,5}))?/?")
PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".test.local")
CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43,128}")
VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
KEY_RE = re.compile(r"[a-z][a-z0-9-]{0,39}")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    """S256: BASE64URL(SHA256(verifier)), 끝의 = 없이 (시험·점검 스크립트도 쓴다)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")


def _no_constant(_name: str) -> None:
    raise ValueError("NaN·Infinity는 쓸 수 없어요.")


def clean_name(value: Any) -> str:
    """앱이 스스로 적은 이름: 믿지 않는 글. 제어 문자를 빼고 한 줄로, 60자까지."""
    text = " ".join(re.sub(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩]", " ", str(value or "")).split())[:60]
    return text or "이름 없는 앱"


# ---------------------------------------------------------------- 검사 (쉬운 한국어 오류)
def parse_public_url(value: Any) -> str:
    """CEO가 넣은 공개 주소 → 정규화한 `https://호스트[:포트]`. 경로·쿼리·사용자 정보·IP·집 안 이름은 거절."""
    if not isinstance(value, str):
        raise ValueError("공개 주소를 글로 넣어 주세요.")
    raw = value.strip()
    if not raw:
        raise ValueError("공개 주소를 넣어 주세요. (터널 프로그램이 알려 준 https:// 주소)")
    if len(raw) > 200 or re.search(r"\s", raw):
        raise ValueError("주소가 너무 길거나 띄어쓰기가 들어 있어요.")
    low = raw.lower()
    if low.startswith("http://"):
        raise ValueError("https:// 로 시작하는 주소만 쓸 수 있어요. (http는 안 돼요)")
    if not low.startswith("https://"):
        raise ValueError("주소는 https:// 로 시작해야 해요.")
    if any(c in low for c in "?#@\\"):
        raise ValueError("주소 뒤에 경로·물음표·# 같은 것을 붙이지 말고 https://이름.도메인 만 넣어 주세요.")
    m = URL_RE.fullmatch(low)
    if not m:
        if re.fullmatch(r"https://[^/]+/.+", low):
            raise ValueError("주소 뒤에 경로를 붙이지 말고 https://이름.도메인 만 넣어 주세요. (/mcp는 자동으로 붙여 드려요)")
        raise ValueError("주소 모양이 맞지 않아요. 영문 이름과 점이 있는 https:// 주소만 쓸 수 있어요.")
    host, port = m.group(1), m.group(2)
    labels = host.split(".")
    if labels[-1].isdigit() or any(host.endswith(s) for s in PRIVATE_SUFFIXES):
        raise ValueError("집 안·이 PC 주소나 숫자 주소는 쓸 수 없어요. 터널이 알려 준 인터넷 주소를 넣어 주세요.")
    if len(host) > 150 or any(len(x) > 63 for x in labels):
        raise ValueError("주소가 너무 길어요.")
    if port is not None:
        if not 1 <= int(port) <= 65535:
            raise ValueError("포트 번호가 올바르지 않아요.")
        port = str(int(port))
    return "https://" + host + (f":{port}" if port and port != "443" else "")


def redirect_allowed(uri: Any, extra: Any = ()) -> bool:
    """등록해도 되는 redirect 주소: 정확히 같은 글만 (쿼리·# 없음). 기본 허용 + 설정으로 더한 것 + 이 PC 루프백."""
    if not isinstance(uri, str) or not 8 <= len(uri) <= 2000:
        return False
    if uri in DEFAULT_REDIRECTS or CHATGPT_APP.fullmatch(uri) or uri in extra:
        return True
    m = LOOPBACK.fullmatch(uri)
    return bool(m and 1 <= int(m.group(1)) <= 65535)


def parse_extra_redirects(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 10:
        raise ValueError("추가로 허용할 연결 주소는 10개까지 목록으로 넣어 주세요.")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) > 500 or not EXTRA_REDIRECT.fullmatch(item):
            raise ValueError("추가 연결 주소는 https:// 로 시작하는 정확한 주소여야 해요 (물음표·# 없음).")
        host = urlparse(item).hostname or ""
        if host.endswith(PRIVATE_SUFFIXES) or host.split(".")[-1].isdigit():
            raise ValueError("집 안·이 PC 주소는 추가할 수 없어요.")
        if item not in out:
            out.append(item)
    return out


def default_settings() -> dict[str, Any]:
    return {"enabled": False, "public_url": "", "port": DEFAULT_PORT,
            "permissions": {"submit": False, "projects": {}}, "extra_redirects": []}


# ---------------------------------------------------------------- 요청 속도 제한
class Limiter:
    """창 안에서 몇 번까지: 키별로 시각 목록을 둔다 (시계는 주입할 수 있다)."""

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self.hits: dict[Any, deque] = {}
        self.lock = threading.Lock()

    def _trim(self, key: Any, window: float, now: float) -> deque:
        q = self.hits.setdefault(key, deque())
        while q and q[0] <= now - window:
            q.popleft()
        return q

    def blocked(self, key: Any, limit: int, window: float = 60.0) -> float:
        """막혀 있으면 몇 초 뒤에 다시 되는지(>0), 아니면 0. 횟수를 올리지 않는다."""
        now = self.clock()
        with self.lock:
            q = self._trim(key, window, now)
            return max(1.0, q[0] + window - now) if len(q) >= limit else 0.0

    def hit(self, key: Any, limit: int, window: float = 60.0) -> float:
        """한 번 센다. 이미 상한이면 세지 않고 기다릴 초를 돌려준다."""
        now = self.clock()
        with self.lock:
            q = self._trim(key, window, now)
            if len(q) >= limit:
                return max(1.0, q[0] + window - now)
            q.append(now)
            if len(self.hits) > 2000:  # 오래 안 쓴 키 정리
                for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - 3600]:
                    self.hits.pop(k, None)
            return 0.0


class AuthError(Exception):
    """액세스 토큰이 없거나 틀림 (이유는 밖으로 알리지 않는다)."""


class OAuthError(Exception):
    def __init__(self, code: str, description: str, status: int = 400):
        super().__init__(description)
        self.code, self.description, self.status = code, description, status


class FatalAuthorize(Exception):
    """redirect 주소를 믿을 수 없어 앱으로 돌려보내지 못하는 오류 (화면에만 알린다)."""


class Redirectable(Exception):
    def __init__(self, code: str, description: str, redirect_uri: str, state: str | None):
        super().__init__(description)
        self.code, self.description, self.redirect_uri, self.state = code, description, redirect_uri, state


# ---------------------------------------------------------------- 상태와 OAuth 논리 (HTTP는 아래 핸들러)
class Gateway:
    def __init__(self, cfg, store, engine, *, clock: Callable[[], float] = time.time, bind_port: int | None = None):
        self.cfg, self.store, self.engine = cfg, store, engine
        self.clock = clock
        self.bind_port = bind_port  # 시험용: 설정의 포트 대신 (0이면 임시 포트)
        self.lock = threading.RLock()
        self.path = cfg.data_dir / "gateway.json"
        self.dir = cfg.data_dir / "gateway"
        self.server: GatewayServer | None = None
        self.thread: threading.Thread | None = None
        self.port = 0
        self.limiter = Limiter(clock)
        self.limits = dict(LIMITS)
        self._settings: dict[str, Any] | None = None
        self._clients: dict[str, dict[str, Any]] | None = None
        self._grants: dict[str, dict[str, Any]] | None = None
        # 메모리에만 (디스크에 두지 않는다): 연결 번호, 인증 코드, 동의 화면 번호표
        self._codes: dict[str, float] = {}
        self._fails = 0
        self._locked_until = 0.0
        self._auth: dict[str, dict[str, Any]] = {}
        self._used: dict[str, tuple[str, float]] = {}
        self._forms: dict[str, dict[str, Any]] = {}
        self._touch: dict[str, float] = {}
        self._audit_minute = (0, 0, 0)  # (분, 쓴 줄, 줄인 줄)

    # ------------------------------------------------------------ 저장
    def settings(self) -> dict[str, Any]:
        with self.lock:
            if self._settings is None:
                self._settings = self._clean_settings(read_json(self.path, {}) or {})
            return json.loads(json.dumps(self._settings))

    def _clean_settings(self, raw: Any) -> dict[str, Any]:
        """파일에서 읽은 값은 믿지 않는다: 잘못된 칸은 기본값으로."""
        out = default_settings()
        if not isinstance(raw, dict):
            return out
        try:
            out["public_url"] = parse_public_url(raw["public_url"]) if raw.get("public_url") else ""
        except ValueError:
            out["public_url"] = ""
        out["enabled"] = raw.get("enabled") is True and bool(out["public_url"])
        port = raw.get("port")
        out["port"] = port if type(port) is int and 1024 <= port <= 65535 else DEFAULT_PORT
        try:
            out["extra_redirects"] = parse_extra_redirects(raw.get("extra_redirects", []))
        except ValueError:
            out["extra_redirects"] = []
        perm = raw.get("permissions") if isinstance(raw.get("permissions"), dict) else {}
        out["permissions"]["submit"] = perm.get("submit") is True
        for key, spec in (perm.get("projects") or {}).items() if isinstance(perm.get("projects"), dict) else []:
            paths = spec.get("paths") if isinstance(spec, dict) else None
            if isinstance(key, str) and KEY_RE.fullmatch(key) and isinstance(paths, list) and 1 <= len(paths) <= 30 \
                    and all(isinstance(p, str) and 0 < len(p) <= 240 for p in paths) and len(out["permissions"]["projects"]) < 50:
                # write: 이 프로젝트에 일 맡기기를 열었는지. 칸이 없으면(옛 설정) 켜짐, 있는데 true가 아니면 꺼짐.
                # run: 실행 시작까지 열었는지. 칸이 없거나 이상한 값이면 꺼짐이고, 일 맡기기가 꺼진 프로젝트에서는 켜질 수 없다.
                write = spec.get("write", True) is True
                out["permissions"]["projects"][key] = {"paths": list(paths), "write": write, "run": write and spec.get("run") is True}
        return out

    def _save_settings(self, data: dict[str, Any]) -> None:
        with self.lock:
            atomic_write_json(self.path, data)
            self._settings = self._clean_settings(data)

    def clients(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            if self._clients is None:
                raw = read_json(self.dir / "clients.json", {}) or {}
                rows = raw.get("clients") if isinstance(raw, dict) else None
                self._clients = {k: v for k, v in (rows or {}).items() if isinstance(k, str) and isinstance(v, dict)
                                 and isinstance(v.get("redirect_uris"), list)}
            return self._clients

    def _save_clients(self) -> None:
        with self.lock:
            atomic_write_json(self.dir / "clients.json", {"clients": self.clients()})

    def grants(self) -> dict[str, dict[str, Any]]:
        with self.lock:
            if self._grants is None:
                raw = read_json(self.dir / "grants.json", {}) or {}
                rows = raw.get("connections") if isinstance(raw, dict) else None
                self._grants = {k: v for k, v in (rows or {}).items() if isinstance(k, str) and isinstance(v, dict)
                                and isinstance(v.get("access"), dict) and isinstance(v.get("refresh"), dict)}
            return self._grants

    def _save_grants(self) -> None:
        with self.lock:
            atomic_write_json(self.dir / "grants.json", {"connections": self.grants()})

    # ------------------------------------------------------------ 기록
    def _iso(self, ts: float | None = None) -> str:
        return datetime.fromtimestamp(self.clock() if ts is None else ts).astimezone().isoformat(timespec="seconds")

    def audit(self, kind: str, text: str, result: str = "ok", **fields: Any) -> None:
        """감사 로그 한 줄 (추가만). 값(토큰·코드·본문)은 절대 넣지 않는다 — 글은 고정 문장 + 이름뿐. 분당 상한을 넘으면 줄인다."""
        with self.lock:
            now = self.clock()
            minute, written, skipped = self._audit_minute
            if minute != int(now // 60):
                if skipped:
                    append_jsonl(self.dir / "audit.jsonl", {"at": self._iso(now), "type": "audit.skipped", "result": "ok",
                                                          "text": f"기록이 너무 많아 {skipped}건은 적지 않았어요"})
                minute, written, skipped = int(now // 60), 0, 0
            if written >= AUDIT_PER_MINUTE:
                self._audit_minute = (minute, written, skipped + 1)
                return
            rec: dict[str, Any] = {"at": self._iso(now), "type": kind, "result": result, "text": text[:200]}
            for k in ("who", "conn", "tool"):
                if fields.get(k):
                    rec[k] = str(fields[k])[:80]
            append_jsonl(self.dir / "audit.jsonl", rec)
            self._audit_minute = (minute, written + 1, skipped)

    def audit_tail(self, limit: int = 20) -> list[dict[str, Any]]:
        path = self.dir / "audit.jsonl"
        try:
            size = path.stat().st_size
            with open(path, "rb") as f:
                f.seek(max(0, size - 65536))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in tail.splitlines()[-limit * 3:]:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                rows.append({k: rec.get(k) for k in ("at", "type", "text", "result", "who", "conn", "tool") if rec.get(k) is not None})
        return list(reversed(rows[-limit:]))

    def _event(self, kind: str, message: str) -> None:
        self.store.event(kind, message)

    # ------------------------------------------------------------ 켜기·끄기
    def allowed_hosts(self) -> set[str]:
        s = self.settings()
        hosts: set[str] = set()
        if self.port:
            hosts |= {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if s["public_url"]:
            hp = s["public_url"][len("https://"):]
            hosts.add(hp)
            if ":" not in hp:
                hosts.add(hp + ":443")
        return hosts

    def allowed_origins(self) -> set[str]:
        s = self.settings()
        origins = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"} if self.port else set()
        if s["public_url"]:
            origins.add(s["public_url"])
        return origins

    def running(self) -> bool:
        return self.server is not None

    def start(self) -> None:
        with self.lock:
            if self.server:
                return
            s = self.settings()
            port = self.bind_port if self.bind_port is not None else s["port"]
            try:
                srv = GatewayServer(self, port)
            except OSError as exc:
                raise ValueError(f"포트 {port}을(를) 열 수 없어요. 다른 프로그램이 쓰고 있을 수 있어요: {exc}") from exc
            self.server, self.port = srv, srv.server_address[1]
            self.thread = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, name="studio-gateway", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        with self.lock:
            srv, thread, self.server, self.thread = self.server, self.thread, None, None
            self.port = 0
        if srv:
            srv.shutdown()
            srv.server_close()
            if thread:
                thread.join(5)

    def autostart(self) -> str:
        """서버가 켜질 때: 켜 두었으면 다시 연다 (터널이 없으면 어차피 안 닿는다). 실패해도 대시보드는 계속 뜬다."""
        s = self.settings()
        if not s["enabled"]:
            return ""
        try:
            self.start()
        except ValueError as exc:
            self._event("gateway.failed", f"외부 연결 문을 열지 못했어요: {exc}")
            self.audit("gateway.failed", "외부 연결 문을 열지 못했어요", "error")
            return str(exc)
        self.audit("gateway.started", "서버를 켤 때 외부 연결 문을 다시 열었어요")
        return ""

    # ------------------------------------------------------------ 대시보드 쪽 (CEO만)
    def status(self) -> dict[str, Any]:
        s = self.settings()
        now = self.clock()
        perm = s["permissions"]
        rows = []
        for conn in self.grants().values():
            granted = [x for x in conn.get("scope", []) if x in SCOPES]
            effective = [x for x in granted if x != SCOPE_SUBMIT or perm["submit"]]
            rows.append({"id": conn["id"], "name": clean_name(conn.get("client_name")), "granted": granted, "scopes": effective,
                         "created": conn.get("created"), "last_used": conn.get("last_used"), "created_ts": conn.get("created_ts"),
                         "last_used_ts": conn.get("last_used_ts"), "refresh_exp": conn.get("refresh", {}).get("exp")})
        rows.sort(key=lambda r: r.get("last_used_ts") or r.get("created_ts") or 0, reverse=True)
        projects = [{"key": p.key, "title": p.title, "kind": p.kind, "default_allowed_paths": list(p.default_allowed_paths)}
                    for p in self.cfg.projects.values()]
        with self.lock:
            code_alive = any(t > now for t in self._codes.values())
        return {"enabled": s["enabled"], "running": self.running(), "port": self.port or (self.bind_port if self.bind_port else s["port"]),
                "public_url": s["public_url"], "mcp_url": s["public_url"] + "/mcp" if s["public_url"] else "",
                "permissions": perm, "projects": projects, "connections": rows, "code_active": code_alive,
                "extra_redirects": s["extra_redirects"], "default_redirects": sorted(DEFAULT_REDIRECTS) + [
                    "https://chatgpt.com/connector/oauth/<영문·숫자>", "http://127.0.0.1:<포트>/…", "http://localhost:<포트>/…"],
                "scopes": list(SCOPES), "audit": self.audit_tail(20), "now": now}

    def configure(self, body: dict[str, Any]) -> dict[str, Any]:
        """켜기·끄기, 공개 주소, 포트, 추가 허용 주소. 한 번에 하나만 바뀌어도 되고 여러 칸을 같이 보내도 된다."""
        if not isinstance(body, dict) or set(body) - {"enabled", "public_url", "port", "extra_redirects"}:
            raise ValueError("알 수 없는 설정이 들어 있어요.")
        with self.lock:
            cur = self.settings()
            new = json.loads(json.dumps(cur))
            if "public_url" in body:
                raw = body["public_url"]
                new["public_url"] = "" if raw in ("", None) else parse_public_url(raw)
            if "port" in body:
                port = body["port"]
                if type(port) is not int or not 1024 <= port <= 65535:
                    raise ValueError("포트는 1024~65535 사이 숫자여야 해요.")
                new["port"] = port
            if "extra_redirects" in body:
                new["extra_redirects"] = parse_extra_redirects(body["extra_redirects"])
            enabled = body.get("enabled", cur["enabled"])
            if type(enabled) is not bool:
                raise ValueError("켜기·끄기는 true 또는 false여야 해요.")
            if enabled and not new["public_url"]:
                raise ValueError("공개 주소를 먼저 넣어 주세요. 터널 프로그램이 알려 준 https:// 주소예요.")
            url_changed = cur["public_url"] != new["public_url"]
            port_changed = cur["port"] != new["port"] and self.bind_port is None
            was_running = self.running()
            if url_changed and cur["public_url"] and self.grants():
                n = self._revoke_all("공개 주소가 바뀌어서 연결을 모두 끊었어요")
                self._event("gateway.url", f"외부 연결 공개 주소 변경 · 연결 {n}개 끊음")
            if enabled and (not was_running or port_changed):
                if was_running:
                    self.stop()
                new["enabled"] = True
                self._save_settings(new)
                try:
                    self.start()
                except ValueError:
                    new["enabled"] = False
                    self._save_settings(new)
                    raise
                self.audit("gateway.enabled", "외부 연결을 켰어요")
                self._event("gateway.enabled", "외부 연결 문 켬 (이 PC 127.0.0.1에만 열림)")
            elif not enabled and (was_running or cur["enabled"]):
                self.stop()
                new["enabled"] = False
                self._save_settings(new)
                self._codes.clear()
                self.audit("gateway.disabled", "외부 연결을 껐어요")
                self._event("gateway.disabled", "외부 연결 문 끔")
            else:
                new["enabled"] = enabled
                self._save_settings(new)
                if url_changed:
                    self.audit("gateway.url", "공개 주소를 바꿨어요")
        return self.status()

    def set_permissions(self, body: dict[str, Any]) -> dict[str, Any]:
        """권한 정하기: 열어 줄 프로젝트와 폴더 범위(기존 grant 검사 `projects.path_list` 그대로), 일 맡기기 허용 여부."""
        if not isinstance(body, dict) or set(body) - {"submit", "projects"}:
            raise ValueError("알 수 없는 권한 설정이 들어 있어요.")
        submit = body.get("submit", False)
        raw = body.get("projects", {})
        if type(submit) is not bool or not isinstance(raw, dict) or len(raw) > 50:
            raise ValueError("권한 설정 모양이 맞지 않아요.")
        projects: dict[str, dict[str, Any]] = {}
        for key, spec in raw.items():
            project = self.cfg.projects.get(key) if isinstance(key, str) else None
            if not project:
                raise ValueError(f"등록되지 않은 프로젝트예요: {str(key)[:40]}")
            if not isinstance(spec, dict) or set(spec) - {"paths", "write", "run"} or type(spec.get("write", True)) is not bool or type(spec.get("run", False)) is not bool:
                raise ValueError("프로젝트 권한 모양이 맞지 않아요.")
            if spec.get("run", False) and not spec.get("write", True):
                raise ValueError("실행 시작은 '일 맡기기'를 켠 프로젝트에서만 켤 수 있어요.")
            paths = spec.get("paths")
            projects[key] = {"paths": projects_mod.path_list(paths if paths else list(project.default_allowed_paths), project),
                             "write": spec.get("write", True), "run": spec.get("run", False)}
        with self.lock:
            new = self.settings()
            new["permissions"] = {"submit": submit, "projects": projects}
            self._save_settings(new)
        label = "일 맡기기까지 허용" if submit else "읽기만 허용"
        writable = sum(1 for spec in projects.values() if spec["write"]) if submit else 0
        runnable = sum(1 for spec in projects.values() if spec["run"]) if submit else 0
        counts = f" (일 맡기기 {writable}개, 실행 시작 {runnable}개)" if submit else ""
        self.audit("permissions.changed", f"권한을 바꿨어요: {label} · 프로젝트 {len(projects)}개" + counts)
        self._event("gateway.permissions", f"외부 연결 권한 변경: {label}, 프로젝트 {len(projects)}개" + counts)
        return self.status()

    def new_code(self) -> dict[str, Any]:
        """연결 번호 (5분 · 한 번). 메모리에만 둔다 — 서버를 다시 켜면 사라진다."""
        if not self.running():
            raise ValueError("먼저 '외부 연결 받기'를 켜 주세요. 켜져 있어야 연결 번호를 쓸 수 있어요.")
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        with self.lock:
            now = self.clock()
            self._codes = {c: t for c, t in self._codes.items() if t > now}
            self._codes[code] = now + CODE_TTL
        self.audit("code.created", "연결 번호를 만들었어요")
        self._event("gateway.code", "외부 연결 번호 만듦")
        return {"code": f"{code[:4]}-{code[4:]}", "expires_in": CODE_TTL}

    def revoke(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) - {"id", "all"}:
            raise ValueError("끊을 연결을 알려 주세요.")
        if body.get("all") is True:
            n = self._revoke_all("사장님이 모든 연결을 끊었어요")
            self._event("gateway.revoked", f"외부 연결 모두 끊음 ({n}개)")
        else:
            conn_id = body.get("id")
            if not isinstance(conn_id, str) or conn_id not in self.grants():
                raise ValueError("그런 연결이 없어요. 이미 끊겼을 수 있어요.")
            name = self._revoke(conn_id, "사장님이 연결을 끊었어요")
            self._event("gateway.revoked", f"외부 연결 끊음: {name}")
        return self.status()

    def _revoke(self, conn_id: str, why: str) -> str:
        with self.lock:
            conn = self.grants().pop(conn_id, None)
            if not conn:
                return ""
            self._save_grants()
            for h, (cid, _) in list(self._used.items()):
                if cid == conn_id:
                    self._used[h] = (cid, self._used[h][1])
        name = clean_name(conn.get("client_name"))
        self.audit("connection.revoked", f"{why}: {name}", who=name, conn=conn_id[:6])
        return name

    def _revoke_all(self, why: str) -> int:
        with self.lock:
            ids = list(self.grants())
            for cid in ids:
                self._revoke(cid, why)
            return len(ids)

    # ------------------------------------------------------------ 정리
    def _purge(self, now: float) -> None:
        with self.lock:
            self._codes = {c: t for c, t in self._codes.items() if t > now}
            self._auth = {h: r for h, r in self._auth.items() if r["exp"] > now}
            self._used = {h: v for h, v in self._used.items() if v[1] > now}
            self._forms = {h: f for h, f in self._forms.items() if f["exp"] > now}

    def _prune_clients(self, now: float) -> None:
        live = {c.get("client_id") for c in self.grants().values()}
        with self.lock:
            clients = self.clients()
            gone = [cid for cid, c in clients.items() if cid not in live
                    and now - float(c.get("last_used_ts") or c.get("created_ts") or 0) > (CLIENT_IDLE_S if c.get("last_used_ts") else CLIENT_IDLE_NEVER_S)]
            for cid in gone:
                clients.pop(cid, None)
            if gone:
                self._save_clients()

    # ------------------------------------------------------------ 메타데이터
    def protected_resource(self, mcp_path: bool) -> dict[str, Any]:
        s = self.settings()
        url = s["public_url"]
        return {"resource": url + ("/mcp" if mcp_path else ""), "authorization_servers": [url],
                "scopes_supported": list(SCOPES), "bearer_methods_supported": ["header"]}

    def authorization_server(self) -> dict[str, Any]:
        url = self.settings()["public_url"]
        return {"issuer": url, "authorization_endpoint": url + "/oauth/authorize", "token_endpoint": url + "/oauth/token",
                "registration_endpoint": url + "/oauth/register", "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"], "scopes_supported": list(SCOPES),
                "authorization_response_iss_parameter_supported": True}

    def www_authenticate(self) -> str:
        s = self.settings()
        scope = SCOPE_READ + (" " + SCOPE_SUBMIT if s["permissions"]["submit"] else "")  # 일 맡기기를 열었으면 클라이언트가 그 권한도 요청하게 알린다
        return f'Bearer resource_metadata="{s["public_url"]}/.well-known/oauth-protected-resource", scope="{scope}"'

    # ------------------------------------------------------------ 동적 등록 (RFC 7591)
    def register(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise OAuthError("invalid_client_metadata", "JSON 객체가 필요해요.")
        uris = body.get("redirect_uris")
        if not isinstance(uris, list) or not 1 <= len(uris) <= 5 or not all(isinstance(u, str) for u in uris):
            raise OAuthError("invalid_redirect_uri", "redirect_uris는 1~5개 목록이어야 해요.")
        extra = self.settings()["extra_redirects"]
        if not all(redirect_allowed(u, extra) for u in uris):
            raise OAuthError("invalid_redirect_uri", "허용되지 않은 redirect 주소가 있어요.")
        method = body.get("token_endpoint_auth_method", "none")
        if method != "none":
            raise OAuthError("invalid_client_metadata", "token_endpoint_auth_method는 none만 지원해요.")
        grants = body.get("grant_types", ["authorization_code"])
        if not isinstance(grants, list) or not grants or not set(grants) <= {"authorization_code", "refresh_token"}:
            raise OAuthError("invalid_client_metadata", "grant_types는 authorization_code, refresh_token만 지원해요.")
        responses = body.get("response_types", ["code"])
        if not isinstance(responses, list) or responses != ["code"]:
            raise OAuthError("invalid_client_metadata", "response_types는 code만 지원해요.")
        scope = body.get("scope", SCOPE_READ)
        if not isinstance(scope, str) or not set(scope.split()) <= set(SCOPES):
            raise OAuthError("invalid_client_metadata", "알 수 없는 scope가 있어요.")
        name = clean_name(body.get("client_name"))
        now = self.clock()
        with self.lock:
            self._prune_clients(now)
            clients = self.clients()
            if len(clients) >= MAX_CLIENTS:
                live = {c.get("client_id") for c in self.grants().values()}
                idle = sorted((c.get("created_ts", 0), cid) for cid, c in clients.items() if cid not in live)
                if not idle:
                    raise OAuthError("temporarily_unavailable", "등록된 앱이 너무 많아요. 사장님이 연결을 정리해야 해요.", 429)
                clients.pop(idle[0][1], None)
            client_id = secrets.token_urlsafe(16)
            ordered = list(dict.fromkeys(uris))
            clients[client_id] = {"client_id": client_id, "client_name": name, "redirect_uris": ordered,
                                  "created": self._iso(now), "created_ts": now}
            self._save_clients()
        self.audit("client.registered", f"앱이 등록을 요청했어요: {name}", who=name)
        return {"client_id": client_id, "client_id_issued_at": int(now), "client_name": name, "redirect_uris": ordered,
                "grant_types": ["authorization_code", "refresh_token"] if "refresh_token" in grants else ["authorization_code"],
                "response_types": ["code"], "token_endpoint_auth_method": "none", "scope": scope}

    # ------------------------------------------------------------ 인증 요청 (동의 화면)
    def _resource_ok(self, value: str | None) -> bool:
        if value is None:
            return True
        url = self.settings()["public_url"]
        return bool(url) and value.rstrip("/") in (url, url + "/mcp")

    def validate_authorize(self, q: dict[str, str]) -> dict[str, Any]:
        """앞쪽 오류(앱·redirect 주소를 못 믿음)는 FatalAuthorize, 나머지는 앱으로 돌려보내는 Redirectable."""
        s = self.settings()
        if not s["public_url"]:
            raise FatalAuthorize("외부 연결 문의 공개 주소가 아직 정해지지 않았어요.")
        client = self.clients().get(q.get("client_id") or "")
        if not client:
            raise FatalAuthorize("등록되지 않은 앱이에요. 앱에서 연결을 처음부터 다시 시작해 주세요.")
        uri = q.get("redirect_uri")
        if not uri or uri not in client["redirect_uris"] or not redirect_allowed(uri, s["extra_redirects"]):
            raise FatalAuthorize("앱이 알려 준 연결 주소가 등록할 때 적은 것과 달라요.")
        state = q.get("state")
        if state is not None and len(state) > 1024:
            raise FatalAuthorize("state 값이 너무 길어요.")

        def fail(code: str, desc: str) -> Redirectable:
            return Redirectable(code, desc, uri, state)

        if q.get("response_type") != "code":
            raise fail("unsupported_response_type", "response_type은 code만 지원해요.")
        challenge = q.get("code_challenge")
        if not challenge or not CHALLENGE.fullmatch(challenge):
            raise fail("invalid_request", "PKCE code_challenge가 필요해요.")
        if q.get("code_challenge_method") != "S256":
            raise fail("invalid_request", "code_challenge_method는 S256만 지원해요.")
        asked = (q.get("scope") or SCOPE_READ).split()
        if not asked or not set(asked) <= set(SCOPES):
            raise fail("invalid_scope", "알 수 없는 scope예요.")
        resource = q.get("resource")
        if not self._resource_ok(resource):
            raise fail("invalid_target", "resource는 이 서버 주소여야 해요.")
        scope = [SCOPE_READ] + ([SCOPE_SUBMIT] if SCOPE_SUBMIT in asked else [])
        return {"client_id": client["client_id"], "client_name": client["client_name"], "redirect_uri": uri, "state": state,
                "challenge": challenge, "scope": scope, "resource": resource}

    def new_form(self, req: dict[str, Any]) -> str:
        form_id = secrets.token_urlsafe(24)
        with self.lock:
            now = self.clock()
            self._purge(now)
            if len(self._forms) >= MAX_FORMS:
                oldest = min(self._forms, key=lambda h: self._forms[h]["exp"])
                self._forms.pop(oldest, None)
            self._forms[_hash(form_id)] = {"req": req, "exp": now + FORM_TTL}
        return form_id

    def form(self, form_id: str | None) -> dict[str, Any] | None:
        if not form_id:
            return None
        with self.lock:
            self._purge(self.clock())
            f = self._forms.get(_hash(form_id))
            return f["req"] if f else None

    def drop_form(self, form_id: str) -> None:
        with self.lock:
            self._forms.pop(_hash(form_id), None)

    def check_number(self, code: str) -> str:
        """연결 번호 확인: 'ok' · 'wrong' · 'locked'. 번호는 한 번만 쓴다. 5번 틀리면 1분 동안 모든 시도를 막는다 (remote.py와 같은 방식)."""
        norm = re.sub(r"[^A-Z0-9]", "", str(code or "").upper())
        with self.lock:
            now = self.clock()
            if now < self._locked_until:
                return "locked"
            expires = self._codes.pop(norm, 0) if norm else 0
            if expires <= now:
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    self._fails, self._locked_until = 0, now + LOCK_S
                return "wrong"
            self._fails = 0
            return "ok"

    def lock_left(self) -> int:
        return max(0, int(self._locked_until - self.clock() + 0.999))

    def make_code(self, req: dict[str, Any]) -> str:
        code = secrets.token_urlsafe(32)
        with self.lock:
            now = self.clock()
            self._purge(now)
            self._auth[_hash(code)] = {**req, "exp": now + AUTH_CODE_TTL}
        return code

    def effective_scope(self, scope: list[str]) -> list[str]:
        """토큰에 담는 권한: 요청한 것 중 지금 CEO 설정이 허용하는 것만 (읽기는 늘 있다)."""
        allowed = self.settings()["permissions"]["submit"]
        return [x for x in scope if x == SCOPE_READ or (x == SCOPE_SUBMIT and allowed)]

    # ------------------------------------------------------------ 토큰
    def _new_tokens(self, conn: dict[str, Any], now: float) -> dict[str, Any]:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        scope = self.effective_scope(conn["scope"])
        conn["access"] = {"hash": _hash(access), "exp": now + ACCESS_TTL, "scope": scope}
        conn["refresh"] = {"hash": _hash(refresh), "exp": now + REFRESH_TTL}
        return {"access_token": access, "token_type": "Bearer", "expires_in": ACCESS_TTL, "refresh_token": refresh,
                "scope": " ".join(scope)}

    def token(self, params: dict[str, str]) -> dict[str, Any]:
        grant = params.get("grant_type")
        if grant == "authorization_code":
            return self._exchange(params)
        if grant == "refresh_token":
            return self._refresh(params)
        raise OAuthError("unsupported_grant_type", "authorization_code, refresh_token만 지원해요.")

    def _exchange(self, p: dict[str, str]) -> dict[str, Any]:
        client = self.clients().get(p.get("client_id") or "")
        if not client:
            raise OAuthError("invalid_client", "등록되지 않은 앱이에요.", 401)
        code, verifier = p.get("code"), p.get("code_verifier")
        if not code or not verifier or not VERIFIER.fullmatch(verifier):
            raise OAuthError("invalid_request", "code와 code_verifier(43~128자)가 필요해요.")
        h = _hash(code)
        with self.lock:
            now = self.clock()
            self._purge(now)
            rec = self._auth.pop(h, None)  # 맞든 틀리든 이 코드는 여기서 끝난다 (한 번만)
            if rec is None:
                used = self._used.get(h)
                if used:  # 이미 쓴 코드가 다시 왔다: 그 코드로 나간 토큰을 거두는 게 안전하다 (RFC 6749 4.1.2)
                    name = self._revoke(used[0], "이미 쓴 인증 코드가 다시 쓰여서 연결을 끊었어요")
                    self._event("gateway.reuse", f"외부 연결: 인증 코드 재사용 감지 · 연결 끊음 ({name})")
                raise OAuthError("invalid_grant", "인증 코드가 맞지 않거나 이미 썼거나 시간이 지났어요.")
            if rec["client_id"] != client["client_id"] or p.get("redirect_uri") != rec["redirect_uri"]:
                raise OAuthError("invalid_grant", "인증 코드가 이 앱·주소에서 받은 것이 아니에요.")
            resource = p.get("resource")
            if resource is not None and (not self._resource_ok(resource) or (rec["resource"] and resource.rstrip("/") != rec["resource"].rstrip("/"))):
                raise OAuthError("invalid_target", "resource가 인증 요청 때와 달라요.")
            if not hmac.compare_digest(pkce_challenge(verifier), rec["challenge"]):
                raise OAuthError("invalid_grant", "PKCE 확인에 실패했어요.")
            url = self.settings()["public_url"]
            if not url:
                raise OAuthError("invalid_grant", "외부 연결 문이 닫혀 있어요.")
            grants = self.grants()
            for cid, old in sorted(((c, v) for c, v in grants.items() if v.get("refresh", {}).get("exp", 0) <= now),
                                   key=lambda x: x[1].get("created_ts", 0)):
                grants.pop(cid, None)
            while len(grants) >= MAX_CONNECTIONS:  # 가장 오래 안 쓴 연결부터 내보낸다
                oldest = min(grants, key=lambda c: grants[c].get("last_used_ts") or grants[c].get("created_ts") or 0)
                self._revoke(oldest, "연결이 너무 많아 가장 오래 안 쓴 연결을 정리했어요")
            conn_id = secrets.token_hex(6)
            conn = {"id": conn_id, "client_id": client["client_id"], "client_name": client["client_name"],
                    "scope": self.effective_scope(rec["scope"]), "aud": url, "created": self._iso(now), "created_ts": now,
                    "last_used": None, "last_used_ts": None, "old_refresh": []}
            tokens = self._new_tokens(conn, now)
            grants[conn_id] = conn
            self._used[h] = (conn_id, now + USED_CODE_KEEP)
            client["last_used_ts"] = now
            self._save_grants()
            self._save_clients()
        self.audit("token.issued", f"토큰을 발급했어요: {client['client_name']}", who=client["client_name"], conn=conn_id[:6])
        self._event("gateway.connected", f"외부 앱 연결됨: {client['client_name']} ({tokens['scope']})")
        return tokens

    def _refresh(self, p: dict[str, str]) -> dict[str, Any]:
        token = p.get("refresh_token")
        if not token or not 32 <= len(token) <= 512:
            raise OAuthError("invalid_request", "refresh_token이 필요해요.")
        h = _hash(token)
        with self.lock:
            now = self.clock()
            grants = self.grants()
            for conn in grants.values():
                if hmac.compare_digest(conn["refresh"]["hash"], h):
                    break
                if any(hmac.compare_digest(old, h) for old in conn.get("old_refresh", [])):
                    name = self._revoke(conn["id"], "이미 쓴 새로고침 토큰이 다시 쓰여서 연결을 끊었어요")
                    self._event("gateway.reuse", f"외부 연결: 새로고침 토큰 재사용 감지 · 연결 끊음 ({name})")
                    raise OAuthError("invalid_grant", "새로고침 토큰이 맞지 않아요. 앱에서 다시 연결해 주세요.")
            else:
                raise OAuthError("invalid_grant", "새로고침 토큰이 맞지 않아요. 앱에서 다시 연결해 주세요.")
            url = self.settings()["public_url"]
            if conn["refresh"]["exp"] <= now or conn["client_id"] != p.get("client_id") or conn["aud"] != url:
                raise OAuthError("invalid_grant", "새로고침 토큰이 맞지 않거나 시간이 지났어요. 앱에서 다시 연결해 주세요.")
            resource = p.get("resource")
            if resource is not None and not self._resource_ok(resource):
                raise OAuthError("invalid_target", "resource는 이 서버 주소여야 해요.")
            asked = p.get("scope")
            if asked is not None and not set(asked.split()) <= set(conn["scope"]):
                raise OAuthError("invalid_scope", "처음 허용한 것보다 넓은 권한은 받을 수 없어요.")
            conn["old_refresh"] = (conn.get("old_refresh", []) + [conn["refresh"]["hash"]])[-5:]
            tokens = self._new_tokens(conn, now)
            if asked is not None:  # 좁히기만 허용: 이번 토큰은 요청한 만큼만
                conn["access"]["scope"] = self.effective_scope(asked.split())
                tokens["scope"] = " ".join(conn["access"]["scope"])
            self._save_grants()
        self.audit("token.refreshed", f"토큰을 새로 받았어요: {conn['client_name']}", who=conn["client_name"], conn=conn["id"][:6])
        return tokens

    # ------------------------------------------------------------ MCP 입구
    def verify_access(self, header_values: list[str]) -> tuple[dict[str, Any], set[str]]:
        """Authorization 헤더 → (연결, 지금 유효한 권한). 토큰은 믿지 않는 입력: 해시 조회·만료·대상(aud)을 매번 본다."""
        if len(header_values) != 1 or not header_values[0].startswith("Bearer "):
            raise AuthError()
        token = header_values[0][7:]
        if not 32 <= len(token) <= 512 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
            raise AuthError()
        h = _hash(token)
        with self.lock:
            now = self.clock()
            url = self.settings()["public_url"]
            for conn in self.grants().values():
                if hmac.compare_digest(conn["access"]["hash"], h):
                    if conn["access"]["exp"] <= now or not url or conn.get("aud") != url:
                        raise AuthError()
                    if now - self._touch.get(conn["id"], 0) >= LAST_USED_WRITE_S:
                        self._touch[conn["id"]] = now
                        conn["last_used"], conn["last_used_ts"] = self._iso(now), now
                        self._save_grants()
                    # Older tokens predate token-specific scope; retain their grant limit.
                    scope = conn["access"].get("scope", conn["scope"])
                    return conn, set(self.effective_scope([s for s in scope if s in conn["scope"]]))
        raise AuthError()

    def actor_for(self, conn: dict[str, Any], scopes: set[str]) -> dict[str, Any]:
        """연결 신분: 기존 감독 권한과 같은 모양({id, projects:{키:{read,write,run,paths}}}). 일 맡기기는 `studio:submit`이 있고
        그 프로젝트에 CEO가 일 맡기기를 열었을 때만 write, 실행 시작(run)은 거기에 CEO가 '실행 시작'까지 켰을 때만."""
        perm = self.settings()["permissions"]
        projects = {}
        for key, spec in perm["projects"].items():
            if key not in self.cfg.projects:
                continue
            write = SCOPE_SUBMIT in scopes and spec.get("write", True) is True
            projects[key] = {"read": True, "write": write, "run": write and spec.get("run") is True, "paths": list(spec["paths"])}
        return {"id": "gateway-" + conn["id"], "projects": projects}

    def tools_for(self, scopes: set[str]) -> set[str]:
        """이 요청에 보일 도구. run_task는 `studio:submit`이 있고 *지금 설정에서* 실행 시작이 켜진 프로젝트가 있을 때만 (설정을 줄이면 바로 사라진다)."""
        names = set(READ_TOOLS)
        if SCOPE_SUBMIT in scopes:
            names |= set(SUBMIT_TOOLS)
            projects = self.settings()["permissions"]["projects"]
            if not any(spec.get("write") is True and spec.get("run") is True and key in self.cfg.projects for key, spec in projects.items()):
                names.discard("run_task")
        return names


class _ActorCaller:
    """`supervisor_mcp_http.post`가 `supervisor.call(인증글, 요청)`으로 부르는 자리에 들어가는 얇은 연결:
    인증은 이미 끝났으므로 `Supervisor.call_as`로 같은 권한 검사만 하고, 도구 이름·결과 종류만 감사 로그에 남긴다 (내용은 안 남김)."""

    def __init__(self, gateway: Gateway, conn: dict[str, Any], scopes: set[str], actor: dict[str, Any]):
        self.gateway, self.conn, self.scopes, self.actor = gateway, conn, scopes, actor

    def call(self, _authorization: str, request: dict[str, Any]) -> dict[str, Any]:
        gw = self.gateway
        tool = OP_TOOL.get(request.get("operation"), "unknown")
        who = clean_name(self.conn.get("client_name"))
        try:
            result = Supervisor(gw.engine).call_as(self.actor, request)
        except AccessError:
            gw.audit("tool.denied", f"도구 호출을 거절했어요: {tool}", "denied", who=who, conn=self.conn["id"][:6], tool=tool)
            raise
        gw.audit("tool.call", f"도구를 불렀어요: {tool}", "ok", who=who, conn=self.conn["id"][:6], tool=tool)
        return result


# ---------------------------------------------------------------- HTTP
CONSENT_CSS = """
:root{color-scheme:light;--ink:#14161b;--soft:#4b5260;--faint:#626977;--bg:#e7e9ee;--card:#fff;--tint:#f3f4f6;--accent:#4f46e5;--bad:#b91c1c;--badbg:#fee2e2;--warn:#92400e;--warnbg:#fef3c7}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--bg);color:var(--ink);font:16px/1.5 "Segoe UI Variable Text","Segoe UI","Malgun Gothic","맑은 고딕","Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif;word-break:keep-all;overflow-wrap:anywhere}
main{width:min(560px,100%);padding:28px 28px 24px;border-radius:28px;background:var(--card);box-shadow:0 8px 24px rgba(17,24,39,.10),0 2px 6px rgba(17,24,39,.06)}
h1{margin:0 0 4px;font-size:24px;letter-spacing:-.02em;line-height:1.3}
.sub{margin:0 0 16px;color:var(--soft)}
.app{padding:14px 16px;border-radius:20px;background:var(--tint)}
.app b{display:block;font-size:20px}
.app span{display:block;margin-top:2px;color:var(--faint);font-size:13px}
dl{margin:16px 0 0}
dt{margin-top:12px;color:var(--soft);font-size:13px;font-weight:700}
dd{margin:2px 0 0;font-size:15px}
dd.url{font-family:Consolas,"Cascadia Mono",monospace;font-size:13px}
ul{margin:4px 0 0;padding-left:20px}
.cap{margin:16px 0 0;padding:10px 14px;border-radius:14px;background:var(--warnbg);color:var(--warn);font-size:14px}
label{display:block;margin:20px 0 6px;font-weight:700}
input[type=text]{width:100%;height:52px;padding:0 16px;border:1px solid rgba(17,24,39,.16);border-radius:14px;background:#fff;color:var(--ink);font:700 24px/1 Consolas,"Cascadia Mono",monospace;letter-spacing:.14em;text-transform:uppercase}
input[type=text]:focus{outline:3px solid rgba(99,102,241,.45);outline-offset:1px}
.hint{margin:6px 0 0;color:var(--faint);font-size:13px}
.err{margin:12px 0 0;padding:10px 14px;border-radius:14px;background:var(--badbg);color:var(--bad);font-size:14px;font-weight:600}
.row{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}
button{height:48px;padding:0 22px;border:0;border-radius:999px;font:700 16px/1 inherit;cursor:pointer}
button.go{background:#16181d;color:#fff}
button.no{background:var(--tint);color:var(--ink)}
button:focus-visible{outline:3px solid rgba(99,102,241,.6);outline-offset:2px}
button:disabled{opacity:.5;cursor:not-allowed}
.small{margin:16px 0 0;color:var(--faint);font-size:13px}
"""

SCOPE_TEXT = {SCOPE_READ: "일의 목록·상태·진행·결과 파일 읽기",
              SCOPE_SUBMIT: "일 맡기기, 이 앱이 맡긴 일 취소하기 (사장님이 허용한 프로젝트는 실행 시작도)"}


def _page(title: str, body: str) -> bytes:
    return ("<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<meta name=\"robots\" content=\"noindex\"><title>" + html.escape(title) + "</title>"
            "<link rel=\"stylesheet\" href=\"/oauth/consent.css\"></head><body><main>" + body + "</main></body></html>").encode("utf-8")


def consent_page(gw: Gateway, req: dict[str, Any], form_id: str, error: str = "", locked: int = 0) -> bytes:
    e = html.escape
    allowed = gw.effective_scope(req["scope"])
    items = "".join(f"<li>{e(SCOPE_TEXT[s])}</li>" for s in allowed)
    cut = ""
    if SCOPE_SUBMIT in req["scope"] and SCOPE_SUBMIT not in allowed:
        cut = "<p class=\"cap\">이 앱은 '일 맡기기'도 요청했지만, 사장님 설정이 '읽기만'이라 이번에는 읽기만 허용돼요.</p>"
    err = f"<p class=\"err\" role=\"alert\">{e(error)}</p>" if error else ""
    off = " disabled" if locked else ""
    body = (
        "<h1>이 앱을 AI 스튜디오에 연결할까요?</h1>"
        "<p class=\"sub\">사장님이 방금 연결하려던 앱이 맞을 때만 허용하세요.</p>"
        f"<div class=\"app\"><b>{e(clean_name(req['client_name']))}</b>"
        "<span>이 이름은 앱이 스스로 적은 것이라 진짜인지 알 수 없어요.</span></div>"
        "<dl><dt>허용하려는 일</dt><dd><ul>" + items + "</ul></dd>"
        f"<dt>연결이 끝나면 돌아갈 주소</dt><dd class=\"url\">{e(req['redirect_uri'])}</dd></dl>"
        + cut +
        "<p class=\"small\">결재와 완료는 항상 사장님이 AI 스튜디오에서 직접 해요. 연결한 앱은 결재할 수 없어요. 언제든 '외부 연결' 화면에서 끊을 수 있어요.</p>"
        "<form method=\"post\" action=\"/oauth/authorize\" autocomplete=\"off\">"
        f"<input type=\"hidden\" name=\"form_id\" value=\"{e(form_id)}\">"
        "<label for=\"code\">연결 번호</label>"
        f"<input id=\"code\" name=\"code\" type=\"text\" inputmode=\"text\" maxlength=\"12\" autocomplete=\"off\" autocapitalize=\"characters\" spellcheck=\"false\" placeholder=\"ABCD-EFGH\"{off}>"
        "<p class=\"hint\">AI 스튜디오의 '외부 연결' 화면에서 [연결 번호 만들기]를 누르면 나와요. 5분 동안, 한 번만 쓸 수 있어요.</p>"
        + err +
        "<div class=\"row\">"
        f"<button class=\"go\" type=\"submit\" name=\"decision\" value=\"allow\"{off}>허용하고 연결</button>"
        "<button class=\"no\" type=\"submit\" name=\"decision\" value=\"deny\">거절</button></div></form>")
    return _page("AI 스튜디오 연결 허용", body)


def error_page(message: str) -> bytes:
    return _page("연결할 수 없어요", "<h1>연결할 수 없어요</h1><p class=\"err\" role=\"alert\">" + html.escape(message) +
                 "</p><p class=\"small\">앱에서 연결을 처음부터 다시 시작해 주세요. 계속 안 되면 AI 스튜디오의 '외부 연결' 화면을 확인하세요.</p>")


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"  # 윈도우의 SO_REUSEADDR은 이미 쓰는 포트를 가로챌 수 있어 끈다

    def __init__(self, gateway: Gateway, port: int):
        self.gateway = gateway
        self.store, self.engine = gateway.store, gateway.engine
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT)
        super().__init__(("127.0.0.1", port), GatewayHandler)  # 127.0.0.1에만 (인터넷 노출은 CEO가 따로 켜는 터널)

    def process_request(self, request, client_address):  # type: ignore[override]
        """동시 연결 제한: 자리가 없으면 바로 503으로 돌려보낸다 (느린 연결이 서버를 붙잡지 못하게)."""
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(0.05)
                try:
                    request.recv(65536)  # 이미 도착한 요청 글을 비운다 (안 읽고 닫으면 상대가 503을 못 받고 연결 중단을 본다)
                except OSError:
                    pass
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 5\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):  # type: ignore[override]
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    server_version = "AIStudioGateway"
    sys_version = ""
    timeout = 10

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    # ---- 공통 (supervisor_mcp_http.post가 쓰는 자리: _send, _read_body)
    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        # form-action은 일부러 두지 않는다: 동의 뒤 다른 앱 주소로 돌려보내는 이동을 브라우저가 막을 수 있다 (글·스크립트는 모두 막혀 있다)
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj: Any, extra: dict[str, str] | None = None) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _oauth_error(self, exc: OAuthError, extra: dict[str, str] | None = None) -> None:
        head = dict(extra or {})
        if exc.status == 401:
            head["WWW-Authenticate"] = 'Bearer error="invalid_client"'
        self._json(exc.status, {"error": exc.code, "error_description": exc.description}, head)

    def _html(self, status: int, body: bytes, extra: dict[str, str] | None = None) -> None:
        self._send(status, body, "text/html; charset=utf-8", extra)

    _body: bytes | None = None

    def _read_body(self, limit: int | None = None) -> bytes | None:
        """본문을 먼저 다 읽는다 (거절할 때도: 읽지 않은 본문이 남으면 윈도우가 연결을 끊어 버린다). 너무 크면 None.
        한 번 읽은 본문은 기억해 둔다 — `supervisor_mcp_http.post`가 같은 본문을 다시 읽으려 해도 멈추지 않게."""
        if self._body is not None:
            return self._body
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length > (MAX_BODY_MCP if limit is None else limit):
            self.close_connection = True
            self._drain(min(length, 2 * MAX_BODY_MCP))
            return None
        self._body = self.rfile.read(length) if length > 0 else b""
        return self._body

    def _drain(self, count: int) -> None:
        """거절하는 요청의 본문을 (상한까지만) 버리며 읽는다: 읽지 않은 채 닫으면 윈도우가 연결을 끊어 상대가 거절 답을 못 받는다."""
        try:
            while count > 0:
                chunk = self.rfile.read(min(65536, count))
                if not chunk:
                    break
                count -= len(chunk)
        except OSError:
            pass

    def _not_found(self) -> None:
        self._json(404, {"error": "not_found"})

    def _limited(self, key: Any, name: str) -> bool:
        gw = self.server.gateway
        limit, window = gw.limits[name]
        wait = gw.limiter.hit(key, limit, window)
        if wait:
            gw.audit("rate.limited", "요청이 너무 많아 잠깐 막았어요", "denied")
            self.close_connection = True
            self._json(429, {"error": "rate_limited", "error_description": "요청이 너무 많아요. 잠시 뒤에 다시 해 주세요."}, {"Retry-After": str(int(wait + 0.999))})
            return True
        return False

    # ---- 진입
    def do_GET(self) -> None:  # noqa: N802
        try:
            self._dispatch()
        except (BrokenPipeError, ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception:  # noqa: BLE001 - 어떤 오류도 내용을 밖에 내지 않는다 (글자 하나 없이 server_error만)
            self.close_connection = True
            try:
                self.server.gateway.audit("server.error", "연결 문에서 예상하지 못한 오류가 났어요", "error")
                self._json(500, {"error": "server_error"})
            except OSError:
                pass

    do_POST = do_GET  # noqa: N815
    do_DELETE = do_GET  # noqa: N815
    do_PUT = do_GET  # noqa: N815
    do_PATCH = do_GET  # noqa: N815
    do_HEAD = do_GET  # noqa: N815
    do_OPTIONS = do_GET  # noqa: N815  (CORS 사전 요청도 받지 않는다: 404)

    def _dispatch(self) -> None:
        gw = self.server.gateway
        self._body = None
        raw = self._read_body(MAX_BODY_MCP)
        if raw is None:
            return self._json(413, {"error": "request_too_large"})
        if (self.headers.get("Host") or "").lower() not in gw.allowed_hosts():
            return self._json(403, {"error": "forbidden_host"})
        url = urlparse(self.path)
        path, method, ip = url.path, self.command, self.client_address[0]
        if path == "/mcp":
            return self._mcp(method, url, raw)
        if len(raw) > MAX_BODY_OAUTH:
            return self._json(413, {"error": "request_too_large"})
        gw._purge(gw.clock())
        if method == "GET" and path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            return self._json(200, gw.protected_resource(path.endswith("/mcp")))
        if method == "GET" and path == "/.well-known/oauth-authorization-server":
            return self._json(200, gw.authorization_server())
        if method == "GET" and path == "/oauth/consent.css":
            return self._send(200, CONSENT_CSS.encode("utf-8"), "text/css; charset=utf-8")
        if path == "/oauth/register" and method == "POST":
            if self._limited(("register", ip), "register"):
                return None
            return self._register(raw)
        if path == "/oauth/authorize" and method in ("GET", "POST"):
            if self._limited(("oauth", ip), "oauth"):
                return None
            return self._authorize_get(url) if method == "GET" else self._authorize_post(raw)
        if path == "/oauth/token" and method == "POST":
            if self._limited(("oauth", ip), "oauth"):
                return None
            return self._token(raw)
        return self._not_found()

    # ---- /oauth/register
    def _body_params(self, raw: bytes) -> dict[str, str]:
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise OAuthError("invalid_request", "Transfer-Encoding은 지원하지 않아요.")
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        try:
            text = raw.decode("utf-8")
            if ctype == "application/json":
                data = json.loads(text, parse_constant=_no_constant)
                if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
                    raise ValueError()
                return data
            if ctype == "application/x-www-form-urlencoded":
                parsed = parse_qs(text, keep_blank_values=True, strict_parsing=bool(text), max_num_fields=40)
                if any(len(v) != 1 for v in parsed.values()):
                    raise ValueError()
                return {k: v[0] for k, v in parsed.items()}
        except (ValueError, UnicodeError):
            pass
        raise OAuthError("invalid_request", "요청 본문 형식이 맞지 않아요.")

    def _register(self, raw: bytes) -> None:
        gw = self.server.gateway
        try:
            if (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json" or self.headers.get("Transfer-Encoding"):
                raise OAuthError("invalid_client_metadata", "application/json 본문이 필요해요.")
            try:
                data = json.loads(raw.decode("utf-8"), parse_constant=_no_constant)
            except (ValueError, UnicodeError):
                raise OAuthError("invalid_client_metadata", "JSON 형식이 아니에요.") from None
            self._json(201, gw.register(data))
        except OAuthError as exc:
            if exc.code == "invalid_redirect_uri":
                gw.audit("client.refused", "등록을 거절했어요: 허용되지 않은 연결 주소", "denied")
            self._oauth_error(exc)

    # ---- /oauth/authorize
    def _redirect(self, uri: str, params: dict[str, Any]) -> None:
        gw = self.server.gateway
        query = {k: v for k, v in params.items() if v is not None}
        query["iss"] = gw.settings()["public_url"]  # 성공·오류 모든 응답에 (RFC 9207)
        self._send(302, b"", "text/plain; charset=utf-8", {"Location": uri + "?" + urlencode(query)})

    def _authorize_get(self, url) -> None:
        gw = self.server.gateway
        try:
            try:
                parsed = parse_qs(url.query, keep_blank_values=True, max_num_fields=40)
            except ValueError:
                raise FatalAuthorize("요청 항목이 너무 많아요.") from None
            if any(len(v) != 1 for v in parsed.values()):
                raise FatalAuthorize("같은 항목이 두 번 들어 있어요.")
            req = gw.validate_authorize({k: v[0] for k, v in parsed.items()})
        except FatalAuthorize as exc:
            gw.audit("authorize.refused", "연결 요청을 거절했어요: 앱 또는 연결 주소가 맞지 않아요", "denied")
            return self._html(400, error_page(str(exc)))
        except Redirectable as exc:
            gw.audit("authorize.refused", f"연결 요청을 거절했어요: {exc.code}", "denied")
            return self._redirect(exc.redirect_uri, {"error": exc.code, "error_description": exc.description, "state": exc.state})
        form_id = gw.new_form(req)
        self._html(200, consent_page(gw, req, form_id))

    def _authorize_post(self, raw: bytes) -> None:
        gw = self.server.gateway
        try:
            params = self._body_params(raw)
        except OAuthError as exc:
            return self._html(400, error_page(exc.description))
        form_id = params.get("form_id", "")
        req = gw.form(form_id)
        if req is None:
            return self._html(400, error_page("연결 화면이 오래됐거나 이미 썼어요."))
        try:  # 보낸 뒤 설정이 바뀌었을 수 있으니 같은 검사를 한 번 더 (앱 등록·주소·권한)
            fresh = gw.validate_authorize({"client_id": req["client_id"], "redirect_uri": req["redirect_uri"], "state": req["state"],
                                           "response_type": "code", "code_challenge": req["challenge"], "code_challenge_method": "S256",
                                           "scope": " ".join(req["scope"]), "resource": req["resource"]})
        except (FatalAuthorize, Redirectable) as exc:
            gw.drop_form(form_id)
            return self._html(400, error_page(str(exc)))
        decision = params.get("decision")
        if decision == "deny":
            gw.drop_form(form_id)
            gw.audit("authorize.denied", f"사장님이 연결을 거절했어요: {fresh['client_name']}", "denied", who=fresh["client_name"])
            return self._redirect(fresh["redirect_uri"], {"error": "access_denied", "error_description": "사장님이 연결을 거절했어요.", "state": fresh["state"]})
        if decision != "allow":
            return self._html(400, consent_page(gw, fresh, form_id, "허용 또는 거절을 눌러 주세요."))
        result = gw.check_number(params.get("code", ""))
        if result == "locked":
            gw.audit("authorize.locked", "연결 번호를 너무 많이 틀려서 잠깐 막았어요", "denied", who=fresh["client_name"])
            return self._html(429, consent_page(gw, fresh, form_id, f"번호를 여러 번 틀려서 잠깐 막았어요. {gw.lock_left()}초 뒤에 다시 해 주세요.", locked=gw.lock_left()),
                              {"Retry-After": str(gw.lock_left())})
        if result == "wrong":
            gw.audit("authorize.wrong", "연결 번호가 맞지 않았어요", "denied", who=fresh["client_name"])
            left = gw.lock_left()
            msg = (f"번호를 여러 번 틀려서 잠깐 막았어요. {left}초 뒤에 다시 해 주세요." if left
                   else "연결 번호가 맞지 않거나 시간이 지났어요. AI 스튜디오 '외부 연결' 화면에서 새로 만들어 주세요.")
            return self._html(403, consent_page(gw, fresh, form_id, msg, locked=left))
        gw.drop_form(form_id)
        code = gw.make_code({"client_id": fresh["client_id"], "redirect_uri": fresh["redirect_uri"], "challenge": fresh["challenge"],
                             "scope": gw.effective_scope(fresh["scope"]), "resource": fresh["resource"]})  # 지금 허용된 만큼만 (나중에 허용해도 이 연결은 그대로)
        gw.audit("authorize.approved", f"연결을 승인했어요: {fresh['client_name']}", who=fresh["client_name"])
        self._redirect(fresh["redirect_uri"], {"code": code, "state": fresh["state"]})

    # ---- /oauth/token
    def _token(self, raw: bytes) -> None:
        gw = self.server.gateway
        try:
            params = self._body_params(raw)
            self._json(200, gw.token(params))
        except OAuthError as exc:
            gw.audit("token.denied", f"토큰 요청을 거절했어요: {exc.code}", "denied")
            self._oauth_error(exc)

    # ---- /mcp
    def _mcp(self, method: str, url, raw: bytes) -> None:
        from . import supervisor_mcp_http as mcp_http

        gw = self.server.gateway
        if method not in ("GET", "POST", "DELETE"):
            return self._not_found()
        if url.query or url.fragment:
            return mcp_http.error(self, 404, -32000, "MCP endpoint unavailable")
        origin = self.headers.get("Origin")
        if origin is not None and origin not in gw.allowed_origins():
            return mcp_http.error(self, 403, -32000, "Origin denied")
        if self._limited(("mcp-ip", self.client_address[0]), "mcp_ip"):
            return None
        if method == "POST":
            return mcp_http.post(self, authorize=self._mcp_authorize, tools=lambda access: gw.tools_for(access[0].scopes))
        # GET·DELETE: 서버가 먼저 보내는 스트림·세션 종료는 없다 (인증이 맞아야 405를 알려 준다)
        self.close_connection = True
        if self._mcp_authorize(self):
            mcp_http.send(self, 405, None, {"Allow": "POST"})

    def _mcp_authorize(self, _handler) -> tuple | None:
        from . import supervisor_mcp_http as mcp_http

        gw = self.server.gateway
        ip = self.client_address[0]
        limit, window = gw.limits["bad_auth"]
        wait = gw.limiter.blocked(("bad", ip), limit, window)
        if wait:
            self.close_connection = True
            mcp_http.error(self, 429, -32000, "Too many failed attempts", extra={"Retry-After": str(int(wait + 0.999))})
            return None
        try:
            conn, scopes = gw.verify_access(self.headers.get_all("Authorization", []))
        except AuthError:
            gw.limiter.hit(("bad", ip), limit, window)
            gw.audit("mcp.denied", "인증이 안 된 요청을 막았어요", "denied")
            mcp_http.error(self, 401, -32001, "MCP authorization required", extra={"WWW-Authenticate": gw.www_authenticate()})
            return None
        if self._limited(("mcp-conn", conn["id"]), "mcp_conn"):
            return None
        actor = gw.actor_for(conn, scopes)
        return _ActorCaller(gw, conn, scopes, actor), "", actor
