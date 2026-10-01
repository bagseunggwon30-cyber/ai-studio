"""내장 MCP '차근차근 생각' (step-thinking): 어려운 문제를 단계로 나눠 적고, 고치고, 갈래를 나눠 본다. (MCP 참고 서버 'Sequential Thinking'의 AI 스튜디오판)

생각 단계를 이 서버가 기억해 두었다가 지금까지의 흐름을 돌려준다. 파일을 쓰지 않고, 서버가 켜져 있는 동안(한 번의 실행)만 기억한다.
기본으로는 아무에게도 장착하지 않는다 (필요한 직원에게 CEO가 장착).
실행: python thinking.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio.mcp_builtin.base import Server, ToolError, setup_stdio  # noqa: E402

MAX_STEPS, MAX_TEXT = 60, 2000


def build() -> Server:
    srv = Server("step-thinking", "1.0", "어려운 문제를 단계별로 생각할 때 쓴다: 한 단계씩 적고, 앞 단계를 고치거나 다른 갈래를 시험한다. "
                 "계획이 바뀌면 total을 늘리거나 줄인다. 답이 나오면 done=true.")
    steps: list[dict] = []

    def view(last: dict) -> str:
        where = f"{last['n']}/{last['total']}"
        if last.get("revises"):
            where += f" ({last['revises']}단계 고침)"
        if last.get("branch"):
            where += f" [갈래 {last['branch']}: {last['from']}단계에서]"
        branches = sorted({s["branch"] for s in steps if s.get("branch")})
        tail = "생각 끝. 결론을 정리해 쓴다." if last["done"] else "다음 단계를 이어서 적는다."
        return (f"적었어요 — {where}. 지금까지 {len(steps)}단계" + (f", 갈래: {', '.join(branches)}" if branches else "")
                + f".\n{tail}")

    @srv.tool("think", "생각 한 단계를 적는다. step은 이번 단계 번호, total은 예상 단계 수 (바뀌어도 된다).",
              {"thought": {"type": "string", "description": "이번 단계의 생각"},
               "step": {"type": "integer"}, "total": {"type": "integer"},
               "done": {"type": "boolean", "description": "생각이 끝났으면 true"},
               "revises": {"type": "integer", "description": "앞 단계를 고치는 것이면 그 번호"},
               "branch": {"type": "string", "description": "다른 갈래를 시험하면 갈래 이름"},
               "branch_from": {"type": "integer", "description": "갈래가 시작된 단계 번호"}},
              ["thought", "step", "total"])
    def think(thought: str, step: int, total: int, done: bool = False, revises: int = 0, branch: str = "", branch_from: int = 0) -> str:
        text = " ".join(str(thought or "").split())[:MAX_TEXT]
        if not text:
            raise ToolError("thought가 비어 있어요.")
        try:
            n, t = int(step), int(total)
        except (TypeError, ValueError) as e:
            raise ToolError("step과 total은 숫자로 적어 주세요.") from e
        if n < 1:
            raise ToolError("step은 1부터예요.")
        if len(steps) >= MAX_STEPS:
            raise ToolError(f"{MAX_STEPS}단계를 넘었어요. 지금까지 생각으로 결론을 내 주세요.")
        if revises and not any(s["n"] == int(revises) for s in steps):
            raise ToolError(f"{revises}단계가 아직 없어요.")
        rec = {"n": n, "total": max(n, t), "text": text, "done": bool(done), "revises": int(revises or 0),
               "branch": str(branch or "")[:40], "from": int(branch_from or 0)}
        steps.append(rec)
        return view(rec)

    @srv.tool("review", "지금까지 적은 생각 단계를 모두 보여 준다 (결론을 정리할 때).")
    def review() -> str:
        if not steps:
            return "아직 적은 생각이 없어요."
        rows = []
        for s in steps:
            tag = f" (고침→{s['revises']})" if s["revises"] else ""
            tag += f" [갈래 {s['branch']}]" if s["branch"] else ""
            rows.append(f"{s['n']}/{s['total']}{tag}: {s['text']}")
        return "\n".join(rows)

    @srv.tool("reset", "생각을 모두 지우고 처음부터 (다른 문제로 넘어갈 때).", read_only=False)
    def reset() -> str:
        steps.clear()
        return "지웠어요."

    return srv


def main() -> None:
    setup_stdio()
    build().serve()


if __name__ == "__main__":
    main()
