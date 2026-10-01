"""CEO 대시보드용 로컬 웹 서버 (표준 라이브러리만 사용).

- 127.0.0.1에만 열린다.
- Host 헤더가 localhost가 아니면 거절한다 (DNS 리바인딩 방지).
- 쓰기 요청은 페이지에 심어 둔 세션 토큰을 X-Studio-Token 헤더로 보내야 한다.
  다른 사이트는 이 토큰을 읽을 수 없으므로 CSRF가 막힌다.
"""

from __future__ import annotations

import json
import mimetypes
import secrets
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, ai, company, floors, gitops, login, mcp, qr, remote, schedules, skills, wardrobe
from .config import Config
from .doctor import run_doctor
from .engine import Engine, EngineError
from .model import KIND_LABELS, STATUS_LABELS, TransitionError
from .qa import suite_hash
from .store import Store
from .util import clean_child_env, no_window_flags, now_iso, read_json, read_jsonl, read_text_tail

STATIC_FILES = {
    "/app.js": "app.js",
    "/style.css": "style.css",
    "/favicon.svg": "favicon.svg",
}
# ui/ 폴더 안에서 내보내도 되는 파일 종류. 이 밖의 확장자와 ui/ 밖 경로는 모두 404.
UI_FILE_TYPES = {
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
}
# 설치한 그림(승인한 옷·새 직원, data/assets/) 중 내보내도 되는 종류. 원본(raw/)은 내보내지 않는다.
CUSTOM_FILE_TYPES = {".png": "image/png", ".json": "application/json; charset=utf-8"}
CUSTOM_PREFIX = "/assets/custom/"
MAX_BODY = 1_000_000


CODE_DIR = Path(__file__).resolve().parent  # studio/ (감독 프로그램 코드)


def code_stamp(code_dir: Path = CODE_DIR) -> int:
    """감독 프로그램 코드(studio/*.py와 옆의 studio.py)의 가장 늦은 수정 시각. 서버가 켜진 뒤 바뀌면 화면에 '껐다 켜 주세요'.
    화면 파일(ui/)은 새로고침하면 바로 새것을 읽으므로 세지 않는다."""
    files = [code_dir.parent / "studio.py", *code_dir.rglob("*.py")]
    stamps = []
    for f in files:
        try:
            stamps.append(f.stat().st_mtime_ns)
        except OSError:
            pass
    return max(stamps, default=0)


EMPTY_USAGE = {"runs": 0, "minutes": 0.0, "tokens": 0, "skills": [], "applied": [], "told": False}


def task_usage(runs: list[dict]) -> dict[str, dict[str, Any]]:
    """작업별 사용량: 실행 수·걸린 분·토큰(입력+출력), 그리고 배운 스킬 — skills = 본문이 붙은 스킬 이름,
    applied = 직원이 따랐다고 알린 스킬, told = 따른 스킬을 한 번이라도 알렸는지. 실행 기록으로만 센다."""
    out: dict[str, dict[str, Any]] = {}
    for r in runs:
        u = out.setdefault(str(r.get("task", "")), {"runs": 0, "seconds": 0.0, "tokens": 0, "skills": set(), "applied": set(), "told": False})
        u["runs"] += 1
        u["skills"].update(str(x).split("@")[0] for x in r.get("skills") or [])
        if isinstance(r.get("skills_applied"), list):
            u["told"] = True
            u["applied"].update(str(x) for x in r["skills_applied"])
        u["seconds"] += float(r.get("duration_s") or 0)
        usage = r.get("usage") or {}
        for key in ("input_tokens", "output_tokens"):
            try:
                u["tokens"] += int(usage.get(key) or 0)
            except (TypeError, ValueError):
                pass
    for u in out.values():
        u["minutes"] = round(u.pop("seconds") / 60, 1)
        u["skills"], u["applied"] = sorted(u["skills"]), sorted(u["applied"])
    return out


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, cfg: Config, store: Store, engine: Engine, port: int, *, bind: str = "127.0.0.1",
                 parent: "StudioServer | None" = None):
        """parent가 있으면 같은 와이파이용 두 번째 서버(bind = 이 PC의 집 안 주소): 휴대폰 화면(/m)만 내보낸다."""
        self.cfg = cfg
        self.store = store
        self.engine = engine
        self.parent = parent
        self.lan_mode = parent is not None
        self.remote = parent.remote if parent else remote.Remote(cfg)
        self.lan_server: StudioServer | None = None
        self.token = secrets.token_urlsafe(24)
        self.boot = parent.boot if parent else secrets.token_hex(3)  # 재시작하면 버전이 0부터 다시 세어도 화면이 새로 읽게
        self.allowed_hosts = {f"{bind}:{port}"} if parent else {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self.fw_cache: tuple[float, tuple, dict[str, Any]] | None = None  # 방화벽 점검 결과 (1분)
        self.doctor: dict[str, Any] | None = None
        self.doctor_running = False
        self.code_at = code_stamp()  # 켜질 때의 코드 (새 버전 알림)
        self._code_check = (0.0, False)
        super().__init__((bind, port), StudioHandler)

    # ------------------------------------------------------------ 같은 와이파이 (휴대폰 리모컨)
    def lan_url(self) -> str:
        if not self.lan_server:
            return ""
        host, port = self.lan_server.server_address[:2]
        return f"http://{host}:{port}/m"

    def start_lan(self) -> str:
        """이 PC의 집 안 주소에 휴대폰 화면만 여는 두 번째 서버를 켠다 (윈도우 방화벽이 한 번 물어볼 수 있다)."""
        if self.lan_server:
            return self.lan_url()
        ip = remote.lan_ip()
        if not ip:
            raise ValueError("이 PC의 집 안 네트워크 주소를 찾지 못했어요. 와이파이(또는 공유기)에 연결돼 있나요?")
        port = self.remote.settings()["lan_port"] or self.server_address[1] + 1
        try:
            srv = StudioServer(self.cfg, self.store, self.engine, port, bind=ip, parent=self)
        except OSError as e:
            raise ValueError(f"포트 {port}을(를) 열 수 없어요: {e}") from e
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.5}, name="studio-lan", daemon=True).start()
        self.lan_server = srv
        self.remote.update(lan=True, lan_port=port)
        return self.lan_url()

    def stop_lan(self, save: bool = True) -> None:
        srv, self.lan_server = self.lan_server, None
        if srv:
            srv.shutdown()
            srv.server_close()
        if save:
            self.remote.update(lan=False)

    def restart_needed(self) -> bool:
        """켜진 뒤 감독 프로그램 코드가 바뀌었는지 (10초에 한 번만 파일을 본다). 한 번 바뀌면 다시 켤 때까지 그대로."""
        at, changed = self._code_check
        if not changed and time.monotonic() - at > 10:
            changed = code_stamp() != self.code_at
            self._code_check = (time.monotonic(), changed)
        return changed

    def refresh_doctor(self) -> None:
        if self.doctor_running:
            return
        self.doctor_running = True

        def work() -> None:
            try:
                self.doctor = run_doctor(self.cfg)
            finally:
                self.doctor_running = False
                self.store._bump()

        threading.Thread(target=work, daemon=True).start()


