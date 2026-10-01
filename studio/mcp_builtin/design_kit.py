"""내장 MCP '디자인 도구' (design-kit): 눈대중으로 틀리기 쉬운 것을 정확히 계산한다. 읽기만 한다.

색 대비(WCAG 2.1)·색 조합·글자 크기와 간격 단계·글자가 칸에 들어가는지(추정)·칸 나누기·PNG 색 개수.
네트워크·환경변수·하위 프로세스를 쓰지 않는다. 파일은 PNG 하나를 읽을 때뿐이고, 서버를 띄운 폴더와 --allow 폴더 안만 본다.
실행: python design_kit.py [--allow <폴더>]...
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
import time
import unicodedata
import zlib
from collections import Counter
from itertools import accumulate
from operator import add
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio.mcp_builtin.base import Server, ToolError, setup_stdio  # noqa: E402

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
COLOR_HELP = "#rgb, #rrggbb, #rrggbbaa, rgb(r,g,b), rgba(r,g,b,a) 중 하나로 적어 주세요."
SIMILAR_DE = 6.0  # Lab 색 차이(ΔE76)가 이보다 작으면 눈으로 거의 구분이 안 된다
MAX_FILE = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_COLORS = 100_000
TIME_BUDGET = 25.0  # PNG 한 장을 읽는 데 쓸 수 있는 시간(초)
PNG_SIG = b"\x89PNG\r\n\x1a\n"
COLOR_TYPE = {0: "회색조", 2: "색(RGB)", 3: "팔레트", 4: "회색조+투명도", 6: "색+투명도(RGBA)"}
DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
BYTE = (255).__and__  # 합을 0~255로 줄인다
WORD4 = "I" if struct.calcsize("I") == 4 else "L"  # 픽셀 하나(RGBA 네 바이트)를 정수 하나로 세는 형식


# ---------------------------------------------------------------- 숫자 다루기
def _half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _num(v: Any, name: str, lo: float, hi: float, integer: bool = False) -> Any:
    """입력을 숫자로 바꾸고 범위를 확인한다 (글자로 온 숫자도 받는다)."""
    if isinstance(v, bool):
        raise ToolError(f"{name}은(는) 숫자로 적어 주세요.")
    try:
        x = float(v)
    except (TypeError, ValueError) as e:
        raise ToolError(f"{name}은(는) 숫자로 적어 주세요.") from e
    if not math.isfinite(x):
        raise ToolError(f"{name}은(는) 숫자로 적어 주세요.")
    if integer:
        if x != int(x):
            raise ToolError(f"{name}은(는) 정수로 적어 주세요.")
        x = int(x)
    if x < lo or x > hi:
        raise ToolError(f"{name}은(는) {lo:g}에서 {hi:g} 사이로 적어 주세요.")
    return x


def _pct(count: int, total: int) -> str:
    if count == 0 or total <= 0:
        return "0%"
    p = count * 100 / total
    return "0.1% 미만" if p < 0.1 else f"{p:.1f}%"


# ---------------------------------------------------------------- 색
HEX_RE = re.compile(r"^(#?)([0-9a-fA-F]+)$")
FUNC_RE = re.compile(r"^rgba?\(\s*([^)]*?)\s*\)$", re.IGNORECASE)
SPLIT_RE = re.compile(r"[,\s/]+")


def parse_color(value: Any, what: str = "색") -> tuple[int, int, int, float]:
    """(r, g, b, 알파 0~1). #rgb #rgba #rrggbb #rrggbbaa rgb() rgba()."""
    s = str(value if value is not None else "").strip()
    shown = s if len(s) <= 40 else s[:40] + "…"
    bad = ToolError(f"{what}을 읽지 못했어요: '{shown}'. {COLOR_HELP}")
    if not s:
        raise ToolError(f"{what}이 비어 있어요. {COLOR_HELP}")
    m = HEX_RE.match(s)
    if m:
        hashed, digits = m.group(1) == "#", m.group(2)
        if len(digits) in (3, 4) and not hashed:  # 'bad', 'face' 같은 낱말과 헷갈리지 않게 #이 있어야 한다
            raise bad
        if len(digits) not in (3, 4, 6, 8):
            raise bad
        if len(digits) <= 4:
            digits = "".join(c * 2 for c in digits)
        vals = [int(digits[i:i + 2], 16) for i in range(0, len(digits), 2)]
        return vals[0], vals[1], vals[2], (vals[3] / 255 if len(vals) == 4 else 1.0)
    m = FUNC_RE.match(s)
    if m:
        parts = [p for p in SPLIT_RE.split(m.group(1)) if p]
        if len(parts) not in (3, 4):
            raise bad
        try:
            rgb = [float(p) for p in parts[:3]]
            if len(parts) == 4:
                alpha = float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])
            else:
                alpha = 1.0
        except ValueError as e:
            raise bad from e
        if not all(math.isfinite(v) and 0 <= v <= 255 for v in rgb) or not (math.isfinite(alpha) and 0 <= alpha <= 1):
            raise ToolError(f"{what}의 숫자가 범위를 벗어났어요: '{shown}'. r·g·b는 0~255, 투명도(a)는 0~1이에요.")
        return _half_up(rgb[0]), _half_up(rgb[1]), _half_up(rgb[2]), alpha
    raise bad


def hex_of(rgb: tuple, alpha: float | None = None) -> str:
    h = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
    return h + f"{_half_up(alpha * 255):02x}" if alpha is not None and alpha < 1 else h


def _lin(v: int) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


LIN = [_lin(i) for i in range(256)]


def luminance(rgb: tuple) -> float:
    """WCAG 2.1 상대 밝기 (0=검정, 1=흰색)."""
    return 0.2126 * LIN[rgb[0]] + 0.7152 * LIN[rgb[1]] + 0.0722 * LIN[rgb[2]]


def contrast_ratio(a: tuple, b: tuple) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def fmt_ratio(r: float) -> str:
    """소수 둘째 자리. 기준(3·4.5·7)에 모자라는데 반올림하면 닿아 보이는 값은 내림한다 (4.496 → 4.49)."""
    s = round(r, 2)
    if any(s >= t > r for t in (3.0, 4.5, 7.0)):
        s = math.floor(r * 100) / 100
    return f"{s:.2f}"


def flatten(fg: tuple, bg: tuple) -> tuple[int, int, int]:
    """투명도가 있는 fg를 bg(불투명) 위에 겹친 색."""
    a = fg[3] if len(fg) > 3 else 1.0
    return tuple(_half_up(fg[i] * a + bg[i] * (1 - a)) for i in range(3))  # type: ignore[return-value]


def rgb_to_hsl(rgb: tuple) -> tuple[float, float, float]:
    """(색상 0~360도, 채도 0~1, 밝기 0~1)."""
    r, g, b = (v / 255 for v in rgb[:3])
    mx, mn = max(r, g, b), min(r, g, b)
    light = (mx + mn) / 2
    d = mx - mn
    if d == 0:
        return 0.0, 0.0, light
    sat = d / (1 - abs(2 * light - 1))
    if mx == r:
        hue = ((g - b) / d) % 6
    elif mx == g:
        hue = (b - r) / d + 2
    else:
        hue = (r - g) / d + 4
    return (hue * 60) % 360, _clamp(sat), light


