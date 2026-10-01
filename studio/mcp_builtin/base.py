"""내장 MCP 서버의 뼈대 (표준 라이브러리만): stdin/stdout 한 줄 JSON-RPC 2.0.

Codex·Claude Code가 이 파일들을 하위 프로세스로 띄운다 (studio/mcp.py가 명령을 만든다).
받는 것: initialize, notifications/initialized, ping, tools/list, tools/call. 그 밖의 요청은 '없는 방법' 오류.
도구 함수는 글(str)을 돌려주고, 실패하면 ToolError를 던진다 (isError로 알린다).
stdout에는 JSON-RPC만 쓴다 — 로그는 stderr로.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXT = 60_000  # 도구 결과 한 번의 최대 글자 (프롬프트가 너무 길어지지 않게)


class ToolError(Exception):
    """도구를 쓸 수 없을 때 (잘못된 입력, 못 찾음). 에이전트에게 이유를 글로 알린다."""


class Tool:
    def __init__(self, name: str, description: str, params: dict[str, Any], required: list[str], fn: Callable[..., str],
                 read_only: bool = True):
        self.name, self.description, self.fn, self.read_only = name, description, fn, read_only
        self.schema = {"type": "object", "properties": params, "required": required, "additionalProperties": False}

    def info(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema,
                "annotations": {"readOnlyHint": self.read_only, "openWorldHint": False}}


class Server:
    def __init__(self, name: str, version: str, instructions: str = ""):
        self.name, self.version, self.instructions = name, version, instructions
        self.tools: dict[str, Tool] = {}

    def tool(self, name: str, description: str, params: dict[str, Any] | None = None, required: list[str] | None = None,
             read_only: bool = True) -> Callable[[Callable[..., str]], Callable[..., str]]:
        def wrap(fn: Callable[..., str]) -> Callable[..., str]:
            self.tools[name] = Tool(name, description, params or {}, required or [], fn, read_only)
            return fn
        return wrap

    # ------------------------------------------------------------ 요청 처리
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        mid = msg.get("id")
        if mid is None:  # 알림 (initialized, cancelled 등): 답하지 않는다
            return None
        try:
            if method == "initialize":
                asked = str((msg.get("params") or {}).get("protocolVersion") or "")
                result: Any = {
                    "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": self.version},
                }
                if self.instructions:
                    result["instructions"] = self.instructions
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [t.info() for t in self.tools.values()]}
            elif method == "tools/call":
                result = self.call(msg.get("params") or {})
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"없는 방법: {method}"}}
        except Exception as e:  # noqa: BLE001 - 서버가 죽지 않고 오류로 답한다
            traceback.print_exc(file=sys.stderr)
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)[:500]}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(str(params.get("name", "")))
        if not tool:
            return _text(f"없는 도구: {params.get('name')}", error=True)
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _text("arguments는 객체여야 합니다.", error=True)
        unknown = [k for k in args if k not in tool.schema["properties"]]
        missing = [k for k in tool.schema["required"] if k not in args]
        if unknown or missing:
            return _text(f"입력이 맞지 않습니다. 모르는 칸: {unknown or '없음'}, 빠진 칸: {missing or '없음'}", error=True)
        try:
            return _text(tool.fn(**args))
        except ToolError as e:
            return _text(str(e), error=True)

    def serve(self) -> None:
        """stdin이 닫힐 때까지 한 줄씩 읽고 답한다."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON이 아닙니다."}})
                continue
            batch = msg if isinstance(msg, list) else [msg]
            answers = [a for a in (self.handle(m) for m in batch if isinstance(m, dict)) if a]
            if answers:
                _send(answers if isinstance(msg, list) else answers[0])


def _text(text: str, error: bool = False) -> dict[str, Any]:
    text = str(text)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f"\n…(길어서 {MAX_TEXT}자까지만)"
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _send(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def setup_stdio() -> None:
    """윈도우에서도 UTF-8로 읽고 쓴다 (한글이 깨지지 않게)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
