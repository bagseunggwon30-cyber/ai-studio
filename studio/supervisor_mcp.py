"""Opt-in stdio bridge to the local supervisor API. Never issues credentials.
Run: python -m studio.supervisor_mcp --port 8765
Set STUDIO_SUPERVISOR_TOKEN in the client environment after owner provisioning.
"""
from __future__ import annotations
import argparse
import http.client
import json
import os
from pathlib import Path
from .mcp_builtin.base import Server, ToolError, setup_stdio, MAX_TEXT


def build(port, token):
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
    return tools_server(call)


def tools_server(call):
    """One tool catalog for stdio and HTTP; all actions use the supervisor gate."""
    srv = Server("ai-studio-supervisor", "1.1",
        "AI Studio 감독 MCP: 작업 제출·상태·이벤트·결과·검증 파일·본인 작업 취소만 제공합니다. "
        "작업 제출의 project/key/payload를 사용하고 같은 요청은 같은 key로 재전송하세요. "
        "프로젝트·경로 권한과 모델 사용 승인·기획 결재·최종 병합은 기존 CEO 경계를 따릅니다. "
        "직원에게 장착하는 MCP와 별개의 외부 감독 연결입니다. "
        "도구 등록·요청 접수·실제 모델 실행·검증 통과·사람 승인 상태를 각각 구분하세요.")
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


def add_arguments(parser):
    parser.add_argument("--port","--api-port",type=int,default=8765)
    parser.add_argument("--credential",type=Path,help="현재 Windows 사용자로 암호화한 로컬 연결 토큰 파일")
    parser.add_argument("--user-credential",action="store_true",
        help="현재 Windows 사용자의 기존 소윤 연결 토큰을 내부적으로 사용; 발급·변경 없음")
    parser.add_argument("--config",choices=("json","codex"),help="비밀값 없는 클라이언트 설정 출력")


def client_config(root, port):
    import sys
    return {"command":sys.executable,
        "args":["-X","utf8","-B",str(root.resolve() / "studio.py"),"mcp","--port",str(port),"--user-credential"]}


def run(args, root, parser):
    if not 1<=args.port<=65535:parser.error("잘못된 포트")
    if args.credential and args.user_credential:parser.error("연결 파일 선택은 한 방식만 사용하세요.")
    if args.config:
        config=client_config(root,args.port)
        if args.config == "json":
            print(json.dumps({"mcpServers":{"ai_studio":config}},ensure_ascii=False,indent=2))
        else:
            from .supervisor_setup import TOOLS
            config.update(enabled=True,enabled_tools=TOOLS,default_tools_approval_mode="writes",
                          startup_timeout_sec=20,tool_timeout_sec=20)
            print("[mcp_servers.ai_studio]")
            for key,value in config.items():print(key+" = "+json.dumps(value,ensure_ascii=False))
        return 0
    setup_stdio()
    token = os.environ.get("STUDIO_SUPERVISOR_TOKEN","")
    credential = args.credential
    if args.user_credential:
        local = os.environ.get("LOCALAPPDATA")
        if not local:parser.exit(2,"현재 Windows 사용자 저장 위치를 확인하지 못했습니다.\n")
        credential = Path(local) / "AIStudio/supervisors/soyun.credential"
    if credential:
        from .supervisor_credentials import load, CredentialError
        try: token = load(credential)
        except CredentialError as exc: parser.exit(2,str(exc)+"\n")
    build(args.port,token).serve()
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser()
    add_arguments(parser)
    return run(parser.parse_args(argv),Path(__file__).resolve().parents[1],parser)


if __name__ == "__main__":main()
