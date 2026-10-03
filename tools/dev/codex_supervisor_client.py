"""Use the installed Codex app-server MCP client without a model turn.

Configuration and the ephemeral protocol session are isolated in a private temp
directory. The supervisor credential is forwarded by environment-variable name.
The current desktop chat's MCP configuration is not edited.
"""
from pathlib import Path
import json
import queue
import subprocess
import sys
import tempfile
import threading
import time

from studio.runtimes import find_codex
from studio.util import atomic_write_text, clean_child_env, kill_tree, no_window_flags


class CodexMcpClient:
    def __init__(self, port, token, cwd, root, mcp_config=None):
        self.operations = []
        self.folder = tempfile.TemporaryDirectory(prefix="ai-studio-codex-mcp-")
        self.messages = queue.Queue()
        self.serial = 0
        self.process = None
        home = Path(self.folder.name)
        info = find_codex()
        if not info.get("found"):
            self.folder.cleanup()
            raise ValueError("Codex CLI를 찾을 수 없습니다.")
        self.version = info["version"]
        env = clean_child_env()
        env["CODEX_HOME"] = str(home)
        if token: env["STUDIO_SUPERVISOR_TOKEN"] = token
        config = '[analytics]\nenabled = false\n[mcp_servers.ai_studio]\n'
        if mcp_config is not None:
            config += '\n'.join(key+' = '+json.dumps(value) for key,value in mcp_config.items())+'\n'
        else:
            config += 'command = ' + json.dumps(sys.executable) + '\n'
            config += 'args = ' + json.dumps(["-X","utf8",str(root / "tools/supervisor-mcp.py"),"--port",str(port)]) + '\n'
            config += 'env_vars = ["STUDIO_SUPERVISOR_TOKEN"]\nstartup_timeout_sec = 20\ntool_timeout_sec = 20\n'
        atomic_write_text(home / "config.toml", config)
        try:
            self.process = subprocess.Popen([*info["cmd"],"app-server","--strict-config"],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                text=True,encoding="utf-8",env=env,cwd=cwd,creationflags=no_window_flags())
            def read():
                for line in self.process.stdout:
                    try: self.messages.put(json.loads(line))
                    except ValueError: self.messages.put({"malformed":True})
                self.messages.put({"closed":True})
            self.reader = threading.Thread(target=read,daemon=True)
            self.reader.start()
            self.request("initialize",{"clientInfo":{"name":"ai_studio_mcp_check","version":"1"},
                        "capabilities":{"experimentalApi":True}})
            self.send({"method":"initialized"})
            started = self.request("thread/start",{"cwd":str(cwd), "ephemeral":True,
                                   "approvalPolicy":"untrusted", "sandbox":"read-only"})
            self.thread_id = started["thread"]["id"]
            inventory = self.request("mcpServerStatus/list",{"threadId":self.thread_id,"serverName":"ai_studio"})
            self.tool_count = sum(len(server.get("tools",{})) for server in inventory.get("data",[]))
            if self.tool_count != 6:
                raise ValueError("Codex에서 감독 도구 6개를 확인하지 못했습니다.")
        except BaseException:
            self.close()
            raise

    def send(self, message):
        self.process.stdin.write(json.dumps(message)+"\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.serial += 1
        rid = self.serial
        self.send({"id":rid,"method":method,"params":params})
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            try: message = self.messages.get(timeout=max(.01,deadline-time.monotonic()))
            except queue.Empty: break
            if message.get("closed") or message.get("malformed"):
                raise ValueError("Codex MCP 연결 응답을 읽지 못했습니다.")
            if "method" in message and "id" in message:
                # Never accept an unsolicited permission/authentication request.
                self.send({"id":message["id"],"error":{"code":-32601,"message":"verification denies unsolicited requests"}})
                continue
            if message.get("id") != rid: continue
            if "error" in message:
                raise ValueError("Codex MCP 연결 실패: " + method)
            return message.get("result",{})
        raise TimeoutError("Codex MCP 연결 시간 초과: " + method)

    def call(self, name, **arguments):
        result = self.request("mcpServer/tool/call",{"threadId":self.thread_id,"server":"ai_studio",
                             "tool":name,"arguments":arguments})
        if result.get("isError"):
            raise ValueError("Codex MCP 도구 요청 실패: " + name)
        self.operations.append(name)
        return json.loads(result["content"][0]["text"])

    def close(self):
        if self.process:
            if self.process.poll() is None:
                try:
                    self.process.stdin.close()
                    self.process.wait(5)
                except (OSError,subprocess.TimeoutExpired):
                    kill_tree(self.process.pid)
                    self.process.wait(10)
            for stream in (self.process.stdout,self.process.stdin):
                if stream and not stream.closed: stream.close()
        self.folder.cleanup()
