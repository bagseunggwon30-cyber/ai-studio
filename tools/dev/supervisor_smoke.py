"""Disposable end-to-end supervisor verification. Defaults to fake model calls.

--real requires prior user approval. --grok-review-only --allow-model-calls 1
uses one real Grok review and fake planning/building; no Codex model turn.
No production company, model credentials, or shared tool settings are changed.
"""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import threading
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio, default_behavior
from studio import mcp
from studio.engine import Engine, EngineError
from studio.runtimes import make_runtime, RunResult, GrokTextRuntime
from studio.server import StudioServer
from studio.store import Store
from studio.util import atomic_write_json, atomic_write_text, clean_child_env, no_window_flags


class StdioClient:
    def __init__(self, port, token):
        self.port, self.token = port, token
        self.operations = []

    def call(self, name, **arguments):
        env = clean_child_env()
        env["STUDIO_SUPERVISOR_TOKEN"] = self.token
        requests = [
            {"jsonrpc":"2.0", "id":1, "method":"initialize", "params":{
                "protocolVersion":"2024-11-05", "capabilities":{},
                "clientInfo":{"name":"ai-studio-verification", "version":"1"}}},
            {"jsonrpc":"2.0", "method":"notifications/initialized"},
            {"jsonrpc":"2.0", "id":2, "method":"tools/list"},
            {"jsonrpc":"2.0", "id":3, "method":"tools/call", "params":{
                "name":name, "arguments":arguments}},
        ]
        process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/supervisor-mcp.py"),
                                  "--port", str(self.port)], cwd=ROOT.parent, env=env,
                                 input="\n".join(json.dumps(r) for r in requests)+"\n",
                                 capture_output=True, text=True, encoding="utf-8", timeout=25,
                                 creationflags=no_window_flags())
        if process.returncode:
            raise RuntimeError("stdio bridge failed; inspect private local output")
        responses = {r["id"]:r for r in (json.loads(line) for line in process.stdout.splitlines())}
        tools = responses[2]["result"]["tools"]
        assert len(tools) == 9
        result = responses[3]["result"]
        if result.get("isError"):
            raise RuntimeError("MCP operation failed: " + name)
        self.operations.append(name)
        return json.loads(result["content"][0]["text"])


