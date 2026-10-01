"""내장 MCP '회사 기록 찾기' (studio-records): 배운 스킬과 지난 작업을 찾아 읽는다. 읽기만 한다.

직원이 "전에 비슷한 일을 어떻게 했지?"를 스스로 찾아보게 한다 (회사 기억).
실행: python records.py --root <회사 폴더> --data <data 폴더>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # studio 패키지 (skills 형식 읽기)

from studio import skills as sk  # noqa: E402
from studio.mcp_builtin.base import Server, ToolError, setup_stdio  # noqa: E402

KIND = {"plan": "기획", "build": "개발", "research": "리서치", "skill": "스킬 공부", "look": "의상", "hire": "새 직원"}
STATUS = {"queued": "대기", "ready": "준비", "running": "진행 중", "checking": "검증 중", "reviewing": "리뷰 중",
          "awaiting_approval": "결재 대기", "blocked": "막힘", "done": "완료", "cancelled": "취소"}
TASK_RE = re.compile(r"^T\d{1,6}$")


class Records:
    def __init__(self, root: Path, data: Path):
        self.root, self.data = root, data

    def skill_list(self) -> list[sk.Skill]:
        folder = self.root / "skills"
        out = []
        if folder.is_dir():
            for d in sorted(folder.iterdir()):
                f = d / "SKILL.md"
                if d.is_dir() and sk.NAME_RE.match(d.name) and f.is_file():
                    out.append(sk.parse(f.read_text(encoding="utf-8", errors="replace"), d.name))
        return out

    def tasks(self) -> list[dict]:
        folder = self.data / "tasks"
        out = []
        if folder.is_dir():
            for f in folder.glob("T*.json"):
                try:
                    t = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(t, dict) and TASK_RE.match(str(t.get("id", ""))):
                    out.append(t)
        out.sort(key=lambda t: str(t.get("updated_at") or t.get("created_at") or ""), reverse=True)
        return out


def _score(words: set[str], text: str) -> int:
    return len(words & sk.tokens(text)) if words else 1


def _short(text: object, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def build(rec: Records) -> Server:
    srv = Server("studio-records", "1.0", "AI 스튜디오의 배운 스킬과 지난 작업 기록을 찾아 읽는다. 읽기만 한다. "
                 "비슷한 일을 전에 어떻게 했는지, 무엇 때문에 막혔는지 확인할 때 쓴다.")

    @srv.tool("find_skills", "회사가 배운 스킬을 찾는다. query가 비면 전부. 결과: 이름·판·제목·언제 쓰나·배운 직원·쓰는 곳.",
              {"query": {"type": "string", "description": "찾을 낱말 (예: 세이브, 시그널). 비우면 전부"}})
    def find_skills(query: str = "") -> str:
        words = sk.tokens(query)
        found = sorted(((s, _score(words, f"{s.title} {s.description} {s.slug} {s.body}")) for s in rec.skill_list()),
                       key=lambda x: -x[1])
        lines = [f"`{s.slug}` v{s.version} — {s.title}: {s.description} (배운 직원: {', '.join(s.learned_by) or '없음'}; "
                 f"쓰는 곳: {', '.join(s.projects) or '모든 프로젝트'} · {', '.join(s.kinds) or '모든 일'})"
                 for s, score in found if score][:15]
        return "\n".join(lines) or "맞는 스킬이 없습니다."

    @srv.tool("read_skill", "스킬 하나의 전체 지침(SKILL.md)을 읽는다.",
              {"name": {"type": "string", "description": "스킬 이름 (find_skills 결과의 `이름`)"}}, ["name"])
    def read_skill(name: str) -> str:
        if not sk.NAME_RE.match(str(name)):
            raise ToolError("스킬 이름이 올바르지 않습니다.")
        f = rec.root / "skills" / name / "SKILL.md"
        if not f.is_file():
            raise ToolError("그런 스킬이 없습니다.")
        return f.read_text(encoding="utf-8", errors="replace")

    @srv.tool("find_tasks", "지난 작업을 찾는다 (최근 것부터). 결과: 번호·종류·상태·제목·목표 앞부분.",
              {"query": {"type": "string", "description": "찾을 낱말. 비우면 최근 작업"},
               "kind": {"type": "string", "enum": ["", "plan", "build", "research", "skill"], "description": "작업 종류 (비우면 모두)"},
               "status": {"type": "string", "enum": ["", "done", "blocked", "awaiting_approval", "cancelled"],
                          "description": "상태 (비우면 모두)"},
               "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "몇 개까지 (기본 10)"}})
    def find_tasks(query: str = "", kind: str = "", status: str = "", limit: int = 10) -> str:
        words = sk.tokens(query)
        hits = []
        for t in rec.tasks():
            if (kind and t.get("kind") != kind) or (status and t.get("status") != status):
                continue
            score = _score(words, f"{t.get('title', '')} {t.get('brief', '')} {t.get('report', '')}")
            if score:
                hits.append((score, t))
        hits.sort(key=lambda x: -x[0])  # 같은 점수면 최근 것 먼저 (sort는 순서를 지킨다)
        lines = [f"{t['id']} [{KIND.get(t.get('kind'), t.get('kind'))}·{STATUS.get(t.get('status'), t.get('status'))}] "
                 f"{_short(t.get('title'), 60)} — {_short(t.get('brief'), 100)}" for _, t in hits[: max(1, min(int(limit), 30))]]
        return "\n".join(lines) or "맞는 작업이 없습니다."

    @srv.tool("read_task", "지난 작업 하나를 자세히 읽는다: 목표·수용 기준·보고·리뷰 지적·CEO 의견·걸린 일·막힌 이유.",
              {"task_id": {"type": "string", "description": "작업 번호 (예: T0012)"}}, ["task_id"])
    def read_task(task_id: str) -> str:
        if not TASK_RE.match(str(task_id)):
            raise ToolError("작업 번호가 올바르지 않습니다 (예: T0012).")
        t = next((x for x in rec.tasks() if x.get("id") == task_id), None)
        if not t:
            raise ToolError("그런 작업이 없습니다.")
        review = t.get("review") or {}
        parts = [
            f"# {t['id']} {t.get('title', '')}",
            f"종류: {KIND.get(t.get('kind'), t.get('kind'))} · 상태: {STATUS.get(t.get('status'), t.get('status'))} · "
            f"프로젝트: {t.get('project', '')} · 담당: {t.get('role', '')}",
            f"\n## 목표\n{_short(t.get('brief'), 3000)}",
        ]
        if t.get("acceptance"):
            parts.append("\n## 수용 기준\n" + "\n".join(f"- {a}" for a in t["acceptance"]))
        if t.get("report"):
            parts.append(f"\n## 보고\n{str(t['report'])[:4000]}")
        if review:
            finds = [f"- {f.get('file', '')}: {f.get('issue', '')} → {f.get('suggestion', '')}"
                     for f in review.get("findings") or [] if isinstance(f, dict)]
            parts.append(f"\n## 리뷰 ({review.get('verdict', '')})\n{_short(review.get('summary'), 1500)}\n" + "\n".join(finds[:15]))
        ceo = [f"- {_short(f.get('text'), 600)}" for f in t.get("feedback") or [] if isinstance(f, dict)]
        if ceo:
            parts.append("\n## CEO 의견\n" + "\n".join(ceo))
        troubles = [f"- [{x.get('kind', '')}] {_short(x.get('text'), 600)}" for x in t.get("troubles") or [] if isinstance(x, dict)]
        if troubles:
            parts.append("\n## 걸린 일\n" + "\n".join(troubles))
        if t.get("blocked_reason"):
            parts.append(f"\n## 막힌 이유\n{_short(t['blocked_reason'], 1000)}")
        return "\n".join(parts)

    return srv


def main() -> None:
    setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    build(Records(Path(a.root), Path(a.data))).serve()


if __name__ == "__main__":
    main()
