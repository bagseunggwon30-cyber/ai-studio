"""본사 층 (CEO 결정 2026-09-29: 본사 새로 그리기 + 2층·별실 추가, 층 늘리기).

1층은 본사(퀘스트 보드·회의실·완성작·휴식터와 책상 6개), 2층부터는 일하는 층(책상 8개와 휴식터)이다.
책상은 1층 앞자리부터 차례로 앉는다: 기본 직원 4명이 1층 0~3번, 새 직원은 명부 순서대로 그다음 자리.
층을 늘리면 새 직원을 더 뽑을 수 있다. 층 수는 data/floors.json에 둔다 (CEO가 게임 화면에서 늘린다).
책상 수는 배경 그림에 맞춘 값이다 — 바꾸면 ui/scene.js FLOORS도 같이 바꾼다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .util import atomic_write_json, now_iso, read_json

if TYPE_CHECKING:
    from .config import Config

DESKS = (6, 8, 8)       # 층마다 책상 수 (1층, 2층, 3층)
MAX_FLOORS = len(DESKS)
FOUNDERS = ("producer", "builder", "reviewer", "analyst")  # 1층 0~3번 책상


class FloorError(ValueError):
    pass


def _path(cfg: "Config"):
    return cfg.data_dir / "floors.json"


def _read(cfg: "Config") -> dict:
    """data/floors.json. 없거나 깨졌으면 빈 값 (1층만 있는 회사)."""
    try:
        raw = read_json(_path(cfg), {})
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def count(cfg: "Config") -> int:
    raw = _read(cfg)
    try:
        n = int(raw.get("count", 1))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(MAX_FLOORS, n))


def desks(floors: int) -> int:
    return sum(DESKS[:max(1, min(MAX_FLOORS, floors))])


def capacity(cfg: "Config") -> int:
    """지금 층 수로 뽑을 수 있는 새 직원 수 (책상 수 - 기본 직원 4명)."""
    return desks(count(cfg)) - len(FOUNDERS)


MAX_STAFF = desks(MAX_FLOORS) - len(FOUNDERS)  # 층을 모두 늘렸을 때


def add(cfg: "Config") -> int:
    """층을 하나 늘린다. 새 층 번호를 돌려준다."""
    n = count(cfg)
    if n >= MAX_FLOORS:
        raise FloorError(f"층은 {MAX_FLOORS}층까지예요.")
    raw = _read(cfg)
    added = [str(x) for x in raw.get("added", [])][-20:] if isinstance(raw.get("added"), list) else []
    atomic_write_json(_path(cfg), {"count": n + 1, "added": [*added, now_iso()]})
    return n + 1


def seats(cfg: "Config") -> dict[str, int]:
    """직원마다 책상 번호 (0부터, 1층 앞자리부터). 층은 floor_of(번호)."""
    out = {key: i for i, key in enumerate(FOUNDERS) if key in cfg.roles}
    n = len(FOUNDERS)
    for key, role in cfg.roles.items():
        if role.job and key not in out:
            out[key] = n
            n += 1
    return out


def floor_of(seat: int) -> int:
    """책상 번호 → 층 (1부터). 층이 모자라면 마지막 층."""
    total = 0
    for i, d in enumerate(DESKS):
        total += d
        if seat < total:
            return i + 1
    return MAX_FLOORS


def info(cfg: "Config") -> dict:
    n = count(cfg)
    used = sum(1 for r in cfg.roles.values() if r.job)
    return {"count": n, "max": MAX_FLOORS, "desks": list(DESKS[:n]), "staff_max": capacity(cfg), "staff": used,
            "next_desks": DESKS[n] if n < MAX_FLOORS else 0}
