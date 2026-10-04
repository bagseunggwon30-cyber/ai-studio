"""Disposable UI preview using the existing TempStudio/Engine/FakeRuntime."""
import argparse
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio
from studio.server import StudioServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8798)
    args = parser.parse_args()
    company = TempStudio()
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
        if server:
            server.shutdown()
            server.server_close()
        company.store.release_process_lock()
        company.close()


if __name__ == "__main__":
    main()
