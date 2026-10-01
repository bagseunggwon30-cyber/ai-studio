"""내장 MCP '제품 기록 보기' (git-history): 제품 저장소의 git 기록을 읽기만 한다. (MCP 참고 서버 'Git'의 AI 스튜디오판)

'이 파일은 언제 왜 바뀌었나', '지난 작업이 무엇을 고쳤나'를 직원이 스스로 확인한다.
쓰는 명령(commit, checkout, reset, add …)은 없다. 볼 수 있는 저장소는 CEO가 등록한 제품(trusted/projects)뿐이다.
인자는 모두 검사한다: ref는 영문·숫자·._/@^~- 만, 경로는 저장소 안 상대 경로만, 둘 다 '-'로 시작할 수 없다.
실행: python git_read.py --project <키>=<저장소 경로> [--project …]
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from studio.mcp_builtin.base import Server, ToolError, setup_stdio  # noqa: E402

REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@^~-]{0,99}$")
MAX_OUT = 40_000
TIMEOUT = 30
# 저장소 설정이 바깥 프로그램을 부르지 못하게 (fsmonitor, 외부 diff, 서명 확인, 페이저)
SAFE = ["-c", "core.quotepath=false", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-c", "log.showSignature=false"]


def _ref(v: object, what: str = "ref") -> str:
    s = str(v or "").strip()
    if not REF_RE.match(s) or ".." in s:
        raise ToolError(f"{what}가 올바르지 않아요: 커밋 번호, 브랜치 이름, HEAD~2 같은 것만 돼요.")
    return s


def _path(v: object) -> str:
    s = str(v or "").strip().replace("\\", "/")
    if not s:
        return ""
    if s.startswith(("-", "/")) or re.match(r"^[A-Za-z]:", s) or ".." in s.split("/") or len(s) > 300 or "\n" in s:
        raise ToolError("경로는 저장소 안 상대 경로로 적어 주세요 (예: scripts/player.gd).")
    return s


def _limit(v: object, default: int, top: int) -> int:
    try:
        n = int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(top, n))


def build(projects: dict[str, Path]) -> Server:
    srv = Server("git-history", "1.0", "제품 저장소의 git 기록을 읽기만 한다 (로그, 커밋 내용, 두 판 차이, 줄별 마지막 수정, 브랜치). "
                 "무엇이 언제 왜 바뀌었는지 확인할 때 쓴다. 쓰는 명령은 없다.")

    def repo(name: object) -> Path:
        key = str(name or "").strip()
        if not key and len(projects) == 1:
            key = next(iter(projects))
        if key not in projects:
            raise ToolError(f"모르는 제품: {key or '(비어 있음)'}. 쓸 수 있는 제품: {', '.join(projects) or '없음'}")
        return projects[key]

    def git(where: Path, *args: str) -> str:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_PAGER="cat", LC_ALL="C.UTF-8")
        try:
            p = subprocess.run(["git", "--no-pager", *SAFE, "-C", str(where), *args], capture_output=True, timeout=TIMEOUT,
                               env=env, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError as e:
            raise ToolError("이 PC에서 git을 찾지 못했어요.") from e
        except subprocess.TimeoutExpired as e:
            raise ToolError("git이 너무 오래 걸려서 멈췄어요. 범위(경로·개수)를 줄여 주세요.") from e
        out = p.stdout.decode("utf-8", "replace")
        if p.returncode != 0:
            raise ToolError(f"git 실패: {p.stderr.decode('utf-8', 'replace').strip()[:400]}")
        if len(out) > MAX_OUT:
            out = out[:MAX_OUT] + f"\n…(길어서 {MAX_OUT}자까지만. 경로를 좁혀 다시 보세요)"
        return out.strip() or "(내용 없음)"

    names = ", ".join(projects) or "없음"
    proj = {"project": {"type": "string", "description": f"제품 키 ({names}). 제품이 하나면 비워도 된다."}}

    @srv.tool("projects", "볼 수 있는 제품 저장소 목록과 지금 기본 브랜치의 마지막 커밋.")
    def list_projects() -> str:
        rows = []
        for key, where in projects.items():
            try:
                last = git(where, "log", "-1", "--format=%h %ad %s", "--date=short")
            except ToolError as e:
                last = str(e)
            rows.append(f"- {key}: {last}")
        return "\n".join(rows) or "등록된 제품이 없어요."

    @srv.tool("log", "커밋 기록 (최신부터). path를 주면 그 파일·폴더를 바꾼 커밋만, grep을 주면 메시지에 그 말이 든 커밋만.",
              {**proj, "ref": {"type": "string", "description": "어느 판에서부터 (비우면 HEAD, 예: main, studio/T0003)"},
               "path": {"type": "string"}, "grep": {"type": "string", "description": "커밋 메시지에서 찾을 말"},
               "limit": {"type": "integer", "description": "몇 개 (기본 20, 최대 100)"}})
    def log(project: str = "", ref: str = "", path: str = "", grep: str = "", limit: int = 20) -> str:
        args = ["log", f"-{_limit(limit, 20, 100)}", "--format=%h %ad %an | %s", "--date=short", "--no-ext-diff"]
        if grep:
            args += ["--fixed-strings", f"--grep={str(grep)[:100]}"]
        args.append(_ref(ref) if ref else "HEAD")
        p = _path(path)
        return git(repo(project), *args, "--", *([p] if p else []))

    @srv.tool("show", "커밋 하나의 설명과 바뀐 내용. path를 주면 그 판의 그 파일 전체 내용을 보여 준다.",
              {**proj, "ref": {"type": "string", "description": "커밋 번호나 브랜치 (예: 735d55b, HEAD~1)"}, "path": {"type": "string"}},
              ["ref"])
    def show(ref: str, project: str = "", path: str = "") -> str:
        where, r, p = repo(project), _ref(ref), _path(path)
        if p:
            return git(where, "show", "--no-ext-diff", "--no-textconv", f"{r}:{p}")
        return git(where, "show", "--stat", "--patch", "--no-ext-diff", "--no-textconv", "--format=%H%n%an %ad%n%n%B", "--date=iso", r)

    @srv.tool("diff", "두 판 사이 차이 (base → head). stat만 원하면 only_stat=true.",
              {**proj, "base": {"type": "string", "description": "기준 판 (예: main)"},
               "head": {"type": "string", "description": "비교할 판 (예: studio/T0003, 비우면 HEAD)"},
               "path": {"type": "string"}, "only_stat": {"type": "boolean"}},
              ["base"])
    def diff(base: str, project: str = "", head: str = "", path: str = "", only_stat: bool = False) -> str:
        args = ["diff", "--no-ext-diff", "--no-textconv", "--stat" if only_stat else "--patch-with-stat", _ref(base, "base"),
                _ref(head, "head") if head else "HEAD"]
        p = _path(path)
        return git(repo(project), *args, "--", *([p] if p else []))

    @srv.tool("blame", "파일의 줄마다 마지막으로 바꾼 커밋 (start~end 줄, 최대 200줄).",
              {**proj, "path": {"type": "string"}, "ref": {"type": "string", "description": "비우면 HEAD"},
               "start": {"type": "integer"}, "end": {"type": "integer"}},
              ["path"])
    def blame(path: str, project: str = "", ref: str = "", start: int = 1, end: int = 0) -> str:
        p = _path(path)
        if not p:
            raise ToolError("path를 적어 주세요.")
        s = _limit(start, 1, 1_000_000)
        try:
            e = int(end or 0)
        except (TypeError, ValueError):
            e = 0
        e = min(e if e >= s else s + 99, s + 199)
        return git(repo(project), "blame", "--no-textconv", "--date=short", "-L", f"{s},{e}", _ref(ref) if ref else "HEAD", "--", p)

    @srv.tool("branches", "브랜치 목록과 각 브랜치의 마지막 커밋 (작업 브랜치는 studio/T0000 모양).", proj)
    def branches(project: str = "") -> str:
        return git(repo(project), "branch", "--list", "--sort=-committerdate", "--format=%(refname:short) %(objectname:short) %(committerdate:short) %(subject)")

    return srv


def main() -> None:
    setup_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", action="append", default=[], help="키=저장소 경로")
    a = ap.parse_args()
    projects = {}
    for item in a.project:
        key, _, where = item.partition("=")
        if key and where and Path(where).is_dir():
            projects[key] = Path(where)
    build(projects).serve()


if __name__ == "__main__":
    main()
