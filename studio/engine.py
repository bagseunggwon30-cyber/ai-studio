"""작업 흐름 엔진: 지시 → 기획 → 구현 → 신뢰 검증 → 리뷰 → 결재 → 병합.

- 독립 작업은 제한된 수만 병렬 실행하고 충돌 자원은 직렬화한다.
- 작업자는 작업별 git worktree 안에서만 쓴다. 허용 경로 밖 변경은 되돌린다.
- '완료'는 CEO 승인으로만 생긴다. 병합은 검증을 통과한 정확한 후보 커밋만 한다.
- 한도·로그인 문제는 추측해서 우회하지 않고 멈춘 뒤 사람에게 알린다.
"""

from __future__ import annotations

import shutil
from copy import deepcopy
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from . import ai, company, evidence, floors, gitops, login, mcp, projects, schedules, scheduler, skills, wardrobe
from .checkpoints import Journal, digest, files_digest, worktree_digest
from uuid import uuid4
from .config import JOBS, Config, ProjectConfig, staff_role
from .model import ACTIVE, FINAL, KIND_ROLE, NO_BRANCH, OPEN_BRANCH, Task, TransitionError
from .prompts import (PLAN_SCHEMA, REVIEW_SCHEMA, TOOL_SCHEMA, build_prompt, plan_prompt, reflect_prompt, review_prompt, skill_context,
                      tool_prompt, tool_review_prompt,
                      skill_prompt)
from .qa import run_qa, suite_hash
from .runtimes import ERROR_LABELS, RunResult, RunSpec, make_runtime, read_jsonl, summarize_codex_events
from .store import Store
from .workbench import Workbench
from .util import atomic_write_json, atomic_write_text, now_iso, read_json, stamp, today_str


class EngineError(ValueError):
    """CEO 요청을 처리할 수 없을 때 (화면에 그대로 보여준다)."""


RuntimeFactory = Callable[[str], Any]


