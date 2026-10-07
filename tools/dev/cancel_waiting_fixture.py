"""연습용 서버 (결재 대기 취소 확인용): 임시 회사 + 가짜 실행기 + 결재 대기 카드 여러 장. 진짜 직원·Grok·진짜 회사(8765)는 부르지 않는다.

  python tools/dev/cancel_waiting_fixture.py --port 8811 --mode grok    # 시작하면 JSON 한 줄로 주소를 알린다. 끄려면 표준 입력에 stop
임시 폴더에 회사를 새로 만들고(폴더 이름은 매번 새로 생긴다) 이 저장소의 ui/를 복사해 서버를 띄운다. 끝나면 모두 지운다.
모드:
  grok   진짜 회사에 쌓인 모습 그대로: 'Grok image' 1장 + 'Grok video' 8장, 모두 결재 대기 리서치 카드 9장 (작업대 실행 기록이 '완료'로 달린 공급자 작업)
  mixed  종류별 창을 눌러 보도록 섞은 카드 10장: 개발 2장(하나는 진짜 흐름 + 작업 폴더) · 기획 · 리서치 3장 · 스킬 공부 · MCP 만들기 · 새 직원 2장 (모두 결재 대기, 프로젝트는 하나)
  real   진짜 결재함 모양: Core Courier의 Grok 리서치 9장 + Studio Docs의 기획 1장 (프로젝트·종류 그룹이 둘)
"""
import argparse
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tests.helpers import TempStudio  # noqa: E402
from studio.server import StudioServer  # noqa: E402
from rooms_fixture import detach_stdin  # noqa: E402

BUILD = {"project": "demo", "kind": "build", "title": "정답 파일 만들기", "brief": "docs/answer.txt에 42를 쓴다.",
         "acceptance": ["검사 통과"], "allowed_paths": ["docs/**"]}


def plant(company: TempStudio, *, kind: str, title: str, role: str, extra=None, project: str = "demo", **fields):
    """실행 없이 결재 대기 상태로 심은 작업 (한 번도 일하지 않은 카드)."""
    store = company.store
    task = store.create_task(title=title, kind=kind, role=role, project=project, status="ready", extra=extra or {}, **fields)
    store.transition(task, "running", by="fixture")
    store.transition(store.get(task.id), "awaiting_approval", by="fixture")
    return store.get(task.id)


def grok_card(company: TempStudio, n: int, video: bool, project: str = "demo"):
    """진짜 회사의 Grok 시험 카드와 같은 모양: 공급자 작업 표시 + 작업대 실행 기록(완료)."""
    run_id = f"W{n:032x}"
    runs = company.store.dir / "workbench-runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps({"id": run_id, "status": "succeeded", "nodes": {}, "events": []}), encoding="utf-8")
    kind = "video" if video else "image"
    return plant(company, kind="research", title=f"Grok {kind}", role="analyst", project=project,
                 brief=f"연습용 {'영상' if video else '그림'} 시험 지시입니다.", report=f"Grok {'영상' if video else '그림'} 시험 결과 (연습용)",
                 extra={"workflow_run": run_id, "workflow_node": "n1", "workflow_no_retry": True, "provider_execution": f"{n:032x}"},
                 created_by="workbench:provider")


def seed(company: TempStudio, mode: str) -> list[str]:
    ids = []
    if mode == "grok":
        for n in range(1, 10):
            ids.append(grok_card(company, n, video=n != 1).id)
        return ids
    if mode == "real":  # 진짜 결재함 그대로: Core Courier의 Grok 보고서 9장 + Studio Docs의 외부 AI 기획안 1장 (그룹이 둘)
        for key, title in (("core-courier", "Core Courier"), ("studio-docs", "Studio Docs")):
            company.engine.create_project({"key": key, "title": title, "kind": "design", "description": f"{title} (연습용 프로젝트)"})
        for n in range(1, 10):
            ids.append(grok_card(company, n, video=n != 1, project="core-courier").id)
        ids.append(plant(company, kind="plan", title="reports/ 동네 서점 소개 1쪽 요약", role="producer", project="studio-docs",
                         brief="동네 서점 소개를 한 쪽으로 요약한다.", extra={"submission": {"by": "연습용 외부 AI"}}).id)
        return ids
    engine, store = company.engine, company.store
    build = engine.create_task(BUILD)
    engine._run_build(store.get(build.id))  # 진짜 개발 흐름(가짜 실행기): 결재 대기 + 작업 폴더가 남는다
    ids.append(build.id)
    plan = engine.submit_directive("정답 파일을 만들어 줘", "demo")
    engine._run_plan(store.get(plan.id))
    ids.append(plan.id)
    ids.append(plant(company, kind="build", title="결과 화면에 다시 하기 단추 넣기", role="builder", brief="결과 화면에 다시 하기 단추를 넣는다.",
                     acceptance=["검사 통과"]).id)  # 결재 창을 눌러 볼 두 번째 개발 카드 (실행 없이 심음)
    for n in (1, 2):
        ids.append(grok_card(company, n, video=n != 1).id)
    ids.append(plant(company, kind="research", title="동네 서점 시장 조사", role="analyst", brief="자료를 모은다.",
                     report="# 동네 서점 시장 조사\n\n연습용 보고서입니다.").id)
    ids.append(plant(company, kind="skill", title="메모 정리 스킬 공부", role="reviewer", brief="메모 정리를 공부한다.",
                     proposal={"skill": {"title": "메모 정리", "description": "메모가 길어질 때 쓴다.", "body": "# 메모 정리\n\n1. 날짜를 맨 위에 적는다.\n2. 한 줄에 하나씩 적는다.", "scope": "all", "kinds": []},
                               "reason": "연습용 스킬입니다."}).id)
    ids.append(plant(company, kind="tool", title="글자 수 세기 도구", role="builder", brief="글자 수를 세는 도구를 만든다.",
                     proposal={"name": "char-count", "title": "글자 수 세기", "description": "글을 받아 글자 수를 알려 준다.",
                               "code": "def count(text):\n    return len(text)\n", "tools": [{"name": "count"}], "flags": [], "reason": "연습용 도구입니다."},
                     review={"verdict": "approve", "summary": "문제 없어요", "by": "reviewer"}).id)
    for n in (1, 2):  # 그룹 하나만 취소해도 다른 그룹은 그대로인지 보려고 맨 끝에 같은 종류(새 직원) 둘
        ids.append(plant(company, kind="hire", title=f"새 직원 시험 {n}", role="producer", brief="연습용 새 직원 카드입니다.").id)
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--mode", choices=("grok", "mixed", "real"), default="grok")
    args = parser.parse_args()
    if not 8811 <= args.port <= 8830:
        raise SystemExit("포트는 8811~8830 안에서만 쓸 수 있어요.")
    stop_reader = detach_stdin()
    company = TempStudio()
    server = None
    try:
        company.cfg.fake_runtimes = True
        shutil.copytree(ROOT / "ui", company.root / "ui")
        ids = seed(company, args.mode)
        server = StudioServer(company.cfg, company.store, company.engine, args.port)
        company.store.acquire_process_lock()
        company.engine.start()
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True).start()
        print(json.dumps({"url": f"http://127.0.0.1:{args.port}/", "root": str(company.root), "mode": args.mode, "waiting": ids,
                          "note": "disposable company / existing fake runtime", "real_model_calls": 0}), flush=True)
        for line in stop_reader:
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
