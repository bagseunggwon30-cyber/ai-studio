"""Controlled execution-record examples; no employee or model execution."""
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio
from studio.server import StudioServer
from studio.util import now_iso


def main():
    company = TempStudio()
    server = None
    try:
        shutil.copytree(ROOT / "ui", company.root / "ui")
        company.cfg.fake_runtimes = True
        cases = [
            ("기존 실행 로그에 모델 ID 없음", {}),
            ("응답 메타데이터의 모델 ID 있음", {"provider_model": "served-model-example",
                "provider_model_source": "response.completed.response.model", "model_identity_reason": "response_metadata"}),
            ("실행 오류를 모델 미제공과 구분", {"ok": False, "error_kind": "login",
                "model_identity_reason": "execution_failed_without_model_id"}),
            ("가짜 실행기 확인", {"actual_runtime": "fake", "model_identity_reason": "fake_runtime"}),
            ("다른 공급자로 대체 실행", {"requested_provider": "grok", "requested_model": "grok-4.7",
                "fallback": True, "fallback_reason": "시험용 대체 사유"}),
            ("긴 모델 이름과 HTML 문자열", {"requested_model": '<img src=x onerror="alert(1)">' + "longmodel" * 40}),
        ]
        for title, extra in cases:
            task = company.store.create_task(title=title, kind="build", role="builder", project="demo",
                status="blocked", brief="실행 정보 표시 시험", blocked_reason="임시 화면 시험", acceptance=[])
            company.store.add_run({"run_id": "fixture-" + task.id, "task": task.id, "role": "builder", "stage": "build1",
                "requested_provider": "codex", "requested_model": "gpt-6.1-sol", "actual_runtime": "codex",
                "runtime": "codex", "runtime_version": "codex-cli 0.160.0", "provider_model": None,
                "started_at": now_iso(), "ok": True, "duration_s": 1, "usage": {}, **extra})
            task.runs.append("fixture-" + task.id)
            company.store.save(task)
        server = StudioServer(company.cfg, company.store, company.engine, 8797)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(json.dumps({"url": "http://127.0.0.1:8797/", "cases": len(cases), "model_calls": 0}), flush=True)
        for line in sys.stdin:
            if line.strip() == "stop": break
            if line.strip() == "update":
                task = company.store.get("T0002")
                rid = "fixture-T0002-update"
                company.store.add_run({"run_id": rid, "task": task.id, "role": "builder", "stage": "build2",
                    "runtime": "codex", "actual_runtime": "codex", "requested_provider": "codex",
                    "requested_model": "gpt-6.1-sol", "runtime_version": "codex-cli 0.160.0",
                    "provider_model": "served-updated-fixture", "provider_model_source": "response.completed.response.model",
                    "model_identity_reason": "response_metadata", "ok": True, "duration_s": 1,
                    "usage": {}, "started_at": now_iso()})
                task.runs.append(rid)
                company.store.save(task)
                print(json.dumps({"fixture_updated": True, "model_calls": 0}), flush=True)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        company.close()


if __name__ == "__main__": main()
