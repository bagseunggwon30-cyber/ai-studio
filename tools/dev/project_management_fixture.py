"""Disposable UI/API fixture with fake employees and two local Git repos."""
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio
from tests.test_projects import target_repo
from studio import gitops
from studio.server import StudioServer


def main():
    company = TempStudio()
    server = None
    try:
        shutil.copytree(ROOT / "ui", company.root / "ui")
        company.cfg.fake_runtimes = True
        company.cfg.roles["reviewer"].runtime = "codex"
        target = target_repo(company)
        (company.root / ".gitignore").write_text("projects/\ndata/\nworktrees/\nui/\ncompany/\ntrusted/\n", encoding="utf-8")
        gitops.init_repo(company.root, "main")
        gitops.commit_all(company.root, "fixture supervisor")
        task = company.engine.create_task({"title": "작업 대상이 다른 문서", "project": "demo",
            "brief": "docs/answer.txt에 42", "acceptance": ["정답 확인"], "allowed_paths": ["docs/**"]})
        company.store.block(task, "선택한 프로젝트가 다릅니다.")
        server = StudioServer(company.cfg, company.store, company.engine, 8797)
        company.engine.start()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(json.dumps({"url": "http://127.0.0.1:8797/", "task": task.id, "target": target,
                          "model_generation_calls": 0}), flush=True)
        for line in sys.stdin:
            if line.strip() == "stop":
                break
    finally:
        if server:
            server.shutdown()
            server.server_close()
        company.close()


if __name__ == "__main__":
    main()
