"""Offline contracts and existing workbench ledger; never invokes a CLI."""
import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from studio import grok_everywhere as ge
from studio.workbench import WorkbenchError
from tests.helpers import TempStudio
from tests.test_workbench import node, graph
from tests import test_server as server_tests


def envelope(kind):
    result = {"ok": True, "module": "search" if kind == "research" else kind,
              "operation": "web" if kind == "research" else "generate", "auth_kind": "session",
              "model": ge.MODELS[kind], "artifacts": [], "cost_usd": None}
    if kind == "research":
        result.update(answer="MOCK research", citations=[], response_status="completed")
    if kind == "video":
        result["request_id"] = "mock-video-123"
    return result


class ContractTests(unittest.TestCase):
    def test_typed_plan_unknown_cost_and_always_blocked(self):
        for kind in ge.MODELS:
            p = ge.plan({"kind": kind, "text": "--evil is only input text"})
            self.assertIsNone(p["cost_usd"])
            self.assertFalse(p["enabled"])
            self.assertIn("one_use_request:" + p["request_hash"], p["approval_checklist"])
        for body in ({"kind": "image", "text": ""}, {"kind": "image", "text": "x", "approved": True}, {"kind": "shell", "text": "x"}, {"kind": [], "text": "x"}, {"kind": {}, "text": "x"}):
            with self.assertRaises(ge.ContractError):
                ge.plan(body)
        with self.assertRaises(ge.ContractError):
            ge.execute({"approved": True})

    def test_video_duration_integer_range_immutable_argv_and_hash(self):
        default = ge.plan({"kind": "video", "text": "clip"})
        self.assertEqual(default["request"]["options"]["duration"], 5)
        for duration in range(1, 16):
            request = {"kind": "video", "text": "--auth api-key", "duration": duration}
            plan = ge.plan(request)
            self.assertEqual(plan["request"]["options"]["duration"], duration)
            for body in (request, plan["request"]):
                argv = ge.command_contract(body, "cache", "output.mp4")
                self.assertEqual(argv[argv.index("--duration") + 1], str(duration))
                self.assertEqual(argv[:2], ["--auth", "session"])
                self.assertEqual(argv[-2:], ["--", request["text"]])
        self.assertNotEqual(ge.plan({"kind": "video", "text": "clip", "duration": 10})["request_hash"], default["request_hash"])
        for field, replacement in (("duration", 11), ("resolution", "1080p")):
            bad = ge.plan({"kind": "video", "text": "clip", "duration": 10})["request"]
            bad["options"][field] = replacement
            with self.assertRaises(ge.ContractError):
                ge.command_contract(bad, "cache", "output.mp4")
        bad = ge.plan({"kind": "video", "text": "clip", "duration": 10})["request"]
        bad["auth_kind"] = "api-key"
        with self.assertRaises(ge.ContractError):
            ge.command_contract(bad, "cache", "output.mp4")

    def test_video_duration_rejects_types_other_kinds_and_extra_fields(self):
        for duration in (0, 16, -1, True, False, 10.0, 2.5, "10", None, [], {}):
            with self.assertRaises(ge.ContractError):
                ge.plan({"kind": "video", "text": "clip", "duration": duration})
        for body in ({"text": "clip", "duration": 10}, {"kind": "image", "text": "clip", "duration": 10}, {"kind": "research", "text": "clip", "duration": 10}, {"kind": "video", "text": "clip", "seconds": 10}):
            with self.assertRaises(ge.ContractError):
                ge.plan(body)
        self.assertIsNone(ge.reported_video_duration(None, 10))
        for reported in (5, True, "10", float("nan"), 16):
            with self.assertRaises(ge.ContractError):
                ge.reported_video_duration(reported, 10)

    def test_env_drops_secrets_and_overrides(self):
        self.assertEqual(ge.child_env({"PATH": "ok", "XAI_API_KEY": "secret", "GROK_TOKEN": "secret", "HTTP_PROXY": "bad", "GROK_CONFIG": "bad"}), {"PATH": "ok"})

    def test_fixed_argv_no_prompt_flags_or_post_retry(self):
        request = {"kind": "video", "text": "--auth api-key"}
        argv = ge.command_contract(request, "local-cache", "local-output.mp4")
        self.assertEqual(argv[:2], ["--auth", "session"])
        self.assertEqual(argv[-2:], ["--", request["text"]])
        argv = ge.command_contract(request, "local-cache", request_id="known-123")
        self.assertEqual(argv[-3:], ["video", "get", "known-123"])
        self.assertNotIn("generate", argv)

    def test_strict_session_and_json(self):
        for kind in ge.MODELS:
            self.assertIsNone(ge.parse_result(json.dumps(envelope(kind)), kind)["cost_usd"])
        upstream_search = {**envelope("research"), "depth": "balanced", "incomplete_details": None, "search_items": {}, "usage": {}}
        self.assertEqual(ge.parse_result(json.dumps(upstream_search), "research")["depth"], "balanced")
        for changes in ({"auth_kind": "api-key"}, {"dry_run": True}, {"cost_usd": False}, {"cost_usd": float("nan")}, {"module": "shell"}, {"model": "fallback"}, {"ok": False, "error": "token=secret"}):
            with self.assertRaises(ge.ContractError):
                ge.parse_result(json.dumps({**envelope("image"), **changes}), "image")
        with self.assertRaises(ge.ContractError):
            ge.parse_result("not JSON token=secret", "video")
        result = envelope("video")
        del result["request_id"]
        with self.assertRaises(ge.ContractError):
            ge.parse_result(json.dumps(result), "video")
        for bad in (123, [], {}):
            with self.assertRaises(ge.ContractError):
                ge.parse_result(json.dumps({**envelope("video"), "request_id": bad}), "video")

    def test_paths_and_media(self):
        with tempfile.TemporaryDirectory() as root:
            for bad in ("../image.png", "/image.png", "C:/image.png", "C:image.png", "\\\\host\\share", "a:stream", "a/../b", "CON.png", "a./b", "a//b", "a\nb", "a?b"):
                with self.assertRaises(ge.ContractError, msg=bad):
                    ge.artifact_path(root, bad)
            with self.assertRaises(ge.ContractError):
                ge.verify_artifact(root, "missing.png", "image")
            Path(root, "raw-response.json").write_text("{}")
            with self.assertRaises(ge.ContractError):
                ge.verify_artifact(root, "raw-response.json", "image")
            Path(root, "picture.png").write_bytes(b"not png")
            with self.assertRaises(ge.ContractError):
                ge.verify_artifact(root, "picture.png", "image")


class MockWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.s.cfg.fake_runtimes = True
        self.w = self.s.engine.workbench
        self.calls = []

    def tearDown(self):
        self.s.close()

    def provider(self, request):
        self.calls.append(request)
        kind = request["kind"]
        selected = []
        if kind != "research":
            filename = "mock.png" if kind == "image" else "mock.mp4"
            Path(self.s.store.dir, filename).write_bytes(b"\x89PNG\r\n\x1a\nMOCK" if kind == "image" else b"\0\0\0\x18ftypisomMOCK")
            selected = [filename]
        return {"simulation": True, "provider_result": envelope(kind), "selected_artifacts": selected}

    def begin(self, kind):
        body = {"title": "MOCK / 모의 실행", "graph": graph(node("a", "input", text="mock request"), node("b", "grok_" + kind), node("c", "summary"))}
        plan = self.w.plan(body)
        body.update(plan_hash=plan["hash"], confirmed=True, allow_models=False, request_id=uuid4().hex)
        return self.w.start(body), body

    def test_mock_research_image_video_in_existing_ledger_and_duplicate_click(self):
        self.w.attach_grok_mock(self.provider)
        for kind in ge.MODELS:
            run, body = self.begin(kind)
            self.w.tick()
            finished = self.w.run(run["id"])
            self.assertEqual(finished["status"], "succeeded")
            out = finished["nodes"]["b"]["output"]
            self.assertTrue(out["simulation"])
            self.assertIsNone(out["cost_usd"])
            task = self.s.store.get(finished["nodes"]["b"]["task"])
            self.assertEqual(task.status, "blocked")
            self.assertFalse(task.run_requested)
            self.assertEqual(task.extra["provider_result"], out)
            self.assertTrue(self.s.store.runs(task.id)[0]["simulation"])
            self.assertEqual(self.w.describe_run(run["id"])["usage"]["total"], 0)
            self.assertEqual(finished["nodes"]["c"]["output"]["result"], out)
            self.w.start(body)
            self.w.tick()
        self.assertEqual(len(self.calls), 3)

    def test_ten_second_plan_hash_mock_media_task_ledger_and_dedup(self):
        from studio.util import atomic_copy
        calls = []
        def provider(request):
            calls.append(request)
            self.assertEqual(request["options"]["duration"], 10)
            atomic_copy(Path(__file__).parent / "fixtures" / "mock-video-10s.webm", self.s.store.dir / "mock10.webm")
            return {"simulation": True, "provider_result": {**envelope("video"), "duration": 10}, "selected_artifacts": ["mock10.webm"]}
        self.w.attach_grok_mock(provider)
        body = {"title": "MOCK 10-second video", "graph": graph(node("a", "input", text="MOCK clip"), node("b", "grok_video", duration=10), node("c", "summary"))}
        plan = self.w.plan(body)
        self.assertEqual(plan["provider_requests"][0]["options"]["duration"], 10)
        changed = json.loads(json.dumps(body)); changed["graph"]["nodes"][1]["params"]["duration"] = 11
        approval = {"plan_hash": plan["hash"], "confirmed": True, "allow_models": False, "request_id": uuid4().hex}
        with self.assertRaises(WorkbenchError):
            self.w.start({**changed, **approval})
        run = self.w.start({**body, **approval}); self.w.tick()
        result = self.w.run(run["id"])
        self.assertEqual(result["status"], "succeeded")
        output = result["nodes"]["b"]["output"]
        self.assertEqual((output["requested_duration"], output["reported_duration"]), (10, 10))
        task = self.s.store.get(result["nodes"]["b"]["task"])
        self.assertEqual(task.extra["provider_result"], output)
        self.assertEqual(self.s.store.runs(task.id)[0]["requested_duration"], 10)
        self.assertEqual(self.s.store.runs(task.id)[0]["reported_duration"], 10)
        self.assertIsNone(output["cost_usd"])
        self.w.start({**body, **approval}); self.w.tick()
        self.assertEqual(len(calls), 1)
        for duration in (True, "10", 0, 16, 10.0):
            invalid = json.loads(json.dumps(body)); invalid["graph"]["nodes"][1]["params"]["duration"] = duration
            with self.assertRaises(WorkbenchError):
                self.w.plan(invalid)

    def test_mock_wrong_reported_duration_blocks_without_resubmission(self):
        def wrong(request):
            result = self.provider(request)
            result["provider_result"]["duration"] = 5
            return result
        self.w.attach_grok_mock(wrong)
        body = {"title": "MOCK mismatch", "graph": graph(node("a", "input", text="clip"), node("b", "grok_video", duration=10))}
        plan = self.w.plan(body)
        self.w.start({**body, "plan_hash": plan["hash"], "confirmed": True, "allow_models": False, "request_id": uuid4().hex})
        self.w.tick(); self.w.tick()
        self.assertEqual(self.w.ledger()[0]["status"], "blocked")
        self.assertEqual(len(self.calls), 1)

    def test_denied_disconnected_missing_input(self):
        with self.assertRaises(WorkbenchError):
            self.begin("image")
        self.w.attach_grok_mock(self.provider)
        run, body = self.begin("image")
        body.update(request_id=uuid4().hex, confirmed=False)
        with self.assertRaises(WorkbenchError):
            self.w.start(body)
        with self.assertRaises(WorkbenchError):
            self.w.plan({"title": "x", "graph": graph(node("a", "input", text=""), node("b", "grok_image"))})

    def test_timeout_invalid_missing_escape_and_restart_fail_closed(self):
        def timeout(_):
            raise TimeoutError("token=DO_NOT_RECORD")
        cases = [timeout, lambda _: {"simulation": False},
                 lambda _: {"simulation": True, "provider_result": envelope("image"), "selected_artifacts": ["missing.png"]},
                 lambda _: {"simulation": True, "provider_result": envelope("image"), "selected_artifacts": ["../escape.png"]}]
        for provider in cases:
            self.w.attach_grok_mock(provider)
            run, body = self.begin("image")
            self.w.tick()
            result = self.w.run(run["id"])
            self.assertEqual(result["status"], "blocked")
            self.assertNotIn("DO_NOT_RECORD", json.dumps(result))
            self.w.reconcile(run["id"])
            self.w.tick()
            self.assertEqual(self.w.run(run["id"])["status"], "blocked")

    def test_known_video_get_only_wait_failed_then_complete_and_no_revival(self):
        submitted, fetched = [], []
        def provider(request):
            submitted.append(request)
            return {"simulation": True, "pending": True, "request_id": "known-video"}
        def get(request):
            fetched.append(request)
            return {"simulation": True, "request_id": "known-video", "status": "pending"}
        self.w.attach_grok_mock(provider, get)
        run, body = self.begin("video")
        self.w.tick()
        self.assertEqual(self.w.run(run["id"])["status"], "waiting")
        self.w.provider_recheck(run["id"], "b")
        self.w.tick()
        self.assertEqual(len(submitted), 1)
        self.assertEqual(fetched[0], {"method": "GET", "request_id": "known-video"})
        self.assertIsNone(self.w.run(run["id"])["nodes"]["b"]["output"])
        self.w._grok_get_mock = lambda _: {"simulation": True, "request_id": "known-video", "status": "failed"}
        self.w.provider_recheck(run["id"], "b")
        self.w.tick()
        self.assertEqual(self.w.run(run["id"])["nodes"]["c"]["status"], "skipped")
        Path(self.s.store.dir, "finished.mp4").write_bytes(b"\0\0\0\x18ftypisomMOCK")
        self.w._grok_get_mock = lambda _: {"simulation": True, "request_id": "known-video", "status": "completed", "selected_artifacts": ["finished.mp4"]}
        self.w.provider_recheck(run["id"], "b")
        self.w.tick()
        self.assertEqual(self.w.run(run["id"])["status"], "succeeded")
        self.assertEqual(self.w.run(run["id"])["error"], "")
        with self.assertRaises(WorkbenchError):
            self.w.provider_recheck(run["id"], "b")
        self.assertEqual(len(submitted), 1)

    def test_typed_artifact_reference_is_reusable_without_text_coercion(self):
        self.w.attach_grok_mock(self.provider)
        g = graph(node("a", "input", text="mock"), node("b", "grok_image"), node("c", "artifact_reference"), node("d", "summary"))
        body = {"title": "refs", "graph": g}
        plan = self.w.plan(body)
        run = self.w.start({**body, "plan_hash": plan["hash"], "request_id": uuid4().hex, "confirmed": True, "allow_models": False})
        self.w.tick()
        finished = self.w.run(run["id"])
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["nodes"]["c"]["output"]["artifact_refs"][0]["run"], run["id"])
        first_ref = finished["nodes"]["c"]["output"]["artifact_refs"][0]
        first_path, _ = self.w.provider_artifact(run["id"], "b", 0)
        first_content = first_path.read_bytes()
        self.assertTrue(first_path.is_relative_to(self.s.store.runs_dir))
        def changed_provider(request):
            result = self.provider(request)
            # Reuse the supplier's exact scratch filename with different media.
            Path(self.s.store.dir, "mock.png").write_bytes(b"\x89PNG\r\n\x1a\nSECOND MOCK")
            return result
        self.w.attach_grok_mock(changed_provider)
        next_run, _ = self.begin("image")
        self.w.tick()
        next_result = self.w.run(next_run["id"])["nodes"]["b"]["output"]
        self.assertNotEqual(next_result["artifact_refs"][0]["path"], first_ref["path"])
        self.assertNotEqual(next_result["artifact_refs"][0]["sha256"], first_ref["sha256"])
        self.assertEqual(first_path.read_bytes(), first_content)
        self.assertEqual(self.w.provider_artifact(run["id"], "b", 0)[0].read_bytes(), first_content)
        first_path.write_bytes(b"\x89PNG\r\n\x1a\nTAMPERED")
        with self.assertRaises(WorkbenchError):
            self.w.provider_artifact(run["id"], "b", 0)
        with self.assertRaises(WorkbenchError):
            self.w.validate(graph(node("a", "input", text="mock"), node("b", "grok_image"), node("c", "format")))


class ApiTests(unittest.TestCase):
    setUp = server_tests.ServerSecurity.setUp
    tearDown = server_tests.ServerSecurity.tearDown
    req = server_tests.ServerSecurity.req
    def test_grok_endpoints_keep_existing_security_and_do_not_initialize(self):
        before = set(self.s.store.dir.rglob("*"))
        res, _ = self.req("GET", "/api/grok-everywhere/catalog")
        self.assertEqual(res.status, 200)
        body = {"kind": "image", "text": "mock"}
        self.assertEqual(self.req("POST", "/api/grok-everywhere/plan", body)[0].status, 403)
        headers = {"X-Studio-Token": self.srv.token}
        res, raw = self.req("POST", "/api/grok-everywhere/plan", body, headers)
        self.assertEqual(res.status, 200)
        self.assertIsNone(json.loads(raw)["cost_usd"])
        self.assertEqual(self.req("POST", "/api/grok-everywhere/execute", body, headers)[0].status, 409)
        self.assertEqual(before, set(self.s.store.dir.rglob("*")))
