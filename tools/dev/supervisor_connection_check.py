"""Approved production scope check using the registered MCP; no model turns.

Default mode only submits/cancels the connection's own job. --read-only reuses
that cancelled card and cannot submit/cancel. Neither mode runs workers or
models, changes product files, approves work, or impersonates the dot's cloud.
"""
from pathlib import Path
import argparse
import hashlib
import http.client
import json
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from codex_supervisor_client import CodexMcpClient
from studio.supervisor_setup import default_paths, connection_config, TOOLS
from studio.util import atomic_write_json
from studio.checkpoints import digest
from studio.supervisor import TASK

PROBE_KEY = "soyun-connection-2026-10-03-v1"


def existing_probe():
    """Reuse only this connection's cancelled check; never create a replacement."""
    key_hash = digest(["soyun", "studio-docs", PROBE_KEY])
    matches = []
    for path in (ROOT / "data/tasks").glob("T*.json"):
        if path.is_symlink():
            continue
        task = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(task, dict) and task.get("project") == "studio-docs"
                and task.get("created_by") == "supervisor:soyun"
                and task.get("extra", {}).get("submission", {}).get("key_hash") == key_hash):
            matches.append(task)
    if (len(matches) != 1 or matches[0].get("status") != "cancelled"
            or not TASK.fullmatch(str(matches[0].get("id", "")))):
        raise ValueError("기존에 취소한 연결 확인 카드를 확인하지 못했습니다. 새로 제출하지 않습니다.")
    return matches[0]["id"]


def readonly_result(client, task):
    status = client.call("task_status", project="studio-docs", task=task)
    events = client.call("task_events", project="studio-docs", task=task, after=0)
    result = client.call("task_result", project="studio-docs", task=task)
    if (status.get("task", {}).get("status") != "cancelled"
            or result.get("task", {}).get("status") != "cancelled"
            or result.get("runs") != [] or result.get("implemented") is not False
            or result.get("approved") is not False):
        raise ValueError("기존 확인 카드가 실행되지 않은 취소 상태인지 확인하지 못했습니다.")
    return {"status":"pass", "mode":"authenticated-read-only",
        "company":"production", "project":"studio-docs",
        "client":"local Codex MCP app-server", "client_version":client.version,
        "registered_config_used":True, "tool_count":client.tool_count,
        "authenticated_reads":["task_status", "task_events", "task_result"],
        "existing_probe_reused":True, "task_status":"cancelled",
        "event_count":len(events["events"]), "new_tasks_submitted":0,
        "cancellation_calls":0, "model_generation_calls":0, "client_model_turns":0,
        "token_values_published":False, "task_ids_published":False,
        "dot_native_mcp_registration_verified":False}


def run(port, read_only=False):
    path,credential=default_paths()
    configured=tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_studio"]
    if configured != connection_config(ROOT,credential,port):
        raise ValueError("등록된 MCP 설정이 승인한 연결과 다릅니다.")
    connection=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
    connection.request("GET","/supervisor/health")
    response=connection.getresponse();health=json.loads(response.read());connection.close()
    if (response.status != 200 or health.get("mode") != "connection-only"
            or health.get("workers") != 0 or health.get("model_generation_calls") != 0
            or health.get("company_id") != hashlib.sha256(str(ROOT).encode()).hexdigest()):
        raise ValueError("모델 없는 실제 회사 연결 서버를 확인하지 못했습니다.")
    probe = existing_probe() if read_only else None
    client=CodexMcpClient(port,None,ROOT,ROOT,mcp_config=configured)
    owned=None
    try:
        if read_only:
            return readonly_result(client, probe)
        payload={"kind":"build","title":"소윤이 연결 확인 · 실행하지 않음",
            "brief":"감독 도구 접수·조회·취소 확인용입니다. 작업과 모델을 실행하지 않습니다.",
            "allowed_paths":["reports/connection-check/**"],
            "requirements":[{"id":"CONNECTION","text":"연결 확인; 파일 생성과 모델 실행 미승인",
                "evidence":[{"type":"file","path":"reports/connection-check/connection.json"}]}]}
        key=PROBE_KEY
        submission=client.call("submit_task",project="studio-docs",key=key,payload=payload)
        owned=submission["task"]["id"]
        replay=client.call("submit_task",project="studio-docs",key=key,payload=payload)
        assert replay["task"]["id"] == owned and replay["replayed"]
        status=client.call("task_status",project="studio-docs",task=owned)
        assert status["task"]["status"] in ("ready","cancelled")
        events=client.call("task_events",project="studio-docs",task=owned,after=0)
        result=client.call("task_result",project="studio-docs",task=owned)
        assert result["runs"] == [] and not result["implemented"] and not result["approved"]
        def attempt(name,arguments):
            return client.request("mcpServer/tool/call",{"threadId":client.thread_id,"server":"ai_studio",
                "tool":name,"arguments":arguments})
        artifact=attempt("task_artifact",{"project":"studio-docs","task":owned,
            "path":"reports/connection-check/connection.json"})
        assert artifact.get("isError"),"No candidate artifact should exist without executing the job"
        outside=attempt("submit_task",{"project":"studio-docs","key":key+"-outside",
            "payload":{**payload,"allowed_paths":["reports/outside/**"]}})
        assert outside.get("isError")
        other=attempt("task_status",{"project":"core-courier","task":owned})
        assert other.get("isError")
        conflict=attempt("submit_task",{"project":"studio-docs","key":key,
            "payload":{**payload,"title":"conflicting request"}})
        assert conflict.get("isError")
        cancelled=client.call("cancel_task",project="studio-docs",task=owned)
        assert cancelled["task"]["status"] == "cancelled"
        return {"status":"pass","company":"production","client":"local Codex MCP app-server",
            "client_id":"soyun","client_version":client.version,
            "registered_config_used":True,"credential":"DPAPI CurrentUser; owner-only ACL",
            "tools_registered":TOOLS,"tool_count":client.tool_count,
            "request_replay_same_task":True,"different_content_conflict":True,
            "outside_path_denied":True,"other_project_denied":True,
            "status_events_results_read":True,"own_task_cancelled":True,
            "artifact":"correctly unavailable: job not executed; no candidate",
            "artifact_retrieval_verified":False,"event_count":len(events["events"]),
            "model_generation_calls":0,"client_model_turns":0,"existing_jobs_executed":False,
            "token_values_published":False,"dot_cloud_tool_call_verified":False}
    finally:
        if owned:
            client.call("cancel_task",project="studio-docs",task=owned)
        client.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--owner-approved",action="store_true")
    parser.add_argument("--read-only",action="store_true",
        help="기존에 취소한 연결 확인 카드의 인증된 조회만 수행; 제출·취소·모델 실행 없음")
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    if not args.owner_approved and not args.read_only:
        parser.error("실제 회사에 제출·취소하는 연결 검사에는 CEO 승인이 필요합니다.")
    try:
        result=run(args.port, read_only=args.read_only)
    except (ValueError, OSError, TimeoutError, KeyError, TypeError, AttributeError) as exc:
        # Never print the exception, raw provider reply, credential or local path.
        print(json.dumps({"status":"blocked", "error_kind":type(exc).__name__,
            "reason":"연결 전용 서버·승인된 MCP 설정·기존 확인 카드를 점검하세요. 자동 제출·모델 실행은 하지 않습니다."},ensure_ascii=False))
        return 1
    if args.report:atomic_write_json(args.report,result)
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__ == "__main__":raise SystemExit(main())
