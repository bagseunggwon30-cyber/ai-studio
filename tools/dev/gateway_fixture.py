"""연습용 서버 (외부 연결 화면 확인용): 임시 회사 + 가짜 실행기. 진짜 직원·Grok·진짜 회사(8765)·인터넷은 쓰지 않는다.

  python tools/dev/gateway_fixture.py --port 8805 --gateway-port 8806   # 시작하면 JSON 한 줄로 주소를 알린다. 끄려면 표준 입력에 stop
대시보드는 --port, MCP 연결 문 서버는 --gateway-port(127.0.0.1에만)에 열린다 — 화면에서 '외부 연결 받기'를 켜야 열린다.
프로젝트: demo(임시 회사 기본) · design-1 '동네 카페 메뉴판'(권한 화면에서 프로젝트가 둘 보이게).
"""
import argparse
import json
import os
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio  # noqa: E402
from studio.server import StudioServer  # noqa: E402


def detach_stdin():
    """멈춤 신호(표준 입력 파이프)를 읽는 동안 자식 프로세스(git)가 같은 파이프를 물려받으면 윈도우에서 멈춘다 (rooms_fixture.py와 같은 처리)."""
    reader = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, 0)
    os.close(nul)
    if os.name == "nt":
        import ctypes
        import msvcrt
        kernel = ctypes.windll.kernel32
        kernel.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        kernel.SetStdHandle(ctypes.c_ulong(-10).value, msvcrt.get_osfhandle(0))
    return reader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8805)
    parser.add_argument("--gateway-port", type=int, default=8806)
    args = parser.parse_args()
    stop_reader = detach_stdin()
    company = TempStudio()
    server = None
    try:
        company.cfg.fake_runtimes = True
        shutil.copytree(ROOT / "ui", company.root / "ui")
        company.engine.create_project({"key": "design-1", "title": "동네 카페 메뉴판", "kind": "design", "description": "카페 메뉴판 시안."})
        server = StudioServer(company.cfg, company.store, company.engine, args.port)
        server.gateway.bind_port = args.gateway_port
        company.store.acquire_process_lock()
        company.engine.start()
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True).start()
        print(json.dumps({"url": f"http://127.0.0.1:{args.port}/", "gateway_port": args.gateway_port, "root": str(company.root),
                          "mode": "disposable company / existing fake runtime", "real_model_calls": 0}), flush=True)
        for line in stop_reader:
            if line.strip() == "stop":
                break
    finally:
        if server:
            server.gateway.stop()
            server.shutdown()
            server.server_close()
        company.store.release_process_lock()
        company.close()


if __name__ == "__main__":
    main()
