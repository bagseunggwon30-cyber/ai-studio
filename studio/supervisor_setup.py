"""Explicit owner-approved local registration. Contains no credential literals."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tomllib

from . import supervisor_credentials as credentials
from .util import atomic_write_json, atomic_write_text, read_json

TOOLS = ["submit_task", "task_status", "task_events", "task_result", "task_artifact", "cancel_task"]
GRANT = {"studio-docs":{"read":True,"write":True,"paths":["reports/connection-check/**"]}}


def default_paths():
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    private = Path(os.environ.get("LOCALAPPDATA", "")) / "AIStudio" / "supervisors" / "soyun.credential"
    if not os.environ.get("LOCALAPPDATA"): raise ValueError("로컬 사용자 저장 위치를 확인하지 못했습니다.")
    return home / "config.toml", private


def connection_config(root: Path, credential: Path, port: int):
    return {"command":sys.executable,
            "args":["-X","utf8","-B",str(root / "tools/supervisor-mcp.py"),
                    "--port",str(port),"--credential",str(credential)],
            "enabled":True, "enabled_tools":TOOLS,
            "startup_timeout_sec":20, "tool_timeout_sec":20,
            "default_tools_approval_mode":"writes"}


def provision(root: Path, config_path: Path, credential: Path, port: int):
    if not 1 <= port <= 65535: raise ValueError("잘못된 포트")
    raw = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    existing = tomllib.loads(raw)
    target = connection_config(root,credential,port)
    prior = existing.get("mcp_servers",{}).get("ai_studio")
    if prior is not None and prior != target:
        raise ValueError("기존 ai_studio MCP 설정이 달라 덮어쓰지 않았습니다.")
    registry_path = root / "data/supervisors.json"
    registry = read_json(registry_path,{}) or {}
    if not isinstance(registry,dict): raise ValueError("기존 감독 권한 설정 형식 오류")
    rows = registry.get("clients",[])
    if not isinstance(rows,list) or not all(isinstance(row,dict) for row in rows):
        raise ValueError("기존 감독 권한 설정 형식 오류")
    owned = [row for row in rows if row.get("id") == "soyun"]
    if len(owned) > 1: raise ValueError("소윤이 연결 ID 중복")
    if credential.exists():
        token = credentials.load(credential)
    else:
        if owned: raise ValueError("기존 소윤이 연결 토큰이 없어 자동 교체하지 않았습니다.")
        token = secrets.token_urlsafe(48)
        credentials.save(credential,token)
    hashed = hashlib.sha256(token.encode()).hexdigest()
    if owned and owned[0].get("token_sha256") != hashed:
        raise ValueError("기존 소윤이 토큰과 연결 파일이 달라 자동 교체하지 않았습니다.")
    client = {"id":"soyun","enabled":True,"token_sha256":hashed,"projects":GRANT}
    registry = {**registry,"enabled":True,"clients":[row for row in rows if row.get("id") != "soyun"]+[client]}
    atomic_write_json(registry_path,registry)
    if prior is None:
        block = "\n[mcp_servers.ai_studio]\n" + "\n".join(
            key + " = " + json.dumps(value,ensure_ascii=False) for key,value in target.items()) + "\n"
        proposed = raw.rstrip("\n") + "\n" + block
        if tomllib.loads(proposed).get("mcp_servers",{}).get("ai_studio") != target:
            raise ValueError("MCP 등록 형식 오류")
        atomic_write_text(config_path,proposed)
    return {"status":"configured","client":"soyun","grants":GRANT,
            "credential_storage":"Windows DPAPI CurrentUser; owner-only ACL",
            "token_values_exposed":False, "mcp_name":"ai_studio","tools":TOOLS,
            "model_generation_calls":0,"dot_cloud_registration_verified":False}
