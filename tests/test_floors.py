"""층 (CEO 결정 2026-09-29): 층 수·책상 수·새 직원 상한·책상 번호, 화면 좌표 파일과 맞는지."""

import json
import unittest

from tests.helpers import ROOT, TempStudio
from studio import company, floors
from studio.config import RoleConfig
from studio.engine import EngineError


class Floors(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()

    def test_count_capacity_and_add(self):
        self.assertEqual(floors.count(self.cfg), 1)
        self.assertEqual(floors.capacity(self.cfg), 2, "1층 책상 6 - 기본 직원 4")
        self.assertEqual(self.e.add_floor(), 2)
        self.assertEqual(floors.capacity(self.cfg), 10)
        self.assertEqual(self.e.add_floor(), 3)
        self.assertEqual(floors.capacity(self.cfg), floors.MAX_STAFF)
        with self.assertRaises(EngineError):
            self.e.add_floor()
        self.assertEqual(floors.count(self.cfg), floors.MAX_FLOORS)
        info = floors.info(self.cfg)
        self.assertEqual((info["count"], info["max"], info["desks"], info["next_desks"]), (3, 3, [6, 8, 8], 0))
        events = [e for e in self.store.recent_events(10) if e.get("type") == "floor.added"]
        self.assertEqual([e["data"]["floor"] for e in events], [3, 2], "최근 것부터")

    def test_broken_file_means_one_floor(self):
        (self.cfg.data_dir / "floors.json").write_text("{깨짐", encoding="utf-8")
        self.assertEqual(floors.count(self.cfg), 1)
        (self.cfg.data_dir / "floors.json").write_text('{"count": 99}', encoding="utf-8")
        self.assertEqual(floors.count(self.cfg), floors.MAX_FLOORS)

    def test_seats_follow_founders_then_roster(self):
        base = self.cfg.roles["builder"]
        for i, job in enumerate(["analyst", "builder", "producer"], start=1):
            key = f"staff{i}"
            self.cfg.roles[key] = RoleConfig(key=key, title=base.title, runtime=base.runtime, name=f"새{i}", character=key, job=job)
        seats = floors.seats(self.cfg)
        self.assertEqual([seats[k] for k in ("producer", "builder", "reviewer", "analyst")], [0, 1, 2, 3])
        self.assertEqual([seats[f"staff{i}"] for i in (1, 2, 3)], [4, 5, 6])
        self.assertEqual([floors.floor_of(n) for n in (0, 5, 6, 13, 14, 21, 99)], [1, 1, 2, 2, 3, 3, 3])
        team = {m["key"]: m for m in company.team(self.cfg, self.store, [], None)}
        self.assertEqual((team["staff3"]["seat"], team["staff3"]["floor"]), (6, 2))

    def test_screen_coordinates_match_desks(self):
        doc = json.loads((ROOT / "ui" / "assets" / "bg" / "floors.json").read_text(encoding="utf-8"))
        by_n = {f["n"]: f for f in doc["floors"]}
        counts = [len((by_n[f["like"]] if "like" in f else f)["desks"]) for f in doc["floors"]]
        self.assertEqual(tuple(counts), floors.DESKS, "floors.json 책상 수 = floors.py DESKS")
        for f in doc["floors"]:
            if "like" in f:
                continue
            self.assertTrue((ROOT / "ui" / "assets" / "bg" / f["bg"]).is_file())
            self.assertGreaterEqual(len(f["rest"]), len(f["desks"]), "책상마다 쉴 자리")
            for i, _ in enumerate(f.get("fronts", [])):
                stem = f["bg"].rsplit(".", 1)[0]
                self.assertTrue((ROOT / "ui" / "assets" / "bg" / f"{stem}.front-{i}.png").is_file(), "make_fronts.gd를 돌렸는지")
            covered = sorted(d for fr in f.get("fronts", []) for d in fr["desks"])
            self.assertEqual(covered, list(range(len(f["desks"]))), "모든 의자에 앞 그림")


if __name__ == "__main__":
    unittest.main()
