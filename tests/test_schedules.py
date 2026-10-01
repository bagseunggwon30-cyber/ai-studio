"""업무 자동 시작 (벽시계): 때 계산, 때가 되면 일 만들기, 쌓이지 않게 건너뛰기, 긴급 정지·에너지 기다리기."""

import unittest
from datetime import datetime

from tests.helpers import TempStudio
from studio import schedules
from studio.engine import EngineError


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm).astimezone()


class Timing(unittest.TestCase):
    def test_daily_weekdays_weekly_hours(self):
        created = at(2026, 9, 27, 8).isoformat()  # 일요일 08:00
        daily = {"every": "daily", "at": "09:00", "created": created, "enabled": True}
        self.assertIsNone(schedules.last_due(daily, at(2026, 9, 27, 8, 30)), "만든 날 9시 전에는 아직")
        self.assertEqual(schedules.last_due(daily, at(2026, 9, 29, 9, 30)), at(2026, 9, 29, 9))
        self.assertEqual(schedules.last_due(daily, at(2026, 9, 29, 8, 59)), at(2026, 9, 28, 9))
        self.assertEqual(schedules.next_due(daily, at(2026, 9, 29, 9, 30)), at(2026, 9, 30, 9))
        # 평일: 토요일(10/3)·일요일(10/4)에는 금요일 것이 마지막
        weekdays = {**daily, "every": "weekdays"}
        self.assertEqual(schedules.last_due(weekdays, at(2026, 10, 4, 12)), at(2026, 10, 2, 9))
        self.assertEqual(schedules.next_due(weekdays, at(2026, 10, 2, 10)), at(2026, 10, 5, 9))
        weekly = {**daily, "every": "weekly", "weekday": 2}  # 수요일
        self.assertEqual(schedules.last_due(weekly, at(2026, 10, 2, 12)), at(2026, 9, 30, 9))
        self.assertEqual(schedules.describe(weekly), "매주 수요일 09:00")
        hours = {"every": "hours", "hours": 3, "created": created, "enabled": True}
        self.assertIsNone(schedules.last_due(hours, at(2026, 9, 27, 10)))
        self.assertEqual(schedules.last_due(hours, at(2026, 9, 27, 15)), at(2026, 9, 27, 14))
        self.assertEqual(schedules.describe(hours), "3시간마다")
        # 이미 한 때는 다시 하지 않는다, 꺼 두면 하지 않는다
        self.assertEqual(schedules.is_due({**daily, "last_run": at(2026, 9, 29, 9, 1).isoformat()}, at(2026, 9, 29, 12)), None)
        self.assertEqual(schedules.is_due({**daily, "last_run": at(2026, 9, 28, 9, 1).isoformat()}, at(2026, 9, 29, 12)), at(2026, 9, 29, 9))
        self.assertIsNone(schedules.is_due({**daily, "enabled": False}, at(2026, 9, 29, 12)))


