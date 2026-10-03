"""MCP protocol and authority checks, real local HTTP with synthetic credentials."""
import base64
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from studio.server import StudioServer
from studio.supervisor_mcp import build
from studio.util import atomic_write_json, clean_child_env, no_window_flags
from tests.helpers import ROOT, TempStudio

TOKEN="fixture-mcp-writer-"+ "a"*48
READER="fixture-mcp-reader-"+ "b"*48


class McpHTTP(unittest.TestCase):
    def setUp(self):
        self.company=TempStudio()
        self.addCleanup(self.company.close)
        rows=[]
        for actor,token,write in (("writer",TOKEN,True),("reader",READER,False)):
            rows.append({"id":actor,"enabled":True,"token_sha256":hashlib.sha256(token.encode()).hexdigest(),
                "projects":{"demo":{"read":True,"write":write,"paths":["docs/**"]}}})
        atomic_write_json(self.company.cfg.data_dir/"supervisors.json",{"enabled":True,"clients":rows})
        self.server=StudioServer(self.company.cfg,self.company.store,self.company.engine,0)
        self.port=self.server.server_address[1]
        self.server.allowed_hosts={f"127.0.0.1:{self.port}",f"localhost:{self.port}"}
        self.server.allowed_origins={"http://"+h for h in self.server.allowed_hosts}
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.finish)
        self.payload={"kind":"build","title":"MCP fixture","brief":"write 42","allowed_paths":["docs/**"],
            "requirements":[{"id":"ANSWER","text":"answer is 42","evidence":[
                {"type":"test","name":"answer_is_42"},{"type":"file","path":"docs/answer.txt"}]}]}

    def finish(self):
        self.server.shutdown();self.server.server_close();self.thread.join(5)

    def request(self,body=None,*,method="POST",token=TOKEN,headers=None,path="/mcp"):
        head={"Content-Type":"application/json","Accept":"application/json, text/event-stream",
              "MCP-Protocol-Version":"2025-11-25"}
        if token is not None:head["Authorization"]="Bearer "+token
        head.update(headers or {})
        conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=5)
        data=body if isinstance(body,bytes) else json.dumps(body).encode() if body is not None else b""
        conn.request(method,path,data,head)
        response=conn.getresponse();raw=response.read();status=response.status;out=dict(response.getheaders())
        conn.close()
        return status,out,json.loads(raw) if raw else None

    def call(self,name,**arguments):
        status,_,msg=self.request({"jsonrpc":"2.0","id":10,"method":"tools/call",
                                  "params":{"name":name,"arguments":arguments}})
        self.assertEqual(status,200)
        return msg["result"]

    def data(self,name,**arguments):
        result=self.call(name,**arguments)
        self.assertFalse(result["isError"],result)
        return json.loads(result["content"][0]["text"])

    def submit(self):
        return self.data("submit_task",project="demo",key="mcp-http-one",payload=self.payload)["task"]["id"]

    def test_initialize_list_notifications_and_stateless_http(self):
        status,headers,msg=self.request({"jsonrpc":"2.0","id":1,"method":"initialize",
            "params":{"protocolVersion":"2025-11-25","clientInfo":{"name":"fixture","version":"1"},"capabilities":{}}})
        self.assertEqual(status,200)
        self.assertEqual(msg["result"]["protocolVersion"],"2025-11-25")
        self.assertEqual(msg["result"]["serverInfo"]["name"],"ai-studio-supervisor")
        self.assertNotIn("Mcp-Session-Id",headers)
        status,_,msg=self.request({"jsonrpc":"2.0","method":"notifications/initialized"})
        self.assertEqual((status,msg),(202,None))
        status,_,msg=self.request({"jsonrpc":"2.0","id":2,"method":"tools/list"})
        self.assertEqual(status,200)
        tools=msg["result"]["tools"]
        self.assertEqual(len(tools),6)
        self.assertEqual(sum(t["annotations"]["readOnlyHint"] for t in tools),4)
        for method in ("GET","DELETE"):
            status,headers,msg=self.request(method=method)
            self.assertEqual((status,headers.get("Allow"),msg),(405,"POST",None))
        self.assertEqual(self.company.store.list(),[])
        self.assertEqual(self.company.store.runs(),[])

    def test_http_and_stdio_share_idempotency_status_result_and_cancel(self):
        tid=self.submit()
        stdio=build(self.port,TOKEN)
        reply=stdio.call({"name":"submit_task","arguments":{"project":"demo","key":"mcp-http-one","payload":self.payload}})
        replay=json.loads(reply["content"][0]["text"])
        self.assertTrue(replay["replayed"]);self.assertEqual(replay["task"]["id"],tid)
        changed={**self.payload,"brief":"different"}
        self.assertTrue(self.call("submit_task",project="demo",key="mcp-http-one",payload=changed)["isError"])
        self.assertEqual(len(self.company.store.list()),1)
        self.assertEqual(self.data("task_status",project="demo",task=tid)["task"]["status"],"ready")
        self.assertIn("events",self.data("task_events",project="demo",task=tid))
        self.assertEqual(self.data("task_result",project="demo",task=tid)["runs"],[])
        self.assertEqual(self.data("cancel_task",project="demo",task=tid)["task"]["status"],"cancelled")

    def test_fake_qa_artifact_is_retrieved_without_approval_or_real_models(self):
        self.company.cfg.roles["reviewer"].runtime="codex"
        tid=self.submit()
        self.company.engine.request_run(tid)
        self.company.engine._run_build(self.company.store.get(tid))
        result=self.data("task_result",project="demo",task=tid)
        self.assertFalse(result["approved"]);self.assertEqual(result["task"]["status"],"awaiting_approval")
        artifact=self.data("task_artifact",project="demo",task=tid,path="docs/answer.txt")
        raw=base64.b64decode(artifact["content"])
        self.assertEqual(artifact["sha256"],hashlib.sha256(raw).hexdigest())
        self.assertIn(b"42",raw)
        self.assertTrue(self.call("task_artifact",project="demo",task=tid,path="../outside.txt")["isError"])

    def test_authentication_cannot_use_dashboard_token_or_session_id(self):
        for token in (None,"invalid",self.server.token):
            with self.subTest(token_present=token is not None):
                status,headers,_=self.request({"jsonrpc":"2.0","id":1,"method":"tools/list"},
                    token=token,headers={"X-Studio-Token":self.server.token,"Mcp-Session-Id":"not-an-auth-token"})
                self.assertEqual(status,401);self.assertIn("WWW-Authenticate",headers)
        self.assertEqual(self.company.store.list(),[])

    def test_host_origin_and_mobile_boundary(self):
        request={"jsonrpc":"2.0","id":1,"method":"tools/list"}
        self.assertEqual(self.request(request,headers={"Host":"evil.example"})[0],403)
        self.assertEqual(self.request(request,headers={"Origin":"https://evil.example"})[0],403)
        self.assertEqual(self.request(request,method="GET",headers={"Origin":"null"})[0],403)
        self.server.lan_mode=True
        self.assertEqual(self.request(request)[0],403)
        self.assertEqual(self.company.store.list(),[])

    def test_readonly_grant_scope_and_no_approval_tools(self):
        tid=self.submit()
        status,_,msg=self.request({"jsonrpc":"2.0","id":1,"method":"tools/call",
            "params":{"name":"cancel_task","arguments":{"project":"demo","task":tid}}},token=READER)
        self.assertEqual(status,200);self.assertTrue(msg["result"]["isError"])
        self.assertEqual(self.company.store.get(tid).status,"ready")
        self.assertTrue(self.call("task_status",project="other",task=tid)["isError"])
        self.assertTrue(self.call("submit_task",project="demo",key="outside",
            payload={**self.payload,"allowed_paths":["secrets/**"]})["isError"])
        for method in ("approve","run","settings"):
            status,_,msg=self.request({"jsonrpc":"2.0","id":1,"method":method})
            self.assertEqual(status,200);self.assertEqual(msg["error"]["code"],-32601)
        self.assertEqual(len(self.company.store.list()),1)

    def test_protocol_and_malformed_input_errors_do_not_reflect_secrets(self):
        for version in ("bad-version","2024-11-05"):
            self.assertEqual(self.request({"jsonrpc":"2.0","id":1,"method":"ping"},
                headers={"MCP-Protocol-Version":version})[0],400)
        for body in (b"{",b"[]",b'{"jsonrpc":"2.0","id":NaN,"method":"ping"}',
                     b'{"jsonrpc":"2.0","id":true,"method":"ping"}'):
            self.assertEqual(self.request(body)[0],400)
        canary="fixture-private-key-or-path"
        for msg in ({"jsonrpc":"2.0","id":1,"method":canary},
            {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"task_status",
                "arguments":{canary:canary}}}):
            status,_,response=self.request(msg)
            self.assertEqual(status,200);self.assertNotIn(canary,json.dumps(response))
        audit=json.dumps(self.company.store.recent_events(100))
        self.assertNotIn(TOKEN,audit);self.assertNotIn(READER,audit);self.assertNotIn(canary,audit)

    def test_content_negotiation_and_query_token_are_rejected(self):
        body={"jsonrpc":"2.0","id":1,"method":"ping"}
        self.assertEqual(self.request(body,headers={"Content-Type":"text/plain"})[0],415)
        self.assertEqual(self.request(body,headers={"Accept":"text/event-stream"})[0],406)
        self.assertEqual(self.request(body,path="/mcp?token=not-supported")[0],404)
        self.assertEqual(self.request(b" "*1_000_001)[0],413)


