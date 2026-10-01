"""설치한 그림의 저장 위치와 꾸미기 ✕, 연습용 색 바꾸기 (SPEC '설치한 그림 메모').

- 승인한 옷·새 직원 그림은 실행 데이터 폴더 data/assets에만 쓴다 (프로그램 폴더 ui/·assets-raw/는 그대로).
- 화면이 읽는 그림 목록·얼굴 목록은 배포 것과 설치한 것을 합친 것이다. 예전 위치의 원본도 찾는다.
- 꾸미기 옷 ✕: 공방에서 만든 옷은 휴지통으로, 배포 옷은 그 직원 목록에서 숨긴다 (되살릴 수 있다).
- 연습용(--fake) 회사에서만 가짜 그림의 옷 색을 돌린다.

실제 Godot 도구를 돌린다 (없으면 건너뜀). 그림 생성은 가짜 실행기가 '여름 옷' 그림을 새 옷처럼 돌려준다.
"""

import colorsys
import shutil
import struct
import unittest
import zlib
from pathlib import Path

from tests.helpers import ROOT, TempStudio, default_behavior
from studio import company, wardrobe
from studio.config import load_config
from studio.engine import EngineError
from studio.runtimes import FakeRuntime, default_fake_behavior
from studio.util import read_json

GODOT = load_config(ROOT).godot_path()


def have_godot() -> bool:
    return bool(GODOT) and Path(GODOT).is_file()


def snapshot(folder: Path) -> dict:
    """폴더 안 모든 파일의 (크기, 수정 시각). 설치가 이 폴더를 건드렸는지 비교한다."""
    return {p.relative_to(folder).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.rglob("*") if p.is_file()}


def write_png(path: Path, rows: list[list[tuple]]) -> None:
    """8비트 RGBA PNG (필터 없음). 작은 시험 그림용."""
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    head = struct.pack(">IIBBBBB", len(rows[0]), len(rows), 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def read_png(path: Path) -> list[list[tuple]]:
    """8비트 RGBA PNG (모든 필터) → 줄마다 (r, g, b, a) 목록. 작은 그림만 읽는다."""
    data, pos, idat = path.read_bytes(), 8, b""
    while pos < len(data):
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + size]
        pos += 12 + size
        if kind == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            idat += body
    assert (depth, ctype) == (8, 6), "8비트 RGBA만 읽는다"
    raw, stride, prev, rows = zlib.decompress(idat), w * 4, bytearray(w * 4), []
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - 4] if i >= 4 else 0
            b = prev[i]
            c = prev[i - 4] if i >= 4 else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append([tuple(line[x * 4:x * 4 + 4]) for x in range(w)])
        prev = line
    return rows


def hsv(px: tuple) -> tuple[float, float, float]:
    h, s, v = colorsys.rgb_to_hsv(px[0] / 255, px[1] / 255, px[2] / 255)
    return h * 360, s, v


def from_hsv(h: float, s: float, v: float) -> tuple:
    return tuple(round(c * 255) for c in colorsys.hsv_to_rgb(h / 360, s, v)) + (255,)