class AutoStart(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()

    def add(self, **kw):
        data = {"kind": "directive", "title": "아침 점검", "text": "어제 바뀐 코드를 점검해 줘", "project": "demo", "every": "daily", "at": "09:00", **kw}
        item = self.e.add_schedule(data)
        schedules.update(self.cfg, item["id"], created=at(2026, 9, 1, 0).isoformat())  # 오래전에 만든 것으로
        return item

    def test_validation(self):
        for bad in ({"kind": "build"}, {"title": ""}, {"project": "nope"}, {"every": "yearly"}, {"at": "25:00"},
                    {"every": "weekly", "weekday": 9}, {"every": "hours", "hours": 0}):
            with self.assertRaises(EngineError, msg=bad):
                self.e.add_schedule({"kind": "directive", "title": "t", "text": "x", "project": "demo", "every": "daily", "at": "09:00", **bad})

    def test_tick_starts_once_and_does_not_pile_up(self):
        item = self.add()
        made = self.e.schedule_tick(at(2026, 9, 29, 9, 5))
        self.assertEqual(len(made), 1)
        t = made[0]
        self.assertEqual((t.kind, t.status, t.created_by, t.extra), ("plan", "queued", "schedule", {"schedule": item["id"]}))
        self.assertEqual(self.e._next_job().id, t.id, "기획은 바로 한다")
        self.assertEqual(self.e.schedule_tick(at(2026, 9, 29, 9, 30)), [], "같은 때는 한 번만")
        # 다음 날: 지난 일이 아직 열려 있으면 건너뛴다
        self.assertEqual(self.e.schedule_tick(at(2026, 9, 30, 9, 5)), [])
        self.assertTrue(any(e["type"] == "schedule.skipped" for e in self.store.recent_events(20)))
        texts = [a["text"] for a in __import__("studio.company", fromlist=["alerts"]).alerts(self.cfg, self.store, self.store.list())]
        self.assertIn("자동 업무 시작: 아침 점검", texts)

    def test_last_run_follows_the_time_given_not_the_wall_clock(self):
        """마지막 실행 시각은 넘겨받은 때로 적는다 — 진짜 시계가 시험 속 시각을 지나가도 결과가 같다 (예전에는 진짜 지금 시각으로 적어
        진짜 시계가 '다음 날 9시 5분'을 지난 뒤부터 건너뛰기 시험이 깨졌다)."""
        item = self.add()
        when = at(2026, 9, 29, 9, 5)
        self.assertEqual(len(self.e.schedule_tick(when)), 1)
        self.assertEqual(schedules.load(self.cfg)[0]["last_run"], when.isoformat(timespec="seconds"))
        later = at(2026, 9, 30, 9, 5)  # 진짜 시계보다 앞일 수도 뒤일 수도 있다
        self.assertEqual(self.e.schedule_tick(later), [], "지난 일이 아직 열려 있어 건너뜀")
        self.assertEqual(schedules.load(self.cfg)[0]["last_run"], later.isoformat(timespec="seconds"))
        self.assertEqual(item["id"], schedules.load(self.cfg)[0]["id"])

    def test_research_runs_by_itself(self):
        self.add(kind="research", title="주간 동향", text="이번 주 Godot 소식 정리")
        (t,) = self.e.schedule_tick(at(2026, 9, 29, 9, 5))
        self.assertEqual((t.kind, t.status, t.run_requested, t.allowed_paths), ("research", "ready", True, ["reports/**"]))
        self.assertEqual(self.e._next_job().id, t.id)

    def test_waits_while_stopped_or_out_of_energy(self):
        self.add()
        self.e._stop.set()
        self.assertEqual(self.e.schedule_tick(at(2026, 9, 29, 9, 5)), [])
        self.e._stop.clear()
        self.cfg.limits["max_runs_per_day"] = 0
        self.assertEqual(self.e.schedule_tick(at(2026, 9, 29, 9, 5)), [])
        self.cfg.limits["max_runs_per_day"] = 40
        self.assertEqual(len(self.e.schedule_tick(at(2026, 9, 29, 13))), 1, "기다렸다가 한 번 따라잡는다")

    def test_actions(self):
        item = self.add()
        self.e.schedule_action(item["id"], "enable", {"on": False})
        self.assertEqual(self.e.schedule_tick(at(2026, 9, 29, 9, 5)), [])
        got = self.e.schedule_action(item["id"], "run", {})
        self.assertTrue(got["last_task"].startswith("T"))
        with self.assertRaises(EngineError):
            self.e.schedule_action(item["id"], "run", {})  # 지난 일이 아직 열려 있음
        self.e.schedule_action(item["id"], "remove", {})
        self.assertEqual(schedules.load(self.cfg), [])
        view = schedules.view(self.cfg)
        self.assertEqual(view, [])


if __name__ == "__main__":
    unittest.main()
