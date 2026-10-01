"""AI 탑재: 직원마다 어떤 AI(실행기·모델·생각 깊이)를 끼울지 (SPEC 'AI 탑재').

- 고를 수 있는 목록은 지어내지 않는다. Codex는 설치된 CLI의 공식 모델 목록(`codex debug models`, 화면에 보이는 것만),
  Claude는 CLI 도움말에 적힌 별칭(fable·opus·sonnet)과 계정 기본 모델.
- 파일을 고치는 일(샌드박스가 read-only가 아닌 역할)에는 Codex만 끼운다. Claude 실행기는 읽기 도구만 쓴다 (AGENTS.md 불변식 3).
- 샌드박스·권한은 역할이 정한다. AI를 바꿔도 그대로다.
- 바꾼 값은 data/ai.json에 둔다 (studio.toml은 건드리지 않는다). '처음대로'는 studio.toml 값으로 돌린다.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .config import Config
from .runtimes import find_codex, find_grok, grok_login
from .store import Store
from .util import clean_child_env

EFFORT_LABELS = {"low": "얕게", "medium": "보통", "high": "깊게", "xhigh": "아주 깊게", "max": "최대", "ultra": "끝까지"}
CLAUDE_EFFORTS = ["low", "medium", "high", "xhigh", "max"]  # claude --help: --effort (low, medium, high, xhigh, max)
CLAUDE_MODELS = [  # claude --help: --model 별칭 예시 'fable', 'opus', 'sonnet'
    {"slug": "", "name": "계정 기본", "desc": "Claude 계정에 정해진 기본 모델"},
    {"slug": "fable", "name": "Fable", "desc": "Claude 최신 최상위 모델"},
    {"slug": "opus", "name": "Opus", "desc": "Claude 고급 모델"},
    {"slug": "sonnet", "name": "Sonnet", "desc": "Claude 빠른 균형형 모델"},
]
# Codex 공식 목록의 영어 설명을 쉬운 한국어로 (목록에 없는 모델은 설명 없이 이름만)
CODEX_DESC = {
    "gpt-6-astra": "가장 똑똑함 · 어려운 일용 (사용량 많음)",
    "gpt-6-sol": "코딩 주력 · 일상 작업",
    "gpt-6-luna": "빠르고 가벼움 · 쉬운 일용",
    "gpt-5.6-sol": "이전 세대 · 복잡한 코딩",
    "gpt-5.6-terra": "이전 세대 · 균형형",
    "gpt-5.6-luna": "이전 세대 · 빠름",
    "gpt-5.5": "옛 코딩 모델",
}

_cache: dict[str, list[dict]] = {}


class AIError(ValueError):
    pass


def codex_models(cfg: Config, refresh: bool = False) -> list[dict]:
    """Codex 공식 모델 목록 (화면에 보이는 것만). 못 읽으면 설정에 적힌 모델만 돌려준다."""
    if not refresh and "codex" in _cache:
        return _cache["codex"]
    models: list[dict] = []
    info = find_codex(str(cfg.runtime_cfg("codex").get("path", "") or ""))
    if info.get("found"):
        try:
            p = subprocess.run([*info["cmd"], "debug", "models"], capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=30, env=clean_child_env(), cwd=str(cfg.root))
            for m in json.loads(p.stdout).get("models", []):
                if m.get("visibility") != "list" or not m.get("slug"):
                    continue
                models.append({
                    "slug": str(m["slug"]),
                    "name": str(m.get("display_name") or m["slug"]),
                    "efforts": [str(e["effort"]) for e in m.get("supported_reasoning_levels") or [] if e.get("effort") in EFFORT_LABELS],
                    "default_effort": str(m.get("default_reasoning_level") or ""),
                })
        except (OSError, ValueError, subprocess.SubprocessError, TypeError, AttributeError, KeyError):
            models = []
    if not models:  # 지어내지 않는다: 설정에 이미 적힌 모델만
        seen = sorted({r.model for r in cfg.roles.values() if r.runtime == "codex" and r.model}
                      | {r.fallback_model for r in cfg.roles.values() if r.fallback_runtime == "codex" and r.fallback_model})
        models = [{"slug": s, "name": s, "efforts": [], "default_effort": ""} for s in seen]
    for m in models:
        m["desc"] = CODEX_DESC.get(m["slug"], "")
    _cache["codex"] = models
    return models


def writes_files(cfg: Config, role: str) -> bool:
    return cfg.roles[role].sandbox != "read-only"


def draw_options(cfg: Config) -> list[dict[str, Any]]:
    """그림을 그리는 AI (꾸미기 공방·캐릭터 제조실). Grok은 설치·로그인이 됐을 때만 고를 수 있다 (1분 기억)."""
    import time

    now = time.monotonic()
    cached = _cache.get("draw")
    if cached and now - cached[0]["at"] < 60:
        return cached
    info = find_grok(str(cfg.runtime_cfg("grok").get("path", "") or ""))
    logged = grok_login(info)
    note = "" if logged else ("grok login이 필요해요" if info.get("found") else "Grok CLI가 없어요")
    out = [
        {"key": "codex", "label": "Codex", "ok": True, "note": "기본 · 가로 그림", "at": now},
        {"key": "grok", "label": "Grok", "ok": logged, "note": note or "정사각형 그림 · 아직 시험 단계", "at": now},
    ]
    _cache["draw"] = out
    return out


def options(cfg: Config) -> dict[str, Any]:
    return {
        "codex": codex_models(cfg),
        "claude": [{**m, "efforts": CLAUDE_EFFORTS, "default_effort": ""} for m in CLAUDE_MODELS],
        "effort_labels": EFFORT_LABELS,
        "writes": {key: writes_files(cfg, key) for key in cfg.roles},
        "draw": [{k: v for k, v in d.items() if k != "at"} for d in draw_options(cfg)],
    }


def clean(cfg: Config, role: str, data: Any) -> dict[str, str]:
    """화면에서 온 값을 허용 목록으로만 받는다. 맞지 않으면 쉬운 말로 거절한다."""
    if role not in cfg.roles:
        raise AIError(f"알 수 없는 직원: {role}")
    data = data if isinstance(data, dict) else {}
    runtime = str(data.get("runtime", ""))
    model = str(data.get("model", "") or "")
    effort = str(data.get("effort", "") or "")
    if runtime == "codex":
        catalog = {m["slug"]: m for m in codex_models(cfg)}
        if model and model not in catalog:
            raise AIError(f"Codex 목록에 없는 모델입니다: {model}")
        efforts = catalog[model]["efforts"] if model else list(EFFORT_LABELS)
    elif runtime == "claude":
        if writes_files(cfg, role):
            raise AIError(f"{cfg.roles[role].name}의 일은 파일을 고쳐야 해서 Codex만 끼울 수 있어요 (Claude는 읽기 전용).")
        if model not in {m["slug"] for m in CLAUDE_MODELS}:
            raise AIError(f"Claude 목록에 없는 모델입니다: {model}")
        efforts = CLAUDE_EFFORTS
    else:
        raise AIError("AI는 codex 또는 claude만 끼울 수 있어요.")
    if effort and effort not in efforts:
        raise AIError(f"이 모델은 생각 깊이 '{EFFORT_LABELS.get(effort, effort)}'를 쓸 수 없어요.")
    return {"runtime": runtime, "model": model, "effort": effort}


def current(cfg: Config, role: str) -> dict[str, str]:
    r = cfg.roles[role]
    return {"runtime": r.runtime, "model": r.model, "effort": r.effort}


def _set(cfg: Config, role: str, value: dict[str, str]) -> None:
    r = cfg.roles[role]
    r.runtime, r.model, r.effort = value["runtime"], value["model"], value["effort"]


def apply_saved(cfg: Config, store: Store) -> dict[str, dict[str, str]]:
    """시작할 때: studio.toml 값을 '처음 값'으로 기억하고, data/ai.json에 바꿔 둔 값을 끼운다.

    저장된 값이 지금 규칙에 맞지 않으면(모델이 목록에서 빠짐 등) 무시하고 처음 값을 쓴다.
    """
    defaults = {key: current(cfg, key) for key in cfg.roles}
    for role, value in (store.read_doc("ai", {}) or {}).items():
        if role not in cfg.roles:
            continue
        try:
            _set(cfg, role, clean(cfg, role, value))
        except AIError:
            continue
    return defaults


def save(cfg: Config, store: Store, defaults: dict[str, dict[str, str]], role: str, data: Any) -> dict[str, str]:
    value = clean(cfg, role, data)
    with store.lock:
        saved = store.read_doc("ai", {}) or {}
        if value == defaults.get(role):
            saved.pop(role, None)
        else:
            saved[role] = value
        store.write_doc("ai", saved)
        _set(cfg, role, value)
    return value


def reset(cfg: Config, store: Store, defaults: dict[str, dict[str, str]], role: str) -> dict[str, str]:
    if role not in cfg.roles:
        raise AIError(f"알 수 없는 직원: {role}")
    with store.lock:
        saved = store.read_doc("ai", {}) or {}
        saved.pop(role, None)
        store.write_doc("ai", saved)
        _set(cfg, role, defaults[role])
    return defaults[role]