def hsl_to_rgb(h: float, s: float, light: float) -> tuple[int, int, int]:
    h, s, light = h % 360, _clamp(s), _clamp(light)
    c = (1 - abs(2 * light - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = light - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(int(_clamp(_half_up((v + m) * 255), 0, 255)) for v in (r, g, b))  # type: ignore[return-value]


def to_lab(rgb: tuple) -> tuple[float, float, float]:
    r, g, b = (LIN[v] for v in rgb[:3])
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(a: tuple, b: tuple) -> float:
    la, lb = to_lab(a), to_lab(b)
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(la, lb)))


def _best_on(rgb: tuple) -> tuple[tuple[int, int, int], float]:
    """이 색 위에 올릴 글자색(흰색·검정 중 대비가 큰 쪽)과 그 대비비. 어떤 색이든 4.58 이상이다."""
    w, k = contrast_ratio(WHITE, rgb), contrast_ratio(BLACK, rgb)
    return (WHITE, w) if w >= k else (BLACK, k)


def _opaque(c: tuple) -> tuple[int, int, int]:
    """투명한 색은 흰색 위에 있다고 보고 겹친다."""
    return flatten(c, WHITE) if c[3] < 1 else (c[0], c[1], c[2])


# ---------------------------------------------------------------- 색 조합
STEP = 0.005  # HSL 밝기를 옮기는 걸음 (0.5%)
SCHEMES = ("mono", "analogous", "complementary", "triad", "split")
SCHEME_KO = {"mono": "한 색 계열", "analogous": "이웃한 색", "complementary": "반대색", "triad": "세 색(120도)", "split": "반대색 이웃"}
HUE_EXTRAS = {"mono": [], "analogous": [-30, 30], "complementary": [180], "triad": [120, 240], "split": [150, 210]}


def _pick_on(c: tuple, mode: str) -> tuple[tuple[int, int, int], float]:
    """강조색 위 글자색. 관례(밝은 화면은 흰색, 어두운 화면은 검정)가 4.5:1 이상이면 그것, 아니면 대비가 큰 쪽."""
    pref = WHITE if mode == "light" else BLACK
    r = contrast_ratio(pref, c)
    return (pref, r) if r >= 4.5 else _best_on(c)


def _fit_accent(hue: float, sat: float, target: float, bgs: list[tuple], mode: str) -> tuple[tuple[int, int, int], float]:
    """target 밝기에서 가장 가까운 강조색을 찾는다 (색상·채도는 그대로, 밝기만 조정).
    1차: 관례대로 글자색(밝은 화면 흰색·어두운 화면 검정)이 4.5:1 이상이고 바탕 위에서 3:1 이상 보이는 색 (밝기 0.25 안).
    2차: 그게 안 되면 바탕 위 3:1 이상이면서 target에 가장 가까운 색 (글자색은 대비가 큰 쪽)."""
    prefer = -1 if mode == "light" else 1  # 밝은 화면은 어둡게, 어두운 화면은 밝게
    pref_on = WHITE if mode == "light" else BLACK
    for k in range(0, int(0.25 / STEP) + 1):
        c = hsl_to_rgb(hue, sat, _clamp(target + prefer * k * STEP))
        if contrast_ratio(c, pref_on) >= 4.5 and all(contrast_ratio(c, bg) >= 3.0 for bg in bgs):
            return c, _clamp(target + prefer * k * STEP)
    last = (hsl_to_rgb(hue, sat, target), target)
    for k in range(0, 205):
        for d in (prefer, -prefer):
            light = _clamp(target + d * k * STEP)
            c = hsl_to_rgb(hue, sat, light)
            last = (c, light)
            if all(contrast_ratio(c, bg) >= 3.0 for bg in bgs):
                return c, light
    return last


def _fit_text(hue: float, sat: float, start: float, direction: int, bgs: list[tuple], need: float) -> tuple[int, int, int]:
    """start 밝기에서 direction(+1 밝게, -1 어둡게)으로 옮겨 가며 모든 bgs 위에서 need:1 이상이 되는 첫 색."""
    c = hsl_to_rgb(hue, sat, start)
    for k in range(0, 205):
        c = hsl_to_rgb(hue, sat, _clamp(start + direction * k * STEP))
        if all(contrast_ratio(c, bg) >= need for bg in bgs):
            return c
    return c


def make_palette(base: tuple, scheme: str, mode: str = "light") -> dict[str, Any]:
    """결정적인 색 조합. 보장: ink 7:1 (surface·bg 위), ink_soft 4.5:1 (surface·bg 위), on_accent 4.5:1 (accent 위)."""
    if scheme not in SCHEMES:
        raise ToolError(f"scheme은 {', '.join(SCHEMES)} 중 하나예요.")
    if mode not in ("light", "dark"):
        raise ToolError("mode는 light(밝은 화면) 또는 dark(어두운 화면)예요.")
    hue, sat, base_l = rgb_to_hsl(base)
    ns = min(sat, 0.6)  # 중립색(바탕·글자)에 살짝 묻힐 색기
    if mode == "light":
        bg, surface = hsl_to_rgb(hue, ns * 0.5, 0.965), hsl_to_rgb(hue, ns * 0.35, 0.995)
        line = hsl_to_rgb(hue, ns * 0.3, 0.86)
        text_dir = -1
        ink = _fit_text(hue, ns * 0.5, 0.13, text_dir, [surface, bg], 7.0)
        soft = _fit_text(hue, ns * 0.35, 0.40, text_dir, [surface, bg], 4.5)
    else:
        bg, surface = hsl_to_rgb(hue, ns * 0.4, 0.09), hsl_to_rgb(hue, ns * 0.4, 0.135)
        line = hsl_to_rgb(hue, ns * 0.35, 0.22)
        text_dir = 1
        ink = _fit_text(hue, ns * 0.15, 0.93, text_dir, [surface, bg], 7.0)
        soft = _fit_text(hue, ns * 0.2, 0.70, text_dir, [surface, bg], 4.5)
    accent, accent_l = _fit_accent(hue, sat, base_l, [bg, surface], mode)
    on_accent, on_ratio = _pick_on(accent, mode)

    def extra_accent(name: str, h: float, target: float) -> dict[str, Any]:
        c, _ = _fit_accent(h, sat, target, [bg, surface], mode)
        on, r = _pick_on(c, mode)
        return {"name": name, "hex": hex_of(c), "on": hex_of(on), "on_contrast": r, "bg_contrast": contrast_ratio(c, bg)}

    extras: list[dict[str, Any]] = []
    if scheme == "mono":
        extras.append(extra_accent("진한 강조", hue, accent_l + (-0.12 if mode == "light" else 0.12)))
    for off in HUE_EXTRAS[scheme]:
        label = {"analogous": "이웃색", "complementary": "반대색", "triad": "세 번째 색", "split": "반대색 이웃"}[scheme]
        extras.append(extra_accent(f"{label} (색상 {off:+d}도)", (hue + off) % 360, accent_l))
    soft_fill = _fit_text(hue, min(sat, 0.75), 0.90 if mode == "light" else 0.20, 1 if mode == "light" else -1, [ink], 7.0)
    extras.append({"name": "연한 면 (강조색의 옅은 색, 그 위에는 ink)", "hex": hex_of(soft_fill), "on": hex_of(ink),
                   "on_contrast": contrast_ratio(ink, soft_fill), "bg_contrast": contrast_ratio(soft_fill, bg)})
    checks = {
        "ink_surface": contrast_ratio(ink, surface), "ink_bg": contrast_ratio(ink, bg),
        "ink_soft_surface": contrast_ratio(soft, surface), "ink_soft_bg": contrast_ratio(soft, bg),
        "on_accent": on_ratio, "accent_bg": contrast_ratio(accent, bg), "accent_surface": contrast_ratio(accent, surface),
    }
    return {"base": hex_of(base), "scheme": scheme, "mode": mode, "bg": hex_of(bg), "surface": hex_of(surface), "ink": hex_of(ink),
            "ink_soft": hex_of(soft), "accent": hex_of(accent), "on_accent": hex_of(on_accent), "line": hex_of(line),
            "extra": extras, "contrast": checks, "base_saturation": sat,
            "ok": checks["ink_surface"] >= 7 and checks["ink_bg"] >= 7 and checks["ink_soft_surface"] >= 4.5
                  and checks["ink_soft_bg"] >= 4.5 and on_ratio >= 4.5}


