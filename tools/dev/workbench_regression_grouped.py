"""Run every normal discovery case in isolated module processes on Windows.

No test selection is relaxed: the final report checks the exact discovery IDs.
Workers use the existing tests/helpers.py fixtures and runtimes.
"""
import argparse
import concurrent.futures
import faulthandler
import json
import os
import subprocess
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from studio.util import append_jsonl, atomic_write_json, clean_child_env, now_iso


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def run_worker(args):
    expected = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    suite = unittest.defaultTestLoader.loadTestsFromNames(expected)
    actual = [case.id() for case in flatten(suite)]
    if actual != expected:
        raise RuntimeError("Worker cases differ from normal discovery")

    class Progress(unittest.TextTestResult):
        def startTest(self, test):
            append_jsonl(Path(args.progress), {"at": now_iso(), "event": "start", "test": test.id()})
            super().startTest(test)

        def stopTest(self, test):
            append_jsonl(Path(args.progress), {"at": now_iso(), "event": "end", "test": test.id()})
            super().stopTest(test)

    faulthandler.dump_traceback_later(60, repeat=True)
    result = unittest.TextTestRunner(verbosity=1, resultclass=Progress).run(suite)
    faulthandler.cancel_dump_traceback_later()
    report = {"at": now_iso(), "status": "pass" if result.wasSuccessful() else "fail", "total": result.testsRun,
              "case_ids": actual, "failures": [{"test": t.id(), "trace": trace} for t, trace in result.failures],
              "errors": [{"test": t.id(), "trace": trace} for t, trace in result.errors],
              "skipped": [{"test": t.id(), "reason": reason} for t, reason in result.skipped]}
    atomic_write_json(Path(args.report), report)
    return 0 if result.wasSuccessful() else 1


def main(args):
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    groups = defaultdict(list)
    discovered = []
    for case in flatten(suite):
        discovered.append(case.id())
        groups[type(case).__module__].append(case.id())
    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out / "discovery.json", {"at": now_iso(), "discovery": "unittest discover -s tests -t .",
                                               "case_ids": discovered, "total": len(discovered), "modules": list(groups)})

    def execute(entry):
        module, ids = entry
        prefix = out / module.replace('.', '_')
        cases = prefix.with_suffix(".cases.json")
        report = prefix.with_suffix(".result.json")
        progress = prefix.with_suffix(".progress.jsonl")
        atomic_write_json(cases, ids)
        env = clean_child_env()
        env["PYTHONIOENCODING"] = "utf-8"
        with prefix.with_suffix(".stdout.log").open("w", encoding="utf-8") as stdout, prefix.with_suffix(".stderr.log").open("w", encoding="utf-8") as stderr:
            process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", "--cases", str(cases),
                                      "--report", str(report), "--progress", str(progress)], cwd=ROOT, env=env,
                                     stdout=stdout, stderr=stderr, timeout=900,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        value = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {
            "status": "interrupted", "total": 0, "case_ids": [], "failures": [], "errors": [], "skipped": []}
        value.update(module=module, exit_code=process.returncode)
        append_jsonl(out / "modules.jsonl", {"at": now_iso(), "module": module, "status": value["status"], "total": value["total"], "exit_code": process.returncode})
        return value

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(execute, entry): entry[0] for entry in groups.items()}
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"module": futures[future], "status": "interrupted", "total": 0, "case_ids": [],
                                "failures": [], "errors": [{"test": futures[future], "trace": str(exc)}], "skipped": []})
    executed = [case for result in results for case in result["case_ids"]]
    exact = sorted(executed) == sorted(discovered)
    failed = [value for result in results for value in result["failures"]]
    errors = [value for result in results for value in result["errors"]]
    skips = [value for result in results for value in result["skipped"]]
    ok = exact and all(result["status"] == "pass" and result.get("exit_code") == 0 for result in results)
    report = {"at": now_iso(), "command": "python tools/dev/workbench_regression_grouped.py", "discovery": "unittest discover -s tests -t .",
              "status": "pass" if ok else "fail", "total": sum(result["total"] for result in results),
              "passed": sum(result["total"] for result in results) - len(failed) - len(errors) - len(skips),
              "failures": failed, "errors": errors, "skipped": skips, "exact_discovery_match": exact,
              "discovery_total": len(discovered), "modules": results, "real_model_calls": 0}
    atomic_write_json(ROOT / args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key != "modules"}, ensure_ascii=False), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--cases")
    parser.add_argument("--progress")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--output", default="output/workbench-visual-polish-regression")
    parser.add_argument("--report", default="docs/verification/workbench-visual-polish-regression.json")
    args = parser.parse_args()
    sys.exit(run_worker(args) if args.worker else main(args))
