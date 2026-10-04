"""Run the normal unittest discovery with append-only progress and deadlock traces."""
import faulthandler
import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from studio.util import append_jsonl, atomic_write_json, now_iso


class Progress(unittest.TextTestResult):
    def startTest(self, test):
        append_jsonl(PROGRESS_PATH, {"at": now_iso(), "event": "start", "test": test.id()})
        super().startTest(test)

    def stopTest(self, test):
        append_jsonl(PROGRESS_PATH, {"at": now_iso(), "event": "end", "test": test.id()})
        super().stopTest(test)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="docs/verification/workbench-regression.json")
    parser.add_argument("--progress", default="output/workbench-test-progress.jsonl")
    args = parser.parse_args()
    PROGRESS_PATH = ROOT / args.progress
    faulthandler.dump_traceback_later(60, repeat=True)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1, resultclass=Progress).run(suite)
    faulthandler.cancel_dump_traceback_later()
    report = {"at": now_iso(), "command": "python tools/dev/workbench_regression.py", "discovery": "unittest discover -s tests -t .",
              "status": "pass" if result.wasSuccessful() else "fail", "total": result.testsRun,
              "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
              "failures": [{"test": t.id(), "trace": trace} for t, trace in result.failures],
              "errors": [{"test": t.id(), "trace": trace} for t, trace in result.errors],
              "skipped": [{"test": t.id(), "reason": reason} for t, reason in result.skipped], "real_model_calls": 0}
    atomic_write_json(ROOT / args.report, report)
    sys.exit(not result.wasSuccessful())
