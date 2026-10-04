"""Reusable notes and bounded DAGs, adapted to the existing task engine.

Notes are documentation. Only the operations below can execute. Model work stays
in Engine, including its sandbox, journal, QA, limits and CEO approval boundary.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from uuid import uuid4

from . import mcp
from .checkpoints import digest
from .util import atomic_write_json, now_iso


class WorkbenchError(ValueError):
    pass


OPERATIONS = {
    "input": {"title": "입력 노트", "mode": "code", "input": None, "output": "text", "params": {"text": ""},
              "description": "입력한 글을 그대로 전달합니다. 모델 사용 없음."},
    "format": {"title": "문장 정리", "mode": "code", "input": "text", "output": "text", "params": {"prefix": "", "suffix": ""},
               "description": "앞말·뒷말을 붙입니다. 고정 처리이며 모델 판단이나 코드 실행을 하지 않습니다."},
    "lines": {"title": "목록 정리", "mode": "code", "input": "text", "output": "text", "params": {"dedupe": True, "sort": False},
              "description": "각 줄의 공백·빈 줄을 정리하고 중복 제거·정렬을 선택합니다. 200줄 이내의 고정 처리입니다."},
    "require_text": {"title": "입력 조건 확인", "mode": "code", "input": "text", "output": "text", "params": {"contains": "", "min_length": 1},
                     "description": "최소 글자 수와 필수 문구를 확인합니다. 조건에 맞지 않으면 후속 노드를 막습니다."},
    "requirements": {"title": "요구정리", "mode": "model", "input": "text", "output": "plan", "params": {},
                     "job": "producer", "description": "기존 읽기 전용 기획을 한 번 요청합니다. 기획 결재 후 만든 카드는 진행판에서 별도로 실행합니다."},
    "implement": {"title": "구현", "mode": "model", "input": "text", "output": "candidate",
                  "params": {"acceptance": []}, "job": "builder",
                  "description": "기존 구현→신뢰 검증→읽기 전용 검토를 한 번 수행합니다. 실패 자동 재시도 없음. 병합은 CEO 결재로만 합니다."},
    "test": {"title": "테스트", "mode": "code", "input": "candidate", "output": "candidate", "params": {},
             "description": "구현 작업의 실제 신뢰 검증 기록과 후보 SHA를 확인합니다. 별도 테스트 명령은 실행하지 않습니다."},
    "review": {"title": "검토", "mode": "code", "input": "candidate", "output": "candidate", "params": {},
               "description": "구현 내부에서 실행된 읽기 전용 모델 리뷰의 승인 증거를 확인합니다. 추가 모델 호출 없음."},
    "approve": {"title": "사용자승인", "mode": "human", "input": "task", "output": "approved", "params": {},
                "description": "기존 결재 창에서 CEO가 승인할 때까지 기다립니다. 구현은 정확한 검증 후보만 병합합니다."},
    "summary": {"title": "결과정리", "mode": "code", "input": "any", "output": "result", "params": {},
                "description": "입력·작업 결과·검증·결재 기록을 장부에 정리합니다. 모델 사용 없음."},
    "shell": {"title": "자유 코드·셸", "mode": "unsupported", "input": "any", "output": "any", "params": {},
              "description": "등록된 고정 처리만 실행할 수 있습니다. 노트의 임의 코드·셸 실행은 지원하지 않습니다."},
}
NOTE_FIELDS = ("purpose", "inputs", "outputs", "cautions", "example")
LIVE = {"running", "waiting"}
NODE_LABELS = {"pending": "순서 대기", "running": "처리 중", "waiting": "결재 대기", "succeeded": "완료",
               "blocked": "막힘", "skipped": "선행 오류", "cancelled": "중단"}
MAX_NODES = 24


def _text(value, label, limit=4000, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise WorkbenchError(f"{label}: {'내용이 필요하고 ' if required else ''}{limit}자 이내의 글로 입력하세요.")
    return value.strip()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,70}", value):
        raise WorkbenchError("노드·폴더·흐름 ID 형식이 잘못됐습니다.")
    return value


def _params(operation, value):
    defaults = OPERATIONS[operation]["params"]
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise WorkbenchError("실행 명세에 지원하지 않는 항목이 있습니다. 임의 명령은 등록할 수 없습니다.")
    out = {**deepcopy(defaults), **value}
    for key in out:
        if key in ("dedupe", "sort"):
            if type(out[key]) is not bool:
                raise WorkbenchError("목록 정리 옵션은 켬·끔으로 지정하세요.")
        elif key == "min_length":
            if type(out[key]) is not int or not 1 <= out[key] <= 4000:
                raise WorkbenchError("최소 글자 수는 1~4000 범위여야 합니다.")
        elif key == "acceptance":
            if not isinstance(out[key], list) or len(out[key]) > 12:
                raise WorkbenchError("수용 기준은 12개 이내 목록이어야 합니다.")
            out[key] = [_text(v, "수용 기준", 500, True) for v in out[key]]
        else:
            validated = _text(out[key], key)
            out[key] = out[key] if key in ("prefix", "suffix") else validated
    return out


def builtin_nodes():
    return [{"id": "builtin-" + key, "version": 1, "title": op["title"], "folder": "basic", "builtin": True,
             "note": {"purpose": op["description"], "inputs": op["input"] or "직접 입력", "outputs": op["output"],
                      "cautions": "문서와 실행 명세는 분리됩니다.", "example": ""},
             "spec": {"operation": key, "params": deepcopy(op["params"])}}
            for key, op in OPERATIONS.items()]


class Workbench:
    def __init__(self, engine):
        self.engine = engine
        self.store = engine.store

    def _doc(self, name, default):
        path = self.store.dir / f"{name}.json"
        if not path.exists():
            return deepcopy(default)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("document")
            return value
        except (ValueError, OSError) as exc:
            raise WorkbenchError("저장 문서를 읽을 수 없습니다. 원본을 보존했습니다. 백업을 확인하세요.") from exc

    def _catalog(self):
        return self._doc("workbench", {"revision": 0, "folders": [{"id": "basic", "title": "기본 기능"},
                                                                  {"id": "personal", "title": "내 기능"}], "nodes": {}, "flows": {}})

    def catalog(self):
        with self.store.lock:
            doc = self._catalog()
            nodes = builtin_nodes() + [self._public(n) for n in doc["nodes"].values()]
            for n in nodes:
                n["capability"] = self.capability(n["spec"]["operation"])
            return {"revision": doc["revision"], "folders": doc["folders"], "nodes": nodes,
                    "flows": [self._public(f) for f in doc["flows"].values()],
                    "operations": {k: {**v, **self.capability(k)} for k, v in OPERATIONS.items()}, "max_nodes": MAX_NODES}

    @staticmethod
    def _public(row):
        return deepcopy({k: v for k, v in row.items() if k != "history"})

    def capability(self, operation):
        op = OPERATIONS[operation]
        reason = ""
        if op["mode"] == "unsupported":
            reason = op["description"]
        elif op.get("job") and not self.engine.staff_for(op["job"]):
            reason = "이 기능을 맡을 직원이 없습니다. 기존 직원 설정을 확인하세요."
        elif op.get("job"):
            role = self.engine.cfg.roles[self.engine._pick(op["job"])]
            if role.runtime == "grok_text":
                reason = "이 작업대는 Grok 텍스트 호출을 지원하지 않습니다. 현재 격리 지원을 별도로 검증해야 합니다."
            elif operation == "implement" and role.runtime not in ("codex", "fake"):
                reason = "현재 엔진은 Codex의 파일 변경 권한만 지원합니다."
        return {"enabled": not reason, "reason": reason, "mode": op["mode"]}

    def model_settings(self, role_key, job):
        role = self.engine.cfg.roles[role_key]
        disabled = role.runtime == "claude" and not self.engine.cfg.runtime_cfg("claude").get("enabled", False)
        return {"role": role_key, "title": role.title, "runtime": role.runtime, "model": role.model, "effort": role.effort,
                "fallback_runtime": role.fallback_runtime, "fallback_model": role.fallback_model,
                "effective_runtime": "codex" if disabled else role.runtime,
                "effective_model": role.fallback_model if disabled and role.fallback_runtime == "codex" else "" if disabled else role.model,
                "sandbox": "read-only" if job in ("producer", "reviewer") else "workspace-write",
                "mcp": [] if job == "reviewer" else [{"name": s["name"], "source": s["source"],
                    "configuration_hash": digest({k: s.get(k) for k in ("transport", "command", "args", "url", "env_keys", "bearer_key")})}
                    for s in mcp.servers(self.engine.cfg, include_secret_presence=False) if s["enabled"] and role_key in s["equipped"]]}

    def check_task(self, task, role, stage):
        expected = task.extra.get("workflow_models")
        if expected is None:
            return
        from .supervisor import path_scope
        snapshot = self.run(task.extra["workflow_run"])["snapshot"]
        project = self.engine.cfg.projects.get(task.project)
        context = {"repo": str(project.repo), "main_branch": project.main_branch, "qa": project.qa} if project else {}
        if (task.project != snapshot["project"] or context != snapshot["context"]
                or task.extra.get("scope_paths") != snapshot["allowed_paths"]
                or any(not path_scope(p, snapshot["allowed_paths"]) for p in task.allowed_paths)):
            raise WorkbenchError("실행 확인 이후 작업 대상·검증·허용 범위가 바뀌었습니다. 새 계획을 확인하세요.")
        job = "reviewer" if stage.startswith("review") else "producer" if task.kind == "plan" else "builder"
        saved = next((m for m in expected if m["role"] == role and m["job"] == job), None)
        if not saved or self.model_settings(role, job) != {k: v for k, v in saved.items() if k != "job"}:
            raise WorkbenchError("실행 확인 이후 직원·모델·도구 설정이 바뀌었습니다. 재호출하지 않고 결과를 보존했습니다.")

    def save_folder(self, body):
        with self.store.lock:
            doc = self._catalog()
            key = _id(body.get("id") or "folder-" + uuid4().hex[:12])
            if key == "basic":
                raise WorkbenchError("기본 폴더 이름은 변경할 수 없습니다.")
            title = _text(body.get("title"), "폴더 이름", 60, True)
            prior = next((f for f in doc["folders"] if f["id"] == key), None)
            if body.get("revision") != doc["revision"]:
                raise WorkbenchError("다른 창에서 서랍이 변경됐습니다. 다시 불러온 뒤 저장하세요.")
            if len(doc["folders"]) >= 100 and not prior:
                raise WorkbenchError("폴더는 100개까지 저장할 수 있습니다.")
            if prior:
                prior["title"] = title
            else:
                doc["folders"].append({"id": key, "title": title})
            self._save_catalog(doc, "폴더 저장")
            return {"id": key, "title": title}

    def _save_catalog(self, doc, message):
        doc["revision"] += 1
        self.store.write_doc("workbench", doc)
        self.store.event("workbench.saved", message)

    def save_node(self, body):
        with self.store.lock:
            doc = self._catalog()
            key = _id(body.get("id") or "node-" + uuid4().hex[:12])
            if key.startswith("builtin-"):
                raise WorkbenchError("기본 기능은 사본으로 저장해 고칠 수 있습니다.")
            title = _text(body.get("title"), "기능 제목", 80, True)
            folder = self._folder(doc, body.get("folder", "personal"))
            note = body.get("note")
            if not isinstance(note, dict) or set(note) - set(NOTE_FIELDS):
                raise WorkbenchError("노트는 목적·입력·출력·주의·예시로 작성하세요.")
            note = {k: _text(note.get(k, ""), k) for k in NOTE_FIELDS}
            spec = body.get("spec", {})
            operation = spec.get("operation") if isinstance(spec, dict) else None
            if operation not in OPERATIONS or set(spec) - {"operation", "params"}:
                raise WorkbenchError("등록된 실행 종류를 선택하세요.")
            params = _params(operation, spec.get("params", {}))
            row = {"id": key, "title": title, "folder": folder, "note": note, "spec": {"operation": operation, "params": params}}
            self._version(doc["nodes"], row, body.get("version", 0))
            self._save_catalog(doc, f"재사용 기능 저장: {title}")
            return self._public(row)

    @staticmethod
    def _folder(doc, key):
        if key not in {f["id"] for f in doc["folders"]}:
            raise WorkbenchError("저장할 폴더를 선택하세요.")
        return key

    def _version(self, rows, row, expected):
        old = rows.get(row["id"])
        if expected != (old["version"] if old else 0):
            raise WorkbenchError("다른 창에서 수정한 버전이 있습니다. 다시 불러온 뒤 저장하세요.")
        if not old and len(rows) >= 500:
            raise WorkbenchError("기능·작업 묶음은 각각 500개까지 저장할 수 있습니다.")
        row.update(version=(old["version"] + 1 if old else 1), updated_at=now_iso(),
                   history=(old.get("history", []) + [self._public(old)] if old else []))
        rows[row["id"]] = row

    def _definition(self, ref, doc):
        if not isinstance(ref, dict) or set(ref) != {"id", "version"}:
            raise WorkbenchError("기능 ID와 버전이 필요합니다.")
        key = _id(ref["id"])
        version = ref["version"]
        if type(version) is not int or version < 1:
            raise WorkbenchError("기능 버전은 1 이상의 정수입니다.")
        latest = next((n for n in builtin_nodes() if n["id"] == key), None) or doc["nodes"].get(key)
        if latest:
            found = next((n for n in [latest, *latest.get("history", [])] if n["version"] == version), None)
            if found:
                return self._public(found)
        raise WorkbenchError(f"기능 {key}의 v{version}을 찾을 수 없습니다.")

    def validate(self, graph, *, execute=False, doc=None):
        doc = doc or self._catalog()
        if not isinstance(graph, dict) or set(graph) != {"nodes", "edges"}:
            raise WorkbenchError("노드와 연결선으로 된 흐름이 필요합니다.")
        if not isinstance(graph["nodes"], list) or len(graph["nodes"]) > MAX_NODES or (execute and not graph["nodes"]):
            raise WorkbenchError(f"흐름에는 1~{MAX_NODES}개 노드가 필요합니다.")
        if not isinstance(graph["edges"], list) or len(graph["edges"]) > MAX_NODES * 2:
            raise WorkbenchError("연결선이 너무 많거나 목록 형식이 아닙니다.")
        nodes, by_id = [], {}
        for raw in graph["nodes"]:
            if not isinstance(raw, dict) or set(raw) - {"id", "ref", "params", "position"}:
                raise WorkbenchError("노드 형식이 잘못됐습니다.")
            key = _id(raw.get("id"))
            if key in by_id:
                raise WorkbenchError("같은 노드 ID가 두 번 있습니다.")
            definition = self._definition(raw.get("ref"), doc)
            op = definition["spec"]["operation"]
            overrides = raw.get("params", {})
            if not isinstance(overrides, dict):
                raise WorkbenchError("노드 입력은 실행 명세 객체여야 합니다.")
            params = _params(op, {**definition["spec"]["params"], **overrides})
            position = raw.get("position", {"x": len(nodes) * 245, "y": 20})
            if not isinstance(position, dict) or set(position) != {"x", "y"} or any(type(v) not in (int, float) or not 0 <= v <= 10000 for v in position.values()):
                raise WorkbenchError("노드 위치는 0~10000 범위여야 합니다.")
            node = {"id": key, "ref": {"id": definition["id"], "version": definition["version"]}, "params": params,
                    "position": position, "definition": definition}
            if execute and not self.capability(op)["enabled"]:
                raise WorkbenchError(f"{definition['title']}: {self.capability(op)['reason']}")
            if execute and op == "input" and not params["text"]:
                raise WorkbenchError(f"{definition['title']}: 실행 입력을 적어 주세요.")
            if execute and op == "implement" and not params["acceptance"]:
                raise WorkbenchError("구현 노드에는 확인 가능한 수용 기준이 하나 이상 필요합니다.")
            nodes.append(node)
            by_id[key] = node
        edges, incoming = [], {}
        for raw in graph["edges"]:
            if not isinstance(raw, dict) or set(raw) != {"from", "to"}:
                raise WorkbenchError("연결선은 출발·도착 노드로 지정하세요.")
            a, b = raw["from"], raw["to"]
            if not isinstance(a, str) or not isinstance(b, str) or a not in by_id or b not in by_id or a == b:
                raise WorkbenchError("없는 노드·자기 자신에는 연결할 수 없습니다.")
            if b in incoming:
                raise WorkbenchError("입력마다 하나의 연결만 허용됩니다. 중복 연결을 제거하세요.")
            source = OPERATIONS[by_id[a]["definition"]["spec"]["operation"]]["output"]
            target = OPERATIONS[by_id[b]["definition"]["spec"]["operation"]]["input"]
            if not (source == target or target == "any" or (target == "task" and source in ("candidate", "plan"))):
                raise WorkbenchError(f"입출력 형식이 맞지 않습니다: {source} → {target or '직접 입력'}")
            edges.append({"from": a, "to": b})
            incoming[b] = a
        order, pending = [], set(by_id)
        while pending:
            ready = [n["id"] for n in nodes if n["id"] in pending and (n["id"] not in incoming or incoming[n["id"]] in order)]
            if not ready:
                raise WorkbenchError("순환 연결은 실행할 수 없습니다. 연결을 끊어 주세요.")
            order.extend(ready)
            pending.difference_update(ready)
        if execute:
            for n in nodes:
                op = n["definition"]["spec"]["operation"]
                if OPERATIONS[op]["input"] and n["id"] not in incoming:
                    raise WorkbenchError(f"{n['definition']['title']}: 선행 입력을 연결하세요.")
                if op in ("implement", "requirements"):
                    successors = [x for x in nodes if x["definition"]["spec"]["operation"] == "approve" and self._ancestor(n["id"], x["id"], incoming)]
                    if not successors:
                        raise WorkbenchError("모델 작업에는 사용자승인 노드를 연결해야 합니다.")
        return {"nodes": nodes, "edges": edges, "order": order}

    @staticmethod
    def _ancestor(source, target, incoming):
        while target in incoming:
            target = incoming[target]
            if target == source:
                return True
        return False

    @staticmethod
    def graph_only(expanded):
        return {"nodes": [{k: deepcopy(v) for k, v in n.items() if k != "definition"} for n in expanded["nodes"]], "edges": deepcopy(expanded["edges"])}

    def save_flow(self, body):
        with self.store.lock:
            doc = self._catalog()
            expanded = self.validate(body.get("graph"), doc=doc)
            row = {"id": _id(body.get("id") or "flow-" + uuid4().hex[:12]), "title": _text(body.get("title"), "작업 묶음 이름", 80, True),
                   "folder": self._folder(doc, body.get("folder", "personal")), "graph": self.graph_only(expanded)}
            project = body.get("project") or None
            if project is not None and project not in self.engine.cfg.projects:
                raise WorkbenchError("등록된 작업 대상을 선택하세요.")
            scope = body.get("allowed_paths", [])
            if not isinstance(scope, list) or len(scope) > 40:
                raise WorkbenchError("허용 경로는 40개 이내 목록이어야 합니다.")
            row.update(project=project, allowed_paths=[_text(p, "허용 경로", 200, True) for p in scope])
            self._version(doc["flows"], row, body.get("version", 0))
            self._save_catalog(doc, f"작업 묶음 저장: {row['title']}")
            return self._public(row)

    def plan(self, body):
        with self.store.lock:
            expanded = self.validate(body.get("graph"), execute=True)
            title = _text(body.get("title"), "실행 이름", 80, True)
            has_model = any(OPERATIONS[n["definition"]["spec"]["operation"]]["mode"] == "model" for n in expanded["nodes"])
            project = self.engine.cfg.projects.get(body.get("project"))
            if has_model and not project:
                raise WorkbenchError("등록된 작업 대상을 선택하세요.")
            scope = body.get("allowed_paths", [])
            if not isinstance(scope, list) or len(scope) > 40:
                raise WorkbenchError("허용 경로는 목록으로 지정하세요.")
            if has_model:
                from .engine import _clean_paths
                from .supervisor import path_scope
                scope = _clean_paths(scope, project)
                if not scope or any(not path_scope(p, project.default_allowed_paths) for p in scope):
                    raise WorkbenchError("기존 프로젝트의 허용 경로 안에서 실행 범위를 하나 이상 선택하세요.")
            elif scope:
                raise WorkbenchError("고정 글 처리에는 파일 변경 경로를 지정하지 않습니다.")
            steps, models = [], []
            for key in expanded["order"]:
                n = next(n for n in expanded["nodes"] if n["id"] == key)
                op = n["definition"]["spec"]["operation"]
                steps.append({"node": key, "title": n["definition"]["title"], "operation": op, "mode": OPERATIONS[op]["mode"],
                              "description": OPERATIONS[op]["description"]})
                jobs = ["producer"] if op == "requirements" else ["builder", "reviewer"] if op == "implement" else []
                for job in jobs:
                    candidates = self.engine.staff_for(job)
                    if not candidates:
                        raise WorkbenchError(f"{job} 담당 직원이 없어 실행할 수 없습니다.")
                    role_key = candidates[0]
                    role = self.engine.cfg.roles[role_key]
                    if role.runtime == "grok_text" or role.fallback_runtime == "grok_text":
                        raise WorkbenchError("작업대에서는 Grok 텍스트 실행·대체 실행을 지원하지 않습니다.")
                    models.append({"node": key, "job": job, **self.model_settings(role_key, job)})
            plan = {"title": title, "graph": expanded, "project": project.key if has_model else None,
                    "project_title": project.title if has_model else "글 처리 · 파일 변경 없음", "allowed_paths": scope,
                    "uses_models": has_model, "steps": steps, "models": models, "max_model_calls": len(models),
                    "policy": "실패 자동 재시도·대체 재호출·회고 자동 생성 없음. 기획 결재의 자식 카드는 별도 수동 실행. 병합은 기존 CEO 결재로만.",
                    "context": {"repo": str(project.repo), "main_branch": project.main_branch, "qa": project.qa} if has_model else {}}
            plan["hash"] = digest(plan)
            return plan

    def start(self, body):
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
            raise WorkbenchError("실행 확인 번호가 필요합니다. 계획을 다시 확인하세요.")
        key = "W" + request_id
        with self.store.lock:
            path = self.store.dir / "workbench-runs" / f"{key}.json"
            if path.exists():
                old = self.run(key)
                if old["plan_hash"] != body.get("plan_hash"):
                    raise WorkbenchError("같은 확인 번호로 다른 실행을 시작할 수 없습니다.")
                return old
            plan = self.plan(body)
            if body.get("confirmed") is not True or body.get("allow_models") is not plan["uses_models"] or body.get("plan_hash") != plan["hash"]:
                raise WorkbenchError("흐름·범위·모델 설정이 바뀌었거나 실행 확인이 없습니다. 계획을 다시 확인하세요.")
            if self.engine._stop.is_set():
                raise WorkbenchError("회사가 정지 상태입니다. 실행을 시작할 수 없습니다.")
            run = {"id": key, "title": plan["title"], "created_at": now_iso(), "status": "running", "plan_hash": plan["hash"],
                   "snapshot": plan, "nodes": {n["id"]: {"status": "pending", "inputs": None, "output": None, "error": "", "task": None}
                                                for n in plan["graph"]["nodes"]}, "error": "", "events": []}
            index = self._doc("workbench-ledger", {"ids": []})
            if len(index["ids"]) >= 2000:
                raise WorkbenchError("장부 2000회 상한에 도달했습니다. 기록을 보존한 뒤 정리하세요.")
            self._persist(run)
            index["ids"].append(key)
            self.store.write_doc("workbench-ledger", index)
            self._event(run, "started", "실행 계획을 확인하고 작업대를 시작했습니다.")
            self._persist(run)
            self.engine.wake()
            return run

    def _persist(self, run):
        atomic_write_json(self.store.dir / "workbench-runs" / f"{_id(run['id'])}.json", run)
        self.store._bump()

    def _event(self, run, kind, message, node=None):
        event = {"at": now_iso(), "type": kind, "message": message, "node": node}
        run["events"].append(event)
        self.store.event("workbench." + kind, message, workflow=run["id"], node=node)

    def run(self, key):
        _id(key)
        value = self._doc("workbench-runs/" + key, {})
        if not value:
            raise WorkbenchError("실행 장부를 찾을 수 없습니다.")
        return value

    def ledger(self):
        with self.store.lock:
            rows = [self.run(key) for key in reversed(self._doc("workbench-ledger", {"ids": []})["ids"])]
            return [{k: r[k] for k in ("id", "title", "created_at", "status", "error")} | {"nodes": len(r["nodes"]), "uses_models": r["snapshot"]["uses_models"]} for r in rows]

    def recover(self):
        with self.store.lock:
            # Recover a durable run whose index write was interrupted as well.
            index = self._doc("workbench-ledger", {"ids": []})
            root = self.store.dir / "workbench-runs"
            for path in sorted(root.glob("W*.json")) if root.exists() else []:
                if path.stem not in index["ids"]:
                    index["ids"].append(path.stem)
                    self.store.write_doc("workbench-ledger", index)
            for key in index["ids"]:
                run = self.run(key)
                if run["status"] in LIVE:
                    for task in self.store.list():
                        if task.extra.get("workflow_run") != key:
                            continue
                        state = run["nodes"].get(task.extra.get("workflow_node"))
                        if state and not state["task"]:
                            state["task"] = task.id
                            state["status"] = "running"
                        if task.status in ("ready", "queued") and task.run_requested:
                            task.run_requested = False
                            self.store.save(task)
                    run["status"] = "blocked"
                    run["error"] = "프로그램 재시작으로 중단됐습니다. 기존 작업·실행 결과를 확인한 뒤 '기록 다시 확인'을 누르세요. 모델을 자동 재호출하지 않습니다."
                    self._event(run, "interrupted", run["error"])
                    self._persist(run)

    def reconcile(self, key):
        with self.store.lock:
            run = self.run(key)
            if run["status"] != "blocked":
                return run
            for n in run["nodes"].values():
                if n["status"] == "dispatching" and not n["task"]:
                    raise WorkbenchError("작업 제출 결과가 불확실합니다. 기존 작업을 확인해야 합니다. 다시 제출하지 않습니다.")
            # Re-observe linked tasks only. Failed tasks remain blocked; no retry.
            for n in run["nodes"].values():
                if n["task"] and n["status"] == "blocked":
                    n["status"] = "running"
                elif n["status"] == "skipped":
                    n["status"] = "pending"
            run["status"], run["error"] = "running", ""
            self._event(run, "reconciled", "기존 작업의 기록을 다시 확인합니다. 새 모델 호출·재제출 없음.")
            self._persist(run)
            self._advance(run, observe_only=True)
            return self.run(key)

    def tick(self):
        with self.store.lock:
            for key in self._doc("workbench-ledger", {"ids": []})["ids"]:
                run = self.run(key)
                if run["status"] in LIVE:
                    self._advance(run)

    def _advance(self, run, observe_only=False):
        if self.engine._stop.is_set() or self.engine._shutdown.is_set():
            return
        before = digest(run)
        old_status = run["status"]
        graph = run["snapshot"]["graph"]
        by_id = {n["id"]: n for n in graph["nodes"]}
        incoming = {e["to"]: e["from"] for e in graph["edges"]}
        for key in graph["order"]:
            n, state = by_id[key], run["nodes"][key]
            if state["status"] in ("succeeded", "blocked", "skipped", "cancelled"):
                continue
            source = run["nodes"].get(incoming.get(key))
            if source and source["status"] in ("blocked", "skipped", "cancelled"):
                state["status"], state["error"] = "skipped", "선행 노드의 결과를 확인하세요."
                continue
            if source and source["status"] != "succeeded":
                continue
            state["inputs"] = deepcopy(source["output"] if source else n["params"].get("text"))
            op = n["definition"]["spec"]["operation"]
            try:
                if op in ("implement", "requirements"):
                    if not state["task"]:
                        if observe_only:
                            raise WorkbenchError("재시작 전에 제출하지 않은 노드입니다. 새 실행 계획에서 시작하세요.")
                        self._dispatch(run, n, state, op)
                    task = self.engine._task(state["task"])
                    if observe_only and task.status in ("ready", "queued"):
                        raise WorkbenchError("기존 작업이 아직 실행되지 않았습니다. 작업창에서 계획과 범위를 확인한 뒤 직접 실행하세요.")
                    if task.status in ("blocked", "cancelled"):
                        raise WorkbenchError(task.blocked_reason or "연결된 작업이 취소됐습니다.")
                    if task.status in ("awaiting_approval", "done"):
                        state["output"] = self._task_output(task)
                        self._complete(run, key, state)
                    else:
                        state["status"] = "running"
                        state["progress"] = task.status
                elif op in ("test", "review", "approve"):
                    task = self.engine._task(state["inputs"]["task"])
                    state["task"] = task.id
                    if task.status in ("blocked", "cancelled"):
                        raise WorkbenchError(task.blocked_reason or "연결된 작업이 취소됐습니다.")
                    if op == "test":
                        qa = task.qa or {}
                        if qa.get("candidate_sha") != task.candidate_sha or qa.get("verdict") not in ("pass", "none"):
                            raise WorkbenchError("현재 후보와 일치하는 검증 통과 증거가 없습니다.")
                        state["output"] = self._task_output(task)
                        self._complete(run, key, state)
                    elif op == "review":
                        review = task.review or {}
                        if review.get("candidate_sha") != task.candidate_sha or review.get("verdict") != "approve":
                            raise WorkbenchError("현재 후보에 대한 검토 승인 증거가 없습니다. 기존 작업창에서 확인하세요.")
                        state["output"] = self._task_output(task)
                        self._complete(run, key, state)
                    elif task.status == "done":
                        state["output"] = self._task_output(task)
                        self._complete(run, key, state)
                    else:
                        state["status"] = "waiting"
                else:
                    text = state["inputs"]
                    if op == "input":
                        state["output"] = n["params"]["text"]
                    elif op == "format":
                        state["output"] = _text(n["params"]["prefix"] + text + n["params"]["suffix"], "정리된 입력", 4000, True)
                    elif op == "lines":
                        lines = [line.strip() for line in text.splitlines() if line.strip()]
                        if len(lines) > 200:
                            raise WorkbenchError("목록 정리는 200줄까지 처리할 수 있습니다.")
                        if n["params"]["dedupe"]:
                            lines = list(dict.fromkeys(lines))
                        if n["params"]["sort"]:
                            lines.sort()
                        state["output"] = "\n".join(lines)
                    elif op == "require_text":
                        if len(text) < n["params"]["min_length"] or n["params"]["contains"] not in text:
                            raise WorkbenchError("입력 조건을 만족하지 않습니다. 최소 길이와 필수 문구를 확인하세요.")
                        state["output"] = text
                    elif op == "summary":
                        state["output"] = {"result": text, "recorded_at": now_iso(), "model_used": False}
                    self._complete(run, key, state)
            except (ValueError, RuntimeError, OSError) as exc:
                state["status"], state["error"] = "blocked", str(exc)
                self._event(run, "node_blocked", str(exc), key)
        statuses = {n["status"] for n in run["nodes"].values()}
        run["status"] = "blocked" if "blocked" in statuses else "succeeded" if statuses == {"succeeded"} else "waiting" if "waiting" in statuses else "running"
        if run["status"] == "blocked":
            run["error"] = next(n["error"] for n in run["nodes"].values() if n["status"] == "blocked")
        if run["status"] != old_status:
            self._event(run, "status", f"작업대 {run['title']}: {NODE_LABELS.get(run['status'], run['status'])}")
        if digest(run) != before:
            self._persist(run)

    def _complete(self, run, key, state):
        if state["status"] != "succeeded":
            state["status"], state["completed_at"] = "succeeded", now_iso()
            self._event(run, "node_finished", "노드 처리 결과를 장부에 보관했습니다.", key)

    def _dispatch(self, run, n, state, op):
        from .supervisor import path_scope
        inputs = _text(state["inputs"], "작업 입력", 4000, True)
        snapshot = run["snapshot"]
        current = self.plan({"title": snapshot["title"], "graph": self.graph_only(snapshot["graph"]), "project": snapshot["project"], "allowed_paths": snapshot["allowed_paths"]})
        if current["hash"] != run["plan_hash"]:
            raise WorkbenchError("실행 확인 이후 프로젝트·모델·도구 설정이 바뀌었습니다. 새 계획을 확인하세요.")
        state["status"] = "dispatching"
        self._persist(run)  # A crash after this boundary must never create another task.
        marker = {"workflow_run": run["id"], "workflow_node": n["id"], "scope_paths": run["snapshot"]["allowed_paths"],
                  "workflow_no_retry": True,
                  "workflow_models": [{k: v for k, v in m.items() if k != "node"} for m in snapshot["models"] if m["node"] == n["id"]]}
        reviewer = next((m["role"] for m in marker["workflow_models"] if m["job"] == "reviewer"), None)
        marker["workflow_reviewer"] = reviewer
        prior = next((t for t in self.store.list() if t.extra.get("workflow_run") == run["id"] and t.extra.get("workflow_node") == n["id"]), None)
        if prior:
            task = prior
        elif op == "requirements":
            task = self.engine.submit_directive(inputs, run["snapshot"]["project"], created_by="workbench", extra=marker)
        else:
            task = self.engine.create_task({"title": n["definition"]["title"], "kind": "build", "project": run["snapshot"]["project"],
                                           "brief": inputs, "acceptance": n["params"]["acceptance"], "allowed_paths": run["snapshot"]["allowed_paths"]},
                                          created_by="workbench", extra=marker)
        task.role = marker["workflow_models"][0]["role"]
        self.store.save(task)
        if op == "implement" and any(not path_scope(p, marker["scope_paths"]) for p in task.allowed_paths):
            raise WorkbenchError("작업의 실제 허용 범위가 실행 계획과 다릅니다.")
        state["task"], state["status"] = task.id, "running"
        self._event(run, "task_linked", f"기존 작업 {task.id}에 연결했습니다.", n["id"])
        self._persist(run)
        if task.status in ("ready", "queued") and not task.run_requested:
            task.run_requested = True
            self.store.save(task)
            self.engine.wake()

    def halt(self, key):
        """Stop only future graph dispatch; already linked work keeps its existing controls."""
        with self.store.lock:
            run = self.run(key)
            if run["status"] not in LIVE | {"blocked"}:
                return run
            run["status"] = "cancelled"
            for state in run["nodes"].values():
                if state["status"] not in ("succeeded", "blocked"):
                    state["status"] = "cancelled"
            self._event(run, "halted", "후속 노드 진행을 중단했습니다. 이미 제출된 작업은 기존 작업창에서 따로 중단하세요.")
            self._persist(run)
            return run

    @staticmethod
    def _task_output(task):
        return {"task": task.id, "status": task.status, "candidate_sha": task.candidate_sha, "merged_sha": task.merged_sha,
                "report": task.report, "proposal": task.proposal, "qa": task.qa, "review": task.review,
                "runs": task.runs, "children": task.children, "history": task.history,
                "note": "기획 결재로 생성한 자식 카드는 진행판에서 별도로 확인하고 실행하세요." if task.kind == "plan" else ""}
