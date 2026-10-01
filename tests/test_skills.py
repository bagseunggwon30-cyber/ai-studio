"""스킬 학습 (Claude 스킬 방식): SKILL.md 저장·읽기, 배우기·잊기, 프롬프트에 붙이기, 스킬 공부 흐름."""

import unittest

from tests.helpers import TempStudio, default_behavior
from studio import company, skills
from studio.engine import EngineError
from studio.prompts import build_prompt

SKILL = {
    "name": "Godot Signal Wiring!",
    "title": "시그널 연결",
    "description": "씬 사이 이벤트를 만들 때 쓴다.",
    "body": "# 시그널\n\n1. `signal`을 선언한다.\n2. `connect`로 잇는다.\n\n---\n\n본문 안의 구분선도 괜찮다.",
}


def study_behavior(spec, runtime=None):
    if spec.run_id.endswith("-skill"):
        return {"structured": {"name": "memo-rules", "title": "메모 규칙", "description": "메모를 쓸 때 쓴다.", "body": "메모는 docs/에 쓴다."}}
    return default_behavior(spec)


class Skills(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()

    def test_skill_file_is_claude_format_and_round_trips(self):
        sk = self.e.teach_skill({**SKILL, "learned_by": ["builder", "nobody"]})
        self.assertEqual(sk.slug, "godot-signal-wiring")
        text = (skills.skills_dir(self.cfg) / sk.slug / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: godot-signal-wiring\ndescription: 씬 사이 이벤트를 만들 때 쓴다.\n"))
        back = skills.get(self.cfg, sk.slug)
        self.assertEqual((back.title, back.learned_by, back.source), ("시그널 연결", ["builder"], "ceo"))
        self.assertIn("본문 안의 구분선도 괜찮다.", back.body)
        # 같은 이름은 뒤에 번호를 붙인다
        self.assertEqual(self.e.teach_skill(SKILL).slug, "godot-signal-wiring-2")
        # 한글 제목만 있으면 로마자로 (skill-2 같은 이름 대신)
        self.assertEqual(self.e.teach_skill({**SKILL, "name": "", "title": "메모 규칙"}).slug, "memo-gyuchik")
        self.assertEqual(skills.slugify("씬 전환 v2!"), "ssin-jeonhwan-v2")
        self.e.remove_skill("memo-gyuchik")
        self.assertEqual([x.slug for x in skills.list_skills(self.cfg)], ["godot-signal-wiring", "godot-signal-wiring-2"])

    def test_bad_input_is_rejected(self):
        with self.assertRaises(EngineError):
            self.e.teach_skill({**SKILL, "body": " "})
        with self.assertRaises(EngineError):
            self.e.teach_skill({**SKILL, "body": "가" * (skills.MAX_BODY + 1)})
        with self.assertRaises(EngineError):
            self.e.set_skill_learned("없는-스킬", "builder", True)
        with self.assertRaises(EngineError):
            self.e.study_skill("nobody", "주제", "demo")
        # 머리말에 줄바꿈을 넣어 다른 칸을 꾸며 낼 수 없다
        sk = self.e.teach_skill({**SKILL, "title": "제목\nlearned_by: reviewer", "description": "설명\n---\nname: x"})
        back = skills.get(self.cfg, sk.slug)
        self.assertEqual(back.learned_by, [])
        self.assertEqual(back.slug, sk.slug)

    def test_frontmatter_quotes_yaml_special_text(self):
        # "예: …"처럼 쌍점·#·따옴표가 든 값은 YAML로 읽어도 같은 글이 되게 큰따옴표로 감싼다
        tricky = {**SKILL, "title": '"따옴표" #1', "description": '예: 씬 전환 # 주의 \\ 끝'}
        sk = self.e.teach_skill(tricky)
        text = (skills.skills_dir(self.cfg) / sk.slug / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('description: "예: 씬 전환 # 주의 \\\\ 끝"\n', text)
        back = skills.get(self.cfg, sk.slug)
        self.assertEqual((back.title, back.description), ('"따옴표" #1', '예: 씬 전환 # 주의 \\ 끝'))

    def test_learn_forget_and_prompt(self):
        sk = self.e.teach_skill(SKILL)
        self.e.set_skill_learned(sk.slug, "builder", True)
        task = self.e.create_task({"project": "demo", "kind": "build", "title": "정답", "brief": "b", "acceptance": ["a"]})
        project = self.cfg.projects["demo"]
        prompt = build_prompt(self.cfg, task, project, 1, "")
        self.assertIn("# 배운 스킬", prompt)
        self.assertIn("`connect`로 잇는다", prompt)
        self.assertNotIn("# 배운 스킬", skills.prompt_block(self.cfg, "reviewer"))
        self.e.set_skill_learned(sk.slug, "builder", False)
        self.assertNotIn("# 배운 스킬", build_prompt(self.cfg, task, project, 1, ""))
        # 지우면 휴지통으로
        self.e.remove_skill(sk.slug)
        self.assertEqual(skills.list_skills(self.cfg), [])
        self.assertEqual(len(list((self.cfg.data_dir / "skills-trash").iterdir())), 1)

    def test_prompt_budget(self):
        for i in range(5):
            self.e.teach_skill({**SKILL, "name": f"s{i}", "body": f"본문{i} " + "가" * 3000, "learned_by": ["builder"]})
        block = skills.prompt_block(self.cfg, "builder")
        self.assertEqual(block.count("언제 쓰나:"), 5)  # 설명은 모두
        self.assertEqual(block.count("(본문은 길거나"), 2)  # 본문은 12000자까지만

    def test_study_flow(self):
        self.s.behavior = study_behavior
        task = self.e.study_skill("analyst", "메모 쓰는 법을 정리해 줘", "demo")
        self.assertEqual((task.kind, task.role, task.status), ("skill", "analyst", "queued"))
        self.assertEqual(self.e._next_job().id, task.id)  # 기획처럼 바로 한다
        self.e._run_skill(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.status, "awaiting_approval")
        self.assertEqual(task.proposal["skill"]["title"], "메모 규칙")
        # 공부 중인 스킬은 아직 아무도 배우지 않았다
        self.assertEqual(skills.list_skills(self.cfg), [])
        texts = [a["text"] for a in company.alerts(self.cfg, self.store, self.store.list())]
        self.assertIn("스킬 공부 끝! 확인해 주세요", texts)
        # 다시 공부 요청 → 다시 공부 → 승인 (함께 배울 직원 고르기, 고친 제목)
        self.e.request_changes(task.id, "예시를 넣어 줘")
        self.assertEqual(self.store.get(task.id).status, "queued")
        self.e._run_skill(self.store.get(task.id))
        self.assertIn("예시를 넣어 줘", (self.store.runs_dir / self.store.get(task.id).runs[-1] / "prompt.md").read_text(encoding="utf-8"))
        self.e.approve(task.id, {"learned_by": ["analyst", "builder"], "edits": {"title": "메모 규칙 v2"}})
        task = self.store.get(task.id)
        self.assertEqual(task.status, "done")
        sk = skills.get(self.cfg, task.report)
        self.assertEqual((sk.title, sk.learned_by, sk.source), ("메모 규칙 v2", ["builder", "analyst"], task.id))
        alerts = company.alerts(self.cfg, self.store, self.store.list())
        learned = next(a for a in alerts if a["type"] == "skill.learned")
        self.assertEqual((learned["text"], learned["who"], learned["skill"]), ("'메모 규칙 v2' 스킬을 배웠어요!", "sol", sk.slug))
        self.assertNotIn("메모 쓰는 법을 정리해 줘 완료!", [a["text"] for a in alerts])

    def test_study_output_that_cannot_be_used_blocks(self):
        self.s.behavior = lambda spec, runtime=None: {"structured": {"name": "x", "title": "", "description": "", "body": ""}}
        task = self.e.study_skill("reviewer", "주제", "demo")
        self.e._run_skill(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.status, "blocked")
        self.assertIn("스킬로 쓸 수 없습니다", task.blocked_reason)
        self.e.retry(task.id)
        self.assertEqual(self.store.get(task.id).status, "queued")

    def test_skill_task_does_not_block_project(self):
        self.s.behavior = study_behavior
        study = self.e.study_skill("builder", "주제", "demo")
        self.e._run_skill(self.store.get(study.id))  # 결재 대기 (브랜치 없음)
        build = self.e.create_task({"project": "demo", "kind": "build", "title": "정답", "brief": "b", "acceptance": ["a"]})
        self.e.request_run(build.id)
        self.assertEqual(self.e._next_job().id, build.id)


if __name__ == "__main__":
    unittest.main()
