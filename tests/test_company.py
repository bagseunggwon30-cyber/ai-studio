"""게임 화면용 회사 정보: 난이도, 보관, 완성작, 보고서 요약, 꾸미기, 알림, 일지, 통계."""

import unittest

from tests.helpers import TempStudio, default_behavior
from studio import company
from studio.engine import EngineError
from studio.runtimes import FAKE_REPORT

REPORT = """# 테스트 보고서

## 결론 요약

첫 문장이 결론입니다. 두 번째 문장은 설명입니다.

## 핵심 주장

1. 하나 [S1]
2. 둘 [S2][S3]
3. 셋
4. 넷

## 출처

- [S1] 문서 A — https://example.com/a (확인 2026-09-28)
- [S2] 문서 B — https://example.com/b.

## 미확인·한계

- 확인 못 한 것 하나
"""


def research_behavior(spec, runtime=None):
    if spec.role == "analyst":
        return {"files": {"docs/answer.txt": "42\n", "docs/report.md": REPORT}, "message": "보고서"}
    return default_behavior(spec)


class CompanyInfo(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.e = self.s.engine
        self.store = self.s.store
        self.cfg = self.s.cfg

    def tearDown(self):
        self.s.close()

    def build(self, kind="build"):
        t = self.e.create_task({"project": "demo", "kind": kind, "title": "정답", "brief": "b", "acceptance": ["검사"], "allowed_paths": ["docs/**"]})
        self.e._run_build(self.store.get(t.id))
        return self.store.get(t.id)

    def test_plan_difficulty_reaches_children(self):
        def behavior(spec, runtime=None):
            out = default_behavior(spec)
            if spec.role == "producer":
                for i, item in enumerate(out["structured"]["tasks"]):
                    item["difficulty"] = [3, 9][i]  # 9는 3으로 잘린다
            return out

        self.s.behavior = behavior
        plan = self.e.submit_directive("해 줘", "demo")
        self.e._run_plan(self.store.get(plan.id))
        plan = self.store.get(plan.id)
        self.assertEqual([t["difficulty"] for t in plan.proposal["tasks"]], [3, 3])
        self.e.approve(plan.id, {"selected": [0]})
        child = self.store.get(self.store.get(plan.id).children[0])
        self.assertEqual(child.difficulty, 3)
        self.assertEqual(child.summary()["difficulty"], 3)

    def test_archive_only_awaiting(self):
        t = self.build()
        self.assertEqual(t.status, "awaiting_approval")
        self.e.archive(t.id, True)
        self.assertTrue(self.store.get(t.id).archived)
        self.e.approve(t.id)
        with self.assertRaises(EngineError):
            self.e.archive(t.id, False)

    def test_research_becomes_trophy_and_report_is_parsed(self):
        self.s.behavior = research_behavior
        t = self.build("research")
        summary = company.report_summary(self.cfg, t)
        self.assertEqual(summary["file"], "docs/report.md")
        self.assertEqual(summary["title"], "테스트 보고서")
        self.assertEqual(summary["conclusion"], "첫 문장이 결론입니다.")
        self.assertEqual(summary["claims"], ["하나", "둘", "셋"])
        self.assertEqual(summary["sources"], [{"title": "문서 A", "url": "https://example.com/a"}, {"title": "문서 B", "url": "https://example.com/b"}])
        self.assertEqual(summary["unverified"], ["확인 못 한 것 하나"])
        self.e.approve(t.id)
        trophies = self.store.read_doc("trophies", [])
        self.assertEqual([(x["kind"], x["task"]) for x in trophies], [("report", t.id)])
        with self.assertRaises(EngineError):
            self.e.add_trophy(t.id, "report")  # 중복

    def test_game_trophy_needs_done_build(self):
        t = self.build()
        with self.assertRaises(EngineError):
            self.e.add_trophy(t.id, "game")  # 아직 결재 대기
        self.e.approve(t.id)
        self.e.add_trophy(t.id, "game")
        self.e.remove_trophy(t.id)
        self.assertEqual(self.store.read_doc("trophies", []), [])

    def test_fake_report_template_parses(self):
        r = company.parse_report(FAKE_REPORT)
        self.assertEqual(len(r["claims"]), 3)
        self.assertEqual(len(r["sources"]), 3)  # studio-docs 신뢰 검사는 출처 3개 이상을 요구한다
        self.assertTrue(r["conclusion"].endswith("."))

    def test_look_is_whitelisted(self):
        look = company.clean_look(self.cfg, "sol", {"style": "bikini", "hair": "blonde", "outfit": "<b>", "height": "tall", "build": "x", "extra": 1})
        self.assertEqual(look, {"style": "base", "hair": "blonde", "outfit": "base", "height": 0, "head": 0, "build": 0, "shoulders": 0, "chest": 0, "waist": 0, "hips": 0, "hair_volume": 0}, "키·체격 늘리기는 없앴다 (예전 값은 버린다)")
        saved = company.save_look(self.cfg, self.store, "builder", {"hair": "red"})
        self.assertEqual(saved["hair"], "red")
        self.assertEqual(company.looks(self.cfg, self.store)["builder"]["hair"], "red")
        with self.assertRaises(ValueError):
            company.save_look(self.cfg, self.store, "nobody", {})

    def test_body_sliders_are_clamped_and_saved(self):
        """몸 조절 막대: 정수로 바꿔 범위로 자르고(자연스러운 범위 고정), 모르는 값·예전 글자 값은 0, 저장·다시 읽기."""
        look = company.clean_look(self.cfg, "sol", {"height": 9, "head": -9, "build": "1", "chest": 5, "waist": -1.9,
                                                    "hips": True, "shoulders": None, "hair_volume": "많이"})
        self.assertEqual({k: look[k] for k, *_ in company.BODY_SLIDERS},
                         {"height": 2, "head": -2, "build": 1, "chest": 2, "waist": -1, "hips": 0, "shoulders": 0, "hair_volume": 0})
        ranges = {k: (lo, hi) for k, _, lo, hi, _ in company.BODY_SLIDERS}
        self.assertEqual((ranges["chest"], ranges["hair_volume"]), ((0, 2), (0, 2)), "가슴·머리 숱은 0~+2로 고정")
        self.assertTrue(all(lo >= -2 and hi <= 2 for lo, hi in ranges.values()), "모든 막대가 -2~+2 안")
        saved = company.save_look(self.cfg, self.store, "producer", {"shoulders": -1, "chest": 1, "waist": -1, "hips": 1})
        again = company.looks(self.cfg, self.store)["producer"]
        self.assertEqual((again["shoulders"], again["chest"], again["waist"], again["hips"]), (-1, 1, -1, 1))
        self.assertEqual(saved, again)
        opts = company.look_options(self.cfg)
        self.assertEqual([d["key"] for d in opts["body"]], [k for k, *_ in company.BODY_SLIDERS])
        self.assertTrue(all(len(d["steps"]) == d["max"] - d["min"] + 1 for d in opts["body"]), "단계 이름 수 = 단계 수")
        presets = {p["key"]: p["values"] for p in opts["presets"]}
        self.assertEqual(set(presets), {"feminine", "neutral", "masculine"})
        self.assertLess(presets["feminine"]["shoulders"], presets["masculine"]["shoulders"])
        self.assertGreater(presets["feminine"]["hips"], presets["masculine"]["hips"])
        for values in presets.values():
            self.assertEqual(company.clean_look(self.cfg, "sol", values)["chest"], values.get("chest", 0), "빠른 선택 값도 범위 안")

    def test_plan_alert_counts_children(self):
        """기획 완료 알림의 퀘스트 수: 작업 목록보다 먼저 읽은 기록을 넘기면 '0개'가 나오지 않는다."""
        plan = self.e.submit_directive("해 줘", "demo")
        self.e._run_plan(self.store.get(plan.id))
        stale = self.store.list()  # 승인 전에 읽은 작업 목록 (자식 없음)
        self.e.approve(plan.id, {"selected": [0, 1]})
        # 예전 순서(작업 목록 → 기록)였다면: 옛 목록 + 새 기록 → "퀘스트 0개"
        self.assertIn("퀘스트 0개 붙였어요", [a["text"] for a in company.alerts(self.cfg, self.store, stale)])
        # 지금 순서(기록 → 작업 목록)
        events = self.store.recent_events(company.ALERT_SCAN)
        texts = [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list(), events=events)]
        self.assertIn("퀘스트 2개 붙였어요", texts)
        self.assertNotIn("퀘스트 0개 붙였어요", texts)

    def test_diary_keeps_every_record_and_summary_for_the_day(self):
        from studio.util import append_jsonl
        t = self.e.create_task({"project": "demo", "kind": "research", "title": "긴 업무 기록", "brief": "b", "allowed_paths": ["docs/**"]})
        today = company.day_date(self.store, company.day_number(self.store))
        for i in range(12):
            append_jsonl(self.store.events_path, {"at": f"{today}T10:{i:02}:00", "type": "task.blocked", "task": t.id})
        append_jsonl(self.store.events_path, {"at": f"{today}T11:00:00", "type": "task.status", "task": t.id,
                                              "data": {"status": "done", "by": "ceo"}})
        append_jsonl(self.store.events_path, {"at": "2000-01-01T10:00:00", "type": "task.blocked", "task": t.id})
        diary = company.diary(self.cfg, self.store, self.store.list(), company.day_number(self.store))
        self.assertEqual(len(diary["events"]), 13)
        self.assertEqual(diary["events"][0]["time"], "10:00")
        self.assertEqual(diary["events"][-1]["time"], "11:00")
        self.assertEqual(diary["events"][-1]["text"], "긴 업무 기록 완성")
        self.assertEqual(diary["summary"]["done"], 1)
        self.assertEqual(diary["summary"]["approvals"], 1)

    def test_alerts_diary_stats_scene(self):
        t = self.build()
        alerts = company.alerts(self.cfg, self.store, self.store.list())
        texts = [a["text"] for a in alerts]
        self.assertIn("결재 부탁드려요!", texts)
        self.assertIn("정답 품질 검사 합격!", texts)
        first = next(a for a in alerts if a["text"] == "결재 부탁드려요!")
        self.assertEqual((first["who"], first["name"], first["screen"]), ("sol", "솔", "approval"))

        self.e.approve(t.id)
        tasks = self.store.list()
        day = company.diary(self.cfg, self.store, tasks, company.day_number(self.store))
        self.assertEqual(day["summary"]["done"], 1)
        self.assertEqual(day["summary"]["approvals"], 1)
        self.assertEqual(day["summary"]["firstPass"], [1, 1])
        self.assertTrue(any(e["text"] == "정답 완성" for e in day["events"]))
        self.assertTrue(any(e["text"].startswith("리뷰 ") for e in day["events"]))

        stats = company.role_stats(self.cfg, "builder", tasks, self.store.runs())
        self.assertEqual((stats["done"], stats["level"], stats["xp"], stats["accuracy"]), (1, 1, 1, 1.0))
        self.assertEqual(stats["today_done"], 1)
        self.assertEqual(stats["mood"], "happy")

        self.assertEqual(company.role_scene("builder", {"role": "builder", "stage": "build2", "task": "T1"}, tasks)["phase"], "고치는 중")
        checking = self.store.get(t.id)
        checking.status = "checking"
        self.assertEqual(company.role_scene("builder", {"role": "builder", "stage": "build1", "task": t.id}, [checking])["phase"], "검사 받는 중")
        self.assertEqual(company.role_scene("reviewer", None, tasks)["state"], "rest")

    def test_blocked_scene(self):
        self.s.behavior = lambda spec, rt=None: {"error_kind": "error"} if spec.role == "builder" else default_behavior(spec)
        t = self.build()
        self.assertEqual(t.status, "blocked")
        scene = company.role_scene("builder", None, self.store.list())
        self.assertEqual((scene["state"], scene["task"]), ("blocked", t.id))

    def test_company_day_is_stable(self):
        self.store.update_state(founded="2026-09-20")
        self.assertEqual(company.day_number(self.store, "2026-09-28"), 9)
        self.assertEqual(company.day_date(self.store, 9), "2026-09-28")


if __name__ == "__main__":
    unittest.main()