class McpCLI(unittest.TestCase):
    def test_stdio_entrypoint_needs_no_company_initialization_or_credentials_for_metadata(self):
        with tempfile.TemporaryDirectory(prefix="studio-mcp-empty-") as folder:
            messages=[{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25"}},
                      {"jsonrpc":"2.0","id":2,"method":"tools/list"}]
            result=subprocess.run([sys.executable,"-X","utf8","-B",str(ROOT/"studio.py"),
                "--root",folder,"mcp"],input="\n".join(map(json.dumps,messages))+"\n",
                text=True,encoding="utf-8",capture_output=True,timeout=15,
                env=clean_child_env(),creationflags=no_window_flags())
            self.assertEqual(result.returncode,0,result.stderr)
            replies=[json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(replies),2)
            self.assertEqual(len(replies[1]["result"]["tools"]),6)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_client_config_has_no_token_values_and_uses_absolute_entrypoint(self):
        for form in ("json","codex"):
            result=subprocess.run([sys.executable,"-X","utf8","-B",str(ROOT/"studio.py"),"mcp","--config",form],
                text=True,encoding="utf-8",capture_output=True,timeout=15,
                env=clean_child_env(),creationflags=no_window_flags())
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn("--credential",result.stdout)
            self.assertNotIn("STUDIO_SUPERVISOR_TOKEN",result.stdout)
            self.assertIn("--user-credential",result.stdout)
            if form=="json":
                settings=json.loads(result.stdout)["mcpServers"]["ai_studio"]
                self.assertTrue(Path(settings["command"]).is_absolute())
                self.assertTrue(Path(settings["args"][3]).is_absolute())
