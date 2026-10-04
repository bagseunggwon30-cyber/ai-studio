"""Disposable planning-question UI fixture. No real login or model calls."""
from pathlib import Path
import argparse
import json
import shutil
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dataclasses import replace
from tests.helpers import TempStudio, default_behavior
from studio.server import StudioServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8797)
    args = parser.parse_args()
    company = TempStudio()
    server = None
    try:
        shutil.copytree(ROOT / "ui", company.root / "ui")
        company.cfg.fake_runtimes = True
        company.cfg.roles["reviewer"].runtime = "codex"
        project = company.cfg.projects["demo"]
        project.title = "Core Courier (시험)"
        project.description = "임시 게임 프로젝트. AI Studio 프로그램 자체와 별개예요."
        company.cfg.projects["reports"] = replace(project, key="reports", title="보고서 자료 (시험)",
            description="보고서를 저장하는 임시 프로젝트예요.")
        def respond(spec, runtime=None):
            if spec.role == "producer" and "현재 게임의 정답 화면" not in spec.prompt:
                return {"structured": {"summary": "선택한 게임과 요청한 AI Studio 화면이 달라 확인이 필요해요.",
                    "tasks": [], "questions": ["현재 게임의 화면을 고칠까요? AI Studio 자체 수정은 별도 프로젝트 등록이 필요해요."],
                    "risks": ["다른 프로젝트를 잘못 수정하지 않도록 대상 확인이 필요해요."], "skills_used": []}}
            return default_behavior(spec, runtime)
        company.behavior = respond
        task = company.engine.submit_directive("업무일지·완성작·회의실 UI가 AI Studio 메인 화면과 맞지 않아요. "
            + "긴 요청을 끝까지 확인할 수 있어야 해요. " * 30 + "LONGTOKEN" * 45, "demo")
        company.engine._run_plan(company.store.get(task.id))
        failed = company.engine.create_task({"title": "연결 오류는 질문 대기와 구분해요", "kind": "build", "project": "demo",
            "brief": "긴 오류 설명 " * 150, "allowed_paths": ["docs/**"], "acceptance": ["LONGTOKEN" * 30] * 8})
        company.store.block(failed, "실행 연결 오류 " * 100)
        server = StudioServer(company.cfg, company.store, company.engine, args.port)
        company.engine.start()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        print(json.dumps({"url": f"http://127.0.0.1:{args.port}/", "planning_task": task.id,
            "error_task": failed.id, "mode": "temporary company / fake runtime", "model_calls": 0}), flush=True)
        for line in sys.stdin:
            if line.strip() == "stop": break
    finally:
        if server:
            server.shutdown()
            server.server_close()
        assert company.root.resolve().parent == Path(tempfile.gettempdir()).resolve()
        assert company.root.name.startswith("studio-test-")
        company.close()


if __name__ == "__main__":
    main()
