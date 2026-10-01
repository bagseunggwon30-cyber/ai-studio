"""신뢰 검증 실행기.

1) 후보 커밋을 git archive로 깨끗한 폴더에 꺼낸다 (.git 없음, 작업 폴더 잔여물 없음).
2) trusted/acceptance/<프로젝트>를 스냅샷의 acceptance/에 넣는다. 작업자는 이 폴더를 바꿀 수 없다.
3) trusted/projects/<프로젝트>.toml에 적힌 명령만 실행한다.
4) 결과 파일을 읽고, 기대한 테스트 수만큼 실제로 실행됐는지까지 확인한다.
   (테스트 0개 통과, 결과 파일 없음, 건너뜀은 모두 실패로 본다)
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Callable

from .config import Config, ProjectConfig
from .gitops import GitError, changed_paths, export_snapshot, normalize_rel
from .runtimes import run_process
from .util import atomic_write_json, clean_child_env, now_iso, read_json, read_text_tail, sha256_dir

FIXTURES_DIR = "fixtures"

# 첫 글자에 BOM(EF BB BF)이 붙었는지 볼 글 파일 확장자
BOM_TEXT_EXTS = frozenset(
    ".md .txt .gd .tscn .tres .cfg .godot .json .py .cs .csv .toml .yaml .yml .ini .html .css .js".split()
)
BOM_MAX_FILES = 20
_BOM = bytes([0xEF, 0xBB, 0xBF])  # UTF-8 BOM


def suite_path(cfg: Config, project: ProjectConfig) -> Path | None:
    suite = (project.qa or {}).get("suite")
    return (cfg.root / suite) if suite else None


def suite_hash(cfg: Config, project: ProjectConfig) -> str | None:
    path = suite_path(cfg, project)
    if not path or not path.exists():
        return None
    digest, _ = _suite_digest(path)
    return digest


def _suite_digest(path: Path) -> tuple[str, list[dict]]:
    digest, files = sha256_dir(path)
    files = [f for f in files if not f["path"].startswith(FIXTURES_DIR + "/")]
    return digest, files


def find_bom_files(repo: Path, base: str | None, sha: str, snapshot: Path) -> list[str]:
    """base와 후보 사이에 바뀐 글 파일 가운데 맨 앞에 UTF-8 BOM이 붙은 것의 상대 경로.

    알림용이다. base를 모르거나 git이 실패하면 조용히 빈 목록을 돌려주고, 검증 결과에는 영향을 주지 않는다.
    """
    if not base or not sha:
        return []
    try:
        paths = changed_paths(repo, base, sha)
    except (GitError, OSError, ValueError):
        return []
    found: list[str] = []
    for raw in paths:
        rel = normalize_rel(raw)
        if rel is None or Path(rel).suffix.lower() not in BOM_TEXT_EXTS:
            continue
        fp = snapshot / rel
        try:
            if fp.is_symlink() or not fp.is_file():
                continue
            with open(fp, "rb") as f:
                head = f.read(3)
        except OSError:
            continue
        if head == _BOM:
            found.append(rel)
            if len(found) >= BOM_MAX_FILES:
                break
    return found


def run_qa(
    cfg: Config,
    project: ProjectConfig,
    sha: str,
    qa_dir: Path,
    should_stop: Callable[[], bool] = lambda: False,
    overrides: dict[str, Path] | None = None,
    base: str | None = None,
) -> dict:
    """후보 커밋 sha를 검증하고 요약을 돌려준다. 전체 증거는 qa_dir/evidence.json에 남긴다.

    base(기준 커밋)를 주면 base와 후보 사이에 바뀐 글 파일 중 BOM이 붙은 것을 결과의 bom_files로 알린다.
    """
    qcfg = project.qa or {}
    qa_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    evidence: dict = {
        "qa_id": qa_dir.name,
        "project": project.key,
        "candidate_sha": sha,
        "started_at": now_iso(),
        "commands": [],
        "overrides": {k: str(v) for k, v in (overrides or {}).items()},
    }

    bom_files: list[str] = []

    def finish(verdict: str, reason: str, tests: list[dict] | None = None, extra: dict | None = None) -> dict:
        tests = tests or []
        passed = sum(1 for t in tests if t.get("ok"))
        summary = {
            "qa_id": qa_dir.name,
            "verdict": verdict,
            "reason": reason,
            "passed": passed,
            "total": len(tests),
            "expected_total": qcfg.get("expected_total"),
            "failed": [t.get("name") for t in tests if not t.get("ok")],
            "tests": tests[:100],
            "candidate_sha": sha,
            "suite_hash": evidence.get("suite_hash"),
            "duration_s": round(time.monotonic() - t0, 1),
            "at": now_iso(),
        }
        if bom_files:
            summary["bom_files"] = bom_files
        if extra:
            summary.update(extra)
        evidence.update(summary)
        evidence["finished_at"] = now_iso()
        atomic_write_json(qa_dir / "evidence.json", evidence)
        return summary

    # 리뷰어도 이 스냅샷을 읽으므로 검증 명령이 없어도 항상 꺼낸다.
    snapshot = qa_dir / "snapshot"
    if snapshot.exists():
        shutil.rmtree(snapshot, ignore_errors=True)
    export_snapshot(project.repo, sha, snapshot)
    for rel, src in (overrides or {}).items():
        dest = snapshot / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    if not overrides:
        bom_files = find_bom_files(project.repo, base, sha, snapshot)

    commands = qcfg.get("commands") or []
    if not commands:
        return finish("none", "이 프로젝트에는 자동 검증이 없습니다. 리뷰와 CEO 확인으로 판단합니다.")

    mount = str(qcfg.get("mount", "acceptance"))
    suite = suite_path(cfg, project)
    if suite is None or not suite.exists():
        return finish("fail", f"신뢰 테스트 폴더가 없습니다: {qcfg.get('suite')}")
    if (snapshot / mount).exists():
        return finish("fail", f"후보 커밋에 예약된 폴더 '{mount}/'가 들어 있습니다.")
    shutil.copytree(suite, snapshot / mount, ignore=shutil.ignore_patterns(FIXTURES_DIR))
    digest, files = _suite_digest(suite)
    evidence["suite_hash"] = digest
    evidence["suite_files"] = files

    results_path = qa_dir / "results.json"
    results_path.unlink(missing_ok=True)
    values = {
        "godot": cfg.godot_path(),
        "python": cfg.python_path(),
        "snapshot": str(snapshot),
        "results": results_path.as_posix(),
        "suite": str(snapshot / mount),
        "qa_dir": str(qa_dir),
    }
    timeout_s = cfg.limit("qa_timeout_min") * 60
    for i, cmd in enumerate(commands):
        argv = [_fill(str(part), values) for part in cmd]
        if not argv or not argv[0]:
            return finish("fail", "검증 도구 경로가 비어 있습니다. studio.toml의 [tools]를 확인하세요.")
        out_path, err_path = qa_dir / f"cmd{i}.out.txt", qa_dir / f"cmd{i}.err.txt"
        try:
            code, reason, dur = run_process(
                argv,
                cwd=snapshot,
                stdin_text="",
                stdout_path=out_path,
                stderr_path=err_path,
                timeout_s=timeout_s,
                should_stop=should_stop,
                env=clean_child_env(),
            )
        except OSError as e:
            return finish("fail", f"검증 명령을 실행하지 못했습니다: {e}")
        evidence["commands"].append({"argv": argv, "exit": code, "reason": reason, "duration_s": round(dur, 1)})
        if reason == "stopped":
            return finish("stopped", "긴급 정지로 검증이 중단됐습니다.")
        if reason == "timeout":
            return finish("fail", f"검증 명령이 {timeout_s // 60}분 안에 끝나지 않았습니다.")
        if code != 0 and i < len(commands) - 1:
            tail = read_text_tail(err_path, 600) or read_text_tail(out_path, 600)
            return finish("fail", f"준비 명령 {i + 1}이 실패했습니다 (exit {code}). {tail.strip()}")

    last_exit = evidence["commands"][-1]["exit"]
    results = read_json(results_path)
    if not isinstance(results, dict):
        tail = read_text_tail(qa_dir / f"cmd{len(commands) - 1}.err.txt", 800)
        return finish("fail", f"테스트 결과 파일이 만들어지지 않았습니다 (exit {last_exit}). {tail.strip()}")

    tests = [
        {
            "name": str(t.get("name", "?")),
            "ok": bool(t.get("ok")),
            "skipped": bool(t.get("skipped", False)),
            "message": str(t.get("message", ""))[:400],
        }
        for t in results.get("tests", [])
        if isinstance(t, dict)
    ]
    extra = {"engine": results.get("engine")}
    expected = qcfg.get("expected_total")
    skipped = [t for t in tests if t["skipped"]]
    failed = [t for t in tests if not t["ok"]]
    if not tests:
        return finish("fail", "실행된 테스트가 0개입니다.", tests, extra)
    if expected and len(tests) != int(expected):
        return finish("fail", f"테스트 {expected}개가 실행돼야 하는데 {len(tests)}개만 실행됐습니다.", tests, extra)
    if skipped:
        return finish("fail", f"건너뛴 테스트가 있습니다: {', '.join(t['name'] for t in skipped)}", tests, extra)
    if failed:
        return finish("fail", f"{len(failed)}개 실패: {', '.join(t['name'] for t in failed)}", tests, extra)
    if last_exit != 0:
        return finish("fail", f"테스트는 모두 통과로 기록됐지만 종료 코드가 {last_exit}입니다.", tests, extra)
    return finish("pass", f"{len(tests)}개 모두 통과", tests, extra)


def run_selftest(cfg: Config, project: ProjectConfig, main_sha: str, work_dir: Path) -> dict:
    """신뢰 테스트가 일부러 망가뜨린 구현을 실제로 잡아내는지 확인한다.

    trusted/acceptance/<프로젝트>/fixtures/manifest.json:
      [{"file": "broken_run_state.gd", "target": "src/core/run_state.gd", "expect": "fail"}]
    """
    suite = suite_path(cfg, project)
    manifest = read_json(suite / FIXTURES_DIR / "manifest.json", []) if suite else []
    report = {"project": project.key, "at": now_iso(), "cases": []}
    for i, case in enumerate(manifest):
        src = suite / FIXTURES_DIR / case["file"]
        result = run_qa(cfg, project, main_sha, work_dir / f"case{i}", overrides={case["target"]: src})
        ok = result["verdict"] == case.get("expect", "fail")
        report["cases"].append({
            "fixture": case["file"],
            "expect": case.get("expect", "fail"),
            "got": result["verdict"],
            "failed_tests": result.get("failed", []),
            "ok": ok,
        })
    report["ok"] = bool(report["cases"]) and all(c["ok"] for c in report["cases"])
    atomic_write_json(work_dir / "selftest.json", report)
    return report


def _fill(text: str, values: dict[str, str]) -> str:
    for key, val in values.items():
        text = text.replace("{" + key + "}", val)
    return text
