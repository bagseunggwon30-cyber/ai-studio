"""Reviewed, default-disconnected contract for pinned Grok Everywhere.

Session compatibility is third-party, not a guarantee of free generation. This
boundary intentionally cannot turn a plan or a workbench note into execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import os
import subprocess
import sys
import threading
import time
import secrets
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit
from .checkpoints import digest
from .util import atomic_write_json, atomic_copy, append_jsonl, now_iso, read_json, sha256_file, no_window_flags

PIN = "4c6fad3eca694b4bc1c9fedea41ae236139f2044"
CLI_SHA256 = "c680fa39ccd173b5005bf32e4fad53ed7b564610e02a07274ca0a5b0e1a29527"
BLOCKED = "Grok Everywhere 실행 비활성: Grok Build 구독 범위를 확인할 수 없습니다. 추가 과금·결제·충전·구독 변경은 금지되며 비용 미상 동의로 해결하지 않습니다. 구독 포함 범위 확인과 요청별 실행 승인이 필요합니다."
MODELS = {"research": "grok-4.6", "image": "grok-imagine-image-2.0", "video": "grok-imagine-video-1.5"}
OPTIONS = {"research": {"source": "web", "depth": "balanced"},
           "image": {"count": 1, "aspect_ratio": "1:1", "resolution": "1k"},
           "video": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "max_wait": 120, "poll_interval": 5}}


class ContractError(ValueError):
    pass


def reported_video_duration(value, expected=None):
    # Pinned CLI reports provider metadata, which may be absent. Never infer it.
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 15:
        raise ContractError("Invalid reported video duration")
    if expected is not None and value != video_duration(expected):
        raise ContractError("Reported video duration differs from the approved request")
    return value


def catalog():
    return [{"id": "grok_" + kind, "kind": kind, "input": "text",
             "output": "research_with_citations" if kind == "research" else kind + "_artifact",
             "model": model, "enabled": False, "reason": BLOCKED,
             "cost_usd": None, "auth_kind": "session", "upstream_commit": PIN, "options": dict(OPTIONS[kind]), "model_verified": False}
            for kind, model in MODELS.items()]


def video_duration(value):
    if type(value) is not int or not 1 <= value <= 15:
        raise ContractError("영상 길이는 정수 1~15초로 지정하세요.")
    return value


def plan(body):
    if not isinstance(body, dict) or set(body) - {"kind", "text", "duration"}:
        raise ContractError("Unsupported request fields")
    kind, text = body.get("kind"), body.get("text")
    if not isinstance(kind, str) or kind not in MODELS or not isinstance(text, str) or not text.strip() or len(text) > 12000 or "\0" in text:
        raise ContractError("Invalid typed request")
    if "duration" in body and kind != "video":
        raise ContractError("Duration is supported only for video requests")
    options = dict(OPTIONS[kind])
    if kind == "video":
        options["duration"] = video_duration(body.get("duration", 5))  # Legacy saved flows used five seconds.
    request = {"kind": kind, "text": text, "model": MODELS[kind], "auth_kind": "session", "upstream_commit": PIN, "options": options}
    if kind == "video":
        request["duration"] = options["duration"]
    request_hash = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"request": request, "request_hash": request_hash, "enabled": False, "reason": BLOCKED,
            "cost_usd": None, "approval_checklist": ["reviewed_install", "session_file_access", "model:" + MODELS[kind],
                                                       "external_transfer", "unknown_cost", "one_use_request:" + request_hash],
            "retry_submission": False, "simulation": False}


def execute(_body):
    # No boolean consent, environment toggle, or plan can activate a transport.
    raise ContractError(BLOCKED)


def child_env(env):
    """Allowlist process environment; no key, token, proxy or CLI overrides."""
    allowed = {"systemroot", "windir", "path", "temp", "tmp", "lang", "lc_all"}
    return {key: value for key, value in env.items() if key.lower() in allowed}


def artifact_path(root, relative):
    if not isinstance(relative, str) or not relative or any(ord(c) < 32 or c in '\\:<>"|?*' for c in relative):
        raise ContractError("Unsafe artifact path")
    parts = relative.split("/")
    if any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts) or PureWindowsPath(relative).is_absolute():
        raise ContractError("Unsafe artifact path")
    base = Path(root)
    for candidate in [base, *base.parents]:
        if _linked(candidate):
            raise ContractError("Linked artifact root")
    path = base
    for part in parts:
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?", part):
            raise ContractError("Reserved artifact path")
        path = path / part
        if _linked(path):
            raise ContractError("Linked artifact path")
    if not path.resolve().is_relative_to(base.resolve()):
        raise ContractError("Artifact escaped root")
    return path


def _linked(path):
    try:
        info = path.lstat()
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def verify_artifact(root, relative, kind):
    path = artifact_path(root, relative)
    if kind not in ("image", "video") or not path.is_file() or not 0 < path.stat().st_size <= 100_000_000:
        raise ContractError("Invalid artifact")
    with path.open("rb") as stream:
        header = stream.read(32)
    image = (path.suffix.lower() == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n")) or (path.suffix.lower() in (".jpg", ".jpeg") and header.startswith(b"\xff\xd8\xff"))
    video = (path.suffix.lower() == ".mp4" and len(header) >= 12 and header[4:8] == b"ftyp") or (path.suffix.lower() == ".webm" and header.startswith(b"\x1aE\xdf\xa3"))
    if not (image if kind == "image" else video):
        raise ContractError("Artifact type mismatch")
    return path


def parse_result(raw, kind):
    """Validate a CLI envelope without saving untrusted stderr/raw JSON."""
    if not isinstance(kind, str) or kind not in MODELS or not isinstance(raw, str) or len(raw.encode()) > 1_000_000:
        raise ContractError("Invalid result")
    try:
        value = strict_json(raw)
    except (ValueError, TypeError):
        raise ContractError("Malformed result") from None
    common = {"ok", "module", "operation", "run_id", "result_path", "artifacts", "elapsed_seconds", "cost_usd", "warnings", "auth_kind", "model"}
    extras = {"research": {"answer", "citations", "tool_call_counts", "response_status", "requested_model", "response_id", "usage", "incomplete_details", "search_items", "depth"}, "image": set(), "video": {"request_id", "duration"}}
    if not isinstance(value, dict) or set(value) - common - extras[kind]:
        raise ContractError("Unsupported result fields")
    module = "search" if kind == "research" else kind
    operation = ("web", "x") if kind == "research" else ("generate",)
    if value.get("ok") is not True or value.get("module") != module or value.get("operation") not in operation or value.get("auth_kind") != "session" or value.get("model") != MODELS[kind]:
        raise ContractError("Unverified session result")
    cost = value.get("cost_usd")
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ContractError("Invalid cost")
    if not isinstance(value.get("artifacts"), list) or len(value["artifacts"]) > 12 or any(not isinstance(v, str) for v in value["artifacts"]):
        raise ContractError("Invalid artifacts")
    if kind == "video" and (not isinstance(value.get("request_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value["request_id"])):
        raise ContractError("Missing structured video request ID; outcome unknown")
    if kind == "research" and (value.get("response_status") not in ("completed", "incomplete") or not isinstance(value.get("answer"), str) or not isinstance(value.get("citations"), list)):
        raise ContractError("Incomplete research")
    if kind == "video":
        reported_video_duration(value.get("duration"))
    return value


def request_body(request):
    """Validate both public typed inputs and our complete immutable request envelope."""
    if not isinstance(request, dict):
        raise ContractError("Invalid request object")
    if "options" not in request:
        if set(request) - {"kind", "text", "duration"}:
            raise ContractError("Unsupported request fields")
        return {**request}
    if not isinstance(request["options"], dict):
        raise ContractError("Invalid request options")
    body = {"kind": request.get("kind"), "text": request.get("text")}
    if body["kind"] == "video":
        body["duration"] = request.get("duration")
    if request != plan(body)["request"]:
        raise ContractError("Immutable request options changed")
    return body


def command_contract(request, cache_dir, output=None, request_id=None):
    """Reviewable argv only. This module never launches the returned command."""
    planned = plan(request_body(request))["request"]
    argv = ["--auth", "session", "--cache-dir", str(cache_dir), "--timeout", "60"]
    kind = planned["kind"]
    if request_id is not None:
        if kind != "video" or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
            raise ContractError("GET requires the known video request ID")
        return argv + ["video", "get", request_id]  # no generate/POST retry
    if kind == "research":
        argv += ["search", "web", "--depth", "balanced", "--model", MODELS[kind]]
    elif kind == "image":
        argv += ["image", "generate", "--model", MODELS[kind], "--n", "1", "--aspect-ratio", "1:1", "--resolution", "1k"]
    else:
        argv += ["video", "generate", "--model", MODELS[kind], "--duration", str(planned["options"]["duration"]), "--resolution", "720p", "--aspect-ratio", "16:9", "--max-wait", "120", "--poll-interval", "5"]
    if kind != "research":
        if output is None:
            raise ContractError("Explicit local output is required")
        argv += ["--output", str(output)]
    return argv + ["--", planned["text"]]


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("Duplicate JSON fields")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ContractError("Non-finite JSON")))
    except (ValueError, TypeError, UnicodeError):
        raise ContractError("Invalid JSON response") from None


def connection_plan(body):
    if not isinstance(body, dict) or set(body) != {"cli_path", "auth_file"}:
        raise ContractError("Exact reviewed CLI and session file paths are required")
    config = {"source_pin": PIN, "source_sha256": CLI_SHA256}
    for key in ("cli_path", "auth_file"):
        value = body[key]
        if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 32 for c in value):
            raise ContractError("Invalid approved path")
        path = Path(value)
        if not path.is_absolute() or value.startswith(("\\\\", "//")) or ":" in value[2:] or any(_linked(p) for p in (path, *path.parents)):
            raise ContractError("Approved path must be absolute, local and unlinked")
        config[key] = str(path.resolve())
    if Path(config["cli_path"]).suffix.lower() != ".py" or Path(config["auth_file"]).name != "auth.json":
        raise ContractError("Reviewed Python CLI and exact auth.json path required")
    consent = ["execute_pinned_cli:" + CLI_SHA256, "direct_session_read:" + config["auth_file"],
               "external_transfer:api.x.ai,cli-chat-proxy.grok.com,provider_media_download", "unknown_cost:no_hard_billing_cap"]
    return {"config": config, "review_hash": digest(config), "consents": consent,
            "auth_verified": False, "source_url": f"https://raw.githubusercontent.com/sudoHG/grok-everywhere/{PIN}/grok-everywhere/scripts/grok.py",
            "limits": {"requests_per_consent": 1, "local_timeout_seconds": 180, "stdout_bytes": 1_000_000},
            "remote_cancel_supported": False, "enabled": False, "reason": BLOCKED,
            "subscription_scope": "unverified", "additional_charges": "not_authorized", "subscription_only_execution_supported": False}


def parse_video_read(raw, expected_id, operation):
    """Pinned get/resume omit auth_kind. Explicit session argv is not auth proof."""
    value = strict_json(raw)
    common = {"ok", "module", "operation", "run_id", "result_path", "artifacts", "elapsed_seconds", "cost_usd", "warnings", "request_id", "model", "duration"}
    extra = {"status", "progress", "video_url"} if operation == "get" else set()
    if not isinstance(value, dict) or set(value) - common - extra or value.get("ok") is not True or value.get("module") != "video" or value.get("operation") != operation or value.get("request_id") != expected_id:
        raise ContractError("Invalid known-request video response")
    if operation == "get" and value.get("status") not in ("pending", "processing", "queued", "in_progress", "completed", "done", "failed", "expired"):
        raise ContractError("Invalid video status")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) > 12 or any(not isinstance(p, str) for p in artifacts):
        raise ContractError("Invalid video artifacts")
    cost = value.get("cost_usd")
    if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
        raise ContractError("Invalid cost")
    return value


class Executor:
    """Only reviewed source can run, only with a request-bound one-use consent.

    Installation/session access is deliberately NOT performed by construction.
    Configuration is metadata, never a credential. No automatic paid retries.
    """
    def __init__(self, store, *, process_factory=None):
        self.store = store
        self._process_factory = process_factory or subprocess.Popen
        self._owned = {}
        self._cancelled = set()
        self._lock = threading.RLock()

    def status(self):
        config = read_json(self.store.dir / "grok-connection.json", None)
        if not config:
            return {"enabled": False, "configured": False, "auth_verified": False, "reason": BLOCKED}
        try:
            reviewed = connection_plan({key: config[key] for key in ("cli_path", "auth_file")})
            if config.get("review_hash") != reviewed["review_hash"] or config.get("consents") != reviewed["consents"]:
                raise ContractError("Unreviewed configuration")
            cli = Path(reviewed["config"]["cli_path"])
            if not cli.is_file() or cli.stat().st_size > 200_000 or sha256_file(cli) != CLI_SHA256:
                raise ContractError("Pinned CLI checksum mismatch")
            return {"enabled": True, "configured": True, "auth_verified": False, "reason": "검토한 설치 설정됨 · 실제 세션 미확인 · 매 요청 일회 승인 필요", "config_hash": reviewed["review_hash"]}
        except (KeyError, ValueError, OSError):
            return {"enabled": False, "configured": True, "auth_verified": False, "reason": "핀 소스·경로·설치 승인 검증 실패"}

    def configure(self, body):
        if not isinstance(body, dict) or set(body) != {"cli_path", "auth_file", "review_hash", "consents"}:
            raise ContractError("Exact connection review required")
        review = connection_plan({k: body[k] for k in ("cli_path", "auth_file")})
        if body["review_hash"] != review["review_hash"] or body["consents"] != review["consents"]:
            raise ContractError("Connection review changed or consent denied")
        cli = Path(review["config"]["cli_path"])
        if not cli.is_file() or cli.stat().st_size > 200_000 or sha256_file(cli) != CLI_SHA256:
            raise ContractError("Pinned CLI checksum mismatch")
        with self.store.lock:
            atomic_write_json(self.store.dir / "grok-connection.json", {**review["config"], "review_hash": review["review_hash"], "consents": review["consents"]})
        return self.status()

    def approve_request(self, body):
        if not isinstance(body, dict) or set(body) != {"request", "request_hash", "config_hash", "consents"}:
            raise ContractError("Exact one-use request review required")
        status = self.status()
        proposal = plan(body["request"])
        expected = proposal["approval_checklist"]
        if not status["enabled"] or body["config_hash"] != status.get("config_hash") or body["request_hash"] != proposal["request_hash"] or body["consents"] != expected:
            raise ContractError("Request, configuration or explicit consents changed")
        grant = secrets.token_hex(16)
        with self.store.lock:
            atomic_write_json(self.store.dir / "grok-consents" / (grant + ".json"), {"request_hash": proposal["request_hash"], "config_hash": status["config_hash"], "used_by": None})
        return {"grant_id": grant, "request_hash": proposal["request_hash"], "one_use": True}

    def check_consent(self, grant, request):
        if not isinstance(grant, str) or not re.fullmatch(r"[a-f0-9]{32}", grant):
            raise ContractError("Missing one-use consent")
        receipt = read_json(self.store.dir / "grok-consents" / (grant + ".json"), {})
        status = self.status()
        if not status["enabled"] or receipt.get("used_by") or receipt.get("config_hash") != status.get("config_hash") or receipt.get("request_hash") != plan(request)["request_hash"]:
            raise ContractError("Consent used, stale or mismatched")
        return receipt

    def _path(self, execution_id):
        if not isinstance(execution_id, str) or not re.fullmatch(r"[a-f0-9]{32}", execution_id):
            raise ContractError("Invalid execution ID")
        return self.store.dir / "grok-executions" / (execution_id + ".json")

    def _save(self, execution_id, record):
        atomic_write_json(self._path(execution_id), record)
        append_jsonl(self.store.dir / "grok-executions" / "events.jsonl", {"at": now_iso(), "execution_id": execution_id, "status": record["status"]})

    def execute(self, request, grant, execution_id):
        proposal = plan(request)
        with self.store.lock:
            path = self._path(execution_id)
            old = read_json(path, None)
            if old:
                if old["request_hash"] != proposal["request_hash"]:
                    raise ContractError("Execution ID reused for another request")
                return old  # includes interrupted/unknown outcome; NEVER replay POST.
            receipt = self.check_consent(grant, request)
            receipt["used_by"] = execution_id
            atomic_write_json(self.store.dir / "grok-consents" / (grant + ".json"), receipt)
            record = {"request_hash": proposal["request_hash"], "config_hash": receipt["config_hash"], "kind": request["kind"], "status": "reserved", "cost_usd": None,
                      "request_id": None, "simulation": False, "model_verified": False, "remote_cancel_supported": False,
                      "requested_duration": proposal["request"]["options"].get("duration")}
            self._save(execution_id, record)
        try:
            raw, cache = self._run(request, execution_id)
            value = parse_result(raw, request["kind"])
            with self.store.lock:
                record = read_json(path, record)
                if record["status"] == "cancelled_local":
                    return record
                record["request_id"] = value.get("request_id")
                record["cost_usd"] = value.get("cost_usd")
                self._save(execution_id, record)  # structured ID preserved before import.
            if request["kind"] == "video":
                reported_video_duration(value.get("duration"), record["requested_duration"])
            if value.get("response_status") == "incomplete":
                raise ContractError("Incomplete research; no automatic retry")
            result = self._archive(value, cache, execution_id, request["kind"])
            if request["kind"] == "video":
                result["requested_duration"] = record["requested_duration"]
            with self.store.lock:
                record = read_json(path, record)
                if record["status"] == "cancelled_local":
                    return record
                record.update(status="completed", result=result)
                self._save(execution_id, record)
            return record
        except (ValueError, OSError, RuntimeError):
            with self.store.lock:
                record = read_json(path, record)
                record["status"] = "cancelled_local" if record.get("status") == "cancelled_local" or execution_id in self._cancelled else "unknown_outcome"
                record["error"] = "실행 결과 불확실 · 자동 재제출 없음 · 로컬 중단은 원격 작업 취소가 아닙니다."
                self._save(execution_id, record)
            return record

    def read_video(self, execution_id, *, download=False):
        with self.store.lock:
            record = read_json(self._path(execution_id), {})
            request_id = record.get("request_id")
            if record.get("status") == "completed":
                return record
            if record.get("config_hash") != self.status().get("config_hash"):
                raise ContractError("Originating connection approval changed")
            if record.get("kind") != "video" or not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id) or record.get("status") in ("reserved", "cancelled_local"):
                raise ContractError("Known existing video request required; no regeneration")
        request = {"kind": "video", "text": "GET known request"}
        raw, cache = self._run(request, execution_id, request_id=request_id, download=download)
        value = parse_video_read(raw, request_id, "resume" if download else "get")
        reported_video_duration(value.get("duration"), record.get("requested_duration"))
        with self.store.lock:
            record = read_json(self._path(execution_id), record)
            if record.get("status") == "cancelled_local":
                raise ContractError("Cancelled locally; cannot revive")
            # get has a signed URL, but it is deliberately never retained.
            record["last_get"] = {"request_id": request_id, "operation": value["operation"], "status": value.get("status", "completed"), "auth_verification": "unreported", "model_verified": False}
            if download:
                record["result"] = self._archive(value, cache, execution_id, "video")
                record["result"]["requested_duration"] = record.get("requested_duration")
                record["status"] = "completed"
            self._save(execution_id, record)
            return record

    def cancel_local(self, execution_id):
        with self.store.lock, self._lock:
            record = read_json(self._path(execution_id), None)
            if not record:
                raise ContractError("Unknown owned execution")
            if record["status"] == "completed":
                return record
            self._cancelled.add(execution_id)
            process = self._owned.get(execution_id)
            if process and process.poll() is None:
                process.kill()  # only this Popen object, never PID enumeration.
            record.update(status="cancelled_local", error="로컬 프로세스만 중단 · 원격 영상 작업 취소 미지원 · 재제출 없음")
            self._save(execution_id, record)
            return record

    def shutdown(self):
        with self._lock:
            identifiers = list(self._owned)
        for identifier in identifiers:
            self.cancel_local(identifier)

    def _run(self, request, execution_id, request_id=None, download=False):
        with self.store.lock:
            status = self.status()
            if not status["enabled"]:
                raise ContractError(BLOCKED)
            record = read_json(self._path(execution_id), {})
            if record.get("config_hash") != status.get("config_hash"):
                raise ContractError("Originating connection changed; no invocation")
            config = read_json(self.store.dir / "grok-connection.json", {})
        # A fresh scratch directory for every invocation; never import raw cache.
        relative = "grok-scratch/" + execution_id + "/" + secrets.token_hex(8)
        cache = artifact_path(self.store.dir, relative)
        cache.mkdir(parents=True, exist_ok=False)
        reviewed_cli = artifact_path(cache, "reviewed-cli.py")
        atomic_copy(Path(config["cli_path"]), reviewed_cli)
        if sha256_file(reviewed_cli) != CLI_SHA256:
            raise ContractError("Copied reviewed CLI checksum mismatch")
        output = cache / ("result.png" if request["kind"] == "image" else "result.mp4")
        argv = command_contract(request, cache, output=output, request_id=request_id)
        argv[0:0] = ["--auth-file", config["auth_file"]]
        if download:
            argv[-3:] = ["video", "resume", request_id, "--max-wait", "120", "--poll-interval", "5", "--output", str(output)]
        env = child_env(os.environ)
        # Pinned parser evaluates these defaults eagerly; inject only approved
        # values rather than retaining HOME/USERPROFILE or inherited overrides.
        env.update(GROK_HOME=str(Path(config["auth_file"]).parent), GROK_EVERYWHERE_CACHE=str(cache))
        with self._lock:
            if execution_id in self._cancelled or execution_id in self._owned:
                raise ContractError("Cancelled or existing invocation active")
            process = self._process_factory([sys.executable, "-I", "-S", str(reviewed_cli), *argv], cwd=cache, env=env, shell=False,
                                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=no_window_flags())
            self._owned[execution_id] = process
        stdout = bytearray()
        excessive = threading.Event()
        def drain(stream, keep):
            count = 0
            try:
                while chunk := stream.read(8192):
                    count += len(chunk)
                    if count > 1_000_000:
                        excessive.set()
                        if process.poll() is None:
                            process.kill()
                        break
                    if keep:
                        stdout.extend(chunk)
            except (OSError, ValueError):
                excessive.set()
                if process.poll() is None:
                    process.kill()
        readers = [threading.Thread(target=drain, args=(process.stdout, True), daemon=True), threading.Thread(target=drain, args=(process.stderr, False), daemon=True)]
        for reader in readers:
            reader.start()
        try:
            try:
                deadline = time.monotonic() + 180
                while process.poll() is None:
                    total, count = 0, 0
                    for folder, dirs, files in os.walk(cache, followlinks=False):
                        for entry in [*dirs, *files]:
                            item = Path(folder) / entry
                            if _linked(item):
                                process.kill()
                                raise ContractError("Unsafe execution scratch link")
                        for name in files:
                            count += 1
                            total += (Path(folder) / name).stat().st_size
                            if count > 128 or total > 120_000_000:
                                process.kill()
                                raise ContractError("Execution scratch exceeded bound")
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired("owned CLI", 180)
                    try:
                        process.wait(timeout=.1)
                    except subprocess.TimeoutExpired:
                        pass
                code = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                raise ContractError("Timeout; outcome unknown") from None
            for reader in readers:
                reader.join(timeout=5)
            if code or excessive.is_set() or any(reader.is_alive() for reader in readers):
                raise ContractError("CLI output invalid; stderr discarded")
            return bytes(stdout).decode("utf-8", "strict"), cache
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for reader in readers:
                reader.join(timeout=2)
            # Only the pinned invocation's bounded structured submission ID is
            # recoverable; never inspect stderr, signed URLs or raw responses.
            if request["kind"] == "video" and request_id is None:
                self._recover_submission(cache, execution_id)
            with self._lock:
                self._owned.pop(execution_id, None)
            process.stdout.close()
            process.stderr.close()

    def _recover_submission(self, cache, execution_id):
        runs = cache / "runs"
        if not runs.exists() or _linked(runs):
            return
        folders = list(runs.iterdir())
        if len(folders) > 16:
            return
        recovered = []
        for folder in folders:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", folder.name) or _linked(folder):
                continue
            path = folder / "submission.json"
            if not path.is_file() or _linked(path) or path.stat().st_size > 16384:
                continue
            try:
                with path.open("rb") as stream:
                    raw = stream.read(16385)
                if len(raw) > 16384:
                    continue
                value = strict_json(raw.decode("utf-8", "strict"))
                identifier = (value.get("request_id") or value.get("id")) if isinstance(value, dict) else None
                if isinstance(identifier, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", identifier):
                    recovered.append(identifier)
            except (ValueError, OSError):
                continue
        if len(set(recovered)) == 1:
            with self.store.lock:
                record = read_json(self._path(execution_id), {})
                if record and not record.get("request_id"):
                    record["request_id"] = recovered[0]
                    self._save(execution_id, record)

    def _archive(self, value, cache, execution_id, kind):
        selected = []
        if kind != "research":
            for raw_path in value["artifacts"]:
                candidate = Path(raw_path)
                if candidate.suffix.lower() not in (".png", ".jpg", ".jpeg", ".mp4", ".webm"):
                    continue
                if not candidate.is_absolute() or not candidate.is_relative_to(cache):
                    raise ContractError("Artifact escaped execution cache")
                source = verify_artifact(cache, candidate.relative_to(cache).as_posix(), kind)
                relative = f"grok-artifacts/{execution_id}/artifact-{len(selected) + 1}{source.suffix.lower()}"
                target = artifact_path(self.store.dir, relative)
                if target.exists():
                    if sha256_file(target) != sha256_file(source):
                        raise ContractError("Archived artifact cannot be overwritten")
                else:
                    atomic_copy(source, target)
                selected.append({"path": relative, "sha256": sha256_file(target), "kind": kind})
            if not selected:
                raise ContractError("Missing verified media")
        citations = []
        # Pinned research returns annotation dictionaries. Publish only bounded
        # public title/URL, not offsets, opaque metadata or signed query URLs.
        for annotation in value.get("citations", [])[:40]:
            if not isinstance(annotation, dict):
                continue
            url, title = annotation.get("url"), annotation.get("title", "")
            if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 32 for c in url):
                continue
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                continue
            citations.append({"url": url, "title": title[:300] if isinstance(title, str) else ""})
        return {"kind": kind, "reported_duration": value.get("duration") if kind == "video" else None, "answer": value.get("answer"), "citations": citations, "artifacts": selected,
                "cost_usd": value.get("cost_usd"), "requested_model": MODELS[kind], "reported_model": value.get("model"),
                "model_verified": False, "simulation": False}
