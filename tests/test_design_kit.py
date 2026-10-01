"""내장 MCP '디자인 도구'(design-kit): 색·대비·색 조합·크기 단계·글자 폭 추정·열 나누기·PNG 읽기와 서버."""

import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from collections import Counter
from pathlib import Path
from unittest import mock

from studio.mcp_builtin import design_kit as dk

TOOLS = ["color", "contrast", "contrast_table", "palette", "scale", "text_fit", "grid", "image_info"]


def call(srv, tool, **args):
    """내장 서버에 JSON-RPC tools/call을 보내고 (글, 오류인지)를 돌려준다."""
    res = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    r = res["result"]
    return r["content"][0]["text"], r["isError"]


# ---------------------------------------------------------------- 시험용 PNG 만들기 (zlib·struct로 직접)
CH = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def scanlines(rows: list, bpp: int, filters: tuple) -> bytes:
    """줄마다 필터(0 없음·1 왼쪽·2 위·3 평균·4 파이스)를 돌려 가며 걸어 PNG 줄 자료로."""
    out, prev = [], bytes(len(rows[0]))
    for i, row in enumerate(rows):
        ft = filters[i % len(filters)]
        line = bytearray()
        for j, x in enumerate(row):
            a = row[j - bpp] if j >= bpp else 0
            b = prev[j]
            c = prev[j - bpp] if j >= bpp else 0
            line.append((x - (0, a, b, (a + b) // 2, paeth(a, b, c))[ft]) & 255)
        out.append(bytes([ft]) + bytes(line))
        prev = row
    return b"".join(out)


def make_png(w, h, ct, depth, rows, plte=None, trns=None, interlace=0, filters=(0,), split=False) -> bytes:
    bpp = max(1, CH.get(ct, 1) * depth // 8)
    packed = zlib.compress(scanlines(rows, bpp, filters))
    parts = [dk.PNG_SIG, chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ct, 0, 0, interlace))]
    if plte is not None:
        parts.append(chunk(b"PLTE", plte))
    if trns is not None:
        parts.append(chunk(b"tRNS", trns))
    if split:
        parts += [chunk(b"IDAT", packed[:5]), chunk(b"IDAT", packed[5:])]
    else:
        parts.append(chunk(b"IDAT", packed))
    parts.append(chunk(b"IEND", b""))
    return b"".join(parts)


def pack_bits(values: list, depth: int) -> bytes:
    """표본 값 목록을 depth비트씩 한 바이트에 채워 넣는다 (맨 앞 표본이 높은 자리)."""
    out, cur, used = bytearray(), 0, 0
    for v in values:
        cur = (cur << depth) | v
        used += depth
        if used == 8:
            out.append(cur)
            cur, used = 0, 0
    if used:
        out.append(cur << (8 - used))
    return bytes(out)


def hist(pixels: list) -> Counter:
    """(r,g,b,a) 목록의 색 개수. 완전히 투명한 것은 하나로 센다."""
    return Counter(bytes(4) if p[3] == 0 else bytes(p) for p in pixels)


class ColorAndContrast(unittest.TestCase):
    def setUp(self):
        self.srv = dk.build()

    def test_color_reads_every_form(self):
        p = dk.parse_color
        self.assertEqual(p("#f5e6b5"), (245, 230, 181, 1.0))
        self.assertEqual(p("  #F5E6B5 "), (245, 230, 181, 1.0))
        self.assertEqual(p("#fb0"), (255, 187, 0, 1.0))
        self.assertEqual(p("f5e6b5"), (245, 230, 181, 1.0), "Godot Color()의 hex는 #이 없어도 된다")
        r, g, b, a = p("#f5e6b580")
        self.assertEqual((r, g, b), (245, 230, 181))
        self.assertAlmostEqual(a, 128 / 255)
        self.assertEqual(p("#fb08")[:3], (255, 187, 0))
        self.assertEqual(p("rgb(245, 230, 181)"), (245, 230, 181, 1.0))
        self.assertEqual(p("RGBA(10,20,30,0.5)"), (10, 20, 30, 0.5))
        self.assertEqual(p("rgb(10 20 30)"), (10, 20, 30, 1.0))
        self.assertEqual(p("rgba(10, 20, 30, 50%)")[3], 0.5)
        text, err = call(self.srv, "color", value="#f5e6b5")
        self.assertFalse(err, text)
        for part in ("#f5e6b5", "rgb(245, 230, 181)", "hsl(46도, 76%, 84%)", "상대 밝기 0.793", "검정 #000000"):
            self.assertIn(part, text)
        text = call(self.srv, "color", value="rgba(17,34,51,0.5)")[0]
        self.assertIn("#11223380", text)
        self.assertIn("투명도(알파) 0.50", text)
        self.assertIn("hsl(210도, 50%, 13%)", text)
        self.assertIn("흰색 #ffffff", call(self.srv, "color", value="#000000")[0])

    def test_color_rejects_bad_input_in_easy_korean(self):
        for bad in ("red", "빨강", "", "  ", "#12", "#12345", "#gggggg", "bad", "rgb(300,0,0)", "rgb(1,2)", "rgb(1,2,3,4,5)",
                    "rgba(1,2,3,2)", "rgb(-1,0,0)", "rgb(a,b,c)", "hsl(10,20%,30%)", "#1234567", "rgb(1,2,3"):
            text, err = call(self.srv, "color", value=bad)
            self.assertTrue(err, bad)
            self.assertRegex(text, "[가-힣]", bad)
        self.assertIn("#rrggbb", call(self.srv, "color", value="red")[0])
        self.assertTrue(call(self.srv, "color")[1], "빠진 입력")

    def test_hsl_round_trip(self):
        for rgb in ((0, 0, 0), (255, 255, 255), (245, 230, 181), (59, 130, 246), (225, 29, 72), (128, 128, 128)):
            h, s, light = dk.rgb_to_hsl(rgb)
            self.assertEqual(dk.hsl_to_rgb(h, s, light), rgb)

    def test_contrast_known_values(self):
        self.assertAlmostEqual(dk.contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0)
        self.assertAlmostEqual(dk.contrast_ratio((255, 255, 255), (0, 0, 0)), 21.0)
        self.assertAlmostEqual(dk.contrast_ratio((0, 0, 255), (255, 255, 255)), 8.59, places=2)
        self.assertEqual(dk.contrast_ratio((10, 20, 30), (10, 20, 30)), 1.0)
        text, err = call(self.srv, "contrast", fg="#000000", bg="#ffffff")
        self.assertFalse(err, text)
        self.assertIn("21.00 : 1", text)
        self.assertEqual(text.count("통과 ✓"), 4)
        # #777777은 흰 바탕에서 4.48 → 일반 글자 AA 탈락, 큰 글자 AA 통과
        text = call(self.srv, "contrast", fg="#777777", bg="#ffffff")[0]
        self.assertIn("4.48 : 1", text)
        self.assertIn("일반 글자 AA (4.5 이상): 탈락 ✗", text)
        self.assertIn("일반 글자 AAA (7 이상): 탈락 ✗", text)
        self.assertIn("큰 글자 AA (3 이상): 통과 ✓", text)
        self.assertIn("큰 글자 AAA (4.5 이상): 탈락 ✗", text)
        self.assertIn("24px 이상", text)
        self.assertIn("19px 이상", text)
        # #767676은 흰 바탕에서 AA를 처음 넘는 회색 (4.54)
        text = call(self.srv, "contrast", fg="#767676", bg="#fff")[0]
        self.assertIn("4.54 : 1", text)
        self.assertIn("일반 글자 AA (4.5 이상): 통과 ✓", text)
        self.assertIn("일반 글자 AAA (7 이상): 탈락 ✗", text)
        self.assertTrue(call(self.srv, "contrast", fg="#ffffff", bg="#777777")[0].startswith("대비비 4.48 : 1 (글자 #ffffff, 바탕 #777777)"), "글자·바탕을 바꿔도 같은 값")

    def test_ratio_never_rounds_up_across_a_line(self):
        self.assertEqual(dk.fmt_ratio(21.0), "21.00")
        self.assertEqual(dk.fmt_ratio(4.5), "4.50")
        self.assertEqual(dk.fmt_ratio(4.496), "4.49", "기준 4.5에 모자라는 값이 4.50으로 보이면 안 된다")
        self.assertEqual(dk.fmt_ratio(2.999), "2.99")
        self.assertEqual(dk.fmt_ratio(6.999), "6.99")
        self.assertEqual(dk.fmt_ratio(4.478), "4.48")

    def test_contrast_with_alpha_and_errors(self):
        text = call(self.srv, "contrast", fg="rgba(0,0,0,0.5)", bg="#ffffff")[0]
        self.assertIn("글자 #808080", text, "투명한 글자색은 바탕 위에 겹쳐 계산")
        self.assertIn("겹친 색(#808080)", text)
        self.assertIn("3.95 : 1", text)
        self.assertIn("겹친 색", call(self.srv, "contrast", fg="#00000000", bg="#ffffff")[0])
        self.assertIn("1.00 : 1", call(self.srv, "contrast", fg="#ffffff00", bg="#ffffff")[0])
        self.assertIn("흰색 위", call(self.srv, "contrast", fg="#000000", bg="#ffffff80")[0])
        text, err = call(self.srv, "contrast", fg="빨강", bg="#ffffff")
        self.assertTrue(err)
        self.assertIn("fg", text)
        self.assertTrue(call(self.srv, "contrast", fg="#000000", bg="")[1])
        self.assertTrue(call(self.srv, "contrast", fg="#000000")[1])

    def test_contrast_table_marks_and_warns_similar(self):
        text, err = call(self.srv, "contrast_table", colors=["#111111", "#ffffff", "#777777", "#787878"])
        self.assertFalse(err, text)
        self.assertIn("18.88 ✓", text)
        self.assertIn("4.48 △", text)
        self.assertIn("4.22 △", text)
        self.assertIn("1.01 ✗", text)
        self.assertIn("3번 #777777 와 4번 #787878", text)
        self.assertIn("ΔE 0.4", text)
        text = call(self.srv, "contrast_table", colors=["#000000", "#ffffff", "#3b82f6"])[0]
        self.assertIn("비슷한 색은 없어요", text)
        self.assertIn("21.00 ✓", text)
        self.assertIn("✗", call(self.srv, "contrast_table", colors=["#111111", "#151515"])[0])
        self.assertIn("완전히 같아요", call(self.srv, "contrast_table", colors=["#123456", "#123456"])[0])
        for bad in (["#000000"], ["#000000"] * 13, "#000000,#ffffff", [], ["#000000", "빨강"]):
            self.assertTrue(call(self.srv, "contrast_table", colors=bad)[1], bad)
        self.assertFalse(call(self.srv, "contrast_table", colors=["#000000"] * 12)[1])
        self.assertIn("흰색 위", call(self.srv, "contrast_table", colors=["#00000080", "#ffffff"])[0])

    def test_delta_e_matches_reference(self):
        self.assertAlmostEqual(dk.delta_e76((0, 0, 0), (255, 255, 255)), 100.0, places=1)
        self.assertEqual(dk.delta_e76((12, 34, 56), (12, 34, 56)), 0.0)
        self.assertAlmostEqual(dk.to_lab((255, 0, 0))[0], 53.24, places=1)
        self.assertAlmostEqual(dk.to_lab((255, 255, 255))[0], 100.0, places=1)
        self.assertLess(dk.delta_e76((119, 119, 119), (120, 120, 120)), dk.SIMILAR_DE)
        self.assertGreater(dk.delta_e76((119, 119, 119), (160, 160, 160)), dk.SIMILAR_DE)


class PaletteTool(unittest.TestCase):
    BASES = ("#3b82f6", "#f5e6b5", "#e11d48", "#16a34a", "#000000", "#ffffff", "#888888", "#ffde59", "#7f00ff", "#0a0a0a", "#c7d2fe")

    @staticmethod
    def rgb(hexstr):
        return dk.parse_color(hexstr)[:3]

    def test_guarantees_hold_for_every_scheme_and_mode(self):
        cr = dk.contrast_ratio
        for base in self.BASES:
            for scheme in dk.SCHEMES:
                for mode in ("light", "dark"):
                    p = dk.make_palette(self.rgb(base), scheme, mode)
                    msg = (base, scheme, mode)
                    bg, surface, ink, soft = (self.rgb(p[k]) for k in ("bg", "surface", "ink", "ink_soft"))
                    accent, on = self.rgb(p["accent"]), self.rgb(p["on_accent"])
                    self.assertGreaterEqual(cr(ink, surface), 7.0, msg)
                    self.assertGreaterEqual(cr(ink, bg), 7.0, msg)
                    self.assertGreaterEqual(cr(soft, surface), 4.5, msg)
                    self.assertGreaterEqual(cr(soft, bg), 4.5, msg)
                    self.assertGreaterEqual(cr(on, accent), 4.5, msg)
                    self.assertIn(p["on_accent"], ("#ffffff", "#000000"), msg)
                    self.assertGreaterEqual(cr(accent, bg), 3.0, msg)
                    self.assertTrue(p["ok"], msg)
                    self.assertTrue(2 <= len(p["extra"]) <= 3, msg)
                    for e in p["extra"]:
                        self.assertGreaterEqual(cr(self.rgb(e["on"]), self.rgb(e["hex"])), 4.5, (msg, e))
                    # 적어 준 실제 대비값이 진짜 계산값과 같다
                    self.assertAlmostEqual(p["contrast"]["ink_surface"], cr(ink, surface))
                    self.assertAlmostEqual(p["contrast"]["on_accent"], cr(on, accent))
                    # 밝은 화면은 바탕이 밝고, 어두운 화면은 어둡다
                    self.assertEqual(dk.luminance(bg) > 0.5, mode == "light", msg)
                    self.assertGreater(len({p["bg"], p["surface"], p["ink"], p["accent"]}), 2, msg)

    def test_same_input_same_output(self):
        for scheme in dk.SCHEMES:
            a = dk.make_palette((59, 130, 246), scheme, "dark")
            self.assertEqual(a, dk.make_palette((59, 130, 246), scheme, "dark"))
        srv = dk.build()
        one = call(srv, "palette", base="#3b82f6", scheme="triad", mode="light")
        self.assertEqual(one, call(srv, "palette", base="#3b82f6", scheme="triad"), "mode를 비우면 light")
        self.assertNotEqual(one[0], call(srv, "palette", base="#3b82f6", scheme="triad", mode="dark")[0])

    def test_scheme_shapes_extras_and_text(self):
        names = {s: [e["name"] for e in dk.make_palette((59, 130, 246), s)["extra"]] for s in dk.SCHEMES}
        self.assertEqual([len(v) for v in names.values()], [2, 3, 2, 3, 3])
        self.assertIn("진한 강조", names["mono"][0])
        self.assertIn("+180도", names["complementary"][0])
        self.assertIn("-30도", names["analogous"][0])
        self.assertIn("+120도", names["triad"][0])
        self.assertIn("+210도", names["split"][1])
        srv = dk.build()
        text, err = call(srv, "palette", base="#3b82f6", scheme="mono")
        self.assertFalse(err, text)
        p = dk.make_palette((59, 130, 246), "mono")
        for part in (f"바탕 bg: {p['bg']}", f"카드 면 surface: {p['surface']}", f"본문 글자 ink: {p['ink']}", f"보조 글자 ink_soft: {p['ink_soft']}",
                     f"강조 accent: {p['accent']}", f"강조 위 글자 on_accent: {p['on_accent']}", f"경계선 line: {p['line']}", "보조색 extra:", "보장:"):
            self.assertIn(part, text)
        self.assertIn(f"카드 면 위 {dk.fmt_ratio(p['contrast']['ink_surface'])}:1", text)
        data = json.loads(text.splitlines()[-1].removeprefix("JSON: "))
        self.assertEqual((data["bg"], data["ink"], data["accent"]), (p["bg"], p["ink"], p["accent"]))
        self.assertEqual(len(data["extra"]), 2)
        self.assertIn("회색에 가까워", call(srv, "palette", base="#888888", scheme="triad")[0])
        self.assertNotIn("회색에 가까워", call(srv, "palette", base="#888888", scheme="mono")[0])

    def test_dark_accent_stays_close_to_base_when_it_already_works(self):
        # 어두운 화면에서 밝은 색은 그대로, 밝은 화면에서 옅은 색은 어두워져 바탕 위에서 보인다
        self.assertEqual(dk.make_palette((245, 230, 181), "mono", "dark")["accent"], "#f5e6b5")
        light = dk.make_palette((245, 230, 181), "mono", "light")
        self.assertGreaterEqual(dk.contrast_ratio(self.rgb(light["accent"]), self.rgb(light["bg"])), 3.0)
        h0 = dk.rgb_to_hsl((245, 230, 181))
        h1 = dk.rgb_to_hsl(self.rgb(light["accent"]))
        self.assertLess(abs(h0[0] - h1[0]), 3, "색상은 그대로, 밝기만 바뀐다")

    def test_bad_input(self):
        srv = dk.build()
        for args in ({"base": "red", "scheme": "mono"}, {"base": "#3b82f6", "scheme": "rainbow"}, {"base": "#3b82f6", "scheme": "mono", "mode": "night"},
                     {"base": "#3b82f6"}, {"scheme": "mono"}):
            text, err = call(srv, "palette", **args)
            self.assertTrue(err, args)
            self.assertRegex(text, "[가-힣]")


class ScaleGridFit(unittest.TestCase):
    def setUp(self):
        self.srv = dk.build()

    def test_type_scale(self):
        text, err = call(self.srv, "scale", kind="type", base=16)
        self.assertFalse(err, text)
        sizes = re.findall(r"^- (\S+)\s+(\d+)px", text, re.M)
        self.assertEqual(sizes, [("small", "13"), ("base", "16"), ("lg", "20"), ("xl", "25"), ("2xl", "31"), ("3xl", "39"), ("4xl", "49"), ("5xl", "61")])
        text = call(self.srv, "scale", kind="type", base=10, ratio=2, steps=3, down=2)[0]
        self.assertEqual(re.findall(r"^- (\S+)\s+(\d+)px", text, re.M), [("xsmall", "3"), ("small", "5"), ("base", "10"), ("lg", "20"), ("xl", "40"), ("2xl", "80")])
        text = call(self.srv, "scale", kind="type", base=12, steps=12, down=3, ratio=1.067)[0]
        self.assertEqual(len(re.findall(r"^- ", text, re.M)), 16)
        self.assertIn("2xsmall", text)
        self.assertIn("11xl", text)
        self.assertIn("같은 크기", call(self.srv, "scale", kind="type", base=8, ratio=1.067, steps=3)[0])
        self.assertNotIn("같은 크기", call(self.srv, "scale", kind="type", base=16)[0])

    def test_space_scale(self):
        text = call(self.srv, "scale", kind="space", base=8, steps=4)[0]
        self.assertEqual(re.findall(r"^- (\S+)배\s+(\d+)px", text, re.M), [("0.5", "4"), ("1", "8"), ("1.5", "12"), ("2", "16")])
        text = call(self.srv, "scale", kind="space", base=8)[0]
        self.assertEqual([m[1] for m in re.findall(r"^- (\S+)배\s+(\d+)px", text, re.M)], ["4", "8", "12", "16", "24", "32"])
        text = call(self.srv, "scale", kind="space", base=5, steps=2)[0]
        self.assertIn("0.5배  3px  (2.5을 반올림)", text)
        text = call(self.srv, "scale", kind="space", base=4, steps=12)[0]
        self.assertEqual(len(re.findall(r"^- ", text, re.M)), 10)
        self.assertIn("최대 10개", text)
        self.assertIn("64px", text)
        self.assertIn("ratio·down은 type에서만", call(self.srv, "scale", kind="space", base=8, ratio=1.5)[0])

    def test_scale_rejects_bad_input(self):
        for args in ({"kind": "size", "base": 16}, {"kind": "type", "base": 0}, {"kind": "type", "base": "abc"}, {"kind": "type", "base": True},
                     {"kind": "type", "base": 16, "ratio": 1.0}, {"kind": "type", "base": 16, "ratio": 2.5}, {"kind": "type", "base": 16, "steps": 13},
                     {"kind": "type", "base": 16, "steps": 0}, {"kind": "type", "base": 16, "steps": 2.5}, {"kind": "type", "base": 16, "down": 4},
                     {"kind": "type", "base": 16, "down": -1}, {"kind": "type", "base": float("inf")}, {"kind": "type"}):
            text, err = call(self.srv, "scale", **args)
            self.assertTrue(err, args)
            self.assertRegex(text, "[가-힣]")
        self.assertFalse(call(self.srv, "scale", kind="type", base="16", ratio="1.5", steps="3")[1], "글자로 온 숫자도 받는다")
        self.assertFalse(call(self.srv, "scale", kind="type", base=16, ratio=1.067)[1])
        self.assertFalse(call(self.srv, "scale", kind="type", base=16, ratio=2)[1])

    def test_char_widths(self):
        em = dk.char_em
        for ch in "가한글漢字あア＠１":
            self.assertEqual(em(ch), 1.0, ch)
        self.assertEqual((em("A"), em("Z"), em("a"), em("z"), em("7"), em(" "), em(",")), (0.68, 0.68, 0.55, 0.55, 0.58, 0.3, 0.35))
        self.assertEqual((em("!"), em("."), em("-"), em("…"), em("·")), (0.35, 0.35, 0.35, 0.35, 0.35))
        self.assertEqual((em("É"), em("é"), em("́")), (0.68, 0.55, 0.0))
        self.assertEqual(em("。"), 1.0)

    def test_text_fit_widths_and_lines(self):
        text, err = call(self.srv, "text_fit", text="안녕 Hello", font_px=10, box_width=100)
        self.assertFalse(err, text)
        self.assertTrue(text.startswith("추정(실제 글꼴에 따라 ±10%)"), text)
        self.assertIn("예상 줄 수: 1줄", text)
        self.assertIn("51.8px", text, "안녕 20 + 공백 3 + Hello 28.8")
        # 공백에서 줄바꿈
        lines = dk.layout_lines("aaaa bbbb cccc", 10, 50, 0)
        self.assertEqual([round(x, 1) for x in lines], [47.0, 22.0])
        self.assertEqual(len(dk.layout_lines("aaaa bbbb cccc", 10, 50, 0)), 2)
        self.assertIn("예상 줄 수: 2줄", call(self.srv, "text_fit", text="aaaa bbbb cccc", font_px=10, box_width=50)[0])
        # 한글은 글자마다 폭 1.0, 낱말이 칸보다 길면 중간에서 자른다 (16px × 6글자 = 96 ≤ 100)
        text = call(self.srv, "text_fit", text="가나다라마바사아자차카타", font_px=16, box_width=100)[0]
        self.assertIn("예상 줄 수: 2줄", text)
        self.assertIn("가장 긴 줄 폭: 96.0px", text)
        lines = dk.layout_lines("Supercalifragilisticexpialidocious", 16, 100, 0)
        self.assertGreaterEqual(len(lines), 3)
        self.assertTrue(all(w <= 100 + 1e-6 for w in lines), lines)
        self.assertAlmostEqual(sum(lines), sum(dk.char_em(c) for c in "Supercalifragilisticexpialidocious") * 16)
        # 줄바꿈 글자·글자 사이 간격
        self.assertEqual(len(dk.layout_lines("a\n\nb", 10, 100, 0)), 3)
        self.assertEqual(dk.layout_lines("aaaa", 10, 1000, 1.0), [26.0])
        self.assertIn("가장 긴 줄 폭: 26.0px", call(self.srv, "text_fit", text="aaaa", font_px=10, box_width=1000, letter_spacing=1)[0])
        # 칸보다 넓은 글자 하나: 한 글자씩이라도 무한 반복하지 않는다
        self.assertEqual(len(dk.layout_lines("가나다", 16, 5, 0)), 3)
        self.assertIn("글자 하나가 칸보다 넓어요", call(self.srv, "text_fit", text="가", font_px=16, box_width=5)[0])

    def test_text_fit_max_lines_and_suggestions(self):
        sample = "안녕하세요 반갑습니다 Hello World"
        text = call(self.srv, "text_fit", text=sample, font_px=16, box_width=200, max_lines=1)[0]
        self.assertIn("1줄 안에 들어가나: 안 들어가요 ✗", text)
        m = re.search(r"글자를 (\d+)px로 줄이거나 칸을 (\d+)px로 넓히세요", text)
        self.assertTrue(m, text)
        small, wide = int(m.group(1)), int(m.group(2))
        # 제안대로 하면 글꼴이 10% 넓게 나와도 1줄에 들어가고, 한 칸(1px)만 덜 하면 안 들어간다
        self.assertEqual(len(dk.layout_lines(sample, small, 200, 0, 1.1)), 1)
        self.assertGreater(len(dk.layout_lines(sample, small + 1, 200, 0, 1.1)), 1)
        self.assertEqual(len(dk.layout_lines(sample, 16, wide, 0, 1.1)), 1)
        self.assertGreater(len(dk.layout_lines(sample, 16, wide - 1, 0, 1.1)), 1)
        self.assertLess(small, 16)
        self.assertGreater(wide, 200)
        # 들어가는 경우
        text = call(self.srv, "text_fit", text="확인", font_px=16, box_width=200, max_lines=1)[0]
        self.assertIn("들어가요 ✓", text)
        self.assertNotIn("제안", text)
        # 들어가지만 글꼴이 10% 넓게 나오면 넘치는 경우 여유가 없다고 알린다
        tight = "가나다라마바사아자차"  # 10글자 × 16 = 160
        text = call(self.srv, "text_fit", text=tight, font_px=16, box_width=165, max_lines=1)[0]
        self.assertIn("들어가요 ✓", text)
        self.assertIn("여유가 없어요", text)
        # 줄바꿈 때문에 어떻게 해도 안 되는 경우
        text = call(self.srv, "text_fit", text="a\nb\nc", font_px=10, box_width=100, max_lines=2)[0]
        self.assertIn("줄바꿈이 2번", text)
        # 글자가 8px 아래로 내려가야만 맞으면 칸을 넓히라고만 한다
        text = call(self.srv, "text_fit", text="가" * 40, font_px=9, box_width=100, max_lines=1)[0]
        self.assertIn("칸을", text)
        self.assertNotIn("px로 줄이", text)

    def test_text_fit_rejects_bad_input(self):
        base = {"text": "안녕", "font_px": 16, "box_width": 100}
        for bad in ({"text": ""}, {"text": "   "}, {"text": "가" * 5001}, {"font_px": 0}, {"font_px": "abc"}, {"font_px": 600}, {"box_width": -1},
                    {"box_width": 0}, {"max_lines": 0}, {"max_lines": 1.5}, {"letter_spacing": 1000}, {"letter_spacing": "x"}):
            text, err = call(self.srv, "text_fit", **{**base, **bad})
            self.assertTrue(err, bad)
            self.assertRegex(text, "[가-힣]")
        self.assertFalse(call(self.srv, "text_fit", **{**base, "max_lines": None, "letter_spacing": None})[1])
        self.assertFalse(call(self.srv, "text_fit", text="가" * 5000, font_px=16, box_width=100)[1])

    def test_grid_sums_to_width(self):
        text, err = call(self.srv, "grid", width=1280, columns=12, gutter=20, margin=40)
        self.assertFalse(err, text)
        self.assertIn("1열: x=40 ~ 122 (폭 82px)", text)
        self.assertIn("9열: x=856 ~ 937 (폭 81px)", text)
        self.assertIn("12열: x=1159 ~ 1240 (폭 81px)", text)
        self.assertIn("8개는 1px 더 넓어 82px, 앞 열부터", text)
        self.assertIn("검산: 80 + 980 + 220 = 1280 ✓", text)
        for width, columns, gutter, margin in ((1280, 12, 20, 40), (360, 4, 16, 16), (640, 7, 3, 0), (100, 3, 0, 0), (999, 5, 7, 11), (48, 48, 0, 0), (13, 1, 0, 6)):
            text = call(self.srv, "grid", width=width, columns=columns, gutter=gutter, margin=margin)[0]
            cols = [tuple(map(int, m)) for m in re.findall(r"x=(\d+) ~ (\d+) \(폭 (\d+)px\)", text)]
            self.assertEqual(len(cols), columns, text)
            self.assertEqual(cols[0][0], margin)
            self.assertEqual(cols[-1][1], width - margin, (width, columns, gutter, margin))
            self.assertEqual(sum(c[2] for c in cols) + gutter * (columns - 1) + 2 * margin, width)
            for (x0, x1, w), nxt in zip(cols, cols[1:]):
                self.assertEqual((x1 - x0, nxt[0] - x1), (w, gutter))
            widths = [c[2] for c in cols]
            self.assertEqual(widths, sorted(widths, reverse=True), "남는 픽셀은 앞 열부터")
            self.assertLessEqual(max(widths) - min(widths), 1)
            self.assertIn("✓ 폭과 같아요", text)
        self.assertIn("(모두 같아요)", call(self.srv, "grid", width=120, columns=4, gutter=0, margin=0)[0])
        self.assertIn("34px", call(self.srv, "grid", width=100, columns=3)[0], "gutter·margin을 비우면 0")

    def test_grid_rejects_bad_input(self):
        for args in ({"width": 10, "columns": 12, "gutter": 5, "margin": 0}, {"width": 100, "columns": 0}, {"width": 100, "columns": 49},
                     {"width": 100, "columns": 2.5}, {"width": 0, "columns": 1}, {"width": 100, "columns": 2, "gutter": -1},
                     {"width": 100, "columns": 2, "margin": 60}, {"width": "abc", "columns": 2}, {"width": 100, "columns": 2, "gutter": 0.5}):
            text, err = call(self.srv, "grid", **args)
            self.assertTrue(err, args)
            self.assertRegex(text, "[가-힣]")


class ImageInfo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="ais-dk-")
        self.root = Path(self._tmp.name).resolve()
        self.work = self.root / "work"  # 서버를 띄운 폴더
        self.extra = self.root / "extra"  # --allow 폴더
        self.outside = self.root / "outside"
        for d in (self.work, self.extra, self.outside):
            d.mkdir()
        self.srv = dk.build(allow=[self.extra], cwd=self.work)

    def tearDown(self):
        self._tmp.cleanup()

    def save(self, folder, name, data):
        p = folder / name
        p.write_bytes(data)
        return str(p)

    def info(self, data, name="a.png"):
        text, err = call(self.srv, "image_info", path=self.save(self.work, name, data))
        return text, err

    def read(self, data):
        return dk.read_png(data)

    def test_rgba_all_filters_and_merged_transparent(self):
        w, h = 8, 6
        pixels = [((x * 37 + y * 11) & 255, (x * x + y * 5) & 255, (x * 13 ^ y * 29) & 255, 255 if (x + y) % 5 else (x * y * 7) & 255)
                  for y in range(h) for x in range(w)]
        rows = [bytes(v for px in pixels[y * w:(y + 1) * w] for v in px) for y in range(h)]
        for filters in ((0,), (1,), (2,), (3,), (4,), (0, 1, 2, 3, 4, 1)):
            info = self.read(make_png(w, h, 6, 8, rows, filters=filters))
            self.assertEqual(info["colors"], hist(pixels), filters)
            self.assertEqual((info["w"], info["h"], info["ct"], info["depth"]), (8, 6, 6, 8))
            self.assertEqual(info["clear"], sum(p[3] == 0 for p in pixels))
            self.assertEqual(info["semi"], sum(0 < p[3] < 255 for p in pixels))
        self.assertGreater(sum(p[3] == 0 for p in pixels), 1)
        self.assertEqual(self.read(make_png(w, h, 6, 8, rows, split=True))["colors"], hist(pixels), "IDAT가 여러 조각이어도")

    def test_rgba_text_report(self):
        red, blue, green_half = (255, 0, 0, 255), (0, 0, 255, 255), (0, 255, 0, 128)
        pixels = [red, red, blue, (0, 0, 0, 0), red, green_half, (255, 255, 255, 0), blue]
        rows = [bytes(v for px in pixels[y * 4:(y + 1) * 4] for v in px) for y in range(2)]
        text, err = self.info(make_png(4, 2, 6, 8, rows, filters=(1, 4)), "hero.png")
        self.assertFalse(err, text)
        self.assertIn("파일: hero.png", text)
        self.assertNotIn(str(self.work), text, "전체 경로는 적지 않는다")
        self.assertIn("크기: 4 × 2 픽셀", text)
        self.assertIn("색+투명도(RGBA), 8비트", text)
        self.assertIn("투명 픽셀(완전히 투명): 25.0%", text)
        self.assertIn("서로 다른 색: 4개 (완전히 투명한 픽셀은 색 하나로 셈)", text)
        self.assertIn("1. #ff0000 37.5%", text)
        self.assertIn("2. 투명 25.0%", text)
        self.assertIn("3. #0000ff 25.0%", text)
        self.assertIn("4. #00ff0080 12.5%", text)
        self.assertIn("색 개수: 4개 → 32개 이하예요 ✓", text)
        self.assertIn("가로 4 · 세로 2은(는) 8의 배수가 아니에요 △", text)
        self.assertIn("반투명 픽셀(알파 1~254): 12.5% ✗", text)

    def test_pixel_art_checks(self):
        pal = [(i * 8, 255 - i * 8, (i * 40) & 255) for i in range(16)]
        rows = [bytes(v for x in range(16) for v in pal[(x + y) % 16] + (255,)) for y in range(16)]
        text = self.info(make_png(16, 16, 6, 8, rows))[0]
        self.assertIn("서로 다른 색: 16개", text)
        self.assertIn("색 개수: 16개 → 32개 이하예요 ✓", text)
        self.assertIn("가로 16·세로 16 모두 8의 배수예요 ✓", text)
        self.assertIn("반투명 픽셀(알파 1~254): 0% ✓", text)
        self.assertIn("투명 픽셀(완전히 투명): 0%", text)
        many = [bytes(v for x in range(40) for v in (x * 6, y * 6, 9, 255)) for y in range(40)]
        text = self.info(make_png(40, 40, 6, 8, many))[0]
        self.assertIn("색 개수: 1600개 → 32개를 넘어요 ✗", text)
        self.assertIn("상위 8개", text)
        self.assertEqual(len(re.findall(r"^  \d\. ", text, re.M)), 8)
        # 조금(1% 미만)만 반투명이면 △
        big = [bytes(v for x in range(32) for v in ((0, 0, 0, 100) if (x, y) == (3, 3) else (9, 9, 9, 255))) for y in range(32)]
        self.assertIn("반투명 픽셀(알파 1~254): 0.1% 미만 △", self.info(make_png(32, 32, 6, 8, big))[0])

    def test_palette_gray_and_other_color_types(self):
        # 팔레트 8비트 + tRNS (번호 1은 반투명, 번호 3은 tRNS에 없어 불투명)
        plte = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9])
        idx = [[0, 1, 2, 3, 0], [3, 2, 1, 0, 1]]
        info = self.read(make_png(5, 2, 3, 8, [bytes(r) for r in idx], plte=plte, trns=bytes([255, 128]), filters=(1, 2)))
        want = Counter()
        for r in idx:
            for i in r:
                c = plte[3 * i:3 * i + 3]
                want[c + bytes([128 if i == 1 else 255])] += 1
        self.assertEqual(info["colors"], want)
        self.assertEqual((info["palette_n"], info["semi"], info["clear"]), (4, 3, 0))
        self.assertIn("팔레트, 8비트, 팔레트 4색", self.info(make_png(5, 2, 3, 8, [bytes(r) for r in idx], plte=plte))[0])
        # 팔레트 2비트(한 바이트에 4픽셀) + 번호 0이 투명
        plte4 = bytes([1, 2, 3, 40, 50, 60, 70, 80, 90, 200, 210, 220])
        idx4 = [[0, 1, 2, 3, 0], [3, 2, 1, 0, 1], [0, 0, 0, 0, 0]]
        info = self.read(make_png(5, 3, 3, 2, [pack_bits(r, 2) for r in idx4], plte=plte4, trns=bytes([0]), filters=(0, 1, 3)))
        self.assertEqual(info["clear"], 8)
        self.assertEqual(info["colors"][bytes(4)], 8)
        self.assertEqual(info["colors"][bytes([70, 80, 90, 255])], 2)
        self.assertEqual(sum(info["colors"].values()), 15)
        # 팔레트 1비트·4비트
        info = self.read(make_png(10, 1, 3, 1, [pack_bits([0, 1] * 5, 1)], plte=bytes([0, 0, 0, 255, 255, 255])))
        self.assertEqual(info["colors"], Counter({bytes([0, 0, 0, 255]): 5, bytes([255, 255, 255, 255]): 5}))
        info = self.read(make_png(3, 1, 3, 4, [pack_bits([15, 0, 7], 4)], plte=bytes(range(48))))
        self.assertEqual(set(info["colors"]), {bytes([45, 46, 47, 255]), bytes([0, 1, 2, 255]), bytes([21, 22, 23, 255])})
        # 회색 8비트 (tRNS: 값 0이 투명)
        gray = [bytes([0, 128, 255, 0]), bytes([64, 64, 0, 255])]
        info = self.read(make_png(4, 2, 0, 8, gray, trns=bytes([0, 0]), filters=(4, 1)))
        self.assertEqual(info["colors"], Counter({bytes(4): 3, bytes([128, 128, 128, 255]): 1, bytes([255, 255, 255, 255]): 2, bytes([64, 64, 64, 255]): 2}))
        # 회색 1비트·4비트 (표본 값이 8비트로 펴진다)
        info = self.read(make_png(10, 1, 0, 1, [pack_bits([1, 0] * 5, 1)]))
        self.assertEqual(info["colors"], Counter({bytes([255, 255, 255, 255]): 5, bytes([0, 0, 0, 255]): 5}))
        info = self.read(make_png(3, 1, 0, 4, [pack_bits([15, 0, 8], 4)]))
        self.assertEqual(set(info["colors"]), {bytes([255] * 4), bytes([0, 0, 0, 255]), bytes([136, 136, 136, 255])})
        # 회색 16비트 (위 바이트로 줄인다) + 투명 값이 16비트 전체와 같을 때만 투명
        rows = [struct.pack(">HHH", 0x8000, 0x1234, 0x1200)]
        info = self.read(make_png(3, 1, 0, 16, rows, trns=struct.pack(">H", 0x1234)))
        self.assertEqual(info["colors"], Counter({bytes([128, 128, 128, 255]): 1, bytes(4): 1, bytes([0x12] * 3 + [255]): 1}))
        # 회색+투명도 8비트·16비트
        info = self.read(make_png(2, 1, 4, 8, [bytes([100, 255, 50, 0])], filters=(1,)))
        self.assertEqual(info["colors"], Counter({bytes([100, 100, 100, 255]): 1, bytes(4): 1}))
        info = self.read(make_png(2, 1, 4, 16, [struct.pack(">HHHH", 0xFFFF, 0x8000, 0x0000, 0xFFFF)], filters=(3,)))
        self.assertEqual(info["colors"], Counter({bytes([255, 255, 255, 128]): 1, bytes([0, 0, 0, 255]): 1}))
        self.assertEqual(info["semi"], 1)
        # RGB 8비트 (tRNS: 그 색이 투명) · RGB 16비트 (투명색은 16비트 전체가 같을 때만)
        rows = [bytes([10, 20, 30, 10, 20, 31, 255, 0, 0])]
        info = self.read(make_png(3, 1, 2, 8, rows, trns=struct.pack(">HHH", 10, 20, 30), filters=(2,)))
        self.assertEqual(info["colors"], Counter({bytes(4): 1, bytes([10, 20, 31, 255]): 1, bytes([255, 0, 0, 255]): 1}))
        rows = [struct.pack(">HHHHHH", 0x0A00, 0x1400, 0x1E00, 0x0A00, 0x1400, 0x1E01)]
        info = self.read(make_png(2, 1, 2, 16, rows, trns=struct.pack(">HHH", 0x0A00, 0x1400, 0x1E00)))
        self.assertEqual(info["colors"], Counter({bytes(4): 1, bytes([10, 20, 30, 255]): 1}))
        info = self.read(make_png(2, 1, 2, 8, [bytes([1, 2, 3, 4, 5, 6])]))
        self.assertEqual(info["colors"], Counter({bytes([1, 2, 3, 255]): 1, bytes([4, 5, 6, 255]): 1}))
        # RGBA 16비트
        rows = [struct.pack(">HHHHHHHH", 0xFFFF, 0, 0, 0xFFFF, 0, 0x8080, 0, 0x8080)]
        info = self.read(make_png(2, 1, 6, 16, rows, filters=(4,)))
        self.assertEqual(info["colors"], Counter({bytes([255, 0, 0, 255]): 1, bytes([0, 128, 0, 128]): 1}))
        text = self.info(make_png(2, 1, 6, 16, rows))[0]
        self.assertIn("색+투명도(RGBA), 16비트", text)

    def test_more_than_100k_colors(self):
        w, h = 400, 300
        rows = [bytes(v for i in range(y * w, (y + 1) * w) for v in ((i >> 16) & 255, (i >> 8) & 255, i & 255)) for y in range(h)]
        text, err = self.info(make_png(w, h, 2, 8, rows))
        self.assertFalse(err, text)
        self.assertIn("서로 다른 색: 10만 개 넘음", text)
        self.assertIn("색 개수: 10만 개 넘음 → 32개를 넘어요 ✗", text)
        self.assertNotIn("1. #", text)
        self.assertIn("색이 너무 많아", text)
        self.assertIn("세로 300은(는) 8의 배수가 아니에요", text)

    def test_only_allowed_folders_and_png(self):
        png = make_png(2, 1, 6, 8, [bytes([1, 2, 3, 255, 4, 5, 6, 255])])
        inside = self.save(self.work, "in.png", png)
        extra = self.save(self.extra, "extra.png", png)
        outside = self.save(self.outside, "out.png", png)
        self.assertFalse(call(self.srv, "image_info", path=inside)[1])
        self.assertFalse(call(self.srv, "image_info", path=extra)[1], "--allow 폴더")
        self.assertFalse(call(self.srv, "image_info", path="in.png")[1], "작업 폴더 기준 상대 경로")
        self.assertFalse(call(self.srv, "image_info", path="sub/../in.png")[1], "폴더 안에서 돌아오는 ..은 괜찮다")
        if os.name == "nt":  # 윈도우는 파일 이름의 대소문자를 가리지 않는다
            self.assertFalse(call(self.srv, "image_info", path=str(self.work / "IN.PNG"))[1], "확장자 대소문자")
        for bad in (outside, str(self.work / ".." / "outside" / "out.png"), "../outside/out.png", str(self.work / "sub" / ".." / ".." / "outside" / "out.png"),
                    str(self.root / "outside" / "out.png")):
            text, err = call(self.srv, "image_info", path=bad)
            self.assertTrue(err, bad)
            self.assertIn("볼 수 없어요", text, bad)
        # 서버를 띄운 폴더가 달라지면 허용 폴더도 달라진다
        other = dk.build(cwd=self.outside)
        self.assertFalse(call(other, "image_info", path=outside)[1])
        self.assertTrue(call(other, "image_info", path=inside)[1])
        # 확장자 (PNG 내용이어도 .png가 아니면 거부, .png인데 내용이 PNG가 아니면 거부)
        for name in ("a.txt", "a.png.txt", "a.jpg", "png", "a.png.exe"):
            text, err = call(self.srv, "image_info", path=self.save(self.work, name, png))
            self.assertTrue(err, name)
            self.assertIn("PNG 파일(.png)만", text)
        text, err = call(self.srv, "image_info", path=self.save(self.work, "fake.png", b"GIF89a-not-a-png"))
        self.assertTrue(err)
        self.assertIn("PNG 파일이 아니에요", text)
        self.assertIn("그 파일이 없어요", call(self.srv, "image_info", path=str(self.work / "none.png"))[0])
        (self.work / "dir.png").mkdir()
        self.assertIn("그 파일이 없어요", call(self.srv, "image_info", path=str(self.work / "dir.png"))[0])
        for bad in ("", "   ", "a" * 1001, "in" + chr(0) + ".png"):
            self.assertTrue(call(self.srv, "image_info", path=bad)[1], bad[:20])

    def test_symlink_out_of_the_folder_is_refused(self):
        png = make_png(2, 1, 6, 8, [bytes([1, 2, 3, 255, 4, 5, 6, 255])])
        target = Path(self.save(self.outside, "secret.png", png))
        link = self.work / "link.png"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("이 PC에서는 바로가기(심볼릭 링크)를 만들 수 없다")
        text, err = call(self.srv, "image_info", path=str(link))
        self.assertTrue(err)
        self.assertIn("볼 수 없어요", text)
        inner = self.work / "inner.png"
        try:
            os.symlink(self.work / "in.png", inner)
        except (OSError, NotImplementedError):
            return
        self.save(self.work, "in.png", png)
        self.assertFalse(call(self.srv, "image_info", path=str(inner))[1], "폴더 안을 가리키는 바로가기는 괜찮다")

    def test_size_and_pixel_limits(self):
        png = make_png(4, 4, 6, 8, [bytes(16)] * 4)
        path = self.save(self.work, "big.png", png)
        with mock.patch.object(dk, "MAX_FILE", len(png) - 1):
            text, err = call(self.srv, "image_info", path=path)
        self.assertTrue(err)
        self.assertIn("넘어서 읽지 않아요", text)
        with mock.patch.object(dk, "MAX_FILE", len(png)):
            self.assertFalse(call(self.srv, "image_info", path=path)[1])
        with mock.patch.object(dk, "MAX_PIXELS", 15):
            text, err = call(self.srv, "image_info", path=path)
        self.assertTrue(err)
        self.assertIn("너무 커요", text)
        with mock.patch.object(dk, "MAX_PIXELS", 16):
            self.assertFalse(call(self.srv, "image_info", path=path)[1])
        self.assertEqual((dk.MAX_FILE, dk.MAX_PIXELS, dk.MAX_COLORS), (20 * 1024 * 1024, 16_000_000, 100_000))
        # 머리 정보만 큰 그림 (자료는 작다): 자료를 풀기 전에 거부한다
        huge = dk.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 100000, 100000, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"x")) + chunk(b"IEND", b"")
        text, err = self.info(huge)
        self.assertTrue(err)
        self.assertIn("너무 커요", text)

    def test_unsupported_and_broken_pngs(self):
        rows = [bytes(8)] * 2
        text, err = self.info(make_png(2, 2, 6, 8, rows, interlace=1))
        self.assertTrue(err)
        self.assertIn("지원하지 않는 PNG(인터레이스)", text)
        good = make_png(2, 2, 6, 8, rows)
        bad_depth = [make_png(2, 2, 2, 4, [bytes(3)] * 2), make_png(2, 2, 3, 16, [bytes(4)] * 2, plte=bytes(3)), make_png(2, 2, 0, 3, [bytes(1)] * 2),
                     make_png(2, 2, 5, 8, rows), make_png(0, 2, 6, 8, rows)]
        for data in bad_depth:
            self.assertTrue(self.info(data)[1])
        crc = bytearray(good)
        crc[-20] ^= 0xFF  # IDAT 안쪽 한 바이트
        text, err = self.info(bytes(crc))
        self.assertTrue(err)
        self.assertIn("깨져 있어요", text)
        self.assertIn("끊겼어요", self.info(good[:-20])[0])
        self.assertIn("PNG 파일이 아니에요", self.info(b"\x89PNG-broken")[0])
        no_idat = dk.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)) + chunk(b"IEND", b"")
        self.assertIn("그림 자료가 없어요", self.info(no_idat)[0])
        no_plte = make_png(2, 2, 3, 8, [bytes(2)] * 2)
        self.assertIn("PLTE", self.info(no_plte)[0])
        self.assertIn("팔레트에 없는 색 번호", self.info(make_png(2, 1, 3, 8, [bytes([0, 5])], plte=bytes(6)))[0])
        # 압축 자료가 짧거나 길다 / 압축이 깨졌다
        head = dk.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
        short = head + chunk(b"IDAT", zlib.compress(bytes(9))) + chunk(b"IEND", b"")
        self.assertIn("모자라요", self.info(short)[0])
        long = head + chunk(b"IDAT", zlib.compress(bytes(1000))) + chunk(b"IEND", b"")
        self.assertIn("길어요", self.info(long)[0])
        junk = head + chunk(b"IDAT", b"not-zlib-data") + chunk(b"IEND", b"")
        self.assertIn("압축이 깨져", self.info(junk)[0])
        bad_filter = head + chunk(b"IDAT", zlib.compress(bytes([9]) + bytes(8) + bytes([9]) + bytes(8))) + chunk(b"IEND", b"")
        self.assertIn("필터", self.info(bad_filter)[0])
        # 줄 필터를 풀지 못한 채로는 절대 통과하지 않는다: 첫 조각이 IHDR가 아니면 거부
        self.assertIn("IHDR", self.info(dk.PNG_SIG + chunk(b"IDAT", b"") + chunk(b"IEND", b""))[0])

    def test_time_budget(self):
        rows = [bytes(64)] * 64
        with mock.patch.object(dk, "TIME_BUDGET", -1.0):
            text, err = self.info(make_png(16, 64, 6, 8, rows))
        self.assertTrue(err)
        self.assertIn("시간 안에", text)


