"""Disposable UI preview using the existing TempStudio/Engine/FakeRuntime."""
import argparse
import json
import shutil
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio, default_behavior
from studio.server import StudioServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--flow-gates", action="store_true", help="Pause the existing fake builder/reviewer until temporary release files appear")
    args = parser.parse_args()
    company = TempStudio()
    gate_stop = threading.Event()
    builds = 0
    def behavior(spec, runtime):
        nonlocal builds
        if args.flow_gates and spec.role in {"builder", "reviewer"}:
            release = company.root / ("flow-release-build" if spec.role == "builder" else "flow-release-review")
            deadline = time.monotonic() + 90
            while not release.is_file() and not gate_stop.wait(.05):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Disposable preview gate timed out")
        result = default_behavior(spec, runtime)
        if spec.role == "builder":
            builds += 1
            result["files"]["docs/revision.txt"] = f"Preview candidate {builds}\n"
            if "계약파일을 추가" in spec.prompt:
                result["files"]["docs/contract.txt"] = "CEO requested contract\n"
        return result
    company.behavior = behavior
    server = None
    try:
        company.cfg.fake_runtimes = True
        shutil.copytree(ROOT / "ui", company.root / "ui")
        # Existing fake runtime supplied by tests.helpers, with normal QA/approval.
        server = StudioServer(company.cfg, company.store, company.engine, args.port)
        company.store.acquire_process_lock()
        company.engine.start()
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True).start()
        print(json.dumps({"url": f"http://127.0.0.1:{args.port}/#view=workbench", "root": str(company.root),
                          "mode": "disposable company / existing fake runtime", "real_model_calls": 0}), flush=True)
        for line in sys.stdin:
            if line.strip() == "stop":
                break
    finally:
        gate_stop.set()
        if server:
            server.shutdown()
            server.server_close()
        company.store.release_process_lock()
        company.close()


if __name__ == "__main__":
    main()