class StudioHandler(BaseHTTPRequestHandler):
    server: StudioServer
    server_version = f"AIStudio/{__version__}"

    def log_message(self, fmt: str, *args: Any) -> None:  # 조용히
        pass

    # ---- 공통 ----
    def _host_ok(self) -> bool:
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def _host_kind(self) -> str | None:
        """local = 이 PC의 대시보드, lan = 같은 와이파이 서버, tailscale = 허용한 *.ts.net 주소. 나머지는 거절 (DNS 리바인딩 막기)."""
        host = self.headers.get("Host", "")
        if host in self.server.allowed_hosts:
            return "lan" if self.server.lan_mode else "local"
        if not self.server.lan_mode and host.lower() in self.server.remote.remote_hosts():
            return "tailscale"
        return None

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: Any, status: int = 200) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    # ---- GET ----
    def do_GET(self) -> None:  # noqa: N802
        kind = self._host_kind()
        if not kind:
            return self._error(HTTPStatus.FORBIDDEN, "허용되지 않은 Host")
        url = urlparse(self.path)
        path = url.path
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        if kind != "local" or path in self.MOBILE_PAGES or path.startswith("/m/api/"):
            try:
                return self._mobile_get(path, kind)
            except (EngineError, ValueError) as e:
                return self._error(HTTPStatus.BAD_REQUEST, str(e))
        try:
            if path == "/api/remote":
                return self._json(self._remote_info())
            if path == "/api/remote/check":
                return self._json(self._remote_check())
            if path == "/api/remote/qr.svg":
                return self._send(200, qr.svg(query.get("u", "")).encode("utf-8"), "image/svg+xml; charset=utf-8")
            if path in ("/", "/index.html"):
                return self._index()
            if path in STATIC_FILES:
                return self._static(STATIC_FILES[path])
            if path.startswith(CUSTOM_PREFIX):
                return self._custom_file(path)
            if path.startswith("/assets/") or path.endswith((".js", ".css")):
                return self._ui_file(path)
            if path == "/api/state":
                return self._json(self._state())
            if path.startswith("/api/tasks/") and path.endswith("/diff"):
                return self._json(self._diff(path.split("/")[3]))
            if path.startswith("/api/tasks/") and path.endswith("/report"):
                return self._json(self._report(path.split("/")[3]))
            if path.startswith("/api/tasks/") and path.count("/") == 5 and path.split("/")[4] == "look":
                # 의상 제작 미리보기 (승인 전 그림은 data/looks/<작업>/out/에만 있다)
                _, _, _, task_id, _, name = path.split("/")
                return self._send(200, wardrobe.preview_file(self.server.cfg, task_id, unquote(name)).read_bytes(), "image/png")
            if path == "/api/ai/options":
                return self._json(ai.options(self.server.cfg))
            if path == "/api/mcp":
                return self._json({"servers": mcp.servers(self.server.cfg)})
            if path == "/api/skills/report":
                return self._json(self._skill_report())
            if path == "/api/diary":
                return self._json(self._diary(query.get("day")))
            if path.startswith("/api/skills/"):
                return self._json(self._skill_detail(path.split("/")[3]))
            if path.startswith("/api/tasks/"):
                return self._json(self._task_detail(path.split("/")[3]))
            if path.startswith("/api/runs/"):
                return self._json(self._run_detail(path.split("/")[3]))
            if path == "/api/events":
                return self._json(self.server.store.recent_events(int(query.get("limit", 200)), query.get("task")))
            if path == "/api/doctor":
                if self.server.doctor is None:
                    self.server.refresh_doctor()
                return self._json({"running": self.server.doctor_running, "result": self.server.doctor})
            return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
        except (EngineError, ValueError) as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))
        except gitops.GitError as e:
            return self._error(HTTPStatus.CONFLICT, str(e))

    def _index(self) -> None:
        html = (self.server.cfg.ui_dir / "index.html").read_text(encoding="utf-8")
        html = html.replace("__STUDIO_TOKEN__", self.server.token)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _static(self, name: str) -> None:
        file = self.server.cfg.ui_dir / name
        if not file.exists():
            return self._error(HTTPStatus.NOT_FOUND, "없는 파일")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, file.read_bytes(), ctype)

    def _ui_file(self, path: str) -> None:
        """ui/ 아래 파일만, 허용한 종류만 내보낸다 (../ 같은 경로 조작은 resolve 후 걸러진다)."""
        ui = self.server.cfg.ui_dir.resolve()
        target = (ui / unquote(path).lstrip("/")).resolve()
        ctype = UI_FILE_TYPES.get(target.suffix.lower())
        if not ctype or not target.is_relative_to(ui) or not target.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "없는 파일")
        self._send(200, target.read_bytes(), ctype)

    def _custom_file(self, path: str) -> None:
        """/assets/custom/<경로> → data/assets/<경로>: 설치한 그림(png·json)만, data/assets 밖으로는 나가지 못한다
        (../ 같은 경로 조작은 resolve 뒤에 걸러진다). 원본 그림(raw/)은 내보내지 않는다."""
        base = wardrobe.assets_dir(self.server.cfg).resolve()
        rel = unquote(path)[len(CUSTOM_PREFIX):]
        try:
            target = (base / rel).resolve()
            inside = target.is_relative_to(base)
        except (OSError, ValueError):
            return self._error(HTTPStatus.NOT_FOUND, "없는 파일")
        ctype = CUSTOM_FILE_TYPES.get(target.suffix.lower())
        # 원본 폴더 raw/는 내보내지 않는다 (윈도우는 대소문자를 가리지 않으므로 소문자로 비교)
        if not ctype or not inside or [p.lower() for p in target.relative_to(base).parts[:1]] == ["raw"]:
            return self._error(HTTPStatus.NOT_FOUND, "없는 파일")
        if not target.is_file():
            if target.parent == base and target.name in ("index.json", "parts.json"):
                return self._json({})  # 설치한 그림이 아직 없다: 빈 목록 (화면이 404를 오류로 남기지 않게)
            if target == base / "mascot" / "mascot.json":
                return self._json({})  # 사장님 발표 캐릭터가 아직 없다: 진행판이 기본 그림(ui/assets/mascot)을 쓴다
            return self._error(HTTPStatus.NOT_FOUND, "없는 파일")
        self._send(200, target.read_bytes(), ctype)

    # ---- POST ----
    def _read_body(self) -> bytes | None:
        """요청 본문을 먼저 다 읽는다. 거절할 때도 읽어 두어야 윈도우가 답을 보내기 전에 연결을 끊지(RST) 않는다
        (읽지 않은 본문이 남은 채 닫으면 받는 쪽에 '연결 중단' 오류가 난다). 너무 크면 읽지 않고 None."""
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self.close_connection = True
            return None
        return self.rfile.read(length) if length > 0 else b""

    def do_POST(self) -> None:  # noqa: N802
        raw = self._read_body()
        if raw is None:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "요청이 너무 큽니다.")
        kind = self._host_kind()
        if not kind:
            return self._error(HTTPStatus.FORBIDDEN, "허용되지 않은 Host")
        path = urlparse(self.path).path
        if path.startswith("/m/api/"):
            return self._mobile_post(path, raw)
        if kind != "local":
            return self._error(HTTPStatus.NOT_FOUND, "휴대폰에서는 /m 화면만 쓸 수 있어요.")
        origin = self.headers.get("Origin")
        if origin and origin not in self.server.allowed_origins:
            return self._error(HTTPStatus.FORBIDDEN, "허용되지 않은 Origin")
        if not secrets.compare_digest(self.headers.get("X-Studio-Token", ""), self.server.token):
            return self._error(HTTPStatus.FORBIDDEN, "세션이 만료됐습니다. 페이지를 새로고침하세요.")
        try:
            body = json.loads(raw.decode("utf-8") or "{}") if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error(HTTPStatus.BAD_REQUEST, "JSON 형식이 아닙니다.")
        if not isinstance(body, dict):
            return self._error(HTTPStatus.BAD_REQUEST, "JSON 객체가 필요합니다.")
        engine = self.server.engine
        path = urlparse(self.path).path
        try:
            if path == "/api/directive":
                task = engine.submit_directive(str(body.get("text", "")), str(body.get("project", "")))
                return self._json({"ok": True, "task": task.id})
            if path == "/api/tasks":
                task = engine.create_task(body)
                return self._json({"ok": True, "task": task.id})
            if path.startswith("/api/tasks/"):
                parts = path.split("/")
                if len(parts) != 5:
                    return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
                task_id, action = parts[3], parts[4]
                if action == "run":
                    engine.request_run(task_id)
                elif action == "approve":
                    engine.approve(task_id, body)
                elif action == "request-changes":
                    engine.request_changes(task_id, str(body.get("note", "")))
                elif action == "retry":
                    if body.get("draw"):
                        engine.redraw_with(task_id, str(body.get("draw")))  # 그리는 AI를 바꿔 다시 (Grok → Codex)
                    else:
                        engine.retry(task_id)
                elif action == "cancel":
                    engine.cancel(task_id)
                elif action == "archive":
                    engine.archive(task_id, bool(body.get("archived", True)))
                elif action == "assign":
                    engine.assign(task_id, str(body.get("role", "")))
                elif action == "merge-skill":  # 새 스킬 제안을 비슷한 스킬에 합쳐 고쳐 오게
                    engine.merge_skill(task_id, str(body.get("into", "")))
                else:
                    return self._error(HTTPStatus.NOT_FOUND, "없는 동작")
                return self._json({"ok": True})
            # 스킬 학습 (Claude 스킬 방식): 직접 가르치기, 공부 맡기기, 배우기·잊기, 쓰는 곳 바꾸기, 지우기
            # MCP 보관소 (왼쪽 서재): 바깥 MCP 등록, 장착·켜기·토큰·연결 확인·지우기. 토큰 값은 돌려주지 않는다
            if path == "/api/mcp":
                return self._json({"ok": True, "server": engine.mcp_add(body)})
            # 업무 자동 시작 (벽시계): 만들기, 켜기·끄기, 지우기, 지금 하기
            if path == "/api/schedules":
                return self._json({"ok": True, "schedule": engine.add_schedule(body)})
            if path.startswith("/api/schedules/"):
                parts = path.split("/")
                if len(parts) != 5:
                    return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
                return self._json({"ok": True, "schedule": engine.schedule_action(parts[3], parts[4], body)})
            if path == "/api/mcp/order":  # 직원에게 MCP 만들기 맡기기 (target: 직원이 만든 도구 고쳐 오기)
                task = engine.order_tool(str(body.get("role", "")), str(body.get("request", "")), str(body.get("project", "")),
                                         str(body.get("target") or "") or None)
                return self._json({"ok": True, "task": task.id})
            if path.startswith("/api/mcp/"):
                parts = path.split("/")
                if len(parts) != 5:
                    return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
                return self._json({"ok": True, "server": engine.mcp_action(unquote(parts[3]), parts[4], body)})
            if path == "/api/skills":
                return self._json({"ok": True, "skill": engine.teach_skill(body).summary()})
            if path == "/api/skills/study":
                task = engine.study_skill(str(body.get("role", "")), str(body.get("topic", "")), str(body.get("project", "")),
                                          str(body.get("target") or "") or None)
                return self._json({"ok": True, "task": task.id})
            if path.startswith("/api/skills/"):
                parts = path.split("/")
                if len(parts) != 5:
                    return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
                slug, action = parts[3], parts[4]
                if action == "learn":
                    skill = engine.set_skill_learned(slug, str(body.get("role", "")), bool(body.get("learned", True)))
                    return self._json({"ok": True, "skill": skill.summary()})
                if action == "scope":  # 쓰는 곳: 프로젝트·일 종류 (비우면 모든 곳)
                    skill = engine.set_skill_scope(slug, body.get("projects"), body.get("kinds"))
                    return self._json({"ok": True, "skill": skill.summary()})
                if action == "remove":
                    engine.remove_skill(slug)
                    return self._json({"ok": True})
                return self._error(HTTPStatus.NOT_FOUND, "없는 동작")
            if path == "/api/alerts/read":
                self.server.store.update_state(alerts_seen_at=now_iso())
                return self._json({"ok": True})
            if path == "/api/settings/self-learning":
                engine.set_self_learning(bool(body.get("enabled", True)))
                return self._json({"ok": True, "self_learning": engine.self_learning()})
            if path == "/api/settings/goals":
                goals = dict(self.server.store.get_state().get("goals") or {})
                if "week" in body:
                    goals["week"] = str(body["week"]).strip()[:40]
                if "month" in body:
                    goals["month"] = max(1, min(99, int(body["month"])))
                self.server.store.update_state(goals=goals)
                return self._json({"ok": True, "goals": goals})
            if path == "/api/staff":
                return self._json({"ok": True, "task": engine.hire(body).id})
            if path == "/api/floors/add":
                return self._json({"ok": True, "floor": engine.add_floor(), "floors": floors.info(self.server.cfg)})
            if path.startswith("/api/team/") and path.endswith("/outfit"):
                task = engine.order_outfit(path.split("/")[3], str(body.get("label", "")), str(body.get("desc", "")),
                                           str(body.get("kind", "outfit")), str(body.get("draw", "codex")))
                return self._json({"ok": True, "task": task.id})
            if path.startswith("/api/team/") and "/looks/" in path:
                # 꾸미기 창의 ✕: /api/team/<역할>/looks/<옷>/remove (공방 옷은 휴지통, 배포 옷은 숨기기) · /restore (숨긴 옷 되살리기)
                parts = path.split("/")
                if len(parts) != 7 or parts[4] != "looks" or parts[6] not in ("remove", "restore"):
                    return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
                run = engine.remove_look if parts[6] == "remove" else engine.restore_look
                return self._json({"ok": True, **run(parts[3], unquote(parts[5]))})
            if path.startswith("/api/team/") and path.endswith("/ai"):
                return self._json({"ok": True, "ai": engine.set_ai(path.split("/")[3], body)})
            if path.startswith("/api/team/") and path.endswith("/dismiss"):
                return self._json({"ok": True, **engine.dismiss(path.split("/")[3])})
            if path.startswith("/api/team/") and path.endswith("/ai/reset"):
                return self._json({"ok": True, "ai": engine.reset_ai(path.split("/")[3])})
            if path.startswith("/api/team/") and path.endswith("/look"):
                role = path.split("/")[3]
                return self._json({"ok": True, "look": company.save_look(self.server.cfg, self.server.store, role, body.get("look"))})
            if path == "/api/trophies/add":
                return self._json({"ok": True, "trophy": engine.add_trophy(str(body.get("task", "")), str(body.get("kind", "game")))})
            if path == "/api/trophies/remove":
                engine.remove_trophy(str(body.get("task", "")))
                return self._json({"ok": True})
            if path == "/api/trophies/play":
                self._play(str(body.get("task", "")))
                return self._json({"ok": True})
            # 휴대폰 리모컨 설정 (이 PC에서만): 짝짓기 번호, 같은 와이파이 켜기·끄기, Tailscale 주소, 기기 끊기
            if path == "/api/remote/pair":
                return self._json({"ok": True, **self._remote_pair()})
            if path == "/api/remote/lan":
                if body.get("on"):
                    url = self.server.start_lan()
                    self.server.store.event("remote.lan", f"휴대폰 리모컨 (같은 와이파이) 켬: {url}")
                else:
                    self.server.stop_lan()
                    self.server.store.event("remote.lan", "휴대폰 리모컨 (같은 와이파이) 끔")
                return self._json({"ok": True, **self._remote_info()})
            if path == "/api/remote/tailscale":
                if body.get("remove"):
                    hosts = [h for h in self.server.remote.settings()["ts_hosts"] if h != str(body["remove"]).lower()]
                    self.server.remote.update(ts_hosts=hosts)
                else:
                    found = remote.detect_tailscale()
                    if not found["host"]:
                        raise ValueError(found["error"])
                    hosts = sorted(set(self.server.remote.settings()["ts_hosts"]) | {found["host"]})
                    self.server.remote.update(ts_hosts=hosts)
                    self.server.store.event("remote.tailscale", f"휴대폰 리모컨 Tailscale 주소 허용: {found['host']}")
                return self._json({"ok": True, **self._remote_info()})
            if path.startswith("/api/remote/devices/") and path.endswith("/remove"):
                self.server.remote.remove_device(path.split("/")[4])
                self.server.store.event("remote.forgot", "휴대폰 연결 끊음")
                return self._json({"ok": True, **self._remote_info()})
            # 다른 아이디로 로그인 (한도·로그인 만료로 멈췄을 때): 로그인 창 열기, 로그인 끝 → 재개·다시 하기
            if path == "/api/login/open":
                return self._json({"ok": True, **engine.open_login(str(body.get("runtime") or ""))})
            if path == "/api/login/done":
                return self._json({"ok": True, **engine.login_done()})
            if path == "/api/control/stop":
                engine.emergency_stop()
                return self._json({"ok": True})
            if path == "/api/control/resume":
                engine.resume()
                return self._json({"ok": True})
            if path == "/api/control/auto-run":
                engine.set_auto_run(bool(body.get("enabled")))
                return self._json({"ok": True})
            if path == "/api/doctor/refresh":
                self.server.refresh_doctor()
                return self._json({"ok": True})
            return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
        except (EngineError, TransitionError, ValueError) as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))
        except gitops.GitError as e:
            return self._error(HTTPStatus.CONFLICT, str(e))

    # ---- 휴대폰 리모컨 (/m) ----
    # PC 대시보드와 따로: 짝지은 기기 토큰(X-Device-Token)으로만. 같은 와이파이(LAN 서버)·Tailscale 주소로 온 요청은 이것만 받는다.
    MOBILE_PAGES = {"/m": "m.html", "/m/": "m.html", "/m.js": "m.js", "/m.css": "m.css", "/favicon.svg": "favicon.svg"}

    def _device(self) -> dict[str, Any] | None:
        return self.server.remote.device_for(self.headers.get("X-Device-Token", ""))

    def _mobile_get(self, path: str, kind: str) -> None:
        if path == "/" and kind != "local":
            self.send_response(302)
            self.send_header("Location", "/m")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if path in self.MOBILE_PAGES:
            return self._static(self.MOBILE_PAGES[path])
        if kind != "local" and path.startswith(CUSTOM_PREFIX):
            return self._custom_file(path)
        if kind != "local" and path.startswith("/assets/"):
            return self._ui_file(path)
        if not path.startswith("/m/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
        if not self._device():
            return self._error(HTTPStatus.UNAUTHORIZED, "짝지은 기기가 아니에요. PC에서 QR로 다시 연결해 주세요.")
        if path == "/m/api/state":
            return self._json(self._mobile_state())
        if path.startswith("/m/api/task/"):
            return self._json(self._mobile_task(path.split("/")[4]))
        return self._error(HTTPStatus.NOT_FOUND, "없는 경로")

    def _mobile_post(self, path: str, raw: bytes) -> None:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://{host}", f"https://{host}"):
            return self._error(HTTPStatus.FORBIDDEN, "허용되지 않은 Origin")
        if len(raw) > 20_000:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "요청이 너무 큽니다.")
        try:
            body = json.loads(raw.decode("utf-8") or "{}") if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._error(HTTPStatus.BAD_REQUEST, "JSON 형식이 아닙니다.")
        if not isinstance(body, dict):
            return self._error(HTTPStatus.BAD_REQUEST, "JSON 객체가 필요합니다.")
        engine = self.server.engine
        try:
            if path == "/m/api/pair":
                token = self.server.remote.pair(str(body.get("code", "")), str(body.get("name", "")))
                self.server.store.event("remote.paired", f"휴대폰 연결: {str(body.get('name', '휴대폰'))[:40]}")
                return self._json({"ok": True, "token": token})
            device = self._device()
            if not device:
                return self._error(HTTPStatus.UNAUTHORIZED, "짝지은 기기가 아니에요. PC에서 QR로 다시 연결해 주세요.")
            if path == "/m/api/forget":
                self.server.remote.remove_device(device["id"])
                return self._json({"ok": True})
            if path == "/m/api/directive":
                task = engine.submit_directive(str(body.get("text", "")), str(body.get("project", "")))
                return self._json({"ok": True, "task": task.id})
            if path == "/m/api/stop":
                engine.emergency_stop("휴대폰에서 긴급 정지") if body.get("stopped", True) else engine.resume()
                return self._json({"ok": True})
            if path == "/m/api/act":
                task_id, action = str(body.get("task", "")), str(body.get("action", ""))
                if action == "approve":
                    task = self.server.store.get(task_id)
                    payload: dict[str, Any] = {}
                    if task and task.kind == "plan":  # 휴대폰은 고른 퀘스트만 (안 고르면 모두)
                        picked = body.get("selected")
                        count = len((task.proposal or {}).get("tasks") or [])
                        payload = {"selected": [int(i) for i in picked if 0 <= int(i) < count] if isinstance(picked, list) else list(range(count)),
                                   "edits": {}}
                    engine.approve(task_id, payload)
                elif action == "request-changes":
                    engine.request_changes(task_id, str(body.get("note", "")))
                elif action == "retry":
                    engine.retry(task_id)
                elif action == "run":
                    engine.request_run(task_id)
                elif action == "cancel":
                    engine.cancel(task_id)
                else:
                    return self._error(HTTPStatus.NOT_FOUND, "휴대폰에서는 할 수 없는 동작이에요.")
                return self._json({"ok": True})
            return self._error(HTTPStatus.NOT_FOUND, "없는 경로")
        except (EngineError, TransitionError, ValueError) as e:
            return self._error(HTTPStatus.BAD_REQUEST, str(e))
        except gitops.GitError as e:
            return self._error(HTTPStatus.CONFLICT, str(e))

    def _mobile_state(self) -> dict[str, Any]:
        """휴대폰 화면용 작은 상태: 결재함·진행 중·최근 끝남·알림·에너지·긴급 정지."""
        cfg, store, engine = self.server.cfg, self.server.store, self.server.engine
        events = store.recent_events(company.ALERT_SCAN)
        tasks = store.list()
        state = store.get_state()
        usage = store.today_usage()
        current = engine.status().get("current") or {}

        def who(role: str) -> str:
            r = cfg.roles.get(role)
            return r.name if r else str(company.left_staff(cfg).get(role, {}).get("name") or role)

        def item(t: Any) -> dict[str, Any]:
            return {"id": t.id, "kind": t.kind, "kind_label": KIND_LABELS.get(t.kind, t.kind), "status": t.status,
                    "status_label": STATUS_LABELS.get(t.status, t.status), "title": t.title, "who": who(t.role),
                    "project": t.project, "updated_at": t.updated_at, "blocked_reason": t.blocked_reason or "",
                    "waiting": engine.waiting_reason(t, tasks), "run_requested": t.run_requested}

        live = [t for t in tasks if t.status in ("running", "checking", "queued", "ready", "blocked") and not t.archived]
        done = sorted((t for t in tasks if t.status == "done"), key=lambda t: t.updated_at, reverse=True)[:8]
        limit = cfg.limit("max_runs_per_day")
        return {
            "studio": {"name": cfg.name, "fake": cfg.fake_runtimes},
            "version": f"{self.server.boot}.{store.version}",
            "stopped": bool(state.get("stopped")),
            "needs_login": bool(state.get("needs_login")),  # PC에서 다른 아이디로 로그인해야 함 (휴대폰은 알리기만)
            "energy": {"max": limit, "left": max(0, limit - usage["runs"])},
            "current": {"title": current.get("title"), "who": who(current.get("role", ""))} if current.get("task") else None,
            "projects": [{"key": p.key, "title": p.title} for p in cfg.projects.values()],
            "inbox": [item(t) for t in tasks if t.status == "awaiting_approval" and not t.archived],
            "active": [item(t) for t in live],
            "done": [item(t) for t in done],
            "alerts": [{"time": a.get("time"), "name": a.get("name"), "text": a.get("text"), "task": a.get("task")}
                       for a in company.alerts(cfg, store, tasks, 20, events)],
        }

    def _mobile_task(self, task_id: str) -> dict[str, Any]:
        """휴대폰에서 볼 작업 내용: 목표·수용 기준·보고·리뷰·검사, 기획이면 퀘스트 목록, 리서치면 보고서, 개발이면 바뀐 코드 (앞부분)."""
        cfg, store = self.server.cfg, self.server.store
        t = store.get(task_id)
        if not t:
            raise EngineError("작업을 찾을 수 없습니다.")
        review = t.review or {}
        out: dict[str, Any] = {
            "id": t.id, "title": t.title, "kind": t.kind, "status": t.status, "status_label": STATUS_LABELS.get(t.status, t.status),
            "brief": t.brief, "acceptance": t.acceptance, "report": (t.report or "")[:6000], "blocked_reason": t.blocked_reason or "",
            "qa": {"verdict": (t.qa or {}).get("verdict"), "passed": (t.qa or {}).get("passed"), "total": (t.qa or {}).get("total")} if t.qa else None,
            "review": {"verdict": review.get("verdict"), "summary": str(review.get("summary", ""))[:2000],
                       "findings": [{"severity": f.get("severity"), "file": f.get("file"), "issue": f.get("issue")}
                                    for f in review.get("findings") or [] if isinstance(f, dict)][:15]} if review else None,
        }
        prop = t.proposal or {}
        if t.kind == "plan":
            out["quests"] = [{"title": q.get("title"), "brief": q.get("brief"), "kind": q.get("kind")} for q in prop.get("tasks") or []]
            out["summary"] = prop.get("summary", "")
        elif t.kind == "skill" and prop.get("skill"):
            out["summary"] = f"{prop['skill'].get('title')}: {prop['skill'].get('description')}"
            out["body"] = str(prop["skill"].get("body", ""))[:6000]
        elif t.kind == "tool" and prop.get("code"):
            out["summary"] = f"{prop.get('title')}: {prop.get('description')}"
            out["body"] = str(prop.get("code", ""))[:12000]
        elif t.kind == "research":
            try:
                rep = company.report_summary(cfg, t)
                out["body"] = str(rep.get("body") or rep.get("conclusion") or "")[:20000]
            except (ValueError, gitops.GitError):
                pass
        elif t.kind == "build" and t.base_sha and t.candidate_sha:
            try:
                d = self._diff(task_id)
                out["body"] = d["diff"][:30000] + ("\n…(길어서 앞부분만)" if len(d["diff"]) > 30000 else "")
            except gitops.GitError:
                pass
        return out

    # ---- 데이터 조립 ----
    def _skill_detail(self, slug: str) -> dict[str, Any]:
        """스킬 본문 + 진화 기록(판마다 바뀐 점) + 실제 기록으로 센 사용 횟수·결과."""
        cfg, store = self.server.cfg, self.server.store
        sk = skills.get(cfg, slug)
        reviewers = {k for k, r in cfg.roles.items() if r.job_key == "reviewer"}
        usage = company.skill_usage(sk.slug, store.list(), store.runs(), reviewers)
        return {**sk.to_dict(), "history": skills.history(cfg, sk), "usage": usage}

    def _remote_info(self) -> dict[str, Any]:
        info = self.server.remote.info()
        port = self.server.server_address[1]
        return {**info, "lan_running": bool(self.server.lan_server), "lan_url": self.server.lan_url(), "lan_ip": remote.lan_ip() or "",
                "ts_urls": [f"https://{h}/m" for h in info["ts_hosts"]], "ts_installed": bool(remote.tailscale_exe()),
                "ts_command": f"tailscale serve --bg {port}"}

    def _remote_check(self) -> dict[str, Any]:
        """같은 와이파이가 켜져 있을 때 윈도우 방화벽이 휴대폰 접속을 막는지 읽기만 한다 (아무것도 바꾸지 않음, 결과는 1분 보관)."""
        srv = self.server.lan_server
        if not srv:
            return {"running": False, "checked": False}
        ip, port = srv.server_address[:2]
        key = (ip, port, sys.executable)
        cached = self.server.fw_cache
        if cached and cached[1] == key and time.monotonic() - cached[0] < 60:
            return {"running": True, **cached[2]}
        result = remote.firewall_check(sys.executable, ip)
        self.server.fw_cache = (time.monotonic(), key, result)
        return {"running": True, **result}

    def _remote_pair(self) -> dict[str, Any]:
        code = self.server.remote.new_code()
        info = self._remote_info()
        urls = ([info["lan_url"]] if info["lan_url"] else []) + info["ts_urls"]
        return {**code, "urls": [f"{u}#pair={code['code']}" for u in urls]}

    def _skill_report(self) -> dict[str, Any]:
        """스킬 성적표 (화면이 열 때만 부른다)."""
        cfg, store = self.server.cfg, self.server.store
        return {"skills": company.skill_report(cfg, store, skills.list_skills(cfg), store.list(), store.runs())}

    def _state(self) -> dict[str, Any]:
        s = self.server
        cfg, store, engine = s.cfg, s.store, s.engine
        # 버전은 무엇보다 먼저 읽는다: 모으는 사이에 바뀌면 다음 요청에서 버전이 달라 화면이 다시 읽는다
        restart = s.restart_needed()
        version = f"{s.boot}.{store.version}" + (".new" if restart else "")
        # 활동 기록을 작업 목록보다 먼저 읽는다: 엔진은 작업 파일을 저장한 뒤 기록을 남기므로,
        # 이렇게 하면 기록에 보이는 일(예: 기획 완료)은 작업 목록에도 반드시 반영돼 있다 ("퀘스트 0개" 알림 방지)
        events = store.recent_events(company.ALERT_SCAN)
        tasks = store.list()
        usage = task_usage(store.runs())
        summaries = []
        for t in tasks:
            item = t.summary()
            item["waiting"] = engine.waiting_reason(t, tasks)
            item["usage"] = usage.get(t.id) or dict(EMPTY_USAGE)  # 작업별 사용량·배운 스킬 (작업 카드·진행판)
            summaries.append(item)
        status = engine.status()
        current = status.get("current") or {}
        runs_today = [r for r in store.runs() if str(r.get("started_at", "")).startswith(_today())]
        team = []
        for key, role in cfg.roles.items():
            mine = [r for r in runs_today if r.get("role") == key]
            team.append({
                "key": key,
                "title": role.title,
                "avatar": role.avatar,
                "description": role.description,
                "runtime": role.runtime,
                "model": role.model or "기본",
                "effort": role.effort,
                "ai": ai.current(cfg, key),  # 화면의 AI 탑재 창이 고른 값을 보여 줄 때 ("기본"으로 바꾸지 않은 값)
                "ai_custom": engine.ai_defaults.get(key) != ai.current(cfg, key),
                "fallback": role.fallback_runtime,
                "sandbox": role.sandbox,
                "busy": current.get("role") == key,
                "task": current.get("task") if current.get("role") == key else None,
                "task_title": current.get("title") if current.get("role") == key else None,
                "runs_today": len(mine),
                "ok_today": sum(1 for r in mine if r.get("ok")),
            })
        projects = [
            {
                "key": p.key,
                "title": p.title,
                "kind": p.kind,
                "description": p.description,
                "has_qa": bool(p.qa.get("commands")),
                "expected_total": p.qa.get("expected_total"),
                "suite_hash": (suite_hash(cfg, p) or "")[:8],
                "default_allowed_paths": p.default_allowed_paths,
            }
            for p in cfg.projects.values()
        ]
        builds = [t for t in tasks if t.kind != "plan" and t.qa]
        first_pass = [t for t in builds if t.status == "done"]
        fp_ok = sum(1 for t in first_pass if _first_attempt_passed(t))
        state = store.get_state()
        alerts = company.alerts(cfg, store, tasks, events=events)
        seen = str(state.get("alerts_seen_at") or "")
        # 게임 화면용 직원 정보 (이름·캐릭터·한마디·스킬·꾸미기·통계·지금 모습)
        people = {p["key"]: p for p in company.team(cfg, store, tasks, current or None)}
        for member in team:
            member.update(people.get(member["key"], {}))
        day = company.day_number(store)
        return {
            "version": version,
            "studio": {"name": cfg.name, "tagline": cfg.tagline, "app_version": __version__, "fake": cfg.fake_runtimes,
                       "restart": restart},  # 켜진 뒤 코드가 바뀜 → '껐다 켜 주세요'
            "day": day,
            "goals": {**cfg.goals, **(state.get("goals") or {})},
            "alerts": alerts,
            "unread_alerts": sum(1 for a in alerts if str(a.get("at") or "") > seen),
            "trophies": store.read_doc("trophies", []),
            "skills": [sk.summary() for sk in skills.list_skills(cfg)],  # 본문은 GET /api/skills/<이름>으로
            "mcp": mcp.servers(cfg),  # MCP 보관소 (토큰 값은 없음, 넣었는지만)
            "schedules": schedules.view(cfg),  # 업무 자동 시작 (벽시계)
            "self_learning": {"on": engine.self_learning(), "limit": cfg.limit("max_auto_skills_per_day"),
                              "today": engine.reflections_today(tasks)},
            "look_options": company.look_options(cfg),
            "floors": floors.info(cfg),  # 층 수·책상 수·새 직원 상한 (studio/floors.py)
            "left_staff": company.left_staff(cfg),  # 내보낸 직원 {키: {이름, 맡았던 일}} (지난 작업 카드의 얼굴)
            "status": status,
            "tasks": summaries,
            "team": team,
            "projects": projects,
            "labels": {"status": STATUS_LABELS, "kind": KIND_LABELS},
            "metrics": {
                "done_builds": len(first_pass),
                "first_pass": fp_ok,
                "awaiting": sum(1 for t in tasks if t.status == "awaiting_approval"),
                "blocked": sum(1 for t in tasks if t.status == "blocked"),
                "active": sum(1 for t in tasks if t.status in ("running", "checking", "queued")),
            },
            "doctor": {"overall": (s.doctor or {}).get("overall"), "running": s.doctor_running},
            "events": store.recent_events(40),
            "runs": store.runs()[-40:],
        }

    def _task_detail(self, task_id: str) -> dict[str, Any]:
        store = self.server.store
        task = store.get(task_id)
        if not task:
            raise EngineError("작업을 찾을 수 없습니다.")
        data = task.to_dict()
        data["status_label"] = STATUS_LABELS.get(task.status, task.status)
        data["waiting"] = self.server.engine.waiting_reason(task, store.list())
        data["runs_detail"] = store.runs(task_id)
        data["events"] = store.recent_events(100, task_id)
        project = self.server.cfg.projects.get(task.project)
        data["project_title"] = project.title if project else task.project
        data["protected_paths"] = project.all_protected() if project else []
        return data

    def _report(self, task_id: str) -> dict[str, Any]:
        task = self.server.store.get(task_id)
        if not task:
            raise EngineError("작업을 찾을 수 없습니다.")
        return company.report_summary(self.server.cfg, task)

    def _diary(self, day: str | None) -> dict[str, Any]:
        store = self.server.store
        today = company.day_number(store)
        n = int(day) if day else today
        if not 1 <= n <= today:
            raise EngineError(f"{n}일차 기록은 없습니다.")
        data = company.diary(self.server.cfg, store, store.list(), n)
        data["days"] = today
        return data

    def _play(self, task_id: str) -> None:
        """완성작 선반의 게임을 Godot로 실행한다 (제품 저장소 main 기준, 셸 없이 정해진 인자만)."""
        import subprocess

        cfg = self.server.cfg
        if not any(i.get("task") == task_id and i.get("kind") == "game" for i in self.server.store.read_doc("trophies", [])):
            raise EngineError("완성작 선반에 있는 게임만 실행할 수 있습니다.")
        task = self.server.store.get(task_id)
        project = cfg.projects.get(task.project) if task else None
        godot = cfg.godot_path()
        if not project or project.kind != "godot" or not (project.repo / "project.godot").exists():
            raise EngineError("Godot 프로젝트가 아니라서 실행할 수 없습니다.")
        if not godot or not Path(godot).exists():
            raise EngineError("studio.toml [tools] godot 경로를 확인하세요.")
        subprocess.Popen([godot, "--path", str(project.repo)], cwd=str(project.repo), env=clean_child_env(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=no_window_flags())
        self.server.store.event("trophy.played", f"{task.id} 게임 실행", task=task.id)

    def _diff(self, task_id: str) -> dict[str, Any]:
        task = self.server.store.get(task_id)
        if not task or not task.base_sha or not task.candidate_sha:
            return {"diff": "", "stats": [], "truncated": False}
        project = self.server.cfg.projects[task.project]
        target = task.merged_sha or task.candidate_sha
        diff, truncated = gitops.diff_text(project.repo, task.base_sha, target, 200000)
        return {"diff": diff, "stats": gitops.diff_numstat(project.repo, task.base_sha, target), "truncated": truncated}

    def _run_detail(self, run_id: str) -> dict[str, Any]:
        if not run_id.startswith("R") or "/" in run_id or "\\" in run_id or ".." in run_id:
            raise EngineError("잘못된 실행 ID")
        run_dir = self.server.store.runs_dir / run_id
        meta = read_json(run_dir / "meta.json", {}) or {}
        return {
            "meta": meta,
            "prompt": read_text_tail(run_dir / "prompt.md", 60000),
            "last_message": read_text_tail(run_dir / "last_message.md", 20000),
            "stderr": read_text_tail(run_dir / "stderr.txt", 6000),
            "events": len(read_jsonl(run_dir / "events.jsonl")),
        }


def _today() -> str:
    from .util import today_str

    return today_str()


def _first_attempt_passed(task: Any) -> bool:
    """개발 실행이 한 번뿐이었으면 첫 후보가 모든 관문을 통과한 것이다."""
    return sum(1 for r in task.runs if "-build" in r) == 1


def serve(cfg: Config, *, port: int | None = None, open_browser: bool = True) -> None:
    import webbrowser

    store = Store(cfg.data_dir)
    store.acquire_process_lock()
    engine = Engine(cfg, store)
    if not cfg.fake_runtimes:  # 진짜 회사만: 한도·로그인 만료로 멈추면 로그인 창을 띄운다 (CEO 요청)
        engine.login_opener = lambda runtime: login.open_login_window(cfg, runtime)
    port = port or cfg.port
    try:
        server = StudioServer(cfg, store, engine, port)
    except OSError as e:
        store.release_process_lock()
        raise SystemExit(f"포트 {port}을(를) 열 수 없습니다: {e}")
    if server.remote.settings()["lan"]:  # 휴대폰 리모컨(같은 와이파이)을 켜 둔 채 껐으면 다시 켠다
        try:
            print(f"  휴대폰 리모컨 (같은 와이파이): {server.start_lan()}", flush=True)
        except ValueError as e:
            store.event("remote.lan", f"휴대폰 리모컨을 켜지 못했어요: {e}")
    engine.start()
    server.refresh_doctor()
    url = f"http://127.0.0.1:{port}/"
    store.event("company.opened", "감독 프로그램 시작")
    print(f"\n  {cfg.name} 대시보드: {url}\n  종료: Ctrl+C\n", flush=True)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        store.event("company.closed", "감독 프로그램 종료")
        server.stop_lan(save=False)
        engine.shutdown()
        server.server_close()
        store.release_process_lock()
