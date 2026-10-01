"""꾸미기 공방(예전 의상 제조실): 새 모습 주문 → 그림 3장(가짜 실행기) → Godot 도구로 자르기 → 미리보기 → 승인하면 설치·입히기.

실제 Godot 도구를 돌린다 (없으면 건너뜀). 그림 생성은 가짜 실행기가 '여름 옷' 그림을 새 옷처럼 돌려준다.
"""

import shutil
import unittest
from pathlib import Path

from tests.helpers import ROOT, TempStudio, default_behavior
from studio import company, wardrobe
from studio.config import load_config
from studio.engine import EngineError
from studio.util import read_json

GODOT = load_config(ROOT).godot_path()


class Wardrobe(unittest.TestCase):
    def setUp(self):
        if not GODOT or not Path(GODOT).is_file():
            self.skipTest("Godot이 없어 건너뜀")
        self.s = TempStudio()
        root = self.s.root
        shutil.copytree(ROOT / "tools" / "sprites", root / "tools" / "sprites", ignore=shutil.ignore_patterns(".godot"))
        (root / "assets-raw" / "looks" / "summer").mkdir(parents=True)
        for name in ("char-sol.png", "walk-sol.png"):
            shutil.copyfile(ROOT / "assets-raw" / name, root / "assets-raw" / name)
            shutil.copyfile(ROOT / "assets-raw" / "looks" / "summer" / name, root / "assets-raw" / "looks" / "summer" / name)
        (root / "ui" / "assets" / "sprites").mkdir(parents=True)
        for name in ("portraits.png", "portraits.json"):
            shutil.copyfile(ROOT / "ui" / "assets" / name, root / "ui" / "assets" / name)
        for name in ("index.json", "parts.json"):
            shutil.copyfile(ROOT / "ui" / "assets" / "sprites" / name, root / "ui" / "assets" / "sprites" / name)
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine
        self.cfg.tools["godot"] = GODOT
        self.prompts = []
        self.s.behavior = self.behavior

    def tearDown(self):
        if hasattr(self, "s"):
            self.s.close()

    def behavior(self, spec, runtime=None):
        if spec.want_image:
            self.prompts.append((spec.run_id, runtime, spec.model, spec.prompt, [Path(i).name for i in spec.images]))
            ref = Path(spec.images[0])
            summer = self.s.root / "assets-raw" / "looks" / "summer" / ref.name
            return {"images": [str(summer if summer.is_file() else ref)]}
        return default_behavior(spec)

    def test_order_make_approve(self):
        with self.assertRaises(EngineError):
            self.e.order_outfit("builder", "", "코트")
        with self.assertRaises(EngineError):
            self.e.order_outfit("nobody", "코트", "코트")
        t = self.e.order_outfit("builder", "겨울 코트", "남색 겨울 코트와\n회색 목도리")
        self.assertEqual((t.kind, t.role, t.extra["set"], t.brief), ("look", "builder", f"sol-{t.id.lower()}", "남색 겨울 코트와 회색 목도리"))
        self.assertEqual(self.e._next_job().id, t.id)
        self.e._run_look(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        # 그림 3장: 동작 시트(기본 시트 EDIT) → 걷기(기본 걷기 + 새 시트) → 얼굴(얼굴 참고 + 새 시트), 모두 Codex
        self.assertEqual([p[0].rsplit("-", 1)[-1] for p in self.prompts], ["sheet", "walk", "face"])
        self.assertTrue(all(p[1] == "codex" and p[2] == wardrobe.IMAGE_MODEL for p in self.prompts))
        self.assertEqual(self.prompts[1][4], ["walk-sol.png", "char-sol.png"])
        self.assertEqual(self.prompts[2][4], ["face-ref.png", "char-sol.png"])
        self.assertIn("남색 겨울 코트", self.prompts[0][3])
        set_name = t.extra["set"]
        for name in t.proposal["preview"].values():
            self.assertTrue(wardrobe.preview_file(self.cfg, t.id, name).is_file(), name)
        with self.assertRaises(wardrobe.WardrobeError):
            wardrobe.preview_file(self.cfg, t.id, "../../studio.toml")
        # 승인 전에는 꾸미기에 없다
        self.assertNotIn(set_name, company.look_sets(self.cfg).get("sol", {}))
        self.assertIn("새 옷이 나왔어요! 입어 볼까요?", [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])

        self.e.approve(t.id)
        # 설치한 그림은 실행 데이터 폴더(data/assets)에 들어가고, 화면은 배포 목록과 합쳐 읽는다 (자세한 것은 test_assets.py)
        index = wardrobe.sprite_index(self.cfg)
        who = f"sol@{set_name}"
        for action in wardrobe.ACTIONS:
            self.assertIn(f"{who}.{action}", index)
            self.assertEqual(index[f"{who}.{action}"]["dir"], "custom/sprites/")
            self.assertTrue((wardrobe.sprites_dir(self.cfg) / index[f"{who}.{action}"]["file"]).is_file())
        self.assertIn("sol.step", index, "원래 그림 목록은 그대로")
        self.assertEqual(company.look_sets(self.cfg)["sol"][set_name], "겨울 코트")
        self.assertEqual(wardrobe.faces(self.cfg)[who], {"file": f"custom/portraits@{set_name}.png", "col": 0, "cols": 1})
        self.assertEqual(company.looks(self.cfg, self.store)["builder"]["style"], set_name, "승인하면 바로 입는다")
        self.assertEqual(self.store.get(t.id).status, "done")
        self.assertIn("새 옷 '겨울 코트' 입었어요!", [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])

    def test_kinds_build_on_the_worn_look(self):
        """꾸미기 공방: 지금 입은 모습에서 한 가지만 바꾼다 (옷 → 그 위에 안경 → 그 위에 체형). 체형은 키를 맞추지 않는다."""
        coat = self.e.order_outfit("builder", "겨울 코트", "남색 코트")
        self.e._run_look(self.store.get(coat.id))
        self.e.approve(coat.id)
        coat_set = coat.extra["set"]
        self.assertTrue((wardrobe.set_raw_dir(self.cfg, coat_set) / "char-sol.png").is_file(), "원본을 남겨 다음 꾸미기의 바탕으로")
        self.assertEqual(read_json(self.cfg.data_dir / "wardrobe.json", {})["looks"][coat_set]["kind"], "outfit")

        glasses = self.e.order_outfit("builder", "동그란 안경", "동그란 금테 안경", kind="accessory")
        self.assertEqual((glasses.extra["look_kind"], glasses.extra["base"]), ("accessory", coat_set))
        self.assertTrue(glasses.title.endswith("새 안경·소품: 동그란 안경"))
        self.e._run_look(self.store.get(glasses.id))
        g = self.store.get(glasses.id)
        self.assertEqual(g.status, "awaiting_approval", g.blocked_reason)
        self.assertIn("ADD ONLY this accessory", self.prompts[-3][3])
        self.assertIn("Change ONLY the accessory", self.prompts[-2][3])
        job = read_json(wardrobe.job_dir(self.cfg, g.id) / "job.json", {})
        new_body = next(x for x in job["sheets"] if x["character"] == f"sol@{g.extra['set']}" and "matchHeightOf" not in x)
        self.assertEqual(new_body["scaleTo"], f"sol@{coat_set}.step", "바탕 모습의 키에 맞춘다")
        self.assertIn(f"새 안경·소품이 나왔어요! 볼까요?", [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])
        self.e.approve(g.id)
        self.assertEqual(company.looks(self.cfg, self.store)["builder"]["style"], g.extra["set"])

        tall = self.e.order_outfit("builder", "키 큰 체형", "지금보다 키가 조금 큰 체형", kind="body")
        self.assertEqual(tall.extra["base"], g.extra["set"])
        self.e._run_look(self.store.get(tall.id))
        job = read_json(wardrobe.job_dir(self.cfg, tall.id) / "job.json", {})
        new_body = next(x for x in job["sheets"] if x["character"] == f"sol@{tall.extra['set']}" and "matchHeightOf" not in x)
        self.assertNotIn("scaleTo", new_body, "체형은 키를 맞추지 않는다")
        self.assertEqual(self.e.order_outfit("builder", "모자", "모자", kind="nope").extra["look_kind"], "outfit")

    def test_redo_with_note(self):
        t = self.e.order_outfit("builder", "겨울 코트", "남색 코트")
        self.e._run_look(self.store.get(t.id))
        self.e.request_changes(t.id, "단추를 금색으로")
        self.assertEqual(self.store.get(t.id).status, "queued")
        self.e._run_look(self.store.get(t.id))
        self.assertIn("CEO note: 단추를 금색으로", self.prompts[-1][3])
        self.assertEqual(self.store.get(t.id).status, "awaiting_approval")

    def test_image_failure_blocks(self):
        self.s.behavior = lambda spec, runtime=None: {"images": []} if spec.want_image else default_behavior(spec)
        t = self.e.order_outfit("builder", "코트", "코트")
        self.e._run_look(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "blocked")


if __name__ == "__main__":
    unittest.main()
