"""내장 MCP '시계·시간대' (clock): 지금 날짜·시각과 시간대 바꾸기. 읽기만 한다. (MCP 참고 서버 'Time'의 AI 스튜디오판)

보고서의 '확인 날짜'나 일정 계산에 쓴다. 이 PC의 파이썬에는 세계 시간대 자료(tzdata)가 없어서, 자주 쓰는 시간대는 규칙을
직접 넣었다 (미국·유럽·호주는 서머타임 규칙 포함). 그 밖에는 '+09:00'처럼 시차로 적으면 된다.
실행: python clock.py
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio.mcp_builtin.base import Server, ToolError, setup_stdio  # noqa: E402

H = timedelta(hours=1)
# 이름: (표준 시차, 서머타임 규칙) — 규칙 us/eu/au, 없으면 서머타임 없음
ZONES = {
    "UTC": (0, None), "Asia/Seoul": (9, None), "Asia/Tokyo": (9, None), "Asia/Shanghai": (8, None), "Asia/Hong_Kong": (8, None),
    "Asia/Taipei": (8, None), "Asia/Singapore": (8, None), "Asia/Kolkata": (5.5, None), "Asia/Dubai": (4, None),
    "Europe/London": (0, "eu"), "Europe/Paris": (1, "eu"), "Europe/Berlin": (1, "eu"), "Europe/Madrid": (1, "eu"),
    "Europe/Moscow": (3, None), "America/New_York": (-5, "us"), "America/Chicago": (-6, "us"), "America/Denver": (-7, "us"),
    "America/Los_Angeles": (-8, "us"), "America/Sao_Paulo": (-3, None), "Australia/Sydney": (10, "au"), "Pacific/Auckland": (12, "nz"),
}
ALIASES = {"KST": "Asia/Seoul", "JST": "Asia/Tokyo", "GMT": "UTC", "Z": "UTC", "서울": "Asia/Seoul", "한국": "Asia/Seoul",
           "도쿄": "Asia/Tokyo", "뉴욕": "America/New_York", "런던": "Europe/London", "파리": "Europe/Paris",
           "PST": "America/Los_Angeles", "EST": "America/New_York", "CET": "Europe/Paris"}
OFFSET_RE = re.compile(r"^(?:UTC|GMT)?([+-])(\d{1,2})(?::?(\d{2}))?$")


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    """그 달 n번째 일요일 (n=-1이면 마지막 일요일), 0시 UTC."""
    if n > 0:
        d = datetime(year, month, 1, tzinfo=timezone.utc)
        d += timedelta(days=(6 - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - 6) % 7)


def _dst(rule: str | None, utc: datetime, std: float) -> bool:
    """그 순간(UTC)이 서머타임인지."""
    y = utc.year
    if rule == "us":  # 3월 둘째 일요일 2시 ~ 11월 첫째 일요일 2시 (그 지역 시각)
        start = _nth_sunday(y, 3, 2) + timedelta(hours=2 - std)
        end = _nth_sunday(y, 11, 1) + timedelta(hours=2 - (std + 1))
        return start <= utc < end
    if rule == "eu":  # 3월 마지막 일요일 1시 UTC ~ 10월 마지막 일요일 1시 UTC
        return _nth_sunday(y, 3, -1) + H <= utc < _nth_sunday(y, 10, -1) + H
    if rule == "au":  # 10월 첫째 일요일 2시 ~ 4월 첫째 일요일 3시 (지역 시각, 남반구)
        return not (_nth_sunday(y, 4, 1) + timedelta(hours=3 - (std + 1)) <= utc < _nth_sunday(y, 10, 1) + timedelta(hours=2 - std))
    if rule == "nz":  # 9월 마지막 일요일 2시 ~ 4월 첫째 일요일 3시
        return not (_nth_sunday(y, 4, 1) + timedelta(hours=3 - (std + 1)) <= utc < _nth_sunday(y, 9, -1) + timedelta(hours=2 - std))
    return False


def zone_of(name: str) -> tuple[str, str | None, float | None]:
    """(보여 줄 이름, 규칙, 시차) — 시차가 None이면 이 PC 시간."""
    n = str(name or "").strip()
    if not n or n.lower() in ("local", "이 pc", "pc", "여기"):
        return "이 PC 시간", None, None
    n = ALIASES.get(n, ALIASES.get(n.upper(), n))
    for key, (std, rule) in ZONES.items():
        if key.lower() == n.lower():
            return key, rule, std
    m = OFFSET_RE.match(n.replace(" ", ""))
    if m:
        sign = 1 if m.group(1) == "+" else -1
        hours = int(m.group(2)) + int(m.group(3) or 0) / 60
        if hours <= 14:
            return f"UTC{m.group(1)}{int(m.group(2)):02d}:{int(m.group(3) or 0):02d}", None, sign * hours
    raise ToolError(f"모르는 시간대: {name}. zones 도구로 이름을 보거나 '+09:00'처럼 시차로 적어 주세요.")


def to_zone(utc: datetime, name: str) -> datetime:
    label, rule, std = zone_of(name)
    if std is None:
        return utc.astimezone()
    off = std + (1 if _dst(rule, utc, std) else 0)
    return utc.astimezone(timezone(timedelta(hours=off)))


def show(d: datetime, label: str) -> str:
    days = "월화수목금토일"
    off = d.utcoffset() or timedelta()
    mins = int(off.total_seconds() // 60)
    return f"{d:%Y-%m-%d} ({days[d.weekday()]}) {d:%H:%M:%S} · {label} (UTC{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d})"


def build() -> Server:
    srv = Server("clock", "1.0", "지금 날짜·시각을 알려 주고 시간대를 바꾼다. 보고서의 확인 날짜, 일정 계산에 쓴다. 읽기만 한다.")

    @srv.tool("now", "지금 날짜·시각 (요일 포함). zone을 비우면 이 PC 시간, 예: Asia/Seoul, America/New_York, UTC, +09:00",
              {"zone": {"type": "string", "description": "시간대 (비우면 이 PC 시간)"}})
    def now(zone: str = "") -> str:
        label = zone_of(zone)[0]
        return show(to_zone(datetime.now(timezone.utc), zone), label)

    @srv.tool("convert", "한 시간대의 날짜·시각을 다른 시간대로 바꾼다.",
              {"time": {"type": "string", "description": "YYYY-MM-DD HH:MM (from_zone 기준)"},
               "from_zone": {"type": "string", "description": "원래 시간대 (비우면 이 PC 시간)"},
               "to_zone": {"type": "string", "description": "바꿀 시간대"}},
              ["time", "to_zone"])
    def convert(time: str, to_zone: str, from_zone: str = "") -> str:
        try:
            local = datetime.strptime(str(time).strip(), "%Y-%m-%d %H:%M")
        except ValueError as e:
            raise ToolError("time은 'YYYY-MM-DD HH:MM' 형식으로 적어 주세요.") from e
        label, rule, std = zone_of(from_zone)
        if std is None:
            utc = local.astimezone().astimezone(timezone.utc)
        else:  # 그 지역 벽시계 시각 → UTC (서머타임은 표준시로 한 번 맞춘 뒤 다시 본다)
            guess = (local - timedelta(hours=std)).replace(tzinfo=timezone.utc)
            utc = guess - (H if _dst(rule, guess, std) else timedelta())
        out_label = zone_of(to_zone)[0]
        return f"{show(to_zone_fn(utc, from_zone), label)}\n→ {show(to_zone_fn(utc, to_zone), out_label)}"

    @srv.tool("zones", "이름으로 쓸 수 있는 시간대 목록 (그 밖에는 +09:00처럼 시차로).")
    def zones() -> str:
        return "\n".join(f"{k} (UTC{'+' if s >= 0 else ''}{s:g}{', 서머타임 있음' if r else ''})" for k, (s, r) in ZONES.items())

    return srv


to_zone_fn = to_zone


def main() -> None:
    setup_stdio()
    build().serve()


if __name__ == "__main__":
    main()
