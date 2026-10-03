"""External supervisors: scoped capability tokens, no CEO approval/settings operations.

Disabled until the owner explicitly provisions data/supervisors.json. Only token
hashes are read here. Idempotency lives in the same atomic task record as the task.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import re
from . import evidence, gitops
from .checkpoints import digest
from .model import FINAL
from .util import read_json

NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
TASK = re.compile(r"^T[0-9]{4,12}$")
READ = {"status", "events", "result", "artifact"}


class AccessError(ValueError):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


def text(value, name, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise AccessError(name + " 값이 올바르지 않습니다.", 400)
    return value.strip()


def path_scope(pattern, roots):
    # Deliberately accepts only exact files or directory/** scopes; no glob algebra.
    if not isinstance(pattern, str) or not pattern or ":" in pattern or "\\" in pattern or pattern.startswith("/") or ".." in pattern.split("/"):
        return False
    for root in roots:
        if root == pattern:
            return True
        if root.endswith("/**") and pattern.startswith(root[:-2]) and not any(x in pattern[len(root)-2:] for x in ("[", "?")):
            return True
    return False


def requirements(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
        raise AccessError("수용 기준은 1~30개가 필요합니다.", 400)
    result, ids = [], set()
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"id", "text", "evidence"}:
            raise AccessError("수용 기준 형식 오류", 400)
        rid = text(item.get("id"), "기준 ID", 40)
        if not NAME.fullmatch(rid) or rid in ids:
            raise AccessError("기준 ID는 고유해야 합니다.", 400)
        ids.add(rid)
        refs = item.get("evidence", [])
        if not isinstance(refs, list) or len(refs) > 20:
            raise AccessError("근거 목록 형식 오류", 400)
        clean = []
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("type") not in ("test", "file", "screenshot", "source"):
                raise AccessError("근거 종류 오류", 400)
            kind = ref["type"]
            field = "name" if kind == "test" else "id" if kind == "source" else "path"
            if set(ref) != {"type", field}:
                raise AccessError("근거 필드 오류", 400)
            value = text(ref[field], "근거", 240)
            if field == "id" and not NAME.fullmatch(value):
                raise AccessError("출처 ID 오류", 400)
            clean.append({"type": kind, field: value})
        result.append({"id": rid, "text": text(item.get("text"), "수용 기준", 1000), "evidence": clean})
    return result


class Supervisor:
    def __init__(self, engine):
        self.engine, self.cfg, self.store = engine, engine.cfg, engine.store

    def authenticate(self, authorization):
        cfg = read_json(self.cfg.data_dir / "supervisors.json", {}) or {}
        if cfg.get("enabled") is not True:
            raise AccessError("외부 감독 연결이 꺼져 있습니다.", 404)
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise AccessError("외부 감독 인증이 필요합니다.", 401)
        token = authorization[7:]
        if not 32 <= len(token) <= 512:
            raise AccessError("외부 감독 인증 실패", 401)
        hashed = hashlib.sha256(token.encode()).hexdigest()
        clients = cfg.get("clients", [])
        if not isinstance(clients,list):raise AccessError("외부 감독 설정 오류",503)
        for client in clients:
            if isinstance(client, dict) and client.get("enabled") is True and hmac.compare_digest(str(client.get("token_sha256", "")), hashed):
                if not NAME.fullmatch(str(client.get("id", ""))) or not isinstance(client.get("projects"), dict):
                    break
                return client
        raise AccessError("외부 감독 인증 실패", 401)

    def call(self, authorization, request):
        try:
            actor = self.authenticate(authorization)
        except AccessError:
            self.store.event("supervisor.auth_denied","외부 감독 인증 거절")
            raise
        operation = request.get("operation") if isinstance(request, dict) else None
        try:
            result = self._call(actor, request)
        except (AccessError, ValueError) as exc:
            self.store.event("supervisor.denied", "외부 감독 요청 거절", actor=actor["id"], operation=operation if isinstance(operation,str) and operation in READ | {"submit", "cancel"} else "unknown")
            if isinstance(exc, AccessError): raise
            raise AccessError(str(exc), 400) from exc
        self.store.event("supervisor.request", "외부 감독 요청", actor=actor["id"], operation=operation, target=result.get("task", {}).get("id") if isinstance(result.get("task"),dict) else None)
        return result

    def _call(self, actor, request):
        if not isinstance(request, dict) or set(request) - {"operation", "project", "task", "key", "payload", "after", "path"}:
            raise AccessError("요청 형식 오류", 400)
        op = request.get("operation")
        if not isinstance(op,str) or op not in READ | {"submit", "cancel"}:
            raise AccessError("외부 감독은 승인·병합·권한·설정을 바꿀 수 없습니다.")
        key = text(request.get("project"), "프로젝트", 80)
        grant = actor["projects"].get(key)
        if not isinstance(grant, dict) or grant.get("read") is not True or key not in self.cfg.projects:
            raise AccessError("프로젝트 접근 권한이 없습니다.")
        if op not in READ and grant.get("write") is not True:
            raise AccessError("읽기 전용 연결입니다.")
        if op == "submit":
            return self._submit(actor, grant, key, request)
        tid = request.get("task")
        if not isinstance(tid, str) or not TASK.fullmatch(tid):
            raise AccessError("작업 ID 오류", 400)
        task = self.store.get(tid)
        if task is None or task.project != key:
            raise AccessError("접근 가능한 작업을 찾을 수 없습니다.", 404)
        if op == "cancel":
            if task.created_by != "supervisor:" + actor["id"]:
                raise AccessError("이 연결이 제출한 작업만 취소할 수 있습니다.")
            if task.status not in FINAL:
                task = self.engine.cancel(tid, by="supervisor:" + actor["id"])
        if op == "events":
            after = request.get("after", 0)
            if type(after) is not int or after < 0:
                raise AccessError("이벤트 위치 오류", 400)
            # Cursor is the position in this task's persisted log, stable across restarts.
            from .util import read_jsonl
            events = [e for e in read_jsonl(self.store.events_path) if e.get("task") == tid]
            rows = [{"cursor": i+1,"at":e.get("at"),"type":e.get("type"),"message":e.get("message")} for i,e in enumerate(events) if i >= after][:100]
            return {"events":rows,"next":rows[-1]["cursor"] if rows else after}
        if op == "artifact":
            rel = text(request.get("path"), "파일", 240)
            if not path_scope(rel, grant.get("paths", [])):
                raise AccessError("파일 접근 범위를 벗어났습니다.")
            if rel not in self._artifacts(task, grant):
                raise AccessError("검증한 결과 파일이 아닙니다.", 404)
            p = evidence.safe_file(self.store.qa_dir / task.qa["qa_id"] / "snapshot", rel)
            if p.stat().st_size > 1_000_000:
                raise AccessError("결과 파일이 1MB를 넘습니다.", 413)
            data = p.read_bytes()
            if len(data) > 1_000_000:
                raise AccessError("결과 파일이 1MB를 넘습니다.", 413)
            return {"path":rel,"sha256":hashlib.sha256(data).hexdigest(),"encoding":"base64","content":base64.b64encode(data).decode()}
        out = self.describe(task)
        if op == "result":
            out["artifacts"] = self._artifacts(task, grant)
            out["evidence"] = evidence.assess(self.cfg,self.store,task) if task.kind != "plan" else None
            if task.kind == "plan":out["proposal"] = task.proposal
            out["report"] = task.report
            out["runs"] = [{k:r.get(k) for k in ("run_id","stage","requested_provider","requested_model","actual_runtime","runtime_version","provider_model","model_identity","usage","duration_s","fallback","fallback_reason","error_kind")} for r in self.store.runs(tid)]
        return out

    def describe(self, task):
        coverage = evidence.assess(self.cfg,self.store,task) if task.kind in ("build","research") and task.qa else None
        validated = bool(coverage and coverage["suite_current"] and task.qa.get("verdict") == "pass"
                         and (not coverage["strict"] or coverage["complete"]))
        return {"task":{**task.summary(),"children":task.children},"progress":self.engine.journal.progress(task.id),
                "approval_required":task.status == "awaiting_approval", "approval_route":"CEO 대시보드 또는 짝지은 휴대폰",
                "blocked_reason":task.blocked_reason,"implemented":bool(task.candidate_sha),
                "validated":validated,"approved":task.status == "done"}

    def _artifacts(self, task, grant):
        if not task.candidate_sha or not task.qa or task.qa.get("candidate_sha") != task.candidate_sha:
            return []
        if not evidence.assess(self.cfg,self.store,task)["suite_current"]:
            return []
        stats = gitops.diff_numstat(self.cfg.projects[task.project].repo, task.base_sha, task.candidate_sha)
        result = []
        for row in stats:
            rel = row.get("path", "")
            if not path_scope(rel,grant.get("paths",[])):continue
            try:
                evidence.safe_file(self.store.qa_dir / task.qa["qa_id"] / "snapshot",rel)
            except (ValueError, KeyError):continue
            result.append(rel)
        return result

    def _submit(self, actor, grant, project, request):
        idem = text(request.get("key"), "요청 키", 120)
        payload = request.get("payload")
        if not isinstance(payload, dict) or set(payload)-{"kind","title","brief","allowed_paths","requirements","resources"}:
            raise AccessError("제출 내용에 허용되지 않은 필드가 있습니다.",400)
        kind = payload.get("kind", "build")
        if kind not in ("plan","build","research"):
            raise AccessError("지원하지 않는 작업 종류",400)
        title = text(payload.get("title"), "제목",80)
        brief = text(payload.get("brief", ""), "내용",4000,empty=True)
        reqs = requirements(payload.get("requirements"))
        paths = payload.get("allowed_paths",grant.get("paths",[]))
        if not isinstance(paths,list) or not paths or len(paths)>30 or not all(path_scope(p,grant.get("paths",[])) for p in paths):
            raise AccessError("수정 경로가 부여한 범위를 벗어났습니다.")
        for req in reqs:
            for ref in req["evidence"]:
                if "path" in ref and not path_scope(ref["path"],grant.get("paths",[])):
                    raise AccessError("근거 파일이 부여한 범위를 벗어났습니다.")
        resources = payload.get("resources",[])
        if not isinstance(resources,list) or len(resources)>10 or not all(isinstance(r,str) and NAME.fullmatch(r) for r in resources):
            raise AccessError("공유 자원 이름 오류",400)
        normalized = dict(project=project,kind=kind,title=title,brief=brief,allowed_paths=paths,requirements=reqs,resources=sorted(set(resources)))
        fingerprint = digest(normalized)
        keyhash = digest([actor["id"],project,idem])
        with self.store.lock:
            for existing in self.store.list():
                receipt = existing.extra.get("submission",{})
                if receipt.get("key_hash") == keyhash:
                    if receipt.get("digest") != fingerprint:
                        raise AccessError("같은 요청 키에 다른 내용이 제출됐습니다.",409)
                    return {**self.describe(existing),"replayed":True}
            extra = {"submission":{"key_hash":keyhash,"digest":fingerprint},"requirements":reqs,"resources":normalized["resources"],"scope_paths":paths}
            if kind == "plan":
                task = self.engine.submit_directive(brief or title,project,created_by="supervisor:"+actor["id"],extra=extra)
            else:
                data = dict(kind=kind,project=project,title=title,brief=brief,allowed_paths=paths,acceptance=[r["text"] for r in reqs])
                task = self.engine.create_task(data,created_by="supervisor:"+actor["id"],extra=extra)
                # Submitting does not silently authorize model usage; CEO's run/auto-run gate stays in force.
            return {**self.describe(task),"replayed":False}
