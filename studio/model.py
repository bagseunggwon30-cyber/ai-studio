"""작업 카드(Task)와 상태 전이 규칙.

상태는 감독 프로그램만 바꾼다. 에이전트는 '완료'를 선언할 수 없고,
결재 대기(awaiting_approval) → 완료(done)는 CEO의 승인으로만 일어난다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any

STATUS_LABELS = {
    "queued": "기획 대기",
    "ready": "준비",
    "running": "작업 중",
    "checking": "검증 중",
    "awaiting_approval": "결재 대기",
    "done": "완료",
    "blocked": "막힘",
    "cancelled": "취소",
}

TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "blocked", "cancelled"},
    "ready": {"running", "blocked", "cancelled"},
    "running": {"checking", "awaiting_approval", "blocked", "cancelled"},
    "checking": {"running", "awaiting_approval", "blocked", "cancelled"},
    "awaiting_approval": {"done", "ready", "queued", "blocked", "cancelled"},
    "blocked": {"ready", "queued", "cancelled"},
    "done": set(),
    "cancelled": set(),
}

ACTIVE = {"running", "checking"}
# 제품 저장소에 아직 병합되지 않은 브랜치를 가진 상태. 같은 프로젝트의 다음 작업은 기다린다.
OPEN_BRANCH = {"running", "checking", "awaiting_approval"}
FINAL = {"done", "cancelled"}

KIND_LABELS = {"plan": "기획", "build": "개발", "research": "리서치·문서", "skill": "스킬 공부", "look": "의상 제작", "hire": "새 직원",
               "tool": "MCP 만들기"}
KIND_ROLE = {"plan": "producer", "build": "builder", "research": "analyst", "skill": "reviewer", "tool": "builder"}
# 제품 저장소에 브랜치를 만들지 않는 작업 (기획·스킬 공부는 읽기 전용 JSON, 의상 제작·새 직원은 그림 생성,
# MCP 만들기는 코드를 JSON으로 받아 승인 뒤 data/mcp/servers/에 설치)
NO_BRANCH = {"plan", "skill", "look", "hire", "tool"}


class TransitionError(ValueError):
    pass


@dataclass
class Task:
    id: str
    title: str
    kind: str  # plan | build | research | skill
    role: str  # producer | builder | analyst | reviewer (스킬 공부는 CEO가 고른 직원)
    project: str
    status: str
    brief: str = ""
    acceptance: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    created_by: str = "ceo"
    attempts: int = 0
    run_requested: bool = False
    branch: str | None = None
    worktree: str | None = None
    base_sha: str | None = None
    candidate_sha: str | None = None
    merged_sha: str | None = None
    runs: list[str] = field(default_factory=list)
    qa: dict | None = None
    review: dict | None = None
    feedback: list[dict] = field(default_factory=list)
    proposal: dict | None = None
    blocked_reason: str | None = None
    report: str = ""
    history: list[dict] = field(default_factory=list)
    difficulty: int = 1  # 1~3, 기획 담당이 매긴다 (퀘스트 쪽지의 별)
    archived: bool = False  # 결재함에서 '나중에 보기'로 미뤄 둠
    # 스스로 배우기: 일하다 걸린 일(검사 탈락·리뷰 수정 요청·오류·막힘)을 적어 두고, 끝난 뒤 회고에 쓴다
    troubles: list[dict] = field(default_factory=list)
    origin: str | None = None  # 회고(스킬 작업)가 돌아보는 작업
    target: str | None = None  # 스킬 작업이 고칠 스킬 (CEO가 '더 좋게 고쳐 오기'로 정함)
    extra: dict = field(default_factory=dict)  # 종류별 값 (의상 제작: character·set·label)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def summary(self) -> dict[str, Any]:
        """보드에 보여줄 요약."""
        qa = self.qa or {}
        review = self.review or {}
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "role": self.role,
            "project": self.project,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "attempts": self.attempts,
            "depends_on": self.depends_on,
            "parent": self.parent,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
            "blocked_reason": self.blocked_reason,
            "run_requested": self.run_requested,
            "qa": {
                "verdict": qa.get("verdict"),
                "passed": qa.get("passed"),
                "total": qa.get("total"),
            }
            if qa
            else None,
            "review": {"verdict": review.get("verdict"), "runtime": review.get("runtime"), "cross_model": review.get("cross_model")}
            if review
            else None,
            "has_proposal": bool(self.proposal),
            "difficulty": self.difficulty,
            "archived": self.archived,
            "brief": self.brief[:600],
            "acceptance": self.acceptance[:12],
            "files": len((review.get("diff_stats") or [])) if review else None,
            "created_by": self.created_by,
            "origin": self.origin,
            "target": self.target,
            "troubles": len(self.troubles),
            "extra": self.extra,
        }


def check_transition(current: str, new: str) -> None:
    if new not in TRANSITIONS.get(current, set()):
        raise TransitionError(f"'{STATUS_LABELS.get(current, current)}'에서 '{STATUS_LABELS.get(new, new)}'(으)로 바꿀 수 없음")
