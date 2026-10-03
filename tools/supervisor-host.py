"""Local supervisor API host without workers or model execution.

Use normal studio.py serve after stopping this connection-only host when the CEO
authorizes actual agent work. This host does not recover or rerun existing tasks.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio.config import load_config
from studio.engine import Engine
from studio.runtimes import RunResult
from studio.server import StudioServer, StudioHandler
from studio.store import Store


class NoExecution:
    name = "disabled"
    def run(self, spec, stop):
        return RunResult(False, self.name, spec.model, None, 0, error_kind="policy",
                         error="연결 전용 서버에서는 모델을 실행하지 않습니다.", side_effects="none")


class ConnectionHandler(StudioHandler):
    def do_GET(self):
        if urlparse(self.path).path == "/mcp":
            from studio.supervisor_mcp_http import reject_stream
            return reject_stream(self)
        if not self._host_kind():
            return self._error(403, "허용되지 않은 Host")
        if urlparse(self.path).path != "/supervisor/health":
            return self._error(404, "연결 전용 서버입니다. 대시보드는 일반 serve 모드에서 여세요.")
        self._json({"schema":"studio.supervisor-host/v1", "mode":"connection-only",
                    "company_id":hashlib.sha256(str(self.server.cfg.root).encode()).hexdigest(),
                    "workers":0, "model_generation_calls":0})

    def do_POST(self):
        if urlparse(self.path).path not in ("/supervisor/v1","/mcp"):
            self.close_connection = True
            return self._error(403, "연결 전용 서버는 감독 API만 제공합니다.")
        super().do_POST()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535: parser.error("잘못된 포트")
    cfg = load_config(ROOT)
    store = Store(cfg.data_dir)
    store.acquire_process_lock()
    server = None
    try:
        engine = Engine(cfg, store, runtime_factory=lambda name: NoExecution())
        server = StudioServer(cfg, store, engine, args.port)
        server.RequestHandlerClass = ConnectionHandler
        print(json.dumps({"status":"ready", "mode":"connection-only", "port":args.port,
                          "workers":0,"model_generation_calls":0}),flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server: server.server_close()
        store.release_process_lock()


if __name__ == "__main__": main()
