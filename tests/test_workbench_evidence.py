"""Candidate-specific completion contracts, using only disposable companies."""
import http.client
import json
import threading
import unittest
from copy import deepcopy
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from tests.helpers import TempStudio, default_behavior
from tests.test_workbench import graph, node
from studio import evidence, gitops
from studio.engine import Engine, EngineError
from studio.server import StudioServer
from studio.util import atomic_write_json, atomic_write_text, read_json


class CompletionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.w = self.s.engine.workbench
        self.refs = [[{"type": "test", "name": "answer_is_42"}, {"type": "file", "path": "docs/answer.txt"}]]

    def tearDown(self):
        self.s.close()

    def start(self, refs=None):
        g = graph(node("a", "input", text="docs/answer.txt에 42"),
                  node("b", "implement", acceptance=["정답은 42"], evidence=self.refs if refs is None else refs),
                  node("c", "test"), node("d", "review"), node("e", "approve"), node("f", "summary"))
        body = {"title": "완료 근거", "graph": g, "project": "demo", "allowed_paths": ["docs/**"]}
        flow = self.w.save_flow(body)
        body.update(flow_id=flow["id"], flow_version=flow["version"])
        plan = self.w.plan(body)
        request = {**body, "confirmed": True, "allow_models": True, "plan_hash": plan["hash"], "request_id": uuid4().hex}
        run = self.w.start(request)
        self.rid = run["id"]
        self.w.tick()
        self.tid = self.w.run(self.rid)["nodes"]["b"]["task"]
        self.base = gitops.head(self.s.repo, "main")
        self.s.engine._run_build(self.s.store.get(self.tid))
        self.w.tick()
        return self.s.store.get(self.tid)

    def test_missing_file_and_unbound_criterion_cannot_approve_or_complete(self):
        for refs in ([], [[{"type": "file", "path": "docs/contract.txt"}]]):
            with self.subTest(refs=refs):
                task = self.start(refs)
                self.assertEqual(task.status, "awaiting_approval")
                coverage = evidence.assess(self.s.cfg, self.s.store, task)
                self.assertTrue(coverage["strict"])
                self.assertFalse(coverage["complete"])
                self.assertEqual(self.w.run(self.rid)["status"], "blocked")
                with self.assertRaises(EngineError):
                    self.s.engine.approve(task.id)
                self.assertEqual(gitops.head(self.s.repo, "main"), self.base)
                self.assertNotEqual(self.w.run(self.rid)["nodes"]["f"]["status"], "succeeded")

    def test_proven_candidate_merges_once_and_summary_preserves_complete_evidence(self):
        task = self.start()
        self.assertTrue(task.qa["evidence_digest"])
        self.assertTrue(self.s.engine.approval_status(task)["allowed"])
        with ThreadPoolExecutor(max_workers=3) as pool:
            def approve(_):
                try:
                    return self.s.engine.approve(task.id).status
                except EngineError:
                    return "rejected"
            results = list(pool.map(approve, range(3)))
        self.assertEqual(results.count("done"), 1)
        self.w.tick()
        run = self.w.run(self.rid)
        self.assertEqual(run["status"], "succeeded")
        proof = run["nodes"]["f"]["output"]["result"]
        self.assertTrue(proof["evidence"]["complete"])
        self.assertEqual(proof["evidence"]["candidate_sha"], proof["merged_sha"])
        self.assertEqual(len(self.s.store.runs()), 2)

    def test_receipt_or_snapshot_tampering_and_old_candidate_rejected(self):
        task = self.start()
        qdir = self.s.store.qa_dir / task.qa["qa_id"]
        original = read_json(qdir / "evidence.json", {})
        atomic_write_json(qdir / "evidence.json", {**original, "tests": [{"name": "forged", "ok": True}]})
        with self.assertRaises(EngineError):
            self.s.engine.approve(task.id)
        atomic_write_json(qdir / "evidence.json", original)
        atomic_write_text(qdir / "snapshot/docs/answer.txt", "99\n")
        with self.assertRaises(EngineError):
            self.s.engine.approve(task.id)
        atomic_write_text(qdir / "snapshot/docs/answer.txt", "42\n")
        task = self.s.store.get(task.id)
        task.qa = {**task.qa, "candidate_sha": self.base}
        self.s.store.save(task)
        with self.assertRaises(EngineError):
            self.s.engine.approve(task.id)
        self.assertEqual(gitops.head(self.s.repo, "main"), self.base)

    def test_revision_archives_first_candidate_and_refreshes_all_nodes_and_calls(self):
        task = self.start()
        first = deepcopy(self.w.run(self.rid))
        old_sha = task.candidate_sha
        self.s.engine.request_changes(task.id, "docs/revision.txt 추가")
        self.w.tick()
        rebuilding = self.w.run(self.rid)
        self.assertEqual(rebuilding["status"], "running")
        self.assertEqual(rebuilding["nodes"]["c"]["status"], "pending")
        self.assertEqual(rebuilding["versions"][0]["nodes"]["c"], first["nodes"]["c"])
        self.s.behavior = lambda spec, runtime: {"files": {"docs/answer.txt": "42\n", "docs/revision.txt": "revised\n"}} if spec.role == "builder" else default_behavior(spec, runtime)
        self.s.engine._run_build(self.s.store.get(task.id))
        self.w.tick()
        task = self.s.store.get(task.id)
        self.assertNotEqual(task.candidate_sha, old_sha)
        current = self.w.describe_run(self.rid)
        for key in ("b", "c", "d"):
            self.assertEqual(current["nodes"][key]["output"]["candidate_sha"], task.candidate_sha)
            self.assertEqual(current["nodes"][key]["output"]["evidence"]["candidate_sha"], task.candidate_sha)
        self.assertEqual(current["versions"][0]["candidate_sha"], old_sha)
        self.assertEqual(current["usage"], {"total": 4, "current": 2, "previous": 2, "planned_initial": 2})
        self.s.engine.approve(task.id)
        self.w.tick()
        self.assertEqual(self.w.run(self.rid)["status"], "succeeded")
        self.assertEqual(self.w.run(self.rid)["snapshot"], first["snapshot"])

    def test_legacy_in_progress_requires_explicit_mapping_without_rebuild(self):
        task = self.start()
        task.extra.pop("requirements")
        self.s.store.save(task)
        with self.assertRaises(EngineError):
            self.s.engine.approve(task.id)
        reqs = [{"id": "A1", "text": "정답은 42", "evidence": self.refs[0]}]
        self.s.engine.set_workflow_evidence(task.id, reqs, task.candidate_sha)
        self.s.engine.set_workflow_evidence(task.id, reqs, task.candidate_sha)
        self.assertEqual(len(self.s.store.get(task.id).extra["workflow_evidence_history"]), 1)
        self.s.engine.approve(task.id)
        self.w.tick()
        self.assertEqual(self.w.run(self.rid)["status"], "succeeded")
        self.assertEqual(len(self.s.store.runs()), 2)

    def test_mapping_cannot_change_criteria_scope_or_another_candidate(self):
        task = self.start()
        for refs, sha, text in (([{"type": "file", "path": "README.md"}], task.candidate_sha, "정답은 42"),
                                (self.refs[0], self.base, "정답은 42"), (self.refs[0], task.candidate_sha, "다른 기준")):
            with self.subTest(refs=refs, sha=sha, text=text), self.assertRaises(EngineError):
                self.s.engine.set_workflow_evidence(task.id, [{"id": "A1", "text": text, "evidence": refs}], sha)

    def test_stale_approval_click_is_rejected_before_merge(self):
        task = self.start()
        with self.assertRaisesRegex(EngineError, "후보가 바뀌"):
            self.s.engine.approve(task.id, {"candidate_sha": self.base, "revision": 1})
        with self.assertRaisesRegex(EngineError, "버전이 바뀌"):
            self.s.engine.approve(task.id, {"candidate_sha": task.candidate_sha, "revision": 0})
        self.assertEqual(gitops.head(self.s.repo, "main"), self.base)

    def test_changed_evidence_after_approval_blocks_workflow_completion(self):
        task = self.start()
        self.s.engine.approve(task.id)
        atomic_write_text(self.s.store.qa_dir / task.qa["qa_id"] / "snapshot/docs/answer.txt", "tampered\n")
        self.w.tick()
        self.assertEqual(self.s.store.get(task.id).status, "done", "CEO approval is never silently undone")
        self.assertEqual(self.w.run(self.rid)["status"], "blocked")
        self.assertNotEqual(self.w.run(self.rid)["nodes"]["f"]["status"], "succeeded")

    def test_completed_legacy_record_is_read_only_and_not_migrated(self):
        task = self.start()
        self.s.engine.approve(task.id); self.w.tick()
        task = self.s.store.get(task.id)
        task.extra.pop("requirements"); self.s.store.save(task)
        path = self.s.store.dir / "workbench-runs" / (self.rid + ".json")
        before = path.read_bytes()
        displayed = self.w.describe_run(self.rid)
        self.assertEqual(displayed["status"], "succeeded")
        self.assertEqual(self.s.store.get(task.id).status, "done")
        self.assertFalse(displayed["current_tasks"][task.id]["evidence"]["complete"])
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_evidence_scope_is_rejected_before_submission(self):
        g = graph(node("a", "input", text="42"), node("b", "implement", acceptance=["README"],
                  evidence=[[{"type": "file", "path": "README.md"}]]), node("c", "approve"))
        with self.assertRaises(EngineError):
            self.w.plan({"title": "범위 오류", "graph": g, "project": "demo", "allowed_paths": ["docs/**"]})
        self.assertEqual(self.s.store.list(), [])

    def test_restart_reconcile_preserves_versions_and_does_not_call_models(self):
        task = self.start()
        self.s.engine.request_changes(task.id, "검증 유지하고 수정")
        self.w.tick()
        before = deepcopy(self.w.run(self.rid)["versions"])
        engine = Engine(self.s.cfg, self.s.store, runtime_factory=self.s._runtime)
        engine.recover()
        run = engine.workbench.reconcile(self.rid)
        self.assertEqual(run["status"], "blocked")
        self.assertEqual(run["versions"], before)
        self.assertEqual(len(self.s.store.list()), 1)
        self.assertEqual(len(self.s.store.runs()), 2)

    def test_public_approval_api_enforces_contract_and_exposes_reason(self):
        task = self.start([[{"type": "file", "path": "docs/missing.txt"}]])
        server = StudioServer(self.s.cfg, self.s.store, self.s.engine, 0)
        port = server.server_address[1]
        server.allowed_hosts = {f"127.0.0.1:{port}"}
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
        thread.start()
        def request(method, path, body=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
            conn.request(method, path, json.dumps(body or {}) if method == "POST" else None,
                         {"X-Studio-Token": server.token, "Content-Type": "application/json"})
            response = conn.getresponse()
            value = json.loads(response.read()); conn.close()
            return response.status, value
        try:
            self.assertEqual(request("POST", f"/api/tasks/{task.id}/approve")[0], 400)
            status, run = request("GET", "/api/workbench/runs/" + self.rid)
            self.assertEqual(status, 200)
            self.assertFalse(run["current_tasks"][task.id]["approval"]["allowed"])
            self.assertTrue(run["current_tasks"][task.id]["approval"]["reasons"])
            reqs = [{"id": "A1", "text": "정답은 42", "evidence": self.refs[0]}]
            self.assertEqual(request("POST", f"/api/tasks/{task.id}/evidence", {"requirements": reqs, "candidate_sha": task.candidate_sha})[0], 200)
            self.w.reconcile(self.rid)
            self.assertEqual(request("POST", f"/api/tasks/{task.id}/approve")[0], 200)
            self.w.tick()
            self.assertEqual(request("GET", "/api/workbench/runs/" + self.rid)[1]["status"], "succeeded")
        finally:
            server.shutdown(); server.server_close(); thread.join(5)
