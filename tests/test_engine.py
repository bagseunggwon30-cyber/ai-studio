"""작업 흐름 엔진 테스트 (가짜 실행기 + 실제 git + 실제 신뢰 검사 명령)."""

import threading
import time
import unittest

from tests.helpers import TempStudio, default_behavior
from studio import gitops
from studio.engine import Engine, EngineError
from studio.runtimes import RunResult


def wait_for(cond, timeout=5.0):
    """고정 sleep 대신 조건이 참이 될 때까지 기다린다 (부하가 있을 때 흔들리지 않게)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def build_task(e, **kw):
    data = {"project": "demo", "kind": "build", "title": "정답", "brief": "docs/answer.txt에 42", "acceptance": ["검사 통과"], "allowed_paths": ["docs/**"]}
    data.update(kw)
    return e.create_task(data)


class EngineFlow(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.e = self.s.engine
        self.store = self.s.store

    def tearDown(self):
        self.s.close()

    def run_build(self, task_id):
        self.e._run_build(self.store.get(task_id))
        return self.store.get(task_id)

    # ---- 지시 → 기획 → 결재 → 구현 → 검증 → 리뷰 → 병합
    def test_empty_plan_keeps_explanation_and_questions(self):
        response = {"summary": "현재 프로젝트는 게임이며 AI Studio 화면 소스가 없습니다.", "tasks": [],
                    "risks": ["다른 프로젝트를 수정할 수 있습니다."],
                    "questions": ["수정할 프로젝트를 확인해 주세요."], "skills_used": []}
        self.s.behavior = lambda spec, runtime=None: {"structured": response}
        plan = self.e.submit_directive("업무일지 화면 수정", "demo")
        self.e._run_plan(self.store.get(plan.id))
        plan = self.store.get(plan.id)
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.report, response["summary"])
        self.assertEqual(plan.proposal["questions"], response["questions"])
        self.assertEqual(plan.proposal["risks"], response["risks"])
        self.assertEqual(plan.proposal["tasks"], [])
        self.assertIn(response["questions"][0], plan.blocked_reason)
        self.assertTrue(plan.summary()["has_proposal"])
        self.assertEqual(plan.children, [])
        with self.assertRaises(EngineError):
            self.e.approve(plan.id)

    def test_plan_question_reply_starts_fresh_readonly_plan(self):
        response = {"summary": "확인이 필요합니다.", "tasks": [], "risks": [],
                    "questions": ["어느 화면을 고칠까요?"], "skills_used": []}
        self.s.behavior = lambda spec, runtime=None: {"structured": response}
        plan = self.e.submit_directive("화면 개선", "demo")
        self.e._run_plan(self.store.get(plan.id))
        plan = self.store.get(plan.id)
        self.assertTrue(plan.needs_plan_input)
        self.assertEqual(plan.summary()["status_label"], "답변 필요")
        self.assertEqual(len(self.store.runs(plan.id)), 1)
        answer = "현재 demo 프로젝트의 정답 화면을 고쳐 주세요."
        self.e.request_changes(plan.id, answer)
        queued = self.store.get(plan.id)
        self.assertEqual(queued.status, "queued")
        self.assertTrue(queued.run_requested)
        self.assertFalse(queued.needs_plan_input)
        self.assertEqual(queued.feedback[-1]["text"], answer)
        self.assertEqual(self.e.journal.read(plan.id), {})
        from tests.helpers import default_behavior
        prompts = []
        def clarified(spec, runtime=None):
            prompts.append(spec.prompt)
            return default_behavior(spec, runtime)
        self.s.behavior = clarified
        self.e._run_plan(queued)
        planned = self.store.get(plan.id)
        self.assertEqual(planned.status, "awaiting_approval")
        self.assertEqual(len(self.store.runs(plan.id)), 2)
        self.assertIn(answer, prompts[0])
        self.assertTrue(planned.proposal["tasks"])
        self.assertEqual(planned.children, [])

    def test_plan_questions_require_answer_instead_of_plain_retry(self):
        self.s.behavior = lambda spec, runtime=None: {"structured": {
            "summary": "질문", "tasks": [], "risks": [], "questions": ["대상은?"], "skills_used": []}}
        plan = self.e.submit_directive("확인", "demo")
        self.e._run_plan(self.store.get(plan.id))
        checkpoint = self.e.journal.read(plan.id)
        with self.assertRaisesRegex(EngineError, "답변"):
            self.e.retry(plan.id)
        with self.assertRaises(EngineError):
            self.e.request_changes(plan.id, "답변", by="supervisor:fixture")
        self.assertEqual(self.store.get(plan.id).status, "blocked")
        self.assertEqual(self.e.journal.read(plan.id), checkpoint)
        self.assertEqual(len(self.store.runs(plan.id)), 1)
        self.e.journal.write(plan.id, "external-write", status="unknown_outcome", effect="write")
        with self.assertRaisesRegex(EngineError, "실행 여부 불확실"):
            self.e.request_changes(plan.id, "답변")
        self.assertEqual(self.store.get(plan.id).feedback, [])

    def test_plan_reply_does_not_resume_errors_or_invalid_proposals(self):
        plan = self.e.submit_directive("기획", "demo")
        self.store.block(plan, "연결 실패")
        with self.assertRaises(EngineError):
            self.e.request_changes(plan.id, "답변")
        plan = self.store.get(plan.id)
        plan.proposal = {"tasks": [], "questions": ["대상은?"], "problems": ["출력 형식 오류"]}
        self.store.save(plan)
        self.assertFalse(plan.needs_plan_input)
        with self.assertRaises(EngineError):
            self.e.request_changes(plan.id, "답변")
        self.assertEqual(self.store.get(plan.id).status, "blocked")

    def test_empty_plan_always_has_a_reason(self):
        response = {"summary": "", "tasks": [], "risks": [], "questions": [], "skills_used": []}
        self.s.behavior = lambda spec, runtime=None: {"structured": response}
        plan = self.e.submit_directive("기획", "demo")
        self.e._run_plan(self.store.get(plan.id))
        plan = self.store.get(plan.id)
        self.assertIn("프로젝트를 확인", plan.blocked_reason)
        self.assertFalse(plan.blocked_reason.endswith(": "))
        self.assertIsNotNone(plan.proposal)

    def test_full_flow(self):
        plan = self.e.submit_directive("정답 파일을 만들어", "demo")
        self.e._run_plan(self.store.get(plan.id))
        plan = self.store.get(plan.id)
        self.assertEqual(plan.status, "awaiting_approval")
        self.assertEqual(len(plan.proposal["tasks"]), 2)
        self.assertEqual(plan.proposal["tasks"][1]["allowed_paths"], ["docs/**"], "보호 경로는 허용 목록에서 빠진다")

        self.e.approve(plan.id, {"selected": [0, 1], "edits": {"0": {"title": "정답 파일 작성"}}})
        plan = self.store.get(plan.id)
        self.assertEqual(plan.status, "done")
        c1, c2 = [self.store.get(i) for i in plan.children]
        self.assertEqual(c1.title, "정답 파일 작성")
        self.assertEqual(c2.depends_on, [c1.id])

        self.assertIsNone(self.e._next_job(), "자동 진행이 꺼져 있으면 실행 요청 전엔 고르지 않는다")
        self.e.request_run(c2.id)
        self.assertIsNone(self.e._next_job(), "선행 작업이 안 끝났으면 고르지 않는다")
        self.e.request_run(c1.id)
        self.assertEqual(self.e._next_job().id, c1.id)

        c1 = self.run_build(c1.id)
        self.assertEqual(c1.status, "awaiting_approval", c1.blocked_reason)
        self.assertEqual(c1.qa["verdict"], "pass")
        self.assertEqual(c1.qa["passed"], 2)
        self.assertEqual(c1.qa["candidate_sha"], c1.candidate_sha)
        self.assertEqual(c1.review["verdict"], "approve")
        self.assertFalse(c1.review["cross_model"], "Claude disabled: separate Codex review, not cross-provider")
        self.assertNotEqual(gitops.head(self.s.repo, "main"), c1.candidate_sha, "결재 전에는 main이 그대로")
        self.assertEqual(self.e.waiting_reason(self.store.get(c2.id), self.store.list()), f"선행 작업 {c1.id} 완료 대기")

        self.e.approve(c1.id)
        c1 = self.store.get(c1.id)
        self.assertEqual(c1.status, "done")
        self.assertEqual(gitops.head(self.s.repo, "main"), c1.candidate_sha)
        self.assertEqual((self.s.repo / "docs" / "answer.txt").read_text(encoding="utf-8").strip(), "42")
        self.assertIsNone(c1.worktree)
        self.assertEqual(self.e._next_job().id, c2.id)

    def test_qa_fail_then_fix_with_feedback(self):
        prompts = []

        def behavior(spec, runtime=None):
            if spec.role == "builder":
                prompts.append(spec.prompt)
                return {"files": {"docs/answer.txt": "41\n" if len(prompts) == 1 else "42\n"}}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.assertEqual(t.attempts, 2)
        self.assertIn("answer_is_42", prompts[1], "두 번째 시도 프롬프트에 실패한 테스트가 들어간다")

    def test_qa_fail_twice_blocks(self):
        self.s.behavior = lambda spec, rt=None: {"files": {"docs/answer.txt": "41\n"}} if spec.role == "builder" else default_behavior(spec)
        main_before = gitops.head(self.s.repo, "main")
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "blocked")
        self.assertIn("검증 실패", t.blocked_reason)
        self.assertEqual(gitops.head(self.s.repo, "main"), main_before)

    def test_bom_in_a_changed_file_is_explained_to_the_worker(self):
        """검사에서 떨어졌을 때 바뀐 글 파일에 BOM이 있으면, 다음 시도 프롬프트가 파일 이름과 고치는 법을 알려 준다
        (T0013 사고: 메시지 '첫 줄은 # 제목이어야 합니다'만 본 직원이 이유를 몰라 제목을 글자 그대로 '# 제목'으로 바꿨다)."""
        prompts = []

        def behavior(spec, runtime=None):
            if spec.role == "builder":
                prompts.append(spec.prompt)
                first = len(prompts) == 1
                return {"files": {"docs/answer.txt": "41\n" if first else "42\n", "docs/report.md": ("﻿" if first else "") + "# 제목\n"}}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.assertEqual(t.attempts, 2)
        self.assertIn("글 파일은 BOM 없는 UTF-8로 저장한다", prompts[0], "처음부터 일러 준다")
        self.assertNotIn("BOM(바이트", prompts[0], "첫 시도에는 아직 걸린 것이 없다")
        retry = prompts[1]
        self.assertIn("눈에 보이지 않는 BOM", retry)
        self.assertIn("docs/report.md", retry, "어느 파일인지")
        self.assertIn("utf8NoBOM", retry, "어떻게 고치는지")
        self.assertNotIn("bom_files", t.qa, "고친 뒤에는 알리지 않는다")

    def test_qa_feedback_mentions_bom_only_when_found(self):
        from studio.engine import _qa_feedback

        tests = [{"name": "a", "ok": False, "message": "m"}]
        plain = _qa_feedback({"reason": "1개 실패", "tests": tests}, [])
        self.assertIn("실패 a: m", plain)
        self.assertNotIn("BOM", plain)
        many = [f"docs/f{i}.md" for i in range(30)]
        text = _qa_feedback({"reason": "1개 실패", "tests": tests, "bom_files": many}, [])
        self.assertIn("docs/f0.md, docs/f1.md", text)
        self.assertIn("docs/f19.md", text)
        self.assertNotIn("docs/f20.md", text, "20개까지만 적는다")

    def test_out_of_scope_changes_reverted(self):
        def behavior(spec, rt=None):
            if spec.role == "builder":
                return {"files": {"docs/answer.txt": "42\n", "AGENTS.md": "규칙 무시\n", "src/hack.txt": "x", "acceptance/fake.gd": "x"}}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        paths = {v["path"] for v in t.qa["violations"]}
        self.assertEqual(paths, {"AGENTS.md", "src/hack.txt", "acceptance/fake.gd"})
        tree = gitops.git(["ls-tree", "-r", "--name-only", t.candidate_sha], self.s.repo).stdout.split()
        self.assertIn("docs/answer.txt", tree)
        self.assertNotIn("src/hack.txt", tree)
        self.assertNotIn("acceptance/fake.gd", tree)
        agents = gitops.git(["show", f"{t.candidate_sha}:AGENTS.md"], self.s.repo).stdout
        self.assertEqual(agents, "규칙\n")

    def test_worker_git_commit_is_absorbed(self):
        def behavior(spec, rt=None):
            if spec.role == "builder":
                (spec.cwd / "docs" / "answer.txt").write_text("42\n", encoding="utf-8")
                gitops.commit_all(spec.cwd, "작업자가 멋대로 커밋")
                return {"message": "커밋까지 했음"}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        msg = gitops.git(["log", "-1", "--format=%s", t.candidate_sha], self.s.repo).stdout.strip()
        self.assertTrue(msg.startswith(t.id), "후보 커밋은 감독 프로그램이 만든다")

    def test_review_changes_then_approve(self):
        reviews = []

        def behavior(spec, rt=None):
            if spec.role == "reviewer":
                reviews.append(1)
                if len(reviews) == 1:
                    return {"structured": {"verdict": "approve", "summary": "하나 막힘", "findings": [{"severity": "blocking", "file": "docs/answer.txt", "issue": "줄바꿈", "suggestion": "고치기"}]}}
                return {"structured": {"verdict": "approve", "summary": "좋음", "findings": []}}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.assertEqual(t.attempts, 2, "blocking 지적이 있으면 approve라고 해도 수정 요청으로 본다")

    def test_reviewer_fallback(self):
        def behavior(spec, runtime=None):
            if spec.role == "reviewer" and runtime == "claude":
                return {"error_kind": "error", "message": "claude 실패"}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval")
        self.assertEqual(t.review["runtime"], "codex")
        self.assertFalse(t.review["cross_model"])

    def test_reviewer_unavailable_still_goes_to_ceo(self):
        def behavior(spec, runtime=None):
            if spec.role == "reviewer":
                return {"error_kind": "error", "message": "실패"}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval")
        self.assertEqual(t.review["verdict"], "unavailable")

    def test_quota_blocks_and_stops_company(self):
        self.s.behavior = lambda spec, rt=None: {"error_kind": "quota"} if spec.role == "builder" else default_behavior(spec)
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "blocked")
        self.assertIn("한도", t.blocked_reason)
        self.assertTrue(self.e.status()["stopped"])
        self.assertTrue(self.store.get_state()["stopped"])

    def test_quota_opens_login_window_once_and_login_done_resumes(self):
        opened = []
        self.e.login_opener = opened.append
        self.s.behavior = lambda spec, rt=None: {"error_kind": "quota"} if spec.role == "builder" else default_behavior(spec)
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "blocked")
        self.assertEqual(opened, ["codex"], "솔이 끼운 AI(Codex)의 로그인 창")
        need = self.e.status()["needs_login"]
        self.assertEqual((need["runtime"], need["reason"], need["opened"], need["task"]), ("codex", "quota", True, t.id))
        self.assertTrue(self.e.status()["stopped"])
        # 또 한도에 걸려도 창은 한 번만
        self.e._fail_run(self.store.get(t.id), RunResult(False, "codex", "", 1, 0.0, error_kind="quota"), "builder")
        self.assertEqual(opened, ["codex"])
        # 다시 열기 단추는 언제든
        self.e.open_login()
        self.assertEqual(opened, ["codex", "codex"])
        # 로그인했어요 → 표시 지움, 재개, 한도로 막힌 일 다시
        self.s.behavior = default_behavior
        done = self.e.login_done()
        self.assertEqual(done["retried"], [t.id])
        self.assertIsNone(self.e.status()["needs_login"])
        self.assertFalse(self.e.status()["stopped"])
        self.assertIn(self.store.get(t.id).status, ("ready", "queued"))

    def test_login_error_also_stops_and_asks(self):
        opened = []
        self.e.login_opener = opened.append
        self.s.behavior = lambda spec, rt=None: {"error_kind": "login"} if spec.role == "builder" else default_behavior(spec)
        self.run_build(build_task(self.e).id)
        self.assertEqual(opened, ["codex"])
        self.assertTrue(self.e.status()["stopped"])
        self.assertEqual(self.e.status()["needs_login"]["reason"], "login")

    def test_no_window_without_opener(self):
        # 시험·연습용 회사(login_opener 없음)에서는 창을 띄우지 않고 표시만 한다
        self.s.behavior = lambda spec, rt=None: {"error_kind": "quota"} if spec.role == "builder" else default_behavior(spec)
        self.run_build(build_task(self.e).id)
        self.assertFalse(self.e.status()["needs_login"]["opened"])
        with self.assertRaises(EngineError):  # 연습용에서 '로그인 창 열기'를 눌러도 진짜 계정을 로그아웃시키지 않는다
            self.e.open_login("codex")

    def test_emergency_stop_kills_running(self):
        self.s.behavior = lambda spec, rt=None: {"delay": 10, "files": {"docs/answer.txt": "42\n"}} if spec.role == "builder" else default_behavior(spec)
        t = build_task(self.e)
        th = threading.Thread(target=self.e._run_build, args=(self.store.get(t.id),))
        th.start()
        self.assertTrue(wait_for(lambda: (self.e.current() or {}).get("task") == t.id), "구현 실행이 시작되지 않음")
        self.assertEqual(self.store.get(t.id).status, "running")
        started = time.monotonic()
        self.e.emergency_stop()
        th.join(5)
        self.assertFalse(th.is_alive())
        self.assertLess(time.monotonic() - started, 3)
        t = self.store.get(t.id)
        self.assertEqual(t.status, "blocked")
        self.assertIn("긴급 정지", t.blocked_reason)
        self.assertEqual(gitops.staged_changes(self.s.cfg.worktrees_dir / "demo" / t.id, t.base_sha), [], "중단된 작업의 변경은 남기지 않는다")

    def test_cancel_running_task(self):
        self.s.behavior = lambda spec, rt=None: {"delay": 10} if spec.role == "builder" else default_behavior(spec)
        t = build_task(self.e)
        th = threading.Thread(target=self.e._run_build, args=(self.store.get(t.id),))
        th.start()
        self.assertTrue(wait_for(lambda: (self.e.current() or {}).get("task") == t.id), "구현 실행이 시작되지 않음")
        self.e.cancel(t.id)
        th.join(5)
        t = self.store.get(t.id)
        self.assertEqual(t.status, "cancelled")
        self.assertIsNone(t.worktree)

    def test_recover_blocks_stale_running(self):
        t = build_task(self.e)
        self.store.transition(t, "running")
        Engine(self.s.cfg, self.store).recover()
        t = self.store.get(t.id)
        self.assertEqual(t.status, "blocked")
        self.assertIn("재시작", t.blocked_reason)

    def test_merge_refused_if_main_moved_then_retry(self):
        t = self.run_build(build_task(self.e).id)
        self.assertEqual(t.status, "awaiting_approval")
        (self.s.repo / "README.md").write_text("# demo 2\n", encoding="utf-8")
        gitops.commit_all(self.s.repo, "CEO 직접 수정")
        self.e.approve(t.id)
        t = self.store.get(t.id)
        self.assertEqual(t.status, "blocked")
        self.assertIn("main", t.blocked_reason)
        self.e.retry(t.id)
        t = self.run_build(t.id)
        self.assertEqual(t.status, "awaiting_approval", t.blocked_reason)
        self.assertEqual(t.base_sha, gitops.head(self.s.repo, "main"))
        self.e.approve(t.id)
        self.assertEqual(self.store.get(t.id).status, "done")

    def test_merge_refused_if_qa_does_not_match_candidate(self):
        t = self.run_build(build_task(self.e).id)
        t.candidate_sha = t.base_sha
        self.store.save(t)
        with self.assertRaises(EngineError):
            self.e.approve(t.id)

    def test_request_changes_reruns(self):
        prompts = []

        def behavior(spec, rt=None):
            if spec.role == "builder":
                prompts.append(spec.prompt)
                return {"files": {"docs/answer.txt": "42\n", "docs/notes.md": f"메모 {len(prompts)}\n"}}
            return default_behavior(spec)

        self.s.behavior = behavior
        t = self.run_build(build_task(self.e).id)
        self.e.request_changes(t.id, "메모를 더 자세히")
        t = self.store.get(t.id)
        self.assertEqual(t.status, "ready")
        self.assertTrue(t.run_requested)
        t = self.run_build(t.id)
        self.assertEqual(t.status, "awaiting_approval")
        self.assertIn("메모를 더 자세히", prompts[-1])

    def test_daily_cap(self):
        self.s.cfg.limits["max_runs_per_day"] = 0
        t = build_task(self.e)
        self.e.request_run(t.id)
        self.assertIsNone(self.e._next_job())
        t = self.run_build(t.id)
        self.assertEqual(t.status, "blocked")
        self.assertIn("상한", t.blocked_reason)

    def test_invalid_actions(self):
        t = build_task(self.e)
        with self.assertRaises(EngineError):
            self.e.approve(t.id)
        with self.assertRaises(EngineError):
            self.e.submit_directive("  ", "demo")
        with self.assertRaises(EngineError):
            self.e.submit_directive("무언가", "없는-프로젝트")
        with self.assertRaises(EngineError):
            self.e.create_task({"project": "demo", "title": "경로 없음", "allowed_paths": ["../x", "AGENTS.md"]})


if __name__ == "__main__":
    unittest.main()
