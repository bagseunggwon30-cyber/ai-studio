"""Local project registration and target correction; no real model calls."""
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from tests.helpers import TempStudio
from tests import test_server
from studio import gitops
from studio.checkpoints import digest
from studio.config import load_projects
from studio.engine import EngineError


def target_repo(s):
    repo = s.root / "projects" / "target"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "notes.md").write_text("target\n", encoding="utf-8")
    gitops.init_repo(repo, "main")
    gitops.commit_all(repo, "init")
    return {"key": "target", "title": "새 대상", "repo": str(repo), "main_branch": "main",
            "allowed_paths": ["docs/**"], "confirm_scope": True}


class ProjectManagement(unittest.TestCase):
    def test_fixture_canonicalizes_allocated_temp_directory(self):
        from tests import helpers
        allocate = helpers.tempfile.mkdtemp

        def noncanonical_directory(*args, **kwargs):
            path = Path(allocate(*args, **kwargs))
            return str(path / ".." / path.name)

        with patch("tests.helpers.tempfile.mkdtemp", side_effect=noncanonical_directory):
            company = TempStudio()
        try:
            self.assertEqual(company.root, company.root.resolve())
            self.assertEqual(company.root, company.cfg.root)
        finally:
            company.close()

    def setUp(self):
        self.s = TempStudio()
        self.e = self.s.engine
        self.data = target_repo(self.s)

    def tearDown(self):
        self.s.close()

    def task(self, **extra):
        return self.e.create_task({"project": "demo", "title": "문서 수정", "brief": "docs/answer.txt에 42",
                                   "acceptance": ["정답 확인"], "allowed_paths": ["docs/**"]}, **extra)

    def move(self, task, **changes):
        body = {"project": "target", "allowed_paths": ["docs/**"], "revision": digest(task.to_dict())}
        body.update(changes)
        return self.e.retarget(task.id, body)

    def test_register_persists_without_mutating_existing_config_or_repo(self):
        original = (self.s.root / "trusted/projects/demo.toml").read_bytes()
        sha = gitops.head(self.s.repo)
        self.e.register_project(self.data)
        restored = load_projects(self.s.root)["target"]
        self.assertEqual(restored.title, "새 대상")
        self.assertEqual(restored.default_allowed_paths, ["docs/**"])
        self.assertEqual(restored.qa, {})
        self.assertEqual(original, (self.s.root / "trusted/projects/demo.toml").read_bytes())
        self.assertEqual(sha, gitops.head(self.s.repo))
        self.assertEqual(self.s.store.runs(), [])

    def test_registration_rejects_bad_inputs_and_does_not_overwrite(self):
        for change in ({"key": "../bad"}, {"main_branch": "--help"}, {"main_branch": "absent"},
                       {"confirm_scope": False}, {"allowed_paths": ["../secret"]}, {"allowed_paths": "docs/**"},
                       {"allowed_paths": ["**"]}, {"qa": {"commands": [["bad"]]}}, {"repo": str(self.s.root / "data")},
                       {"allowed_paths": ["AGENTS.md"]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.e.register_project({**self.data, **change})
        self.assertNotIn("target", self.e.cfg.projects)
        self.e.register_project(self.data)
        saved = (self.s.root / "trusted/projects/target.toml").read_bytes()
        with self.assertRaises(ValueError):
            self.e.register_project(self.data)
        with self.assertRaises(ValueError):
            self.e.register_project({**self.data, "key": "alias"})
        self.assertEqual(saved, (self.s.root / "trusted/projects/target.toml").read_bytes())

    def test_self_registration_protects_company_and_runtime_data(self):
        (self.s.root / ".gitignore").write_text("projects/\ndata/\nworktrees/\n", encoding="utf-8")
        gitops.init_repo(self.s.root, "main")
        gitops.commit_all(self.s.root, "init supervisor")
        data = {**self.data, "key": "self", "repo": str(self.s.root)}
        for path in ["trusted/**", "Trusted/**", "company/**", "studio.toml", "data/**", "worktrees/**", "projects/**"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.e.register_project({**data, "allowed_paths": [path]})
        project = self.e.register_project({**data, "allowed_paths": ["ui/**", "docs/design/**"]})
        self.assertIn("trusted/**", project.all_protected())

    def test_registration_requires_ceo(self):
        with self.assertRaises(EngineError):
            self.e.register_project(self.data, by="supervisor:test")

    def test_interruption_while_copying_keeps_source_paused(self):
        self.e.register_project(self.data)
        source = self.e.submit_directive("조사", "demo")
        with patch.object(self.s.store, "create_task", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.move(source)
        self.e.recover()
        paused = self.s.store.get(source.id)
        self.assertEqual(paused.status, "blocked")
        self.assertFalse(paused.run_requested)
        copied = self.move(paused)
        self.assertEqual(copied.status, "blocked")
        self.assertEqual(len(self.s.store.list()), 2)

    def test_retarget_preserves_strict_requirements_but_no_evidence_result(self):
        self.e.register_project(self.data)
        task = self.task(extra={"requirements": [{"id": "R1", "text": "정답", "evidence": [{"type": "file", "path": "docs/answer.txt"}]}]})
        new = self.move(task)
        self.assertEqual(new.extra["requirements"], task.extra["requirements"])
        self.assertIsNone(new.qa)
        self.assertIsNone(new.review)

    def test_retarget_preserves_records_pauses_new_card_and_is_idempotent(self):
        self.e.register_project(self.data)
        task = self.task()
        self.s.store.block(task, "대상 오류")
        task = self.s.store.get(task.id)
        self.e.journal.write(task.id, "build1", status="complete", effect="external_effect", run_id="old-run")
        saved = self.e.journal.read(task.id)
        new = self.move(task)
        self.assertEqual(self.s.store.get(task.id).status, "cancelled")
        self.assertEqual(new.status, "blocked")
        self.assertFalse(new.run_requested)
        self.assertEqual(new.acceptance, task.acceptance)
        self.assertIsNone(new.candidate_sha)
        self.assertEqual(self.e.journal.read(new.id), {})
        self.assertEqual(self.e.journal.read(task.id), saved)
        self.assertEqual(self.move(task).id, new.id)
        with self.assertRaises(EngineError):
            self.move(task, allowed_paths=["docs/other.txt"])
        self.assertEqual(len(self.s.store.list()), 2)
        self.assertEqual(self.s.store.runs(), [])
        self.e.retry(new.id)
        self.assertEqual(self.s.store.get(new.id).status, "ready")

    def test_stale_revision_and_target_scope_rejected(self):
        self.e.register_project(self.data)
        task = self.task()
        for change in ({"revision": "stale"}, {"allowed_paths": ["src/**"]}, {"allowed_paths": ["AGENTS.md"]}):
            with self.subTest(change=change), self.assertRaises(EngineError if "revision" in change or "src/**" in change.get("allowed_paths", []) else ValueError):
                self.move(task, **change)
        self.assertEqual(len(self.s.store.list()), 1)

    def test_external_supervisor_tasks_cannot_expand_project_access(self):
        self.e.register_project(self.data)
        task = self.task(created_by="supervisor:test")
        with self.assertRaises(EngineError):
            self.move(task)
        with self.assertRaises(EngineError):
            self.e.retarget(task.id, {"project": "target"}, by="reviewer")

    def test_uncertain_candidate_running_and_dependencies_cannot_move(self):
        self.e.register_project(self.data)
        for field, value in [("candidate_sha", "a" * 40), ("children", ["T9999"]), ("depends_on", ["T9999"])]:
            task = self.task()
            setattr(task, field, value)
            self.s.store.save(task)
            with self.subTest(field=field), self.assertRaises(EngineError):
                self.move(self.s.store.get(task.id))
        task = self.task()
        self.e.journal.write(task.id, "build1", status="unknown_outcome", effect="external_effect")
        with self.assertRaises(EngineError):
            self.move(task)
        task = self.task()
        self.s.store.transition(task, "running")
        with self.assertRaises(EngineError):
            self.move(self.s.store.get(task.id))

    def test_dirty_worktree_is_preserved_and_move_is_denied(self):
        self.e.register_project(self.data)
        task = self.e._ensure_worktree(self.task(), self.s.cfg.projects["demo"])
        path = Path(task.worktree) / "docs/new.txt"
        path.write_text("do not discard", encoding="utf-8")
        with self.assertRaises(EngineError):
            self.move(task)
        self.assertEqual(path.read_text(encoding="utf-8"), "do not discard")

    def test_plan_copy_discards_old_proposal_and_survives_recovery_paused(self):
        self.e.register_project(self.data)
        task = self.e.submit_directive("새 대상 조사", "demo")
        task.proposal = {"questions": ["대상 확인"], "tasks": []}
        self.s.store.save(task)
        task = self.s.store.get(task.id)
        new = self.move(task)
        self.assertIsNone(new.proposal)
        self.e.recover()
        self.assertEqual(self.s.store.get(new.id).status, "blocked")
        self.e.retry(new.id)
        self.assertEqual(self.s.store.get(new.id).status, "queued")

    def test_new_target_pipeline_uses_new_repo_and_reports_qa_none(self):
        self.e.register_project(self.data)
        self.s.cfg.roles["reviewer"].runtime = "codex"
        source = self.task()
        moved = self.move(source)
        self.e.retry(moved.id)
        self.e._run_build(self.s.store.get(moved.id))
        result = self.s.store.get(moved.id)
        self.assertEqual(result.status, "awaiting_approval")
        self.assertEqual(result.qa["verdict"], "none")
        self.assertEqual(result.review["verdict"], "approve")
        self.assertFalse((self.s.repo / "docs/answer.txt").exists())
        self.assertEqual((Path(result.worktree) / "docs/answer.txt").read_text(encoding="utf-8").strip(), "42")


class ProjectAPI(unittest.TestCase):
    setUp = test_server.ServerSecurity.setUp
    tearDown = test_server.ServerSecurity.tearDown
    req = test_server.ServerSecurity.req

    def test_registration_and_retarget_require_session_and_origin(self):
        body = target_repo(self.s)
        self.assertEqual(self.req("POST", "/api/projects", body)[0].status, 403)
        headers = {"X-Studio-Token": self.srv.token}
        self.assertEqual(self.req("POST", "/api/projects", body, {**headers, "Origin": "http://evil.example"})[0].status, 403)
        self.assertEqual(self.req("POST", "/api/projects", body, headers)[0].status, 200)
        task = self.s.engine.create_task({"project": "demo", "title": "문서", "allowed_paths": ["docs/**"]})
        res, raw = self.req("GET", f"/api/tasks/{task.id}")
        payload = {"project": "target", "allowed_paths": ["docs/**"], "revision": json.loads(raw)["retarget_revision"]}
        endpoint = f"/api/tasks/{task.id}/retarget"
        self.assertEqual(self.req("POST", endpoint, payload)[0].status, 403)
        self.assertEqual(self.req("POST", endpoint, payload, headers)[0].status, 200)
        self.assertEqual(self.s.store.runs(), [])

    def test_defaults_are_read_only(self):
        before = len(self.s.store.list())
        res, raw = self.req("GET", "/api/projects/defaults")
        self.assertEqual(res.status, 200)
        self.assertEqual(json.loads(raw)["repo"], str(self.s.root))
        self.assertEqual(before, len(self.s.store.list()))