def palette_text(p: dict[str, Any]) -> str:
    c = p["contrast"]
    lines = [f"색 조합: 기준 {p['base']} · {SCHEME_KO[p['scheme']]}({p['scheme']}) · {'밝은' if p['mode'] == 'light' else '어두운'} 화면({p['mode']})",
             f"- 바탕 bg: {p['bg']}",
             f"- 카드 면 surface: {p['surface']}",
             f"- 본문 글자 ink: {p['ink']} (카드 면 위 {fmt_ratio(c['ink_surface'])}:1, 바탕 위 {fmt_ratio(c['ink_bg'])}:1)",
             f"- 보조 글자 ink_soft: {p['ink_soft']} (카드 면 위 {fmt_ratio(c['ink_soft_surface'])}:1, 바탕 위 {fmt_ratio(c['ink_soft_bg'])}:1)",
             f"- 강조 accent: {p['accent']} (바탕 위 {fmt_ratio(c['accent_bg'])}:1, 카드 면 위 {fmt_ratio(c['accent_surface'])}:1)",
             f"- 강조 위 글자 on_accent: {p['on_accent']} (강조색 위 {fmt_ratio(c['on_accent'])}:1)",
             f"- 경계선 line: {p['line']}",
             "- 보조색 extra:"]
    for e in p["extra"]:
        lines.append(f"  · {e['name']}: {e['hex']} (그 위 글자 {e['on']} {fmt_ratio(e['on_contrast'])}:1, 바탕 위 {fmt_ratio(e['bg_contrast'])}:1)")
    lines.append("보장: 본문 글자 7:1 이상 ✓ · 보조 글자 4.5:1 이상 ✓ · 강조 위 글자 4.5:1 이상 ✓ (위 숫자는 실제로 계산한 값). "
                 "강조색은 바탕·카드 면 위에서도 3:1 이상이에요.")
    if p["scheme"] != "mono" and p["base_saturation"] < 0.10:
        lines.append(f"참고: 기준색이 회색에 가까워(채도 {p['base_saturation'] * 100:.0f}%) 보조색도 회색빛이에요. 색을 뚜렷하게 쓰려면 채도가 있는 기준색을 주세요.")
    lines.append("글자 위·면 위 짝: ink·ink_soft는 bg·surface 위에, on_accent는 accent 위에만 써요.")
    keys = ("bg", "surface", "ink", "ink_soft", "accent", "on_accent", "line")
    lines.append("JSON: " + json.dumps({**{k: p[k] for k in keys}, "extra": [{"name": e["name"], "hex": e["hex"], "on": e["on"]} for e in p["extra"]]},
                                       ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


# ---------------------------------------------------------------- 크기·간격 단계
SIZE_NAMES = {-3: "2xsmall", -2: "xsmall", -1: "small", 0: "base", 1: "lg", 2: "xl"}
SPACE_MULTS = (0.5, 1, 1.5, 2, 3, 4, 6, 8, 12, 16)


def _size_name(i: int) -> str:
    return SIZE_NAMES.get(i) or f"{i - 1}xl"


def scale_text(kind: str, base: float, ratio: float | None, steps: int, down: int) -> str:
    if kind == "type":
        r = 1.25 if ratio is None else ratio
        rows = []
        for i in range(-down, steps + 1):
            exact = base * r ** i
            rows.append((_size_name(i), _half_up(exact), exact))
        lines = [f"글자 크기 단계 (기준 {base:g}px, 비율 {r:g}) — 작은 것부터. base보다 작은 단계 {down}개, 큰 단계 {steps}개"]
        lines += [f"- {n:<8} {px}px  (계산값 {ex:.2f})" for n, px, ex in rows]
        px_list = [px for _, px, _ in rows]
        if len(set(px_list)) < len(px_list):
            lines.append("주의: 반올림하면 같은 크기가 된 단계가 있어요. base나 ratio를 키워 보세요.")
        lines.append("px는 반올림한 정수예요. 이 크기들만 골라 쓰면 글자 크기가 들쭉날쭉하지 않아요.")
        return "\n".join(lines)
    if ratio is not None or down != 1:
        note = "참고: ratio·down은 type에서만 써요 (space는 무시했어요)."
    else:
        note = ""
    n = min(steps, len(SPACE_MULTS))
    lines = [f"간격 단계 (기준 {base:g}px의 배수를 정수로) — {n}단계"]
    for m in SPACE_MULTS[:n]:
        exact = base * m
        px = _half_up(exact)
        lines.append(f"- {m:g}배  {px}px" + ("" if exact == px else f"  ({exact:g}을 반올림)"))
    if steps > len(SPACE_MULTS):
        lines.append(f"참고: 간격 단계는 최대 {len(SPACE_MULTS)}개예요 (steps {steps}는 {len(SPACE_MULTS)}개로 줄였어요).")
    if note:
        lines.append(note)
    lines.append("여백·간격은 이 값들만 골라 쓰면 화면이 가지런해요.")
    return "\n".join(lines)


# ---------------------------------------------------------------- 글자가 칸에 들어가는지 (추정)
_EM: dict[str, float] = {}
WIDE = ((0x1100, 0x11FF), (0x2E80, 0x9FFF), (0xA960, 0xA97F), (0xAC00, 0xD7FF), (0xF900, 0xFAFF), (0xFE30, 0xFE4F),
        (0xFF00, 0xFF60), (0xFFE0, 0xFFE6), (0x20000, 0x3FFFF))
MAX_TEXT_CHARS = 5000


def char_em(ch: str) -> float:
    """글자 하나의 폭 (em 단위, 글꼴 크기 1 기준 어림값)."""
    v = _EM.get(ch)
    if v is None:
        v = _EM[ch] = _char_em(ch)
    return v


def _char_em(ch: str) -> float:
    o = ord(ch)
    if ch in " \t ":
        return 0.3
    if "0" <= ch <= "9":
        return 0.58
    if "A" <= ch <= "Z":
        return 0.68
    if "a" <= ch <= "z":
        return 0.55
    if ch.isascii():
        return 0.35 if ch.isprintable() else 0.0
    if any(lo <= o <= hi for lo, hi in WIDE):  # 한글·한자·가나·전각
        return 1.0
    if 0xFF61 <= o <= 0xFFDC:  # 반각 가나·한글
        return 0.5
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me", "Cf", "Cc"):  # 결합 글자·제어 글자는 폭이 없다
        return 0.0
    if o < 0x250 and cat == "Lu":
        return 0.68
    if o < 0x250 and cat == "Ll":
        return 0.55
    if cat.startswith("P"):
        return 0.35
    return 1.0  # 이모지·그 밖의 글자


def layout_lines(text: str, font: float, box: float, spacing: float, grow: float = 1.0) -> list[float]:
    """줄마다의 폭(px). 줄바꿈은 공백 기준, 낱말 하나가 칸보다 길면 중간에서 자른다. grow: 글자 폭에 곱해 본다."""
    eps = 1e-9

    def cw(ch: str) -> float:
        return char_em(ch) * font * grow + spacing

    space = cw(" ")
    lines: list[float] = []
    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = para.split()
        if not words:
            lines.append(0.0)
            continue
        cur: float | None = None
        for word in words:
            widths = [cw(c) for c in word]
            total = sum(widths)
            if cur is not None and cur + space + total <= box + eps:
                cur += space + total
                continue
            if cur is not None:
                lines.append(cur)
                cur = None
            if total <= box + eps:
                cur = total
                continue
            piece = 0.0  # 낱말이 칸보다 길다: 칸이 찰 때마다 자른다
            for w in widths:
                if piece > 0 and piece + w > box + eps:
                    lines.append(piece)
                    piece = 0.0
                piece += w
            cur = piece
        lines.append(cur if cur is not None else 0.0)
    return lines


def _fits(text: str, font: float, box: float, spacing: float, max_lines: int, grow: float) -> bool:
    return len(layout_lines(text, font, box, spacing, grow)) <= max_lines


def text_fit_text(text: str, font: float, box: float, max_lines: int | None, spacing: float) -> str:
    lines = layout_lines(text, font, box, spacing)
    longest = max(lines)
    one_line = max(layout_lines(p, font, 1e12, spacing)[0] for p in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    out = ["추정(실제 글꼴에 따라 ±10%): 글자 종류별 평균 폭으로 어림한 값이에요.",
           f"- 글자 크기 {font:g}px, 칸 폭 {box:g}px, 글자 사이 {spacing:g}px",
           f"- 예상 줄 수: {len(lines)}줄",
           f"- 가장 긴 줄 폭: {longest:.1f}px (칸 폭의 {longest * 100 / box:.0f}%)",
           f"- 가장 긴 문단을 한 줄로 쓰면 폭 약 {one_line:.1f}px"]
    wider = len(layout_lines(text, font, box, spacing, 1.1))
    fits = True
    if max_lines is not None:
        fits = len(lines) <= max_lines
        out.append(f"- {max_lines}줄 안에 들어가나: " + ("들어가요 ✓" if fits else f"안 들어가요 ✗ ({len(lines)}줄 필요)"))
        if fits and wider > max_lines:
            out.append(f"- 주의: 글꼴이 10% 넓게 나오면 {wider}줄이 되어 넘쳐요. 여유가 없어요.")
    else:
        out.append(f"- 글꼴이 10% 넓게 나오면 예상 줄 수: {wider}줄")
    if longest > box + 1e-9:
        out.append("- 주의: 글자 하나가 칸보다 넓어요. 칸을 넓히거나 글자를 줄여야 해요.")
    if max_lines is not None and not fits:
        out.append(_suggest(text, font, box, max_lines, spacing))
    return "\n".join(out)


def _suggest(text: str, font: float, box: float, max_lines: int, spacing: float) -> str:
    """안 들어갈 때 글자 크기 또는 칸 폭 제안 (글꼴이 10% 넓게 나와도 들어가도록 잡는다)."""
    grow = 1.1
    paras = len(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    if paras > max_lines:
        return f"→ 제안: 글에 줄바꿈이 {paras - 1}번 들어 있어서 어떤 크기·폭으로도 {max_lines}줄이 안 돼요. max_lines를 {paras}줄 이상으로 하거나 글을 줄이세요."
    # 칸 폭: box보다 넓은 쪽으로 가장 작은 정수 (줄 수는 칸이 넓을수록 줄지 않는 일이 없다)
    top = math.ceil(max(layout_lines(p, font, 1e12, spacing, grow)[0] for p in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))) + 1
    wide: int | None = None
    if _fits(text, font, top, spacing, max_lines, grow):
        lo, hi = int(math.floor(box)) + 1, top
        while lo < hi:
            mid = (lo + hi) // 2
            if _fits(text, font, mid, spacing, max_lines, grow):
                hi = mid
            else:
                lo = mid + 1
        wide = lo
    # 글자 크기: 지금보다 작은 가장 큰 정수 (8px 밑은 읽기 어려워 권하지 않는다)
    start = math.ceil(font) - 1
    small: int | None = None
    if start >= 8 and _fits(text, 8, box, spacing, max_lines, grow):
        lo, hi = 8, start
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _fits(text, mid, box, spacing, max_lines, grow):
                lo = mid
            else:
                hi = mid - 1
        small = lo
    tail = " (글꼴이 10% 넓게 나와도 들어가도록 잡았어요)"
    if small is not None and wide is not None:
        return f"→ 제안: 글자를 {small}px로 줄이거나 칸을 {wide}px로 넓히세요.{tail}"
    if small is not None:
        return f"→ 제안: 글자를 {small}px로 줄이세요.{tail}"
    if wide is not None:
        return f"→ 제안: 칸을 {wide}px로 넓히세요. (글자를 줄여서는 안 맞아요){tail}"
    return "→ 제안: 글이 너무 길어요. 글을 줄이거나 max_lines를 늘리세요."


# ---------------------------------------------------------------- 열 나누기
def grid_text(width: int, columns: int, gutter: int, margin: int) -> str:
    content = width - 2 * margin - gutter * (columns - 1)
    if content < columns:
        raise ToolError("칸이 너무 좁아요: 열 너비를 1px도 줄 수 없어요. 열 수·간격·여백을 줄이거나 폭을 늘려 보세요.")
    base, extra = divmod(content, columns)
    widths = [base + (1 if i < extra else 0) for i in range(columns)]
    xs, x = [], margin
    for w in widths:
        xs.append(x)
        x += w + gutter
    total = 2 * margin + sum(widths) + gutter * (columns - 1)
    lines = [f"폭 {width}px = 바깥 여백 {margin}px×2 + 열 {columns}개 + 간격 {gutter}px×{columns - 1}",
             f"열 너비: {base}px" + (f" ({extra}개는 1px 더 넓어 {base + 1}px, 앞 열부터)" if extra else " (모두 같아요)")]
    lines += [f"- {i + 1}열: x={xs[i]} ~ {xs[i] + widths[i]} (폭 {widths[i]}px)" for i in range(columns)]
    lines.append(f"검산: {2 * margin} + {sum(widths)} + {gutter * (columns - 1)} = {total} " + ("✓ 폭과 같아요" if total == width else f"✗ 폭 {width}과 달라요"))
    return "\n".join(lines)


# ---------------------------------------------------------------- PNG 읽기 (struct·zlib만)
def _chunks(data: bytes):
    pos, n = 8, len(data)
    while pos + 12 <= n:
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        end = pos + 8 + length
        if end + 4 > n:
            raise ToolError("PNG가 중간에 끊겼어요.")
        body = data[pos + 8:end]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack(">I", data[end:end + 4])[0]:
            raise ToolError("PNG가 깨져 있어요 (검사값이 달라요).")
        yield kind, body
        if kind == b"IEND":
            return
        pos = end + 4


def _unfilter(ft: int, cur: bytearray, prev: bytearray, bpp: int) -> bytearray:
    """PNG 줄 필터(0 없음·1 왼쪽·2 위·3 평균·4 파이스)를 되돌린다. 순수 파이썬이라 큰 그림에서는 느리다."""
    n = len(cur)
    if ft == 0:
        return cur
    if ft == 1:  # 색 채널마다 앞에서부터 더해 나간다
        for c in range(min(bpp, n)):
            cur[c::bpp] = bytes(map(BYTE, accumulate(cur[c::bpp])))
    elif ft == 2:
        cur = bytearray(map(BYTE, map(add, cur, prev)))
    elif ft == 3:
        for i in range(min(bpp, n)):
            cur[i] = (cur[i] + (prev[i] >> 1)) & 255
        for i in range(bpp, n):
            cur[i] = (cur[i] + ((cur[i - bpp] + prev[i]) >> 1)) & 255
    elif ft == 4:
        for i in range(min(bpp, n)):  # 왼쪽·왼쪽 위가 없으면 파이스 예측은 위 픽셀과 같다
            cur[i] = (cur[i] + prev[i]) & 255
        for i in range(bpp, n):
            a, b, c = cur[i - bpp], prev[i], prev[i - bpp]
            pa, pb = abs(b - c), abs(a - c)
            pc = abs(a + b - c - c)
            cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
    else:
        raise ToolError("PNG 줄 필터 종류가 이상해요.")
    return cur


_UNPACK: dict[int, list[bytes]] = {}


def _unpack_table(depth: int) -> list[bytes]:
    """1·2·4비트 표본을 한 바이트에 여러 개 담은 줄을 표본 하나당 한 바이트로 펴는 표."""
    t = _UNPACK.get(depth)
    if t is None:
        per, mask = 8 // depth, (1 << depth) - 1
        t = _UNPACK[depth] = [bytes((b >> (8 - depth * (i + 1))) & mask for i in range(per)) for b in range(256)]
    return t


def read_png(data: bytes) -> dict[str, Any]:
    """PNG 한 장을 읽어 크기·색 세는 값을 돌려준다 (인터레이스 없는 것만)."""
    if data[:8] != PNG_SIG:
        raise ToolError("PNG 파일이 아니에요 (파일 머리말이 PNG와 달라요).")
    header: tuple[int, ...] | None = None
    plte, trns, idat = b"", None, []
    for kind, body in _chunks(data):
        if header is None:
            if kind != b"IHDR" or len(body) != 13:
                raise ToolError("PNG가 깨져 있어요 (첫 조각이 IHDR가 아니에요).")
            header = struct.unpack(">IIBBBBB", body)
            w, h, depth, ct, comp, filt, inter = header
            if ct not in DEPTHS or depth not in DEPTHS[ct] or comp != 0 or filt != 0 or inter not in (0, 1) or w < 1 or h < 1:
                raise ToolError("PNG 머리 정보가 이상하거나 지원하지 않는 종류예요.")
            if inter == 1:
                raise ToolError("지원하지 않는 PNG(인터레이스)예요. 인터레이스 없이 다시 저장해 주세요.")
            if w * h > MAX_PIXELS:
                raise ToolError(f"그림이 너무 커요 ({w}×{h}, {MAX_PIXELS // 10_000}만 픽셀을 넘으면 읽지 않아요).")
        elif kind == b"PLTE":
            plte = body
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat.append(body)
    if header is None or not idat:
        raise ToolError("PNG에 그림 자료가 없어요.")
    return _decode(header[0], header[1], header[2], header[3], plte, trns, b"".join(idat))


def _decode(w: int, h: int, depth: int, ct: int, plte: bytes, trns: bytes | None, packed: bytes) -> dict[str, Any]:
    started = time.monotonic()
    ch = CHANNELS[ct]
    bits = ch * depth
    stride = (w * bits + 7) // 8
    bpp = max(1, bits // 8)
    expected = h * (stride + 1)
    try:
        raw = zlib.decompressobj().decompress(packed, expected + 1)
    except zlib.error as e:
        raise ToolError("PNG 그림 자료의 압축이 깨져 있어요.") from e
    if len(raw) > expected:
        raise ToolError("PNG 그림 자료가 머리 정보의 크기보다 길어요.")
    if len(raw) < expected:
        raise ToolError("PNG 그림 자료가 모자라요.")
    # 색 표 (팔레트) · 투명색 (tRNS)
    tables: tuple[bytes, bytes, bytes, bytes] | None = None
    palette_n = None
    if ct == 3:
        if not plte or len(plte) % 3 or len(plte) > 768:
            raise ToolError("PNG 팔레트(PLTE)가 이상해요.")
        palette_n = len(plte) // 3
        alphas = list(trns[:palette_n]) if trns else []
        alphas += [255] * (palette_n - len(alphas))
        tables = (bytes(plte[3 * i] if i < palette_n else 0 for i in range(256)),
                  bytes(plte[3 * i + 1] if i < palette_n else 0 for i in range(256)),
                  bytes(plte[3 * i + 2] if i < palette_n else 0 for i in range(256)),
                  bytes(alphas[i] if i < palette_n else 0 for i in range(256)))
    key: tuple[int, ...] | None = None
    if trns and ct == 0 and len(trns) >= 2:
        key = (int.from_bytes(trns[:2], "big"),)
    elif trns and ct == 2 and len(trns) >= 6:
        key = tuple(int.from_bytes(trns[2 * i:2 * i + 2], "big") for i in range(3))
    scale8 = bytes(min(255, v * (255 // ((1 << depth) - 1))) for v in range(256)) if depth < 8 else bytes(range(256))
    gray_alpha = bytes(0 if key and v == key[0] else 255 for v in range(256)) if ct == 0 and depth <= 8 else b""
    unpack = _unpack_table(depth) if depth < 8 else None

    def key_alpha(row: bytes, samples: bytes) -> bytearray:
        """tRNS가 정한 색과 (16비트면 두 바이트 모두) 같은 픽셀만 투명하게."""
        k = 1 if ct == 0 else 3
        alpha = bytearray(b"\xff" * w)
        for i in range(w):
            if depth == 16:
                vals = tuple((row[2 * (i * k + c)] << 8) | row[2 * (i * k + c) + 1] for c in range(k))
            elif depth == 8:
                vals = tuple(row[i * k + c] for c in range(k))
            else:
                vals = (samples[i],)
            if vals == key:
                alpha[i] = 0
        return alpha

    def to_rgba(row: bytes) -> bytes:
        samples = b"".join([unpack[b] for b in row])[:w] if unpack else b""  # type: ignore[index]
        if ct == 6:
            return bytes(row if depth == 8 else row[0::2])
        out = bytearray(4 * w)
        if ct == 4:
            g, a = (row[0::2], row[1::2]) if depth == 8 else (row[0::4], row[2::4])
            out[0::4] = out[1::4] = out[2::4] = g
            out[3::4] = a
        elif ct == 2:
            r, g, b = (row[0::3], row[1::3], row[2::3]) if depth == 8 else (row[0::6], row[2::6], row[4::6])
            out[0::4], out[1::4], out[2::4] = r, g, b
            out[3::4] = key_alpha(row, samples) if key else b"\xff" * w
        elif ct == 0:
            g = samples.translate(scale8) if unpack else (row if depth == 8 else row[0::2])
            out[0::4] = out[1::4] = out[2::4] = g
            if not key:
                out[3::4] = b"\xff" * w
            elif depth <= 8:
                out[3::4] = (samples if unpack else row).translate(gray_alpha)
            else:
                out[3::4] = key_alpha(row, samples)
        else:  # 팔레트
            idx = samples if unpack else row
            if idx and max(idx) >= palette_n:  # type: ignore[operator]
                raise ToolError("PNG가 팔레트에 없는 색 번호를 써요.")
            out[0::4], out[1::4], out[2::4], out[3::4] = (idx.translate(t) for t in tables)  # type: ignore[union-attr]
        return bytes(out)

    counter: Counter = Counter()
    too_many = False
    clear = semi = 0
    prev = bytearray(stride)
    for y in range(h):
        base = y * (stride + 1)
        cur = _unfilter(raw[base], bytearray(raw[base + 1:base + 1 + stride]), prev, bpp)
        prev = cur
        pix = to_rgba(bytes(cur))
        a = pix[3::4]
        zero, full = a.count(0), a.count(255)
        clear += zero
        semi += w - zero - full
        if not too_many:
            counter.update(memoryview(pix).cast(WORD4))
            if len(counter) > MAX_COLORS:
                too_many = True
                counter.clear()
        if y % 32 == 31 and time.monotonic() - started > TIME_BUDGET:
            raise ToolError("그림이 커서 시간 안에 다 읽지 못했어요. 더 작은 그림으로 시험해 주세요.")
    colors: Counter | None = None
    if not too_many:
        colors = Counter()
        for k, n in counter.items():
            px = k.to_bytes(4, sys.byteorder)
            colors[bytes(4) if px[3] == 0 else px] += n  # 완전히 투명한 픽셀은 색이 달라도 하나로 센다
    return {"w": w, "h": h, "depth": depth, "ct": ct, "palette_n": palette_n, "colors": colors, "clear": clear, "semi": semi}


def png_text(name: str, info: dict[str, Any]) -> str:
    w, h, total = info["w"], info["h"], info["w"] * info["h"]
    colors = info["colors"]
    kind = COLOR_TYPE[info["ct"]] + f", {info['depth']}비트" + (f", 팔레트 {info['palette_n']}색" if info["palette_n"] else "")
    lines = [f"파일: {name}", f"크기: {w} × {h} 픽셀", f"색 종류: {kind}",
             f"투명 픽셀(완전히 투명): {_pct(info['clear'], total)}"]
    if colors is None:
        lines.append(f"서로 다른 색: {MAX_COLORS // 10_000}만 개 넘음 (도트 그림이 아니라 사진·그라데이션 같아요)")
        lines.append("많이 쓰인 색: 색이 너무 많아 적지 않았어요.")
    else:
        lines.append(f"서로 다른 색: {len(colors)}개 (완전히 투명한 픽셀은 색 하나로 셈)")
        lines.append("많이 쓰인 색 (상위 8개):")
        for i, (px, n) in enumerate(sorted(colors.items(), key=lambda kv: (-kv[1], kv[0]))[:8], 1):
            label = "투명" if px[3] == 0 else hex_of(px[:3], px[3] / 255)
            lines.append(f"  {i}. {label} {_pct(n, total)}")
    lines.append("도트 그림 점검:")
    if colors is None:
        lines.append(f"- 색 개수: {MAX_COLORS // 10_000}만 개 넘음 → 32개를 넘어요 ✗ (도트 그림은 보통 32색 안쪽이에요)")
    elif len(colors) <= 32:
        lines.append(f"- 색 개수: {len(colors)}개 → 32개 이하예요 ✓")
    else:
        lines.append(f"- 색 개수: {len(colors)}개 → 32개를 넘어요 ✗ (도트 그림은 보통 32색 안쪽이에요)")
    if w % 8 == 0 and h % 8 == 0:
        lines.append(f"- 크기: 가로 {w}·세로 {h} 모두 8의 배수예요 ✓")
    else:
        bad = " · ".join(f"{n} {v}" for n, v in (("가로", w), ("세로", h)) if v % 8)
        lines.append(f"- 크기: {bad}은(는) 8의 배수가 아니에요 △ (타일·스프라이트 시트에 맞추기 어려울 수 있어요)")
    semi = info["semi"]
    if semi == 0:
        lines.append("- 반투명 픽셀(알파 1~254): 0% ✓ (도트 그림은 보통 0에 가까워요)")
    elif semi * 100 < total:
        lines.append(f"- 반투명 픽셀(알파 1~254): {_pct(semi, total)} △ (조금 있어요. 가장자리가 번졌는지 보세요)")
    else:
        lines.append(f"- 반투명 픽셀(알파 1~254): {_pct(semi, total)} ✗ (많아요. 도트 그림이면 가장자리가 번졌을 수 있어요)")
    return "\n".join(lines)


# ---------------------------------------------------------------- 서버
def build(allow: list[Path] | None = None, cwd: Path | None = None) -> Server:
    roots = [Path(p).resolve() for p in ([cwd if cwd is not None else Path.cwd()] + list(allow or []))]
    srv = Server("design-kit", "1.0", "디자인에서 눈대중으로 틀리기 쉬운 것(색 대비·색 조합·글자 크기·간격·글자 폭·PNG 색 개수)을 정확히 계산한다. "
                 "짐작하지 말고 이 도구로 확인한다. 읽기만 한다.")

    @srv.tool("color", "색 하나(#rgb, #rrggbb, #rrggbbaa, rgb(r,g,b), rgba(r,g,b,a) — Godot Color의 hex도 됨)를 넣으면 hex·rgb·hsl과 상대 밝기, 그 위에 올릴 글자색을 알려 준다.",
              {"value": {"type": "string", "description": "색 (예: #f5e6b5, rgb(245,230,181))"}}, ["value"])
    def color(value: str) -> str:
        r, g, b, a = parse_color(value)
        h, s, light = rgb_to_hsl((r, g, b))
        on, ratio = _best_on((r, g, b))
        lines = [hex_of((r, g, b), a), f"- rgb({r}, {g}, {b})" + (f", 투명도(알파) {a:.2f}" if a < 1 else ""),
                 f"- hsl({_half_up(h) % 360}도, {_half_up(s * 100)}%, {_half_up(light * 100)}%)",
                 f"- 상대 밝기 {luminance((r, g, b)):.3f} (0=검정, 1=흰색)",
                 f"- 이 색 위에 올릴 글자색: {'흰색 #ffffff' if on == WHITE else '검정 #000000'} (대비 {fmt_ratio(ratio)}:1)"]
        if a < 1:
            lines.append("- 투명한 색이라 바탕에 따라 달라 보여요. 바탕 위에서의 대비는 contrast 도구로 계산해요.")
        return "\n".join(lines)

    @srv.tool("contrast", "글자색(fg)과 바탕색(bg)을 넣으면 WCAG 2.1 대비비(예: 4.48:1)와 일반 글자·큰 글자의 AA·AAA 통과 여부를 알려 준다. fg에 투명도가 있으면 bg 위에 겹쳐 계산한다.",
              {"fg": {"type": "string", "description": "글자색 (예: #777777)"}, "bg": {"type": "string", "description": "바탕색 (예: #ffffff)"}},
              ["fg", "bg"])
    def contrast(fg: str, bg: str) -> str:
        f, b = parse_color(fg, "fg(글자색)"), parse_color(bg, "bg(바탕색)")
        notes = []
        bg_rgb = (b[0], b[1], b[2])
        if b[3] < 1:
            bg_rgb = flatten(b, WHITE)
            notes.append(f"바탕색이 투명해서 흰색 위에 있다고 보고 겹친 색({hex_of(bg_rgb)})으로 계산했어요.")
        fg_rgb = (f[0], f[1], f[2])
        if f[3] < 1:
            fg_rgb = flatten(f, bg_rgb)
            notes.append(f"글자색이 투명해서 바탕 위에 겹친 색({hex_of(fg_rgb)})으로 계산했어요.")
        r = contrast_ratio(fg_rgb, bg_rgb)

        def mark(t: float) -> str:
            return "통과 ✓" if r >= t else "탈락 ✗"

        verdict = ("본문 글자로 충분해요 (AAA)." if r >= 7 else "본문 글자로 쓸 수 있어요 (AA)." if r >= 4.5
                   else "큰 글자·굵은 제목에만 쓸 수 있어요." if r >= 3 else "글자로 쓰기 어려워요 (흐릿해요).")
        return "\n".join([f"대비비 {fmt_ratio(r)} : 1 (글자 {hex_of(fg_rgb)}, 바탕 {hex_of(bg_rgb)})",
                          f"- 일반 글자 AA (4.5 이상): {mark(4.5)}", f"- 일반 글자 AAA (7 이상): {mark(7)}",
                          f"- 큰 글자 AA (3 이상): {mark(3)}", f"- 큰 글자 AAA (4.5 이상): {mark(4.5)}",
                          "큰 글자는 24px 이상, 또는 굵은 글자 19px 이상이에요. AA는 꼭 지킬 기준, AAA는 더 엄격한 기준이에요.",
                          f"결론: {verdict}", *notes])

    @srv.tool("contrast_table", "색 2~12개를 넣으면 모든 색 쌍의 대비 표(✓ 4.5 이상, △ 3 이상, ✗ 3 미만)와 눈으로 구분하기 어려운 비슷한 색 쌍을 알려 준다.",
              {"colors": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 12, "description": "색 목록 (2~12개)"}},
              ["colors"])
    def contrast_table(colors: list) -> str:
        if not isinstance(colors, list) or not 2 <= len(colors) <= 12:
            raise ToolError("colors는 색 2~12개의 목록이에요.")
        parsed = [parse_color(c, f"{i + 1}번째 색") for i, c in enumerate(colors)]
        rgb = [_opaque(c) for c in parsed]
        n = len(rgb)
        lines = ["색 목록: " + " · ".join(f"{i + 1} {hex_of(rgb[i])}" for i in range(n)),
                 "대비 표 (✓ 4.5 이상 · △ 3 이상 4.5 미만 · ✗ 3 미만, 위쪽 삼각형만)",
                 "     " + "".join(f"{j + 1:>9}" for j in range(1, n))]
        for i in range(n - 1):
            cells = []
            for j in range(1, n):
                if j <= i:
                    cells.append(" " * 9)
                    continue
                r = contrast_ratio(rgb[i], rgb[j])
                cells.append(f"{fmt_ratio(r):>7} {'✓' if r >= 4.5 else '△' if r >= 3 else '✗'}")
            lines.append(f"{i + 1:>4} " + "".join(cells))
        similar = [(i, j, delta_e76(rgb[i], rgb[j])) for i in range(n) for j in range(i + 1, n) if delta_e76(rgb[i], rgb[j]) < SIMILAR_DE]
        if similar:
            lines.append(f"눈으로 구분하기 어려운 비슷한 색 (색 차이 ΔE {SIMILAR_DE:g} 미만):")
            lines += [f"- {i + 1}번 {hex_of(rgb[i])} 와 {j + 1}번 {hex_of(rgb[j])} (ΔE {d:.1f}" + (", 완전히 같아요)" if d == 0 else ")") for i, j, d in similar]
        else:
            lines.append(f"눈으로 구분이 안 될 만큼 비슷한 색은 없어요 (색 차이 ΔE {SIMILAR_DE:g} 이상).")
        if any(c[3] < 1 for c in parsed):
            lines.append("참고: 투명한 색은 흰색 위에 있다고 보고 계산했어요.")
        return "\n".join(lines)

    @srv.tool("palette", "기준색(base)·조합(scheme: mono, analogous, complementary, triad, split)·화면(mode: light, dark)을 넣으면 역할별 hex(바탕·카드 면·본문 글자·보조 글자·강조·강조 위 글자·경계선·보조색)를 준다. "
                         "본문 글자 7:1, 보조 글자·강조 위 글자 4.5:1 이상을 보장하고 실제 대비값도 적는다. 같은 입력이면 같은 결과.",
              {"base": {"type": "string", "description": "기준색 (예: #3b82f6)"},
               "scheme": {"type": "string", "enum": list(SCHEMES), "description": "mono 한 색 계열 · analogous 이웃색 · complementary 반대색 · triad 세 색 · split 반대색 이웃"},
               "mode": {"type": "string", "enum": ["light", "dark"], "description": "밝은 화면(light, 기본) 또는 어두운 화면(dark)"}},
              ["base", "scheme"])
    def palette(base: str, scheme: str, mode: str = "light") -> str:
        c = parse_color(base, "base(기준색)")
        return palette_text(make_palette((c[0], c[1], c[2]), str(scheme).strip().lower(), str(mode or "light").strip().lower()))

    @srv.tool("scale", "kind=type: 기준 글자 크기(px)와 비율(ratio)로 글자 크기 단계표(small, base, lg, xl…)를, kind=space: 기준 간격(px)의 배수(0.5~16배)로 정수 간격 단계표를 만든다.",
              {"kind": {"type": "string", "enum": ["type", "space"], "description": "type 글자 크기 · space 간격"},
               "base": {"type": "number", "description": "기준 크기 (px, 예: 16)"},
               "ratio": {"type": "number", "description": "type만: 단계마다 곱할 비율 (기본 1.25, 1.067~2)"},
               "steps": {"type": "integer", "description": "base보다 큰 단계 수 (기본 6, 최대 12)"},
               "down": {"type": "integer", "description": "type만: base보다 작은 단계 수 (기본 1, 최대 3)"}},
              ["kind", "base"])
    def scale(kind: str, base: float, ratio: float | None = None, steps: int | None = 6, down: int | None = 1) -> str:
        kind = str(kind).strip().lower()
        if kind not in ("type", "space"):
            raise ToolError("kind는 type(글자 크기) 또는 space(간격)예요.")
        b = _num(base, "base", 1, 1000)
        r = None if ratio is None else _num(ratio, "ratio", 1.067, 2)
        st = _num(6 if steps is None else steps, "steps", 1, 12, integer=True)
        dn = _num(1 if down is None else down, "down", 0, 3, integer=True)
        return scale_text(kind, b, r, st, dn)

    @srv.tool("text_fit", "글(text)·글자 크기(font_px)·칸 폭(box_width)을 넣으면 줄 수와 가장 긴 줄 폭을 어림하고 max_lines 안에 드는지 알려 준다. 안 들어가면 줄일 글자 크기·넓힐 칸 폭을 제안한다. 추정값(실제 글꼴에 따라 ±10%)이다.",
              {"text": {"type": "string", "description": "칸에 넣을 글"},
               "font_px": {"type": "number", "description": "글자 크기 (px)"},
               "box_width": {"type": "number", "description": "칸 폭 (px)"},
               "max_lines": {"type": "integer", "description": "허용하는 최대 줄 수 (비우면 제한 없음)"},
               "letter_spacing": {"type": "number", "description": "글자 사이 간격 (px, 기본 0)"}},
              ["text", "font_px", "box_width"])
    def text_fit(text: str, font_px: float, box_width: float, max_lines: int | None = None, letter_spacing: float | None = 0) -> str:
        t = str(text if text is not None else "")
        if not t.strip():
            raise ToolError("text가 비어 있어요.")
        if len(t) > MAX_TEXT_CHARS:
            raise ToolError(f"text가 너무 길어요 ({MAX_TEXT_CHARS}자까지).")
        font = _num(font_px, "font_px", 1, 512)
        box = _num(box_width, "box_width", 1, 100000)
        ml = None if max_lines is None else _num(max_lines, "max_lines", 1, 1000, integer=True)
        sp = _num(0 if letter_spacing is None else letter_spacing, "letter_spacing", -font / 2, font * 2)
        return text_fit_text(t, font, box, ml, sp)

    @srv.tool("grid", "화면 폭(width)·열 수(columns)·열 사이 간격(gutter)·바깥 여백(margin)을 px로 넣으면 열 너비, 각 열의 시작 x, 합계 검산을 준다. 남는 픽셀은 앞 열부터 1px씩 나눈다.",
              {"width": {"type": "integer", "description": "전체 폭 (px)"}, "columns": {"type": "integer", "description": "열 수 (1~48)"},
               "gutter": {"type": "integer", "description": "열 사이 간격 (px, 기본 0)"}, "margin": {"type": "integer", "description": "양쪽 바깥 여백 (px, 기본 0)"}},
              ["width", "columns"])
    def grid(width: int, columns: int, gutter: int | None = 0, margin: int | None = 0) -> str:
        return grid_text(_num(width, "width", 1, 20000, integer=True), _num(columns, "columns", 1, 48, integer=True),
                         _num(0 if gutter is None else gutter, "gutter", 0, 2000, integer=True),
                         _num(0 if margin is None else margin, "margin", 0, 10000, integer=True))

    @srv.tool("image_info", "PNG 그림 하나의 경로(path)를 넣으면 가로×세로, 색 종류, 투명 픽셀 비율, 서로 다른 색 개수, 많이 쓰인 색 상위 8개, 도트 그림 점검(32색 이하·8의 배수·반투명)을 알려 준다. PNG만, 허용된 폴더 안만 읽는다.",
              {"path": {"type": "string", "description": "PNG 파일 경로 (절대 경로, 또는 작업 폴더 기준 상대 경로)"}}, ["path"])
    def image_info(path: str) -> str:
        raw = str(path if path is not None else "").strip()
        if not raw or len(raw) > 1000:
            raise ToolError("path에 PNG 파일 경로를 적어 주세요.")
        try:
            p = Path(raw)
            p = (roots[0] / p if not p.is_absolute() else p).resolve()
        except (OSError, ValueError, RuntimeError) as e:
            raise ToolError("경로를 읽을 수 없어요.") from e
        if not any(p == r or p.is_relative_to(r) for r in roots):
            raise ToolError("이 경로는 볼 수 없어요. 작업 폴더와 허용된 폴더 안의 PNG만 읽어요.")
        if p.suffix.lower() != ".png":
            raise ToolError("PNG 파일(.png)만 읽어요.")
        try:
            if not p.is_file():
                raise ToolError("그 파일이 없어요.")
            if p.stat().st_size > MAX_FILE:
                raise ToolError(f"파일이 {MAX_FILE // (1024 * 1024)}MB를 넘어서 읽지 않아요.")
            with p.open("rb") as f:
                data = f.read(MAX_FILE + 1)
        except OSError as e:
            raise ToolError("파일을 열지 못했어요.") from e
        if len(data) > MAX_FILE:
            raise ToolError(f"파일이 {MAX_FILE // (1024 * 1024)}MB를 넘어서 읽지 않아요.")
        return png_text(p.name, read_png(data))

    return srv


def main() -> None:
    setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow", action="append", default=[], help="PNG를 읽어도 되는 폴더 (여러 번 쓸 수 있다)")
    a = ap.parse_args()
    build([Path(p) for p in a.allow]).serve()


if __name__ == "__main__":
    main()
