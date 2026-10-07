"""이미지·영상 제작 작업대의 '내 작업물' 목록 (작업대 장부에서 그림·영상 노드만 찾는다). 모의 미디어만 쓴다."""
import json
import unittest
from pathlib import Path
from uuid import uuid4

from studio import grok_everywhere as ge
from tests.helpers import TempStudio
from tests.test_grok_everywhere import envelope
from tests.test_workbench import graph, node
from tests import test_server as server_tests


class MediaJobTests(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.s.cfg.fake_runtimes = True
        self.w = self.s.engine.workbench

        def provider(request):
            kind = request["kind"]
            name = "mock.png" if kind == "image" else "mock.mp4"
            Path(self.s.store.dir, name).write_bytes(b"\x89PNG\r\n\x1a\nMOCK" if kind == "image" else b"\0\0\0\x18ftypisomMOCK")
            result = envelope(kind)
            if kind == "video":
                result["duration"] = request["options"]["duration"]
            return {"simulation": True, "provider_result": result, "selected_artifacts": [name]}
        self.w.attach_grok_mock(provider)

    def tearDown(self):
        self.s.close()

    def run_flow(self, title, g):
        body = {"title": title, "graph": g}
        plan = self.w.plan(body)
        body.update(plan_hash=plan["hash"], confirmed=True, allow_models=False, request_id=uuid4().hex)
        run = self.w.start(body)
        self.w.tick()
        return self.w.run(run["id"])

    def test_lists_only_media_nodes_newest_first_with_prompt_status_and_asset_urls(self):
        self.assertEqual(self.w.media_jobs(), [])
        self.run_flow("글 정리", graph(node("a", "input", text="a\n\na"), node("b", "lines"), node("c", "summary")))
        self.assertEqual(self.w.media_jobs(), [], "그림·영상 노드가 없는 흐름은 목록에 없다")
        image = self.run_flow("그림 · 종이배", graph(node("a", "input", text="파란 종이배"), node("b", "grok_image")))
        video = self.run_flow("영상 · 물결", graph(node("a", "input", text="잔잔한 물결"), node("b", "grok_video", duration=7), node("c", "summary")))
        jobs = self.w.media_jobs()
        self.assertEqual([j["kind"] for j in jobs], ["video", "image"], "새것이 먼저")
        v, i = jobs
        self.assertEqual((v["run"], v["node"], v["id"]), (video["id"], "b", video["id"] + "/b"))
        self.assertEqual((v["prompt"], v["duration"], v["status"], v["simulation"], v["title"]), ("잔잔한 물결", 7, "succeeded", True, "영상 · 물결"))
        self.assertEqual((i["prompt"], i["duration"], i["status"]), ("파란 종이배", None, "succeeded"))
        for job in jobs:
            self.assertEqual(len(job["assets"]), 1)
            asset = job["assets"][0]
            self.assertEqual(asset["url"], f"/api/workbench/runs/{job['run']}/artifacts/b/0")
            self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(asset["kind"], job["kind"])
            self.assertIn("created_at", job)
        self.assertEqual(v["requested_duration"], 7)

    def test_pending_blocked_and_limit(self):
        body = {"title": "대기 중", "graph": graph(node("a", "input", text="아직 안 돌린 지시"), node("b", "grok_image"))}
        plan = self.w.plan(body)
        body.update(plan_hash=plan["hash"], confirmed=True, allow_models=False, request_id=uuid4().hex)
        self.w.start(body)  # tick 전: 아직 아무것도 안 만들어졌다
        job = self.w.media_jobs()[0]
        self.assertEqual(job["prompt"], "아직 안 돌린 지시", "기다리는 노드는 앞 입력 노드의 글에서 지시를 가져온다")
        self.assertNotEqual(job["status"], "succeeded")
        self.assertEqual(job["assets"], [])
        for n in range(4):
            self.run_flow(f"그림 {n}", graph(node("a", "input", text=f"지시 {n}"), node("b", "grok_image")))
        self.assertEqual(len(self.w.media_jobs(limit=3)), 3)
        self.assertEqual(len(self.w.media_jobs()), 5)


class MediaApiTests(unittest.TestCase):
    setUp = server_tests.ServerSecurity.setUp
    tearDown = server_tests.ServerSecurity.tearDown
    req = server_tests.ServerSecurity.req

    def test_media_endpoint_is_read_only_and_reports_connection_and_capabilities(self):
        before = set(self.s.store.dir.rglob("*"))
        res, raw = self.req("GET", "/api/workbench/media")
        self.assertEqual(res.status, 200)
        body = json.loads(raw)
        self.assertEqual(body["jobs"], [])
        self.assertFalse(body["connection"]["enabled"])
        self.assertEqual(set(body["capabilities"]), {"image", "video"})
        self.assertFalse(body["capabilities"]["image"]["enabled"])
        self.assertEqual(before, set(self.s.store.dir.rglob("*")), "읽기만 하고 아무것도 만들지 않는다")
        self.assertEqual(self.req("POST", "/api/workbench/media", {})[0].status, 403)


if __name__ == "__main__":
    unittest.main()
