"""No paid services: real HTTP/Git/disk with injected runtimes."""
import base64
import hashlib
import http.client
import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from studio import gitops
from studio.engine import Engine, EngineError
from studio.store import Store
from studio.supervisor import Supervisor, AccessError
from studio.supervisor_mcp import build as bridge
from studio.server import StudioServer
from studio.util import atomic_write_json
from tests.helpers import TempStudio, default_behavior
from tests.test_engine import build_task, wait_for

TOKEN = "test-only-supervisor-token-" + "a" * 32


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.s = TempStudio(); self.e = self.s.engine
        self.api = Supervisor(self.e)
        self.auth = "Bearer " + TOKEN
        atomic_write_json(self.s.cfg.data_dir / "supervisors.json", {"enabled":True,"clients":[{"id":"test","enabled":True,"token_sha256":hashlib.sha256(TOKEN.encode()).hexdigest(),"projects":{"demo":{"read":True,"write":True,"paths":["docs/**"]}}}]})
        self.req = {"operation":"submit","project":"demo","key":"request-one","payload":{"kind":"build","title":"answer","brief":"write 42","allowed_paths":["docs/**"],"requirements":[{"id":"A1","text":"answer is 42","evidence":[{"type":"test","name":"answer_is_42"},{"type":"file","path":"docs/answer.txt"}]}]}}

    def tearDown(self):self.s.close()

    def call(self,**kw):return self.api.call(self.auth,kw)

    def test_idempotency_concurrent_restart_conflict(self):
        outputs=[]
        workers=[threading.Thread(target=lambda:outputs.append(self.api.call(self.auth,self.req))) for _ in range(8)]
        for w in workers:w.start()
        for w in workers:w.join(10)
        self.assertEqual(len(outputs),8)
        self.assertEqual(len({o["task"]["id"] for o in outputs}),1)
        self.assertEqual(len(self.s.store.list()),1)
        other = Supervisor(Engine(self.s.cfg,Store(self.s.cfg.data_dir),runtime_factory=self.s._runtime))
        self.assertTrue(other.call(self.auth,self.req)["replayed"])
        altered=json.loads(json.dumps(self.req));altered["payload"]["brief"]="different"
        with self.assertRaises(AccessError) as caught:other.call(self.auth,altered)
        self.assertEqual(caught.exception.status,409)

    def test_crash_after_atomic_task_before_response(self):
        original=self.s.store.event
        def crash(kind,*args,**kw):
            if kind=="task.created":raise RuntimeError("simulated power loss")
            return original(kind,*args,**kw)
        with mock.patch.object(self.s.store,"event",side_effect=crash):
            with self.assertRaises(RuntimeError):self.api.call(self.auth,self.req)
        self.assertTrue(self.api.call(self.auth,self.req)["replayed"])
        self.assertEqual(len(self.s.store.list()),1)

    def test_invalid_operation_is_rejected_without_server_error(self):
        for op in [[],{},None,123]:
            with self.assertRaises(AccessError):self.call(operation=op,project="demo")

    def test_scope_and_approval_cannot_be_bypassed(self):
        for op in ["approve","merge","settings","run","source"]:
            with self.assertRaises(AccessError):self.call(operation=op,project="demo")
        with self.assertRaises(AccessError):self.call(operation="status",project="other",task="T0001")
        altered=json.loads(json.dumps(self.req));altered["payload"]["role"]="reviewer"
        with self.assertRaises(AccessError):self.api.call(self.auth,altered)
        altered=json.loads(json.dumps(self.req));altered["payload"]["allowed_paths"]=["../secrets/**"]
        with self.assertRaises(AccessError):self.api.call(self.auth,altered)
        with self.assertRaises(AccessError):self.api.call("Bearer wrong",self.req)
        cfg=json.loads((self.s.cfg.data_dir/"supervisors.json").read_text());cfg["clients"][0]["projects"]["demo"]["write"]=False
        atomic_write_json(self.s.cfg.data_dir/"supervisors.json",cfg)
        with self.assertRaises(AccessError):self.api.call(self.auth,self.req)

    def test_claude_free_pipeline_result_and_missing_evidence(self):
        calls=[]
        def behavior(spec,name):
            calls.append((name,spec.sandbox,spec.role))
            if name=="claude":raise AssertionError("Claude must never start")
            return default_behavior(spec,name)
        self.s.behavior=behavior
        tid=self.api.call(self.auth,self.req)["task"]["id"]
        task=self.s.store.get(tid)
        self.assertFalse(task.run_requested)
        self.e.request_run(tid);self.e._run_build(self.s.store.get(tid))
        out=self.call(operation="result",project="demo",task=tid)
        self.assertEqual(out["task"]["status"],"awaiting_approval",out)
        self.assertTrue(out["evidence"]["complete"])
        self.assertFalse(out["approved"])
        self.assertIn(("codex","read-only","reviewer"),calls)
        blob=self.call(operation="artifact",project="demo",task=tid,path="docs/answer.txt")
        self.assertEqual(base64.b64decode(blob["content"]).strip(),b"42")
        task=self.s.store.get(tid)
        (self.s.store.qa_dir/task.qa["qa_id"]/"snapshot/docs/answer.txt").unlink()
        with self.assertRaises(EngineError):self.e.approve(tid)
        self.assertFalse(self.call(operation="result",project="demo",task=tid)["evidence"]["complete"])
        self.assertFalse(self.call(operation="status",project="demo",task=tid)["validated"])
        events=self.call(operation="events",project="demo",task=tid,after=0)
        self.assertTrue(events["events"])
        self.assertEqual(self.call(operation="events",project="demo",task=tid,after=events["next"])["events"],[])

    def test_plan_scope_approval_and_children(self):
        self.req["payload"]["kind"]="plan"
        tid=self.api.call(self.auth,self.req)["task"]["id"]
        self.assertIsNone(self.e._next_job(),"external planning waits for CEO execution permission")
        self.e.request_run(tid);self.e._run_plan(self.s.store.get(tid))
        self.assertEqual(self.s.store.get(tid).status,"awaiting_approval")
        self.e.approve(tid,{"selected":[0]})
        child=self.s.store.get(self.s.store.get(tid).children[0])
        self.assertEqual(child.created_by,"supervisor:test")
        self.assertEqual(child.allowed_paths,["docs/**"])
        self.assertEqual(child.extra["requirements"],self.req["payload"]["requirements"])

    def test_source_receipt_and_tampered_snapshot(self):
        self.req["payload"]["requirements"][0]["evidence"].append({"type":"source","id":"S1"})
        tid=self.api.call(self.auth,self.req)["task"]["id"]
        self.e._run_build(self.s.store.get(tid))
        self.assertEqual(self.s.store.get(tid).status,"blocked")
        with mock.patch("studio.mcp_builtin.web.fetch",return_value="verified public source text"):
            self.e.capture_source(tid,"S1","https://example.com/source")
        with mock.patch.object(self.e,"_agent_run_once",side_effect=AssertionError("must reuse completed review")):
            self.e.retry(tid);self.e._run_build(self.s.store.get(tid))
        task=self.s.store.get(tid)
        self.assertEqual(task.status,"awaiting_approval",task.blocked_reason)
        from studio.mcp_builtin.base import ToolError
        with mock.patch("studio.mcp_builtin.web.fetch",side_effect=ToolError("HTTP 404")):
            with self.assertRaises(EngineError):self.e.capture_source(tid,"S1","https://example.com/source")
        self.assertFalse(self.call(operation="result",project="demo",task=tid)["evidence"]["complete"])
        with self.assertRaises(EngineError):self.e.approve(tid)
        (self.s.store.qa_dir/task.qa["qa_id"]/"snapshot/docs/answer.txt").write_text("tampered")
        with self.assertRaises(EngineError):self.e.approve(tid)
        with self.assertRaises(AccessError):self.call(operation="artifact",project="demo",task=tid,path="docs/answer.txt")

    def test_missing_criterion_blocks_and_cancel_ownership(self):
        self.req["payload"]["requirements"][0]["evidence"].append({"type":"file","path":"docs/missing.txt"})
        tid=self.api.call(self.auth,self.req)["task"]["id"]
        self.e._run_build(self.s.store.get(tid))
        self.assertEqual(self.s.store.get(tid).status,"blocked")
        other=build_task(self.e)
        with self.assertRaises(AccessError):self.call(operation="cancel",project="demo",task=other.id)
        self.assertEqual(self.call(operation="cancel",project="demo",task=tid)["task"]["status"],"cancelled")

    def test_http_and_stdio_bridge(self):
        srv=StudioServer(self.s.cfg,self.s.store,self.e,0)
        port=srv.server_address[1];srv.allowed_hosts={f"127.0.0.1:{port}"};srv.allowed_origins={f"http://127.0.0.1:{port}"}
        t=threading.Thread(target=srv.serve_forever,daemon=True);t.start()
        try:
            mcp=bridge(port,TOKEN)
            self.assertEqual(len(mcp.handle({"jsonrpc":"2.0","id":1,"method":"tools/list"})["result"]["tools"]),6)
            reply=mcp.call({"name":"submit_task","arguments":{k:self.req[k] for k in ("project","key","payload")}})
            self.assertFalse(reply["isError"],reply)
            tid=json.loads(reply["content"][0]["text"])["task"]["id"]
            for path,origin,token,status in [("/api/tasks/"+tid+"/approve",None,self.auth,403),("/supervisor/v1","https://evil.example",self.auth,403),("/supervisor/v1",None,"Bearer bad",401)]:
                c=http.client.HTTPConnection("127.0.0.1",port,timeout=10)
                headers={"Authorization":token,"Content-Type":"application/json"}
                if origin:headers["Origin"]=origin
                c.request("POST",path,json.dumps(self.req),headers);res=c.getresponse();res.read();self.assertEqual(res.status,status);c.close()
        finally:srv.shutdown();srv.server_close();t.join(5)


