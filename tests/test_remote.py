"""휴대폰 리모컨: 짝짓기(한 번 쓰는 번호·기기 토큰), Tailscale 주소·같은 와이파이 서버는 /m만, PC 대시보드는 그대로 이 PC에서만."""

import http.client
import json
import shutil
import threading
import unittest
from unittest import mock

from tests.helpers import ROOT, TempStudio
from tests.test_server import free_port
from studio.server import StudioServer

TS = "pc.tail1a2b.ts.net"


class Remote(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio()
        shutil.copytree(ROOT / "ui", self.s.root / "ui")
        self.port = free_port()
        self.srv = StudioServer(self.s.cfg, self.s.store, self.s.engine, self.port)
        self.th = threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.th.start()

    def tearDown(self):
        self.srv.stop_lan(save=False)
        self.srv.shutdown()
        self.srv.server_close()
        self.s.close()

    def req(self, method, path, body=None, host=None, headers=None, addr="127.0.0.1", port=None):
        conn = http.client.HTTPConnection(addr, port or self.port, timeout=10)
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

    def desk(self, path, body=None):
        return self.req("POST", path, body or {}, headers={"X-Studio-Token": self.srv.token, "Origin": f"http://127.0.0.1:{self.port}"})

    def phone(self, method, path, token="", body=None, host=TS, origin=None, addr="127.0.0.1", port=None):
        headers = {"X-Device-Token": token} if token else {}
        if origin:
            headers["Origin"] = origin
        return self.req(method, path, body, host=host, headers=headers, addr=addr, port=port)

    def pair(self, host=TS, addr="127.0.0.1", port=None):
        code = json.loads(self.desk("/api/remote/pair")[1])["code"]
        res, raw = self.phone("POST", "/m/api/pair", body={"code": code, "name": "시험 휴대폰"}, host=host, origin=f"http://{host}",
                              addr=addr, port=port)
        self.assertEqual(res.status, 200, raw)
        return json.loads(raw)["token"]

    def test_tailscale_host_gets_only_the_phone_page(self):
        self.assertEqual(self.phone("GET", "/m")[0].status, 403, "허용하지 않은 Tailscale 이름은 거절")
        self.srv.remote.update(ts_hosts=[TS])
        res, _ = self.phone("GET", "/")
        self.assertEqual((res.status, res.getheader("Location")), (302, "/m"))
        res, raw = self.phone("GET", "/m")
        self.assertEqual(res.status, 200)
        self.assertIn(b'<script src="/m.js" defer>', raw)
        self.assertNotIn(self.srv.token.encode(), raw, "PC 세션 토큰은 휴대폰 화면에 없다")
        self.assertEqual(self.phone("GET", "/m.js")[0].status, 200)
        self.assertEqual(self.phone("GET", "/api/state")[0].status, 404, "PC 대시보드 API는 이 PC에서만")
        self.assertEqual(self.phone("POST", "/api/directive", body={"text": "x", "project": "demo"})[0].status, 404)
        self.assertEqual(self.phone("GET", "/m/api/state")[0].status, 401)
        self.assertEqual(self.phone("GET", "/m/api/state", token="wrong")[0].status, 401)

    def test_pairing_and_phone_actions(self):
        self.srv.remote.update(ts_hosts=[TS])
        token = self.pair()
        self.assertNotIn(token, (self.s.cfg.data_dir / "remote.json").read_text(encoding="utf-8"), "토큰은 해시로만")
        # 번호는 한 번만
        res, raw = self.phone("POST", "/m/api/pair", body={"code": "ABCD-EFGH"}, origin=f"https://{TS}")
        self.assertEqual(res.status, 400)
        state = json.loads(self.phone("GET", "/m/api/state", token)[1])
        self.assertEqual((state["inbox"], state["stopped"], state["projects"][0]["key"]), ([], False, "demo"))
        # 지시 → 기획 결재 → 휴대폰에서 고른 퀘스트로 승인
        res, raw = self.phone("POST", "/m/api/directive", token, {"text": "정답 만들기", "project": "demo"}, origin=f"https://{TS}")
        self.assertEqual(res.status, 200, raw)
        plan_id = json.loads(raw)["task"]
        self.s.engine._run_plan(self.s.store.get(plan_id))
        state = json.loads(self.phone("GET", "/m/api/state", token)[1])
        self.assertEqual([t["id"] for t in state["inbox"]], [plan_id])
        detail = json.loads(self.phone("GET", f"/m/api/task/{plan_id}", token)[1])
        self.assertEqual(len(detail["quests"]), 2)
        self.assertEqual(self.phone("POST", "/m/api/act", token, {"task": plan_id, "action": "approve", "selected": [0]},
                                    origin="https://evil.example")[0].status, 403, "다른 사이트에서 온 요청은 거절")
        res, raw = self.phone("POST", "/m/api/act", token, {"task": plan_id, "action": "approve", "selected": [0]}, origin=f"https://{TS}")
        self.assertEqual(res.status, 200, raw)
        self.assertEqual(len(self.s.store.get(plan_id).children), 1)
        self.assertEqual(self.phone("POST", "/m/api/act", token, {"task": plan_id, "action": "archive"})[0].status, 404)
        # 긴급 정지·재개
        self.phone("POST", "/m/api/stop", token, {"stopped": True})
        self.assertTrue(self.s.store.get_state()["stopped"])
        self.phone("POST", "/m/api/stop", token, {"stopped": False})
        self.assertFalse(self.s.store.get_state()["stopped"])
        # PC에서 기기 끊기 → 그 토큰은 더는 안 된다
        info = json.loads(self.req("GET", "/api/remote")[1])
        self.assertEqual([d["name"] for d in info["devices"]], ["시험 휴대폰"])
        self.assertNotIn("hash", info["devices"][0])
        self.desk(f"/api/remote/devices/{info['devices'][0]['id']}/remove")
        self.assertEqual(self.phone("GET", "/m/api/state", token)[0].status, 401)

    def test_wrong_codes_lock_for_a_minute(self):
        self.srv.remote.update(ts_hosts=[TS])
        code = json.loads(self.desk("/api/remote/pair")[1])["code"]
        for _ in range(5):
            self.phone("POST", "/m/api/pair", body={"code": "ZZZZ-ZZZZ"})
        res, raw = self.phone("POST", "/m/api/pair", body={"code": code})
        self.assertEqual(res.status, 400)
        self.assertIn("잠깐 막혔어요", json.loads(raw)["error"])

    def test_same_wifi_server_serves_only_the_phone_page(self):
        with mock.patch("studio.remote.lan_ip", return_value="127.0.0.2"):
            info = json.loads(self.desk("/api/remote/lan", {"on": True})[1])
        self.assertTrue(info["lan_running"])
        host, port = self.srv.lan_server.server_address[:2]
        self.assertEqual(info["lan_url"], f"http://127.0.0.2:{port}/m")
        lan = f"{host}:{port}"
        self.assertEqual(self.req("GET", "/m", host=lan, addr=host, port=port)[0].status, 200)
        self.assertEqual(self.req("GET", "/api/state", host=lan, addr=host, port=port)[0].status, 404)
        self.assertEqual(self.req("GET", "/m", host=f"127.0.0.1:{self.port}", addr=host, port=port)[0].status, 403)
        token = self.pair(host=lan, addr=host, port=port)
        self.assertEqual(self.req("GET", "/m/api/state", host=lan, addr=host, port=port, headers={"X-Device-Token": token})[0].status, 200)
        pair = json.loads(self.desk("/api/remote/pair")[1])
        self.assertEqual(pair["urls"], [f"http://127.0.0.2:{port}/m#pair={pair['code']}"])
        self.desk("/api/remote/lan", {"on": False})
        self.assertIsNone(self.srv.lan_server)
        self.assertFalse(self.srv.remote.settings()["lan"])

    def test_firewall_check_route_reads_once_a_minute_and_is_local_only(self):
        self.assertEqual(json.loads(self.req("GET", "/api/remote/check")[1]), {"running": False, "checked": False}, "와이파이가 꺼져 있으면 점검하지 않는다")
        fake = {"checked": True, "category": "Public", "alias": "이더넷 2", "blocked": True, "allowed": False, "fix": "Set-NetConnectionProfile"}
        with mock.patch("studio.remote.lan_ip", return_value="127.0.0.2"), mock.patch("studio.remote.firewall_check", return_value=fake) as check:
            self.desk("/api/remote/lan", {"on": True})
            first = json.loads(self.req("GET", "/api/remote/check")[1])
            json.loads(self.req("GET", "/api/remote/check")[1])
        self.assertEqual(first, {"running": True, **fake})
        self.assertEqual(check.call_count, 1, "1분 안에는 다시 읽지 않는다")
        host, port = self.srv.lan_server.server_address[:2]
        self.assertEqual(self.req("GET", "/api/remote/check", host=f"{host}:{port}", addr=host, port=port)[0].status, 404, "휴대폰 쪽에는 안 준다")

    def test_qr_svg_is_local_only(self):
        res, raw = self.req("GET", "/api/remote/qr.svg?u=http%3A%2F%2F192.168.0.10%3A8766%2Fm%23pair%3DABCD-EFGH")
        self.assertEqual((res.status, res.getheader("Content-Type")), (200, "image/svg+xml; charset=utf-8"))
        self.assertTrue(raw.startswith(b"<svg"))
        self.srv.remote.update(ts_hosts=[TS])
        self.assertEqual(self.phone("GET", "/api/remote/qr.svg?u=x")[0].status, 404)


class FirewallReading(unittest.TestCase):
    EXE = r"C:\Py\python.exe"

    def read(self, category, rules, alias="이더넷 2"):
        from studio.remote import interpret_firewall

        return interpret_firewall({"alias": alias, "category": category, "rules": rules}, self.EXE)

    def test_public_block_is_found_and_the_fix_is_narrow(self):
        r = self.read("Public", [{"action": "Block", "profile": "Public"}, {"action": "Block", "profile": "Public"}])
        self.assertTrue(r["blocked"])
        self.assertFalse(r["allowed"])
        lines = r["fix"].splitlines()
        self.assertEqual(lines[0], "Set-NetConnectionProfile -InterfaceAlias '이더넷 2' -NetworkCategory Private")
        # 규칙은 개인 네트워크·이 프로그램에만 (공용 네트워크는 계속 막힌다). 포트는 정하지 않는다: 회사마다 와이파이 포트가 다르다
        self.assertIn("-Profile Private", lines[1])
        self.assertNotIn("-LocalPort", lines[1])
        self.assertIn(f"-Program '{self.EXE}'", lines[1])
        self.assertNotIn("Public -Action", lines[1])

    def test_private_network_with_an_allow_rule_is_clean(self):
        r = self.read("Private", [{"action": "Allow", "profile": "Private, Public"}])
        self.assertEqual((r["blocked"], r["allowed"], r["fix"]), (False, True, ""))

    def test_a_block_on_another_network_kind_does_not_count(self):
        r = self.read("Private", [{"action": "Block", "profile": "Public"}])
        self.assertFalse(r["blocked"])

    def test_any_profile_and_single_rule_object(self):
        # PowerShell은 규칙이 하나면 목록이 아니라 객체 하나로 준다
        r = self.read("Private", {"action": "Block", "profile": "Any"})
        self.assertTrue(r["blocked"])
        self.assertNotIn("Set-NetConnectionProfile", r["fix"], "이미 개인 네트워크면 네트워크 종류는 건드리지 않는다")
        self.assertIn("New-NetFirewallRule", r["fix"])

    def test_quotes_in_names_cannot_break_out_of_the_command(self):
        r = self.read("Public", [{"action": "Block", "profile": "Public"}], alias="Wi-Fi 'x'; calc")
        self.assertIn("'Wi-Fi ''x''; calc'", r["fix"])

    def test_not_windows_or_unreadable_says_unchecked(self):
        from studio import remote

        with mock.patch.object(remote.sys, "platform", "linux"):
            self.assertEqual(remote.firewall_check(self.EXE, "192.168.0.2"), {"checked": False})
        with mock.patch("studio.remote.subprocess.run", side_effect=OSError("없음")):
            self.assertEqual(remote.firewall_check(self.EXE, "192.168.0.2"), {"checked": False})


if __name__ == "__main__":
    unittest.main()
