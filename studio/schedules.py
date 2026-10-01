"""업무 자동 시작 (벽시계): 정해 둔 때가 되면 직원이 스스로 일을 시작한다 (마누스 2.0의 '자동 시작'처럼).

종류 (kind)
- directive: 지시 → 기획 담당이 기획안을 만든다 → CEO가 회의실에서 퀘스트를 고른다 (지금 지시와 같다).
- research: 리서치 보고서를 바로 쓰기 시작한다 → CEO가 보고서를 결재한다.

때 (every)
- daily: 매일 at(HH:MM) · weekdays: 평일(월~금) at · weekly: 매주 weekday(0=월) at · hours: hours시간마다 (만든 때부터).

지키는 것
- 결재는 그대로 CEO가 한다 (자동으로 끝나는 일은 없다).
- 긴급 정지 중이거나 오늘 에너지(실행 상한)를 다 썼으면 만들지 않고 기다린다. 때를 여러 번 넘겨도 한 번만 따라잡는다.
- 같은 자동 업무의 지난 일이 아직 안 끝났으면 새로 만들지 않고 건너뛴다 (일이 쌓이지 않게).
저장: data/schedules.json {"items": [...]}
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .config import Config
from .util import atomic_write_json, now_iso, read_json

KINDS = {"directive": "지시", "research": "리서치"}
EVERY = ("daily", "weekdays", "weekly", "hours")
DAYS = ["월", "화", "수", "목", "금", "토", "일"]
MAX_ITEMS = 20
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScheduleError(ValueError):
    pass


def _path(cfg: Config):
    return cfg.data_dir / "schedules.json"


def load(cfg: Config) -> list[dict[str, Any]]:
    data = read_json(_path(cfg), {}) or {}
    items = data.get("items") if isinstance(data, dict) else None
    return [x for x in items or [] if isinstance(x, dict) and re.fullmatch(r"S\d{1,4}", str(x.get("id", "")))]


def save(cfg: Config, items: list[dict[str, Any]]) -> None:
    atomic_write_json(_path(cfg), {"items": items})


def _dt(text: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now().astimezone()


def last_due(item: dict[str, Any], now: datetime | None = None) -> datetime | None:
    """지금까지 가장 최근의 정해진 때 (만든 때 이후만). 아직 한 번도 오지 않았으면 None."""
    now = now or _now()
    created = _dt(item.get("created")) or now
    if item.get("every") == "hours":
        step = timedelta(hours=max(1, int(item.get("hours") or 1)))
        if now < created + step:
            return None
        return created + step * int((now - created) / step)
    hh, mm = (int(x) for x in str(item.get("at", "09:00")).split(":"))
    day = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if day > now:
        day -= timedelta(days=1)
    for _ in range(8):  # 조건에 맞는 날을 거슬러 찾는다
        ok = (item.get("every") == "daily" or (item.get("every") == "weekdays" and day.weekday() < 5)
              or (item.get("every") == "weekly" and day.weekday() == int(item.get("weekday") or 0)))
        if ok:
            return day if day >= created else None
        day -= timedelta(days=1)
    return None


def next_due(item: dict[str, Any], now: datetime | None = None) -> datetime:
    now = now or _now()
    if item.get("every") == "hours":
        created = _dt(item.get("created")) or now
        step = timedelta(hours=max(1, int(item.get("hours") or 1)))
        return created + step * (int((now - created) / step) + 1)
    hh, mm = (int(x) for x in str(item.get("at", "09:00")).split(":"))
    day = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if day <= now:
        day += timedelta(days=1)
    for _ in range(8):
        if (item.get("every") == "daily" or (item.get("every") == "weekdays" and day.weekday() < 5)
                or (item.get("every") == "weekly" and day.weekday() == int(item.get("weekday") or 0))):
            return day
        day += timedelta(days=1)
    return day


def describe(item: dict[str, Any]) -> str:
    every = item.get("every")
    if every == "hours":
        return f"{item.get('hours')}시간마다"
    at = item.get("at", "09:00")
    if every == "weekdays":
        return f"평일 {at}"
    if every == "weekly":
        return f"매주 {DAYS[int(item.get('weekday') or 0)]}요일 {at}"
    return f"매일 {at}"


def is_due(item: dict[str, Any], now: datetime | None = None) -> datetime | None:
    """지금 시작해야 하면 그 정해진 때를, 아니면 None."""
    if not item.get("enabled", True):
        return None
    when = last_due(item, now)
    last = _dt(item.get("last_run"))
    return when if when and (last is None or last < when) else None


def view(cfg: Config) -> list[dict[str, Any]]:
    """화면용: 저장한 값 + 언제(글) · 다음 때."""
    now = _now()
    return [{**x, "when": describe(x), "next": next_due(x, now).isoformat(timespec="minutes") if x.get("enabled", True) else ""}
            for x in load(cfg)]


def add(cfg: Config, data: dict[str, Any]) -> dict[str, Any]:
    items = load(cfg)
    if len(items) >= MAX_ITEMS:
        raise ScheduleError(f"자동 업무는 {MAX_ITEMS}개까지예요.")
    kind = str(data.get("kind", ""))
    if kind not in KINDS:
        raise ScheduleError("무엇을 할지(지시·리서치) 골라 주세요.")
    title = " ".join(str(data.get("title", "")).split())[:40]
    text = str(data.get("text", "")).strip()
    if not title or not text:
        raise ScheduleError("제목과 내용을 적어 주세요.")
    if len(text) > 2000:
        raise ScheduleError("내용은 2000자 이내로 적어 주세요.")
    project = str(data.get("project", ""))
    if project not in cfg.projects:
        raise ScheduleError("프로젝트를 골라 주세요.")
    every = str(data.get("every", "daily"))
    if every not in EVERY:
        raise ScheduleError("언제 할지 골라 주세요.")
    item: dict[str, Any] = {"kind": kind, "title": title, "text": text, "project": project, "every": every,
                            "enabled": True, "created": now_iso(), "last_run": "", "last_task": ""}
    if every == "hours":
        try:
            hours = int(data.get("hours") or 0)
        except (TypeError, ValueError):
            hours = 0
        if not 1 <= hours <= 168:
            raise ScheduleError("몇 시간마다인지 1~168로 적어 주세요.")
        item["hours"] = hours
    else:
        at = str(data.get("at", "")).strip()
        if not TIME_RE.match(at):
            raise ScheduleError("시각을 00:00~23:59로 적어 주세요.")
        item["at"] = at
        if every == "weekly":
            try:
                weekday = int(data.get("weekday"))
            except (TypeError, ValueError):
                weekday = -1
            if not 0 <= weekday <= 6:
                raise ScheduleError("요일을 골라 주세요.")
            item["weekday"] = weekday
    n = max([int(x["id"][1:]) for x in items] or [0]) + 1
    item = {"id": f"S{n}", **item}
    save(cfg, items + [item])
    return item


def update(cfg: Config, sid: str, **changes: Any) -> dict[str, Any]:
    items = load(cfg)
    item = next((x for x in items if x["id"] == sid), None)
    if not item:
        raise ScheduleError("그런 자동 업무가 없어요.")
    item.update(changes)
    save(cfg, items)
    return item


def remove(cfg: Config, sid: str) -> dict[str, Any]:
    items = load(cfg)
    item = next((x for x in items if x["id"] == sid), None)
    if not item:
        raise ScheduleError("그런 자동 업무가 없어요.")
    save(cfg, [x for x in items if x["id"] != sid])
    return item
