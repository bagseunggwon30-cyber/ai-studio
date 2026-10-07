"""MCP 연결 문(studio/mcp_gateway.py) 시험: 임시 회사 + 이 PC 로컬 포트의 연결 문 + ChatGPT 흉내 클라이언트.

인터넷·터널·진짜 서버(8765)·진짜 직원은 쓰지 않는다. 시간은 가짜 시계를 주입한다.
"""
import hashlib
import http.client
import json
import re
import secrets
import socket
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from studio import mcp_gateway
from studio.mcp_gateway import (MAX_BODY_MCP, MAX_CONCURRENT, Gateway, parse_public_url, pkce_challenge, redirect_allowed)
from studio.server import MAX_BODY, StudioServer
from studio.util import atomic_write_json
from tests.helpers import TempStudio

PUBLIC = "https://gw.example.test"
HOST = "gw.example.test"
CHATGPT = "https://chatgpt.com/connector_platform_oauth_redirect"
READ_TOOLS = {"list_projects", "list_tasks", "task_status", "task_events", "task_result", "task_artifact"}
SUBMIT_TOOLS = {"submit_task", "cancel_task"}
RUN_TOOLS = {"run_task"}


class FakeClock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


class GatewayCase(unittest.TestCase):
    def setUp(self):
        self.company = TempStudio()
        self.addCleanup(self.company.close)
        self.clock = FakeClock()
        self.gw = Gateway(self.company.cfg, self.company.store, self.company.engine, clock=self.clock, bind_port=0)
        self.addCleanup(self.gw.stop)
        for name in self.gw.limits:  # 속도 제한은 Limits 시험에서만 낮춘다
            self.gw.limits[name] = (100_000, 60.0)
        self.payload = {"kind": "build", "title": "게이트웨이 시험", "brief": "docs/answer.txt에 42", "allowed_paths": ["docs/**"],
                        "requirements": [{"id": "ANSWER", "text": "answer is 42", "evidence": [{"type": "test", "name": "answer_is_42"}]}]}

    # ---- 도구
    def enable(self):
        self.gw.configure({"public_url": PUBLIC, "enabled": True})
        return self.gw.port

    def http(self, method, path, body=None, headers=None, host=HOST):
        head = {"Host": host}
        head.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.gw.port, timeout=10)
        try:
            conn.request(method, path, body, head)
            response = conn.getresponse()
            raw = response.read()
            return response.status, {k.lower(): v for k, v in response.getheaders()}, raw
        finally:
            conn.close()

    def json_of(self, raw):
        return json.loads(raw.decode("utf-8")) if raw else None

    def register(self, redirect=CHATGPT, name="ChatGPT", **extra):
        body = {"redirect_uris": [redirect], "client_name": name, "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], **extra}
        status, _, raw = self.http("POST", "/oauth/register", json.dumps(body), {"Content-Type": "application/json"})
        return status, self.json_of(raw)

    def authorize_url(self, client_id, challenge, redirect=CHATGPT, **over):
        q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect, "code_challenge": challenge,
             "code_challenge_method": "S256", "state": "st-" + secrets.token_hex(4), "scope": "studio:read", "resource": PUBLIC + "/mcp"}
        q.update(over)
        return "/oauth/authorize?" + urlencode({k: v for k, v in q.items() if v is not None}), q

    def form_id(self, page):
        found = re.search(r'name="form_id" value="([^"]+)"', page.decode("utf-8"))
        self.assertTrue(found, page[:400])
        return found.group(1)

    def approve(self, form_id, code, decision="allow"):
        body = urlencode({"form_id": form_id, "code": code, "decision": decision})
        return self.http("POST", "/oauth/authorize", body, {"Content-Type": "application/x-www-form-urlencoded"})

    def redirect_params(self, headers):
        loc = urlparse(headers["location"])
        return loc, {k: v[0] for k, v in parse_qs(loc.query).items()}

    def token(self, **params):
        status, headers, raw = self.http("POST", "/oauth/token", urlencode(params), {"Content-Type": "application/x-www-form-urlencoded"})
        return status, headers, self.json_of(raw)

    def connect(self, scope="studio:read", name="ChatGPT", redirect=CHATGPT, resource=PUBLIC + "/mcp"):
        """ChatGPT 흉내: 등록 → 동의 화면 → 연결 번호 → 코드 → 토큰."""
        status, client = self.register(redirect, name)
        self.assertEqual(status, 201, client)
        verifier = secrets.token_urlsafe(48)
        url, q = self.authorize_url(client["client_id"], pkce_challenge(verifier), redirect, scope=scope, resource=resource)
        status, _, page = self.http("GET", url)
        self.assertEqual(status, 200, page[:300])
        status, headers, _ = self.approve(self.form_id(page), self.gw.new_code()["code"])
        self.assertEqual(status, 302)
        _, params = self.redirect_params(headers)
        self.assertEqual(params["state"], q["state"])
        extra = {"resource": resource} if resource else {}
        status, _, tokens = self.token(grant_type="authorization_code", code=params["code"], redirect_uri=redirect,
                                       client_id=client["client_id"], code_verifier=verifier, **extra)
        self.assertEqual(status, 200, tokens)
        return {"client_id": client["client_id"], "tokens": tokens, "verifier": verifier, "code": params["code"], "redirect": redirect}

    def mcp(self, token, body, headers=None, host=HOST):
        head = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
        if token is not None:
            head["Authorization"] = "Bearer " + token
        head.update(headers or {})
        status, out, raw = self.http("POST", "/mcp", body if isinstance(body, bytes) else json.dumps(body), head, host=host)
        return status, out, self.json_of(raw)

    def tools(self, token):
        status, _, msg = self.mcp(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(status, 200, msg)
        return {t["name"] for t in msg["result"]["tools"]}

    def call(self, token, name, **arguments):
        status, _, msg = self.mcp(token, {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
        self.assertEqual(status, 200, msg)
        return msg["result"]

    def allow_submit(self, paths=("docs/**",)):
        self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": list(paths)}}})


class Metadata(GatewayCase):
    def test_protected_resource_and_authorization_server_shapes(self):
        self.enable()
        for path, resource in (("/.well-known/oauth-protected-resource", PUBLIC), ("/.well-known/oauth-protected-resource/mcp", PUBLIC + "/mcp")):
            status, headers, raw = self.http("GET", path)
            data = self.json_of(raw)
            self.assertEqual(status, 200)
            self.assertEqual(data["resource"], resource)
            self.assertEqual(data["authorization_servers"], [PUBLIC])
            self.assertEqual(data["scopes_supported"], ["studio:read", "studio:submit"])
            self.assertNotIn("access-control-allow-origin", headers)
        status, _, raw = self.http("GET", "/.well-known/oauth-authorization-server")
        meta = self.json_of(raw)
        self.assertEqual(status, 200)
        self.assertEqual(meta["issuer"], PUBLIC)
        self.assertEqual(meta["authorization_endpoint"], PUBLIC + "/oauth/authorize")
        self.assertEqual(meta["token_endpoint"], PUBLIC + "/oauth/token")
        self.assertEqual(meta["registration_endpoint"], PUBLIC + "/oauth/register")
        self.assertEqual(meta["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(meta["token_endpoint_auth_methods_supported"], ["none"])
        self.assertEqual(meta["grant_types_supported"], ["authorization_code", "refresh_token"])
        self.assertEqual(meta["response_types_supported"], ["code"])
        self.assertEqual(meta["scopes_supported"], ["studio:read", "studio:submit"])
        self.assertIs(meta["authorization_response_iss_parameter_supported"], True)
        self.assertNotIn("client_id_metadata_document_supported", meta)  # CIMD는 서버가 바깥 주소를 가져와야 해서 지원하지 않는다

    def test_mcp_401_shape(self):
        self.enable()
        for token in (None, "x" * 43, secrets.token_urlsafe(32)):
            status, headers, body = self.mcp(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(status, 401)
            self.assertEqual(headers["www-authenticate"], f'Bearer resource_metadata="{PUBLIC}/.well-known/oauth-protected-resource", scope="studio:read"')
            self.assertEqual(body["error"]["code"], -32001)
        # 두 개의 Authorization 헤더 · Basic · 빈 Bearer
        status, _, _ = self.http("POST", "/mcp", b"{}", {"Content-Type": "application/json", "Authorization": "Basic abc"})
        self.assertEqual(status, 401)

    def test_unsupported_protocol_features_are_not_announced(self):
        self.enable()
        raw = self.http("GET", "/.well-known/oauth-authorization-server")[2].decode()
        for word in ("implicit", "password", "client_credentials", "plain", "client_secret"):
            self.assertNotIn(word, raw)


class Registration(GatewayCase):
    def test_allowed_and_rejected_redirects(self):
        self.enable()
        ok = [CHATGPT, "https://chatgpt.com/connector/oauth/abc_DEF-123", "https://claude.ai/api/mcp/auth_callback",
              "http://127.0.0.1:5555/callback", "http://localhost:8123/cb/x"]
        for uri in ok:
            with self.subTest(uri=uri):
                self.assertEqual(self.register(uri)[0], 201)
        bad = ["http://chatgpt.com/connector_platform_oauth_redirect", "https://evil.example/cb", CHATGPT + "?x=1", CHATGPT + "#f",
               "https://chatgpt.com/connector/oauth/", "https://chatgpt.com/connector/oauth/a/b", "https://chatgpt.com.evil.example/connector_platform_oauth_redirect",
               "https://chatgpt.com@evil.example/connector_platform_oauth_redirect", "http://127.0.0.1/cb", "http://127.0.0.1:99999/cb",
               "http://127.0.0.1:80@evil.example/cb", "http://127.0.0.1:5555/cb?x=1", "http://192.168.0.5:8080/cb", "javascript:alert(1)",
               "https://chat.openai.com/aip/g-123/oauth/callback", "https://chatgpt.com/connector/oauth/" + "a" * 129]
        for uri in bad:
            with self.subTest(uri=uri):
                status, body = self.register(uri)
                self.assertEqual((status, body["error"]), (400, "invalid_redirect_uri"))
        # 설정으로 더한 OpenAI 옛 주소는 그때부터 허용
        self.gw.configure({"extra_redirects": ["https://chat.openai.com/aip/g-123/oauth/callback"]})
        self.assertEqual(self.register("https://chat.openai.com/aip/g-123/oauth/callback")[0], 201)

    def test_rejects_other_grants_methods_and_bad_bodies(self):
        self.enable()
        for extra in ({"grant_types": ["implicit"]}, {"grant_types": ["password"]}, {"grant_types": ["client_credentials"]},
                      {"response_types": ["token"]}, {"token_endpoint_auth_method": "client_secret_basic"}, {"scope": "admin"}):
            with self.subTest(extra=extra):
                self.assertEqual(self.register(**extra)[0], 400)
        for body in (b"[]", b"{", b'{"redirect_uris": []}', b'{"redirect_uris": "x"}', b'{"redirect_uris": [1]}', b'{"redirect_uris": ["' + CHATGPT.encode() + b'"], "x": NaN}'):
            status, _, _ = self.http("POST", "/oauth/register", body, {"Content-Type": "application/json"})
            self.assertEqual(status, 400, body)
        status, _, _ = self.http("POST", "/oauth/register", b"redirect_uris=x", {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 400)
        self.assertEqual(self.http("GET", "/oauth/register")[0], 404)

    def test_unknown_metadata_is_ignored_and_name_is_cleaned(self):
        self.enable()
        status, body = self.register(name="  A\x00\n앱\u202e" + "x" * 100, logo_uri="https://evil.example/x.png", jwks_uri="https://evil.example/jwks")
        self.assertEqual(status, 201)
        self.assertNotIn("logo_uri", body)
        self.assertNotIn("jwks_uri", body)
        self.assertNotRegex(body["client_name"], r"[\x00-\x1f\u202e]")
        self.assertLessEqual(len(body["client_name"]), 60)
        stored = self.gw.clients()[body["client_id"]]
        self.assertEqual(set(stored), {"client_id", "client_name", "redirect_uris", "created", "created_ts"})

    def test_client_count_limit_evicts_unused_but_protects_connected(self):
        self.enable()
        ids = []
        for _ in range(mcp_gateway.MAX_CLIENTS):
            ids.append(self.register()[1]["client_id"])
            self.clock.advance(1)
        self.assertEqual(len(self.gw.clients()), mcp_gateway.MAX_CLIENTS)
        newest = self.register()[1]["client_id"]  # 가득 차면 가장 오래된 안 쓴 등록을 내보낸다
        self.assertEqual(len(self.gw.clients()), mcp_gateway.MAX_CLIENTS)
        self.assertNotIn(ids[0], self.gw.clients())
        self.assertIn(newest, self.gw.clients())
        # 모두 연결 중이면 새 등록은 거절
        self.gw._grants = {f"c{i}": {"id": f"c{i}", "client_id": cid, "scope": ["studio:read"], "access": {"hash": "a", "exp": 0}, "refresh": {"hash": "b", "exp": 0}}
                           for i, cid in enumerate(self.gw.clients())}
        status, body = self.register()
        self.assertEqual((status, body["error"]), (429, "temporarily_unavailable"))

    def test_old_unused_registrations_are_pruned(self):
        self.enable()
        old = self.register()[1]["client_id"]
        self.clock.advance(15 * 86400)
        fresh = self.register()[1]["client_id"]
        self.assertNotIn(old, self.gw.clients())
        self.assertIn(fresh, self.gw.clients())


class Consent(GatewayCase):
    def start(self, **over):
        self.enable()
        _, client = self.register()
        self.verifier = secrets.token_urlsafe(48)
        url, self.q = self.authorize_url(client["client_id"], pkce_challenge(self.verifier), **over)
        self.client_id = client["client_id"]
        status, headers, page = self.http("GET", url)
        return status, headers, page

    def test_consent_page_shows_app_redirect_and_permissions_in_easy_korean(self):
        status, headers, page = self.start()
        text = page.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("ChatGPT", text)
        self.assertIn(CHATGPT, text)
        self.assertIn("연결 번호", text)
        self.assertIn("일의 목록·상태·진행·결과 파일 읽기", text)
        self.assertNotIn("일 맡기기, 이 앱이 맡긴 일 취소하기", text)
        self.assertNotIn("실행 시작", text)
        self.assertIn("default-src 'none'", headers["content-security-policy"])
        self.assertNotIn("script", headers["content-security-policy"])
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertNotIn("<script", text.lower())
        self.assertNotIn("style=", text.lower())

    def test_client_name_is_escaped_not_trusted(self):
        self.enable()
        _, client = self.register(name='<script>alert(1)</script><img src=x onerror=alert(2)>"&')
        url, _ = self.authorize_url(client["client_id"], pkce_challenge(secrets.token_urlsafe(48)))
        page = self.http("GET", url)[2].decode("utf-8")
        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("이 이름은 앱이 스스로 적은 것이라", page)

    def test_wrong_then_right_number_and_single_use_and_state_iss(self):
        self.start()
        status, _, page = self.http("GET", self.authorize_url(self.client_id, pkce_challenge(self.verifier))[0])
        form = self.form_id(page)
        status, headers, body = self.approve(form, "WRONG-123")
        self.assertEqual(status, 403)
        self.assertNotIn("location", headers)
        self.assertIn("연결 번호가 맞지 않", body.decode("utf-8"))
        number = self.gw.new_code()["code"]
        status, headers, _ = self.approve(form, number.lower())  # 대소문자·하이픈은 상관없다
        self.assertEqual(status, 302)
        loc, params = self.redirect_params(headers)
        self.assertEqual(f"{loc.scheme}://{loc.netloc}{loc.path}", CHATGPT)
        self.assertEqual(params["iss"], PUBLIC)
        self.assertTrue(params["code"])
        # 번호도 폼도 한 번만
        _, _, page2 = self.http("GET", self.authorize_url(self.client_id, pkce_challenge(self.verifier))[0])
        self.assertEqual(self.approve(self.form_id(page2), number)[0], 403)
        self.assertEqual(self.approve(form, self.gw.new_code()["code"])[0], 400)

    def test_five_wrong_numbers_lock_for_a_minute_even_for_the_right_one(self):
        self.start()
        form = self.form_id(self.http("GET", self.authorize_url(self.client_id, pkce_challenge(self.verifier))[0])[2])
        for _ in range(5):
            self.assertEqual(self.approve(form, "AAAA-AAAA")[0], 403)
        number = self.gw.new_code()["code"]
        status, headers, body = self.approve(form, number)
        self.assertEqual(status, 429)
        self.assertIn("잠깐 막았어요", body.decode("utf-8"))
        self.assertIn("retry-after", headers)
        self.clock.advance(61)
        self.assertEqual(self.approve(form, number)[0], 302)

    def test_connection_number_expires_after_five_minutes_and_needs_the_dashboard(self):
        self.start()
        form = self.form_id(self.http("GET", self.authorize_url(self.client_id, pkce_challenge(self.verifier))[0])[2])
        number = self.gw.new_code()["code"]
        self.clock.advance(301)
        self.assertEqual(self.approve(form, number)[0], 403)
        self.assertEqual(self.approve(form, "")[0], 403)
        # 연결 화면 번호표도 10분 뒤에는 쓸 수 없다
        number = self.gw.new_code()["code"]
        self.clock.advance(601)
        self.assertEqual(self.approve(form, number)[0], 400)

    def test_deny_redirects_with_access_denied_and_iss(self):
        self.start()
        form = self.form_id(self.http("GET", self.authorize_url(self.client_id, pkce_challenge(self.verifier))[0])[2])
        status, headers, _ = self.approve(form, "", decision="deny")
        _, params = self.redirect_params(headers)
        self.assertEqual((status, params["error"], params["iss"]), (302, "access_denied", PUBLIC))
        self.assertNotIn("code", params)

    def test_authorize_errors_never_redirect_to_unknown_places_and_carry_iss(self):
        self.enable()
        _, client = self.register()
        challenge = pkce_challenge(secrets.token_urlsafe(48))
        for cid, over, label in ((client["client_id"], {"redirect_uri": "https://evil.example/cb"}, "다른 주소"), ("nope", {}, "모르는 앱")):
            url, _ = self.authorize_url(cid, challenge, **over)
            status, headers, page = self.http("GET", url)
            self.assertEqual(status, 400, label)
            self.assertNotIn("location", headers)
        url, _ = self.authorize_url(client["client_id"], challenge, redirect_uri=None)
        self.assertEqual(self.http("GET", url)[0], 400)
        cases = {"code_challenge_method": ("plain", "invalid_request"), "response_type": ("token", "unsupported_response_type"),
                 "scope": ("admin", "invalid_scope"), "resource": ("https://other.example/mcp", "invalid_target"),
                 "code_challenge": (None, "invalid_request")}
        for key, (value, error) in cases.items():
            with self.subTest(key=key):
                url, q = self.authorize_url(client["client_id"], challenge, **{key: value})
                status, headers, _ = self.http("GET", url)
                loc, params = self.redirect_params(headers)
                self.assertEqual(status, 302)
                self.assertEqual(f"{loc.scheme}://{loc.netloc}{loc.path}", CHATGPT)
                self.assertEqual((params["error"], params["iss"]), (error, PUBLIC))
                self.assertEqual(params["state"], q["state"])
        url, _ = self.authorize_url(client["client_id"], challenge, code_challenge_method=None)
        self.assertEqual(self.redirect_params(self.http("GET", url)[1])[1]["error"], "invalid_request")  # 방법을 안 적으면 plain이 되므로 거절
        # 같은 항목 두 번
        status, _, _ = self.http("GET", self.authorize_url(client["client_id"], challenge)[0] + "&state=again")
        self.assertEqual(status, 400)

    def test_read_only_setting_trims_requested_submit_on_the_consent_screen(self):
        self.enable()
        _, client = self.register()
        url, _ = self.authorize_url(client["client_id"], pkce_challenge(secrets.token_urlsafe(48)), scope="studio:read studio:submit")
        text = self.http("GET", url)[2].decode("utf-8")
        self.assertIn("이번에는 읽기만 허용돼요", text)
        self.assertNotIn("일 맡기기, 이 앱이 맡긴 일 취소하기", text)
        self.allow_submit()
        text = self.http("GET", url)[2].decode("utf-8")
        self.assertIn("일 맡기기, 이 앱이 맡긴 일 취소하기 (사장님이 허용한 프로젝트는 실행 시작도)", text)
        self.assertNotIn("이번에는 읽기만 허용돼요", text)

    def test_consent_css_is_served_and_nothing_else_static(self):
        self.enable()
        status, headers, raw = self.http("GET", "/oauth/consent.css")
        self.assertEqual((status, headers["content-type"].split(";")[0]), (200, "text/css"))
        self.assertIn(b"body", raw)


class Tokens(GatewayCase):
    def test_full_flow_and_token_shape(self):
        self.enable()
        flow = self.connect()
        tokens = flow["tokens"]
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["expires_in"], 3600)
        self.assertEqual(tokens["scope"], "studio:read")
        self.assertGreaterEqual(len(tokens["access_token"]), 43)
        self.assertGreaterEqual(len(tokens["refresh_token"]), 43)
        self.assertEqual(self.tools(tokens["access_token"]), READ_TOOLS)
        status, _, msg = self.mcp(tokens["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}}})
        self.assertEqual((status, msg["result"]["serverInfo"]["name"]), (200, "ai-studio-supervisor"))
        status, headers, _ = self.http("GET", "/mcp", headers={"Authorization": "Bearer " + tokens["access_token"]})
        self.assertEqual((status, headers["allow"]), (405, "POST"))
        self.assertEqual(self.http("GET", "/mcp")[0], 401)

    def test_pkce_s256_mismatch_and_bad_verifier_are_refused(self):
        self.enable()
        _, client = self.register()
        verifier = secrets.token_urlsafe(48)
        url, _ = self.authorize_url(client["client_id"], pkce_challenge(verifier))
        form = self.form_id(self.http("GET", url)[2])
        _, headers, _ = self.approve(form, self.gw.new_code()["code"])
        code = self.redirect_params(headers)[1]["code"]
        args = dict(grant_type="authorization_code", code=code, redirect_uri=CHATGPT, client_id=client["client_id"])
        self.assertEqual(self.token(**args, code_verifier="short")[0], 400)  # 형식이 틀린 것은 코드를 쓰지 않는다
        status, _, body = self.token(**args, code_verifier=secrets.token_urlsafe(48))
        self.assertEqual((status, body["error"]), (400, "invalid_grant"))
        # 틀린 시도 한 번으로 코드는 끝났다
        self.assertEqual(self.token(**args, code_verifier=verifier)[0], 400)
        self.assertEqual(self.token(**args)[0], 400)

    def test_code_reuse_is_refused_and_revokes_the_connection(self):
        self.enable()
        flow = self.connect()
        access = flow["tokens"]["access_token"]
        self.assertEqual(self.tools(access), READ_TOOLS)
        status, _, body = self.token(grant_type="authorization_code", code=flow["code"], redirect_uri=CHATGPT, client_id=flow["client_id"], code_verifier=flow["verifier"])
        self.assertEqual((status, body["error"]), (400, "invalid_grant"))
        self.assertEqual(self.mcp(access, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)
        self.assertEqual(self.gw.status()["connections"], [])

    def test_code_expires_after_sixty_seconds(self):
        self.enable()
        _, client = self.register()
        verifier = secrets.token_urlsafe(48)
        form = self.form_id(self.http("GET", self.authorize_url(client["client_id"], pkce_challenge(verifier))[0])[2])
        code = self.redirect_params(self.approve(form, self.gw.new_code()["code"])[1])[1]["code"]
        self.clock.advance(61)
        status, _, body = self.token(grant_type="authorization_code", code=code, redirect_uri=CHATGPT, client_id=client["client_id"], code_verifier=verifier)
        self.assertEqual((status, body["error"]), (400, "invalid_grant"))

    def test_code_is_bound_to_redirect_client_and_resource(self):
        self.enable()
        other = self.register("http://127.0.0.1:5555/cb")[1]["client_id"]
        for label, args in (("redirect", {"redirect_uri": "http://127.0.0.1:5555/cb"}), ("client", {"client_id": other}),
                            ("resource", {"resource": "https://other.example/mcp"}), ("resource-base", {"resource": PUBLIC})):
            with self.subTest(label):
                _, client = self.register()
                verifier = secrets.token_urlsafe(48)
                form = self.form_id(self.http("GET", self.authorize_url(client["client_id"], pkce_challenge(verifier))[0])[2])
                code = self.redirect_params(self.approve(form, self.gw.new_code()["code"])[1])[1]["code"]
                base = dict(grant_type="authorization_code", code=code, redirect_uri=CHATGPT, client_id=client["client_id"], code_verifier=verifier, resource=PUBLIC + "/mcp")
                base.update(args)
                status, _, body = self.token(**base)
                self.assertEqual(status, 400, body)
                self.assertIn(body["error"], ("invalid_grant", "invalid_target"))
        self.assertEqual(self.gw.status()["connections"], [])

    def test_resource_may_be_either_server_address_form(self):
        self.enable()
        for resource in (PUBLIC, PUBLIC + "/mcp", PUBLIC + "/mcp/", None):
            with self.subTest(resource=resource):
                flow = self.connect(resource=resource)
                self.assertEqual(self.tools(flow["tokens"]["access_token"]), READ_TOOLS)

    def test_only_two_grant_types(self):
        self.enable()
        flow = self.connect()
        for grant in ("password", "client_credentials", "implicit", "urn:ietf:params:oauth:grant-type:jwt-bearer", ""):
            status, _, body = self.token(grant_type=grant, client_id=flow["client_id"], username="a", password="b")
            self.assertEqual((status, body["error"]), (400, "unsupported_grant_type"))
        self.assertEqual(self.token(client_id=flow["client_id"])[0], 400)
        status, headers, body = self.token(grant_type="authorization_code", client_id="unknown", code="x" * 43, code_verifier="y" * 43)
        self.assertEqual((status, body["error"]), (401, "invalid_client"))
        self.assertIn("www-authenticate", headers)
        self.assertEqual(self.http("POST", "/oauth/token", b"{", {"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.http("POST", "/oauth/token", b"a=1&a=2", {"Content-Type": "application/x-www-form-urlencoded"})[0], 400)

    def test_access_token_lifetime_one_hour(self):
        self.enable()
        flow = self.connect()
        access = flow["tokens"]["access_token"]
        self.clock.advance(3599)
        self.assertEqual(self.tools(access), READ_TOOLS)
        self.clock.advance(2)
        self.assertEqual(self.mcp(access, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)

    def test_refresh_rotates_and_reuse_revokes_whole_connection(self):
        self.enable()
        flow = self.connect()
        first = flow["tokens"]
        status, _, second = self.token(grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=flow["client_id"])
        self.assertEqual(status, 200, second)
        self.assertNotEqual(second["access_token"], first["access_token"])
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.assertEqual(self.mcp(first["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)  # 바뀐 뒤 옛 액세스는 끝
        self.assertEqual(self.tools(second["access_token"]), READ_TOOLS)
        third = self.token(grant_type="refresh_token", refresh_token=second["refresh_token"], client_id=flow["client_id"])[2]
        self.assertIn("access_token", third)
        # 이미 바꾼 새로고침 토큰이 다시 오면 그 연결 전체를 거둔다
        status, _, body = self.token(grant_type="refresh_token", refresh_token=first["refresh_token"], client_id=flow["client_id"])
        self.assertEqual((status, body["error"]), (400, "invalid_grant"))
        self.assertEqual(self.mcp(third["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)
        self.assertEqual(self.token(grant_type="refresh_token", refresh_token=third["refresh_token"], client_id=flow["client_id"])[0], 400)
        self.assertEqual(self.gw.status()["connections"], [])
        self.assertTrue(any(r["type"] == "connection.revoked" for r in self.gw.audit_tail(30)))

    def test_refresh_needs_the_same_client_and_30_day_limit_and_cannot_widen(self):
        self.enable()
        flow = self.connect()
        other = self.register()[1]["client_id"]
        refresh = flow["tokens"]["refresh_token"]
        self.assertEqual(self.token(grant_type="refresh_token", refresh_token=refresh, client_id=other)[0], 400)
        self.assertEqual(self.token(grant_type="refresh_token", refresh_token=refresh, client_id=flow["client_id"], scope="studio:read studio:submit")[0], 400)
        self.assertEqual(self.token(grant_type="refresh_token", refresh_token="z" * 43, client_id=flow["client_id"])[0], 400)
        self.clock.advance(30 * 86400 + 1)
        self.assertEqual(self.token(grant_type="refresh_token", refresh_token=refresh, client_id=flow["client_id"])[0], 400)

    def test_refresh_scope_reduction_limits_tools_calls_and_survives_reload(self):
        self.enable()
        self.gw.set_permissions({"submit": True, "projects": {"demo": {
            "paths": ["docs/**"], "write": True, "run": True}}})
        flow = self.connect(scope="studio:read studio:submit")
        self.assertTrue(SUBMIT_TOOLS <= self.tools(flow["tokens"]["access_token"]))
        status, _, narrow = self.token(grant_type="refresh_token", client_id=flow["client_id"],
                                       refresh_token=flow["tokens"]["refresh_token"], scope="studio:read")
        self.assertEqual(status, 200)
        self.assertEqual(narrow["scope"], "studio:read")
        self.assertEqual(self.tools(narrow["access_token"]), READ_TOOLS)
        denied = self.call(narrow["access_token"], "submit_task", project="demo",
                           idempotency_key="narrowed-access", payload=self.payload)
        self.assertTrue(denied["isError"])
        self.assertEqual(self.company.store.list(), [])
        restored = Gateway(self.company.cfg, self.company.store, self.company.engine, clock=self.clock, bind_port=0)
        conn, scope = restored.verify_access(["Bearer " + narrow["access_token"]])
        self.assertEqual(scope, {"studio:read"})
        self.assertFalse(restored.actor_for(conn, scope)["projects"]["demo"]["write"])

    def test_dashboard_or_supervisor_tokens_are_not_accepted_here(self):
        self.enable()
        supervisor = "fixture-supervisor-" + "c" * 40
        atomic_write_json(self.company.cfg.data_dir / "supervisors.json", {"enabled": True, "clients": [
            {"id": "writer", "enabled": True, "token_sha256": hashlib.sha256(supervisor.encode()).hexdigest(), "projects": {"demo": {"read": True, "write": True, "paths": ["docs/**"]}}}]})
        for token in (supervisor, "session-token"):
            self.assertEqual(self.mcp(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)
        self.assertEqual(self.company.store.list(), [])

    def test_state_survives_restart_but_codes_and_numbers_do_not(self):
        self.enable()
        self.allow_submit()
        flow = self.connect(scope="studio:read studio:submit")
        number = self.gw.new_code()["code"]
        self.gw.stop()
        again = Gateway(self.company.cfg, self.company.store, self.company.engine, clock=self.clock, bind_port=0)
        self.addCleanup(again.stop)
        self.assertEqual(again.autostart(), "")
        self.assertTrue(again.running())
        self.gw = again
        access = flow["tokens"]["access_token"]
        self.assertEqual(self.tools(access), READ_TOOLS | SUBMIT_TOOLS)
        self.assertEqual(again.check_number(number), "wrong")


class McpPermissions(GatewayCase):
    def test_read_token_can_list_projects_and_tasks_only_where_granted(self):
        self.enable()
        self.gw.set_permissions({"submit": False, "projects": {"demo": {"paths": ["docs/**"]}}})
        access = self.connect()["tokens"]["access_token"]
        projects = json.loads(self.call(access, "list_projects")["content"][0]["text"])["projects"]
        self.assertEqual([(p["project"], p["can_submit"]) for p in projects], [("demo", False)])
        task = self.company.store.create_task(title="목록에 보일 일", kind="build", role="builder", project="demo", status="ready", brief="비밀 지시 본문")
        listed = self.call(access, "list_tasks", project="demo", limit=5)
        self.assertFalse(listed["isError"])
        data = json.loads(listed["content"][0]["text"])
        self.assertEqual([t["id"] for t in data["tasks"]], [task.id])
        self.assertNotIn("비밀 지시 본문", listed["content"][0]["text"])
        self.assertTrue(self.call(access, "list_tasks", project="other")["isError"], "열어 주지 않은 프로젝트는 목록도 거절")
        self.assertTrue(self.call(access, "list_tasks", project="demo", limit=999)["isError"])

    def test_read_token_sees_only_read_tools_and_cannot_submit(self):
        self.enable()
        self.gw.set_permissions({"submit": False, "projects": {"demo": {"paths": ["docs/**"]}}})
        access = self.connect()["tokens"]["access_token"]
        self.assertEqual(self.tools(access), READ_TOOLS)
        result = self.call(access, "submit_task", project="demo", key="k1", payload=self.payload)
        self.assertTrue(result["isError"])
        self.assertIn("권한이 부족해요", result["content"][0]["text"])
        self.assertTrue(self.call(access, "cancel_task", project="demo", task="T0001")["isError"])
        self.assertEqual(self.company.store.list(), [])
        status, _, msg = self.mcp(access, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}})
        self.assertEqual((status, msg["error"]["code"]), (200, -32602))
        for method in ("approve", "run", "settings"):
            self.assertEqual(self.mcp(access, {"jsonrpc": "2.0", "id": 4, "method": method})[2]["error"]["code"], -32601)

    def test_without_project_grant_nothing_is_visible(self):
        self.enable()
        access = self.connect()["tokens"]["access_token"]
        self.assertTrue(self.call(access, "task_status", project="demo", task="T0001")["isError"])

    def test_submit_scope_allows_only_the_chosen_folder_and_own_tasks(self):
        self.enable()
        self.allow_submit(("docs/**",))
        mine = self.connect(scope="studio:read studio:submit", name="Dots")["tokens"]["access_token"]
        other = self.connect(scope="studio:read studio:submit", name="Other")["tokens"]["access_token"]
        self.assertEqual(self.tools(mine), READ_TOOLS | SUBMIT_TOOLS)
        out = self.call(mine, "submit_task", project="demo", key="k-ok", payload=self.payload)
        self.assertFalse(out["isError"], out)
        task = json.loads(out["content"][0]["text"])["task"]
        record = self.company.store.get(task["id"])
        self.assertTrue(record.created_by.startswith("supervisor:gateway-"))
        # 범위 밖 폴더 · 범위 밖 근거 파일 · 허용하지 않은 프로젝트
        outside = {**self.payload, "allowed_paths": ["secrets/**"]}
        self.assertTrue(self.call(mine, "submit_task", project="demo", key="k-out", payload=outside)["isError"])
        reach = {**self.payload, "requirements": [{"id": "A", "text": "x", "evidence": [{"type": "file", "path": "secrets/a.txt"}]}]}
        self.assertTrue(self.call(mine, "submit_task", project="demo", key="k-ev", payload=reach)["isError"])
        self.assertTrue(self.call(mine, "submit_task", project="other", key="k-pr", payload=self.payload)["isError"])
        self.assertEqual(len(self.company.store.list()), 1)
        # 읽기는 같은 프로젝트면 누구나, 취소는 이 연결이 낸 것만
        self.assertFalse(self.call(other, "task_status", project="demo", task=task["id"])["isError"])
        self.assertTrue(self.call(other, "cancel_task", project="demo", task=task["id"])["isError"])
        self.assertEqual(self.company.store.get(task["id"]).status, "ready")
        self.assertFalse(self.call(mine, "cancel_task", project="demo", task=task["id"])["isError"])
        self.assertEqual(self.company.store.get(task["id"]).status, "cancelled")
        # 결재·병합 길은 도구 목록에도 없고, 실행 시작(run_task)은 CEO가 '실행 시작'을 켠 프로젝트가 있을 때만 보인다 (여기선 없다)
        self.assertEqual(self.tools(mine) & {"approve_task", "merge", "run_task"}, set())
        self.assertFalse(record.run_requested, "맡기기만으로는 실행되지 않는다")

    def test_submit_can_be_opened_for_one_project_while_another_stays_read_only(self):
        self.enable()
        self.company.engine.create_project({"key": "story", "title": "비 오는 날의 서점", "kind": "novel"})
        self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": ["docs/**"], "write": True},
                                                              "story": {"paths": [], "write": False}}})
        saved = self.gw.settings()["permissions"]["projects"]
        self.assertEqual((saved["demo"]["write"], saved["story"]["write"]), (True, False))
        self.assertEqual(self.gw.status()["permissions"]["projects"]["story"]["write"], False)
        # 401 안내에 일 맡기기를 열었다는 것이 들어가야 ChatGPT가 그 권한까지 요청한다 (읽기만이면 읽기만)
        status, headers, _ = self.mcp(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(status, 401)
        self.assertIn('scope="studio:read studio:submit"', headers["www-authenticate"])
        access = self.connect(scope="studio:read studio:submit", name="Dots")["tokens"]["access_token"]
        rows = {p["project"]: p for p in json.loads(self.call(access, "list_projects")["content"][0]["text"])["projects"]}
        self.assertEqual({k: v["can_submit"] for k, v in rows.items()}, {"demo": True, "story": False})
        story_paths = rows["story"]["paths"]
        # 읽기는 둘 다, 일 맡기기는 켜 둔 곳만
        self.assertFalse(self.call(access, "list_tasks", project="story")["isError"])
        refused = self.call(access, "submit_task", project="story", key="k-story",
                            payload={**self.payload, "allowed_paths": story_paths[:1]})
        self.assertTrue(refused["isError"], refused)
        self.assertFalse(self.call(access, "submit_task", project="demo", key="k-demo", payload=self.payload)["isError"])
        self.assertEqual([t.project for t in self.company.store.list()], ["demo"])
        # 모양: 칸 값이 참/거짓이 아니면 거절, 저장 파일을 손으로 고쳐 이상한 값이 들어가면 꺼짐으로 읽는다
        with self.assertRaises(ValueError):
            self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": ["docs/**"], "write": "yes"}}})
        with self.assertRaises(ValueError):
            self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": ["docs/**"], "extra": 1}}})
        cleaned = self.gw._clean_settings({"permissions": {"submit": True, "projects": {
            "demo": {"paths": ["docs/**"], "write": "yes"}, "story": {"paths": ["manuscript/**"], "write": False}, "old": {"paths": ["docs/**"]}}}})
        self.assertEqual({k: v["write"] for k, v in cleaned["permissions"]["projects"].items()}, {"demo": False, "story": False, "old": True})
        # 읽기만으로 바꾸면 켜 둔 곳도 일 맡기기가 닫힌다
        self.gw.set_permissions({"submit": False, "projects": {"demo": {"paths": ["docs/**"], "write": True}}})
        status, headers, _ = self.mcp(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn('scope="studio:read"', headers["www-authenticate"])
        self.assertNotIn("studio:submit", headers["www-authenticate"])
        self.assertTrue(self.call(access, "submit_task", project="demo", key="k-demo2", payload=self.payload)["isError"])

    def test_permission_changes_apply_immediately_and_never_upgrade_old_connections(self):
        self.enable()
        self.gw.set_permissions({"submit": False, "projects": {"demo": {"paths": ["docs/**"]}}})
        early = self.connect(scope="studio:read studio:submit")["tokens"]["access_token"]  # 읽기만 허용된 때 받은 연결
        self.assertEqual(self.tools(early), READ_TOOLS)
        self.allow_submit()
        self.assertEqual(self.tools(early), READ_TOOLS)  # 나중에 허용해도 이미 받은 연결은 그대로 (다시 연결해야 함)
        late = self.connect(scope="studio:read studio:submit")["tokens"]["access_token"]
        self.assertEqual(self.tools(late), READ_TOOLS | SUBMIT_TOOLS)
        self.gw.set_permissions({"submit": False, "projects": {"demo": {"paths": ["docs/**"]}}})
        self.assertEqual(self.tools(late), READ_TOOLS)
        self.assertTrue(self.call(late, "submit_task", project="demo", key="k", payload=self.payload)["isError"])
        self.assertEqual(self.company.store.list(), [])

    def test_revoke_is_immediate(self):
        self.enable()
        a = self.connect(name="A")["tokens"]["access_token"]
        b = self.connect(name="B")["tokens"]["access_token"]
        rows = self.gw.status()["connections"]
        self.assertEqual({r["name"] for r in rows}, {"A", "B"})
        victim = next(r for r in rows if r["name"] == "A")
        self.gw.revoke({"id": victim["id"]})
        self.assertEqual(self.mcp(a, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)
        self.assertEqual(self.tools(b), READ_TOOLS)
        self.gw.revoke({"all": True})
        self.assertEqual(self.mcp(b, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)
        with self.assertRaises(ValueError):
            self.gw.revoke({"id": victim["id"]})

    def test_changing_the_public_address_disconnects_everyone(self):
        self.enable()
        access = self.connect()["tokens"]["access_token"]
        self.gw.configure({"public_url": "https://other.example.test"})
        self.assertEqual(self.mcp(access, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, host="other.example.test")[0], 401)
        self.assertEqual(self.gw.status()["connections"], [])

    def test_permission_input_is_checked_with_the_existing_grant_rules(self):
        for bad in (["../x"], ["/abs"], ["a/../b"], ["C:/x"], ["*"], ["docs/*.md"], ["acceptance/**"], ["AGENTS.md"], [], ["x" * 300]):
            with self.subTest(paths=bad):
                if not bad:  # 비면 프로젝트 기본 범위
                    self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": bad}}})
                    self.assertEqual(self.gw.settings()["permissions"]["projects"]["demo"]["paths"], ["docs/**"])
                    continue
                with self.assertRaises(ValueError) as ctx:
                    self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": bad}}})
                self.assertRegex(str(ctx.exception), "[가-힣]")
        for bad in ({"submit": "yes", "projects": {}}, {"submit": True, "projects": {"nope": {"paths": ["docs/**"]}}},
                    {"submit": True, "projects": {"demo": {"paths": ["docs/**"], "write": "yes"}}}, {"submit": True, "extra": 1},
                    {"projects": [] }):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.gw.set_permissions(bad)
        self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": ["docs/a.md", "docs/sub/**"]}}})
        self.assertEqual(self.gw.settings()["permissions"]["projects"]["demo"]["paths"], ["docs/a.md", "docs/sub/**"])


class McpRun(GatewayCase):
    """실행 시작(run_task): CEO가 프로젝트마다 '실행 시작'을 켠 곳에서만, 이 앱이 맡긴 일에만, 동시에 3개까지.
    시험 회사의 엔진은 돌지 않는다 (엔진 thread 없음): 실제 직원을 부르지 않고 run_requested 표시와 상태만 본다."""

    PATHS = {"demo": ["docs/**"], "story": ["notes/**"], "art": ["brief/**"]}

    def setUp(self):
        super().setUp()
        self.enable()
        self.company.engine.create_project({"key": "story", "title": "비 오는 날의 서점", "kind": "novel"})
        self.company.engine.create_project({"key": "art", "title": "동네 카페 메뉴판", "kind": "design"})
        self.levels(demo="run", story="submit", art="read")
        self.assertIsNone(self.company.engine._thread)

    def levels(self, submit=True, **levels):
        projects = {key: {"paths": self.PATHS[key], "write": level != "read", "run": level == "run"} for key, level in levels.items()}
        self.gw.set_permissions({"submit": submit, "projects": projects})

    def app(self, name="Dots"):
        return self.connect(scope="studio:read studio:submit", name=name)["tokens"]["access_token"]

    def submit(self, token, project="demo", key="k1"):
        out = self.call(token, "submit_task", project=project, key=key, payload={**self.payload, "allowed_paths": self.PATHS[project]})
        self.assertFalse(out["isError"], out)
        return json.loads(out["content"][0]["text"])["task"]["id"]

    def start(self, token, project, task):
        return self.call(token, "run_task", project=project, task=task)

    def body(self, result):
        self.assertFalse(result["isError"], result)
        return json.loads(result["content"][0]["text"])

    def requested(self, task_id):
        return self.company.store.get(task_id).run_requested

    def test_levels_decide_can_submit_can_run_and_whether_the_run_tool_is_listed(self):
        token = self.app()
        rows = {p["project"]: p for p in self.body(self.call(token, "list_projects"))["projects"]}
        self.assertEqual({k: (v["can_submit"], v["can_run"]) for k, v in rows.items()}, {"demo": (True, True), "story": (True, False), "art": (False, False)})
        self.assertEqual(self.tools(token), READ_TOOLS | SUBMIT_TOOLS | RUN_TOOLS)
        saved = self.gw.status()["permissions"]["projects"]
        self.assertEqual({k: (v["write"], v["run"]) for k, v in saved.items()}, {"demo": (True, True), "story": (True, False), "art": (False, False)})
        # 실행 시작을 켠 프로젝트가 하나도 없으면 도구도 숨긴다 (일 맡기기만 있는 연결)
        self.levels(demo="submit", story="submit", art="read")
        self.assertEqual(self.tools(token), READ_TOOLS | SUBMIT_TOOLS)
        rows = {p["project"]: p for p in self.body(self.call(token, "list_projects"))["projects"]}
        self.assertEqual({k: v["can_run"] for k, v in rows.items()}, {"demo": False, "story": False, "art": False})
        # 다른 프로젝트 하나에만 켜도 보인다
        self.levels(demo="submit", story="run", art="read")
        self.assertEqual(self.tools(token), READ_TOOLS | SUBMIT_TOOLS | RUN_TOOLS)
        # 읽기만 연결은 어떤 설정에서도 run_task가 안 보인다
        reader = self.connect(name="Reader")["tokens"]["access_token"]
        self.assertEqual(self.tools(reader), READ_TOOLS)

    def test_run_task_starts_only_my_task_and_nothing_else_happens(self):
        token = self.app()
        tid = self.submit(token)
        self.assertFalse(self.requested(tid), "맡기기만으로는 실행되지 않는다")
        out = self.body(self.start(token, "demo", tid))
        self.assertEqual((out["started"], out["replayed"], out["run_requested"], out["task"]["status"]), (True, False, True, "ready"))
        self.assertTrue(self.requested(tid))
        self.assertEqual(self.company.store.get(tid).status, "ready", "엔진이 가져가기 전까지 상태는 그대로")
        self.assertEqual(self.company.store.runs(), [])
        self.assertIsNone(self.company.engine._thread)
        self.assertFalse(self.body(self.call(token, "task_status", project="demo", task=tid))["approved"])
        # 다시 불러도 안전하다 (같은 상태가 돌아오고 실행 요청 기록도 늘지 않는다)
        again = self.body(self.start(token, "demo", tid))
        self.assertEqual((again["started"], again["replayed"]), (True, True))
        self.assertEqual(len([e for e in self.company.store.recent_events(200) if e["type"] == "task.run_requested"]), 1)
        # 이 앱이 맡긴 일만: 다른 앱이 맡긴 일·사장님이 만든 일은 안 된다
        other = self.app("Other")
        theirs = self.submit(other, key="k-other")
        refused = self.start(token, "demo", theirs)
        self.assertTrue(refused["isError"])
        self.assertIn("이 연결이 맡긴 일만", refused["content"][0]["text"])
        self.assertFalse(self.requested(theirs))
        ceo = self.company.store.create_task(title="사장님이 만든 일", kind="build", role="builder", project="demo", status="ready", brief="x")
        self.assertTrue(self.start(token, "demo", ceo.id)["isError"])
        self.assertFalse(self.requested(ceo.id))
        self.assertTrue(self.start(token, "demo", "T9999")["isError"])
        self.assertTrue(self.start(token, "other", tid)["isError"])
        # 기록: 도구 이름만 (내용 없음), 활동 기록에는 누가 시작시켰는지
        audit = (self.company.cfg.data_dir / "gateway" / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"tool": "run_task"', audit)
        self.assertNotIn("게이트웨이 시험", audit)
        self.assertIn("supervisor.run", [e["type"] for e in self.company.store.recent_events(200)])

    def test_run_is_refused_where_only_submit_or_read_is_allowed(self):
        token = self.app()
        story = self.submit(token, "story", "k-story")  # 일 맡기기만 켠 프로젝트: 맡기기는 되지만
        refused = self.start(token, "story", story)
        self.assertTrue(refused["isError"])
        self.assertIn("실행 시작 권한이 없어요", refused["content"][0]["text"])
        self.assertFalse(self.requested(story))
        # 읽기만 연 프로젝트: 이 앱 이름으로 만들어진 일이라 해도 안 된다
        conn = self.gw.status()["connections"][0]["id"]
        art = self.company.store.create_task(title="읽기만 프로젝트의 일", kind="build", role="builder", project="art", status="ready", brief="x", created_by="supervisor:gateway-" + conn)
        refused = self.start(token, "art", art.id)
        self.assertTrue(refused["isError"])
        self.assertIn("읽기 전용", refused["content"][0]["text"])
        self.assertFalse(self.requested(art.id))
        # 열어 주지 않은 프로젝트
        self.assertTrue(self.start(token, "nope", art.id)["isError"])

    def test_run_has_a_cap_of_three_per_connection(self):
        token = self.app()
        ids = [self.submit(token, key=f"k{i}") for i in range(4)]
        for tid in ids[:3]:
            self.assertTrue(self.body(self.start(token, "demo", tid))["started"])
        refused = self.start(token, "demo", ids[3])
        self.assertTrue(refused["isError"])
        self.assertIn("동시에 실행을 시작한 일이 3개예요", refused["content"][0]["text"])
        self.assertFalse(self.requested(ids[3]))
        self.assertTrue(self.body(self.start(token, "demo", ids[1]))["replayed"], "이미 시작한 일을 다시 부르는 것은 상한에 걸리지 않는다")
        self.assertFalse(self.call(token, "cancel_task", project="demo", task=ids[0])["isError"])  # 하나가 끝나면 자리가 난다
        self.assertTrue(self.body(self.start(token, "demo", ids[3]))["started"])
        # 다른 앱은 따로 센다
        other = self.app("Other")
        self.assertTrue(self.body(self.start(other, "demo", self.submit(other, key="k-o")))["started"])

    def test_run_is_refused_during_an_emergency_stop(self):
        token = self.app()
        tid = self.submit(token)
        self.company.engine.emergency_stop("시험용 정지")
        refused = self.start(token, "demo", tid)
        self.assertTrue(refused["isError"])
        self.assertIn("긴급 정지", refused["content"][0]["text"])
        self.assertFalse(self.requested(tid))
        self.company.engine.resume()
        self.assertTrue(self.body(self.start(token, "demo", tid))["started"])

    def test_lowering_the_level_stops_the_same_token_right_away(self):
        token = self.app()
        tid = self.submit(token)
        self.levels(demo="submit", story="submit", art="read")  # 실행 시작만 끈다
        self.assertEqual(self.tools(token), READ_TOOLS | SUBMIT_TOOLS)
        refused = self.start(token, "demo", tid)
        self.assertTrue(refused["isError"])
        self.assertIn("권한이 부족해요", refused["content"][0]["text"])
        self.assertIn("실행 시작", refused["content"][0]["text"])
        self.assertFalse(self.requested(tid))
        self.assertFalse(self.call(token, "task_status", project="demo", task=tid)["isError"], "읽기와 일 맡기기는 그대로")
        self.levels(demo="run", story="submit", art="read")  # 다시 켜면 같은 연결이 바로 쓴다 (처음 받은 권한 안에서)
        self.assertTrue(self.body(self.start(token, "demo", tid))["started"])
        tid2 = self.submit(token, key="k2")
        self.levels(submit=False, demo="run", story="submit", art="read")  # 읽기만으로 바꾸면 모두 막힌다
        self.assertEqual(self.tools(token), READ_TOOLS)
        self.assertTrue(self.start(token, "demo", tid2)["isError"])
        self.assertFalse(self.requested(tid2))

    def test_run_needs_write_and_old_or_odd_settings_mean_off(self):
        for bad in ({"paths": ["docs/**"], "write": False, "run": True}, {"paths": ["docs/**"], "run": "yes"}, {"paths": ["docs/**"], "run": 1},
                    {"paths": ["docs/**"], "write": "yes", "run": True}, {"paths": ["docs/**"], "run": None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError) as ctx:
                self.gw.set_permissions({"submit": True, "projects": {"demo": bad}})
            self.assertRegex(str(ctx.exception), "[가-힣]")
        with self.assertRaises(ValueError) as ctx:
            self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": ["docs/**"], "write": False, "run": True}}})
        self.assertIn("실행 시작은 '일 맡기기'를 켠 프로젝트에서만", str(ctx.exception))
        self.assertEqual(self.gw.settings()["permissions"]["projects"]["demo"]["run"], True, "거절된 저장은 설정을 바꾸지 않는다")
        # 생략하면 꺼짐
        self.gw.set_permissions({"submit": True, "projects": {"demo": {"paths": ["docs/**"]}}})
        self.assertEqual(self.gw.settings()["permissions"]["projects"]["demo"], {"paths": ["docs/**"], "write": True, "run": False})
        # 저장 파일을 읽을 때: run 칸이 없는 옛 설정 · 이상한 값 · 일 맡기기가 꺼진 프로젝트는 모두 꺼짐
        cleaned = self.gw._clean_settings({"permissions": {"submit": True, "projects": {
            "old": {"paths": ["docs/**"]}, "odd": {"paths": ["docs/**"], "write": True, "run": "yes"}, "num": {"paths": ["docs/**"], "write": True, "run": 1},
            "readonly": {"paths": ["docs/**"], "write": False, "run": True}, "both": {"paths": ["docs/**"], "write": True, "run": True}}}})
        self.assertEqual({k: (v["write"], v["run"]) for k, v in cleaned["permissions"]["projects"].items()},
                         {"old": (True, False), "odd": (True, False), "num": (True, False), "readonly": (False, False), "both": (True, True)})

    def test_old_permission_file_without_run_field_keeps_the_run_tool_hidden(self):
        atomic_write_json(self.company.cfg.data_dir / "gateway.json", {"enabled": True, "public_url": PUBLIC, "permissions": {
            "submit": True, "projects": {"demo": {"paths": ["docs/**"], "write": True}}}})
        self.gw._settings = None  # 파일에서 다시 읽는다
        token = self.app()
        self.assertEqual(self.tools(token), READ_TOOLS | SUBMIT_TOOLS)
        tid = self.submit(token)
        self.assertTrue(self.start(token, "demo", tid)["isError"])
        self.assertFalse(self.requested(tid))

    def test_permission_change_is_recorded_with_the_number_of_run_projects(self):
        self.levels(demo="run", story="run", art="read")
        text = " ".join(r["text"] for r in self.gw.audit_tail(5))
        self.assertIn("일 맡기기 2개, 실행 시작 2개", text)
        self.assertIn("실행 시작 2개", " ".join(e["message"] for e in self.company.store.recent_events(20)))
        self.levels(submit=False, demo="run", story="submit", art="read")
        self.assertIn("읽기만 허용", self.gw.audit_tail(1)[0]["text"])

    def test_consent_screen_tells_about_run_in_easy_words(self):
        self.enable()
        _, client = self.register()
        url, _ = self.authorize_url(client["client_id"], pkce_challenge(secrets.token_urlsafe(48)), scope="studio:read studio:submit")
        text = self.http("GET", url)[2].decode("utf-8")
        self.assertIn("일 맡기기, 이 앱이 맡긴 일 취소하기 (사장님이 허용한 프로젝트는 실행 시작도)", text)
        self.assertIn("결재와 완료는 항상 사장님이 AI 스튜디오에서 직접 해요", text)


class Boundary(GatewayCase):
    def test_other_paths_are_404_and_no_cors(self):
        self.enable()
        for path in ("/", "/api/state", "/api/gateway", "/api/remote", "/m", "/m/api/state", "/app.js", "/index.html", "/style.css", "/gateway.js",
                     "/supervisor/v1", "/oauth", "/oauth/", "/oauth/authorize/x", "/.well-known/openid-configuration", "/mcp/", "/mcp/x", "/mcp%2f", "/Mcp",
                     "/oauth/token/", "/assets/ui/cat.png", "/../studio.toml", "/%2e%2e/studio.toml"):
            for method in ("GET", "POST"):
                with self.subTest(path=path, method=method):
                    status, headers, raw = self.http(method, path, b"{}" if method == "POST" else None, {"Content-Type": "application/json"})
                    self.assertEqual(status, 404, raw[:200])
                    self.assertNotIn("access-control-allow-origin", headers)
        status, headers, _ = self.http("OPTIONS", "/mcp", None, {"Origin": "https://chatgpt.com", "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertNotEqual(status, 200)
        for method in ("PUT", "PATCH"):
            self.assertEqual(self.http(method, "/oauth/token", b"x")[0], 404)
        self.assertEqual(self.http("GET", "/oauth/register")[0], 404)
        self.assertEqual(self.http("GET", "/oauth/token")[0], 404)
        self.assertEqual(self.http("POST", "/.well-known/oauth-authorization-server", b"{}")[0], 404)

    def test_unexpected_errors_answer_500_without_details_and_keep_serving(self):
        self.enable()
        original = self.gw.authorization_server

        def boom():
            raise RuntimeError("SECRET-INTERNAL-DETAIL C:\\private\\path")
        self.gw.authorization_server = boom
        status, _, raw = self.http("GET", "/.well-known/oauth-authorization-server")
        self.assertEqual((status, self.json_of(raw)), (500, {"error": "server_error"}))
        self.assertNotIn(b"SECRET", raw)
        self.gw.authorization_server = original
        self.assertEqual(self.http("GET", "/.well-known/oauth-authorization-server")[0], 200)
        self.assertTrue(any(r["type"] == "server.error" for r in self.gw.audit_tail(10)))
        self.assertNotIn("SECRET-INTERNAL-DETAIL", (self.company.cfg.data_dir / "gateway" / "audit.jsonl").read_text(encoding="utf-8"))

    def test_host_checks(self):
        self.enable()
        ok = [HOST, HOST + ":443", f"127.0.0.1:{self.gw.port}", f"localhost:{self.gw.port}", HOST.upper()]
        for host in ok:
            with self.subTest(host=host):
                self.assertEqual(self.http("GET", "/.well-known/oauth-authorization-server", host=host)[0], 200)
        for host in ("evil.example", f"{HOST}.evil.example", f"evil.example:{self.gw.port}", "127.0.0.1", "localhost", f"127.0.0.1:{self.gw.port + 1}", HOST + ":444", ""):
            with self.subTest(host=host):
                status, _, raw = self.http("GET", "/.well-known/oauth-authorization-server", host=host)
                self.assertEqual(status, 403)
                self.assertNotIn(b"issuer", raw)
        flow = self.connect()
        self.assertEqual(self.mcp(flow["tokens"]["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, host="evil.example")[0], 403)

    def test_origin_is_checked_on_mcp(self):
        self.enable()
        access = self.connect()["tokens"]["access_token"]
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        self.assertEqual(self.mcp(access, body, headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.mcp(access, body, headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.mcp(access, body, headers={"Origin": PUBLIC})[0], 200)
        self.assertEqual(self.mcp(access, body)[0], 200)
        status, _, _ = self.http("POST", "/mcp?token=" + access, json.dumps(body), {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": "Bearer " + access})
        self.assertEqual(status, 404)

    def test_off_by_default_port_closed_and_opens_only_when_enabled(self):
        port = free_port()
        gw = Gateway(self.company.cfg, self.company.store, self.company.engine, clock=self.clock, bind_port=port)
        self.addCleanup(gw.stop)
        self.assertFalse(gw.settings()["enabled"])
        self.assertEqual(gw.autostart(), "")
        self.assertFalse(listening(port))
        with self.assertRaises(ValueError):
            gw.new_code()  # 꺼져 있으면 연결 번호도 못 만든다
        with self.assertRaises(ValueError):
            gw.configure({"enabled": True})  # 공개 주소 없이는 못 켠다
        self.assertFalse(listening(port))
        gw.configure({"public_url": PUBLIC})
        self.assertFalse(listening(port))  # 주소만 넣어서는 열리지 않는다
        gw.configure({"enabled": True})
        self.assertTrue(listening(port))
        # 127.0.0.1에만 묶여 있다
        self.assertEqual(gw.server.server_address[0], "127.0.0.1")
        gw.configure({"enabled": False})
        self.assertFalse(listening(port))
        self.assertFalse(gw.settings()["enabled"])
        self.assertTrue((self.company.cfg.data_dir / "gateway.json").exists())

    def test_default_port_is_8767_and_failed_open_stays_off(self):
        self.assertEqual(Gateway(self.company.cfg, self.company.store, self.company.engine).settings()["port"], 8767)
        blocker = socket.socket()
        self.addCleanup(blocker.close)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        gw = Gateway(self.company.cfg, self.company.store, self.company.engine, clock=self.clock, bind_port=blocker.getsockname()[1])
        with self.assertRaises(ValueError) as ctx:
            gw.configure({"public_url": PUBLIC, "enabled": True})
        self.assertIn("포트", str(ctx.exception))
        self.assertFalse(gw.settings()["enabled"])
        self.assertFalse(gw.running())

    def test_public_address_validation_is_strict_and_easy(self):
        self.assertEqual(parse_public_url(" HTTPS://Gw.Example.Test/ "), "https://gw.example.test")
        self.assertEqual(parse_public_url("https://gw.example.test:8443"), "https://gw.example.test:8443")
        self.assertEqual(parse_public_url("https://gw.example.test:443"), "https://gw.example.test")
        self.assertEqual(parse_public_url("https://a-b.trycloudflare.com"), "https://a-b.trycloudflare.com")
        bad = ["", "   ", "gw.example.test", "http://gw.example.test", "https://gw.example.test/mcp", "https://gw.example.test/?a=1", "https://gw.example.test#x",
               "https://user:pw@gw.example.test", "https://127.0.0.1", "https://localhost", "https://192.168.0.5", "https://[::1]", "https://nas.local",
               "https://gw.example.test:0", "https://gw.example.test:70000", "https://gw example.test", "https://-bad.example.test", "https://한글.예시",
               "ftp://gw.example.test", "https://", "https://.example.test", "https://x..example.test", 5, None, "https://" + "a" * 70 + ".example.test"]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError) as ctx:
                parse_public_url(value)
            self.assertRegex(str(ctx.exception), "[가-힣]")
        for value in ("http://x.example.test", "https://x.example.test/mcp", ""):
            with self.assertRaises(ValueError):
                self.gw.configure({"public_url": value, "enabled": True})
        self.assertFalse(self.gw.running())

    def test_redirect_allow_list_unit(self):
        self.assertTrue(redirect_allowed("http://localhost:1/x"))
        self.assertFalse(redirect_allowed("http://localhost:70000/x"))
        self.assertFalse(redirect_allowed("http://localhost/x"))
        self.assertFalse(redirect_allowed(None))
        self.assertFalse(redirect_allowed("https://claude.ai/api/mcp/auth_callback/"))
        self.assertTrue(redirect_allowed("https://claude.ai/api/mcp/auth_callback", ()))

    def test_extra_redirect_setting_is_validated(self):
        for bad in ("x", ["http://a.example.test/cb"], ["https://a.example.test/cb?x=1"], ["https://192.168.0.1/cb"], ["https://nas.local/cb"], ["https://a.example.test"],
                    ["https://a.example.test/" + "x" * 600], [f"https://a{i}.example.test/cb" for i in range(11)]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.gw.configure({"extra_redirects": bad})
        self.gw.configure({"extra_redirects": ["https://a.example.test/cb", "https://a.example.test/cb"]})
        self.assertEqual(self.gw.settings()["extra_redirects"], ["https://a.example.test/cb"])

    def test_unknown_config_keys_are_refused(self):
        for body in ({"enabled": "yes"}, {"surprise": 1}, {"port": 80}, {"port": "8767"}, {"port": True}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.gw.configure(body)


class Limits(GatewayCase):
    def test_rate_limits_per_ip_and_per_connection_with_fake_clock(self):
        self.enable()
        self.gw.limits["register"] = (3, 60.0)
        statuses = [self.register()[0] for _ in range(5)]
        self.assertEqual(statuses, [201, 201, 201, 429, 429])
        status, headers, raw = self.http("POST", "/oauth/register", b"{}", {"Content-Type": "application/json"})
        self.assertEqual((status, headers["retry-after"] > "0"), (429, True))
        self.assertEqual(self.json_of(raw)["error"], "rate_limited")
        self.clock.advance(61)
        self.assertEqual(self.register()[0], 201)
        self.gw.limits["oauth"] = (2, 60.0)
        _, client = self.register()
        url, _ = self.authorize_url(client["client_id"], pkce_challenge(secrets.token_urlsafe(48)))
        self.assertEqual([self.http("GET", url)[0] for _ in range(3)], [200, 200, 429])
        self.clock.advance(61)
        self.assertEqual(self.http("GET", url)[0], 200)

    def test_mcp_per_connection_and_failed_auth_limits(self):
        self.enable()
        access = self.connect()["tokens"]["access_token"]
        self.gw.limits["mcp_conn"] = (3, 60.0)
        body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        self.assertEqual([self.mcp(access, body)[0] for _ in range(4)], [200, 200, 200, 429])
        self.clock.advance(61)
        self.assertEqual(self.mcp(access, body)[0], 200)
        self.gw.limits["bad_auth"] = (3, 60.0)
        codes = [self.mcp(secrets.token_urlsafe(32), body)[0] for _ in range(5)]
        self.assertEqual(codes, [401, 401, 401, 429, 429])
        self.assertEqual(self.mcp(access, body)[0], 429)  # 같은 곳에서 실패가 너무 많으면 잠깐 모두 막는다
        self.clock.advance(61)
        self.assertEqual(self.mcp(access, body)[0], 200)

    def test_body_limits_reuse_the_dashboard_mcp_limit(self):
        self.assertEqual(MAX_BODY_MCP, MAX_BODY)
        self.enable()
        status, _, _ = self.http("POST", "/oauth/register", b" " * (mcp_gateway.MAX_BODY_OAUTH + 1), {"Content-Type": "application/json"})
        self.assertEqual(status, 413)
        access = self.connect()["tokens"]["access_token"]
        self.assertEqual(self.mcp(access, b" " * (MAX_BODY_MCP + 1))[0], 413)
        self.assertEqual(self.mcp(access, b'{"jsonrpc":"2.0","id":1,"method":"ping"}')[0], 200)

    def test_concurrent_connection_limit_answers_503_quickly(self):
        self.enable()
        held = []
        try:
            for _ in range(MAX_CONCURRENT):
                s = socket.create_connection(("127.0.0.1", self.gw.port), timeout=5)
                held.append(s)
            time.sleep(0.3)
            extra = socket.create_connection(("127.0.0.1", self.gw.port), timeout=5)
            held.append(extra)
            extra.sendall(b"GET / HTTP/1.0\r\nHost: " + HOST.encode() + b"\r\n\r\n")
            self.assertIn(b"503", extra.recv(200))
        finally:
            for s in held:
                s.close()
        time.sleep(0.3)
        self.assertEqual(self.http("GET", "/.well-known/oauth-authorization-server")[0], 200)


class Secrets(GatewayCase):
    def all_text(self):
        data = self.company.cfg.data_dir
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in data.rglob("*") if p.is_file() and ".git" not in p.parts)

    def test_only_hashes_on_disk_and_no_secret_in_audit_events_or_status(self):
        self.enable()
        self.allow_submit()
        number = self.gw.new_code()["code"]
        status, client = self.register(name="비밀 시험 앱")
        verifier = secrets.token_urlsafe(48)
        url, q = self.authorize_url(client["client_id"], pkce_challenge(verifier), scope="studio:read studio:submit")
        form = self.form_id(self.http("GET", url)[2])
        _, headers, _ = self.approve(form, number)
        code = self.redirect_params(headers)[1]["code"]
        _, _, tokens = self.token(grant_type="authorization_code", code=code, redirect_uri=CHATGPT, client_id=client["client_id"], code_verifier=verifier, resource=PUBLIC + "/mcp")
        access, refresh = tokens["access_token"], tokens["refresh_token"]
        out = self.call(access, "submit_task", project="demo", key="k", payload={**self.payload, "title": "SECRET-TITLE-123", "brief": "SECRET-BRIEF-456"})
        self.assertFalse(out["isError"], out)
        self.token(grant_type="refresh_token", refresh_token="bogus" * 9, client_id=client["client_id"])
        self.mcp("not-a-token-" + "q" * 40, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        text = self.all_text()
        grants = json.loads((self.company.cfg.data_dir / "gateway" / "grants.json").read_text(encoding="utf-8"))
        hashes = json.dumps(grants)
        self.assertIn(hashlib.sha256(access.encode()).hexdigest(), hashes)
        self.assertIn(hashlib.sha256(refresh.encode()).hexdigest(), hashes)
        for secret in (access, refresh, code, verifier, form, number, number.replace("-", ""), "bogus" * 9):
            with self.subTest(secret=secret[:6]):
                self.assertNotIn(secret, text)
                self.assertNotIn(secret, json.dumps(self.gw.status()))
        audit = (self.company.cfg.data_dir / "gateway" / "audit.jsonl").read_text(encoding="utf-8")
        for needed in ("code.created", "client.registered", "authorize.approved", "token.issued", "tool.call", "mcp.denied", "token.denied"):
            self.assertIn(needed, audit)
        self.assertIn('"tool": "submit_task"', audit)
        for forbidden in ("SECRET-TITLE-123", "SECRET-BRIEF-456", "state=", "code=", "redirect_uri"):
            self.assertNotIn(forbidden, audit)
        events = json.dumps(self.company.store.recent_events(500), ensure_ascii=False)
        self.assertNotIn(access, events)
        self.assertNotIn(number, events)
        # gateway.json과 clients.json에도 토큰은 없다
        self.assertNotIn("token", (self.company.cfg.data_dir / "gateway.json").read_text(encoding="utf-8").lower())

    def test_audit_records_in_easy_korean_and_is_capped_per_minute(self):
        self.enable()
        for _ in range(mcp_gateway.AUDIT_PER_MINUTE + 50):
            self.gw.audit("mcp.denied", "인증이 안 된 요청을 막았어요", "denied")
        rows = (self.company.cfg.data_dir / "gateway" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(len(rows), mcp_gateway.AUDIT_PER_MINUTE + 5)
        self.clock.advance(61)
        self.gw.audit("x", "다음 분")
        tail = self.gw.audit_tail(5)
        self.assertEqual(tail[0]["text"], "다음 분")
        self.assertIn("너무 많아", tail[1]["text"])
        self.assertLessEqual(len(self.gw.status()["audit"]), 20)

    def test_status_never_contains_tokens_and_code_is_returned_once(self):
        self.enable()
        flow = self.connect()
        text = json.dumps(self.gw.status())
        self.assertNotIn(flow["tokens"]["access_token"], text)
        self.assertNotIn("hash", text)
        first = self.gw.new_code()
        self.assertRegex(first["code"], r"^[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$")
        self.assertEqual(first["expires_in"], 300)
        self.assertNotIn(first["code"], json.dumps(self.gw.status()))
        self.assertTrue(self.gw.status()["code_active"])


class DashboardApi(unittest.TestCase):
    """대시보드 서버(127.0.0.1)의 /api/gateway/* : CEO 전용(세션 토큰), 휴대폰·같은 와이파이 쪽에는 없음. 기존 /mcp는 그대로."""

    def setUp(self):
        self.company = TempStudio()
        self.addCleanup(self.company.close)
        self.server = StudioServer(self.company.cfg, self.company.store, self.company.engine, 0)
        self.server.gateway.bind_port = 0
        self.port = self.server.server_address[1]
        self.server.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.server.allowed_origins = {"http://" + h for h in self.server.allowed_hosts}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.finish)

    def finish(self):
        self.server.gateway.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)

    def api(self, method, path, body=None, token=True, host=None):
        head = {"Content-Type": "application/json"}
        if token:
            head["X-Studio-Token"] = self.server.token
        if host:
            head["Host"] = host
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, json.dumps(body) if body is not None else None, head)
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
        finally:
            conn.close()

    def test_status_is_off_by_default_and_has_projects(self):
        status, data = self.api("GET", "/api/gateway", token=False)
        self.assertEqual(status, 200)
        self.assertFalse(data["enabled"] or data["running"])
        self.assertEqual(data["public_url"], "")
        self.assertEqual([p["key"] for p in data["projects"]], ["demo"])
        self.assertEqual(data["permissions"], {"submit": False, "projects": {}})
        self.assertEqual(data["connections"], [])
        self.assertFalse(self.server.gateway.running())

    def test_writes_need_the_session_token_and_validate_in_easy_korean(self):
        for path, body in (("/api/gateway/config", {"enabled": True, "public_url": PUBLIC}), ("/api/gateway/permissions", {"submit": True, "projects": {}}),
                           ("/api/gateway/code", {}), ("/api/gateway/revoke", {"all": True})):
            self.assertEqual(self.api("POST", path, body, token=False)[0], 403)
        self.assertFalse(self.server.gateway.running())
        status, data = self.api("POST", "/api/gateway/config", {"enabled": True, "public_url": "http://x.example.test"})
        self.assertEqual(status, 400)
        self.assertIn("https://", data["error"])
        status, data = self.api("POST", "/api/gateway/config", {"enabled": True})
        self.assertEqual(status, 400)
        self.assertEqual(self.api("POST", "/api/gateway/code", {})[0], 400)
        self.assertFalse(self.server.gateway.running())

    def test_turn_on_make_number_set_permissions_and_turn_off(self):
        status, data = self.api("POST", "/api/gateway/config", {"enabled": True, "public_url": PUBLIC})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["running"] and data["enabled"])
        self.assertEqual(data["mcp_url"], PUBLIC + "/mcp")
        gateway_port = data["port"]
        self.assertTrue(listening(gateway_port))
        self.assertNotEqual(gateway_port, self.port)
        status, data = self.api("POST", "/api/gateway/code", {})
        self.assertEqual(status, 200)
        self.assertRegex(data["code"], r"^[A-Z0-9]{4}-[A-Z0-9]{4}$")
        status, data = self.api("POST", "/api/gateway/permissions", {"submit": True, "projects": {"demo": {"paths": ["docs/**"]}}})
        self.assertEqual((status, data["permissions"]["submit"]), (200, True))
        status, data = self.api("POST", "/api/gateway/permissions", {"submit": True, "projects": {"demo": {"paths": ["../x"]}}})
        self.assertEqual(status, 400)
        self.assertEqual(self.api("GET", "/api/gateway", token=False)[1]["permissions"]["projects"]["demo"]["paths"], ["docs/**"])
        status, data = self.api("POST", "/api/gateway/config", {"enabled": False})
        self.assertFalse(data["running"] or data["enabled"])
        self.assertFalse(listening(gateway_port))
        self.assertTrue(any(e["type"] == "gateway.enabled" for e in self.company.store.recent_events(50)))

    def test_not_served_on_the_phone_or_other_hosts_and_gateway_token_does_not_open_dashboard_mcp(self):
        self.assertEqual(self.api("GET", "/api/gateway", token=False, host="evil.example")[0], 403)
        self.server.lan_mode = True
        self.assertEqual(self.api("GET", "/api/gateway", token=False)[0], 404)
        self.assertEqual(self.api("POST", "/api/gateway/config", {"enabled": False})[0], 404)
        self.server.lan_mode = False
        # 연결 문의 토큰으로는 대시보드 쪽 /mcp(감독 토큰 Bearer)가 열리지 않는다
        atomic_write_json(self.company.cfg.data_dir / "supervisors.json", {"enabled": True, "clients": [
            {"id": "writer", "enabled": True, "token_sha256": hashlib.sha256(b"x" * 48).hexdigest(), "projects": {"demo": {"read": True, "write": True, "paths": ["docs/**"]}}}]})
        self.api("POST", "/api/gateway/config", {"enabled": True, "public_url": PUBLIC})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
                     {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": "Bearer " + "g" * 43})
        self.assertEqual(conn.getresponse().status, 401)
        conn.close()

    def test_second_server_for_lan_shares_the_same_gateway_object_but_serves_nothing_of_it(self):
        lan = StudioServer(self.company.cfg, self.company.store, self.company.engine, 0, parent=self.server)
        self.addCleanup(lan.server_close)
        self.assertIs(lan.gateway, self.server.gateway)


if __name__ == "__main__":
    unittest.main()
