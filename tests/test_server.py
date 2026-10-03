"""대시보드 서버 보안 테스트: Host 검사, 토큰, Origin, 경로 조작."""

import http.client
import json
import shutil
import socket
import threading
import unittest

from tests.helpers import ROOT, TempStudio
from studio.server import StudioServer


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerSecurity(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        shutil.copytree(ROOT / "ui", self.s.root / "ui")
        self.port = free_port()
        self.srv = StudioServer(self.s.cfg, self.s.store, self.s.engine, self.port)
        self.th = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.th.start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.s.close()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        conn.request(method, path, body=data, headers=h)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        return res, raw

    def test_index_has_token_and_csp(self):
        res, raw = self.req("GET", "/")
        self.assertEqual(res.status, 200)
        self.assertIn(self.srv.token.encode(), raw)
        csp = res.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self';", csp)
        self.assertIn("style-src 'self';", csp)
        # 얼굴 아틀라스는 blob: 그림 주소로 붙인다 (그림만 허용, 스크립트·스타일은 그대로)
        self.assertIn("img-src 'self' data: blob:;", csp)
        self.assertNotIn("blob:", csp.split("script-src")[1].split(";")[0])
        self.assertEqual(res.getheader("X-Frame-Options"), "DENY")

    def test_state(self):
        res, raw = self.req("GET", "/api/state")
        self.assertEqual(res.status, 200)
        data = json.loads(raw)
        self.assertEqual(data["studio"]["name"], "Test Studio")
        self.assertEqual([p["key"] for p in data["projects"]], ["demo"])
        # 새 버전 알림: 켜진 뒤 코드가 바뀌면 restart, 화면이 다시 읽게 버전도 바뀐다
        self.assertFalse(data["studio"]["restart"])
        self.srv.code_at, self.srv._code_check = -1, (0.0, False)
        again = json.loads(self.req("GET", "/api/state")[1])
        self.assertTrue(again["studio"]["restart"])
        self.assertNotEqual(again["version"], data["version"])

    def test_login_routes(self):
        opened = []
        self.s.engine.login_opener = opened.append
        self.assertIsNone(json.loads(self.req("GET", "/api/state")[1])["status"]["needs_login"])
        self.s.engine._need_login("codex", "quota", "T0001")
        state = json.loads(self.req("GET", "/api/state")[1])
        self.assertEqual(state["status"]["needs_login"]["runtime"], "codex")
        res, raw = self.post("/api/login/open", {"runtime": "claude"})
        self.assertEqual((res.status, opened), (200, ["codex", "claude"]), raw)
        self.assertEqual(self.post("/api/login/open", {"runtime": "grok"})[0].status, 400)
        res, raw = self.post("/api/login/done")
        self.assertEqual((res.status, json.loads(raw)["retried"]), (200, []))
        self.assertIsNone(json.loads(self.req("GET", "/api/state")[1])["status"]["needs_login"])
        self.assertEqual(self.req("POST", "/api/login/open", {"runtime": "codex"})[0].status, 403, "토큰 없으면 못 연다")

    def test_login_script(self):
        from studio import login
        text = login.script("codex", [r"C:\Program Files\codex.exe", "logout"], [r"C:\Program Files\codex.exe", "login"])
        self.assertIn('"C:\\Program Files\\codex.exe" logout\r\n"C:\\Program Files\\codex.exe" login', text)
        self.assertNotIn("api-key", text)
        self.assertEqual(login.login_runtime("fake", "codex"), "codex")
        self.assertEqual(login.login_runtime("claude", "codex"), "claude")
        self.assertIsNone(login.login_runtime("grok", "grok"))

    def test_rejected_post_still_answers(self):
        # 본문을 읽지 않고 거절하면 윈도우에서 가끔 '연결 중단'(WinError 10053)이 났다: 큰 본문이어도 403을 받아야 한다
        big = {"x": "a" * 300_000}
        for _ in range(3):
            res, _ = self.req("POST", "/api/directive", big)  # 토큰 없음
            self.assertEqual(res.status, 403)

    def test_task_usage(self):
        from studio.server import task_usage
        runs = [{"task": "T1", "duration_s": 90, "usage": {"input_tokens": 1000, "output_tokens": 200}},
                {"task": "T1", "duration_s": 30, "usage": {"input_tokens": None, "output_tokens": "x"}},
                {"task": "T2", "duration_s": 6}]
        self.assertEqual(task_usage(runs), {"T1": {"runs": 2, "tokens": None, "minutes": 2.0, "skills": [], "applied": [], "told": False},
                                            "T2": {"runs": 1, "tokens": None, "minutes": 0.1, "skills": [], "applied": [], "told": False}})
        # 배운 스킬: 본문이 붙은 것·따랐다고 알린 것 (알림이 없는 실행만 있으면 told는 거짓)
        skilled = task_usage([{"task": "T3", "skills": ["tidy@2", "memo@1"], "skills_applied": ["tidy"]},
                              {"task": "T3", "skills": ["tidy@2"], "skills_applied": None},
                              {"task": "T4", "skills": ["memo@1"], "skills_applied": None}])
        self.assertEqual((skilled["T3"]["skills"], skilled["T3"]["applied"], skilled["T3"]["told"]), (["memo", "tidy"], ["tidy"], True))
        self.assertEqual((skilled["T4"]["applied"], skilled["T4"]["told"]), ([], False))
        self.s.engine.create_task({"project": "demo", "kind": "build", "title": "t", "brief": "b", "acceptance": ["a"]})
        task = json.loads(self.req("GET", "/api/state")[1])["tasks"][0]
        self.assertEqual(task["usage"], {"runs": 0, "minutes": 0.0, "tokens": None, "skills": [], "applied": [], "told": False})

    def test_skill_api(self):
        res, raw = self.post("/api/skills", {"title": "시그널", "name": "signals", "description": "이벤트를 만들 때", "body": "connect로 잇는다", "learned_by": ["builder"]})
        self.assertEqual(res.status, 200, raw)
        res, raw = self.req("GET", "/api/state")
        state = json.loads(raw)
        self.assertEqual(state["skills"], [{"slug": "signals", "title": "시그널", "description": "이벤트를 만들 때",
                                            "learned_by": ["builder"], "source": "ceo", "created": state["skills"][0]["created"],
                                            "version": 1, "updated": "", "change": "", "how": "ceo", "projects": [], "kinds": []}])
        self.assertEqual(state["self_learning"], {"on": True, "limit": 3, "today": 0})
        res, raw = self.req("GET", "/api/skills/signals")
        detail = json.loads(raw)
        self.assertEqual(detail["body"], "connect로 잇는다")
        self.assertEqual([h["version"] for h in detail["history"]], [1])
        self.assertEqual(detail["usage"], {"runs": 0, "told": 0, "applied": 0, "tasks": 0, "smooth": 0})
        # 스스로 배우기 스위치, '더 좋게 고쳐 오기'
        res, raw = self.post("/api/settings/self-learning", {"enabled": False})
        self.assertEqual(json.loads(raw)["self_learning"], False)
        res, raw = self.post("/api/skills/study", {"role": "reviewer", "topic": "", "project": "demo", "target": "signals"})
        self.assertEqual(res.status, 200, raw)
        self.assertEqual(self.s.store.get(json.loads(raw)["task"]).target, "signals")
        res, _ = self.post("/api/skills/signals/learn", {"role": "reviewer", "learned": True})
        self.assertEqual(res.status, 200)
        # 쓰는 곳 바꾸기 (목록이 아니면 거절)
        res, raw = self.post("/api/skills/signals/scope", {"projects": [], "kinds": ["build"]})
        self.assertEqual((res.status, json.loads(raw)["skill"]["kinds"]), (200, ["build"]))
        res, _ = self.post("/api/skills/signals/scope", {"projects": "demo", "kinds": []})
        self.assertEqual(res.status, 400)
        # 스킬 성적표: 배운 직원마다 배우기 전·후 (기록이 없으면 0건)
        res, raw = self.req("GET", "/api/skills/report")
        report = json.loads(raw)["skills"]
        self.assertEqual([l["role"] for l in report[0]["learners"]], ["builder", "reviewer"])
        self.assertEqual(report[0]["learners"][0]["after"], {"tasks": 0, "smooth": 0})
        # 상태: 업무 카드·층
        state = json.loads(self.req("GET", "/api/state")[1])
        builder = next(m for m in state["team"] if m["key"] == "builder")
        self.assertEqual((builder["seat"], builder["floor"]), (1, 1))
        self.assertTrue(builder["card"]["can"])
        self.assertEqual(state["floors"]["count"], 1)
        res, raw = self.post("/api/skills/study", {"role": "analyst", "topic": "공부할 것", "project": "demo"})
        self.assertEqual(res.status, 200, raw)
        self.assertEqual(self.s.store.get(json.loads(raw)["task"]).kind, "skill")
        for bad in ("/api/skills/../x", "/api/skills/NOPE"):
            res, _ = self.req("GET", bad)
            self.assertIn(res.status, (400, 404), bad)
        res, _ = self.post("/api/skills/signals/remove")
        self.assertEqual(res.status, 200)
        res, _ = self.req("GET", "/api/skills/signals")
        self.assertEqual(res.status, 400)

    def test_state_reads_events_before_tasks(self):
        # 기록을 작업 목록보다 먼저 읽어야 알림("퀘스트 n개 붙였어요")이 작업 내용과 어긋나지 않는다
        store = self.s.store
        calls = []
        orig_events, orig_list = store.recent_events, store.list

        def events(*a, **k):
            calls.append("events")
            return orig_events(*a, **k)

        def tasks(*a, **k):
            calls.append("list")
            return orig_list(*a, **k)

        store.recent_events, store.list = events, tasks
        try:
            res, _ = self.req("GET", "/api/state")
        finally:
            del store.recent_events, store.list
        self.assertEqual(res.status, 200)
        self.assertEqual(calls[:2], ["events", "list"])

    def test_bad_host_rejected(self):
        res, _ = self.req("GET", "/api/state", headers={"Host": f"evil.example:{self.port}"})
        self.assertEqual(res.status, 403)

    def test_post_needs_token(self):
        res, _ = self.req("POST", "/api/directive", {"text": "x", "project": "demo"})
        self.assertEqual(res.status, 403)
        res, _ = self.req("POST", "/api/directive", {"text": "x", "project": "demo"}, {"X-Studio-Token": "wrong"})
        self.assertEqual(res.status, 403)
        self.assertEqual(self.s.store.list(), [])

    def test_post_bad_origin_rejected(self):
        res, _ = self.req("POST", "/api/directive", {"text": "x", "project": "demo"}, {"X-Studio-Token": self.srv.token, "Origin": "http://evil.example"})
        self.assertEqual(res.status, 403)

    def test_post_ok(self):
        res, raw = self.req("POST", "/api/directive", {"text": "정답 파일을 만들어", "project": "demo"}, {"X-Studio-Token": self.srv.token, "Origin": f"http://127.0.0.1:{self.port}"})
        self.assertEqual(res.status, 200, raw)
        tasks = self.s.store.list()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].status, "queued")

    def test_ui_files(self):
        sprites = self.s.root / "ui" / "assets" / "sprites"
        sprites.mkdir(parents=True, exist_ok=True)
        (sprites / "index.json").write_text("{}", encoding="utf-8")
        (self.s.root / "ui" / "notes.txt").write_text("비밀 아님", encoding="utf-8")
        res, raw = self.req("GET", "/assets/sprites/index.json")
        self.assertEqual(res.status, 200)
        self.assertIn("application/json", res.getheader("Content-Type"))
        # index.html이 부르는 화면 파일이 모두 나와야 한다
        for path, ctype in (("/data.js", "javascript"), ("/popups.js", "javascript"), ("/scene.js", "javascript"), ("/effects.js", "javascript"),
                            ("/sound.js", "javascript"), ("/popups.css", "text/css"), ("/assets/portraits.png", "image/png"),
                            ("/assets/bg/meeting.png", "image/png"), ("/assets/ui/icon-logo.png", "image/png"),
                            ("/assets/fonts/Galmuri11.woff2", "font/woff2")):
            res, _ = self.req("GET", path)
            self.assertEqual(res.status, 200, path)
            self.assertIn(ctype, res.getheader("Content-Type"), path)
        for bad in ("/assets/../../studio.toml", "/assets/..%2F..%2Fstudio.toml", "/assets/nope.png", "/notes.txt", "/../ui-old/app.js"):
            res, _ = self.req("GET", bad)
            self.assertEqual(res.status, 404, bad)

    def test_board_files_and_mascot(self):
        # 진행판 화면 파일과 기본 발표 캐릭터 (index.html이 부른다)
        for path, ctype in (("/board.js", "javascript"), ("/board.css", "text/css"), ("/assets/mascot/mascot.json", "application/json"),
                            ("/assets/mascot/normal.png", "image/png"), ("/assets/mascot/happy.png", "image/png"), ("/assets/mascot/worried.png", "image/png")):
            res, _ = self.req("GET", path)
            self.assertEqual(res.status, 200, path)
            self.assertIn(ctype, res.getheader("Content-Type"), path)
        default = json.loads(self.req("GET", "/assets/mascot/mascot.json")[1])
        for mood in default["moods"].values():
            self.assertTrue((self.s.root / "ui" / "assets" / "mascot" / mood["image"]).is_file(), mood)
        # 사장님 그림이 없으면 빈 설정 (404 대신) → 화면이 기본 그림을 쓴다
        res, raw = self.req("GET", "/assets/custom/mascot/mascot.json")
        self.assertEqual((res.status, json.loads(raw)), (200, {}))
        # 넣으면 그대로 나오고, 다른 종류·밖으로 나가는 경로는 막힌다
        folder = self.s.cfg.data_dir / "assets" / "mascot"
        folder.mkdir(parents=True)
        (folder / "mascot.json").write_text('{"version": 1}', encoding="utf-8")
        (folder / "me.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (folder / "run.js").write_text("alert(1)", encoding="utf-8")
        self.assertEqual(json.loads(self.req("GET", "/assets/custom/mascot/mascot.json")[1]), {"version": 1})
        self.assertEqual(self.req("GET", "/assets/custom/mascot/me.png")[0].status, 200)
        for bad in ("/assets/custom/mascot/run.js", "/assets/custom/mascot/../../studio.toml", "/assets/custom/mascot/none.png"):
            self.assertEqual(self.req("GET", bad)[0].status, 404, bad)

    def post(self, path, body=None):
        return self.req("POST", path, body or {}, {"X-Studio-Token": self.srv.token, "Origin": f"http://127.0.0.1:{self.port}"})

    def test_game_screen_api(self):
        res, raw = self.req("GET", "/api/state")
        data = json.loads(raw)
        self.assertEqual(data["day"], 1)
        builder = next(p for p in data["team"] if p["key"] == "builder")
        self.assertEqual((builder["name"], builder["character"], builder["state"]), ("솔", "sol", "rest"))
        self.assertEqual(builder["look"]["hair"], "base")
        self.assertIn("hair", data["look_options"])

        # 꾸미기: 허용 목록 밖 값은 기본값으로
        res, raw = self.post("/api/team/builder/look", {"look": {"hair": "blonde", "height": "giant"}})
        self.assertEqual(res.status, 200, raw)
        self.assertEqual(json.loads(raw)["look"], {"style": "base", "hair": "blonde", "outfit": "base", "height": 0, "head": 0, "build": 0, "shoulders": 0, "chest": 0, "waist": 0, "hips": 0, "hair_volume": 0})
        res, _ = self.post("/api/team/nobody/look", {"look": {}})
        self.assertEqual(res.status, 400)
        # 꾸미기도 토큰이 있어야 바뀐다
        res, _ = self.req("POST", "/api/team/builder/look", {"look": {"hair": "red"}})
        self.assertEqual(res.status, 403)

        res, raw = self.post("/api/settings/goals", {"week": "  보스전  ", "month": 500})
        self.assertEqual(json.loads(raw)["goals"], {"week": "보스전", "month": 99})
        res, raw = self.req("GET", "/api/state")
        self.assertEqual(json.loads(raw)["goals"]["week"], "보스전")

        res, _ = self.post("/api/alerts/read")
        self.assertEqual(res.status, 200)
        res, raw = self.req("GET", "/api/diary?day=1")
        self.assertEqual(res.status, 200)
        self.assertEqual(json.loads(raw)["days"], 1)
        res, _ = self.req("GET", "/api/diary?day=9")
        self.assertEqual(res.status, 400)

        res, raw = self.post("/api/directive", {"text": "지시", "project": "demo"})
        tid = json.loads(raw)["task"]
        res, _ = self.req("GET", f"/api/tasks/{tid}/report")
        self.assertEqual(res.status, 400)  # 리서치 작업이 아님
        res, _ = self.post(f"/api/tasks/{tid}/archive", {"archived": True})
        self.assertEqual(res.status, 400)  # 결재 대기가 아님
        res, _ = self.post("/api/trophies/play", {"task": tid})
        self.assertEqual(res.status, 400)  # 선반에 없는 작업은 실행하지 않는다

    def test_bad_input(self):
        res, _ = self.req("POST", "/api/directive", {"text": "", "project": "demo"}, {"X-Studio-Token": self.srv.token})
        self.assertEqual(res.status, 400)
        res, _ = self.req("GET", "/api/runs/..%5C..%5Cstudio.toml")
        self.assertEqual(res.status, 400)
        res, _ = self.req("GET", "/api/tasks/T9999")
        self.assertEqual(res.status, 400)
        res, _ = self.req("GET", "/../studio.toml")
        self.assertEqual(res.status, 404)


if __name__ == "__main__":
    unittest.main()
