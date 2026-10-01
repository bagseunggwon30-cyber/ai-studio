"""스킬 강화: 쓰는 곳(프로젝트·일 종류), 지금 일에 맞는 스킬 고르기, 따른 스킬 알리기, 비슷한 스킬 합치기."""

import unittest

from tests.helpers import TempStudio, default_behavior
from studio import company, skills
from studio.engine import EngineError
from studio.prompts import build_prompt, reflect_prompt, skill_prompt, tool_prompt
from studio.runtimes import _fake_skills_used, default_fake_behavior


def teach(e, name, body, **extra):
    data = {"name": name, "title": extra.pop("title", name), "description": extra.pop("description", f"{name} 할 때"),
            "body": body, "learned_by": extra.pop("learned_by", ["builder"])}
    return e.teach_skill({**data, **extra})


def build_task(e, title="정답"):
    return e.create_task({"project": "demo", "kind": "build", "title": title, "brief": "docs/answer.txt에 42",
                          "acceptance": ["검사 통과"], "allowed_paths": ["docs/**"]})


class SkillStrength(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.cfg, self.store, self.e = self.s.cfg, self.s.store, self.s.engine

    def tearDown(self):
        self.s.close()

    def test_scope_limits_where_a_skill_is_used(self):
        a = teach(self.e, "only-build", "A본문", kinds=["build"], projects=["demo", "nope"])
        self.assertEqual((a.projects, a.kinds), (["demo"], ["build"]), "없는 프로젝트·일 종류는 뺀다")
        self.assertEqual((skills.get(self.cfg, a.slug).projects, skills.get(self.cfg, a.slug).kinds), (["demo"], ["build"]))
        b = teach(self.e, "only-review", "B본문", kinds=["review", "bogus"])
        self.assertEqual(b.kinds, ["review"])
        block = skills.prompt_block(self.cfg, "builder", project="demo", kind="build")
        self.assertIn("A본문", block)
        self.assertNotIn("B본문", block)
        self.assertNotIn("`only-review`", block, "쓰는 곳 밖의 스킬은 설명도 붙이지 않는다")
        self.assertNotIn("A본문", skills.prompt_block(self.cfg, "builder", project="other", kind="build"))
        # 개발 프롬프트에도 그대로
        task = build_task(self.e)
        prompt = build_prompt(self.cfg, task, self.cfg.projects["demo"], 1, "")
        self.assertIn("A본문", prompt)
        self.assertNotIn("B본문", prompt)
        # 쓰는 곳 바꾸기: 내용이 아니라 판은 그대로
        sk = self.e.set_skill_scope(b.slug, [], ["build", "review"])
        self.assertEqual((sk.kinds, sk.version), (["build", "review"], 1))
        self.assertEqual(skills.get(self.cfg, b.slug).kinds, ["build", "review"])
        self.assertIn("B본문", skills.prompt_block(self.cfg, "builder", project="demo", kind="build"))
        self.assertTrue(any(e["type"] == "skill.scope" for e in self.store.recent_events(10)))
        # 모두 비우면 모든 곳
        self.e.set_skill_scope(a.slug, [], [])
        self.assertIn("A본문", skills.prompt_block(self.cfg, "builder", project="other", kind="review"))
        with self.assertRaises(EngineError):
            self.e.set_skill_scope(b.slug, "demo", [])
        with self.assertRaises(EngineError):
            self.e.set_skill_scope("no-such-skill", [], [])

    def test_most_relevant_skills_get_the_full_body(self):
        for i in range(6):
            teach(self.e, f"chore-{i}", f"잡일본문{i}", title=f"잡일 {i}", description="아무 때나")
        teach(self.e, "save-file", "세이브본문", title="세이브 파일 저장", description="세이브 저장 기능을 만들 때")
        full, brief = skills.select(self.cfg, "builder", kind="build", text="세이브 저장 기능 추가")
        self.assertEqual(full[0].slug, "save-file", "지금 일과 낱말이 겹치는 스킬부터 본문을 붙인다")
        self.assertEqual((len(full), len(brief)), (skills.MAX_FULL, 2))
        block = skills.prompt_block(self.cfg, "builder", kind="build", text="세이브 저장 기능 추가")
        self.assertIn("세이브본문", block)
        self.assertEqual(block.count("(본문은 길거나"), 2)
        self.assertIn("사용한 스킬:", block, "끝낼 때 따른 스킬을 알리게 한다")

    def test_parse_applied(self):
        offered = ["a-skill", "b-skill"]
        self.assertEqual(skills.parse_applied("", {"skills_used": ["b-skill", "zzz", "b-skill"]}, offered), ["b-skill"])
        self.assertEqual(skills.parse_applied("했어요\n사용한 스킬: `a-skill`, c-skill", None, offered), ["a-skill"])
        self.assertEqual(skills.parse_applied("- 사용한 스킬: 없음", None, offered), [])
        self.assertEqual(skills.parse_applied("사용한 스킬: a-skill\n…\n사용한 스킬: b-skill", None, offered), ["b-skill"])
        self.assertIsNone(skills.parse_applied("보고만 했어요", None, offered), "알리지 않으면 모름")

    def test_parse_applied_reads_common_formatting(self):
        """진짜 모델이 흔히 쓰는 표기: 굵은 글씨·번호 목록·인용·마침표·전각 콜론 (놓치면 '알리지 않음'으로 세어진다)."""
        offered = ["signal-wiring", "review-checklist"]
        both = ["signal-wiring", "review-checklist"]
        for text, want in [
            ("했어요\n\n**사용한 스킬:** signal-wiring", ["signal-wiring"]),
            ("**사용한 스킬**: signal-wiring, review-checklist", both),
            ("사용한 스킬: signal-wiring, review-checklist.", both),
            ("1. 한 일\n2. 사용한 스킬: signal-wiring", ["signal-wiring"]),
            ("> 사용한 스킬: signal-wiring", ["signal-wiring"]),
            ("사용한 스킬：`signal-wiring`, `review-checklist`", both),
            ("사용한 스킬: (없음)", []),
            ("사용한 스킬: 없음.", []),
            ("사용한 스킬: other-skill", []),
        ]:
            self.assertEqual(skills.parse_applied(text, None, offered), want, text)
        self.assertIsNone(skills.parse_applied("저는 사용한 스킬: signal-wiring 을 따랐어요", None, offered), "줄 맨 앞이 아니면 모름")
        self.assertIsNone(skills.parse_applied("그냥 끝냈어요", None, offered))

    def test_prompts_ask_for_applied_skills_where_the_model_looks(self):
        """개발 프롬프트는 맨 끝 '끝낼 때' 양식에도 '사용한 스킬' 줄을 요청하고(배운 스킬이 붙었을 때만),
        스킬 공부·회고 프롬프트에는 스킬 본문이 한 번만 들어가고 이 요청은 없다."""
        project = self.cfg.projects["demo"]
        task = build_task(self.e)
        before = build_prompt(self.cfg, task, project, 1, "")
        self.assertNotIn("사용한 스킬", before, "배운 스킬이 없으면 요청하지 않는다")
        teach(self.e, "answer-rules", "UNIQUE-BODY-XYZ 답을 쓴다.", title="정답 쓰기", description="정답 파일을 쓸 때 쓴다")
        after = build_prompt(self.cfg, task, project, 1, "")
        ending = after.split("## 끝낼 때", 1)[1]
        self.assertIn("`사용한 스킬: 이름, 이름`", ending, "맨 끝 양식에도 요청한다")
        study = self.e.study_skill("builder", "정답 쓰는 법", "demo")
        prompt = skill_prompt(self.cfg, self.store.get(study.id), project)
        self.assertEqual(prompt.count("UNIQUE-BODY-XYZ"), 1, "공부 프롬프트에 본문이 두 번 들어가지 않는다")
        self.assertNotIn("사용한 스킬", prompt)
        self.assertIn("`answer-rules` (v1)", prompt, "배운 스킬은 전체 글 칸에서 보여 준다")
        origin = build_task(self.e, "지난 일")
        retro = reflect_prompt(self.cfg, self.store.get(study.id), origin, project, [])
        self.assertEqual(retro.count("UNIQUE-BODY-XYZ"), 1)
        self.assertNotIn("`사용한 스킬: 이름, 이름`", retro)

    def test_study_kind_attaches_only_chosen_skills_once(self):
        """스킬 공부(study): 쓰는 곳에 study를 고른 스킬만 공부·회고·MCP 만들기에 붙고(보통 스킬은 안 붙음), 본문은 한 번만,
        보통 일에는 붙지 않는다. 실행 기록에 붙은 스킬과 따른 스킬이 남는다."""
        teach(self.e, "general", "GENERAL-BODY 답을 쓴다.", title="보통 요령", description="아무 일에나")
        teach(self.e, "how-to-skill", "STUDY-BODY 스킬 본문은 순서·실수·확인으로.", title="스킬 쓰는 법",
              description="스킬을 공부해 정리할 때 쓴다", kinds=["study"])
        build_block = skills.prompt_block(self.cfg, "builder", project="demo", kind="build")
        self.assertIn("GENERAL-BODY", build_block)
        self.assertNotIn("STUDY-BODY", build_block, "스킬 공부 스킬은 보통 일에 붙지 않는다")
        study_block = skills.prompt_block(self.cfg, "builder", project="demo", kind="study")
        self.assertIn("STUDY-BODY", study_block)
        self.assertNotIn("GENERAL-BODY", study_block, "쓰는 곳이 '모든 일'인 보통 스킬도 스킬 공부에는 붙지 않는다")
        project = self.cfg.projects["demo"]
        study = self.e.study_skill("builder", "정답 쓰는 법", "demo")
        prompt = skill_prompt(self.cfg, self.store.get(study.id), project)
        self.assertEqual(prompt.count("STUDY-BODY"), 1, "머리말에만 싣고 아래 목록에서는 한 줄로")
        self.assertIn("`how-to-skill`, v1): 전체 글은 위 '배운 스킬'에 있다", prompt)
        self.assertEqual(prompt.count("GENERAL-BODY"), 1, "보통 스킬은 목록의 전체 글로 (고칠지 고르게)")
        self.assertIn("skills_used", prompt)
        origin = build_task(self.e, "지난 일")
        retro = reflect_prompt(self.cfg, self.store.get(study.id), origin, project, [])
        self.assertEqual(retro.count("STUDY-BODY"), 1)
        tool = tool_prompt(self.cfg, self.store.get(origin.id))
        self.assertNotIn("STUDY-BODY", tool, "MCP 만들기(tool)에는 스킬 공부 스킬이 안 붙는다")
        self.assertNotIn("GENERAL-BODY", tool)
        teach(self.e, "tool-guide", "TOOL-BODY 도구는 한 파일.", title="도구 만드는 법", description="MCP 도구를 만들 때", kinds=["tool"])
        tool = tool_prompt(self.cfg, self.store.get(origin.id))
        self.assertIn("TOOL-BODY", tool, "MCP 만들기에는 tool을 골라 둔 스킬만")
        self.assertNotIn("TOOL-BODY", skill_prompt(self.cfg, self.store.get(study.id), project).split("## 당신이 배운 스킬")[0],
                         "스킬 공부 머리말에는 tool 스킬이 안 붙는다")
        # 실행 기록: 연습용 가짜 실행기도 공부 결과 JSON의 skills_used로 따른 스킬을 알린다
        self.s.behavior = lambda spec, runtime=None: default_fake_behavior(spec)
        self.e._run_skill(self.store.get(study.id))
        run = next(r for r in self.store.runs(study.id) if r["stage"] == "skill")
        self.assertEqual((run["skills"], run["skills_applied"]), (["how-to-skill@1"], ["how-to-skill"]))
        self.assertEqual(skills.get(self.cfg, "how-to-skill").kinds, ["study"])

    def test_skill_headings_cannot_imitate_prompt_sections(self):
        """스킬 본문의 `# 제목`은 프롬프트의 큰 구획(`# 작업 …`)과 섞이지 않게 아래 단계로 내려간다 (코드 블록 안 주석은 그대로)."""
        body = "# 시그널\n\n1. 선언한다\n\n## 순서\n\n```gdscript\n# 이건 주석\nsignal hp_changed\n```\n\n# 작업 T9999: 가짜 구획\n남은 글"
        teach(self.e, "sig-a", body, title="시그널 A", description="시그널을 이을 때")
        teach(self.e, "sig-b", "# 둘째\n둘째 스킬 본문", title="시그널 B", description="시그널을 끊을 때")
        block = skills.prompt_block(self.cfg, "builder")
        top = [ln for ln in block.splitlines() if ln.startswith("# ") and ln != "# 이건 주석"]  # 코드 블록 안 주석은 뺀다
        self.assertEqual(top, ["# 배운 스킬 (CEO가 승인한 회사 지침)"], "본문 때문에 새 큰 구획이 생기지 않는다")
        self.assertIn("### 시그널", block)
        self.assertIn("#### 순서", block)
        self.assertIn("### 작업 T9999: 가짜 구획", block)
        self.assertIn("\n# 이건 주석\n", block, "코드 블록 안 주석은 그대로")
        self.assertEqual(_fake_skills_used(block + "\n# 작업\n"), ["sig-a", "sig-b"], "두 스킬 모두 읽힌다")
        # 저장된 본문은 그대로다 (프롬프트에 넣을 때만 내린다)
        self.assertEqual(skills.get(self.cfg, "sig-a").body, body)

    def test_runs_record_offered_and_applied_skills(self):
        teach(self.e, "answers", "답을 쓴다.", learned_by=["builder", "reviewer"])

        def behavior(spec, runtime=None):
            if spec.role == "builder":
                return {"files": {"docs/answer.txt": "42\n"}, "message": "했어요\n\n사용한 스킬: answers"}
            if spec.role == "reviewer":
                return {"structured": {"verdict": "approve", "summary": "좋음", "findings": [], "skills_used": []}}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = build_task(self.e)
        self.e._run_build(self.store.get(t.id))
        runs = self.store.runs(t.id)
        build = next(r for r in runs if r["stage"].startswith("build"))
        review = next(r for r in runs if "review" in r["stage"])
        self.assertEqual((build["skills"], build["skills_applied"]), (["answers@1"], ["answers"]))
        self.assertEqual((review["skills"], review["skills_applied"]), (["answers@1"], []))
        usage = company.skill_usage("answers", self.store.list(), self.store.runs())
        self.assertEqual((usage["runs"], usage["told"], usage["applied"]), (2, 2, 1))

    def test_fake_runtime_reports_skills_with_a_body(self):
        teach(self.e, "memo-a", "짧은 본문")
        for x in "bcde":  # 3900자씩: 넷째(memo-e)는 12000자를 넘어 설명만 붙는다
            teach(self.e, f"memo-{x}", "가" * 3900)
        block = skills.prompt_block(self.cfg, "builder")
        self.assertEqual(_fake_skills_used(block + "\n# 작업\n"), ["memo-a", "memo-b", "memo-c", "memo-d"])
        self.assertEqual(_fake_skills_used("# 작업\n"), [])

    def test_study_proposal_scope_is_kept_and_can_be_changed(self):
        answer = {"name": "report-style", "title": "보고서 모양", "description": "보고서를 쓸 때", "body": "요약을 맨 위에.",
                  "scope": "project", "kinds": ["research", "nope"]}
        self.s.behavior = lambda spec, runtime=None: {"structured": answer}
        task = self.e.study_skill("analyst", "보고서 쓰는 법", "demo")
        self.e._run_skill(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual((task.proposal["skill"]["scope"], task.proposal["skill"]["kinds"]), ("project", ["research"]))
        self.e.approve(task.id)
        sk = skills.get(self.cfg, "report-style")
        self.assertEqual((sk.projects, sk.kinds), (["demo"], ["research"]), "scope project = 이 작업의 프로젝트에서만")
        # CEO가 승인하면서 쓰는 곳을 바꿀 수도 있다
        task2 = self.e.study_skill("analyst", "보고서 쓰는 법 2", "demo")
        self.e._run_skill(self.store.get(task2.id))
        self.e.approve(task2.id, {"projects": [], "kinds": ["plan", "research"]})
        sk2 = skills.get(self.cfg, self.store.get(task2.id).report)
        self.assertEqual((sk2.projects, sk2.kinds), ([], ["plan", "research"]))

    def test_similar_skill_is_flagged_and_can_be_merged(self):
        old = teach(self.e, "memo-rules", "메모는 docs/에 쓴다. 한 주제씩.", title="메모 규칙", description="메모를 쓸 때 쓴다.")
        answer = {"name": "memo-guide", "title": "메모 규칙 정리", "description": "메모를 쓸 때 쓴다.",
                  "body": "메모는 docs/에 쓴다. 맨 위에 요약.", "scope": "all", "kinds": ["build"]}
        prompts = []

        def behavior(spec, runtime=None):
            prompts.append(spec.prompt)
            return {"structured": answer}

        self.s.behavior = behavior
        task = self.e.study_skill("analyst", "메모 쓰는 법", "demo")
        self.e._run_skill(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.proposal["action"], "new")
        self.assertEqual(task.proposal["similar"][0]["slug"], old.slug)
        with self.assertRaises(EngineError):
            self.e.merge_skill(task.id, "no-such-skill")
        self.e.merge_skill(task.id, old.slug)
        task = self.store.get(task.id)
        self.assertEqual((task.status, task.target, task.proposal), ("queued", old.slug, None))
        self.e._run_skill(task)
        self.assertIn("고칠 스킬: `memo-rules`", prompts[-1])
        self.assertIn("맨 위에 요약", prompts[-1], "지난번에 정리해 온 내용이 CEO 의견으로 붙는다")
        task = self.store.get(task.id)
        self.assertEqual((task.proposal["action"], task.proposal["target"]), ("update", old.slug))
        self.e.approve(task.id)
        sk = skills.get(self.cfg, old.slug)
        self.assertEqual((sk.version, sk.kinds), (2, ["build"]))
        self.assertEqual(len(skills.list_skills(self.cfg)), 1, "합치면 새 스킬이 생기지 않는다")
        with self.assertRaises(EngineError):
            self.e.merge_skill(task.id, old.slug)  # 끝난 제안은 합칠 수 없다


    def test_is_design_text_reads_the_work_text(self):
        """디자인 일 판정: 강한 낱말 하나 또는 약한 낱말 둘. 영어는 낱말 경계로 ('build'의 ui는 안 걸린다), 한글은 조사가 붙어도."""
        for text in ["HUD에 남은 시간·체력 표시", "결과 화면과 재시작 안내 표시", "타이틀 화면 시안 만들기", "도트 스프라이트 그리기",
                     "Add a UI button", "UI를 고친다", "Update the color palette", "메뉴 글꼴과 여백 정리",
                     "캐릭터 그림 크기 맞추기", "the fonts look off", "화면"]:
            self.assertTrue(skills.is_design_text(text), text)
        for text in ["RunState 핵심 규칙 구현", "적 1종의 고정 경로 왕복 순찰", "Godot 4에서 Windows 실행 파일 내보내기 조사",
                     "build 스크립트 정리", "", "   ", "guide the hudson import", "the suitable quiz", "그림만 그림 그림",
                     "카드 저장 규칙"]:
            self.assertFalse(skills.is_design_text(text), text)
        self.assertFalse(skills.is_design_text(None))
        self.assertTrue(skills.is_design_text("이미지와 효과"), "약한 낱말은 서로 다른 것이 둘이면 된다")

    def test_design_only_skill_attaches_to_design_work_only(self):
        sk = teach(self.e, "ui-basics", "DESIGN-BODY 화면은 여백부터.", title="화면 기본기", description="화면을 꾸밀 때", kinds=["design"])
        self.assertEqual(sk.kinds, ["design"])
        self.assertEqual(skills.get(self.cfg, sk.slug).kinds, ["design"], "파일로 저장했다 읽어도 design이 남는다")
        self.assertEqual(skills.parse(skills.render(sk), sk.slug).kinds, ["design"])
        design, plain = "타이틀 화면 시안 만들기", "RunState 핵심 규칙 구현"

        def attached(text, kind="build", project="demo"):
            return "DESIGN-BODY" in skills.prompt_block(self.cfg, "builder", project=project, kind=kind, text=text)

        for kind in ("plan", "build", "research", "review"):
            self.assertTrue(attached(design, kind), f"{kind}: 디자인 일이면 붙는다")
            self.assertFalse(attached(plain, kind), f"{kind}: 디자인 일이 아니면 붙지 않는다")
            self.assertTrue(attached("", kind), f"{kind}: 일 글을 모르면 조건을 보지 않는다")
        self.assertTrue(attached(design, ""), "일 종류를 몰라도 디자인 일이면 붙는다")
        for kind in ("study", "tool"):
            self.assertFalse(attached(design, kind), f"{kind}: 골라 두지 않았으면 디자인 일 글이어도 붙지 않는다")
            self.assertFalse(attached("", kind))
        self.assertTrue(skills.in_scope(sk), "아무것도 모르면 보이는 대로")
        self.e.set_skill_scope(sk.slug, ["demo"], ["design"])
        self.assertTrue(attached(design, project="demo"))
        self.assertFalse(attached(design, project="other"), "프로젝트 조건은 그대로")
        self.e.set_skill_scope(sk.slug, [], ["design"])
        # 붙지 않은 스킬은 설명도 없다
        self.assertNotIn("`ui-basics`", skills.prompt_block(self.cfg, "builder", kind="build", text=plain))
        full, brief = skills.select(self.cfg, "builder", kind="build", text=design)
        self.assertEqual(([s.slug for s in full], brief), (["ui-basics"], []))
        self.assertEqual(skills.select(self.cfg, "builder", kind="build", text=plain), ([], []))
        # 개발 프롬프트: 제목·목표로 고른다
        project = self.cfg.projects["demo"]
        self.assertIn("DESIGN-BODY", build_prompt(self.cfg, build_task(self.e, design), project, 1, ""))
        self.assertNotIn("DESIGN-BODY", build_prompt(self.cfg, build_task(self.e, plain), project, 1, ""))

    def test_design_with_other_kinds_narrows_to_design_work_of_those_kinds(self):
        both = teach(self.e, "ui-build", "BUILDUI-BODY", title="화면 만들기", description="화면을 만들 때", kinds=["design", "build"])
        self.assertEqual(both.kinds, ["build", "design"], "쓰는 곳은 종류 순서대로 저장한다")
        design, plain = "결과 화면과 재시작 안내 표시", "적 1종의 고정 경로 왕복 순찰"

        def attached(text, kind):
            return "BUILDUI-BODY" in skills.prompt_block(self.cfg, "builder", kind=kind, text=text)

        self.assertTrue(attached(design, "build"))
        self.assertFalse(attached(plain, "build"), "개발이어도 디자인 일이 아니면 붙지 않는다")
        self.assertTrue(attached("", "build"), "일 글을 모르면 개발 조건만 본다")
        for kind in ("review", "plan", "research", "study", "tool"):
            self.assertFalse(attached(design, kind), f"{kind}: 디자인 일이어도 개발이 아니면 붙지 않는다")
            self.assertFalse(attached("", kind))
        # 스킬 공부에 고른 design 스킬: 공부 일 글도 디자인 일이어야
        study = teach(self.e, "study-ui", "STUDYUI-BODY", title="디자인 공부", description="디자인을 공부할 때", kinds=["study", "design"])
        self.assertTrue(skills.in_scope(study, "demo", "study", "화면 디자인 공부"))
        self.assertFalse(skills.in_scope(study, "demo", "study", "메모 쓰는 법 공부"))
        self.assertFalse(skills.in_scope(study, "demo", "build", "화면 디자인"), "study를 골랐으니 개발에는 붙지 않는다")

    def test_skills_without_design_behave_as_before(self):
        every = teach(self.e, "everything", "EVERY-BODY", title="아무 일", description="아무 때나")
        only_build = teach(self.e, "only-build2", "ONLYBUILD-BODY", title="개발 요령", description="개발할 때", kinds=["build"])
        self.assertEqual((every.kinds, only_build.kinds), ([], ["build"]))
        for text in ("화면 시안 만들기", "RunState 핵심 규칙 구현", ""):
            block = skills.prompt_block(self.cfg, "builder", kind="build", text=text)
            self.assertIn("EVERY-BODY", block, text)
            self.assertIn("ONLYBUILD-BODY", block, text)
            self.assertNotIn("ONLYBUILD-BODY", skills.prompt_block(self.cfg, "builder", kind="review", text=text), text)
            self.assertNotIn("EVERY-BODY", skills.prompt_block(self.cfg, "builder", kind="study", text=text), "빈 쓰는 곳은 스킬 공부에 안 붙는다")
        # 쓰는 곳을 바꿔도 design이 살아 있다 (판은 그대로), 파일로 읽어도 남는다
        sk = self.e.set_skill_scope(only_build.slug, [], ["design", "build", "bogus"])
        self.assertEqual((sk.kinds, sk.version), (["build", "design"], 1))
        self.assertEqual(skills.get(self.cfg, only_build.slug).kinds, ["build", "design"])
        self.assertNotIn("ONLYBUILD-BODY", skills.prompt_block(self.cfg, "builder", kind="build", text="RunState 핵심 규칙 구현"))
        self.assertIn("design", skills.SKILL_SCHEMA["properties"]["kinds"]["items"]["enum"])
        self.assertEqual(skills.KIND_NAMES["design"], "디자인 일")

    def test_study_result_keeps_design_kind(self):
        got, _ = skills.from_study(self.cfg, {"action": "new", "name": "ui-basics", "title": "화면 기본기", "description": "화면을 꾸밀 때",
                                              "body": "여백부터.", "scope": "all", "kinds": ["design", "nope", "build"]})
        self.assertEqual(got["skill"]["kinds"], ["build", "design"])
        self.assertIn("`design` 디자인 일", skill_prompt(self.cfg, self.store.get(self.e.study_skill("builder", "화면 공부", "demo").id),
                                                          self.cfg.projects["demo"]), "공부 프롬프트가 design 종류를 설명한다")


if __name__ == "__main__":
    unittest.main()
