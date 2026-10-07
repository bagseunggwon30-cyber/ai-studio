"""Model-free regression runner. Publish counts/IDs, never raw local logs."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from studio.util import atomic_write_json, clean_child_env, no_window_flags


def source_state():
    paths = subprocess.check_output(["git", "ls-files", "-z", "-co", "--exclude-standard", "--",
        "studio", "ui", "tests", "tools", ".github", "AGENTS.md", "studio.py"], cwd=ROOT)
    rows = sorted(set(name for name in paths.decode("utf-8").split("\0") if name))
    hashes = [(name, hashlib.sha256((ROOT / name).read_bytes()).hexdigest()) for name in rows
              if (ROOT / name).is_file()]
    return {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
            "source_sha256": hashlib.sha256(json.dumps(hashes, separators=(",", ":")).encode()).hexdigest(),
            "source_files": len(hashes)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=ROOT / "docs/verification/followup-regression.json")
    args = parser.parse_args()
    start = time.monotonic()
    before = source_state()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.with_suffix(".log").open("w", encoding="utf-8") as log:
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        env = clean_child_env()
        ui = []
        for path in sorted((ROOT / "ui").glob("*.js")):
            run = subprocess.run(["node", "--check", str(path)], cwd=ROOT, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30, creationflags=no_window_flags())
            log.write(run.stdout.decode("utf-8", "replace"))
            ui.append({"file": path.name, "pass": run.returncode == 0})
        ui_suites = []
        for name in ("home_sim.js", "finder_sim.js", "media_sim.js", "rooms_sim.js", "gateway_sim.js", "m_sim.js"):
            run = subprocess.run(["node", "tools/dev/" + name], cwd=ROOT, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, creationflags=no_window_flags())
            log.write(run.stdout.decode("utf-8", "replace"))
            ui_suites.append({"file": name, "pass": run.returncode == 0})
        board = subprocess.run(["node", "tools/dev/board_sim.js"], cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, creationflags=no_window_flags())
        output = board.stdout.decode("utf-8", "replace")
        log.write(output)
    after = source_state()
    match = re.search(r"진행판 점검 통과 \((\d+)개\)", output)
    failures = [{"test": test.id(), "kind": kind} for kind, group in
                (("failure", result.failures), ("error", result.errors)) for test, _ in group]
    stable = before == after
    report = {"status": "pass" if result.wasSuccessful() and all(row["pass"] for row in ui)
              and board.returncode == 0 and match and stable and all(row["pass"] for row in ui_suites) else "fail",
              "code": before, "source_unchanged_during_run": stable,
              "ui_suites": ui_suites,
              "python": {"total": result.testsRun,
                  "passed": result.testsRun - len(result.skipped) - len(result.failures) - len(result.errors)
                            - len(result.expectedFailures) - len(result.unexpectedSuccesses),
                  "skipped": len(result.skipped), "failures": len(result.failures), "errors": len(result.errors),
                  "expected_failures": len(result.expectedFailures), "unexpected_successes": len(result.unexpectedSuccesses),
                  "skipped_tests": [test.id() for test, _ in result.skipped], "failed_tests": failures},
              "progress_board": {"pass": board.returncode == 0 and bool(match),
                  "total": int(match.group(1)) if match else None},
              "javascript_syntax": ui, "duration_s": round(time.monotonic() - start, 1),
              "model_generation_calls": 0, "real_logins_required": False,
              "runtime": {"python": sys.version.split()[0], "platform": sys.platform},
              "raw_log_published": False}
    atomic_write_json(args.report, report)
    print(json.dumps({key: report[key] for key in ("status", "python", "progress_board", "duration_s")}, ensure_ascii=False))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