class Engine:
    def __init__(self, cfg: Config, store: Store, runtime_factory: RuntimeFactory | None = None):
        self.cfg = cfg
        self.store = store
        self.runtime_factory = runtime_factory or (lambda name: make_runtime(name, cfg.runtimes, fake=cfg.fake_runtimes))
        self._thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._currents: dict[int, dict] = {}
        self._workers: dict[str, threading.Thread] = {}
        self._reservations: dict[str, float] = {}
        self._git_locks: dict[str, threading.RLock] = {}
        self.journal = Journal(store)
        self._cancel_task: str | None = None
        self.last_error: str | None = None
        self._tick_at = 0.0  # 업무 자동 시작을 마지막으로 본 때 (30초마다)
        # 한도·로그인으로 멈추면 로그인 창을 띄우는 함수 (serve가 진짜 회사에서만 넣는다 — 시험·연습용에서는 창을 띄우지 않는다)
        self.login_opener: Callable[[str], None] | None = None
        if store.get_state().get("stopped"):
            self._stop.set()
        # AI 탑재: studio.toml 값을 처음 값으로 기억하고, CEO가 바꿔 둔 AI(data/ai.json)를 끼운다
        self.ai_defaults = ai.apply_saved(cfg, store)
        self.workbench = Workbench(self)
        self._workbench_version = -1

    # ------------------------------------------------------------ 수명
    def start(self) -> None:
        self.recover()
        self._thread = threading.Thread(target=self._loop, name="studio-worker", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float | None = 10) -> bool:
        self._shutdown.set()
        self._wake.set()
        deadline = None if timeout is None else time.monotonic() + timeout
        if self._thread:
            self._thread.join(timeout)
        with self.store.lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.join(None if deadline is None else max(0, deadline-time.monotonic()))
        return not (self._thread and self._thread.is_alive()) and not any(w.is_alive() for w in workers)

    @property
    def _current(self):
        with self.store.lock:
            return self._currents.get(threading.get_ident())

    @_current.setter
    def _current(self, value):
        with self.store.lock:
            if value is None:
                self._currents.pop(threading.get_ident(), None)
            else:
                self._currents[threading.get_ident()] = value

    def _git_lock(self, project):
        with self.store.lock:
            return self._git_locks.setdefault(project, threading.RLock())

    def recover(self) -> None:
        # Keep fail-closed status. A person requests resume after inspecting the saved boundary.
        for t in self.store.list():
            if t.status not in ACTIVE:
                continue
            doc = self.journal.read(t.id)
            pending = [(k,v) for k,v in doc.items() if v.get("status") == "running"]
            uncertain = False
            for stage, saved in pending:
                receipt = read_json(self.store.runs_dir / saved.get("run_id", "missing") / "receipt.json", {}) or {}
                completed = receipt.get("input_digest") == saved.get("input_digest") and receipt.get("result",{}).get("ok") is True
                if completed:
                    self.journal.write(t.id,stage,**{k:v for k,v in receipt.items() if k != "updated_at"},status="complete")
                elif saved.get("effect") != "read_only":
                    uncertain = True
                    self.journal.write(t.id,stage,status="unknown_outcome",reason="server_restart",next_action="실행 여부 불확실: 작업 폴더와 외부 결과를 사람이 확인해야 합니다. 자동 재실행하지 않습니다.")
                else:
                    self.journal.write(t.id,stage,status="interrupted",reason="server_restart",next_action="재개하면 끝난 단계는 재사용하고 읽기 전용 단계부터 진행합니다.")
            pipe = doc.get("pipeline",{})
            if pipe.get("status") == "committing":
                # A commit without its durable SHA receipt is ambiguous, even with a clean tree.
                uncertain = True
                self.journal.write(t.id,"pipeline",status="unknown_outcome",reason="server_restart",next_action="후보 커밋 저장 도중 중단됨: Git 결과를 사람이 확인해야 합니다.")
            self.store.block(t, "실행 여부 불확실 — 결과 확인 전 재실행 금지" if uncertain else "서버 재시작으로 중단됐습니다. 저장된 단계에서 재개할 수 있습니다.")
        self.workbench.recover()

    def wake(self) -> None:
        self._wake.set()

    # ------------------------------------------------------------ 상태 조회
    def auto_run(self) -> bool:
        return bool(self.store.get_state().get("auto_run", self.cfg.auto_run))

    def status(self) -> dict[str, Any]:
        state = self.store.get_state()
        usage = self.store.today_usage()
        return {
            "stopped": self._stop.is_set(),
            "stop_reason": state.get("stop_reason") if self._stop.is_set() else None,
            "needs_login": state.get("needs_login") or None,  # 한도·로그인 만료로 멈춤: 화면이 '다른 아이디로 로그인' 창을 연다
            "auto_run": self.auto_run(),
            "current": self.current(),
            "active": list(self._currents.values()),
            "max_parallel": max(1,min(3,self.cfg.limit("max_parallel"))),
            "runtime_status": {"claude":"사용 불가 · Codex로 대체" if not self.cfg.runtime_cfg("claude").get("enabled",False) else "사용 설정됨", "grok_text":"읽기 전용 텍스트 · 매 실행 전 격리 점검"},
            "today": usage,
            "limits": {
                "max_runs_per_day": self.cfg.limit("max_runs_per_day"),
                "max_agent_minutes_per_day": self.cfg.limit("max_agent_minutes_per_day"),
                "max_attempts": self.cfg.limit("max_attempts"),
                "task_timeout_min": self.cfg.limit("task_timeout_min"),
            },
            "last_error": self.last_error,
        }

    def current(self) -> dict[str, Any] | None:
        with self.store.lock:
            cur = next((dict(c) for c in self._currents.values()), None)
        if not cur:
            return None
        run_dir = self.store.runs_dir / cur["run_id"]
        if cur.get("runtime") == "codex":
            steps, *_ = summarize_codex_events(read_jsonl(run_dir / "events.jsonl"))
            cur["steps"] = steps[-12:]
        return cur

    def waiting_reason(self, task: Task, tasks: list[Task]) -> str | None:
        if task.status != "ready":
            return None
        by_id = {t.id: t for t in tasks}
        for d in task.depends_on:
            dep = by_id.get(d)
            if dep is None or dep.status == "cancelled":
                return f"선행 작업 {d}이(가) 없거나 취소됨"
            if dep.status != "done":
                return f"선행 작업 {d} 완료 대기"
        resource_tasks = self._resource_tasks(tasks)
        resource_task = next((t for t in resource_tasks if t.id == task.id),task)
        blocked = scheduler.blocker(resource_task,resource_tasks,self._workers)
        if blocked:
            return f"같은 프로젝트의 {blocked} 처리 대기"
        if self._stop.is_set():
            return "회사가 정지 상태"
        if not (self.auto_run() or task.run_requested):
            return "실행 버튼을 누르면 시작 (자동 진행 꺼짐)"
        return "순서 대기"

    # ------------------------------------------------------------ CEO 행동
    def _project(self, key: str) -> ProjectConfig:
        project = self.cfg.projects.get(key)
        if not project:
            raise EngineError(f"알 수 없는 프로젝트: {key}")
        return project

    def _task(self, task_id: str) -> Task:
        task = self.store.get(task_id)
        if not task:
            raise EngineError(f"작업 {task_id}을(를) 찾을 수 없습니다.")
        return task

    def submit_directive(self, text: str, project_key: str, *, created_by="ceo", extra=None) -> Task:
        text = (text or "").strip()
        if not text:
            raise EngineError("지시 내용을 입력하세요.")
        if len(text) > 4000:
            raise EngineError("지시는 4000자 이내로 입력하세요.")
        self._project(project_key)
        first = text.splitlines()[0].strip()
        title = first if len(first) <= 60 else first[:57] + "…"
        task = self.store.create_task(
            title=title, kind="plan", role=self._pick("producer"), project=project_key, status="queued", brief=text, note="작업 지시", created_by=created_by, extra=extra or {}
        )
        self.wake()
        return task

    def study_skill(self, role: str, topic: str, project_key: str, target: str | None = None) -> Task:
        """스킬 공부 맡기기: 고른 직원이 주제를 공부해 스킬로 정리해 온다 (읽기 전용, CEO 승인 뒤에 배움).

        target: '더 좋게 고쳐 오기' — 이 스킬을 고쳐 온다 (주제는 비워도 된다).
        """
        topic = (topic or "").strip()
        if role not in self.cfg.roles:
            raise EngineError(f"알 수 없는 직원: {role}")
        old = None
        if target:
            try:
                old = skills.get(self.cfg, target)
            except skills.SkillError as e:
                raise EngineError(str(e)) from e
            topic = topic or f"'{old.title}' 스킬을 더 좋게 고쳐 줘. 틀린 곳은 바로잡고, 모자란 순서·확인 방법을 채운다."
        if not topic:
            raise EngineError("무엇을 공부할지 적어 주세요.")
        if len(topic) > 2000:
            raise EngineError("공부할 내용은 2000자 이내로 적어 주세요.")
        self._project(project_key)
        first = f"고쳐 오기: {old.title}" if old else topic.splitlines()[0].strip()
        title = first if len(first) <= 40 else first[:37] + "…"
        task = self.store.create_task(
            title=title, kind="skill", role=role, project=project_key, status="queued", brief=topic,
            target=old.slug if old else None, note="스킬 고쳐 오기" if old else "스킬 공부"
        )
        self.wake()
        return task

    def teach_skill(self, data: dict[str, Any]) -> skills.Skill:
        """CEO가 직접 가르친 스킬 (공부 없이 바로 저장)."""
        try:
            skill = skills.create(
                self.cfg,
                name=str(data.get("name") or data.get("title") or ""),
                title=str(data.get("title", "")),
                description=str(data.get("description", "")),
                body=str(data.get("body", "")),
                learned_by=data.get("learned_by") or [],
                source="ceo",
                projects=data.get("projects"),
                kinds=data.get("kinds"),
            )
        except skills.SkillError as e:
            raise EngineError(str(e)) from e
        self.store.event("skill.learned", f"스킬 등록: {skill.title}", skill=skill.slug, title=skill.title, roles=skill.learned_by)
        return skill

    def set_skill_scope(self, slug: str, projects: object, kinds: object) -> skills.Skill:
        """스킬을 쓰는 곳(프로젝트·일 종류)을 바꾼다. 비우면 모든 곳. 내용은 그대로라 판은 오르지 않는다."""
        for name, value in (("프로젝트", projects), ("일 종류", kinds)):
            if value is not None and not isinstance(value, list):
                raise EngineError(f"{name}는 목록으로 보내 주세요.")
        try:
            skill = skills.set_scope(self.cfg, slug, projects or [], kinds or [])
        except skills.SkillError as e:
            raise EngineError(str(e)) from e
        self.store.event("skill.scope", f"스킬 쓰는 곳 바꿈: {skill.title}", skill=skill.slug, title=skill.title,
                         projects=skill.projects, kinds=skill.kinds)
        return skill

    def set_skill_learned(self, slug: str, role: str, learned: bool) -> skills.Skill:
        try:
            skill = skills.set_learned(self.cfg, slug, role, learned)
        except skills.SkillError as e:
            raise EngineError(str(e)) from e
        verb = "배움" if learned else "잊음"
        self.store.event("skill.learned" if learned else "skill.forgot", f"{self.cfg.roles[role].title} {verb}: {skill.title}",
                         skill=skill.slug, title=skill.title, roles=[role])
        return skill

    # ------------------------------------------------------------ MCP 보관소 (왼쪽 서재)
    def mcp_action(self, name: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
        """MCP 보관소 바꾸기: equip(직원 장착·빼기) · enable(켜기·끄기) · secrets(토큰 넣기) · check(연결 확인) · remove(지우기).
        토큰 값은 기록에 남기지 않는다 (이름만)."""
        try:
            if action == "equip":
                role = str(body.get("role", ""))
                on = bool(body.get("on", True))
                item = mcp.set_equipped(self.cfg, name, role, on)
                who = self.cfg.roles[role].name if role in self.cfg.roles else role
                self.store.event("mcp.equipped", f"{who} {'장착' if on else '뺌'}: {item['title']}", mcp=name, role=role, on=on)
                return item
            if action == "enable":
                item = mcp.set_enabled(self.cfg, name, bool(body.get("on", True)))
                self.store.event("mcp.enabled", f"MCP {'켬' if item['enabled'] else '끔'}: {item['title']}", mcp=name, on=item["enabled"])
                return item
            if action == "secrets":
                values = body.get("values")
                if not isinstance(values, dict):
                    raise EngineError("토큰은 {이름: 값}으로 보내 주세요.")
                item = mcp.set_secrets(self.cfg, name, values)
                self.store.event("mcp.secrets", f"MCP 토큰 바꿈: {item['title']}", mcp=name, keys=sorted(str(k) for k in values))
                return item
            if action == "check":
                result = mcp.check(self.cfg, name)
                item = mcp.get(self.cfg, name)
                note = f"도구 {len(result['tools'])}개" if result["ok"] else "실패"
                self.store.event("mcp.checked", f"MCP 연결 확인: {item['title']} · {note}", mcp=name, ok=result["ok"])
                return item
            if action == "remove":
                item = mcp.remove(self.cfg, name)
                self.store.event("mcp.removed", f"MCP 지움: {item['title']}", mcp=name)
                return item
        except mcp.McpError as e:
            raise EngineError(str(e)) from e
        raise EngineError("없는 동작")

    def mcp_add(self, data: dict[str, Any]) -> dict[str, Any]:
        """바깥 MCP 등록 (CEO). 토큰은 data['env'] {이름: 값}으로 함께 받을 수 있다."""
        try:
            item = mcp.add(self.cfg, data)
        except mcp.McpError as e:
            raise EngineError(str(e)) from e
        self.store.event("mcp.added", f"MCP 등록: {item['title']}", mcp=item["name"], source=item["source"])
        return item

    def remove_skill(self, slug: str) -> None:
        try:
            skill = skills.remove(self.cfg, slug)
        except skills.SkillError as e:
            raise EngineError(str(e)) from e
        self.store.event("skill.removed", f"스킬 지움: {skill.title}", skill=slug)

    def create_task(self, data: dict[str, Any], *, created_by="ceo", extra=None) -> Task:
        kind = str(data.get("kind", "build"))
        if kind not in ("build", "research"):
            raise EngineError("작업 종류는 build 또는 research 입니다.")
        project = self._project(str(data.get("project", "")))
        title = str(data.get("title", "")).strip()[:80]
        if not title:
            raise EngineError("제목을 입력하세요.")
        allowed = _clean_paths(data.get("allowed_paths") or project.default_allowed_paths, project)
        if not allowed:
            raise EngineError("수정 허용 경로가 하나 이상 필요합니다.")
        acceptance = [str(x).strip() for x in data.get("acceptance") or [] if str(x).strip()]
        depends = [str(d) for d in data.get("depends_on") or [] if self.store.get(str(d))]
        task = self.store.create_task(
            title=title,
            kind=kind,
            role=self._pick(KIND_ROLE[kind]),
            project=project.key,
            status="ready",
            brief=str(data.get("brief", "")).strip(),
            acceptance=acceptance,
            allowed_paths=allowed,
            depends_on=depends,
            note="직접 만든 작업", created_by=created_by, extra=extra or {},
        )
        self.wake()
        return task

    def capture_source(self, task_id, source_id, url):
        import hashlib
        import re
        from .mcp_builtin.web import fetch
        if not isinstance(source_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",source_id):
            raise EngineError("출처 ID 오류")
        self._task(task_id)
        if not isinstance(url,str) or not 1 <= len(url) <= 2000:
            raise EngineError("출처 주소 오류")
        from .mcp_builtin.base import ToolError
        root = self.store.dir / "sources" / task_id
        try:
            text = fetch(url,50000)
        except ToolError as exc:
            atomic_write_json(root / (source_id+".json"),{"id":source_id,"url":url,"captured_at":now_iso(),"ok":False})
            self.store.event("source.failed","출처에 접근하지 못했습니다.",task=task_id,source=source_id)
            raise EngineError(str(exc)) from exc
        atomic_write_text(root / (source_id+".txt"),text)
        receipt = {"id":source_id,"url":url,"captured_at":now_iso(),"sha256":hashlib.sha256(text.encode()).hexdigest(),"ok":True}
        atomic_write_json(root / (source_id+".json"),receipt)
        self.store.event("source.captured","출처를 실제로 읽어 보관했습니다.",task=task_id,source=source_id)
        return receipt

    def request_run(self, task_id: str) -> Task:
        with self.store.lock:
            task = self._task(task_id)
            if task.status != "ready" and not (task.status == "queued" and (task.created_by.startswith("supervisor:") or task.extra.get("workflow_run"))):
                raise EngineError("준비 상태의 작업만 실행할 수 있습니다.")
            task.run_requested = True
            self.store.save(task)
        self.store.event("task.run_requested", f"{task.id} 실행 요청", task=task.id)
        self.wake()
        return task

    def approve(self, task_id: str, payload: dict[str, Any] | None = None, by: str = "ceo") -> Task:
        payload = payload or {}
        with self.store.lock:
            task = self._task(task_id)
            if task.status != "awaiting_approval":
                raise EngineError("결재 대기 중인 작업만 승인할 수 있습니다.")
            if task.kind == "plan":
                return self._approve_plan(task, payload, by)
            if task.kind == "skill":
                return self._approve_skill(task, payload, by)
            if task.kind == "look":
                return self._approve_look(task, payload, by)
            if task.kind == "hire":
                return self._approve_hire(task, payload, by)
            if task.kind == "tool":
                return self._approve_tool(task, payload, by)
            return self._merge(task, by)

    def request_changes(self, task_id: str, note: str, by: str = "ceo") -> Task:
        note = (note or "").strip()
        if not note:
            raise EngineError("무엇을 고칠지 적어 주세요.")
        with self.store.lock:
            task = self._task(task_id)
            if task.status != "awaiting_approval":
                if not task.needs_plan_input or by != "ceo":
                    raise EngineError("결재 대기 또는 CEO 답변이 필요한 기획만 수정할 수 있습니다.")
                if any(v.get("status") in ("unknown_outcome", "running") and v.get("effect") != "read_only"
                       for v in self.journal.read(task.id).values()):
                    raise EngineError("실행 여부 불확실: 결과 확인 전 다시 기획할 수 없습니다.")
            task.feedback.append({"at": now_iso(), "by": by, "text": note})
            task.attempts = 0
            self.journal.clear(task.id)
            task.run_requested = True
            if task.kind in NO_BRANCH:
                task.proposal = None
                self.store.save(task)
                note = {"plan": "기획 수정 요청", "skill": "다시 공부 요청", "look": "다시 만들기 요청",
                        "hire": "다시 그리기 요청", "tool": "다시 만들기 요청"}.get(task.kind, "수정 요청")
                self.store.transition(task, "queued", by=by, note=note)
            else:
                self.store.save(task)
                self.store.transition(task, "ready", by=by, note="수정 요청")
        self.wake()
        return task

    def merge_skill(self, task_id: str, into: str, by: str = "ceo") -> Task:
        """새 스킬 제안을 따로 저장하지 않고, 비슷한 기존 스킬에 합쳐 고쳐 오게 돌려보낸다 (스킬이 겹겹이 쌓이지 않게).

        정리해 왔던 내용은 CEO 의견으로 붙여 두고, target을 그 스킬로 바꿔 다시 공부(회고)한다. 돌아오면 그 스킬의 판이 오른다."""
        with self.store.lock:
            task = self._task(task_id)
            if task.kind != "skill" or task.status != "awaiting_approval":
                raise EngineError("결재를 기다리는 스킬 제안만 합칠 수 있습니다.")
            proposal = task.proposal or {}
            sk = proposal.get("skill") or {}
            if not sk:
                raise EngineError("합칠 내용이 없습니다.")
            try:
                old = skills.get(self.cfg, str(into or ""))
            except skills.SkillError as e:
                raise EngineError(str(e)) from e
            if proposal.get("action") == "update" and proposal.get("target") == old.slug:
                raise EngineError("이미 그 스킬을 고친 제안입니다. 그대로 승인하면 됩니다.")
            body = str(sk.get("body", ""))
            body = body if len(body) <= 3000 else body[:3000] + "\n…(뒤는 생략)"
            task.feedback.append({"at": now_iso(), "by": by, "text": (
                f"새 스킬로 따로 만들지 말고, 정리해 온 내용을 기존 스킬 '{old.title}'(`{old.slug}`)에 합쳐서 그 스킬을 고쳐 와 주세요. "
                f"겹치는 내용은 하나로 줄이고, 새로 알게 된 것만 더합니다.\n\n지난번에 정리해 온 내용:\n"
                f"제목: {sk.get('title', '')}\n언제 쓰나: {sk.get('description', '')}\n\n{body}")})
            task.target = old.slug
            task.attempts = 0
            task.run_requested = True
            task.proposal = None
            self.store.save(task)
            self.store.transition(task, "queued", by=by, note=f"비슷한 스킬에 합치기: {old.title}")
        self.wake()
        return task

    def retry(self, task_id: str, by: str = "ceo") -> Task:
        with self.store.lock:
            task = self._task(task_id)
            if task.status != "blocked":
                raise EngineError("막힘 상태의 작업만 재시도할 수 있습니다.")
            if any(t.extra.get("retargeted_from") == task.id for t in self.store.list()):
                raise EngineError("이미 새 대상의 카드가 있습니다. 작업 대상 변경으로 새 카드를 확인하세요.")
            if task.needs_plan_input:
                raise EngineError("질문에 답변한 뒤 '답변하고 다시 기획'을 선택하세요.")
            if task.kind != "skill":
                self._trouble(task, "blocked", task.blocked_reason or "")
            checkpoints = self.journal.read(task.id)
            if any(v.get("status") in ("unknown_outcome", "running") and v.get("effect") != "read_only" for v in checkpoints.values()):
                raise EngineError("실행 여부 불확실: 결과 확인 전 재실행할 수 없습니다. 작업 폴더와 외부 결과를 확인하세요.")
            resume_candidate = task.candidate_sha and checkpoints.get("pipeline",{}).get("candidate_sha") == task.candidate_sha
            finished_write = checkpoints.get(f"build{task.attempts}",{}).get("status") == "complete"
            if not resume_candidate and not finished_write:
                task.attempts = 0
                if task.kind not in NO_BRANCH: self.journal.clear(task.id)
            elif finished_write and not resume_candidate:
                task.attempts = max(0,task.attempts-1)
            task.run_requested = True
            if task.kind in NO_BRANCH:
                task.proposal = None
                self.store.save(task)
                self.store.transition(task, "queued", by=by, note="재시도")
            else:
                project = self._project(task.project)
                if task.base_sha and gitops.is_repo(project.repo):
                    main_head = gitops.head(project.repo, project.main_branch)
                    if main_head != task.base_sha:
                        pipe = checkpoints.get("pipeline",{})
                        if checkpoints and (not task.worktree or not gitops.is_clean(Path(task.worktree)) or pipe.get("files_digest") != worktree_digest(Path(task.worktree))):
                            raise EngineError("기준 커밋과 작업 폴더가 바뀌었습니다. 결과를 보존했습니다. 새 작업으로 검토하세요.")
                        self._discard_branch(task, project)
                        self.journal.clear(task.id)
                        task.attempts = 0
                self.store.save(task)
                self.store.transition(task, "ready", by=by, note="재시도")
        self.wake()
        return task

    def cancel(self, task_id: str, by: str = "ceo") -> Task:
        with self.store.lock:
            task = self._task(task_id)
            if task.status in FINAL:
                raise EngineError("이미 끝난 작업입니다.")
            running = task_id in self._workers or any(c.get("task") == task_id for c in list(self._currents.values()))
            if running:
                self.journal.write(task_id,"stop",status="cancelled",reason="cancelled",effect="read_only",next_action="취소된 작업은 다시 실행하지 않습니다.")
            self.store.transition(task, "cancelled", by=by, note="취소")
            if not running and task.kind not in NO_BRANCH:
                self._cleanup_worktree(task)
        return task

    def emergency_stop(self, reason: str = "CEO 긴급 정지") -> None:
        self._stop.set()
        self.store.update_state(stopped=True, stop_reason=reason)
        self.store.event("company.stopped", f"회사 정지: {reason}")

    def resume(self) -> None:
        self._stop.clear()
        self.store.update_state(stopped=False, stop_reason=None)
        self.store.event("company.resumed", "회사 재개")
        self.wake()

    def set_auto_run(self, enabled: bool) -> None:
        self.store.update_state(auto_run=bool(enabled))
        self.store.event("company.auto_run", f"자동 진행 {'켬' if enabled else '끔'}")
        self.wake()

    # ------------------------------------------------------------ AI 탑재
    def set_ai(self, role: str, data: dict[str, Any]) -> dict[str, str]:
        """직원에게 다른 AI를 끼운다 (다음 실행부터). 샌드박스·권한은 역할 그대로."""
        try:
            value = ai.save(self.cfg, self.store, self.ai_defaults, role, data)
        except ai.AIError as e:
            raise EngineError(str(e)) from e
        name = self.cfg.roles[role].name
        self.store.event("team.ai", f"{name} AI 탑재: {value['runtime']} {value['model'] or '기본'} {value['effort']}".strip(),
                         role=role, **value)
        return value

    def reset_ai(self, role: str) -> dict[str, str]:
        try:
            value = ai.reset(self.cfg, self.store, self.ai_defaults, role)
        except ai.AIError as e:
            raise EngineError(str(e)) from e
        self.store.event("team.ai", f"{self.cfg.roles[role].name} AI 처음대로", role=role, **value)
        return value

    # ------------------------------------------------------------ 직원 고르기 (같은 일을 하는 직원이 여럿일 때)
    def job_of(self, role: str) -> str:
        r = self.cfg.roles.get(role or "")
        return r.job_key if r else role

    def staff_for(self, job: str) -> list[str]:
        """이 일을 하는 직원 (기본 직원이 먼저)."""
        return [k for k, r in self.cfg.roles.items() if r.job_key == job]

    def _pick(self, job: str, prefer: str | None = None) -> str:
        """이 일을 맡을 직원: 정해 둔 사람이 그 일을 하면 그 사람, 아니면 맡은 일이 가장 적은 사람 (같으면 기본 직원)."""
        cands = self.staff_for(job) or [job]
        if prefer in cands:
            return str(prefer)
        load = {k: 0 for k in cands}
        for t in self.store.list():
            if t.role in load and t.status not in FINAL:
                load[t.role] += 1
        return min(cands, key=lambda k: (load[k], cands.index(k)))

    def _reviewer_for(self, task: Task) -> str:
        """리뷰 담당이 여럿이면 작업 번호로 돌아가며 맡는다 (같은 작업은 늘 같은 사람)."""
        cands = self.staff_for("reviewer") or ["reviewer"]
        if task.extra.get("workflow_reviewer") in cands:
            return task.extra["workflow_reviewer"]
        digits = "".join(ch for ch in task.id if ch.isdigit())
        return cands[int(digits or 0) % len(cands)]

    def assign(self, task_id: str, role: str) -> Task:
        """CEO가 담당을 바꾼다: 아직 시작하지 않았거나 막힌 작업만, 같은 일을 하는 직원에게만."""
        with self.store.lock:
            task = self._task(task_id)
            if task.status not in ("queued", "ready", "blocked"):
                raise EngineError("시작 전이거나 막힌 작업만 담당을 바꿀 수 있습니다.")
            if task.kind == "look":
                raise EngineError("새 옷은 입을 사람이 정해져 있어요.")
            if role not in self.cfg.roles:
                raise EngineError(f"알 수 없는 직원: {role}")
            if task.kind != "skill" and self.job_of(role) != self.job_of(task.role):
                raise EngineError(f"{self.cfg.roles[role].name}은(는) 이 일을 하지 않아요.")
            task.role = role
            self.store.save(task)
        self.store.event("task.assigned", f"{task.id} 담당: {self.cfg.roles[role].name}", task=task.id, role=role)
        return task

    def register_project(self, data: dict, *, by: str = "ceo") -> ProjectConfig:
        if by != "ceo":
            raise EngineError("프로젝트 등록은 CEO만 할 수 있습니다.")
        with self.store.lock:
            project = projects.register(self.cfg, data)
            self.store.event("project.registered", f"프로젝트 등록: {project.title}",
                             project=project.key, allowed_paths=project.default_allowed_paths,
                             automatic_qa=False, by=by)
        return project

    def retarget(self, task_id: str, data: dict, *, by: str = "ceo") -> Task:
        """Preserve old executions and move the instruction into a fresh, paused task."""
        if by != "ceo":
            raise EngineError("작업 대상 변경은 CEO만 할 수 있습니다.")
        with self.store.lock:
            source = self._task(task_id)
            target = self._project(str(data.get("project", "")))
            revision = data.get("revision")
            request_digest = digest(data)
            prior = next((t for t in self.store.list() if t.extra.get("retargeted_from") == source.id), None)
            if prior:
                if prior.project != target.key or prior.extra.get("retarget_request") != request_digest:
                    raise EngineError("이미 다른 대상으로 옮긴 작업입니다. 새 카드를 확인하세요.")
                # A crash between creating the copy and closing the source is recoverable.
                if source.status in ("queued", "ready", "blocked"):
                    self.store.transition(source, "cancelled", by=by, note=f"대상 변경: {prior.id}에 기록 보존")
                return prior
            if revision != digest(source.to_dict()):
                raise EngineError("작업 내용이 바뀌었습니다. 카드를 다시 열어 확인하세요.")
            if source.created_by.startswith("supervisor:"):
                raise EngineError("외부 감독의 프로젝트 권한은 옮길 수 없습니다. 허용된 대상으로 새 요청을 제출하세요.")
            if source.status not in ("queued", "ready", "blocked") or source.kind not in ("plan", "build", "research"):
                raise EngineError("시작 전이거나 막힌 기획·개발·리서치 작업만 대상을 바꿀 수 있습니다.")
            if source.project == target.key:
                raise EngineError("현재와 다른 프로젝트를 선택하세요.")
            if source.children or source.depends_on or source.extra.get("resources"):
                raise EngineError("연결된 작업이 있는 카드는 개별 이동할 수 없습니다. 새 지시로 기획하세요.")
            if source.candidate_sha or source.qa or source.review:
                raise EngineError("후보 변경·검증·리뷰가 있는 작업은 먼저 기존 결과를 검토하세요.")
            checkpoints = self.journal.read(source.id)
            if any(v.get("status") in ("unknown_outcome", "running", "committing") for v in checkpoints.values()):
                raise EngineError("실행 여부가 불확실한 기록이 있습니다. 결과 확인 전 대상을 바꿀 수 없습니다.")
            if source.worktree:
                wt = Path(source.worktree)
                if not wt.exists() or gitops.git(["status", "--porcelain", "--untracked-files=all"], wt).stdout.strip():
                    raise EngineError("기존 작업 폴더의 변경 파일을 먼저 검토하세요. 파일은 보존했습니다.")
                if source.base_sha and gitops.head(wt) != source.base_sha:
                    raise EngineError("기존 작업 폴더에 커밋이 있습니다. 결과를 먼저 검토하세요.")
            allowed = []
            if source.kind != "plan":
                from .supervisor import path_scope
                allowed = projects.path_list(data.get("allowed_paths"), target)
                if not all(path_scope(p, target.default_allowed_paths) for p in allowed):
                    raise EngineError("새 프로젝트에 등록된 수정 허용 범위를 벗어났습니다.")
            extra = {"retargeted_from": source.id, "source_revision": revision, "retarget_request": request_digest}
            if "requirements" in source.extra:
                extra["requirements"] = deepcopy(source.extra["requirements"])
            # Pause the source first: a crash during copy creation must not let the
            # original queued/ready task run automatically after restart.
            source = self.store.block(source, "대상 변경 중입니다. 중단되면 카드를 다시 열어 대상을 확인하세요.", by=by)
            moved = self.store.create_task(title=source.title, kind=source.kind, role=source.role,
                project=target.key, status="blocked", brief=source.brief, acceptance=source.acceptance.copy(),
                allowed_paths=allowed, difficulty=source.difficulty,
                blocked_reason="작업 대상이 변경됐습니다. 목표와 수정 범위를 확인한 뒤 재시도하세요.",
                extra=extra,
                note=f"{source.id}에서 대상 변경 · 기존 실행 근거는 복사하지 않음", created_by=by)
            self.store.transition(source, "cancelled", by=by, note=f"대상 변경: {moved.id}에 기록 보존")
            self.store.event("task.retargeted", f"{source.id} → {moved.id}: {target.title}", task=moved.id,
                             source=source.id, project=target.key, by=by)
            return moved

    # ------------------------------------------------------------ 스스로 배우기 (회고)
    def self_learning(self) -> bool:
        return bool(self.store.get_state().get("self_learning", True))

    def set_self_learning(self, enabled: bool) -> None:
        self.store.update_state(self_learning=bool(enabled))
        self.store.event("company.self_learning", f"스스로 배우기 {'켬' if enabled else '끔'}")

    def reflections_today(self, tasks: list[Task] | None = None) -> int:
        today = today_str()
        return sum(1 for t in (tasks if tasks is not None else self.store.list()) if t.origin and t.created_at.startswith(today))

    def _trouble(self, task: Task, kind: str, text: str) -> None:
        """일하다 걸린 일을 작업 카드에 적어 둔다 (끝난 뒤 회고 재료). 최근 12개만."""
        task.troubles = (task.troubles + [{"at": now_iso(), "kind": kind, "text": str(text)[:2000]}])[-12:]
        self.store.save(task)

    def _maybe_reflect(self, task: Task) -> list[Task]:
        """한 번에 안 풀린 작업이 CEO 승인으로 끝나면, 그 일을 한 직원이 돌아보고 스킬을 제안하게 한다.

        - 한 번에 안 풀림 = 걸린 일(검사 탈락·리뷰 수정 요청·오류·막힘)이 있었거나 CEO가 고쳐 달라고 했다.
        - 리뷰를 통과한 작업을 CEO가 고쳐 달라고 했으면 리뷰 담당도 돌아본다.
        - 스위치가 꺼져 있거나 오늘 횟수(max_auto_skills_per_day)를 다 썼으면 하지 않는다.
        - 회고는 새 스킬·고친 스킬을 '제안'만 한다. 배우는 것은 CEO 승인 뒤다.
        """
        if task.extra.get("workflow_no_retry") or task.kind not in ("plan", "build", "research") or not self.self_learning():
            return []
        ceo = any(f.get("by") == "ceo" for f in task.feedback)
        who = []
        if task.troubles or ceo:
            who.append(task.role or KIND_ROLE.get(task.kind, "builder"))
        if ceo and task.kind != "plan" and any("-review" in r for r in task.runs):
            who.append(str((task.review or {}).get("by") or "reviewer"))
        who = [r for r in dict.fromkeys(who) if r in self.cfg.roles]
        tasks = self.store.list()
        if not who or any(t.origin == task.id for t in tasks):
            return []
        left = max(0, self.cfg.limit("max_auto_skills_per_day") - self.reflections_today(tasks))
        title = f"회고: {task.title}"
        title = title if len(title) <= 40 else title[:39] + "…"
        made = [
            self.store.create_task(
                title=title, kind="skill", role=role, project=task.project, status="queued",
                brief=f"{task.id} '{task.title}'을 돌아보고 다음에 한 번에 해낼 요령을 스킬로 정리한다.",
                origin=task.id, created_by="system", note="스스로 돌아보기",
            )
            for role in who[:left]
        ]
        if len(made) < len(who):
            self.store.event("skill.reflect_skipped", f"{task.id} 오늘 회고 횟수를 다 써서 돌아보기를 건너뜀", task=task.id)
        if made:
            self.wake()
        return made

    # ------------------------------------------------------------ 작업자 루프
    def _loop(self) -> None:
        while not self._shutdown.is_set():
            if not self._stop.is_set():
                with self.store.lock:
                    if self._workbench_version != self.store.version:
                        try:
                            self.workbench.tick()
                        except (ValueError, OSError) as e:
                            self.last_error = f"작업대 기록 확인 실패: {e}"
                        self._workbench_version = self.store.version
                if time.monotonic()-self._tick_at > 30:
                    self._tick_at = time.monotonic()
                    try:
                        self.schedule_tick()
                    except Exception as e:
                        self.last_error = f"자동 업무 확인 실패: {e}"
                with self.store.lock:
                    if len(self._workers) < max(1,min(3,self.cfg.limit("max_parallel"))):
                        task = self._next_job()
                        if task:
                            worker = threading.Thread(target=self._work,args=(task,),name=f"studio-{task.id}",daemon=True)
                            self._workers[task.id] = worker
                            worker.start()
                            continue
            self._wake.wait(.2)
            self._wake.clear()

    def _work(self, task):
        try:
            run = {"plan": self._run_plan,"skill":self._run_skill,"look":self._run_look,"hire":self._run_hire,"tool":self._run_tool}.get(task.kind,self._run_build)
            run(task)
        except Exception as e:
            self.last_error = f"{task.id}: {e}"
            atomic_write_text(self.store.dir / "last_error.txt",traceback.format_exc())
            self.store.block(task,f"시스템 오류: {e}")
        finally:
            try:
                if self._cancelled(task.id) and task.kind not in NO_BRANCH:
                    fresh = self.store.get(task.id)
                    if fresh: self._cleanup_worktree(fresh)
            finally:
                with self.store.lock:
                    self._current = None
                    self._workers.pop(task.id,None)
                self.wake()

    def _resource_tasks(self, tasks):
        result = []
        for original in tasks:
            t = Task.from_dict(original.to_dict())
            specs = [] if self.cfg.roles.get(t.role) and self.cfg.roles[t.role].runtime == "grok_text" else mcp.for_role(self.cfg,t.role)
            # A completed worker no longer owns tools or external execution resources.
            # Awaiting candidates still reserve overlapping file paths via scheduler.blocker.
            resources = set() if t.status == "awaiting_approval" else set(t.extra.get("resources",[]))
            for spec in specs:
                if t.status != "awaiting_approval" and (spec.get("source") != "builtin" or spec.get("name") == "team-memory"):
                    resources.add("mcp:"+spec["name"])
            t.extra["resources"] = sorted(resources)
            t.extra["uncertain"] = t.status == "blocked" and any(v.get("status") == "unknown_outcome" for v in self.journal.read(t.id).values())
            result.append(t)
        return result

    def _next_job(self) -> Task | None:
        usage = self.store.today_usage()
        if usage["runs"] + len(self._reservations) >= self.cfg.limit("max_runs_per_day") or usage["minutes"] >= self.cfg.limit("max_agent_minutes_per_day"):
            return None
        tasks = self._resource_tasks(self.store.list())
        by_id = {t.id:t for t in tasks}
        for t in sorted(tasks,key=lambda x: bool(x.origin)):
            if t.id in self._workers or scheduler.blocker(t,tasks,self._workers):
                continue
            if t.extra.get("workflow_plan_child") and not t.run_requested:
                continue
            if t.status == "queued" and t.kind in NO_BRANCH:
                if t.extra.get("workflow_run") and not t.run_requested: continue
                if t.created_by.startswith("supervisor:") and not (t.run_requested or self.auto_run()):continue
                return self._task(t.id)
            if t.extra.get("workflow_run") and not t.run_requested: continue
            if t.status != "ready" or t.kind in NO_BRANCH or not (self.auto_run() or t.run_requested):continue
            if any(d not in by_id or by_id[d].status != "done" for d in t.depends_on):continue
            return self._task(t.id)
        return None

    def _should_stop(self, task_id: str) -> bool:
        return self._shutdown.is_set() or self._stop.is_set() or self._cancelled(task_id)

    def _cancelled(self, task_id: str) -> bool:
        fresh = self.store.get(task_id)
        return fresh is None or fresh.status == "cancelled"

    # ------------------------------------------------------------ 에이전트 1회 실행
    def _agent_run(self, task, role, prompt, cwd, **kwargs):
        stage = kwargs["stage"]
        self.workbench.check_task(task, role, stage)
        if self._should_stop(task.id):
            return RunResult(False,kwargs.get("runtime_name") or self.cfg.roles[role].runtime,kwargs.get("model") or self.cfg.roles[role].model,None,0,error_kind="stopped",error="중단됨")
        requested = kwargs.get("runtime_name") or self.cfg.roles[role].runtime
        requested_model = kwargs.get("model", self.cfg.roles[role].model)
        reported_provider = kwargs.pop("requested_provider", requested)
        reported_model = kwargs.pop("requested_model", requested_model)
        fallback = kwargs.pop("fallback_reason", None)
        if requested == "claude" and not self.cfg.runtime_cfg("claude").get("enabled",False):
            kwargs["runtime_name"] = "codex"
            kwargs["model"] = self.cfg.roles[role].fallback_model if self.cfg.roles[role].fallback_runtime == "codex" else ""
            kwargs["effort"] = ""
            fallback = "claude_disabled"
        if kwargs.get("sandbox") != "read-only" and (kwargs.get("runtime_name") or requested) not in ("codex","fake"):
            return RunResult(False,requested,requested_model,None,0,error_kind="policy",error="파일 변경 권한이 확인된 Codex 실행기만 사용할 수 있습니다.")
        text_runtime = (kwargs.get("runtime_name") or requested) == "grok_text"
        attached = [] if kwargs.get("want_image") or stage.startswith("review") or text_runtime else mcp.for_role(self.cfg,role)
        if text_runtime:kwargs["web_search"] = False
        effect = "external_effect" if kwargs.get("want_image") or any(m.get("source") != "builtin" or m.get("name") == "team-memory" for m in attached) else "read_only" if kwargs.get("sandbox") == "read-only" else "reversible"
        observation = None
        if kwargs.get("sandbox") == "read-only" and not kwargs.get("want_image"):
            observation = worktree_digest(Path(cwd)) if gitops.is_repo(Path(cwd)) else files_digest(Path(cwd))
        runtime = self.runtime_factory(kwargs.get("runtime_name") or requested)
        info = getattr(runtime,"info",{}) or {}
        if not isinstance(info,dict):info = {}
        runtime_id = getattr(runtime,"name",None)
        if not isinstance(runtime_id,str):runtime_id = kwargs.get("runtime_name") or requested
        identity = [type(runtime).__module__,type(runtime).__qualname__,runtime_id,info.get("cmd"),info.get("version"),self.cfg.fake_runtimes]
        image_inputs = [(str(p),digest(Path(p).read_bytes().hex())) for p in kwargs.get("images",[]) or []]
        key = digest([identity,image_inputs,kwargs.pop("resume_context",None),kwargs.get("effort"),kwargs.get("web_search"),attached,observation,prompt,str(Path(cwd).resolve()),kwargs.get("runtime_name",requested),kwargs.get("model",requested_model),kwargs.get("sandbox"),kwargs.get("schema"),task.base_sha,task.candidate_sha,task.attempts])
        saved = self.journal.read(task.id).get(stage,{})
        if saved.get("status") == "unknown_outcome":
            return RunResult(False,requested,requested_model,None,0,error_kind="unknown_outcome",error="실행 여부 불확실: 자동 재실행 금지")
        if saved.get("input_digest") == key and saved.get("status") == "complete":
            if saved.get("files_digest") is None or saved.get("files_digest") == worktree_digest(Path(cwd)):
                return RunResult(**saved["result"])
            raise EngineError("저장된 산출물이 변경돼 단계를 재사용할 수 없습니다.")
        kwargs["runtime_instance"] = runtime
        before = worktree_digest(Path(cwd)) if kwargs.get("sandbox") != "read-only" else None
        reservation = uuid4().hex
        with self.store.lock:
            usage = self.store.today_usage()
            budget = sum(self._reservations.values())
            if usage["runs"]+len(self._reservations) >= self.cfg.limit("max_runs_per_day") or usage["minutes"]+budget >= self.cfg.limit("max_agent_minutes_per_day"):
                return RunResult(False,requested,requested_model,None,0,error_kind="cap",error="실행 상한에 도달했습니다.")
            remaining = self.cfg.limit("max_agent_minutes_per_day")-usage["minutes"]-budget
            reserved_minutes = min(self.cfg.limit("task_timeout_min"),remaining)
            self._reservations[reservation] = reserved_minutes
        run_id = f"R{stamp()}-{uuid4().hex[:8]}-{task.id}-{stage}"
        kwargs["run_id"] = run_id
        kwargs["requested_provider"] = "grok" if reported_provider == "grok_text" else reported_provider
        kwargs["requested_model"] = reported_model
        kwargs["fallback_reason"] = fallback
        kwargs["timeout_s"] = max(1,int(reserved_minutes*60))
        try:
            self.journal.write(task.id,stage,status="running",input_digest=key,run_id=run_id,effect=effect,candidate_sha=task.candidate_sha,reason=None,next_action=None)
            result = self._agent_run_once(task,role,prompt,cwd,**kwargs)
            after = worktree_digest(Path(cwd)) if kwargs.get("sandbox") != "read-only" else None
            uncertain = not result.ok and ((effect != "read_only" and result.side_effects != "none") or after != before)
            reason = ("cancelled" if self._cancelled(task.id) else "server_shutdown" if self._shutdown.is_set() else "emergency_stop" if self._stop.is_set() else result.error_kind)
            receipt = dict(input_digest=key,run_id=run_id,effect=effect,candidate_sha=task.candidate_sha,result=result.to_dict(),files_digest=after,
                           reason=reason,next_action="실행 여부 불확실: 결과 확인 필요" if uncertain else "저장된 다음 단계에서 재개" if not result.ok else None)
            atomic_write_json(self.store.runs_dir / run_id / "receipt.json",receipt)
            self.journal.write(task.id,stage,**receipt,status="complete" if result.ok else "unknown_outcome" if uncertain else "failed")
            return result
        except Exception:
            self.journal.write(task.id,stage,status="interrupted" if effect == "read_only" else "unknown_outcome",reason="process_error",next_action="실제 결과를 확인한 뒤 재개")
            raise
        finally:
            with self.store.lock:
                self._reservations.pop(reservation,None)

    def _agent_run_once(
        self,
        task: Task,
        role: str,
        prompt: str,
        cwd: Path,
        *,
        sandbox: str,
        stage: str,
        schema: dict | None = None,
        runtime_name: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        web_search: bool = False,
        images: list[Path] | None = None,
        want_image: bool = False,
        skills_kind: str | None = None,
        skills_task: Task | None = None,
        run_id: str | None = None,
        runtime_instance=None,
        requested_provider: str | None = None,
        requested_model: str | None = None,
        fallback_reason: str | None = None,
        timeout_s: int | None = None,
    ) -> RunResult:
        """skills_kind: 이 실행이 배운 스킬을 '쓰는' 일이면 그 종류 (plan·build·research·review·study). 프롬프트가 고른 것과 같은
        스킬을 다시 골라 실행 기록에 남긴다 (skills = 본문까지 붙음, skills_brief = 설명만, skills_applied = 따랐다고 알린 것).
        None이면 스킬을 쓰는 일이 아니다 (그림) — 사용 기록에 넣지 않는다.
        skills_task: 프롬프트가 다른 작업의 글로 스킬을 골랐을 때 그 작업 (회고는 끝난 작업의 제목·목표로 고른다)."""
        rcfg = self.cfg.roles[role]
        runtime_name = runtime_name or rcfg.runtime
        model = rcfg.model if model is None else model
        effort = rcfg.effort if effort is None else effort
        if self._should_stop(task.id):
            return RunResult(False, runtime_name, model, None, 0.0, error_kind="stopped", error="중단됨")
        usage = self.store.today_usage()
        if usage["runs"] >= self.cfg.limit("max_runs_per_day") or usage["minutes"] >= self.cfg.limit("max_agent_minutes_per_day"):
            return RunResult(False, runtime_name, model, None, 0.0, error_kind="cap", error="하루 실행 상한에 도달했습니다.")
        run_id = run_id or f"R{stamp()}-{uuid4().hex[:8]}-{task.id}-{stage}"
        run_dir = self.store.runs_dir / run_id
        runtime = runtime_instance if runtime_instance is not None else self.runtime_factory(runtime_name)
        offered_full, offered_brief = ([], []) if skills_kind is None else skills.select(
            self.cfg, role, **skill_context(skills_task or task, skills_kind))
        # 장착한 MCP (MCP 보관소): 그림 그리기·리뷰에는 붙이지 않는다. 리뷰 담당은 mcp.for_role이 늘 빈 목록
        mcp_specs = [] if want_image or stage.startswith("review") or runtime_name == "grok_text" else mcp.for_role(self.cfg, role)
        if mcp_specs:
            prompt = f"{prompt}\n\n{mcp.prompt_block(mcp_specs)}"
        used_skills = [f"{sk.slug}@{sk.version}" for sk in offered_full]  # 프롬프트에 본문이 붙은 스킬
        started = now_iso()
        self._current = {
            "task": task.id,
            "title": task.title,
            "role": role,
            "role_title": rcfg.title,
            "runtime": runtime_name,
            "model": model or "기본",
            "stage": stage,
            "run_id": run_id,
            "started_at": started,
        }
        self.store.event("run.started", f"{task.id} {rcfg.title} 시작 · {runtime_name} {model}".strip(), task=task.id, run=run_id)
        spec = RunSpec(
            run_id=run_id,
            role=role,
            prompt=prompt,
            cwd=Path(cwd),
            run_dir=run_dir,
            sandbox=sandbox,
            model=model,
            effort=effort,
            timeout_s=timeout_s if timeout_s is not None else self.cfg.limit("task_timeout_min") * 60,
            output_schema=schema,
            web_search=web_search,
            skip_git_check=not gitops.is_repo(Path(cwd)),
            images=list(images or []),
            want_image=want_image,
            mcp=mcp_specs,
        )
        if self._should_stop(task.id):
            result = RunResult(False, runtime_name, model, None, 0.0, error_kind="stopped", error="중단됨")
        else:
            result = runtime.run(spec, lambda: self._should_stop(task.id))
        rec = {
            "run_id": run_id,
            "task": task.id,
            "role": role,
            "stage": stage,
            "runtime": runtime_name,
            "model": model or "기본",
            "requested_provider": requested_provider or runtime_name,
            "requested_model": requested_model or None,
            "actual_runtime": result.runtime,
            "runtime_version": (getattr(runtime,"info",{}).get("version") or None) if isinstance(getattr(runtime,"info",None),dict) else None,
            "provider_model": result.provider_model,
            "provider_model_source": result.provider_model_source,
            "model_identity_reason": ("response_metadata" if result.provider_model else
                "fake_runtime" if result.runtime == "fake" else
                "execution_failed_without_model_id" if not result.ok else "model_id_not_provided"),
            "model_identity": "확인됨" if result.provider_model else "확인 불가",
            "fallback": bool(fallback_reason) or runtime_name != ({"grok": "grok_text"}.get(requested_provider, requested_provider) or runtime_name),
            "fallback_reason": fallback_reason,
            "cost": None,
            "sandbox": sandbox,
            "started_at": started,
            "ended_at": now_iso(),
            "duration_s": result.duration_s,
            "ok": result.ok,
            "exit_code": result.exit_code,
            "error_kind": result.error_kind,
            "error": result.error[:500],
            "usage": result.usage,
            "skills": used_skills,
            "skills_brief": [f"{sk.slug}@{sk.version}" for sk in offered_brief],
            "mcp": [s["name"] for s in mcp_specs],  # 붙인 MCP 이름만 (토큰은 기록하지 않는다)
            "host_skills": result.host_skills,  # 회사 스킬이 아니라 이 PC 사용자의 개인 Codex 스킬을 열어 읽은 것
            # 직원이 따랐다고 알린 스킬 (알리지 않았으면 None — 모름)
            "skills_applied": None if skills_kind is None else skills.parse_applied(
                result.final_message, result.structured, [sk.slug for sk in offered_full + offered_brief]),
        }
        self.store.add_run(rec)
        atomic_write_json(run_dir / "meta.json", {**rec, "steps": result.steps, "warnings": result.warnings})
        with self.store.lock:
            fresh = self.store.get(task.id)
            if fresh:
                fresh.runs.append(run_id)
                self.store.save(fresh)
        verdict = "완료" if result.ok else ERROR_LABELS.get(result.error_kind or "error", result.error_kind or "실패")
        self.store.event("run.finished", f"{task.id} {rcfg.title} {verdict} ({result.duration_s:.0f}초)", task=task.id, run=run_id, ok=result.ok)
        return result

    def _fail_run(self, task: Task, run: RunResult, role: str) -> None:
        kind = run.error_kind or "error"
        who = self.cfg.roles[role].title
        cli = "codex login" if run.runtime == "codex" else "grok login" if run.runtime in ("grok","grok_text") else "claude auth login"
        reasons = {
            "login": f"{who}: 로그인이 필요합니다. 터미널에서 `{cli}`로 본인이 로그인한 뒤 재시도하세요.",
            "quota": f"{who}: 구독 사용 한도에 도달했습니다. 한도가 풀린 뒤 재개·재시도하세요. (API로 우회하지 않습니다)",
            "model": f"{who}: 모델을 쓸 수 없습니다 ({run.model}). studio.toml의 역할 모델을 확인하세요. — {run.error[:200]}",
            "timeout": f"{who}: 제한 시간({self.cfg.limit('task_timeout_min')}분)을 넘겨 중단했습니다. 작업을 더 작게 나누세요.",
            "certificate": f"{who}: 보안 인증서를 확인하지 못해 AI 연결을 중단했습니다. Windows 신뢰 인증서 또는 지정한 인증서 파일을 확인한 뒤 재시도하세요.",
            "stopped": "긴급 정지로 중단됐습니다.",
            "cap": "하루 실행 상한에 도달했습니다. 내일 재시도하거나 studio.toml [limits]를 조정하세요.",
            "not_found": f"{who}: CLI를 찾을 수 없습니다. 점검 화면을 확인하세요.",
        }
        self.store.block(task, reasons.get(kind, f"{who} 실행 실패: {run.error[:300]}"))
        if kind in ("quota", "login"):
            rt = login.login_runtime(run.runtime, self.cfg.roles[role].runtime if role in self.cfg.roles else "")
            self._need_login(rt, kind, task.id)
            self.emergency_stop("구독 사용 한도 도달 — 다른 아이디로 로그인하거나 한도가 풀리면 재개하세요" if kind == "quota"
                                else "로그인 필요 — 다시 로그인한 뒤 재개하세요")

    # ------------------------------------------------------------ 다른 아이디로 로그인 (한도·로그인 만료)
    STOP_REASONS = ("구독 사용 한도", "로그인 필요")
    BLOCK_REASONS = ("구독 사용 한도에 도달", "로그인이 필요합니다")

    def _need_login(self, runtime: str | None, kind: str, task_id: str) -> None:
        """로그인이 필요하다고 적어 두고, 로그인 창을 한 번만 띄운다 (같은 프로그램이면 이미 띄운 창을 또 띄우지 않는다)."""
        prev = self.store.get_state().get("needs_login") or {}
        info = {"runtime": runtime or "", "reason": kind, "at": now_iso(), "task": task_id,
                "opened": bool(prev.get("opened")) and prev.get("runtime") == runtime, "error": ""}
        if runtime and self.login_opener and not info["opened"]:
            try:
                self.login_opener(runtime)
                info["opened"] = True
            except Exception as e:  # 창을 못 띄워도 화면의 '로그인 창 열기'로 다시 할 수 있다
                info["error"] = str(e)[:300]
        self.store.update_state(needs_login=info)
        name = login.NAMES.get(runtime or "", runtime or "AI")
        self.store.event("company.needs_login", f"{name} {'사용 한도' if kind == 'quota' else '로그인 필요'} — 다른 아이디로 로그인해 주세요",
                         task=task_id, runtime=runtime, reason=kind)

    def open_login(self, runtime: str = "") -> dict[str, Any]:
        """CEO가 누른 '로그인 창 열기'. runtime을 안 주면 멈춘 프로그램."""
        info = dict(self.store.get_state().get("needs_login") or {})
        runtime = runtime or info.get("runtime") or "codex"
        if runtime not in login.NAMES:
            raise EngineError(f"로그인 창을 띄울 수 없는 실행기예요: {runtime}")
        if self.login_opener is None:  # 연습용·시험 회사: 진짜 계정을 로그아웃시키면 안 된다
            raise EngineError("연습용 회사에서는 로그인 창을 띄우지 않아요 (진짜 회사에서만 열려요).")
        try:
            self.login_opener(runtime)
        except login.LoginError as e:
            raise EngineError(str(e)) from e
        if info:
            self.store.update_state(needs_login={**info, "opened": True, "error": ""})
        self.store.event("company.login_opened", f"{login.NAMES[runtime]} 로그인 창을 열었어요", runtime=runtime)
        return {"runtime": runtime}

    def login_done(self, by: str = "ceo") -> dict[str, Any]:
        """CEO가 다른 아이디로 로그인했다: 표시를 지우고, 한도·로그인 때문에 멈췄으면 재개하고, 그 때문에 막힌 일을 다시 한다."""
        state = self.store.get_state()
        self.store.update_state(needs_login=None)
        if state.get("stopped") and str(state.get("stop_reason") or "").startswith(self.STOP_REASONS):
            self.resume()
        retried = []
        for t in self.store.list():
            if t.status == "blocked" and any(k in (t.blocked_reason or "") for k in self.BLOCK_REASONS):
                try:
                    self.retry(t.id, by=by)
                    retried.append(t.id)
                except (EngineError, TransitionError):
                    pass
        self.store.event("company.logged_in", f"다시 로그인했어요 — 다시 시작 (다시 하는 일 {len(retried)}개)", retried=retried)
        return {"retried": retried}

    # ------------------------------------------------------------ 기획
    def _run_plan(self, task: Task) -> None:
        project = self._project(task.project)
        role = task.role if self.job_of(task.role) == "producer" else self._pick("producer")
        task = self.store.transition(task, "running", note="기획 담당이 작업을 나누는 중")
        prompt = plan_prompt(self.cfg, task, project, self.store.list(), role)
        if task.extra.get("workflow_run"):
            prompt += "\n# 작업대에서 CEO가 확인한 허용 범위\n" + "\n".join(task.extra.get("scope_paths", []))
            prompt += "\n이 범위 밖의 작업은 제안하지 않는다. 결재 뒤 생성된 카드는 별도로 직접 실행한다.\n"
        cwd = project.repo if project.repo.exists() else self.cfg.root
        run = self._agent_run(task, role, prompt, cwd, sandbox="read-only", stage="plan", schema=PLAN_SCHEMA, skills_kind="plan")
        if self._cancelled(task.id):
            return
        task = self._task(task.id)
        if not run.ok:
            self._fail_run(task, run, role)
            return
        tasks, problems = validate_plan(run.structured or {}, project, self.cfg.limit("max_children_per_plan"))
        s = run.structured or {}
        task.proposal = {
            "summary": str(s.get("summary", ""))[:2000],
            "tasks": tasks,
            "risks": [str(x)[:300] for x in s.get("risks", [])][:10],
            "questions": [str(x)[:300] for x in s.get("questions", [])][:10],
            "problems": problems,
        }
        task.report = str(s.get("summary", ""))[:2000]
        self.store.save(task)
        if not tasks:
            questions = task.proposal["questions"]
            detail = "; ".join(problems[:5]) or (questions[0] if questions else task.report)
            self.store.block(task, "기획안 확인 필요: " + (detail or "작업 후보가 없습니다. 지시와 프로젝트를 확인하세요."))
            return
        self.store.transition(task, "awaiting_approval", note=f"기획안 결재 요청 · 작업 {len(tasks)}개")

    def _approve_plan(self, task: Task, payload: dict[str, Any], by: str) -> Task:
        items = (task.proposal or {}).get("tasks", [])
        selected = payload.get("selected")
        selected_set = {int(i) for i in selected} if isinstance(selected, list) else None
        edits = payload.get("edits") or {}
        project = self._project(task.project)
        index_to_id: dict[int, str] = {}
        if task.extra.get("workflow_no_retry"):
            from .supervisor import path_scope
            # Validate the whole selection before creating the first child card.
            for i, item in enumerate(items):
                if selected_set is not None and i not in selected_set:
                    continue
                allowed = _clean_paths(item.get("allowed_paths", []), project)
                if any(not path_scope(p, task.extra.get("scope_paths", [])) for p in allowed):
                    raise EngineError("기획안이 작업대에서 확인한 허용 경로를 벗어났습니다.")
        for i, item in enumerate(items):
            if selected_set is not None and i not in selected_set:
                continue
            edit = edits.get(str(i)) or {}
            title = str(edit.get("title") or item["title"]).strip()[:80]
            kind = item.get("kind", "build")
            allowed = _clean_paths(item.get("allowed_paths", []),project)
            child_extra = {}
            if task.created_by.startswith("supervisor:"):
                from .supervisor import path_scope
                allowed = [p for p in allowed if path_scope(p,task.extra.get("scope_paths",[]))]
                if not allowed: raise EngineError("외부 지시의 허용 경로를 벗어난 기획안입니다.")
                child_extra = {"requirements":task.extra.get("requirements",[]),"resources":task.extra.get("resources",[]),"scope_paths":task.extra.get("scope_paths",[])}
            child_extra["plan_item"] = i
            if task.extra.get("workflow_no_retry"):
                from .supervisor import path_scope
                if any(not path_scope(p, task.extra.get("scope_paths", [])) for p in allowed):
                    raise EngineError("기획안이 작업대에서 확인한 허용 경로를 벗어났습니다.")
                child_extra.update(workflow_no_retry=True, workflow_plan_child=True, scope_paths=task.extra.get("scope_paths", []))
            prior = next((t for t in self.store.list() if t.parent == task.id and t.extra.get("plan_item") == i),None)
            if prior:
                index_to_id[i] = prior.id
                continue
            child = self.store.create_task(
                title=title,
                kind=kind,
                role=self._pick(KIND_ROLE.get(kind, "builder")),
                project=task.project,
                status="ready",
                brief=str(edit.get("brief") or item.get("brief", "")),
                acceptance=list(item.get("acceptance", [])),
                allowed_paths=allowed,
                extra=child_extra,
                depends_on=[index_to_id[d] for d in item.get("depends_on", []) if d in index_to_id],
                difficulty=int(item.get("difficulty", 1)),
                parent=task.id,
                created_by=task.created_by if task.created_by.startswith("supervisor:") else "producer",
                note=f"{task.id} 기획안에서 생성",
            )
            index_to_id[i] = child.id
        if not index_to_id:
            raise EngineError("만들 작업을 하나 이상 선택하세요.")
        task.children = list(index_to_id.values())
        self.store.save(task)
        self.store.transition(task, "done", by=by, note=f"작업 {len(index_to_id)}개 생성")
        self._maybe_reflect(task)
        self.wake()
        return task

    # ------------------------------------------------------------ 스킬 공부 (Claude 스킬 방식)
    def _run_skill(self, task: Task) -> None:
        """스킬 공부 또는 회고(origin이 있으면): 읽기 전용으로 한 번 실행하고 스킬 제안을 받는다."""
        project = self._project(task.project)
        role = task.role if task.role in self.cfg.roles else KIND_ROLE["skill"]
        rcfg = self.cfg.roles[role]
        origin = self.store.get(task.origin) if task.origin else None
        if task.origin and origin is None:
            self.store.transition(task, "cancelled", note="돌아볼 작업을 찾지 못함")
            return
        what = "지난 작업을 돌아보는" if origin else "스킬을 공부하는"
        task = self.store.transition(task, "running", note=f"{rcfg.title}이 {what} 중")
        prompt = (reflect_prompt(self.cfg, task, origin, project, self.store.runs(origin.id)) if origin
                  else skill_prompt(self.cfg, task, project))
        cwd = project.repo if project.repo.exists() else self.cfg.root
        run = self._agent_run(task, role, prompt, cwd, sandbox="read-only", stage="retro" if origin else "skill",
                              schema=skills.SKILL_SCHEMA, web_search=rcfg.web_search and not origin, skills_kind="study",
                              skills_task=origin)
        if self._cancelled(task.id):
            return
        task = self._task(task.id)
        if not run.ok:
            self._fail_run(task, run, role)
            return
        result, problems = skills.from_study(self.cfg, run.structured, task.target or "")
        if not result:
            self.store.block(task, "공부한 내용을 스킬로 쓸 수 없습니다: " + "; ".join(problems))
            return
        if result["action"] == "new" and result["skill"]:
            # 새 스킬인데 이미 비슷한 스킬이 있으면 CEO에게 알린다 (새로 쌓기보다 고치는 편이 나을 수 있다)
            result["similar"] = skills.similar(self.cfg, result["skill"])
        task.proposal = {**result, "problems": problems}
        if result["action"] == "none":
            task.report = result["reason"]
            self.store.save(task)
            if origin:  # 돌아봤지만 배울 것이 없으면 조용히 끝낸다 (결재할 것 없음)
                self.store.transition(task, "cancelled", note=f"돌아봤지만 새로 배울 것 없음 · {result['reason'][:120]}")
                self.store.event("skill.reflected", f"{task.id} 회고: 새로 배울 것 없음", task=task.id, origin=origin.id)
            else:
                self.store.block(task, f"공부했지만 스킬로 정리할 것이 없다고 합니다: {result['reason']}")
            return
        sk = result["skill"]
        task.report = sk["description"]
        self.store.save(task)
        verb = "스킬 고침" if result["action"] == "update" else "스킬"
        self.store.transition(task, "awaiting_approval", note=f"{verb} 결재 요청 · {sk['title']}")

    def _approve_skill(self, task: Task, payload: dict[str, Any], by: str) -> Task:
        """CEO가 공부·회고해 온 스킬을 승인: 새 스킬이면 skills/에 저장하고, 고친 스킬이면 판을 올린다.

        배울 직원은 CEO가 고른다 (기본: 새 스킬은 공부한 직원, 고친 스킬은 이미 배운 직원 + 공부한 직원).
        """
        proposal = task.proposal or {}
        data = dict(proposal.get("skill") or {})
        edits = payload.get("edits") or {}
        for key in ("title", "description", "body"):
            if isinstance(edits.get(key), str) and edits[key].strip():
                data[key] = edits[key]
        chosen = payload.get("learned_by")
        chosen = chosen if isinstance(chosen, list) and chosen else None
        how = "reflect" if task.origin else "study"
        # 쓰는 곳: CEO가 고치면 그 값, 아니면 제안대로 (scope project = 이 작업의 프로젝트에서만)
        kinds = payload["kinds"] if isinstance(payload.get("kinds"), list) else data.get("kinds")
        if isinstance(payload.get("projects"), list):
            projects = payload["projects"]
        elif "scope" in data:
            projects = [task.project] if data.get("scope") == "project" and task.project else []
        else:
            projects = None
        old = None
        if proposal.get("action") == "update" and proposal.get("target"):
            try:
                old = skills.get(self.cfg, str(proposal["target"]))
            except skills.SkillError:
                old = None  # 그사이 지워졌으면 새 스킬로 저장한다
        try:
            if old:
                skill = skills.update(self.cfg, old.slug, title=data.get("title", ""), description=data.get("description", ""),
                                      body=data.get("body", ""), learned_by=chosen or [*old.learned_by, task.role],
                                      source=task.id, how=how, change=str(proposal.get("change") or ""),
                                      projects=projects, kinds=kinds)
            else:
                skill = skills.create(self.cfg, name=data.get("name", ""), title=data.get("title", ""),
                                      description=data.get("description", ""), body=data.get("body", ""),
                                      learned_by=chosen or [task.role], source=task.id, how=how,
                                      projects=projects or [], kinds=kinds or [])
        except skills.SkillError as e:
            raise EngineError(str(e)) from e
        task.report = skill.slug
        self.store.save(task)
        note = f"스킬 고침: {skill.title} v{skill.version}" if old else f"스킬 배움: {skill.title}"
        self.store.transition(task, "done", by=by, note=note)
        self.store.event("skill.learned", note, task=task.id, skill=skill.slug, title=skill.title,
                         roles=skill.learned_by, version=skill.version, updated=bool(old))
        return task

    # ------------------------------------------------------------ 업무 자동 시작 (벽시계)
    def add_schedule(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            item = schedules.add(self.cfg, data)
        except schedules.ScheduleError as e:
            raise EngineError(str(e)) from e
        self.store.event("schedule.added", f"자동 업무 만듦: {item['title']} · {schedules.describe(item)}", schedule=item["id"])
        return item

    def schedule_action(self, sid: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
        """enable(켜기·끄기) · remove(지우기) · run(지금 한 번 하기)."""
        try:
            if action == "enable":
                item = schedules.update(self.cfg, sid, enabled=bool(body.get("on", True)))
                self.store.event("schedule.enabled", f"자동 업무 {'켬' if item['enabled'] else '끔'}: {item['title']}", schedule=sid)
                return item
            if action == "remove":
                item = schedules.remove(self.cfg, sid)
                self.store.event("schedule.removed", f"자동 업무 지움: {item['title']}", schedule=sid)
                return item
            if action == "run":
                item = next((x for x in schedules.load(self.cfg) if x["id"] == sid), None)
                if not item:
                    raise EngineError("그런 자동 업무가 없어요.")
                if self._schedule_open(sid):
                    raise EngineError("이 자동 업무의 지난 일이 아직 안 끝났어요.")
                task = self._start_scheduled(item)
                return {**item, "last_task": task.id}
        except schedules.ScheduleError as e:
            raise EngineError(str(e)) from e
        raise EngineError("없는 동작")

    def _schedule_open(self, sid: str) -> list[Task]:
        return [t for t in self.store.list() if (t.extra or {}).get("schedule") == sid and t.status not in FINAL]

    def schedule_tick(self, now: Any = None) -> list[Task]:
        """때가 된 자동 업무를 시작한다. 긴급 정지 중·오늘 에너지를 다 쓴 때는 기다린다 (때를 넘겨도 한 번만 따라잡는다).
        지난 일이 아직 열려 있으면 이번 때는 건너뛴다 (쌓이지 않게)."""
        if self._stop.is_set():
            return []
        usage = self.store.today_usage()
        if usage["runs"] >= self.cfg.limit("max_runs_per_day") or usage["minutes"] >= self.cfg.limit("max_agent_minutes_per_day"):
            return []
        made = []
        # 마지막 실행 시각은 넘겨받은 때(now)로 적는다 (운영에서는 now가 없어 지금 시각) — 시험이 진짜 시계에 따라 달라지지 않게
        stamp = now.astimezone().isoformat(timespec="seconds") if now is not None else now_iso()
        for item in schedules.load(self.cfg):
            if not schedules.is_due(item, now):
                continue
            if self._schedule_open(item["id"]):
                schedules.update(self.cfg, item["id"], last_run=stamp)
                self.store.event("schedule.skipped", f"자동 업무 건너뜀 (지난 일이 아직 안 끝남): {item['title']}", schedule=item["id"])
                continue
            try:
                made.append(self._start_scheduled(item, stamp))
            except EngineError as e:  # 프로젝트가 없어지는 등: 끄고 알린다
                schedules.update(self.cfg, item["id"], enabled=False, last_run=stamp)
                self.store.event("schedule.failed", f"자동 업무를 시작하지 못해 껐어요: {item['title']} · {e}", schedule=item["id"])
        return made

    def _start_scheduled(self, item: dict[str, Any], stamp: str = "") -> Task:
        project = self._project(item["project"])
        note = f"자동 시작 · {item['title']} ({schedules.describe(item)})"
        if item["kind"] == "research":
            allowed = _clean_paths(["reports/**"], project) or _clean_paths(project.default_allowed_paths, project)
            task = self.store.create_task(
                title=item["title"], kind="research", role=self._pick("analyst"), project=project.key, status="ready",
                brief=item["text"], acceptance=["출처(링크)가 달린 보고서를 쓴다"], allowed_paths=allowed, run_requested=True,
                extra={"schedule": item["id"]}, created_by="schedule", note=note,
            )
        else:
            task = self.store.create_task(
                title=item["title"], kind="plan", role=self._pick("producer"), project=project.key, status="queued",
                brief=item["text"], extra={"schedule": item["id"]}, created_by="schedule", note=note,
            )
        schedules.update(self.cfg, item["id"], last_run=stamp or now_iso(), last_task=task.id)
        self.store.event("schedule.started", f"자동 업무 시작: {item['title']}", task=task.id, schedule=item["id"], title=item["title"])
        self.wake()
        return task

    # ------------------------------------------------------------ MCP 만들기 (직원이 도구를 만든다)
    TOOL_TRIES = 2  # 리뷰에서 반려되면 한 번 더 고쳐 온다

    def order_tool(self, role: str, request: str, project_key: str, target: str | None = None) -> Task:
        """MCP 만들기 맡기기: 직원이 표준 라이브러리 한 파일짜리 MCP 서버를 써 오면 → 리뷰 담당이 읽고 → CEO가 승인하면 보관소에 꽂는다.
        target: 직원이 만든 도구 '고쳐 오기' (요청은 비워도 된다). 코드는 승인 전에는 실행하지 않는다."""
        request = (request or "").strip()
        if role not in self.cfg.roles:
            raise EngineError(f"알 수 없는 직원: {role}")
        if not mcp.can_equip(self.cfg, role):
            raise EngineError("리뷰 담당은 도구를 만들지 않아요 (만든 도구를 읽고 확인해요).")
        old = None
        if target:
            try:
                old = mcp.get(self.cfg, target)
            except mcp.McpError as e:
                raise EngineError(str(e)) from e
            if old["source"] != "staff":
                raise EngineError("직원이 만든 도구만 고쳐 오게 할 수 있어요.")
            request = request or f"'{old['title']}' 도구를 더 좋게 고쳐 줘. 틀린 곳은 바로잡고, 모자란 도구·설명을 채운다."
        if not request:
            raise EngineError("어떤 도구를 만들지 적어 주세요.")
        if len(request) > 2000:
            raise EngineError("요청은 2000자 이내로 적어 주세요.")
        self._project(project_key)
        first = f"도구 고치기: {old['title']}" if old else request.splitlines()[0].strip()
        task = self.store.create_task(
            title=first if len(first) <= 40 else first[:37] + "…", kind="tool", role=role, project=project_key, status="queued",
            brief=request, target=old["name"] if old else None, note="도구 고치기" if old else "MCP 만들기",
        )
        self.wake()
        return task

    def _run_tool(self, task: Task) -> None:
        """직원이 코드를 JSON으로 써 오고(읽기 전용) → 엔진이 문법만 보고 → 리뷰 담당이 읽는다. 반려되면 한 번 더.
        두 번 모두 반려되거나 리뷰를 못 하면 막힘 (코드가 이 PC에서 돌게 되므로 리뷰 없이 올리지 않는다)."""
        project = self._project(task.project)
        role = task.role if task.role in self.cfg.roles else KIND_ROLE["tool"]
        rcfg = self.cfg.roles[role]
        cwd = project.repo if project.repo.exists() else self.cfg.root
        task = self.store.transition(task, "running", note=f"{rcfg.title}이 도구를 만드는 중")
        for attempt in range(1, self.TOOL_TRIES + 1):
            task.attempts = attempt
            self.store.save(task)
            prompt = tool_prompt(self.cfg, task, mcp.staff_code(self.cfg, task.target or ""))
            run = self._agent_run(task, role, prompt, cwd, sandbox="read-only", stage=f"tool{attempt}", schema=TOOL_SCHEMA,
                                  web_search=rcfg.web_search, skills_kind="tool")
            if self._cancelled(task.id):
                return
            task = self._task(task.id)
            if not run.ok:
                self._fail_run(task, run, role)
                return
            proposal, problems = mcp.clean_tool(self.cfg, run.structured, task.target or "")
            if not proposal:
                self._trouble(task, "error", "; ".join(problems))
                if attempt < self.TOOL_TRIES:
                    task.feedback.append({"at": now_iso(), "by": "system", "text": "지난번 결과를 쓸 수 없었다: " + "; ".join(problems)})
                    self.store.save(task)
                    continue
                self.store.block(task, "만든 도구를 쓸 수 없습니다: " + "; ".join(problems))
                return
            flags = mcp.scan_code(proposal["code"])
            review = self._review_tool(task, proposal, flags, cwd)
            if self._cancelled(task.id):
                return
            task = self._task(task.id)
            task.review = review
            if review["verdict"] == "approve":
                task.proposal = {**proposal, "flags": flags, "problems": problems}
                task.report = proposal["description"] or proposal["title"]
                self.store.save(task)
                self.store.transition(task, "awaiting_approval", note=f"도구 결재 요청 · {proposal['title']}")
                return
            if review["verdict"] == "stopped" or self._should_stop(task.id):
                self.store.block(task, "긴급 정지로 리뷰가 멈췄습니다.")
                return
            if review["verdict"] == "unavailable":
                self.store.block(task, review["summary"])
                return
            self._trouble(task, "review", review["summary"])
        self.store.block(task, f"리뷰를 {self.TOOL_TRIES}번 통과하지 못했어요: {(task.review or {}).get('summary', '')}"[:600])

    def _review_tool(self, task: Task, proposal: dict[str, Any], flags: list[str], cwd: Path) -> dict[str, Any]:
        reviewer = self._reviewer_for(task)
        rcfg = self.cfg.roles[reviewer]
        prompt = tool_review_prompt(self.cfg, task, proposal, flags, reviewer)
        chain = [(rcfg.runtime, rcfg.model, rcfg.effort)] + ([(rcfg.fallback_runtime, rcfg.fallback_model, "")] if rcfg.fallback_runtime else [])
        errors = []
        failure = None
        for index, (runtime_name, model, effort) in enumerate(chain):
            run = self._agent_run(task, reviewer, prompt, cwd, sandbox="read-only", stage="review", schema=REVIEW_SCHEMA,
                                  runtime_name=runtime_name, model=model, effort=effort, skills_kind="review",
                                  requested_provider=rcfg.runtime, requested_model=rcfg.model,
                                  fallback_reason=failure if index else None)
            if run.error_kind == "stopped":
                return {"verdict": "stopped", "summary": "중단됨", "findings": [], "runtime": runtime_name}
            s = run.structured or {}
            if run.ok and s.get("verdict") in ("approve", "changes_requested"):
                findings = [f for f in s.get("findings", []) if isinstance(f, dict)][:30]
                blocking = any(f.get("severity") == "blocking" for f in findings)
                return {"verdict": "changes_requested" if blocking else s["verdict"], "by": reviewer, "summary": str(s.get("summary", ""))[:3000],
                        "findings": findings,
                        "runtime": "codex" if runtime_name == "claude" and not self.cfg.runtime_cfg("claude").get("enabled",False) else runtime_name,
                        "actual_runtime": run.runtime, "model": run.provider_model,
                        "model_identity": "확인됨" if run.provider_model else "확인 불가", "at": now_iso()}
            errors.append(f"{run.runtime}: {run.error or '응답 형식 오류'}"[:300])
            failure = f"{runtime_name}:{run.error_kind or 'schema'}"
        return {"verdict": "unavailable", "summary": "리뷰 실행기를 쓸 수 없어 도구를 올리지 않았어요 (리뷰 없이 이 PC에서 돌릴 수 없음). " + " / ".join(errors),
                "findings": [], "runtime": None, "at": now_iso()}

    def _approve_tool(self, task: Task, payload: dict[str, Any], by: str) -> Task:
        """CEO 승인: 보관소에 꽂고(data/mcp/servers/<이름>/) 장착할 직원을 정한 뒤, 한 번 띄워 연결을 확인한다 (여기서 처음 실행)."""
        proposal = task.proposal or {}
        if not proposal.get("code"):
            raise EngineError("설치할 코드가 없습니다.")
        chosen = payload.get("equip")
        roles = [str(r) for r in chosen] if isinstance(chosen, list) else [task.role]
        try:
            item = mcp.install_staff(self.cfg, proposal, task.id, roles)
        except mcp.McpError as e:
            raise EngineError(str(e)) from e
        result = mcp.check(self.cfg, item["name"])
        task.report = item["name"]
        self.store.save(task)
        note = f"도구 설치: {item['title']}" + ("" if result["ok"] else " (연결 확인 실패)")
        self.store.transition(task, "done", by=by, note=note)
        self.store.event("mcp.added", f"MCP 설치: {item['title']} · " + (f"도구 {len(result['tools'])}개" if result["ok"] else "연결 안 됨"),
                         task=task.id, mcp=item["name"], source="staff", ok=result["ok"])
        return task

    # ------------------------------------------------------------ 의상 제조실 (그림 생성)
    def order_outfit(self, role: str, label: str, desc: str, kind: str = "outfit", draw: str = "codex") -> Task:
        """꾸미기 주문 (꾸미기 공방): 지금 입은 모습에서 한 가지(옷·체형·머리 모양·안경·소품·표정)만 바꾼 그림 3장을 그려
        자른 뒤 결재에 올린다 (승인하면 꾸미기에 새 모습이 생긴다). 그래서 여름 옷 + 안경처럼 겹쳐 쌓인다."""
        if role not in self.cfg.roles:
            raise EngineError(f"알 수 없는 직원: {role}")
        r = self.cfg.roles[role]
        kind = wardrobe.kind_of(kind)
        label = wardrobe.one_line(label, wardrobe.MAX_LABEL)
        desc = wardrobe.one_line(desc, wardrobe.MAX_DESC)
        if not label or not desc:
            raise EngineError("이름과 어떻게 바꿀지 적어 주세요.")
        worn = company.looks(self.cfg, self.store).get(role, {}).get("style", "base")
        base = worn if worn and worn != "base" else None
        try:
            wardrobe.sources(self.cfg, r.character, base)
        except wardrobe.WardrobeError as e:
            raise EngineError(str(e)) from e
        what = wardrobe.KINDS[kind]["label"]
        task = self.store.create_task(
            title=f"{r.name} 새 {what}: {label}", kind="look", role=role, project="", status="queued", brief=desc,
            extra={"character": r.character, "label": label, "look_kind": kind, "base": base, "draw": wardrobe.draw_ai(draw)},
            note=f"꾸미기 주문 ({what}, {wardrobe.DRAW_AIS[wardrobe.draw_ai(draw)]})",
        )
        task.extra["set"] = f"{r.character}-{task.id.lower()}"
        self.store.save(task)
        self.wake()
        return task

    def _run_look(self, task: Task) -> None:
        ex = dict(task.extra or {})
        c, set_name = str(ex.get("character", "")), str(ex.get("set", ""))
        role = task.role if task.role in self.cfg.roles else "builder"
        d = wardrobe.job_dir(self.cfg, task.id)
        raw = d / "raw"
        if raw.exists():
            shutil.rmtree(raw)  # 다시 만들기: 새로 그린다
        raw.mkdir(parents=True)
        kind, base = wardrobe.kind_of(ex.get("look_kind")), ex.get("base") or None
        task = self.store.transition(task, "running", note=f"꾸미기 공방에서 새 {wardrobe.KINDS[kind]['label']} 그리는 중")
        try:
            src = wardrobe.sources(self.cfg, c, base)
        except wardrobe.WardrobeError as e:
            self.store.block(task, str(e))
            return
        looks_cfg = self.cfg.root / "tools" / "sprites" / "look-sets.json"
        described = (read_json(looks_cfg, {}) or {}).get("characters", {}).get(c) or self.cfg.roles[role].name
        notes = [f["text"] for f in task.feedback if f.get("by") == "ceo"]
        want = task.brief + (f" (CEO note: {notes[-1]})" if notes else "")
        body, walk = self.cfg.root / src["body"]["file"], self.cfg.root / src["walk"]["file"]
        ok, log = wardrobe.face_ref(self.cfg, c, raw / "face-ref.png", base)
        if not ok:
            self.store.block(task, f"얼굴 참고 그림을 만들지 못했어요: {log[-300:]}")
            return
        # 결과 파일 이름은 기본 시트 이름으로 (자르기 설정이 그 이름을 찾는다)
        plain = wardrobe.base_sources(self.cfg, c)
        sheet_out, walk_out = raw / Path(plain["body"]["file"]).name, raw / Path(plain["walk"]["file"]).name
        steps = [
            ("sheet", wardrobe.sheet_prompt(described, want, kind), [body], sheet_out),
            ("walk", wardrobe.walk_prompt(described, want, kind), [walk, sheet_out], walk_out),
            ("face", wardrobe.face_prompt(described, want, kind), [raw / "face-ref.png", sheet_out], raw / "portraits.png"),
        ]
        if not self._draw(task, role, "look", steps):
            return
        task = self.store.transition(self._task(task.id), "checking", note="새 모습 그림을 자르는 중")
        ok, msg = wardrobe.process(self.cfg, c, set_name, task.id, base, kind)
        if self._cancelled(task.id):
            return
        task = self._task(task.id)
        if not ok:
            self.store.block(task, f"그림을 자르지 못했어요 ({msg}). 재시도하면 새로 그립니다.")
            return
        who = f"{c}@{set_name}"
        task.proposal = {"character": c, "set": set_name, "label": ex.get("label", ""), "kind": kind, "base": base,
                         "preview": {"step": f"{who}.step.strip.png", "celebrate": f"{who}.celebrate.strip.png",
                                     "walk": f"{who}.walk.strip.png", "face": f"portraits@{set_name}.png"}}
        self.store.save(task)
        self.store.transition(task, "awaiting_approval", note=f"새 모습 결재 요청 · {ex.get('label', '')}")

    def _draw(self, task: Task, role: str, prefix: str, steps: list[tuple[str, str, list[Path], Path]]) -> bool:
        """그림 생성 여러 장 (본인 구독의 Codex, 또는 CEO가 고르면 Grok): 한 장씩 그려 target(PNG)에 둔다.
        실패·취소면 False (막힘은 여기서 처리)."""
        ai_name = wardrobe.draw_ai((task.extra or {}).get("draw"))
        codex = ai_name == "codex"
        for stage, prompt, images, target in steps:
            run = self._agent_run(task, role, prompt, self.cfg.root, sandbox="read-only", stage=f"{prefix}-{stage}",
                                  runtime_name=ai_name, model=wardrobe.IMAGE_MODEL if codex else "",
                                  effort=wardrobe.IMAGE_EFFORT if codex else "", images=images, want_image=True,resume_context=str(target.resolve()))
            if self._cancelled(task.id):
                return False
            task = self._task(task.id)
            if not run.ok or not run.images:
                self._fail_run(task, run, role)
                return False
            ok, log = wardrobe.to_png(self.cfg, Path(run.images[0]), target)
            if not ok:
                self.store.block(task, f"그림을 PNG로 바꾸지 못했어요: {log[-300:]}")
                return False
            if self.cfg.fake_runtimes and run.runtime == "fake":
                # 연습용(--fake) 회사에서만: 가짜 실행기는 지금 모습을 돌려줄 뿐이라, 옷 색을 돌려 새 옷처럼 보이게 한다.
                # 진짜 Codex·Grok 그림에는 절대 쓰지 않는다 (위 조건이 둘 다 맞아야 한다).
                character, base = self._tint_source(task)
                ok, log = wardrobe.fake_tint(self.cfg, task.id, character, base, target)
                if not ok:
                    self.store.block(task, f"연습용 그림의 옷 색을 바꾸지 못했어요: {log[-300:]}")
                    return False
        return True

    @staticmethod
    def _tint_source(task: Task) -> tuple[str, str | None]:
        """연습용 색 바꾸기가 볼 캐릭터와 바탕 세트: 새 직원 주문은 틀 직원(같은 모습), 꾸미기 주문은 그 직원과 지금 모습."""
        ex = task.extra or {}
        if task.kind == "hire":
            return str(ex.get("template", "")), None
        return str(ex.get("character", "")), ex.get("base") or None

    def redraw_with(self, task_id: str, draw: str) -> Task:
        """막힌 꾸미기·새 직원 작업을 다른 AI로 다시 그린다 (예: Grok으로 안 되면 Codex로)."""
        with self.store.lock:
            task = self._task(task_id)
            if task.kind not in ("look", "hire"):
                raise EngineError("그림 작업만 그리는 AI를 바꿀 수 있어요.")
            task.extra = {**(task.extra or {}), "draw": wardrobe.draw_ai(draw)}
            self.store.save(task)
        return self.retry(task_id)

    def _approve_look(self, task: Task, payload: dict[str, Any], by: str) -> Task:
        """승인: 새 옷을 설치하고(꾸미기에 생김), 원하면 바로 입힌다."""
        ex = dict(task.extra or {})
        c, set_name, label = str(ex.get("character", "")), str(ex.get("set", "")), str(ex.get("label", ""))
        try:
            wardrobe.install(self.cfg, c, set_name, task.id, label, task.brief, wardrobe.kind_of(ex.get("look_kind")),
                             ex.get("base") or None)
        except wardrobe.WardrobeError as e:
            raise EngineError(str(e)) from e
        if payload.get("wear", True) and task.role in self.cfg.roles:
            look = {**company.looks(self.cfg, self.store).get(task.role, {}), "style": set_name}
            company.save_look(self.cfg, self.store, task.role, look)
        task.report = set_name
        self.store.save(task)
        self.store.transition(task, "done", by=by, note=f"새 옷: {label}")
        self.store.event("look.made", f"새 옷: {self.cfg.roles[task.role].name} · {label}", task=task.id,
                         role=task.role, set=set_name, label=label)
        return task

    # ------------------------------------------------------------ 꾸미기 옷 지우기·숨기기 (꾸미기 창의 ✕)
    def _look_target(self, role: str, set_name: str):
        """✕를 누른 옷이 그 직원의 옷인지 확인한다 (기본 모습·다른 직원의 옷·없는 옷은 거절)."""
        if role not in self.cfg.roles:
            raise EngineError(f"알 수 없는 직원: {role}")
        r = self.cfg.roles[role]
        if not set_name or set_name == "base":
            raise EngineError("기본 모습은 지우거나 숨길 수 없어요.")
        try:
            wardrobe.check_set(set_name)
        except wardrobe.WardrobeError as e:
            raise EngineError("옷 이름이 올바르지 않아요.") from e
        if f"{r.character}@{set_name}.step" not in wardrobe.sprite_index(self.cfg):
            raise EngineError(f"{r.name}의 옷이 아니에요. 다른 직원의 옷은 지우거나 숨길 수 없어요.")
        return r

    def remove_look(self, role: str, set_name: str) -> dict[str, Any]:
        """꾸미기 창의 ✕: 공방에서 만든 옷은 휴지통(data/trash/looks/)으로 옮기고, 배포 옷(여름 옷 등)은 지우지 않고
        그 직원 목록에서 숨긴다 (되살릴 수 있다). 지금 입고 있던 옷이면 기본으로 돌린다.
        그 옷을 바탕으로 새 모습을 만드는 중(결재 전)이면 지우지 않고 거절한다."""
        r = self._look_target(role, set_name)
        with self.store.lock:
            label = company.look_labels(self.cfg).get(set_name, set_name)
            made = set_name in wardrobe.made_sets(self.cfg)
            if made:
                using = [t for t in self.store.list()
                         if t.kind == "look" and t.status not in FINAL and (t.extra or {}).get("base") == set_name]
                if using:
                    raise EngineError(f"'{label}'을(를) 바탕으로 새 모습을 만드는 중이에요 ({using[0].title}). "
                                      "끝나거나 취소한 뒤에 지워 주세요.")
                try:
                    trash = wardrobe.trash_look(self.cfg, r.character, set_name)
                except wardrobe.WardrobeError as e:
                    raise EngineError(str(e)) from e
            else:
                wardrobe.set_hidden(self.cfg, r.character, set_name, True)
                trash = None
            saved = self.store.read_doc("looks", {}).get(role)
            if isinstance(saved, dict) and saved.get("style") == set_name:  # 입고 있던 옷이면 기본으로
                company.save_look(self.cfg, self.store, role, {**saved, "style": "base"})
        if made:
            self.store.event("look.removed", f"{r.name} 옷을 지웠어요: {label}", role=role, set=set_name, label=label,
                             trash=trash.relative_to(self.cfg.data_dir).as_posix())
        else:
            self.store.event("look.hidden", f"{r.name} 옷을 목록에서 뺐어요: {label}", role=role, set=set_name, label=label)
        return {"removed": made, "hidden": not made, "label": label}

    def restore_look(self, role: str, set_name: str) -> dict[str, Any]:
        """'숨긴 옷 다시 보기': 목록에서 뺀 배포 옷을 그 직원의 꾸미기 목록에 되살린다."""
        r = self._look_target(role, set_name)
        if not wardrobe.set_hidden(self.cfg, r.character, set_name, False):
            raise EngineError("숨겨 둔 옷이 아니에요.")
        label = company.look_labels(self.cfg).get(set_name, set_name)
        self.store.event("look.restored", f"{r.name} 숨긴 옷을 되살렸어요: {label}", role=role, set=set_name, label=label)
        return {"label": label}

    # ------------------------------------------------------------ 캐릭터 제조실 (새 직원)
    def hire(self, data: dict[str, Any]) -> Task:
        """새 직원 만들기: 이름·맡을 일·겉모습으로 그림 3장을 그려 자른 뒤 결재에 올린다 (승인하면 회사에 들어온다).

        새 직원은 같은 일을 하는 기본 직원의 권한·AI를 물려받고 책상을 같이 쓴다 (한 번에 한 명만 일한다).
        """
        name = wardrobe.one_line(data.get("name"), 8)
        job = str(data.get("job", ""))
        looks = wardrobe.one_line(data.get("looks"), wardrobe.MAX_DESC)
        memo = wardrobe.one_line(data.get("memo"), 40)
        raw_skills = data.get("skills") or []
        if isinstance(raw_skills, str):
            raw_skills = raw_skills.replace("，", ",").split(",")
        skill_tags = [wardrobe.one_line(x, 12) for x in raw_skills if str(x).strip()][:4]
        if job not in JOBS or job not in self.cfg.roles or self.cfg.roles[job].job:
            raise EngineError("맡을 일을 골라 주세요.")
        if not name or not looks:
            raise EngineError("이름과 겉모습을 적어 주세요.")
        tasks = self.store.list()
        pending = [t for t in tasks if t.kind == "hire" and t.status not in FINAL]
        if sum(1 for r in self.cfg.roles.values() if r.job) + len(pending) >= floors.capacity(self.cfg):
            raise EngineError(self._no_desk())
        if name in {r.name for r in self.cfg.roles.values()} | {t.extra.get("name") for t in pending}:
            raise EngineError("같은 이름의 직원이 있어요.")
        template = self.cfg.roles[job].character
        try:
            wardrobe.base_sources(self.cfg, template)
        except wardrobe.WardrobeError as e:
            raise EngineError(str(e)) from e
        used = set(self.cfg.roles) | {str(t.extra.get("key")) for t in tasks if t.kind == "hire"}
        for chars in (wardrobe.assets_dir(self.cfg) / "raw" / "chars", self.cfg.root / "assets-raw" / "chars"):  # 새·예전 위치 모두
            used |= {p.name for p in chars.iterdir()} if chars.is_dir() else set()
        key = next(f"staff{n}" for n in range(1, 1000) if f"staff{n}" not in used)
        task = self.store.create_task(
            title=f"새 직원: {name}", kind="hire", role=self._pick("producer"), project="", status="queued", brief=looks,
            extra={"key": key, "name": name, "job": job, "memo": memo, "skills": skill_tags, "template": template,
                   "draw": wardrobe.draw_ai(data.get("draw"))},
            note="새 직원 주문",
        )
        self.wake()
        return task

    def _no_desk(self) -> str:
        if floors.count(self.cfg) < floors.MAX_FLOORS:
            return "빈 책상이 없어요. 층을 늘리면 새 직원을 더 뽑을 수 있어요."
        return f"빈 책상이 없어요 (모든 층이 찼어요, 새 직원 {floors.capacity(self.cfg)}명)."

    # ------------------------------------------------------------ 층 늘리기
    def add_floor(self) -> int:
        try:
            n = floors.add(self.cfg)
        except floors.FloorError as e:
            raise EngineError(str(e)) from e
        self.store.event("floor.added", f"{n}층을 열었어요! 책상 {floors.DESKS[n - 1]}개", floor=n)
        return n

    def _run_hire(self, task: Task) -> None:
        ex = dict(task.extra or {})
        key, template = str(ex.get("key", "")), str(ex.get("template", ""))
        role = task.role if task.role in self.cfg.roles else "producer"
        d = wardrobe.job_dir(self.cfg, task.id)
        raw = d / "raw"
        if raw.exists():
            shutil.rmtree(raw)  # 다시 그리기: 새로 그린다
        raw.mkdir(parents=True)
        task = self.store.transition(task, "running", note="캐릭터 제조실에서 새 직원을 그리는 중")
        try:
            src = wardrobe.base_sources(self.cfg, template)
        except wardrobe.WardrobeError as e:
            self.store.block(task, str(e))
            return
        looks_cfg = self.cfg.root / "tools" / "sprites" / "look-sets.json"
        described = (read_json(looks_cfg, {}) or {}).get("characters", {}).get(template) or template
        notes = [f["text"] for f in task.feedback if f.get("by") == "ceo"]
        looks = task.brief + (f" (CEO note: {notes[-1]})" if notes else "")
        ok, log = wardrobe.face_ref(self.cfg, template, raw / "face-ref.png")
        if not ok:
            self.store.block(task, f"얼굴 참고 그림을 만들지 못했어요: {log[-300:]}")
            return
        body, walk = self.cfg.root / src["body"]["file"], self.cfg.root / src["walk"]["file"]
        sheet, walk_out = raw / f"char-{key}.png", raw / f"walk-{key}.png"
        steps = [
            ("sheet", wardrobe.hire_sheet_prompt(described, looks), [body], sheet),
            ("walk", wardrobe.hire_walk_prompt(looks), [walk, sheet], walk_out),
            ("face", wardrobe.hire_face_prompt(looks), [raw / "face-ref.png", sheet], raw / "portraits.png"),
        ]
        if not self._draw(task, role, "hire", steps):
            return
        task = self.store.transition(self._task(task.id), "checking", note="새 직원 그림을 자르는 중")
        ok, msg = wardrobe.process_hire(self.cfg, template, key, task.id)
        if self._cancelled(task.id):
            return
        task = self._task(task.id)
        if not ok:
            self.store.block(task, f"그림을 자르지 못했어요 ({msg}). 재시도하면 새로 그립니다.")
            return
        task.proposal = {"key": key, "name": ex.get("name", ""), "job": ex.get("job", ""),
                         "preview": {"step": f"{key}.step.strip.png", "celebrate": f"{key}.celebrate.strip.png",
                                     "walk": f"{key}.walk.strip.png", "face": f"portraits+{key}.png"}}
        self.store.save(task)
        self.store.transition(task, "awaiting_approval", note=f"새 직원 결재 요청 · {ex.get('name', '')}")

    def _approve_hire(self, task: Task, payload: dict[str, Any], by: str) -> Task:
        """채용: 그림을 설치하고 직원 명부(data/staff.json)에 올린 뒤 바로 회사에 들인다 (다시 켜지 않아도 된다)."""
        ex = dict(task.extra or {})
        key = str(ex.get("key", ""))
        if key in self.cfg.roles:
            raise EngineError("이미 들어온 직원입니다.")
        if sum(1 for r in self.cfg.roles.values() if r.job) >= floors.capacity(self.cfg):
            raise EngineError(self._no_desk())
        entry = {"key": key, "name": ex.get("name", ""), "job": ex.get("job", ""), "memo": ex.get("memo", ""),
                 "skills": ex.get("skills", []), "template": ex.get("template", ""), "looks": task.brief,
                 "task": task.id, "at": now_iso()}
        role = staff_role(self.cfg, entry)
        if role is None:
            raise EngineError("직원 정보가 올바르지 않습니다.")
        try:
            wardrobe.install_character(self.cfg, key, task.id)
        except wardrobe.WardrobeError as e:
            raise EngineError(str(e)) from e
        with self.store.lock:
            reg = read_json(self.cfg.data_dir / "staff.json", {}) or {}
            reg.setdefault("staff", []).append(entry)
            atomic_write_json(self.cfg.data_dir / "staff.json", reg)
            self.cfg.roles[key] = role
            self.ai_defaults[key] = ai.current(self.cfg, key)
        # 같은 일을 하는 직원들이 배운 스킬을 물려받는다 (회사 지침이라 신입도 같은 지침을 따른다). CEO가 끌 수 있다.
        inherited = self._inherit_skills(key, role.job) if payload.get("inherit_skills", True) is not False else []
        task.report = key
        task.extra = {**(task.extra or {}), "inherited": inherited}
        self.store.save(task)
        self.store.transition(task, "done", by=by, note=f"새 직원: {role.name}")
        self.store.event("staff.hired", f"새 직원: {role.name} ({self.cfg.roles[role.job].title})", task=task.id,
                         role=key, name=role.name, job=role.job, inherited=inherited)
        return task

    def _inherit_skills(self, key: str, job: str) -> list[str]:
        """새 직원 key가 같은 일(job)을 하는 다른 직원이 배운 스킬을 모두 배운다. 배운 스킬 이름 목록을 돌려준다."""
        got = []
        for sk in skills.list_skills(self.cfg):
            mates = [r for r in sk.learned_by if r != key and r in self.cfg.roles and self.cfg.roles[r].job_key == job]
            if mates and key not in sk.learned_by:
                try:
                    skills.set_learned(self.cfg, sk.slug, key, True)
                except skills.SkillError:
                    continue
                got.append(sk.slug)
        return got

    # ------------------------------------------------------------ 직원 내보내기 (퇴사, CEO 요청 2026-09-29)
    def dismiss(self, role: str, by: str = "ceo") -> dict[str, Any]:
        """새 직원을 내보낸다 (기본 직원 4명은 안 된다). 일하는 중이면 거절한다.

        - 그 직원의 옷·스킬 공부(회고)처럼 그 사람에게 딸린 열린 작업은 취소하고, 나머지 열린 작업(기획·개발·리서치·그림 그리기 등)은
          같은 일을 하는 다른 직원에게 넘긴다 (`_pick`).
        - 배운 스킬 목록·끼운 AI(data/ai.json)·꾸미기(data/looks.json)에서 빼고, 명부(data/staff.json)에서는 'left'로 옮긴다.
        - 그림은 휴지통(data/trash/staff/)으로. 책상 번호는 명부 순서라 뒤 직원이 한 칸씩 당겨진다 (화면이 소환으로 옮긴다).
        """
        r = self.cfg.roles.get(role)
        if r is None:
            raise EngineError(f"알 수 없는 직원: {role}")
        if not r.job:
            raise EngineError("기본 직원은 내보낼 수 없어요.")
        with self.store.lock:
            tasks = self.store.list()
            busy = [t for t in tasks if t.role == role and t.status in ("running", "checking")]
            if busy or (self._current or {}).get("role") == role:
                title = busy[0].title if busy else "지금 하는 일"
                raise EngineError(f"{r.name}{company._subj(r.name)} 일하는 중이에요 ({title}). 끝나거나 취소한 뒤에 내보내 주세요.")
            for sk in skills.list_skills(self.cfg):
                if role in sk.learned_by:
                    skills.set_learned(self.cfg, sk.slug, role, False)
            own = [t for t in tasks if t.role == role and t.status not in FINAL and t.kind in ("look", "skill")]
            moving = [t for t in tasks if t.role == role and t.status not in FINAL and t.kind not in ("look", "skill")]
            for t in own:
                self.store.transition(t, "cancelled", by=by, note=f"{r.name} 퇴사로 취소")
            # 명부에서 빼기: 이 뒤로는 이 직원에게 일이 가지 않는다
            reg = read_json(self.cfg.data_dir / "staff.json", {}) or {}
            staff = [e for e in reg.get("staff") or [] if isinstance(e, dict)]
            gone = [e for e in staff if e.get("key") == role]
            reg["staff"] = [e for e in staff if e.get("key") != role]
            reg["left"] = [*(reg.get("left") or []), *({**e, "left_at": now_iso()} for e in gone)][-50:]
            atomic_write_json(self.cfg.data_dir / "staff.json", reg)
            self.cfg.roles.pop(role, None)
            self.ai_defaults.pop(role, None)
            mcp.forget_role(self.cfg, role)
            for doc in ("ai", "looks"):
                saved = self.store.read_doc(doc, {}) or {}
                if role in saved:
                    saved.pop(role)
                    self.store.write_doc(doc, saved)
            handed = []
            for t in moving:
                t = self._task(t.id)
                t.role = self._pick(r.job_key)
                self.store.save(t)
                handed.append((t.id, t.role))
                self.store.event("task.assigned", f"{t.id} 담당: {self.cfg.roles[t.role].name} ({r.name} 퇴사)", task=t.id, role=t.role)
        try:
            trash = wardrobe.trash_character(self.cfg, role)
        except wardrobe.WardrobeError:
            trash = None
        self.store.event("staff.left", f"{r.name}{company._subj(r.name)} 회사를 떠났어요", role=role, name=r.name, job=r.job_key,
                         cancelled=[t.id for t in own], handed=[{"task": i, "to": to} for i, to in handed],
                         trash=trash.relative_to(self.cfg.data_dir).as_posix() if trash else "")
        self.wake()
        return {"name": r.name, "cancelled": len(own), "handed": len(handed)}

    # ------------------------------------------------------------ 구현·검증·리뷰
    def _run_build(self, task: Task) -> None:
        project = self._project(task.project)
        job = KIND_ROLE.get(task.kind, "builder")
        role = task.role if self.job_of(task.role) == job else job
        rcfg = self.cfg.roles[role]
        max_attempts = 1 if task.extra.get("workflow_no_retry") else self.cfg.limit("max_attempts")
        task = self._ensure_worktree(task, project)
        wt = Path(task.worktree or "")
        feedback = self._latest_feedback(task)
        pipe = self.journal.read(task.id).get("pipeline",{})
        if task.candidate_sha and pipe.get("candidate_sha") == task.candidate_sha and pipe.get("status") in ("candidate","qa","review"):
            if gitops.head(wt) != task.candidate_sha or not gitops.is_clean(wt) or worktree_digest(wt) != pipe.get("files_digest"):
                raise EngineError("후보 작업 폴더가 바뀌었습니다. 확인 전에는 재개하지 않습니다.")
            if task.status == "ready": task = self.store.transition(task,"running",note="완료된 구현을 재사용")
            if self._verify_candidate(task,project,pipe.get("violations",[])):
                return
            task = self._task(task.id)
            feedback = self._latest_feedback(task)

        while task.attempts < max_attempts:
            if self._should_stop(task.id):
                self.store.block(task, "감독 프로그램 정지로 중단됐습니다.")
                return
            task.attempts += 1
            task.run_requested = False
            self.store.save(task)
            note = f"{rcfg.title} 시도 {task.attempts}/{max_attempts}"
            if task.status == "running":
                self.store.event("task.attempt", f"{task.id} {note}", task=task.id)
            else:
                task = self.store.transition(task, "running", note=note)
            expected = task.candidate_sha or task.base_sha or ""
            prompt = build_prompt(self.cfg, task, project, task.attempts, feedback, role)
            run = self._agent_run(
                task, role, prompt, wt, sandbox=rcfg.sandbox, stage=f"build{task.attempts}", web_search=rcfg.web_search,
                skills_kind=task.kind if task.kind in ("build", "research") else "build",
            )
            if self._cancelled(task.id):
                self._cleanup_worktree(self._task(task.id))
                return
            task = self._task(task.id)
            if not run.ok:
                cp = self.journal.read(task.id).get(f"build{task.attempts}",{})
                if cp.get("status") == "unknown_outcome":
                    self.store.block(task,"실행 여부 불확실 — 변경을 보존했습니다. 결과 확인 전 재실행 금지")
                    return
                if run.error_kind in ("error", "schema") and task.attempts < max_attempts:
                    feedback = f"이전 실행이 오류로 끝났습니다: {run.error[:500]}"
                    self._trouble(task, "error", feedback)
                    self._discard_all(wt, expected)
                    continue
                self._discard_all(wt, expected)
                self._fail_run(task, run, role)
                return
            task.report = run.final_message[:4000]

            changed = gitops.staged_changes(wt, expected)
            violations = gitops.check_paths(changed, task.allowed_paths, project.all_protected())
            if violations:
                gitops.discard_paths(wt, expected, [v["path"] for v in violations])
                self.store.event(
                    "task.violation",
                    f"{task.id} 허용 범위 밖 변경 {len(violations)}건을 되돌림",
                    task=task.id,
                    paths=[v["path"] for v in violations][:20],
                )
            remaining = gitops.staged_changes(wt, expected)
            if remaining:
                self.journal.write(task.id,"pipeline",status="committing",effect="reversible",files_digest=worktree_digest(wt),candidate_sha=None)
                sha = gitops.commit_staged(wt, f"{task.id}: {task.title} (시도 {task.attempts})")
            elif task.candidate_sha:
                # 수정 시도에서 바꾼 게 없으면 이전 후보를 그대로 다시 검증한다 (리뷰가 틀렸을 수도 있다)
                sha = task.candidate_sha
                self.store.event("task.no_change", f"{task.id} 수정 시도에서 바뀐 파일 없음 — 이전 후보로 다시 검증", task=task.id)
            else:
                feedback = "변경된 파일이 없습니다." + _violation_text(violations)
                self._trouble(task, "no_change", feedback)
                if task.attempts < max_attempts:
                    continue
                self.store.block(task, "작업자가 허용 범위 안에서 아무것도 바꾸지 않았습니다." + _violation_text(violations))
                return
            # Git staging/commit can take long enough for a cancellation request.
            # Reload under the same lock used by cancel before saving any result.
            with self.store.lock:
                fresh = self._task(task.id)
                if fresh.status == "cancelled":
                    self._cleanup_worktree(fresh)
                    return
                self.store._check_current(task)
                fresh.report = task.report
                fresh.candidate_sha = sha
                self.store.save(fresh)
                self.journal.write(task.id,"pipeline",status="candidate",effect="reversible",candidate_sha=sha,files_digest=worktree_digest(wt),violations=violations)
                task = fresh
                if self._should_stop(task.id):
                    self.store.block(task, "감독 프로그램 정지로 중단됐습니다.")
                    return
                task = self.store.transition(task, "checking", note="신뢰 테스트 실행")
            if self._verify_candidate(task,project,violations):
                return
            task = self._task(task.id)
            feedback = self._latest_feedback(task)

    def _verify_candidate(self, task, project, violations):
        if task.status == "running": task = self.store.transition(task,"checking",note="후보 검증")
        saved = self.journal.read(task.id).get("verification",{})
        current_suite = suite_hash(self.cfg,project)
        qa = saved.get("result",{})
        qa_dir = self.store.qa_dir / qa.get("qa_id","missing")
        valid = (saved.get("status") == "complete" and qa.get("candidate_sha") == task.candidate_sha
                 and qa.get("suite_hash") == current_suite and (qa_dir/"evidence.json").is_file()
                 and saved.get("snapshot_digest") == files_digest(qa_dir/"snapshot"))
        if not valid:
            qa_dir = self.store.qa_dir / f"Q{stamp()}-{task.id}-{uuid4().hex[:8]}"
            self.journal.write(task.id,"verification",status="running",effect="read_only",candidate_sha=task.candidate_sha,run_id=qa_dir.name,input_digest=digest([task.candidate_sha,current_suite]))
            qa = run_qa(self.cfg,project,task.candidate_sha,qa_dir,lambda:self._should_stop(task.id),base=task.base_sha)
            qa["violations"] = violations
            qa["snapshot_digest"] = files_digest(qa_dir/"snapshot")
            receipt = read_json(qa_dir/"evidence.json",{}) or {}
            if receipt:
                atomic_write_json(qa_dir/"evidence.json",{**receipt,"snapshot_digest":qa["snapshot_digest"]})
            self.journal.write(task.id,"verification",status="complete" if qa.get("verdict") in ("pass","none") else "failed",result=qa,snapshot_digest=files_digest(qa_dir/"snapshot"),reason="timeout" if "시간" in qa.get("reason","") else qa.get("verdict"))
        if self._cancelled(task.id):
            self._cleanup_worktree(self._task(task.id)); return True
        task = self._task(task.id); task.qa = qa; self.store.save(task)
        self.journal.write(task.id,"pipeline",status="qa")
        self.store.event("qa.finished",f"{task.id} 검증 {qa['verdict']} · {qa['reason']}",task=task.id,verdict=qa["verdict"])
        if qa["verdict"] == "stopped" or self._should_stop(task.id):
            self.store.block(task,"감독 프로그램 정지로 검증이 중단됐습니다."); return True
        if qa["verdict"] == "fail":
            self._trouble(task,"qa",_qa_feedback(qa,violations))
            self.journal.write(task.id,"pipeline",status="needs_changes")
            if not task.extra.get("workflow_no_retry") and task.attempts < self.cfg.limit("max_attempts"): return False
            self.store.block(task,f"고쳐 봐도 검증 실패 — {qa['reason']}"); return True
        review = self._review(task,project,qa,qa_dir/"snapshot")
        if self._cancelled(task.id):
            self._cleanup_worktree(self._task(task.id)); return True
        task = self._task(task.id); task.review = review; self.store.save(task)
        self.journal.write(task.id,"pipeline",status="review")
        if review["verdict"] == "stopped" or self._should_stop(task.id):
            self.store.block(task,"감독 프로그램 정지로 리뷰가 중단됐습니다."); return True
        coverage = evidence.assess(self.cfg,self.store,task)
        if coverage["strict"] and not coverage["complete"]:
            self.store.block(task,"수용 기준의 검증 근거가 누락됐거나 접근할 수 없습니다."); return True
        if review["verdict"] in ("approve","unavailable"):
            if coverage["strict"] and review["verdict"] != "approve":
                self.store.block(task,"리뷰 실행 불가 — 외부 제출 작업은 리뷰 통과 후 결재할 수 있습니다.");return True
            self.store.transition(task,"awaiting_approval",note="검증·리뷰 결과 확인 및 CEO 결재 필요"); return True
        self._trouble(task,"review",_review_feedback(review))
        self.journal.write(task.id,"pipeline",status="needs_changes")
        if not task.extra.get("workflow_no_retry") and task.attempts < self.cfg.limit("max_attempts"):return False
        self.store.block(task,"리뷰의 수정 요청이 남아 있습니다.");return True

    def _ensure_worktree(self, task: Task, project: ProjectConfig) -> Task:
        if not gitops.is_repo(project.repo):
            raise EngineError(f"제품 저장소가 없습니다: {project.repo}")
        wt = self.cfg.worktrees_dir / project.key / task.id
        if task.worktree and Path(task.worktree).exists():
            return task
        branch = task.branch or f"studio/{task.id}"
        base = task.base_sha or gitops.head(project.repo, project.main_branch)
        with self._git_lock(project.key):
            gitops.add_worktree(project.repo, wt, branch, base)
        task.worktree, task.branch, task.base_sha = str(wt), branch, base
        self.store.save(task)
        return task

    def _review(self, task: Task, project: ProjectConfig, qa: dict, snapshot: Path) -> dict:
        reviewer = self._reviewer_for(task)
        rcfg = self.cfg.roles[reviewer]
        worker = task.role if task.role in self.cfg.roles else KIND_ROLE.get(task.kind, "builder")
        builder_runtime = self.cfg.roles[worker].runtime
        diff, truncated = gitops.diff_text(project.repo, task.base_sha or "", task.candidate_sha or "", self.cfg.limit("review_diff_max_chars"))
        stats = gitops.diff_numstat(project.repo, task.base_sha or "", task.candidate_sha or "")
        prompt = review_prompt(self.cfg, task, project, diff, truncated, qa if qa.get("verdict") != "none" else None, reviewer)
        cwd = snapshot if snapshot.exists() else Path(task.worktree or project.repo)
        chain = [(rcfg.runtime, rcfg.model, rcfg.effort)]
        if rcfg.fallback_runtime:
            chain.append((rcfg.fallback_runtime, rcfg.fallback_model, ""))
        if rcfg.runtime == "claude" and not self.cfg.runtime_cfg("claude").get("enabled",False):
            chain = [("claude",rcfg.model,rcfg.effort)]
        if task.extra.get("workflow_no_retry"):
            chain = chain[:1]
        errors = []
        failure = None
        for index, (runtime_name, model, effort) in enumerate(chain):
            run = self._agent_run(
                task, reviewer, prompt, cwd, sandbox="read-only", stage="review", schema=REVIEW_SCHEMA,
                runtime_name=runtime_name, model=model, effort=effort, skills_kind="review",
                requested_provider=rcfg.runtime, requested_model=rcfg.model,
                fallback_reason=failure if index else None,
            )
            if run.error_kind == "stopped":
                return {"verdict": "stopped", "summary": "중단됨", "findings": [], "runtime": runtime_name}
            s = run.structured or {}
            if run.ok and s.get("verdict") in ("approve", "changes_requested"):
                findings = [f for f in s.get("findings", []) if isinstance(f, dict)][:30]
                verdict = s["verdict"]
                if any(f.get("severity") == "blocking" for f in findings):
                    verdict = "changes_requested"
                return {
                    "verdict": verdict,
                    "by": reviewer,
                    "summary": str(s.get("summary", ""))[:3000],
                    "findings": findings,
                    "runtime": "codex" if runtime_name == "claude" and not self.cfg.runtime_cfg("claude").get("enabled",False) else runtime_name,
                    "actual_runtime": run.runtime,
                    "model": run.provider_model,
                    "model_identity": "확인됨" if run.provider_model else "확인 불가",
                    "cross_model": run.runtime != "fake" and ("codex" if runtime_name == "claude" and not self.cfg.runtime_cfg("claude").get("enabled",False) else runtime_name) != builder_runtime,
                    "diff_stats": stats,
                    "diff_truncated": truncated,
                    "candidate_sha": task.candidate_sha,
                    "at": now_iso(),
                }
            errors.append(f"{run.runtime}: {run.error or '응답 형식 오류'}"[:300])
            failure = f"{runtime_name}:{run.error_kind or 'schema'}"
            if run.error_kind == "quota" and runtime_name == "codex":
                break
        return {
            "verdict": "unavailable",
            "summary": "리뷰 실행기를 쓸 수 없어 리뷰 없이 결재에 올립니다. " + " / ".join(errors),
            "findings": [],
            "runtime": None,
            "cross_model": False,
            "diff_stats": stats,
            "candidate_sha": task.candidate_sha,
            "at": now_iso(),
        }

    def _latest_feedback(self, task: Task) -> str:
        parts = []
        if task.qa and task.qa.get("verdict") == "fail":
            parts.append(_qa_feedback(task.qa, task.qa.get("violations") or []))
        if task.review and task.review.get("verdict") == "changes_requested":
            parts.append(_review_feedback(task.review))
        ceo = [f["text"] for f in task.feedback if f.get("by") == "ceo"]
        if ceo:
            parts.append("CEO 수정 요청: " + ceo[-1])
        return "\n\n".join(parts)

    # ------------------------------------------------------------ 병합·정리
    def _merge(self, task: Task, by: str) -> Task:
        project = self._project(task.project)
        qa = task.qa or {}
        if not task.candidate_sha:
            raise EngineError("병합할 후보 커밋이 없습니다.")
        if qa.get("candidate_sha") != task.candidate_sha or qa.get("verdict") not in ("pass", "none"):
            raise EngineError("검증 결과가 현재 후보 커밋과 맞지 않습니다. 재시도해서 다시 검증하세요.")
        if qa.get("suite_hash") != suite_hash(self.cfg,project):
            raise EngineError("신뢰 테스트가 변경됐습니다. 다시 검증하세요.")
        coverage = evidence.assess(self.cfg,self.store,task)
        if coverage["strict"] and (not coverage["complete"] or (task.review or {}).get("candidate_sha") != task.candidate_sha or (task.review or {}).get("verdict") != "approve"):
            raise EngineError("수용 기준 근거 또는 현재 후보의 리뷰가 유효하지 않습니다.")
        main_head = gitops.head(project.repo, project.main_branch)
        if main_head != task.base_sha:
            self.store.block(task, "결재하는 사이 main이 바뀌었습니다. 재시도하면 최신 main에서 다시 만듭니다.", by=by)
            return self._task(task.id)
        try:
            with self._git_lock(project.key):
                merged = gitops.fast_forward_main(project.repo, project.main_branch, task.candidate_sha)
        except gitops.GitError as e:
            raise EngineError(f"병합 실패: {e}") from e
        task.merged_sha = merged
        self._cleanup_worktree(task)
        self.store.transition(task, "done", by=by, note=f"승인·병합 {merged[:7]}")
        if task.kind == "research":
            self.add_trophy(task.id, "report")
        self._maybe_reflect(task)
        self.wake()
        return task

    # ------------------------------------------------------------ 결재함 보관·완성작
    def archive(self, task_id: str, archived: bool) -> Task:
        with self.store.lock:
            task = self._task(task_id)
            if task.status != "awaiting_approval":
                raise EngineError("결재 대기 중인 작업만 미뤄 둘 수 있습니다.")
            task.archived = bool(archived)
            self.store.save(task)
        return task

    def add_trophy(self, task_id: str, kind: str) -> dict:
        """완성작 선반에 올린다. 보고서는 승인 때 자동으로, 게임은 CEO가 완료된 개발 작업에서 올린다."""
        with self.store.lock:
            task = self._task(task_id)
            if task.status != "done" or task.kind not in ("build", "research"):
                raise EngineError("완료된 개발·리서치 작업만 완성작에 올릴 수 있습니다.")
            if kind not in ("game", "report"):
                raise EngineError("완성작 종류는 game 또는 report 입니다.")
            items = self.store.read_doc("trophies", [])
            if any(i.get("task") == task_id for i in items):
                raise EngineError("이미 완성작에 있습니다.")
            item = {"kind": kind, "title": task.title, "task": task.id, "project": task.project, "at": now_iso()}
            items.append(item)
            self.store.write_doc("trophies", items)
        self.store.event("trophy.added", f"{task.id} 완성작 등록: {task.title}", task=task.id, kind=kind)
        return item

    def remove_trophy(self, task_id: str) -> None:
        with self.store.lock:
            items = self.store.read_doc("trophies", [])
            left = [i for i in items if i.get("task") != task_id]
            if len(left) == len(items):
                raise EngineError("완성작에 없는 작업입니다.")
            self.store.write_doc("trophies", left)

    def _cleanup_worktree(self, task: Task) -> None:
        if not task.worktree:
            return
        project = self.cfg.projects.get(task.project)
        if project and gitops.is_repo(project.repo):
            with self._git_lock(project.key):
                gitops.remove_worktree(project.repo, Path(task.worktree))
        task.worktree = None
        self.store.save(task)

    def _discard_branch(self, task: Task, project: ProjectConfig) -> None:
        self._cleanup_worktree(task)
        if task.branch:
            gitops.git(["branch", "-D", task.branch], project.repo, check=False)
        task.branch = task.base_sha = task.candidate_sha = None
        task.qa = task.review = None

    @staticmethod
    def _discard_all(wt: Path, expected: str) -> None:
        if wt.exists() and expected:
            gitops.git(["reset", "-q", "--hard", expected], wt, check=False)
            gitops.git(["clean", "-q", "-fd"], wt, check=False)


# ---------------------------------------------------------------- 도우미

def _clean_paths(paths: list[Any], project: ProjectConfig) -> list[str]:
    out = []
    for p in paths:
        rel = gitops.normalize_rel(str(p))
        if rel and not gitops.matches_any(rel, project.all_protected()) and rel not in out:
            out.append(rel)
    return out


def validate_plan(data: dict, project: ProjectConfig, limit: int) -> tuple[list[dict], list[str]]:
    problems: list[str] = []
    raw = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return [], ["tasks 목록이 없습니다."]
    if len(raw) > limit:
        problems.append(f"작업이 {len(raw)}개라 앞의 {limit}개만 씁니다.")
        raw = raw[:limit]
    out: list[dict] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            problems.append(f"{i}번 항목 형식 오류")
            continue
        title = str(item.get("title", "")).strip()[:80]
        kind = item.get("kind") if item.get("kind") in ("build", "research") else "build"
        allowed = _clean_paths(item.get("allowed_paths", []), project)
        acceptance = [str(a).strip()[:300] for a in item.get("acceptance", []) if str(a).strip()]
        if not title or not allowed or not acceptance:
            problems.append(f"{i}번 '{title or '?'}': 제목·허용 경로·수용 기준 중 빠진 것이 있어 제외")
            continue
        deps = [d for d in item.get("depends_on", []) if isinstance(d, int) and 0 <= d < i]
        if len(deps) != len(item.get("depends_on", [])):
            problems.append(f"{i}번: 앞 번호가 아닌 선행 작업은 무시했습니다.")
        # 앞에서 제외된 항목 번호를 새 번호로 옮긴다
        try:
            difficulty = min(3, max(1, int(item.get("difficulty", 1))))
        except (TypeError, ValueError):
            difficulty = 1
        out.append({
            "title": title,
            "kind": kind,
            "difficulty": difficulty,
            "brief": str(item.get("brief", "")).strip()[:4000],
            "acceptance": acceptance[:12],
            "allowed_paths": allowed[:12],
            "depends_on": deps,
            "_orig": i,
        })
    remap = {t["_orig"]: n for n, t in enumerate(out)}
    for t in out:
        t["depends_on"] = [remap[d] for d in t["depends_on"] if d in remap]
        del t["_orig"]
    return out, problems


def _violation_text(violations: list[dict]) -> str:
    if not violations:
        return ""
    lines = [f"- {v['path']} ({v['reason']})" for v in violations[:15]]
    return "\n허용 범위 밖이라 되돌린 변경:\n" + "\n".join(lines)


def _qa_feedback(qa: dict, violations: list[dict]) -> str:
    lines = [f"신뢰 테스트 결과: {qa.get('reason', '')}"]
    for t in qa.get("tests", []):
        if not t.get("ok"):
            lines.append(f"- 실패 {t.get('name')}: {t.get('message', '')}")
    text = "\n".join(lines) + _violation_text(violations)
    bom_files = qa.get("bom_files")
    if bom_files:
        text += (
            f"\n\n파일 맨 앞에 눈에 보이지 않는 BOM(바이트 EF BB BF)이 붙어 있다: {', '.join(str(b) for b in bom_files[:20])}. "
            "검사는 첫 글자를 '#'로 읽지 못한다. BOM 없는 UTF-8로 다시 저장한다 "
            "(PowerShell은 `Set-Content -Encoding utf8NoBOM`, 파이썬은 `encoding=\"utf-8\"` — `utf-8-sig`는 쓰지 않는다). "
            "검사 메시지의 '# 제목'은 '# 실제 제목' 모양이라는 뜻이다."
        )
    return text


def _review_feedback(review: dict) -> str:
    lines = [f"리뷰({review.get('runtime')}) 수정 요청: {review.get('summary', '')}"]
    for f in review.get("findings", []):
        lines.append(f"- [{f.get('severity')}] {f.get('file')}: {f.get('issue')} → {f.get('suggestion')}")
    return "\n".join(lines)
