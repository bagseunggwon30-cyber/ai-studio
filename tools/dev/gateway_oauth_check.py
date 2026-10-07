"""MCP 연결 문 흉내 점검: 실제 ChatGPT·Dots에 연결하기 전에, 이 PC 안에서만 OAuth 전 과정을 한 번 훑어 본다.

  python tools/dev/gateway_oauth_check.py

- 임시 회사(가짜 실행기)와 이 PC의 임시 포트(127.0.0.1)에서만 돈다. 터널·인터넷·진짜 서버(8765)·진짜 직원·진짜 ChatGPT는 쓰지 않는다.
- 진짜 회사의 data/ 폴더는 읽지도 쓰지도 않는다 (임시 폴더에 만들고 끝나면 지운다).
- 결과는 쉬운 글로 한 줄씩: 통과(✓)와 실패(✗). 하나라도 실패하면 종료 코드 1.
"""
import http.client
import json
import re
import secrets
import socket
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from studio.mcp_gateway import Gateway, pkce_challenge  # noqa: E402
from tests.helpers import TempStudio  # noqa: E402

PUBLIC = "https://gw.example.test"
HOST = "gw.example.test"
REDIRECT = "https://chatgpt.com/connector_platform_oauth_redirect"

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))
    return ok


def listening(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    print("MCP 연결 문 흉내 점검 (이 PC 안에서만, 터널·인터넷 없음)\n")
    company = TempStudio()
    gw = Gateway(company.cfg, company.store, company.engine, bind_port=0)
    try:
        def http_(method, path, body=None, headers=None, host=HOST):
            conn = http.client.HTTPConnection("127.0.0.1", gw.port, timeout=10)
            try:
                conn.request(method, path, body, {"Host": host, **(headers or {})})
                r = conn.getresponse()
                return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
            finally:
                conn.close()

        def mcp(token, message):
            head = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}
            if token:
                head["Authorization"] = "Bearer " + token
            status, headers, raw = http_("POST", "/mcp", json.dumps(message), head)
            return status, headers, json.loads(raw) if raw else None

        print("1. 문 열기와 닫기")
        free = socket.socket()
        free.bind(("127.0.0.1", 0))
        gw.bind_port = free.getsockname()[1]
        free.close()
        check("처음에는 꺼져 있고 포트가 닫혀 있어요", not gw.settings()["enabled"] and not listening(gw.bind_port))
        gw.configure({"public_url": PUBLIC, "enabled": True})
        check("켜면 이 PC 안(127.0.0.1)에서만 열려요", listening(gw.port) and gw.server.server_address[0] == "127.0.0.1")
        gw.set_permissions({"submit": False, "projects": {"demo": {"paths": ["docs/**"]}}})

        print("\n2. 안내문(메타데이터)")
        status, _, raw = http_("GET", "/.well-known/oauth-protected-resource")
        meta = json.loads(raw)
        check("보호 자원 안내문: 서버 주소와 로그인 서버가 맞아요", status == 200 and meta["resource"] == PUBLIC and meta["authorization_servers"] == [PUBLIC])
        status, _, raw = http_("GET", "/.well-known/oauth-authorization-server")
        auth = json.loads(raw)
        check("로그인 서버 안내문: S256만, 공개 클라이언트, iss 응답 지원", auth["issuer"] == PUBLIC and auth["code_challenge_methods_supported"] == ["S256"]
              and auth["token_endpoint_auth_methods_supported"] == ["none"] and auth["authorization_response_iss_parameter_supported"] is True)

        print("\n3. 앱 등록 (ChatGPT가 처음에 하는 일)")
        body = {"redirect_uris": [REDIRECT], "client_name": "ChatGPT (흉내)", "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"]}
        status, _, raw = http_("POST", "/oauth/register", json.dumps(body), {"Content-Type": "application/json"})
        client = json.loads(raw)
        check("허용된 ChatGPT 주소로 등록하면 받아 줘요", status == 201 and client.get("client_id"))
        status, _, raw = http_("POST", "/oauth/register", json.dumps({**body, "redirect_uris": ["https://evil.example/cb"]}), {"Content-Type": "application/json"})
        check("모르는 주소로 등록하려 하면 거절해요", status == 400 and json.loads(raw)["error"] == "invalid_redirect_uri")

        print("\n4. 동의 화면과 연결 번호")
        verifier = secrets.token_urlsafe(48)
        query = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT, "code_challenge": pkce_challenge(verifier),
                 "code_challenge_method": "S256", "state": "abc", "scope": "studio:read", "resource": PUBLIC + "/mcp"}
        status, headers, page = http_("GET", "/oauth/authorize?" + urlencode(query))
        text = page.decode("utf-8")
        check("동의 화면에 앱 이름·돌아갈 주소·허용할 일이 쉬운 말로 보여요", status == 200 and "ChatGPT (흉내)" in text and REDIRECT in text and "연결 번호" in text and "일의 목록·상태·진행·결과 파일 읽기" in text)
        check("동의 화면은 스크립트를 쓰지 않고 다른 곳에 끼워 넣을 수 없어요", "<script" not in text.lower() and headers["x-frame-options"] == "DENY" and "script-src" not in headers["content-security-policy"])
        form_id = re.search(r'name="form_id" value="([^"]+)"', text).group(1)

        def consent(code):
            return http_("POST", "/oauth/authorize", urlencode({"form_id": form_id, "code": code, "decision": "allow"}), {"Content-Type": "application/x-www-form-urlencoded"})

        status, headers, _ = consent("ZZZZ-ZZZZ")
        check("연결 번호를 틀리면 코드를 주지 않아요", status == 403 and "location" not in headers)
        number = gw.new_code()["code"]
        status, headers, _ = consent(number)
        loc = urlparse(headers.get("location", ""))
        params = {k: v[0] for k, v in parse_qs(loc.query).items()}
        check("맞는 연결 번호면 허용 코드가 와요 (state·iss 포함)", status == 302 and params.get("state") == "abc" and params.get("iss") == PUBLIC and params.get("code"))
        check("연결 번호는 한 번만 써요", http_("POST", "/oauth/authorize", urlencode({"form_id": form_id, "code": number, "decision": "allow"}), {"Content-Type": "application/x-www-form-urlencoded"})[0] == 400)

        print("\n5. 토큰 받기")
        form = {"grant_type": "authorization_code", "code": params["code"], "redirect_uri": REDIRECT, "client_id": client["client_id"], "resource": PUBLIC + "/mcp"}
        status, _, raw = http_("POST", "/oauth/token", urlencode({**form, "code_verifier": secrets.token_urlsafe(48)}), {"Content-Type": "application/x-www-form-urlencoded"})
        check("PKCE 확인값이 다르면 거절해요", status == 400 and json.loads(raw)["error"] == "invalid_grant")
        # 위 시도로 코드가 끝났으니 처음부터 다시
        _, _, page = http_("GET", "/oauth/authorize?" + urlencode(query))
        form_id = re.search(r'name="form_id" value="([^"]+)"', page.decode("utf-8")).group(1)
        status, headers, _ = consent(gw.new_code()["code"])
        code = parse_qs(urlparse(headers["location"]).query)["code"][0]
        form["code"] = code
        status, _, raw = http_("POST", "/oauth/token", urlencode({**form, "code_verifier": verifier}), {"Content-Type": "application/x-www-form-urlencoded"})
        tokens = json.loads(raw)
        check("맞는 확인값이면 액세스·새로고침 토큰을 줘요 (1시간)", status == 200 and tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600 and tokens["refresh_token"])
        status, _, raw = http_("POST", "/oauth/token", urlencode({**form, "code_verifier": verifier}), {"Content-Type": "application/x-www-form-urlencoded"})
        check("같은 코드를 다시 쓰면 거절해요", status == 400)
        access = tokens["access_token"]
        # 코드 재사용은 그 연결을 거두므로 새 연결을 하나 더 만든다
        _, _, page = http_("GET", "/oauth/authorize?" + urlencode(query))
        form_id = re.search(r'name="form_id" value="([^"]+)"', page.decode("utf-8")).group(1)
        code = parse_qs(urlparse(consent(gw.new_code()["code"])[1]["location"]).query)["code"][0]
        tokens = json.loads(http_("POST", "/oauth/token", urlencode({**form, "code": code, "code_verifier": verifier}), {"Content-Type": "application/x-www-form-urlencoded"})[2])
        access = tokens["access_token"]

        print("\n6. MCP 입구 (/mcp)")
        status, headers, _ = mcp(None, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        check("토큰이 없으면 401과 로그인 안내 머리글을 줘요", status == 401 and 'resource_metadata="' + PUBLIC + '/.well-known/oauth-protected-resource"' in headers.get("www-authenticate", ""))
        status, _, msg = mcp(access, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {t["name"] for t in msg["result"]["tools"]} if status == 200 else set()
        check("읽기 권한이면 읽기 도구 6개만 보여요", names == {"list_projects", "list_tasks", "task_status", "task_events", "task_result", "task_artifact"}, str(sorted(names)))
        payload = {"kind": "build", "title": "점검", "brief": "x", "allowed_paths": ["docs/**"],
                   "requirements": [{"id": "A", "text": "x", "evidence": [{"type": "test", "name": "answer_is_42"}]}]}
        status, _, msg = mcp(access, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "submit_task", "arguments": {"project": "demo", "key": "k", "payload": payload}}})
        check("읽기만 허용된 연결이 일을 맡기려 하면 거절해요 (카드도 안 생겨요)", status == 200 and msg["result"]["isError"] and company.store.list() == [])

        print("\n7. 새로고침과 끊기")
        old_refresh = tokens["refresh_token"]
        status, _, raw = http_("POST", "/oauth/token", urlencode({"grant_type": "refresh_token", "refresh_token": old_refresh, "client_id": client["client_id"]}), {"Content-Type": "application/x-www-form-urlencoded"})
        fresh = json.loads(raw)
        check("새로고침하면 새 토큰이 오고 옛 액세스 토큰은 멈춰요", status == 200 and mcp(access, {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 401
              and mcp(fresh["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 200)
        status, _, _ = http_("POST", "/oauth/token", urlencode({"grant_type": "refresh_token", "refresh_token": old_refresh, "client_id": client["client_id"]}), {"Content-Type": "application/x-www-form-urlencoded"})
        check("이미 바꾼 새로고침 토큰이 다시 오면 거절하고 그 연결을 모두 거둬요", status == 400 and mcp(fresh["access_token"], {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 401)
        _, _, page = http_("GET", "/oauth/authorize?" + urlencode(query))
        form_id = re.search(r'name="form_id" value="([^"]+)"', page.decode("utf-8")).group(1)
        code = parse_qs(urlparse(consent(gw.new_code()["code"])[1]["location"]).query)["code"][0]
        access = json.loads(http_("POST", "/oauth/token", urlencode({**form, "code": code, "code_verifier": verifier}), {"Content-Type": "application/x-www-form-urlencoded"})[2])["access_token"]
        conn_id = gw.status()["connections"][0]["id"]
        gw.revoke({"id": conn_id})
        check("사장님이 [끊기]를 누르면 바로 401이 돼요", mcp(access, {"jsonrpc": "2.0", "id": 1, "method": "ping"})[0] == 401)

        print("\n8. 문 밖으로 나가는 길이 없는지")
        statuses = [http_("GET", p)[0] for p in ("/", "/api/state", "/m", "/app.js", "/api/gateway", "/supervisor/v1")]
        check("대시보드 화면·/api/*·/m·정적 파일은 모두 404예요", statuses == [404] * 6, str(statuses))
        check("공개 주소도 127.0.0.1도 아닌 Host는 거절해요", http_("GET", "/.well-known/oauth-authorization-server", host="evil.example")[0] == 403)
        disk = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in company.cfg.data_dir.rglob("*") if p.is_file())
        check("디스크에는 토큰·코드가 없어요 (저장되는 것은 해시뿐)", access not in disk and fresh["refresh_token"] not in disk and code not in disk and verifier not in disk)
        check("감사 기록은 쉬운 글이고 비밀이 없어요", access not in (company.cfg.data_dir / "gateway" / "audit.jsonl").read_text(encoding="utf-8"))
        gw.configure({"enabled": False})
        check("끄면 포트가 다시 닫혀요", not listening(gw.bind_port))
    finally:
        gw.stop()
        company.close()
    print(f"\n결과: 통과 {passed}개, 실패 {failed}개")
    print("이 점검은 이 PC 안에서만 돌았어요. 터널·인터넷·진짜 ChatGPT·Dots와는 연결하지 않았어요 (그건 사장님이 터널을 켠 뒤 docs/MCP_GATEWAY.md 순서로 해 봐야 알 수 있어요).")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
