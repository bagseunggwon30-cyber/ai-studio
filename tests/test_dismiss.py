"""직원 내보내기 (퇴사, CEO 요청 2026-09-29): 새 직원만, 일하는 중이면 거절, 열린 일은 넘기거나 취소, 기록·그림 정리, 책상이 당겨진다."""

import unittest

from tests.helpers import TempStudio
from studio import company, floors, skills, wardrobe
from studio.config import staff_role
from studio.engine import EngineError
from studio.util import atomic_write_json, read_json


class Dismiss(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine
        self.e.add_floor()
        entries = [{"key": f"staff{i}", "name": name, "job": job, "template": "sol", "memo": "", "skills": []}
                   for i, (name, job) in enumerate([("미나", "builder"), ("다온", "analyst"), ("보리", "builder")], start=1)]
        atomic_write_json(self.cfg.data_dir / "staff.json", {"staff": entries})
        for e in entries:
            self.cfg.roles[e["key"]] = staff_role(self.cfg, e)
        # 미나의 설치된 그림 (띠 하나·얼굴·원본·옷 세트)
        assets = wardrobe.assets_dir(self.cfg)
        (assets / "sprites").mkdir(parents=True)
        for name in ("staff1.step.strip.png", "staff1@staff1-t0009.step.strip.png"):
            (assets / "sprites" / name).write_bytes(b"png")
        atomic_write_json(assets / "index.json", {
            "staff1.step": {"file": "staff1.step.strip.png", "dir": "custom/sprites/"},
            "staff1@staff1-t0009.step": {"file": "staff1@staff1-t0009.step.strip.png", "dir": "custom/sprites/"},
            "staff3.step": {"file": "staff3.step.strip.png", "dir": "custom/sprites/"},
        })
        atomic_write_json(assets / "parts.json", {"staff1@staff1-t0009": {}, "staff3": {}})
        (assets / "portraits+staff1.png").write_bytes(b"png")
        (assets / "raw" / "chars" / "staff1").mkdir(parents=True)
        (assets / "raw" / "chars" / "staff1" / "char-staff1.png").write_bytes(b"png")
        atomic_write_json(self.cfg.data_dir / "wardrobe.json", {"looks": {"staff1-t0009": {"character": "staff1", "label": "코트"}}})

    def tearDown(self):
        self.s.close()

    def test_founders_and_busy_staff_are_refused(self):
        with self.assertRaises(EngineError):
            self.e.dismiss("builder")
        with self.assertRaises(EngineError):
            self.e.dismiss("nobody")
        t = self.e.create_task({"project": "demo", "kind": "build", "title": "만들기", "brief": "b", "acceptance": ["a"]})
        t = self.store.get(t.id)
        t.role = "staff1"
        self.store.save(t)
        self.store.transition(self.store.get(t.id), "running", note="시험")
        with self.assertRaises(EngineError) as err:
            self.e.dismiss("staff1")
        self.assertIn("일하는 중", str(err.exception))
        self.assertIn("staff1", self.cfg.roles)

    def test_dismiss_hands_over_work_and_cleans_up(self):
        seats = floors.seats(self.cfg)
        self.assertEqual((seats["staff1"], seats["staff2"], seats["staff3"]), (4, 5, 6))
        build = self.e.create_task({"project": "demo", "kind": "build", "title": "만들기", "brief": "b", "acceptance": ["a"]})
        build = self.store.get(build.id)
        build.role = "staff1"
        self.store.save(build)
        # 그 직원의 옷 작업 (그림 설정 없이 직접 만든다)
        look = self.store.create_task(title="미나 새 옷", kind="look", role="staff1", project="", status="queued", brief="코트",
                                      extra={"character": "staff1", "label": "코트"}, note="시험")
        sk = self.e.teach_skill({"name": "tidy", "title": "정리", "description": "정리할 때", "body": "짧게", "learned_by": ["staff1", "builder"]})
        company.save_look(self.cfg, self.store, "staff1", {"shoulders": 1})
        saved_ai = self.store.read_doc("ai", {}) or {}
        saved_ai["staff1"] = {"runtime": "codex", "model": "", "effort": ""}
        self.store.write_doc("ai", saved_ai)

        out = self.e.dismiss("staff1")
        self.assertEqual((out["name"], out["cancelled"], out["handed"]), ("미나", 1, 1))
        self.assertNotIn("staff1", self.cfg.roles)
        self.assertEqual(self.store.get(look.id).status, "cancelled", "그 직원의 옷 작업은 취소")
        self.assertIn(self.store.get(build.id).role, ("builder", "staff3"), "개발 일은 다른 개발 직원에게")
        self.assertEqual(skills.get(self.cfg, sk.slug).learned_by, ["builder"])
        self.assertNotIn("staff1", self.store.read_doc("looks", {}))
        self.assertNotIn("staff1", self.store.read_doc("ai", {}) or {})
        reg = read_json(self.cfg.data_dir / "staff.json", {})
        self.assertEqual([e["key"] for e in reg["staff"]], ["staff2", "staff3"])
        self.assertEqual(reg["left"][0]["key"], "staff1")
        self.assertIn("left_at", reg["left"][0])
        self.assertEqual(company.left_staff(self.cfg), {"staff1": {"name": "미나", "job": "builder"}})
        # 그림: 설치 목록에서 빠지고 휴지통으로 (다른 직원 것은 그대로)
        assets = wardrobe.assets_dir(self.cfg)
        index = read_json(assets / "index.json", {})
        self.assertEqual(sorted(index), ["staff3.step"])
        self.assertEqual(sorted(read_json(assets / "parts.json", {})), ["staff3"])
        self.assertFalse((assets / "portraits+staff1.png").exists())
        self.assertFalse((assets / "raw" / "chars" / "staff1").exists())
        trash = list((self.cfg.data_dir / "trash" / "staff").iterdir())
        self.assertEqual(len(trash), 1)
        self.assertTrue((trash[0] / "portraits+staff1.png").is_file())
        self.assertTrue((trash[0] / "sprites" / "staff1.step.strip.png").is_file())
        self.assertNotIn("staff1-t0009", read_json(self.cfg.data_dir / "wardrobe.json", {}).get("looks", {}))
        # 책상이 한 칸씩 당겨진다
        seats = floors.seats(self.cfg)
        self.assertEqual((seats["staff2"], seats["staff3"]), (4, 5))
        # 기록·알림, 키는 다시 쓰지 않는다
        ev = next(e for e in self.store.recent_events(20) if e["type"] == "staff.left")
        self.assertEqual((ev["data"]["name"], ev["data"]["cancelled"]), ("미나", [look.id]))
        alerts = [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())]
        self.assertIn("미나가 회사를 떠났어요. 그동안 고마웠어요!", alerts)
        team = {m["key"] for m in company.team(self.cfg, self.store, self.store.list(), None)}
        self.assertNotIn("staff1", team)

    def test_dismiss_twice_is_refused(self):
        self.e.dismiss("staff2")
        self.assertNotIn("staff2", self.cfg.roles)
        with self.assertRaises(EngineError):
            self.e.dismiss("staff2")


if __name__ == "__main__":
    unittest.main()
