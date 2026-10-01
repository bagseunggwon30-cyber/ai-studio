"""테스트용 임시 회사: 작은 제품 저장소 + 파이썬 신뢰 검사 + 가짜 실행기."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio import gitops  # noqa: E402
from studio.config import load_config  # noqa: E402
from studio.engine import Engine  # noqa: E402
from studio.runtimes import FakeRuntime  # noqa: E402
from studio.store import Store  # noqa: E402

CHECK_PY = textwrap.dedent(
    """
    import argparse, json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--root")
    ap.add_argument("--out")
    a = ap.parse_args()
    p = Path(a.root) / "docs" / "answer.txt"
    val = p.read_text(encoding="utf-8").strip() if p.exists() else None
    tests = [
        {"name": "answer_exists", "ok": p.exists(), "message": "" if p.exists() else "docs/answer.txt 없음"},
        {"name": "answer_is_42", "ok": val == "42", "message": f"값 {val!r}"},
    ]
    Path(a.out).write_text(json.dumps({"tests": tests}), encoding="utf-8")
    """
)

STUDIO_TOML = textwrap.dedent(
    """
    [studio]
    name = "Test Studio"
    port = 0
    auto_run = false

    [limits]
    max_attempts = 2
    task_timeout_min = 1
    max_runs_per_day = 100
    qa_timeout_min = 1

    [roles.producer]
    title = "기획 담당"
    runtime = "codex"
    sandbox = "read-only"

    [roles.builder]
    title = "개발 담당"
    runtime = "codex"
    sandbox = "workspace-write"

    [roles.reviewer]
    title = "리뷰 담당"
    runtime = "claude"
    fallback_runtime = "codex"
    sandbox = "read-only"

    [roles.analyst]
    title = "리서치·문서 담당"
    runtime = "codex"
    sandbox = "workspace-write"
    """
)

PROJECT_TOML = textwrap.dedent(
    """
    key = "demo"
    title = "Demo"
    kind = "generic"
    repo = "projects/demo"
    default_allowed_paths = ["docs/**"]

    [qa]
    suite = "trusted/acceptance/demo"
    expected_total = 2
    commands = [["{python}", "{suite}/check.py", "--root", "{snapshot}", "--out", "{results}"]]
    """
)


def rmtree_force(path: Path) -> None:
    def onexc(func, p, exc):  # git 객체 파일은 읽기 전용이라 권한을 풀고 지운다
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onexc=onexc)


class TempStudio:
    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="studio-test-"))
        (self.root / "studio.toml").write_text(STUDIO_TOML, encoding="utf-8")
        shutil.copytree(ROOT / "company", self.root / "company")
        (self.root / "trusted" / "projects").mkdir(parents=True)
        (self.root / "trusted" / "projects" / "demo.toml").write_text(PROJECT_TOML, encoding="utf-8")
        suite = self.root / "trusted" / "acceptance" / "demo"
        suite.mkdir(parents=True)
        (suite / "check.py").write_text(CHECK_PY, encoding="utf-8")
        repo = self.root / "projects" / "demo"
        (repo / "docs").mkdir(parents=True)
        (repo / "README.md").write_text("# demo\n", encoding="utf-8")
        (repo / "AGENTS.md").write_text("규칙\n", encoding="utf-8")
        (repo / "docs" / "notes.md").write_text("메모\n", encoding="utf-8")
        gitops.init_repo(repo, "main")
        gitops.commit_all(repo, "init")
        self.repo = repo
        self.cfg = load_config(self.root)
        self.store = Store(self.cfg.data_dir)
        self.behavior = default_behavior
        self.engine = Engine(self.cfg, self.store, runtime_factory=self._runtime)

    def _runtime(self, name: str) -> FakeRuntime:
        return FakeRuntime(lambda spec: self.behavior(spec, name))

    def close(self) -> None:
        self.engine.shutdown(2)
        rmtree_force(self.root)


def default_behavior(spec, runtime=None):
    if spec.role == "producer":
        return {
            "structured": {
                "summary": "두 단계로 나눕니다.",
                "tasks": [
                    {"title": "정답 파일", "kind": "build", "brief": "docs/answer.txt에 42", "acceptance": ["검사 통과"], "allowed_paths": ["docs/**"], "depends_on": []},
                    {"title": "메모 보강", "kind": "build", "brief": "메모", "acceptance": ["메모"], "allowed_paths": ["docs/**", "acceptance/**"], "depends_on": [0]},
                ],
                "risks": [],
                "questions": [],
            }
        }
    if spec.role == "reviewer":
        return {"structured": {"verdict": "approve", "summary": "좋음", "findings": []}}
    return {"files": {"docs/answer.txt": "42\n"}, "message": "완료 보고"}
