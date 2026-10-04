"""Workbench safety and actual Engine integration, entirely in disposable companies."""
import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4

from tests.helpers import TempStudio
from studio.engine import Engine
from studio.server import StudioServer
from studio.util import atomic_write_json
from studio.workbench import WorkbenchError


def node(key, operation, **params):
    return {"id": key, "ref": {"id": "builtin-" + operation, "version": 1}, "params": params}


def graph(*nodes):
    return {"nodes": list(nodes), "edges": [{"from": a["id"], "to": b["id"]} for a, b in zip(nodes, nodes[1:])]}


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.w = self.s.engine.workbench

    def tearDown(self):
        self.s.close()

    def begin(self, g, **extra):
        body = {"title": "시험 흐름", "graph": g, **extra}
        plan = self.w.plan(body)
        body.update(plan_hash=plan["hash"], confirmed=True, allow_models=plan["uses_models"], request_id=uuid4().hex)
        return self.w.start(body), body

    def build_graph(self):
        return graph(node("a", "input", text="docs/answer.txt에 42를 저장"), node("b", "implement", acceptance=["정답은 42"]),
                     node("c", "test"), node("d", "review"), node("e", "approve"), node("f", "summary"))

    def test_catalog_read_does_not_initialize_data_or_call_models(self):
        before = set(self.s.store.dir.rglob("*"))
        with patch.object(self.s.engine, "runtime_factory", side_effect=AssertionError("model")):
            catalog = self.w.catalog()
        self.assertEqual(before, set(self.s.store.dir.rglob("*")))
        self.assertFalse(catalog["operations"]["shell"]["enabled"])

    def test_notes_version_and_folder_survive_engine_reload(self):
        folder = self.w.save_folder({"title": "재사용", "revision": 0})
        body = {"title": "반복 정리", "folder": folder["id"], "note": {"purpose": "코드는 설명일 뿐", "example": "os.remove('anything')"},
                "spec": {"operation": "format", "params": {"prefix": "요약: "}}}
        first = self.w.save_node(body)
        second = self.w.save_node({**body, "id": first["id"], "version": 1, "title": "정리 2"})
        self.assertEqual(second["version"], 2)
        with self.assertRaises(WorkbenchError):
            self.w.save_node({**body, "id": first["id"], "version": 1})
        restored = Engine(self.s.cfg, self.s.store, runtime_factory=self.s._runtime).workbench.catalog()
        self.assertEqual(restored["nodes"][-1]["title"], "정리 2")
        self.assertEqual(self.w._definition({"id": first["id"], "version": 1}, self.w._catalog())["title"], first["title"])

    def test_flow_pins_old_node_version_and_keeps_immutable_run_graph(self):
        custom = self.w.save_node({"title": "접두사", "note": {}, "spec": {"operation": "format", "params": {"prefix": "old:"}}})
        g = graph(node("a", "input", text="value"), {"id": "b", "ref": {"id": custom["id"], "version": 1}}, node("c", "summary"))
        flow = self.w.save_flow({"title": "묶음", "graph": g})
        r, _ = self.begin(flow["graph"])
        snapshot = deepcopy(r["snapshot"])
        self.w.save_node({**custom, "version": 1, "spec": {"operation": "format", "params": {"prefix": "new:"}}})
        self.w.tick()
        done = self.w.run(r["id"])
        self.assertEqual(done["snapshot"], snapshot)
        self.assertEqual(done["nodes"]["b"]["output"], "old:value")
        self.assertEqual(len(self.s.store.list()), 0)

    def test_typed_cycles_duplicates_and_dangling_edges_rejected(self):
        cases = [
            {"nodes": [node("a", "format"), node("b", "format")], "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]},
            {"nodes": [node("a", "input"), node("b", "test")], "edges": [{"from": "a", "to": "b"}]},
            {"nodes": [node("a", "input"), node("a", "input")], "edges": []},
            {"nodes": [node("a", "input")], "edges": [{"from": "a", "to": "absent"}]},
            {"nodes": [node("a", "input"), node("b", "format")], "edges": [{"from": "a", "to": "b"}] * 2},
        ]
        for g in cases:
            with self.subTest(graph=g), self.assertRaises(WorkbenchError):
                self.w.validate(g)

    def test_drafts_can_save_missing_input_but_cannot_execute(self):
        g = {"nodes": [node("a", "format")], "edges": []}
        self.w.save_flow({"title": "작성 중", "graph": g})
        with self.assertRaisesRegex(WorkbenchError, "선행 입력"):
            self.begin(g)
        with self.assertRaisesRegex(WorkbenchError, "실행 입력"):
            self.begin(graph(node("a", "input")))
        self.w.save_flow({"title": "빈 작업대", "graph": {"nodes": [], "edges": []}})
        with self.assertRaises(WorkbenchError):
            self.begin({"nodes": [], "edges": []})

    def test_unknown_code_and_bad_types_are_rejected(self):
        for spec in ({"operation": "exec", "params": {}}, {"operation": "input", "params": {"command": "cmd"}}, {"operation": "format", "code": "print(1)"}):
            with self.subTest(spec=spec), self.assertRaises(WorkbenchError):
                self.w.save_node({"title": "bad", "note": {}, "spec": spec})
        with self.assertRaises(WorkbenchError):
            self.w.validate(graph(node("a", "lines", dedupe="true")))
        with self.assertRaises(WorkbenchError):
            self.w.validate({"nodes": [{**node("a", "input"), "params": "bad"}], "edges": []})

    def test_finite_code_processing_and_condition_failure(self):
        r, _ = self.begin(graph(node("a", "input", text=" beta \nalpha\nbeta"), node("b", "lines", sort=True), node("c", "summary")))
        self.w.tick()
        self.assertEqual(self.w.run(r["id"])["nodes"]["b"]["output"], "alpha\nbeta")
        r, _ = self.begin(graph(node("a", "input", text="hello"), node("b", "require_text", contains="missing"), node("c", "summary")))
        self.w.tick()
        blocked = self.w.run(r["id"])
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["nodes"]["c"]["status"], "skipped")
        self.assertEqual(self.s.store.runs(), [])

    def test_plan_confirmation_scope_and_settings_are_required(self):
        b = {"title": "구현", "graph": self.build_graph(), "project": "demo", "allowed_paths": ["docs/**"]}
        plan = self.w.plan(b)
        self.assertEqual(plan["max_model_calls"], 2)
        self.assertEqual(self.s.store.list(), [])
        with self.assertRaises(WorkbenchError):
            self.w.start({**b, "plan_hash": plan["hash"], "request_id": uuid4().hex, "allow_models": True})
        self.s.cfg.roles["builder"].model = "changed"
        with self.assertRaises(WorkbenchError):
            self.w.start({**b, "plan_hash": plan["hash"], "request_id": uuid4().hex, "allow_models": True, "confirmed": True})
        with self.assertRaisesRegex(WorkbenchError, "허용 경로"):
            self.w.plan({**b, "allowed_paths": ["**"]})

    def test_models_need_explicit_approval_node_and_acceptance(self):
        with self.assertRaisesRegex(WorkbenchError, "사용자승인"):
            self.begin(graph(node("a", "input", text="work"), node("b", "implement", acceptance=["test"])), project="demo", allowed_paths=["docs/**"])
        with self.assertRaisesRegex(WorkbenchError, "수용 기준"):
            self.begin(graph(node("a", "input", text="work"), node("b", "implement"), node("c", "approve")), project="demo", allowed_paths=["docs/**"])

    def test_duplicate_clicks_and_lost_response_create_one_run_and_task(self):
        r, body = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        with ThreadPoolExecutor(max_workers=3) as pool:
            runs = list(pool.map(lambda _: self.w.start(body), range(3)))
        self.assertTrue(all(run["id"] == r["id"] for run in runs))
        self.w.tick()
        self.w.tick()
        self.assertEqual(len(self.w.ledger()), 1)
        self.assertEqual(len(self.s.store.list()), 1)

    def test_engine_pipeline_evidence_ceo_approval_and_outputs(self):
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        self.w.tick()
        task_id = self.w.run(r["id"])["nodes"]["b"]["task"]
        self.s.engine._run_build(self.s.store.get(task_id))
        self.w.tick()
        waiting = self.w.run(r["id"])
        self.assertEqual(waiting["status"], "waiting")
        self.assertEqual(waiting["nodes"]["c"]["output"]["qa"]["verdict"], "pass")
        self.assertEqual(waiting["nodes"]["d"]["output"]["review"]["verdict"], "approve")
        self.assertEqual(len(self.s.store.runs()), 2)
        self.s.engine.approve(task_id)
        self.w.tick()
        done = self.w.run(r["id"])
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["nodes"]["e"]["output"]["status"], "done")
        self.assertTrue(done["nodes"]["f"]["output"]["result"]["merged_sha"])
        self.assertEqual(len(self.s.store.runs()), 2)

    def test_review_failure_is_not_automatically_retried_or_approved(self):
        from tests.helpers import default_behavior
        self.s.behavior = lambda spec, runtime: {"structured": {"verdict": "changes_requested", "summary": "fix", "findings": []}} if spec.role == "reviewer" else default_behavior(spec, runtime)
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        self.w.tick()
        task_id = self.w.run(r["id"])["nodes"]["b"]["task"]
        self.s.engine._run_build(self.s.store.get(task_id))
        self.w.tick()
        self.assertEqual(self.w.run(r["id"])["status"], "blocked")
        self.assertEqual(len(self.s.store.runs()), 2)
        self.w.reconcile(r["id"])
        self.w.tick()
        self.assertEqual(len(self.s.store.runs()), 2)

    def test_model_settings_change_after_dispatch_fails_before_call(self):
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        self.w.tick()
        task = self.s.store.get(self.w.run(r["id"])["nodes"]["b"]["task"])
        self.s.cfg.roles["builder"].model = "changed"
        with self.assertRaisesRegex(WorkbenchError, "설정이 바뀌었"):
            self.s.engine._run_build(task)
        self.assertEqual(self.s.store.runs(), [])

    def test_mcp_secrets_never_read_or_appear_in_plan(self):
        with patch("studio.mcp._secrets", side_effect=AssertionError("secret read")):
            plan = self.w.plan({"title": "구현", "graph": self.build_graph(), "project": "demo", "allowed_paths": ["docs/**"]})
        self.assertNotIn('"env":', json.dumps(plan))

    def test_recovery_never_resubmits_or_starts_pending_tasks(self):
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        self.w.tick()
        engine = Engine(self.s.cfg, self.s.store, runtime_factory=self.s._runtime)
        engine.recover()
        self.assertEqual(engine.workbench.run(r["id"])["status"], "blocked")
        engine.workbench.reconcile(r["id"])
        engine.workbench.tick()
        self.assertEqual(len(self.s.store.list()), 1)
        self.assertIsNone(engine._next_job())
        self.assertEqual(self.s.store.runs(), [])

    def test_uncertain_dispatch_boundary_and_corrupt_storage_fail_closed(self):
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        r["nodes"]["b"]["status"] = "dispatching"
        self.w._persist(r)
        self.w.recover()
        with self.assertRaisesRegex(WorkbenchError, "不確実|불확실"):
            self.w.reconcile(r["id"])
        self.assertEqual(self.s.store.list(), [])
        path = self.s.store.dir / "workbench.json"
        from studio.util import atomic_write_text
        atomic_write_text(path, "corrupt")
        with self.assertRaisesRegex(WorkbenchError, "원본을 보존"):
            self.w.save_node({"title": "change", "note": {}, "spec": {"operation": "input"}})
        self.assertEqual(path.read_text(), "corrupt")

    def test_grok_disabled_and_halt_keeps_existing_task(self):
        self.s.cfg.roles["builder"].runtime = "grok_text"
        self.assertFalse(self.w.capability("implement")["enabled"])
        self.s.cfg.roles["builder"].runtime = "codex"
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/**"])
        self.w.tick()
        task_id = self.w.run(r["id"])["nodes"]["b"]["task"]
        self.w.halt(r["id"])
        self.assertEqual(self.s.store.get(task_id).status, "ready")
        self.assertEqual(self.w.run(r["id"])["status"], "cancelled")

    def test_plan_approval_preserves_scope_and_children_require_manual_run(self):
        r, _ = self.begin(graph(node("a", "input", text="작업을 나눠 주세요"), node("b", "requirements"), node("c", "approve"), node("d", "summary")), project="demo", allowed_paths=["docs/**"])
        self.w.tick()
        task_id = self.w.run(r["id"])["nodes"]["b"]["task"]
        self.s.engine._run_plan(self.s.store.get(task_id))
        self.s.engine.approve(task_id, {"selected": [0]})
        self.s.engine.set_auto_run(True)
        self.assertIsNone(self.s.engine._next_job())
        self.w.tick()
        self.assertEqual(self.w.run(r["id"])["status"], "succeeded")
        self.assertEqual(len(self.s.store.runs()), 1)

    def test_plan_scope_rejection_creates_no_partial_children(self):
        r, _ = self.begin(graph(node("a", "input", text="작업을 나눠 주세요"), node("b", "requirements"), node("c", "approve")), project="demo", allowed_paths=["docs/answer.txt"])
        self.w.tick()
        task_id = self.w.run(r["id"])["nodes"]["b"]["task"]
        self.s.engine._run_plan(self.s.store.get(task_id))
        task = self.s.store.get(task_id)
        task.proposal["tasks"][0]["allowed_paths"] = ["docs/answer.txt"]
        task.proposal["tasks"][1]["allowed_paths"] = ["docs/**"]
        self.s.store.save(task)
        with self.assertRaisesRegex(ValueError, "허용 경로"):
            self.s.engine.approve(task_id)
        self.assertEqual(len(self.s.store.list()), 1)

    def test_project_scope_changes_block_before_model_invocation(self):
        r, _ = self.begin(self.build_graph(), project="demo", allowed_paths=["docs/answer.txt"])
        self.w.tick()
        task = self.s.store.get(self.w.run(r["id"])["nodes"]["b"]["task"])
        self.w.check_task(task, "builder", "build")
        task.allowed_paths = ["docs/**"]
        with self.assertRaisesRegex(WorkbenchError, "허용 범위"):
            self.w.check_task(task, "builder", "build")
        task.allowed_paths = ["docs/answer.txt"]
        self.s.cfg.projects["demo"].main_branch = "other-branch"
        with self.assertRaisesRegex(WorkbenchError, "작업 대상"):
            self.w.check_task(task, "builder", "build")
        self.assertEqual(self.s.store.runs(), [])


class WorkbenchApiTests(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.server = StudioServer(self.s.cfg, self.s.store, self.s.engine, 0)
        port = self.server.server_address[1]
        self.server.allowed_hosts = {f"127.0.0.1:{port}"}
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.s.close()

    def request(self, method, path, body=None, **headers):
        port = self.server.server_address[1]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, json.loads(raw)

    def test_workbench_api_token_origin_and_graph_validation(self):
        self.assertEqual(self.request("GET", "/api/workbench")[0], 200)
        body = {"title": "글", "graph": graph(node("a", "input", text="hello"), node("b", "summary"))}
        self.assertEqual(self.request("POST", "/api/workbench/flows", body)[0], 403)
        token = {"X-Studio-Token": self.server.token}
        self.assertEqual(self.request("POST", "/api/workbench/flows", body, **token, Origin="https://invalid.test")[0], 403)
        self.assertEqual(self.request("POST", "/api/workbench/flows", body, **token)[0], 200)
        status, plan = self.request("POST", "/api/workbench/plan", body, **token)
        self.assertEqual(status, 200)
        status, result = self.request("POST", "/api/workbench/start", {**body, "confirmed": True, "allow_models": False, "plan_hash": plan["hash"], "request_id": uuid4().hex}, **token)
        self.assertEqual(status, 200)
        self.s.engine.workbench.tick()
        status, run = self.request("GET", "/api/workbench/runs/" + result["run"]["id"])
        self.assertEqual((status, run["status"]), (200, "succeeded"))
        self.assertEqual(self.request("GET", "/api/workbench/ledger")[1]["runs"][0]["id"], run["id"])
        self.assertEqual(self.request("GET", "/api/workbench/runs/..%2f..%2fstate")[0], 400)
