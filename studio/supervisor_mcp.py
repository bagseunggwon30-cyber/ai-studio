"""Opt-in stdio bridge to the local supervisor API. Never issues credentials.
Run: python -m studio.supervisor_mcp --port 8765
Set STUDIO_SUPERVISOR_TOKEN in the client environment after owner provisioning.
"""
from __future__ import annotations
import argparse
import http.client
import json
import os
from .mcp_builtin.base import Server, ToolError, setup_stdio, MAX_TEXT


def build(port, token):
    srv = Server("ai-studio-supervisor", "1.0", "작업 제출·조회·취소만 가능. 승인과 병합은 CEO가 수행합니다.")
    def call(operation, **args):
        if not token: raise ToolError("STUDIO_SUPERVISOR_TOKEN 설정 및 CEO의 연결 권한 등록이 필요합니다.")
        conn = http.client.HTTPConnection("127.0.0.1",port,timeout=15)
        try:
            conn.request("POST","/supervisor/v1",json.dumps({"operation":operation,**args}),{"Content-Type":"application/json","Authorization":"Bearer "+token})
            response = conn.getresponse()
            data = response.read(1_500_001)
            if len(data)>1_500_000: raise ToolError("응답 크기 상한 초과")
            obj = json.loads(data)
            if not isinstance(obj,dict) or obj.get("schema") != "studio.supervisor-result/v1":
                raise ToolError("잘못된 감독 응답")
            if response.status != 200 or obj.get("status") != "ok":
                raise ToolError(str(obj.get("errors") or "외부 감독 연결 실패"))
            if not isinstance(obj.get("data"),dict):raise ToolError("잘못된 감독 응답")
            output = json.dumps(obj["data"],ensure_ascii=False)
            if len(output) > MAX_TEXT:
                raise ToolError("MCP 응답 크기 상한 초과: 로컬 감독 HTTP API로 결과를 조회하세요.")
            return output
        except (OSError, ValueError) as e:
            raise ToolError("외부 감독 연결 실패: 로컬 서버·권한을 확인하세요.") from e
        finally:conn.close()
    string = {"type":"string"}
    @srv.tool("submit_task","요청 키로 중복 없이 작업 제출. 실행과 승인 경계는 기존 회사 설정을 따릅니다.",{"project":string,"key":string,"payload":{"type":"object"}},["project","key","payload"],read_only=False)
    def submit_task(project,key,payload):return call("submit",project=project,key=key,payload=payload)
    @srv.tool("task_status","상태·차단 사유·필요한 승인·재개 방법 조회",{"project":string,"task":string},["project","task"])
    def task_status(project,task):return call("status",project=project,task=task)
    @srv.tool("task_events","영속 이벤트 커서로 진행 조회",{"project":string,"task":string,"after":{"type":"integer","minimum":0}},["project","task"])
    def task_events(project,task,after=0):return call("events",project=project,task=task,after=after)
    @srv.tool("task_result","산출물·수용 기준 근거·실제 실행 기록 조회",{"project":string,"task":string},["project","task"])
    def task_result(project,task):return call("result",project=project,task=task)
    @srv.tool("task_artifact","허용된 결과 파일을 base64와 SHA256으로 조회",{"project":string,"task":string,"path":string},["project","task","path"])
    def task_artifact(project,task,path):return call("artifact",project=project,task=task,path=path)
    @srv.tool("cancel_task","이 연결이 제출한 작업 취소",{"project":string,"task":string},["project","task"],read_only=False)
    def cancel_task(project,task):return call("cancel",project=project,task=task)
    return srv


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8765)
    args=parser.parse_args()
    if not 1<=args.port<=65535:parser.error("잘못된 포트")
    setup_stdio()
    build(args.port,os.environ.get("STUDIO_SUPERVISOR_TOKEN","")).serve()


if __name__ == "__main__":main()