class Fixture(unittest.TestCase):
    need_godot = True

    def setUp(self):
        if self.need_godot and not have_godot():
            self.skipTest("Godot이 없어 건너뜀")
        self.s = TempStudio()
        root = self.s.root
        shutil.copytree(ROOT / "tools" / "sprites", root / "tools" / "sprites", ignore=shutil.ignore_patterns(".godot"))
        (root / "assets-raw" / "looks" / "summer").mkdir(parents=True)
        for name in ("char-sol.png", "walk-sol.png"):
            shutil.copyfile(ROOT / "assets-raw" / name, root / "assets-raw" / name)
            shutil.copyfile(ROOT / "assets-raw" / "looks" / "summer" / name, root / "assets-raw" / "looks" / "summer" / name)
        (root / "ui" / "assets" / "sprites").mkdir(parents=True)
        for name in ("portraits.png", "portraits.json", "portraits@summer.png", "portraits@summer.json"):  # 여름 옷 얼굴: 배포 세트 원본 찾기
            shutil.copyfile(ROOT / "ui" / "assets" / name, root / "ui" / "assets" / name)
        for name in ("index.json", "parts.json"):
            shutil.copyfile(ROOT / "ui" / "assets" / "sprites" / name, root / "ui" / "assets" / "sprites" / name)
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine
        self.cfg.tools["godot"] = GODOT
        self.s.behavior = self.behavior

    def tearDown(self):
        if hasattr(self, "s"):
            self.s.close()

    def behavior(self, spec, runtime=None):
        if spec.want_image:
            ref = Path(spec.images[0])
            summer = self.s.root / "assets-raw" / "looks" / "summer" / ref.name
            return {"images": [str(summer if summer.is_file() else ref)]}
        return default_behavior(spec)

    def make_look(self, label="겨울 코트", desc="남색 코트"):
        t = self.e.order_outfit("builder", label, desc)
        self.e._run_look(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.e.approve(t.id)
        return self.store.get(t.id)


class Installed(Fixture):
    def test_look_install_writes_only_data_assets(self):
        ui_before, raw_before = snapshot(self.s.root / "ui"), snapshot(self.s.root / "assets-raw")
        version = wardrobe.sprite_version(self.cfg)
        t = self.make_look()
        set_name, who = t.extra["set"], f"sol@{t.extra['set']}"
        # 프로그램 폴더(ui/·assets-raw/)는 한 파일도 바뀌지 않았다
        self.assertEqual(snapshot(self.s.root / "ui"), ui_before)
        self.assertEqual(snapshot(self.s.root / "assets-raw"), raw_before)
        assets = wardrobe.assets_dir(self.cfg)
        self.assertEqual(assets, self.cfg.data_dir / "assets")
        # 설치한 목록에는 이 옷 것만, 그림 위치(dir)와 함께
        custom = read_json(assets / "index.json", {})
        self.assertEqual({k.split(".")[0] for k in custom}, {who})
        for action in wardrobe.ACTIONS:
            meta = custom[f"{who}.{action}"]
            self.assertEqual(meta["dir"], "custom/sprites/")
            for name in (meta["file"], meta["mask"], meta["file"].replace(".strip.png", ".strip.json")):
                self.assertTrue((assets / "sprites" / name).is_file(), name)
        self.assertIn(who, read_json(assets / "parts.json", {}))
        for suffix in (".png", ".json"):
            self.assertTrue((assets / f"portraits@{set_name}{suffix}").is_file(), suffix)
        self.assertTrue((assets / "raw" / "looks" / set_name / "char-sol.png").is_file())
        # 합친 목록: 배포(dir 없음) + 설치
        merged = wardrobe.sprite_index(self.cfg)
        self.assertIn("sol.step", merged)
        self.assertNotIn("dir", merged["sol.step"])
        self.assertEqual(merged[f"{who}.step"]["dir"], "custom/sprites/")
        self.assertIn(who, wardrobe.sprite_parts(self.cfg))
        self.assertIn("sol", wardrobe.sprite_parts(self.cfg))
        self.assertEqual(company.look_sets(self.cfg)["sol"][set_name], "겨울 코트")
        # 얼굴 목록: 배포는 그대로, 설치한 것은 custom/ 아래
        faces = wardrobe.faces(self.cfg)
        self.assertEqual(faces["sol"]["file"], "portraits.png")
        self.assertEqual(faces[who], {"file": f"custom/portraits@{set_name}.png", "col": 0, "cols": 1})
        # 그림 목록 버전은 설치 목록이 바뀌면 바뀐다
        self.assertNotEqual(wardrobe.sprite_version(self.cfg), version)
        self.assertEqual(company.look_options(self.cfg)["version"], wardrobe.sprite_version(self.cfg))
        # 이 옷 위에 또 꾸미기: 새 위치의 원본과 얼굴을 바탕으로 쓴다
        src = wardrobe.sources(self.cfg, "sol", set_name)
        self.assertEqual(src["body"]["file"], (assets / "raw" / "looks" / set_name / "char-sol.png").relative_to(self.s.root).as_posix())
        self.assertEqual(src["face_atlas"], f"data/assets/portraits@{set_name}.png")

    def test_old_locations_are_still_found(self):
        """예전에 설치한 옷(assets-raw/looks/<세트>)·더 예전 작업 폴더의 원본도 바탕으로 찾는다."""
        t = self.make_look()
        set_name = t.extra["set"]
        new_dir = wardrobe.set_raw_dir(self.cfg, set_name)
        old_dir = self.s.root / "assets-raw" / "looks" / set_name
        shutil.copytree(new_dir, old_dir)
        shutil.rmtree(new_dir)
        src = wardrobe.sources(self.cfg, "sol", set_name)
        self.assertEqual(src["body"]["file"], f"assets-raw/looks/{set_name}/char-sol.png")
        # 그것도 없으면 작업 폴더(data/looks/<작업>/raw/)
        shutil.rmtree(old_dir)
        src = wardrobe.sources(self.cfg, "sol", set_name)
        self.assertEqual(src["body"]["file"], f"data/looks/{t.id}/raw/char-sol.png")
        # 배포 세트(여름 옷)는 예전 그대로 assets-raw/looks/summer
        self.assertEqual(wardrobe.sources(self.cfg, "sol", "summer")["body"]["file"], "assets-raw/looks/summer/char-sol.png")
        # 모두 없으면 쉬운 말로 거절
        shutil.rmtree(wardrobe.job_dir(self.cfg, t.id) / "raw")
        with self.assertRaises(wardrobe.WardrobeError):
            wardrobe.sources(self.cfg, "sol", set_name)

    def test_hire_installs_into_data_assets(self):
        ui_before, raw_before = snapshot(self.s.root / "ui"), snapshot(self.s.root / "assets-raw")
        t = self.e.hire({"name": "미나", "job": "builder", "looks": "짧은 분홍 머리, 초록 후드티"})
        self.e._run_hire(self.store.get(t.id))
        self.assertEqual(self.store.get(t.id).status, "awaiting_approval", self.store.get(t.id).blocked_reason)
        self.e.approve(t.id)
        self.assertEqual(snapshot(self.s.root / "ui"), ui_before)
        self.assertEqual(snapshot(self.s.root / "assets-raw"), raw_before)
        assets = wardrobe.assets_dir(self.cfg)
        custom = read_json(assets / "index.json", {})
        self.assertEqual({k.split(".")[0] for k in custom}, {"staff1"})
        self.assertTrue(all(m["dir"] == "custom/sprites/" for m in custom.values()))
        self.assertTrue((assets / "portraits+staff1.png").is_file())
        self.assertEqual(wardrobe.faces(self.cfg)["staff1"], {"file": "custom/portraits+staff1.png", "col": 0, "cols": 1})
        for name in ("char-staff1.png", "walk-staff1.png"):
            self.assertTrue((assets / "raw" / "chars" / "staff1" / name).is_file(), name)
        src = wardrobe.base_sources(self.cfg, "staff1")
        self.assertEqual(src["body"]["file"], "data/assets/raw/chars/staff1/char-staff1.png")
        self.assertEqual(src["face_atlas"], "data/assets/portraits+staff1.png")
        # 예전 위치(assets-raw/chars/<키>)에 있으면 거기서도 찾는다
        old = self.s.root / "assets-raw" / "chars" / "staff1"
        shutil.copytree(assets / "raw" / "chars" / "staff1", old)
        shutil.rmtree(assets / "raw" / "chars" / "staff1")
        self.assertEqual(wardrobe.base_sources(self.cfg, "staff1")["body"]["file"], "assets-raw/chars/staff1/char-staff1.png")
        # 새 직원 키는 두 위치 모두 겹치지 않게 (지금 있는 staff1은 건너뛴다)
        self.assertEqual(self.e.hire({"name": "도윤", "job": "analyst", "looks": "안경"}).extra["key"], "staff2")

    def test_remove_made_look(self):
        t = self.make_look()
        set_name, who = t.extra["set"], f"sol@{t.extra['set']}"
        self.assertEqual(company.looks(self.cfg, self.store)["builder"]["style"], set_name, "승인하면 입는다")
        assets = wardrobe.assets_dir(self.cfg)
        self.assertEqual(company.look_options(self.cfg)["made"], [set_name])
        # 그 옷을 바탕으로 새 모습을 만드는 중(결재 전)이면 지우지 않는다
        glasses = self.e.order_outfit("builder", "동그란 안경", "동그란 금테 안경", kind="accessory")
        self.assertEqual(glasses.extra["base"], set_name)
        with self.assertRaises(EngineError) as err:
            self.e.remove_look("builder", set_name)
        self.assertIn("만드는 중", str(err.exception))
        self.assertIn(set_name, wardrobe.made_sets(self.cfg))
        self.assertTrue((assets / f"portraits@{set_name}.png").is_file())
        self.e.cancel(glasses.id)
        # 다른 직원의 옷·기본·없는 옷·이상한 이름은 거절
        for role, name in (("producer", set_name), ("builder", "base"), ("builder", ""), ("builder", "nope"), ("nobody", set_name),
                           ("builder", "../x"), ("builder", "a/b")):
            with self.assertRaises(EngineError, msg=(role, name)):
                self.e.remove_look(role, name)

        res = self.e.remove_look("builder", set_name)
        self.assertEqual((res["removed"], res["hidden"]), (True, False))
        # 휴지통으로 (띠·표시·얼굴·원본), 설치한 곳에는 남지 않는다
        trash = list((self.cfg.data_dir / "trash" / "looks").glob(f"{set_name}-*"))
        self.assertEqual(len(trash), 1)
        self.assertTrue((trash[0] / "sprites" / f"{who}.step.strip.png").is_file())
        self.assertTrue((trash[0] / "sprites" / f"{who}.step.mask.png").is_file())
        self.assertTrue((trash[0] / f"portraits@{set_name}.png").is_file())
        self.assertTrue((trash[0] / "raw" / "char-sol.png").is_file())
        self.assertEqual([p.name for p in (assets / "sprites").glob(f"{who}.*")], [])
        self.assertFalse((assets / f"portraits@{set_name}.png").exists())
        self.assertFalse((assets / "raw" / "looks" / set_name).exists())
        # 목록에서 빠진다 (설치 목록·색 통계·이름·얼굴·꾸미기 선택지)
        self.assertEqual([k for k in wardrobe.sprite_index(self.cfg) if k.startswith(who + ".")], [])
        self.assertIn("sol.step", wardrobe.sprite_index(self.cfg), "배포 그림은 그대로")
        self.assertNotIn(who, wardrobe.sprite_parts(self.cfg))
        self.assertNotIn(who, wardrobe.faces(self.cfg))
        self.assertNotIn(set_name, wardrobe.labels(self.cfg))
        self.assertNotIn(set_name, company.look_sets(self.cfg)["sol"])
        self.assertEqual(company.look_options(self.cfg)["made"], [])
        # 입고 있던 옷이라 기본으로 돌아간다
        self.assertEqual(company.looks(self.cfg, self.store)["builder"]["style"], "base")
        self.assertEqual(self.store.read_doc("looks", {})["builder"]["style"], "base")
        self.assertIn("look.removed", [e["type"] for e in self.store.recent_events(50)])
        with self.assertRaises(EngineError):
            self.e.remove_look("builder", set_name)


class Shipped(Fixture):
    """배포 옷(여름 옷)은 지우지 않고 그 직원 목록에서 숨긴다."""

    need_godot = False

    def test_hide_and_restore(self):
        self.assertEqual(company.look_sets(self.cfg)["sol"]["summer"], "여름 옷")
        self.assertEqual(company.look_options(self.cfg)["hidden"], {})
        company.save_look(self.cfg, self.store, "builder", {"style": "summer", "hair": "blonde"})
        self.assertEqual(company.looks(self.cfg, self.store)["builder"]["style"], "summer")
        before = snapshot(self.s.root / "ui")

        res = self.e.remove_look("builder", "summer")
        self.assertEqual((res["removed"], res["hidden"]), (False, True))
        self.assertNotIn("summer", company.look_sets(self.cfg)["sol"])
        self.assertIn("summer", company.look_sets(self.cfg)["hana"], "다른 직원의 여름 옷은 그대로")
        self.assertEqual(company.look_options(self.cfg)["hidden"], {"sol": {"summer": "여름 옷"}})
        self.assertEqual(read_json(self.cfg.data_dir / "wardrobe.json", {})["hidden"], {"sol": ["summer"]})
        # 입고 있던 옷이라 기본으로 (머리색은 그대로), 그림 파일은 그대로 (지우지 않는다)
        self.assertEqual(self.store.read_doc("looks", {})["builder"], {"style": "base", "hair": "blonde", "outfit": "base", "height": 0, "head": 0, "build": 0, "shoulders": 0, "chest": 0, "waist": 0, "hips": 0, "hair_volume": 0})
        self.assertEqual(snapshot(self.s.root / "ui"), before)
        self.assertTrue((self.s.root / "assets-raw" / "looks" / "summer" / "char-sol.png").is_file())
        self.assertFalse((self.cfg.data_dir / "trash").exists())
        self.assertIn("sol@summer.step", wardrobe.sprite_index(self.cfg), "그림 목록에서도 그대로")
        # 숨긴 옷으로는 저장할 수 없다 (허용 목록 밖은 기본)
        self.assertEqual(company.clean_look(self.cfg, "sol", {"style": "summer"})["style"], "base")
        self.assertIn("look.hidden", [e["type"] for e in self.store.recent_events(50)])
        # 되살리기
        self.e.restore_look("builder", "summer")
        self.assertIn("summer", company.look_sets(self.cfg)["sol"])
        self.assertEqual(company.look_options(self.cfg)["hidden"], {})
        self.assertEqual(read_json(self.cfg.data_dir / "wardrobe.json", {}).get("hidden"), {})
        self.assertEqual(company.clean_look(self.cfg, "sol", {"style": "summer"})["style"], "summer")
        with self.assertRaises(EngineError):
            self.e.restore_look("builder", "summer")  # 숨긴 옷이 아니다
        with self.assertRaises(EngineError):
            self.e.restore_look("builder", "nope")

    def test_not_wearing_stays(self):
        """입고 있지 않은 옷을 숨겨도 지금 옷은 그대로."""
        company.save_look(self.cfg, self.store, "analyst", {"style": "summer"})
        self.e.remove_look("builder", "summer")
        self.assertEqual(company.looks(self.cfg, self.store)["analyst"]["style"], "summer")


class FakeTint(Fixture):
    def test_tool_turns_only_the_outfit(self):
        """색 규칙이 있으면 그 규칙의 픽셀만, 없으면 (채도 높고 피부·갈색이 아닌) 픽셀만 돌린다. 배경·머리는 그대로."""
        magenta, blue, brown = (255, 0, 255, 255), from_hsv(215, 0.8, 0.9), from_hsv(20, 0.7, 0.5)
        original = [[magenta] * 8 + [blue] * 8 + [brown] * 8 for _ in range(4)]
        for base_set in (None, "sol-t0001"):  # None: sol의 색 규칙 / 세트 위에 꾸민 모습: 자동
            png = self.s.root / f"tint-{base_set}.png"
            write_png(png, original)
            ok, log = wardrobe.fake_tint(self.cfg, "T0007", "sol", base_set, png)
            self.assertTrue(ok, log)
            after = read_png(png)
            self.assertEqual(after[0][:8], [magenta] * 8, "배경은 그대로")
            self.assertEqual(after[0][16:], [brown] * 8, "머리색은 그대로")
            moved = hsv(after[0][8])
            turn = abs(moved[0] - 215) % 360
            self.assertGreater(min(turn, 360 - turn), 20, f"옷 색이 돌아갔다 ({moved})")
            self.assertTrue(55 <= moved[0] < 265,
                            f"자홍 배경·피부와 헷갈리는 색으로는 돌리지 않는다 (다음 주문 때도 색이 바뀌게) ({moved})")
            self.assertAlmostEqual(moved[1], 0.8, delta=0.05)
            self.assertAlmostEqual(moved[2], 0.9, delta=0.05)
            self.assertFalse((self.s.root / f"tint-{base_set}.tint.png").exists(), "임시 그림은 남기지 않는다")

    def test_repeat_orders_keep_changing_color(self):
        """돌린 옷 색은 언제나 노랑~파랑(55~265도)이라, 같은 사람에게 이어서 주문해도 자동 규칙이 피부·갈색으로 오해하지 않아 매번 색이 바뀐다."""
        magenta, brown = (255, 0, 255, 255), from_hsv(20, 0.7, 0.5)
        png = self.s.root / "tint-chain.png"
        write_png(png, [[magenta] * 4 + [from_hsv(215, 0.8, 0.9)] * 4 + [brown] * 4 for _ in range(2)])
        before = 215.0
        for n in range(1, 8):  # 주문 번호마다 돌리는 각도가 다르다 (T0001~T0007)
            ok, log = wardrobe.fake_tint(self.cfg, f"T{n:04d}", "staff1", None, png)  # 규칙 없는 새 직원: 자동
            self.assertTrue(ok, log)
            row = read_png(png)[0]
            self.assertEqual(row[8:], [brown] * 4, "머리색은 그대로")
            moved = hsv(row[4])[0]
            self.assertTrue(55 <= moved < 265, f"T{n:04d}: 피부·자홍과 헷갈리는 색으로 돌렸다 ({moved})")
            turn = abs(moved - before) % 360
            self.assertGreater(min(turn, 360 - turn), 20, f"T{n:04d}: 옷 색이 안 바뀌었다 ({before} → {moved})")
            before = moved

    def test_hue_differs_by_task(self):
        hues = [wardrobe.fake_hue(f"T{n:04d}") for n in range(1, 21)]
        self.assertTrue(all(30 <= h <= 315 for h in hues), hues)
        self.assertGreaterEqual(len(set(hues)), 8, "주문마다 다르게 보인다")
        self.assertEqual(wardrobe.fake_hue("T0007"), wardrobe.fake_hue("T0007"))

    def test_draw_tints_only_fake_company_results(self):
        ref = self.s.root / "assets-raw" / "char-sol.png"
        original = ref.read_bytes()
        self.s.behavior = lambda spec, runtime=None: default_fake_behavior(spec)  # 가짜 실행기의 기본 동작: 참고 그림을 그대로 돌려준다
        t = self.e.order_outfit("builder", "코트", "남색 코트")
        out = self.s.root / "out"
        out.mkdir()
        count = [0]

        def draw():
            count[0] += 1
            target = out / f"sheet-{count[0]}.png"
            ok = self.e._draw(self.store.get(t.id), "builder", "look", [("sheet", "prompt", [ref], target)])
            self.assertTrue(ok, self.store.get(t.id).blocked_reason)
            return target.read_bytes()

        # 진짜 회사(연습용이 아님)의 그림은 색을 건드리지 않는다
        self.assertFalse(self.cfg.fake_runtimes)
        self.assertEqual(draw(), original)
        # 연습용 회사: 가짜 그림(지금 모습)의 옷 색이 돌아가 원본과 달라진다. 참고 그림 원본은 그대로.
        self.cfg.fake_runtimes = True
        tinted = draw()
        self.assertNotEqual(tinted, original)
        self.assertEqual(ref.read_bytes(), original)
        # 연습용 회사여도 가짜 실행기가 그린 것이 아니면(진짜 Codex·Grok) 쓰지 않는다
        class Real(FakeRuntime):
            name = "codex"

        self.e.runtime_factory = lambda name: Real(lambda spec: default_fake_behavior(spec))
        self.assertEqual(draw(), original)

    def test_fake_company_order_looks_different(self):
        """연습용 회사에서 주문한 새 옷은 그림 3장 모두 옷 색이 돌아가고, 잘라 결재까지 올라간다."""
        self.s.behavior = lambda spec, runtime=None: default_fake_behavior(spec) if spec.want_image else default_behavior(spec)
        self.cfg.fake_runtimes = True
        t = self.e.order_outfit("builder", "코트", "남색 코트")
        self.e._run_look(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        raw = wardrobe.job_dir(self.cfg, t.id) / "raw"
        for name, ref in (("char-sol.png", self.s.root / "assets-raw" / "char-sol.png"), ("walk-sol.png", self.s.root / "assets-raw" / "walk-sol.png")):
            self.assertNotEqual((raw / name).read_bytes(), ref.read_bytes(), name)
        self.assertTrue((raw / "portraits.png").is_file())


if __name__ == "__main__":
    unittest.main()
