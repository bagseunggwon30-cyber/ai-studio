"""결재 대기 묶음 취소: Engine.cancel_waiting + POST /api/tasks/cancel-waiting (PC 화면만, 휴대폰 길에는 없음)."""

import http.client
import json
import shutil
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, TempStudio
from tests.test_server import free_port
from studio.engine import EngineError
from studio.server import StudioServer

TS = "pc.tail1a2b.ts.net"
BUILD = {"project": "demo", "kind": "build", "title": "정답", "brief": "docs/answer.txt에 42", "acceptance": ["검사 통과"], "allowed_paths": ["docs/**"]}


class Base(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        self.e = self.s.engine
        self.store = self.s.store

    def tearDown(self):
        self.s.close()

    def waiting_build(self, title="정답"):
        """진짜 개발 흐름(가짜 실행기)으로 결재 대기까지: 작업 폴더가 남아 있다."""
        task = self.e.create_task({**BUILD, "title": title})
        self.e._run_build(self.store.get(task.id))
        task = self.store.get(task.id)
        self.assertEqual(task.status, "awaiting_approval", task.blocked_reason)
        return task

    def waiting_plan(self):
        plan = self.e.submit_directive("정답 만들기", "demo")
        self.e._run_plan(self.store.get(plan.id))
        plan = self.store.get(plan.id)
        self.assertEqual(plan.status, "awaiting_approval", plan.blocked_reason)
        return plan

    def planted(self, status="awaiting_approval", kind="research", extra=None, title="Grok 시험"):
        """상태만 맞춰 심은 작업 (실행 없이)."""
        task = self.store.create_task(title=title, kind=kind, role="analyst", project="demo", status="ready", extra=extra or {})
        if status == "ready":
            return task
        self.store.transition(task, "running", by="test")
        if status == "running":
            return self.store.get(task.id)
        self.store.transition(self.store.get(task.id), "awaiting_approval", by="test")
        if status == "done":
            self.store.transition(self.store.get(task.id), "done", by="test")
        return self.store.get(task.id)


class CancelWaiting(Base):
    def test_cancels_only_waiting_and_explains_the_rest(self):
        build = self.waiting_build()
        plan = self.waiting_plan()
        research = self.planted()
        queued = self.e.create_task({**BUILD, "title": "아직 시작 전"})
        finished = self.planted(status="done", kind="build", title="끝난 일")
        gone = self.planted(title="이미 취소한 일")
        self.e.cancel(gone.id)
        blocked = self.planted(title="막힌 일")
        self.store.block(self.store.get(blocked.id), "막힘 시험")
        running = self.planted(status="running", title="일하는 중")
        worktree = Path(build.worktree)
        self.assertTrue(worktree.exists())

        ids = [build.id, plan.id, research.id, queued.id, finished.id, gone.id, blocked.id, running.id, "T9999"]
        result = self.e.cancel_waiting(ids)

        self.assertEqual(result["cancelled"], [build.id, plan.id, research.id])
        skipped = {s["id"]: s["reason"] for s in result["skipped"]}
        self.assertEqual(list(skipped), [queued.id, finished.id, gone.id, blocked.id, running.id, "T9999"])
        self.assertIn("준비", skipped[queued.id])
        self.assertEqual(skipped[finished.id], "이미 끝난 작업이에요.")
        self.assertEqual(skipped[gone.id], "이미 끝난 작업이에요.")
        self.assertIn("막힘", skipped[blocked.id])
        self.assertIn("작업 중", skipped[running.id])
        self.assertEqual(skipped["T9999"], "작업을 찾을 수 없어요.")
        for reason in skipped.values():
            self.assertNotRegex(reason, r"[A-Za-z]{4,}", "화면에 보이는 이유에 영어 문장이 없다")
        for task in (build, plan, research):
            fresh = self.store.get(task.id)
            self.assertEqual(fresh.status, "cancelled")
            self.assertEqual(fresh.history[-1]["note"], "취소")
            self.assertEqual(fresh.history[-1]["by"], "ceo")
        # 다른 상태는 그대로
        self.assertEqual(self.store.get(queued.id).status, "ready")
        self.assertEqual(self.store.get(finished.id).status, "done")
        self.assertEqual(self.store.get(blocked.id).status, "blocked")
        self.assertEqual(self.store.get(running.id).status, "running")
        # 개별 취소가 하던 일은 그대로: 작업 폴더 정리, 제품 저장소 main은 안 바뀐다
        self.assertFalse(worktree.exists())
        self.assertIsNone(self.store.get(build.id).worktree)
        # 이벤트 한 줄 (개별 취소 이벤트와 별개)
        events = [ev for ev in self.store.recent_events(200) if ev["type"] == "task.cancel_waiting"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message"], "결재 대기 3건 취소 · 건너뜀 6건")
        self.assertEqual(events[0]["data"]["cancelled"], [build.id, plan.id, research.id])

    def test_inbox_shrinks_and_second_call_skips(self):
        a, b = self.planted(), self.planted()
        self.assertEqual([t.id for t in self.store.list() if t.status == "awaiting_approval"], [a.id, b.id])
        self.assertEqual(self.e.cancel_waiting([a.id, b.id])["cancelled"], [a.id, b.id])
        self.assertEqual([t.id for t in self.store.list() if t.status == "awaiting_approval"], [])
        again = self.e.cancel_waiting([a.id])
        self.assertEqual(again["cancelled"], [])
        self.assertEqual(again["skipped"], [{"id": a.id, "reason": "이미 끝난 작업이에요."}])

    def test_duplicates_count_once(self):
        a = self.planted()
        result = self.e.cancel_waiting([a.id, a.id, a.id])
        self.assertEqual(result, {"cancelled": [a.id], "skipped": []})
        self.assertEqual(len([h for h in self.store.get(a.id).history if h["to"] == "cancelled"]), 1)

    def test_bad_input_is_refused_and_nothing_changes(self):
        a = self.planted()
        for bad in ([], None, "T0001", {"ids": [a.id]}, 5, ["T1"], ["t0001"], ["T0001 "], ["T0001/cancel"], ["../x"], [1], [None], [a.id, ""], ["T" + "1" * 13],
                    [a.id] * 101, [f"T{n:04d}" for n in range(1, 102)]):
            with self.subTest(bad=repr(bad)[:40]):
                with self.assertRaises(EngineError) as ctx:
                    self.e.cancel_waiting(bad)
                self.assertRegex(str(ctx.exception), r"[가-힣]", "쉬운 한국어 문구")
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval")
        # 100개는 된다 (없는 번호는 건너뜀)
        result = self.e.cancel_waiting([a.id] + [f"T9{n:03d}" for n in range(99)])
        self.assertEqual((len(result["cancelled"]), len(result["skipped"])), (1, 99))

    def test_only_ceo(self):
        a = self.planted()
        with self.assertRaises(EngineError):
            self.e.cancel_waiting([a.id], by="supervisor:x")
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval")

    def test_provider_task_stops_the_workbench_run(self):
        """provider 작업은 개별 취소와 똑같이 작업대 실행 후속 진행을 멈추는 길(workbench.halt)을 탄다."""
        grok = self.planted(extra={"provider_execution": "e" * 32, "workflow_run": "W" + "a" * 32})
        plain = self.planted()
        with mock.patch.object(self.e.workbench, "halt") as halt:
            result = self.e.cancel_waiting([grok.id, plain.id])
        self.assertEqual(result["cancelled"], [grok.id, plain.id])
        halt.assert_called_once_with("W" + "a" * 32)

    def test_one_failure_does_not_stop_the_rest(self):
        first = self.planted(title="첫째")
        # 실행 장부가 없으면 진짜 halt가 오류를 낸다 → 이 한 건만 건너뛰고 이유를 알린다
        broken = self.planted(extra={"provider_execution": "e" * 32, "workflow_run": "W" + "b" * 32}, title="장부 없는 일")
        last = self.planted(title="셋째")
        result = self.e.cancel_waiting([first.id, broken.id, last.id])
        self.assertEqual(result["cancelled"], [first.id, last.id])
        self.assertEqual([s["id"] for s in result["skipped"]], [broken.id])
        self.assertTrue(result["skipped"][0]["reason"].startswith("취소하지 못했어요."), result)
        self.assertRegex(result["skipped"][0]["reason"], r"[가-힣]")
        self.assertEqual(self.store.get(broken.id).status, "awaiting_approval", "실패한 것은 그대로 결재 대기")
        self.assertEqual((self.store.get(first.id).status, self.store.get(last.id).status), ("cancelled", "cancelled"))

    def test_unexpected_error_text_is_not_shown(self):
        a, b = self.planted(), self.planted()
        real = self.e.cancel

        def flaky(task_id, by="ceo"):
            if task_id == a.id:
                raise RuntimeError("Traceback: boom at line 3")
            return real(task_id, by=by)

        with mock.patch.object(self.e, "cancel", side_effect=flaky):
            result = self.e.cancel_waiting([a.id, b.id])
        self.assertEqual(result["cancelled"], [b.id])
        self.assertEqual(result["skipped"], [{"id": a.id, "reason": "취소하지 못했어요. 잠시 뒤 다시 해 보세요."}])


class CancelWaitingRoutes(Base):
    def setUp(self):
        super().setUp()
        shutil.copytree(ROOT / "ui", self.s.root / "ui")
        self.port = free_port()
        self.srv = StudioServer(self.s.cfg, self.s.store, self.s.engine, self.port)
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()

    def tearDown(self):
        self.srv.stop_lan(save=False)
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, method, path, body=None, host=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        return res, raw

    def desk(self, path, body=None, token=None, origin=None):
        headers = {"X-Studio-Token": self.srv.token if token is None else token}
        headers["Origin"] = origin or f"http://127.0.0.1:{self.port}"
        return self.req("POST", path, body if body is not None else {}, headers=headers)

    def test_needs_the_session_token_origin_and_host(self):
        a = self.planted()
        body = {"ids": [a.id]}
        self.assertEqual(self.req("POST", "/api/tasks/cancel-waiting", body)[0].status, 403, "토큰 없음")
        self.assertEqual(self.desk("/api/tasks/cancel-waiting", body, token="wrong")[0].status, 403, "토큰 틀림")
        self.assertEqual(self.desk("/api/tasks/cancel-waiting", body, origin="http://evil.example")[0].status, 403, "다른 사이트")
        res, _ = self.req("POST", "/api/tasks/cancel-waiting", body, host=f"evil.example:{self.port}", headers={"X-Studio-Token": self.srv.token})
        self.assertEqual(res.status, 403, "허용하지 않은 Host")
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval", "거절된 요청은 아무것도 바꾸지 않는다")
        # GET으로는 취소가 안 된다
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval")
        res, _ = self.req("GET", "/api/tasks/cancel-waiting")
        self.assertNotEqual(res.status, 200)
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval")

    def test_cancels_and_reports(self):
        a, b = self.planted(), self.planted()
        done = self.planted(status="done", kind="build")
        res, raw = self.desk("/api/tasks/cancel-waiting", {"ids": [a.id, b.id, done.id]})
        self.assertEqual(res.status, 200, raw)
        data = json.loads(raw)
        self.assertEqual((data["ok"], data["cancelled"]), (True, [a.id, b.id]))
        self.assertEqual(data["skipped"], [{"id": done.id, "reason": "이미 끝난 작업이에요."}])
        state = json.loads(self.req("GET", "/api/state")[1])
        self.assertEqual([t["id"] for t in state["tasks"] if t["status"] == "awaiting_approval"], [], "결재함이 비었다")
        self.assertEqual(sorted(t["id"] for t in state["tasks"] if t["status"] == "cancelled"), sorted([a.id, b.id]))

    def test_bad_bodies_get_a_400_with_easy_words(self):
        a = self.planted()
        cases = [{}, {"ids": []}, {"ids": "T0001"}, {"ids": ["abc"]}, {"ids": [a.id], "all": True}, {"ids": [a.id] * 101}, {"ids": [5]}]
        for body in cases:
            with self.subTest(body=repr(body)[:40]):
                res, raw = self.desk("/api/tasks/cancel-waiting", body)
                self.assertEqual(res.status, 400, raw)
                self.assertRegex(json.loads(raw)["error"], r"[가-힣]")
        res = self.req("POST", "/api/tasks/cancel-waiting", None, headers={"X-Studio-Token": self.srv.token, "Origin": f"http://127.0.0.1:{self.port}"})[0]
        self.assertEqual(res.status, 400, "본문이 없으면 ids가 없다")
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval")
        # JSON 객체가 아닌 본문
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/tasks/cancel-waiting", body=b"[1]", headers={"Host": f"127.0.0.1:{self.port}", "X-Studio-Token": self.srv.token,
                                                                             "Content-Type": "application/json"})
        res = conn.getresponse()
        res.read()
        conn.close()
        self.assertEqual(res.status, 400)
        self.assertEqual(self.store.get(a.id).status, "awaiting_approval")

    def test_phone_has_single_cancel_but_no_bulk_cancel(self):
        self.srv.remote.update(ts_hosts=[TS])
        code = json.loads(self.desk("/api/remote/pair")[1])["code"]
        res, raw = self.req("POST", "/m/api/pair", {"code": code, "name": "시험 휴대폰"}, host=TS, headers={"Origin": f"http://{TS}"})
        self.assertEqual(res.status, 200, raw)
        token = json.loads(raw)["token"]
        phone = lambda method, path, body=None: self.req(method, path, body, host=TS, headers={"X-Device-Token": token, "Origin": f"http://{TS}"})
        a, b = self.planted(), self.planted()
        # 묶음 취소 길은 휴대폰에 없다 (짝지은 기기여도 404, 기기 없이는 401, PC 길은 휴대폰 주소로 404)
        self.assertEqual(phone("POST", "/m/api/cancel-waiting", {"ids": [a.id, b.id]})[0].status, 404)
        self.assertEqual(self.req("POST", "/m/api/cancel-waiting", {"ids": [a.id]}, host=TS, headers={"Origin": f"http://{TS}"})[0].status, 401)
        self.assertEqual(phone("POST", "/api/tasks/cancel-waiting", {"ids": [a.id, b.id]})[0].status, 404)
        self.assertEqual(phone("POST", "/m/api/act", {"task": a.id, "action": "cancel-waiting"})[0].status, 404)
        self.assertEqual((self.store.get(a.id).status, self.store.get(b.id).status), ("awaiting_approval", "awaiting_approval"))
        # 개별 취소(결재 대기 한 건)는 휴대폰에서도 된다
        res, raw = phone("POST", "/m/api/act", {"task": a.id, "action": "cancel"})
        self.assertEqual(res.status, 200, raw)
        self.assertEqual((self.store.get(a.id).status, self.store.get(b.id).status), ("cancelled", "awaiting_approval"))
        state = json.loads(phone("GET", "/m/api/state")[1])
        self.assertEqual([t["id"] for t in state["inbox"]], [b.id])


if __name__ == "__main__":
    unittest.main()
