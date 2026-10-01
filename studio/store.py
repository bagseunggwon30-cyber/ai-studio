"""파일 기반 저장소.

data/
  tasks/T0001.json   작업 카드 (감독 프로그램만 쓴다)
  events.jsonl       회사 활동 기록 (추가만 한다)
  runs.jsonl         에이전트 실행 기록 (추가만 한다)
  runs/<run_id>/     실행별 프롬프트·로그·마지막 메시지
  qa/<qa_id>/        검증별 스냅샷·결과·증거
  state.json         긴급 정지, 자동 진행, 목표, 알림 읽음 같은 회사 상태
  trophies.json      완성작 선반 (보고서는 승인 때 자동, 게임은 CEO가 올림)
  looks.json         직원 꾸미기 (의상 세트·머리색·옷 색·키·체격)
"""

from __future__ import annotations

import os
import threading
from collections import deque
from pathlib import Path
from typing import Any

from .model import STATUS_LABELS, Task, check_transition
from .util import (
    append_jsonl,
    atomic_write_json,
    now_iso,
    pid_alive,
    read_json,
    read_jsonl,
    today_str,
)


class StoreLockedError(RuntimeError):
    pass


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.tasks_dir = self.dir / "tasks"
        self.runs_dir = self.dir / "runs"
        self.qa_dir = self.dir / "qa"
        for d in (self.tasks_dir, self.runs_dir, self.qa_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.runs_index = self.dir / "runs.jsonl"
        self.state_path = self.dir / "state.json"
        self.lock = threading.RLock()
        self._version = 0
        self._lock_path: Path | None = None
        self._events: deque[dict] = deque(read_jsonl(self.events_path)[-2000:], maxlen=2000)
        self._runs: list[dict] = read_jsonl(self.runs_index)

    # ---- 프로세스 잠금: 감독 프로그램은 한 번에 하나만 ----
    def acquire_process_lock(self) -> None:
        path = self.dir / "studio.lock"
        if path.exists():
            try:
                pid = int(path.read_text(encoding="utf-8").strip() or 0)
            except ValueError:
                pid = 0
            if pid and pid != os.getpid() and pid_alive(pid):
                raise StoreLockedError(f"감독 프로그램이 이미 실행 중입니다 (PID {pid}).")
        path.write_text(str(os.getpid()), encoding="utf-8")
        self._lock_path = path

    def release_process_lock(self) -> None:
        path = self._lock_path
        try:
            if path and path.exists() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
                path.unlink()
        except OSError:
            pass

    # ---- 변경 카운터 (화면 갱신용) ----
    def _bump(self) -> None:
        self._version += 1

    @property
    def version(self) -> int:
        return self._version

    # ---- 회사 상태 ----
    def get_state(self) -> dict[str, Any]:
        return read_json(self.state_path, {}) or {}

    def update_state(self, **values: Any) -> dict[str, Any]:
        with self.lock:
            state = self.get_state()
            state.update(values)
            atomic_write_json(self.state_path, state)
            self._bump()
            return state

    # ---- 작은 문서 (완성작, 꾸미기) ----
    def read_doc(self, name: str, default: Any) -> Any:
        value = read_json(self.dir / f"{name}.json", None)
        return default if value is None else value

    def write_doc(self, name: str, value: Any) -> None:
        with self.lock:
            atomic_write_json(self.dir / f"{name}.json", value)
            self._bump()

    def next_task_id(self) -> str:
        with self.lock:
            state = self.get_state()
            n = int(state.get("next_task", 1))
            while (self.tasks_dir / f"T{n:04d}.json").exists():
                n += 1
            state["next_task"] = n + 1
            atomic_write_json(self.state_path, state)
            return f"T{n:04d}"

    # ---- 작업 카드 ----
    def create_task(self, *, created_by: str = "ceo", note: str = "생성", **fields: Any) -> Task:
        with self.lock:
            tid = self.next_task_id()
            now = now_iso()
            task = Task(id=tid, created_at=now, updated_at=now, created_by=created_by, **fields)
            task.history.append({"at": now, "from": None, "to": task.status, "by": created_by, "note": note})
            self._save(task)
            self.event("task.created", f"{tid} 생성: {task.title}", task=tid)
            return task

    def _save(self, task: Task) -> None:
        task.updated_at = now_iso()
        atomic_write_json(self.tasks_dir / f"{task.id}.json", task.to_dict())
        self._bump()

    def save(self, task: Task) -> None:
        with self.lock:
            self._save(task)

    def get(self, task_id: str) -> Task | None:
        data = read_json(self.tasks_dir / f"{task_id}.json")
        return Task.from_dict(data) if data else None

    def list(self) -> list[Task]:
        tasks = []
        for p in sorted(self.tasks_dir.glob("T*.json")):
            data = read_json(p)
            if data:
                tasks.append(Task.from_dict(data))
        return tasks

    def transition(self, task: Task, new: str, *, by: str = "system", note: str = "") -> Task:
        with self.lock:
            check_transition(task.status, new)
            old = task.status
            task.status = new
            if new != "blocked":
                task.blocked_reason = None
            task.history.append({"at": now_iso(), "from": old, "to": new, "by": by, "note": note})
            self._save(task)
            msg = f"{task.id} {STATUS_LABELS.get(old, old)} → {STATUS_LABELS.get(new, new)}"
            if note:
                msg += f" · {note}"
            self.event("task.status", msg, task=task.id, status=new, by=by)
            return task

    def block(self, task: Task, reason: str, *, by: str = "system") -> Task:
        with self.lock:
            fresh = self.get(task.id) or task
            if fresh.status in ("blocked", "done", "cancelled"):
                return fresh
            check_transition(fresh.status, "blocked")
            fresh.blocked_reason = reason
            old = fresh.status
            fresh.status = "blocked"
            fresh.run_requested = False
            fresh.history.append({"at": now_iso(), "from": old, "to": "blocked", "by": by, "note": reason})
            self._save(fresh)
            self.event("task.blocked", f"{fresh.id} 막힘 · {reason}", task=fresh.id, status="blocked")
            return fresh

    # ---- 활동 기록 ----
    def event(self, type: str, message: str, task: str | None = None, **data: Any) -> None:
        rec: dict[str, Any] = {"at": now_iso(), "type": type, "message": message}
        if task:
            rec["task"] = task
        if data:
            rec["data"] = data
        with self.lock:
            append_jsonl(self.events_path, rec)
            self._events.append(rec)
            self._bump()

    def recent_events(self, limit: int = 100, task: str | None = None) -> list[dict]:
        with self.lock:
            items = [e for e in self._events if task is None or e.get("task") == task]
        return list(reversed(items[-limit:]))

    # ---- 실행 기록 ----
    def add_run(self, rec: dict) -> None:
        with self.lock:
            append_jsonl(self.runs_index, rec)
            self._runs.append(rec)
            self._bump()

    def runs(self, task: str | None = None) -> list[dict]:
        with self.lock:
            return [r for r in self._runs if task is None or r.get("task") == task]

    def today_usage(self) -> dict[str, Any]:
        today = today_str()
        with self.lock:
            todays = [r for r in self._runs if str(r.get("started_at", "")).startswith(today)]
        seconds = sum(float(r.get("duration_s") or 0) for r in todays)
        by_runtime: dict[str, int] = {}
        for r in todays:
            by_runtime[r.get("runtime", "?")] = by_runtime.get(r.get("runtime", "?"), 0) + 1
        return {"runs": len(todays), "minutes": round(seconds / 60, 1), "by_runtime": by_runtime}
