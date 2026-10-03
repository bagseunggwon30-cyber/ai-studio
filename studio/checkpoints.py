"""Durable stage receipts. Interrupted writes are never automatically replayed."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from . import gitops
from .util import atomic_write_json, now_iso, read_json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def files_digest(root: Path) -> str:
    """Hash a supervisor-owned QA snapshot; symlinks invalidate the snapshot."""
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):
            raise ValueError("증거에 링크 파일이 있습니다.")
        if p.is_file():
            rows.append((p.relative_to(root).as_posix(), hashlib.sha256(p.read_bytes()).hexdigest()))
    return digest(rows)


def worktree_digest(root: Path) -> str:
    names = gitops.git(["ls-files", "-co", "--exclude-standard", "-z"], root).stdout.split("\0")
    rows = []
    for name in sorted(set(filter(None, names))):
        p = root / name
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):
            raise ValueError("작업 폴더 밖 링크는 재개할 수 없습니다.")
        rows.append((name, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None))
    return digest(rows)


class Journal:
    def __init__(self, store):
        self.store = store

    def read(self, task):
        return read_json(self.store.dir / "checkpoints" / (task + ".json"), {}) or {}

    def write(self, task, stage, **values):
        with self.store.lock:
            doc = self.read(task)
            item = {**doc.get(stage, {}), **values, "updated_at": now_iso()}
            doc[stage] = item
            atomic_write_json(self.store.dir / "checkpoints" / (task + ".json"), doc)
            self.store._bump()
            return item

    def clear(self, task):
        with self.store.lock:
            atomic_write_json(self.store.dir / "checkpoints" / (task + ".json"), {})

    def progress(self, task):
        doc = self.read(task)
        steps = [{"stage": k, **{n: v.get(n) for n in ("status", "run_id", "effect", "candidate_sha", "reason", "next_action", "updated_at")}}
                 for k, v in doc.items()]
        labels = {"plan":"기획", "review":"읽기 전용 리뷰", "verification":"검증", "pipeline":"후보 저장", "stop":"중지"}
        states = {"running":"진행 중", "complete":"저장 완료", "failed":"실패", "unknown_outcome":"실행 여부 불확실", "interrupted":"중단", "candidate":"후보 저장", "qa":"검증 저장", "review":"리뷰 저장", "needs_changes":"수정 필요", "cancelled":"취소", "committing":"커밋 저장 중"}
        for step in steps:
            step["label"] = "구현" if step["stage"].startswith("build") else labels.get(step["stage"],step["stage"])
            step["status_label"] = states.get(step.get("status"),step.get("status"))
        last = max(steps, key=lambda x: x.get("updated_at") or "", default={})
        return {"steps": steps, "last": last}