def run(real=False, allow_model_calls=0, client_kind="stdio", grok_review_only=False):
    client = None
    required_calls = 1 if grok_review_only else 3
    if real and allow_model_calls != required_calls:
        raise ValueError("Real verification needs explicit approval for its exact call count.")
    if real:
        readiness = GrokTextRuntime({}).preflight()
        if not readiness.get("ready"):
            return {"status":"blocked", "reason":readiness.get("reason"), "model_calls":0}
    company = TempStudio()
    server = thread = None
    model_calls = []
    if not real:
        def smoke_behavior(spec, runtime=None):
            result = default_behavior(spec, runtime)
            if spec.role == "producer":
                result["structured"]["tasks"] = [result["structured"]["tasks"][0]]
                result["structured"]["tasks"][0]["acceptance"] = ["정답은 42"]
            return result
        company.behavior = smoke_behavior
    engine = company.engine
    engine.set_self_learning(False)
    for role in company.cfg.roles:
        for tool in mcp.for_role(company.cfg, role):
            mcp.set_equipped(company.cfg, tool["name"], role, False)
    company.cfg.roles["reviewer"].runtime = "grok_text" if real else "codex"
    company.cfg.roles["reviewer"].model = "grok-4.7" if real else ""
    company.cfg.roles["reviewer"].fallback_runtime = ""
    company.cfg.limits["max_attempts"] = 1
    company.cfg.limits["task_timeout_min"] = 2
    if real:
        def factory(name):
            if grok_review_only and name != "grok_text":return company._runtime(name)
            runtime = make_runtime(name, company.cfg.runtimes)
            original = runtime.run
            def counted(spec, stop):
                if len(model_calls) >= allow_model_calls:
                    return RunResult(False,name,spec.model,None,0,error_kind="cap",side_effects="none")
                model_calls.append({"requested_executor":name, "role":spec.role})
                return original(spec, stop)
            runtime.run = counted
            return runtime
        engine.runtime_factory = factory
    else:
        factory = company._runtime
    token = secrets.token_urlsafe(32)
    atomic_write_json(company.cfg.data_dir / "supervisors.json", {"enabled":True, "clients":[{
        "id":"verification", "enabled":True, "token_sha256":hashlib.sha256(token.encode()).hexdigest(),
        "projects":{"demo":{"read":True, "write":True, "paths":["docs/**"]}}}]})
    try:
        company.store.acquire_process_lock()
        server = StudioServer(company.cfg, company.store, engine, 0)
        port = server.server_address[1]
        server.allowed_hosts = {f"127.0.0.1:{port}"}
        server.allowed_origins = {f"http://127.0.0.1:{port}"}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        if client_kind == "codex":
            from codex_supervisor_client import CodexMcpClient
            client = CodexMcpClient(port,token,company.repo,ROOT)
        else:
            client = StdioClient(port, token)
        payload = {"kind":"plan", "title":"작은 정답 파일", "brief":
            "딱 한 개 개발 작업으로 기획하세요. docs/answer.txt에 숫자 42와 줄바꿈만 저장합니다. "
            "허용 경로 docs/**. 수용 기준: answer_is_42 검사 통과와 정답 파일 존재. "
            "셸로 외부 서비스나 다른 모델을 호출하지 말고 이 작은 작업만 수행합니다.",
            "allowed_paths":["docs/**"], "requirements":[{"id":"A1", "text":"정답은 42", "evidence":[
                {"type":"test", "name":"answer_is_42"}, {"type":"file", "path":"docs/answer.txt"}]}]}
        submission = client.call("submit_task", project="demo", key="manual-smoke-plan", payload=payload)
        tid = submission["task"]["id"]
        assert client.call("submit_task", project="demo", key="manual-smoke-plan", payload=payload)["task"]["id"] == tid
        engine.request_run(tid)
        engine._work(company.store.get(tid))
        plan = company.store.get(tid)
        if plan.status != "awaiting_approval":
            return {"status":"blocked", "phase":"planning", "model_calls":len(model_calls),
                    "reason":plan.blocked_reason}
        engine.approve(tid, {"selected":[0]})  # CEO fixture; temporary project only.
        child = company.store.get(company.store.get(tid).children[0])
        assert child.acceptance == [r["text"] for r in child.extra["requirements"]]
        engine.request_run(child.id)
        with mock.patch.object(engine,"_review",side_effect=RuntimeError("verification interruption before review")):
            engine._work(company.store.get(child.id))
        before = company.store.get(child.id)
        if before.status not in ("checking","blocked") or not before.qa:
            return {"status":"blocked", "phase":"implementation", "model_calls":len(model_calls),
                    "reason":before.blocked_reason}
        qid = before.qa["qa_id"]
        candidate = before.candidate_sha
        assert before.qa["candidate_sha"] == candidate
        # Recreate store/engine, then validate and reuse completed writer and QA receipts.
        recovered_store = Store(company.cfg.data_dir)
        recovered = Engine(company.cfg,recovered_store,runtime_factory=factory)
        recovered.recover(); recovered.retry(child.id)
        recovered._work(recovered_store.get(child.id))
        server.store, server.engine = recovered_store, recovered
        result = client.call("task_result", project="demo", task=child.id)
        status = client.call("task_status", project="demo", task=child.id)
        events = client.call("task_events", project="demo", task=child.id, after=0)
        if status["task"]["status"] != "awaiting_approval":
            return {"status":"blocked", "phase":"review", "reason":status["blocked_reason"],
                    "model_calls":len(model_calls), "executions":result["runs"]}
        artifact = client.call("task_artifact", project="demo", task=child.id, path="docs/answer.txt")
        assert base64.b64decode(artifact["content"]).strip() == b"42"
        assert result["evidence"]["complete"] and status["validated"] and not status["approved"]
        resumed = recovered_store.get(child.id)
        assert resumed.qa["qa_id"] == qid
        assert resumed.candidate_sha == resumed.qa["candidate_sha"] == resumed.review["candidate_sha"] == candidate
        assert resumed.acceptance == [r["text"] for r in resumed.extra["requirements"]]
        snapshot = recovered_store.qa_dir / qid / "snapshot/docs/answer.txt"
        atomic_write_text(snapshot,"tampered\n")
        tampered = client.call("task_result", project="demo", task=child.id)
        assert not tampered["evidence"]["complete"]
        try: recovered.approve(child.id)
        except EngineError: pass
        else: raise AssertionError("tampered evidence allowed approval")
        canceled = client.call("cancel_task", project="demo", task=child.id)
        assert canceled["task"]["status"] == "cancelled"
        assert not recovered._reservations and not recovered._workers
        assert not Path(before.worktree).exists()
        report = {"status":"pass", "company":"temporary", "models":"real Grok review; fake planning/build" if real and grok_review_only else "real" if real else "fake",
                  "model_calls":len(model_calls), "stdio_tools":sorted(set(client.operations)),
                  "request_replay_same_task":True, "qa_receipt_reused_after_restart":True, "criterion_contract_preserved":True, "candidate_review_binding_preserved":True,
                  "artifact_sha256":artifact["sha256"], "candidate_sha":result["evidence"]["candidate_sha"],
                  "evidence_verified":True, "tamper_blocks_approval":True,
                  "cancel_cleans_worktree_and_reservations":True, "event_count":len(events["events"]),
                  "production_company_connected":False, "external_client":client_kind,
                  "client_model_turns":0, "client_version":getattr(client,"version",None),
                  "executions":result["runs"], "planning_executions":company.store.runs(tid)}
        # Keep only provider/runtime facts, never full local metadata or directory names.
        keys = ("stage","requested_provider","requested_model","actual_runtime","runtime_version",
                "provider_model","model_identity","usage","duration_s","fallback","error_kind")
        for key in ("executions","planning_executions"):
            report[key] = [{k:row.get(k) for k in keys} for row in report[key]]
        return report
    finally:
        if client and hasattr(client,"close"):client.close()
        if server:
            server.shutdown(); server.server_close()
        if thread: thread.join(5)
        company.store.release_process_lock()
        company.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--allow-model-calls",type=int,default=0)
    parser.add_argument("--grok-review-only",action="store_true")
    parser.add_argument("--client",choices=("stdio","codex"),default="stdio")
    parser.add_argument("--report",type=Path)
    args = parser.parse_args()
    result = run(args.real,args.allow_model_calls,args.client,args.grok_review_only)
    if args.report: atomic_write_json(args.report,result)
    print(json.dumps({"status":result["status"], "models":result.get("models"),
                      "model_calls":result.get("model_calls"), "phase":result.get("phase")},ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
