"""스스로 배우기: 한 번에 안 풀린 일을 끝낸 직원이 돌아보고(회고) 스킬을 새로 만들거나 고쳐서 제안한다.

배우는 것은 CEO 승인 뒤. 고친 스킬은 판이 오르고 옛 판은 history/에 남는다.
"""

import unittest

from tests.helpers import TempStudio, default_behavior
from studio import company, skills
from studio.util import today_str

NEW_SKILL = {"action": "new", "target": "", "reason": "정답 값을 확인하지 않아 검사에 떨어졌어요.", "change": "",
             "name": "check-answer", "title": "정답 확인", "description": "검사 값을 맞춰야 할 때 쓴다.",
             "body": "1. 수용 기준의 값을 다시 읽는다.\n2. 파일 값을 확인한다."}


def build_task(e, title="정답"):
    return e.create_task({"project": "demo", "kind": "build", "title": title, "brief": "docs/answer.txt에 42",
                          "acceptance": ["검사 통과"], "allowed_paths": ["docs/**"]})


class SelfLearning(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine
        self.prompts: list[str] = []
        self.retro_answer = NEW_SKILL
        self.builds = 0

    def tearDown(self):
        self.s.close()

    def behavior(self, spec, runtime=None):
        """개발은 첫 시도에 41을 써서 검사에 떨어지고 두 번째에 42. 회고는 retro_answer를 돌려준다."""
        if spec.run_id.endswith("-retro"):
            self.prompts.append(spec.prompt)
            return {"structured": self.retro_answer}
        if spec.role == "builder":
            self.builds += 1
            return {"files": {"docs/answer.txt": "41\n" if self.builds == 1 else "42\n"}}
        return default_behavior(spec)

    def finish_with_trouble(self, title="정답"):
        self.s.behavior = self.behavior
        self.builds = 0
        t = build_task(self.e, title)
        self.e._run_build(self.store.get(t.id))
        t = self.store.get(t.id)
        self.assertEqual((t.status, t.attempts), ("awaiting_approval", 2), t.blocked_reason)
        self.e.approve(t.id)
        return self.store.get(t.id)

    def retro_of(self, task_id):
        return next(t for t in self.store.list() if t.origin == task_id)

    def test_trouble_is_recorded_and_reflection_proposes_new_skill(self):
        done = self.finish_with_trouble()
        self.assertEqual([x["kind"] for x in done.troubles], ["qa"])
        self.assertIn("answer_is_42", done.troubles[0]["text"])
        retro = self.retro_of(done.id)
        self.assertEqual((retro.kind, retro.role, retro.status, retro.created_by), ("skill", "builder", "queued", "system"))
        self.assertEqual(self.e._next_job().id, retro.id)
        self.e._run_skill(self.store.get(retro.id))
        retro = self.store.get(retro.id)
        self.assertEqual(retro.status, "awaiting_approval")
        self.assertEqual(retro.proposal["action"], "new")
        self.assertIn("돌아보기 (회고)", self.prompts[-1])
        self.assertIn("[신뢰 검사 탈락]", self.prompts[-1])
        self.assertEqual(skills.list_skills(self.cfg), [], "승인 전에는 배우지 않는다")
        texts = [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())]
        self.assertIn("돌아보고 새 스킬을 만들었어요! 확인해 주세요", texts)
        self.e.approve(retro.id)
        sk = skills.get(self.cfg, "check-answer")
        self.assertEqual((sk.how, sk.version, sk.learned_by, sk.source), ("reflect", 1, ["builder"], retro.id))

    def test_reflection_updates_skill_and_keeps_history(self):
        old = self.e.teach_skill({"name": "answers", "title": "답 쓰기", "description": "답을 쓸 때", "body": "답을 쓴다.",
                                  "learned_by": ["builder", "analyst"]})
        self.retro_answer = {**NEW_SKILL, "action": "update", "target": old.slug, "change": "값 확인 순서를 더함",
                             "title": "답 쓰기", "body": "답을 쓴다.\n쓰고 나서 값을 확인한다."}
        done = self.finish_with_trouble()
        # 실행 기록에 그때 붙은 스킬(판까지)이 남는다
        builds = [r for r in self.store.runs(done.id) if r["stage"].startswith("build")]
        self.assertEqual(builds[0]["skills"], ["answers@1"])
        self.assertEqual(company.skill_usage("answers", self.store.list(), self.store.runs())["tasks"], 1)
        retro = self.retro_of(done.id)
        self.e._run_skill(self.store.get(retro.id))
        self.assertIn("`answers` (v1)", self.prompts[-1], "배운 스킬은 전체 글로 보여 준다")
        self.assertIn("'답 쓰기' 스킬을 고쳐 왔어요! 확인해 주세요",
                      [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])
        self.e.approve(retro.id)
        sk = skills.get(self.cfg, old.slug)
        self.assertEqual((sk.version, sk.change, sk.how, sk.learned_by), (2, "값 확인 순서를 더함", "reflect", ["builder", "analyst"]))
        self.assertIn("값을 확인한다", sk.body)
        self.assertTrue((skills.history_dir(self.cfg, old.slug) / "v1.md").is_file())
        hist = skills.history(self.cfg, sk)
        self.assertEqual([(h["version"], h["how"]) for h in hist], [(1, "ceo"), (2, "reflect")])
        self.assertEqual(skills.get(self.cfg, old.slug).created, today_str())
        self.assertEqual(len(skills.list_skills(self.cfg)), 1, "고치면 새 스킬이 생기지 않는다")
        self.assertIn("'답 쓰기' 스킬을 고쳤어요! (v2)",
                      [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())])

    def test_nothing_to_learn_ends_quietly(self):
        self.retro_answer = {**NEW_SKILL, "action": "none", "reason": "네트워크 문제였어요.", "name": "", "title": "",
                             "description": "", "body": ""}
        done = self.finish_with_trouble()
        retro = self.retro_of(done.id)
        self.e._run_skill(self.store.get(retro.id))
        retro = self.store.get(retro.id)
        self.assertEqual(retro.status, "cancelled")
        self.assertEqual(retro.report, "네트워크 문제였어요.")
        self.assertEqual(skills.list_skills(self.cfg), [])
        texts = [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())]
        self.assertFalse(any("스킬" in x for x in texts), texts)

    def test_redo_note_reaches_reflection(self):
        # 회고해 온 스킬에 '다시 정리'를 요청하면 그 의견이 다음 회고 프롬프트에 들어간다
        done = self.finish_with_trouble()
        retro = self.retro_of(done.id)
        self.e._run_skill(self.store.get(retro.id))
        self.e.request_changes(retro.id, "예시를 하나 넣어 줘")
        self.e._run_skill(self.store.get(retro.id))
        self.assertIn("예시를 하나 넣어 줘", self.prompts[-1])
        self.assertEqual(self.store.get(retro.id).status, "awaiting_approval")

    def test_smooth_work_is_not_reflected(self):
        self.s.behavior = default_behavior
        t = build_task(self.e)
        self.e._run_build(self.store.get(t.id))
        self.e.approve(t.id)
        self.assertFalse(any(x.origin for x in self.store.list()))

    def test_switch_and_daily_cap(self):
        self.e.set_self_learning(False)
        done = self.finish_with_trouble("하나")
        self.assertFalse(any(x.origin == done.id for x in self.store.list()))
        self.e.set_self_learning(True)
        for i in range(self.cfg.limit("max_auto_skills_per_day") + 1):
            self.finish_with_trouble(f"일 {i}")
        self.assertEqual(self.e.reflections_today(), self.cfg.limit("max_auto_skills_per_day"))
        self.assertTrue(any(e["type"] == "skill.reflect_skipped" for e in self.store.recent_events(50)))

    def test_ceo_change_request_also_makes_reviewer_reflect(self):
        self.s.behavior = default_behavior
        t = build_task(self.e)
        self.e._run_build(self.store.get(t.id))
        self.e.request_changes(t.id, "메모도 남겨 줘")
        self.e._run_build(self.store.get(t.id))
        self.e.approve(t.id)
        roles = sorted(x.role for x in self.store.list() if x.origin == t.id)
        self.assertEqual(roles, ["builder", "reviewer"])
        self.s.behavior = self.behavior
        reviewer = next(x for x in self.store.list() if x.origin == t.id and x.role == "reviewer")
        self.e._run_skill(self.store.get(reviewer.id))
        self.assertIn("리뷰를 승인했지만", self.prompts[-1])
        self.assertIn("메모도 남겨 줘", self.prompts[-1])

    def test_plan_redo_makes_producer_reflect(self):
        self.s.behavior = default_behavior
        plan = self.e.submit_directive("정답 만들기", "demo")
        self.e._run_plan(self.store.get(plan.id))
        self.e.request_changes(plan.id, "작업을 하나로 줄여 줘")
        self.e._run_plan(self.store.get(plan.id))
        self.e.approve(plan.id)
        retro = self.retro_of(plan.id)
        self.assertEqual(retro.role, "producer")

    def test_ceo_asks_to_improve_a_skill(self):
        old = self.e.teach_skill({"name": "answers", "title": "답 쓰기", "description": "답을 쓸 때", "body": "답을 쓴다.",
                                  "learned_by": ["builder"]})
        task = self.e.study_skill("reviewer", "", "demo", target=old.slug)
        self.assertEqual((task.title, task.target), ("고쳐 오기: 답 쓰기", old.slug))
        seen = []

        def behavior(spec, runtime=None):
            seen.append(spec.prompt)
            return {"structured": {**NEW_SKILL, "action": "new"}}  # 새 스킬이라고 해도 고친 것으로 받는다

        self.s.behavior = behavior
        self.e._run_skill(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertIn("고칠 스킬: `answers` (지금 v1)", seen[-1])
        self.assertEqual((task.proposal["action"], task.proposal["target"]), ("update", old.slug))
        self.e.approve(task.id)
        sk = skills.get(self.cfg, old.slug)
        self.assertEqual((sk.version, sk.how, sk.learned_by), (2, "study", ["builder", "reviewer"]))


if __name__ == "__main__":
    unittest.main()
