"""캐릭터 제조실: CEO가 새 직원을 만든다 (이름·맡을 일·겉모습 → 그림 3장 → 승인하면 회사에 들어온다).

새 직원은 같은 일을 하는 기본 직원의 권한·AI를 물려받고, 일을 나눠 받는다. 실제 Godot 도구를 돌린다 (없으면 건너뜀).
"""

import shutil
import unittest
from pathlib import Path

from tests.helpers import ROOT, TempStudio, default_behavior
from studio import company, floors, wardrobe
from studio.config import load_config
from studio.engine import EngineError

GODOT = load_config(ROOT).godot_path()


class Hire(unittest.TestCase):
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
            self.prompts.append((spec.run_id, spec.prompt, [Path(i).name for i in spec.images]))
            ref = Path(spec.images[0])
            summer = self.s.root / "assets-raw" / "looks" / "summer" / ref.name
            return {"images": [str(summer if summer.is_file() else ref)]}
        return default_behavior(spec)

    def hire_mina(self, payload=None):
        t = self.e.hire({"name": "미나", "job": "builder", "looks": "짧은 분홍 머리, 초록 후드티", "memo": "잘 부탁해요!", "skills": "Godot, 셰이더"})
        self.e._run_hire(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.e.approve(t.id, payload)
        return t

    def test_hire_flow(self):
        with self.assertRaises(EngineError):
            self.e.hire({"name": "미나", "job": "boss", "looks": "x"})
        with self.assertRaises(EngineError):
            self.e.hire({"name": "", "job": "builder", "looks": "x"})
        with self.assertRaises(EngineError):
            self.e.hire({"name": "솔", "job": "builder", "looks": "x"})  # 같은 이름
        t = self.e.hire({"name": "미나", "job": "builder", "looks": "짧은 분홍 머리, 초록 후드티", "memo": "잘 부탁해요!", "skills": "Godot, 셰이더"})
        self.assertEqual((t.kind, t.extra["key"], t.extra["template"], t.extra["skills"]), ("hire", "staff1", "sol", ["Godot", "셰이더"]))
        self.e._run_hire(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        # 틀(솔)의 시트를 EDIT: 다른 사람을 같은 자세로
        self.assertEqual([p[0].rsplit("-", 1)[-1] for p in self.prompts], ["sheet", "walk", "face"])
        self.assertIn("DIFFERENT, NEW character", self.prompts[0][1])
        self.assertIn("짧은 분홍 머리", self.prompts[0][1])
        self.assertEqual(self.prompts[0][2], ["char-sol.png"])
        for name in t.proposal["preview"].values():
            self.assertTrue(wardrobe.preview_file(self.cfg, t.id, name).is_file(), name)
        self.assertNotIn("staff1", self.cfg.roles, "승인 전에는 회사에 없다")
        self.assertIn("새 직원 그림이 나왔어요! 만나 볼까요?", [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])

        self.e.approve(t.id)
        r = self.cfg.roles["staff1"]
        base = self.cfg.roles["builder"]
        self.assertEqual((r.name, r.job_key, r.character, r.memo, r.skills), ("미나", "builder", "staff1", "잘 부탁해요!", ["Godot", "셰이더"]))
        self.assertEqual((r.sandbox, r.runtime, r.title), (base.sandbox, base.runtime, base.title))
        index = wardrobe.sprite_index(self.cfg)
        for action in wardrobe.ACTIONS:
            self.assertIn(f"staff1.{action}", index)
        self.assertEqual(wardrobe.faces(self.cfg)["staff1"], {"file": "custom/portraits+staff1.png", "col": 0, "cols": 1})
        self.assertTrue((wardrobe.char_dir(self.cfg, "staff1") / "char-staff1.png").is_file(), "원본은 data/assets/raw/chars/에")
        self.assertIn("새 직원 미나가 들어왔어요!", [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])
        team = {m["key"]: m for m in company.team(self.cfg, self.store, self.store.list(), None)}
        self.assertEqual((team["staff1"]["job"], team["staff1"]["name"], team["staff1"]["state"]), ("builder", "미나", "rest"))
        # 다시 켜도 명부에서 읽는다
        self.assertEqual(load_config(self.s.root).roles["staff1"].name, "미나")

    def test_new_staff_inherits_skills_of_the_same_job(self):
        """새 직원은 같은 일을 하는 직원이 배운 스킬을 물려받는다 (기본). 다른 일의 스킬은 받지 않고, CEO가 끌 수 있다."""
        from studio import skills

        build = self.e.teach_skill({"name": "build-tip", "title": "개발 요령", "description": "개발할 때", "body": "본문", "learned_by": ["builder"]})
        review = self.e.teach_skill({"name": "review-tip", "title": "리뷰 요령", "description": "리뷰할 때", "body": "본문", "learned_by": ["reviewer"]})
        t = self.hire_mina()
        self.assertEqual(skills.get(self.cfg, build.slug).learned_by, ["builder", "staff1"])
        self.assertEqual(skills.get(self.cfg, review.slug).learned_by, ["reviewer"], "다른 일의 스킬은 받지 않는다")
        self.assertEqual(self.store.get(t.id).extra["inherited"], [build.slug])
        hired = next(e for e in self.store.recent_events(30) if e["type"] == "staff.hired")
        self.assertEqual(hired["data"]["inherited"], [build.slug])
        self.assertIn("새 직원 미나가 들어왔어요! 스킬 1개를 물려받았어요",
                      [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])
        self.assertIn("build-tip", skills.prompt_block(self.cfg, "staff1"), "물려받은 스킬은 그 직원 프롬프트에 붙는다")

    def test_new_staff_can_skip_inheriting(self):
        from studio import skills

        build = self.e.teach_skill({"name": "build-tip", "title": "개발 요령", "description": "개발할 때", "body": "본문", "learned_by": ["builder"]})
        t = self.hire_mina({"inherit_skills": False})
        self.assertEqual(skills.get(self.cfg, build.slug).learned_by, ["builder"])
        self.assertEqual(self.store.get(t.id).extra["inherited"], [])
        self.assertIn("새 직원 미나가 들어왔어요!", [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])

    def test_work_is_shared_and_reassignable(self):
        self.hire_mina()
        mk = lambda title: self.e.create_task({"project": "demo", "kind": "build", "title": title, "brief": "42", "acceptance": ["a"], "allowed_paths": ["docs/**"]})
        a, b = mk("하나"), mk("둘")
        self.assertEqual((a.role, b.role), ("builder", "staff1"), "일이 적은 쪽에 준다")
        seen = []

        def behavior(spec, runtime=None):
            seen.append((spec.role, spec.prompt))
            return default_behavior(spec)

        self.s.behavior = behavior
        self.e._run_build(self.store.get(b.id))
        builds = [x for x in seen if x[0] == "staff1"]
        self.assertTrue(builds, "미나가 일한다")
        self.assertIn("당신의 이름: 미나", builds[0][1])
        self.assertEqual(self.store.runs(b.id)[0]["role"], "staff1")
        # 담당 바꾸기: 같은 일을 하는 직원에게만
        self.e.assign(a.id, "staff1")
        self.assertEqual(self.store.get(a.id).role, "staff1")
        with self.assertRaises(EngineError):
            self.e.assign(a.id, "reviewer")

    def test_new_staff_can_order_outfit_and_limit(self):
        self.hire_mina()
        t = self.e.order_outfit("staff1", "겨울옷", "남색 코트")
        self.e._run_look(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.assertEqual(self.prompts[-3][2], ["char-staff1.png"], "새 직원 옷의 틀은 자기 그림")
        self.e.approve(t.id)
        self.assertEqual(wardrobe.faces(self.cfg)[f"staff1@{t.extra['set']}"]["file"], f"custom/portraits@{t.extra['set']}.png")
        # 뽑을 수 있는 수는 책상 수 (1층 책상 6 - 기본 직원 4 = 2명). 층을 늘리면 더 뽑을 수 있다.
        for i in range(floors.capacity(self.cfg) - 1):
            self.e.hire({"name": f"직원{i}", "job": "analyst", "looks": "안경"})
        with self.assertRaises(EngineError) as err:
            self.e.hire({"name": "한명더", "job": "analyst", "looks": "안경"})
        self.assertIn("층을 늘리면", str(err.exception))
        self.e.add_floor()
        self.e.hire({"name": "한명더", "job": "analyst", "looks": "안경"})


if __name__ == "__main__":
    unittest.main()