class RecoveryTests(unittest.TestCase):
    def setUp(self):self.s=TempStudio();self.e=self.s.engine
    def tearDown(self):self.s.close()

    def test_write_disconnect_never_replayed_or_discarded(self):
        task=build_task(self.e);calls=[]
        def behavior(spec,rt):
            calls.append(spec.role)
            (spec.cwd/"docs/answer.txt").write_text("42")
            raise RuntimeError("disconnected after write")
        self.s.behavior=behavior
        with self.assertRaises(RuntimeError):self.e._run_build(self.s.store.get(task.id))
        self.e.recover()
        task=self.s.store.get(task.id)
        self.assertEqual(task.status,"blocked")
        self.assertTrue((Path(task.worktree)/"docs/answer.txt").exists())
        with self.assertRaises(EngineError):self.e.retry(task.id)
        self.assertEqual(calls,["builder"])

    def test_restart_after_qa_reuses_build_and_verification(self):
        task=build_task(self.e);calls=[]
        def behavior(spec,rt):
            calls.append(spec.role);return default_behavior(spec,rt)
        self.s.behavior=behavior
        with mock.patch.object(self.e,"_review",side_effect=RuntimeError("crash before review")):
            with self.assertRaises(RuntimeError):self.e._run_build(self.s.store.get(task.id))
        qid=self.s.store.get(task.id).qa["qa_id"]
        self.e.recover();self.e.retry(task.id)
        self.e._run_build(self.s.store.get(task.id))
        fresh=self.s.store.get(task.id)
        self.assertEqual(fresh.status,"awaiting_approval",fresh.blocked_reason)
        self.assertEqual(fresh.qa["qa_id"],qid)
        self.assertEqual(calls.count("builder"),1)
        self.assertEqual(calls.count("reviewer"),1)

    def test_restart_after_completed_write_receipt_reuses_model(self):
        task=build_task(self.e);calls=[]
        def behavior(spec,rt):calls.append(spec.role);return default_behavior(spec,rt)
        self.s.behavior=behavior
        with mock.patch.object(gitops,"staged_changes",side_effect=RuntimeError("crash after model")):
            with self.assertRaises(RuntimeError):self.e._run_build(self.s.store.get(task.id))
        self.e.recover();self.e.retry(task.id);self.e._run_build(self.s.store.get(task.id))
        self.assertEqual(calls.count("builder"),1)
        self.assertEqual(self.s.store.get(task.id).status,"awaiting_approval")

    def test_resumed_review_changes_continue_to_next_build(self):
        task=build_task(self.e);calls=[];reviews=[]
        def behavior(spec,rt):
            calls.append(spec.role)
            if spec.role=="reviewer":
                reviews.append(spec.run_id)
                if len(reviews)==1:
                    return {"structured":{"verdict":"changes_requested","summary":"Add a note","findings":[]}}
            if spec.role=="builder" and calls.count("builder")==2:
                return {"files":{"docs/answer.txt":"42\n","docs/note.txt":"review addressed"},"final_message":"updated"}
            return default_behavior(spec,rt)
        self.s.behavior=behavior
        with mock.patch.object(self.e,"_review",side_effect=RuntimeError("crash before review")):
            with self.assertRaises(RuntimeError):self.e._run_build(self.s.store.get(task.id))
        self.e.recover();self.e.retry(task.id);self.e._run_build(self.s.store.get(task.id))
        fresh=self.s.store.get(task.id)
        self.assertEqual(fresh.status,"awaiting_approval",fresh.blocked_reason)
        self.assertEqual(calls.count("builder"),2)
        self.assertEqual(len(reviews),2)

    def test_plan_receipt_reused_after_restart(self):
        plan=self.e.submit_directive("plan","demo");calls=[]
        def behavior(spec,rt):calls.append(spec.role);return default_behavior(spec,rt)
        self.s.behavior=behavior
        with mock.patch("studio.engine.validate_plan",side_effect=RuntimeError("crash after planning")):
            with self.assertRaises(RuntimeError):self.e._run_plan(self.s.store.get(plan.id))
        self.e.recover();self.e.retry(plan.id);self.e._run_plan(self.s.store.get(plan.id))
        self.assertEqual(calls,["producer"])
        self.assertEqual(self.s.store.get(plan.id).status,"awaiting_approval")

    def test_uncertain_operation_keeps_conflicting_jobs_waiting(self):
        task=build_task(self.e);self.e.request_run(task.id)
        self.s.store.transition(task,"running")
        self.e.journal.write(task.id,"build1",status="running",effect="reversible",run_id="R-interrupted",input_digest="x")
        self.e.recover()
        other=build_task(self.e);self.e.request_run(other.id)
        self.assertIsNone(self.e._next_job())
        self.assertIn(task.id,self.e.waiting_reason(other,self.s.store.list()))

    def test_changed_suite_invalidates_cached_qa(self):
        task=build_task(self.e)
        with mock.patch.object(self.e,"_review",side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):self.e._run_build(self.s.store.get(task.id))
        qid=self.s.store.get(task.id).qa["qa_id"]
        p=self.s.root/"trusted/acceptance/demo/check.py";p.write_text(p.read_text(encoding="utf-8")+"\n# changed suite\n",encoding="utf-8")
        self.e.recover();self.e.retry(task.id);self.e._run_build(self.s.store.get(task.id))
        self.assertNotEqual(self.s.store.get(task.id).qa["qa_id"],qid)


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.s=TempStudio();self.e=self.s.engine;self.e.set_self_learning(False)
        from studio import mcp
        mcp.set_equipped(self.s.cfg,"team-memory","builder",False)
    def tearDown(self):self.s.close()

    def test_independent_parallel_conflicts_wait_cancel_releases(self):
        a=build_task(self.e,allowed_paths=["docs/a/**"])
        b=build_task(self.e,allowed_paths=["docs/b/**"])
        c=build_task(self.e,allowed_paths=["docs/a/**"])
        entered=[];guard=threading.Lock()
        def behavior(spec,rt):
            if spec.role=="builder":
                with guard:entered.append(spec.run_id)
                return {"delay":3,"error_kind":"timeout"}
            return default_behavior(spec,rt)
        self.s.behavior=behavior
        for task in (a,b,c):self.e.request_run(task.id)
        self.e.start()
        self.assertTrue(wait_for(lambda:len(entered)==2,15),entered)
        self.assertTrue(any(a.id in r for r in entered[:2]));self.assertTrue(any(b.id in r for r in entered[:2]))
        self.e.cancel(a.id)
        self.assertTrue(wait_for(lambda:len(entered)>=3,20),entered)
        self.assertIn(c.id,entered[2])
        self.assertTrue(wait_for(lambda:not self.e._workers,20))
        self.assertEqual(self.e._reservations,{})
        self.assertEqual(self.e._currents,{})

    def test_budget_reservation_and_runtime_error_release(self):
        self.s.cfg.limits["max_runs_per_day"]=1
        task=build_task(self.e)
        self.e._run_build(self.s.store.get(task.id))
        self.assertEqual(len(self.s.store.runs()),1)
        self.assertEqual(self.e._reservations,{})

    def test_completed_worker_releases_mcp_but_candidate_keeps_file_scope(self):
        from studio import mcp
        mcp.set_equipped(self.s.cfg,"team-memory","builder",True)
        a=build_task(self.e,allowed_paths=["docs/a/**"])
        self.s.store.transition(a,"running");self.s.store.transition(a,"checking");self.s.store.transition(a,"awaiting_approval")
        b=build_task(self.e,allowed_paths=["docs/b/**"]);self.e.request_run(b.id)
        self.assertEqual(self.e._next_job().id,b.id)
        self.e.cancel(b.id)
        c=build_task(self.e,allowed_paths=["docs/a/**"]);self.e.request_run(c.id)
        self.assertIsNone(self.e._next_job())

    def test_builtin_shared_memory_is_a_conflict(self):
        from studio import mcp
        mcp.set_equipped(self.s.cfg,"team-memory","builder",True)
        a=build_task(self.e,allowed_paths=["docs/a/**"])
        b=build_task(self.e,allowed_paths=["docs/b/**"])
        self.s.store.transition(a,"running");self.e.request_run(b.id)
        self.assertIsNone(self.e._next_job())

    def test_filename_glob_conflict_is_conservative(self):
        from studio.scheduler import overlaps
        self.assertTrue(overlaps("docs/a*.py","docs/answer.py"))
        self.assertTrue(overlaps("docs/**","docs/answer.py"))
        self.assertFalse(overlaps("docs/a/**","docs/b/**"))

    def test_same_external_resource_conflicts_across_projects(self):
        from studio.scheduler import conflict
        a=build_task(self.e);b=build_task(self.e);b.project="other"
        a.extra["resources"]=["shared-db"];b.extra["resources"]=["shared-db"]
        self.assertTrue(conflict(a,b))
        b.extra["resources"]=[];self.assertFalse(conflict(a,b))