class ServerIntegration(unittest.TestCase):
    def test_initialize_list_and_call_every_tool(self):
        srv = dk.build()
        init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})["result"]
        self.assertEqual(init["serverInfo"]["name"], "design-kit")
        self.assertEqual(init["protocolVersion"], "2025-06-18")
        self.assertIn("읽기만", init["instructions"])
        self.assertIsNone(srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        listed = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual([t["name"] for t in listed], TOOLS)
        for t in listed:
            self.assertTrue(t["annotations"]["readOnlyHint"], t["name"])
            self.assertRegex(t["description"], "[가-힣]")
            self.assertLessEqual(len(t["description"]), 320, t["name"])
            self.assertEqual(t["inputSchema"]["additionalProperties"], False)
        schemas = {t["name"]: t["inputSchema"] for t in listed}
        self.assertEqual(schemas["palette"]["required"], ["base", "scheme"])
        self.assertEqual(schemas["palette"]["properties"]["scheme"]["enum"], ["mono", "analogous", "complementary", "triad", "split"])
        self.assertEqual(schemas["contrast_table"]["properties"]["colors"]["minItems"], 2)
        self.assertEqual(schemas["contrast_table"]["properties"]["colors"]["maxItems"], 12)
        with tempfile.TemporaryDirectory(prefix="ais-dk-") as d:
            png = Path(d) / "a.png"
            png.write_bytes(make_png(1, 1, 6, 8, [bytes([1, 2, 3, 255])]))
            srv = dk.build(cwd=Path(d))
            samples = {"color": {"value": "#336699"}, "contrast": {"fg": "#000", "bg": "#fff"}, "contrast_table": {"colors": ["#000", "#fff"]},
                       "palette": {"base": "#336699", "scheme": "split", "mode": "dark"}, "scale": {"kind": "type", "base": 16},
                       "text_fit": {"text": "안녕", "font_px": 16, "box_width": 100}, "grid": {"width": 100, "columns": 4, "gutter": 4, "margin": 2},
                       "image_info": {"path": str(png)}}
            self.assertEqual(sorted(samples), sorted(TOOLS))
            for name, args in samples.items():
                text, err = call(srv, name, **args)
                self.assertFalse(err, (name, text))
                self.assertTrue(text.strip())
                self.assertTrue(call(srv, name, **{**args, "bogus": 1})[1], "모르는 입력은 거절")
                self.assertTrue(call(srv, name)[1], "빠진 입력은 거절")
        self.assertTrue(call(srv, "no_such_tool")[1])

    def test_no_network_environment_or_subprocess(self):
        for name in ("os", "subprocess", "socket", "urllib", "http", "ssl", "shutil", "tempfile"):
            self.assertNotIn(name, vars(dk), f"{name}을(를) 쓰지 않는다")
        source = Path(dk.__file__).read_text(encoding="utf-8")
        for word in ("environ", "getenv", "subprocess", "socket", "urlopen", "open(", ".write", "unlink", "rmdir", "rename"):
            if word == "open(":
                self.assertEqual(source.count("open("), source.count(".open(\"rb\")"), "파일은 읽기 전용(rb)으로만 연다")
            else:
                self.assertNotIn(word, source, word)
        raw = Path(dk.__file__).read_bytes()
        self.assertEqual((raw.count(b"\r\n"), raw.count(bytes(1)), raw[:3] == b"\xef\xbb\xbf"), (0, 0, False), "LF, 널 문자·BOM 없음")

    def test_runs_over_stdio_with_allow_folders(self):
        with tempfile.TemporaryDirectory(prefix="ais-dk-") as d:
            root = Path(d).resolve()
            for name in ("cwd", "allowed", "denied"):
                (root / name).mkdir()
            png = make_png(1, 2, 6, 8, [bytes([9, 8, 7, 255]), bytes([9, 8, 7, 255])])
            for name in ("allowed", "denied"):
                (root / name / "a.png").write_bytes(png)
            script = Path(dk.__file__)
            lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                     {"jsonrpc": "2.0", "method": "notifications/initialized"},
                     {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                     {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "image_info", "arguments": {"path": str(root / "allowed" / "a.png")}}},
                     {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "image_info", "arguments": {"path": str(root / "denied" / "a.png")}}},
                     {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "contrast", "arguments": {"fg": "#777777", "bg": "#ffffff"}}}]
            done = subprocess.run([sys.executable, str(script), "--allow", str(root / "allowed"), "--allow", str(root / "missing")], cwd=root / "cwd",
                                  input="\n".join(json.dumps(x) for x in lines) + "\n", capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            answers = {a["id"]: a for a in (json.loads(x) for x in done.stdout.splitlines())}
            self.assertEqual([t["name"] for t in answers[2]["result"]["tools"]], TOOLS)
            self.assertFalse(answers[3]["result"]["isError"], answers[3])
            self.assertIn("크기: 1 × 2 픽셀", answers[3]["result"]["content"][0]["text"])
            self.assertTrue(answers[4]["result"]["isError"])
            self.assertIn("볼 수 없어요", answers[4]["result"]["content"][0]["text"])
            self.assertIn("4.48 : 1", answers[5]["result"]["content"][0]["text"])
            self.assertEqual(done.stderr.strip(), "")


if __name__ == "__main__":
    unittest.main()
