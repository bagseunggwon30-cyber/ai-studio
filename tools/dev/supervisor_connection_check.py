"""Approved production scope check using the registered MCP; no model turns.

Only submits/cancels the connection's own job. Does not run workers, create QA
artifacts, change product files, approve work, or impersonate the dot's cloud.
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


def run(port):
    path,credential=default_paths()
    configured=tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]["ai_studio"]
    if configured != connection_config(ROOT,credential,port):
        raise ValueError("등록된 MCP 설정이 승인한 연결과 다릅니다.")
    connection=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
    connection.request("GET","/supervisor/health")
    response=connection.getresponse();health=json.loads(response.read());connection.close()
    if response.status != 200 or health.get("mode") != "connection-only" or health.get("company_id") != hashlib.sha256(str(ROOT).encode()).hexdigest():
        raise ValueError("모델 없는 실제 회사 연결 서버를 확인하지 못했습니다.")
    client=CodexMcpClient(port,None,ROOT,ROOT,mcp_config=configured)
    owned=None
    try:
        payload={"kind":"build","title":"소윤이 연결 확인 · 실행하지 않음",
            "brief":"감독 도구 접수·조회·취소 확인용입니다. 작업과 모델을 실행하지 않습니다.",
            "allowed_paths":["reports/connection-check/**"],
            "requirements":[{"id":"CONNECTION","text":"연결 확인; 파일 생성과 모델 실행 미승인",
                "evidence":[{"type":"file","path":"reports/connection-check/connection.json"}]}]}
        key="soyun-connection-2026-10-03-v1"
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
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    if not args.owner_approved:parser.error("실제 회사에 제출·취소하는 연결 검사에는 CEO 승인이 필요합니다.")
    result=run(args.port)
    if args.report:atomic_write_json(args.report,result)
    print(json.dumps(result,ensure_ascii=False))


if __name__ == "__main__":main()
