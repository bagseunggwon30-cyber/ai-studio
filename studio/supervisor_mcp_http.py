"""Stateless MCP 2025 Streamable HTTP, using the existing supervisor authority."""
from __future__ import annotations
import json
import socket
from urllib.parse import urlparse

from .mcp_builtin.base import MAX_TEXT, ToolError
from .supervisor import Supervisor, AccessError
from .supervisor_mcp import tools_server

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26")
METHODS = {"initialize", "notifications/initialized", "notifications/cancelled",
           "ping", "tools/list", "tools/call"}
MAX_RESPONSE = 1_500_000


def send(handler, status, value=None, extra=None):
    try:
        raw = b"" if value is None else json.dumps(value,ensure_ascii=False,allow_nan=False).encode("utf-8")
        if len(raw) > MAX_RESPONSE:raise ValueError()
    except (ValueError,TypeError):
        status=500
        raw=b'{"jsonrpc":"2.0","id":null,"error":{"code":-32603,"message":"MCP response unavailable"}}'
    handler._send(status,raw,"application/json; charset=utf-8",extra)


def error(handler,status,code,message,rid=None,extra=None):
    send(handler,status,{"jsonrpc":"2.0","id":rid,"error":{"code":code,"message":message}},extra)


def guard(handler):
    if handler._host_kind() != "local":
        error(handler,403,-32000,"MCP is local only")
        return None
    origin=handler.headers.get("Origin")
    if origin is not None and origin not in handler.server.allowed_origins:
        error(handler,403,-32000,"Origin denied")
        return None
    url=urlparse(handler.path)
    if url.path != "/mcp" or url.query or url.fragment:
        error(handler,404,-32000,"MCP endpoint unavailable")
        return None
    supervisor=Supervisor(handler.server.engine)
    authorization=handler.headers.get("Authorization","")
    try:
        if len(handler.headers.get_all("Authorization",[])) != 1:raise AccessError("MCP 인증 필요",401)
        actor=supervisor.authenticate(authorization)
    except AccessError as exc:
        handler.server.store.event("supervisor.mcp.auth_denied","MCP 인증 거절")
        error(handler,exc.status,-32001,"MCP authorization required",
              extra={"WWW-Authenticate":'Bearer realm="AI Studio"'})
        return None
    except (ValueError,TypeError,AttributeError):
        error(handler,503,-32603,"MCP configuration unavailable")
        return None
    return supervisor,authorization,actor


def reject_stream(handler):
    # Never let a rejected browser request leave a live unread connection.
    handler.close_connection=True
    if guard(handler):
        send(handler,405,None,{"Allow":"POST"})


def post(handler):
    handler.connection.settimeout(10)
    try:
        raw=handler._read_body()
    except (OSError,socket.timeout):
        handler.close_connection=True
        return error(handler,408,-32000,"MCP request timeout")
    access=guard(handler)
    if access is None:return
    if raw is None:return error(handler,413,-32600,"MCP request too large")
    if handler.headers.get("Transfer-Encoding"):
        handler.close_connection=True
        return error(handler,400,-32600,"MCP transfer encoding unsupported")
    if handler.headers.get("Content-Type","").split(";",1)[0].strip().lower() != "application/json":
        return error(handler,415,-32600,"MCP requires application/json")
    accepted={part.split(";",1)[0].strip().lower() for part in handler.headers.get("Accept","").split(",")}
    if not {"application/json","text/event-stream"}.issubset(accepted):
        return error(handler,406,-32600,"MCP Accept must include JSON and SSE")
    version=handler.headers.get("MCP-Protocol-Version","2025-03-26")
    if version not in PROTOCOLS:return error(handler,400,-32600,"MCP protocol version unsupported")
    try:
        def finite(_):raise ValueError()
        msg=json.loads(raw.decode("utf-8"),parse_constant=finite)
    except (ValueError,UnicodeError):
        return error(handler,400,-32700,"Invalid MCP JSON")
    if (not isinstance(msg,dict) or msg.get("jsonrpc") != "2.0"
            or not isinstance(msg.get("method"),str)
            or not isinstance(msg.get("params",{}),dict)):
        return error(handler,400,-32600,"Invalid MCP request")
    rid=msg.get("id")
    if "id" in msg and (type(rid) not in (str,int) or isinstance(rid,str) and len(rid)>200):
        return error(handler,400,-32600,"Invalid MCP request id")
    method=msg["method"]
    if method not in METHODS:return error(handler,200,-32601,"MCP method unavailable",rid)
    supervisor,authorization,actor=access
    handler.server.store.event("supervisor.mcp.request","MCP 요청",actor=actor["id"],method=method)
    if "id" not in msg:
        # Notifications never submit/cancel a stored Studio job.
        return send(handler,202)
    def invoke(operation,**args):
        try:result=supervisor.call(authorization,{"operation":operation,**args})
        except AccessError as exc:raise ToolError(str(exc)) from None
        output=json.dumps(result,ensure_ascii=False)
        if len(output)>MAX_TEXT:raise ToolError("MCP 응답 크기 상한 초과: 로컬 감독 API로 조회하세요.")
        return output
    srv=tools_server(invoke)
    try:
        if method == "tools/call":
            params=msg.get("params",{})
            name=params.get("name")
            args=params.get("arguments",{})
            tool=srv.tools.get(name) if isinstance(name,str) else None
            if (not tool or not isinstance(args,dict)
                    or set(args)-set(tool.schema["properties"])
                    or any(key not in args for key in tool.schema["required"])):
                return error(handler,200,-32602,"MCP tool input invalid",rid)
            reply={"jsonrpc":"2.0","id":rid,"result":srv.call(params)}
        else:
            reply=srv.handle(msg)
        if method == "initialize" and reply and "result" in reply:
            asked=msg.get("params",{}).get("protocolVersion")
            reply["result"]["protocolVersion"]=asked if asked in PROTOCOLS else PROTOCOLS[0]
    except Exception:
        return error(handler,500,-32603,"MCP request failed",rid)
    send(handler,200,reply)
