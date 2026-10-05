"""Offline contract for pinned Grok Everywhere. No transport is installed or invoked.

Session compatibility is third-party, not a guarantee of free generation. This
boundary intentionally cannot turn a plan or a workbench note into execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import stat
from pathlib import Path, PureWindowsPath

PIN = "4c6fad3eca694b4bc1c9fedea41ae236139f2044"
BLOCKED = "Grok Everywhere 실행 차단: 검토된 설치, 세션 파일 접근, 외부 전송 및 알 수 없는 비용에 대한 별도 승인이 필요합니다."
MODELS = {"research": "grok-4.6", "image": "grok-imagine-image-2.0", "video": "grok-imagine-video-1.5"}
OPTIONS = {"research": {"source": "web", "depth": "balanced"},
           "image": {"count": 1, "aspect_ratio": "1:1", "resolution": "1k"},
           "video": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "max_wait": 120, "poll_interval": 5}}


class ContractError(ValueError):
    pass


def catalog():
    return [{"id": "grok_" + kind, "kind": kind, "input": "text",
             "output": "research_with_citations" if kind == "research" else kind + "_artifact",
             "model": model, "enabled": False, "reason": BLOCKED,
             "cost_usd": None, "auth_kind": "session", "upstream_commit": PIN, "options": dict(OPTIONS[kind]), "model_verified": False}
            for kind, model in MODELS.items()]


def plan(body):
    if not isinstance(body, dict) or set(body) - {"kind", "text"}:
        raise ContractError("Unsupported request fields")
    kind, text = body.get("kind"), body.get("text")
    if not isinstance(kind, str) or kind not in MODELS or not isinstance(text, str) or not text.strip() or len(text) > 12000 or "\0" in text:
        raise ContractError("Invalid typed request")
    request = {"kind": kind, "text": text, "model": MODELS[kind], "auth_kind": "session", "upstream_commit": PIN, "options": dict(OPTIONS[kind])}
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
        value = json.loads(raw)
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
    return value


def command_contract(request, cache_dir, output=None, request_id=None):
    """Reviewable argv only. This module never launches the returned command."""
    planned = plan({"kind": request.get("kind"), "text": request.get("text")})["request"]
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
        argv += ["video", "generate", "--model", MODELS[kind], "--duration", "5", "--resolution", "720p", "--aspect-ratio", "16:9", "--max-wait", "120", "--poll-interval", "5"]
    if kind != "research":
        if output is None:
            raise ContractError("Explicit local output is required")
        argv += ["--output", str(output)]
    return argv + ["--", planned["text"]]
