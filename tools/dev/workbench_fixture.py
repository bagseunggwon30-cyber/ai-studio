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
from studio import grok_everywhere
from studio.util import atomic_copy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8798)
    parser.add_argument("--flow-gates", action="store_true", help="Pause the existing fake builder/reviewer until temporary release files appear")
    parser.add_argument("--grok-mock", action="store_true", help="Isolated MOCK research/image/video samples; no supplier connection")
    parser.add_argument("--mock-video", type=Path, help="Locally recorded WebM sample for the isolated mock preview")
    parser.add_argument("--mock-video-duration", type=int, choices=range(1, 16), help="Decoded duration of the local sample; required for a precise video mock")
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
        if args.grok_mock:
            source_png = ROOT / "ui" / "assets" / "portraits.png"
            if not args.mock_video:
                raise ValueError("--grok-mock requires a locally recorded --mock-video sample")
            video = args.mock_video.resolve()
            atomic_copy(source_png, company.store.dir / "mock-image.png")
            atomic_copy(video, company.store.dir / "mock-video.webm")
            def mock_provider(request):
                kind = request["kind"]
                value = {"ok": True, "module": "search" if kind == "research" else kind, "operation": "web" if kind == "research" else "generate",
                         "auth_kind": "session", "model": grok_everywhere.MODELS[kind], "cost_usd": None, "artifacts": []}
                if kind == "research":
                    value.update(answer="MOCK 조사 결과 · 실제 외부 조사 없음", citations=[], response_status="completed")
                if kind == "video":
                    value["request_id"] = "mock-video-preview"
                    if args.mock_video_duration is not None and request["options"]["duration"] != args.mock_video_duration:
                        raise ValueError("Mock sample does not match requested duration")
                    value["duration"] = args.mock_video_duration
                return {"simulation": True, "provider_result": value,
                        "selected_artifacts": [] if kind == "research" else ["mock-image.png" if kind == "image" else "mock-video.webm"]}
            company.engine.workbench.attach_grok_mock(mock_provider)
            wb = company.engine.workbench
            stored = wb.save_node({"id": "mock-saved-image-brief", "title": "MOCK stored image brief", "folder": "personal",
                                  "note": {"purpose": "Reusable stored image brief formatter", "inputs": "text", "outputs": "text", "cautions": "MOCK only", "example": "goal to image"},
                                  "spec": {"operation": "format", "params": {"prefix": "MOCK stored note: ", "suffix": ""}}})
            def mock_planner(prepared):
                nodes = [{"id": "a", "ref": {"id": "builtin-input", "version": 1}, "params": {"text": prepared["goal"]}},
                         {"id": "b", "ref": {"id": stored["id"], "version": stored["version"]}},
                         {"id": "c", "ref": {"id": "builtin-grok_image", "version": 1}},
                         {"id": "d", "ref": {"id": "builtin-artifact_reference", "version": 1}},
                         {"id": "e", "ref": {"id": "builtin-summary", "version": 1}}]
                return json.dumps({"title": "MOCK model-selected stored skills", "graph": {"nodes": nodes, "edges": [{"from": a["id"], "to": b["id"]} for a, b in zip(nodes, nodes[1:])]},
                                   "steps": [{"node": key, "executor": op, "validation": "Check typed output and archived SHA256", "approval": op.startswith("grok_")} for key, op in [("a", "input"), ("b", "format"), ("c", "grok_image"), ("d", "artifact_reference"), ("e", "summary")]]})
            wb.planner.attach_mock(mock_planner)
            from uuid import uuid4
            for kind in grok_everywhere.MODELS:
                nodes = [{"id": "input", "ref": {"id": "builtin-input", "version": 1}, "params": {"text": "MOCK 미리보기 요청"}},
                         {"id": "provider", "ref": {"id": "builtin-grok_" + kind, "version": 1}},
                         {"id": "summary", "ref": {"id": "builtin-summary", "version": 1}}]
                if kind == "video" and args.mock_video_duration is not None:
                    nodes[1]["params"] = {"duration": args.mock_video_duration}
                for i, item in enumerate(nodes):
                    item["position"] = {"x": 400 + i * 285, "y": 45}
                body = {"title": "MOCK / 모의 실행 · " + kind, "graph": {"nodes": nodes, "edges": [{"from": "input", "to": "provider"}, {"from": "provider", "to": "summary"}]}}
                plan = company.engine.workbench.plan(body)
                company.engine.workbench.start({**body, "plan_hash": plan["hash"], "request_id": uuid4().hex, "confirmed": True, "allow_models": False})
            company.engine.workbench.tick()
            if args.mock_video_duration is not None:
                wb.save_flow({"title": "MOCK 10초 영상 길이 확인", "graph": {"nodes": [
                    {"id": "input", "ref": {"id": "builtin-input", "version": 1}, "params": {"text": "MOCK ten-second clip"}, "position": {"x": 400, "y": 45}},
                    {"id": "provider", "ref": {"id": "builtin-grok_video", "version": 1}, "params": {"duration": args.mock_video_duration}, "position": {"x": 685, "y": 45}}],
                    "edges": [{"from": "input", "to": "provider"}]}})
            preview_nodes = [{"id": "input", "ref": {"id": "builtin-input", "version": 1}, "params": {"text": "계획 확인 요청"}},
                             {"id": "format", "ref": {"id": "builtin-format", "version": 1}, "params": {"prefix": "MOCK: ", "suffix": " / 정확한 입력"}},
                             {"id": "provider", "ref": {"id": "builtin-grok_image", "version": 1}},
                             {"id": "refs", "ref": {"id": "builtin-artifact_reference", "version": 1}},
                             {"id": "summary", "ref": {"id": "builtin-summary", "version": 1}}]
            for i, item in enumerate(preview_nodes):
                item["position"] = {"x": 400 + (i % 3) * 285, "y": 45 + (i // 3) * 300}
            company.engine.workbench.save_flow({"title": "MOCK 입력·옵션 확인", "graph": {"nodes": preview_nodes,
                "edges": [{"from": a["id"], "to": b["id"]} for a, b in zip(preview_nodes, preview_nodes[1:])]}})
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