class ModelIdentityTests(unittest.TestCase):
    def test_grok_negative_login_is_not_reported_as_authenticated(self):
        from studio.runtimes import grok_login
        for message,wanted in [("You are logged in with grok.com.",True),("You are not logged in.",False),("You are not authenticated.",False)]:
            with mock.patch("studio.runtimes.subprocess.run",return_value=mock.Mock(returncode=0,stdout=message,stderr="")):
                self.assertEqual(grok_login({"found":True,"cmd":["fixture"]}),wanted)


    def test_mcp_rejects_large_or_malformed_result_without_truncated_json(self):
        for body in [[],{"schema":"studio.supervisor-result/v1","status":"ok","data":{"text":"x"*61000}}]:
            response=mock.Mock(status=200)
            response.read.return_value=json.dumps(body).encode()
            connection=mock.Mock();connection.getresponse.return_value=response
            with mock.patch("studio.supervisor_mcp.http.client.HTTPConnection",return_value=connection):
                out=bridge(8765,TOKEN).call({"name":"task_status","arguments":{"project":"demo","task":"T0001"}})
            self.assertTrue(out["isError"],out)
            self.assertLess(len(out["content"][0]["text"]),1000)


    def test_grok_text_is_fail_closed_and_never_infers_requested_model(self):
        from studio.runtimes import GrokTextRuntime, RunSpec
        with mock.patch("studio.runtimes.find_grok",return_value={"found":True,"version":"test"}):
            rt=GrokTextRuntime({})
        spec=RunSpec("R-test","reviewer","review",Path.cwd(),Path.cwd(),model="requested-only")
        with mock.patch("studio.runtimes.run_process") as call:
            out=rt.run(spec,lambda:False)
        self.assertEqual(out.error_kind,"policy");self.assertIsNone(out.provider_model);call.assert_not_called()
        rt.info={"found":False}
        self.assertEqual(rt.run(spec,lambda:False).error_kind,"not_found")
