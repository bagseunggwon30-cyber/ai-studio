"""명령줄 진입점: python studio.py <명령>."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, gitops
from .config import load_config
from .doctor import run_doctor
from .qa import run_selftest
from .store import Store
from .util import read_json, stamp

ROOT = Path(__file__).resolve().parent.parent
ICONS = {"ok": "[ OK ]", "warn": "[주의]", "fail": "[실패]"}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="studio", description=f"AI Studio 감독 프로그램 {__version__}")
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    parser.add_argument("--data", default=None, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="대시보드를 열고 회사를 가동한다")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--no-browser", action="store_true")
    p_serve.add_argument("--fake", action="store_true", help=argparse.SUPPRESS)

    sub.add_parser("init", help="제품 저장소와 첫 작업을 준비한다 (여러 번 실행해도 안전)")
    sub.add_parser("doctor", help="도구·로그인·프로젝트 상태를 점검한다")
    p_self = sub.add_parser("selftest", help="신뢰 테스트가 결함 구현을 잡아내는지 확인한다")
    p_self.add_argument("project")
    sub.add_parser("status", help="작업 목록을 출력한다")

    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.cmd == "serve":
        from .server import serve

        cfg = load_config(root, args.data, fake_runtimes=args.fake)
        serve(cfg, port=args.port, open_browser=not args.no_browser)
        return 0
    cfg = load_config(root, args.data)
    if args.cmd == "init":
        return cmd_init(cfg)
    if args.cmd == "doctor":
        return cmd_doctor(cfg)
    if args.cmd == "selftest":
        return cmd_selftest(cfg, args.project)
    if args.cmd == "status":
        return cmd_status(cfg)
    parser.print_help()
    return 0


def cmd_init(cfg) -> int:
    store = Store(cfg.data_dir)
    for p in cfg.projects.values():
        if not p.repo.exists():
            print(f"{ICONS['warn']} {p.key}: 폴더가 없습니다 ({p.repo})")
            continue
        if not gitops.is_repo(p.repo):
            gitops.init_repo(p.repo, p.main_branch)
            sha = gitops.commit_all(p.repo, "초기 구조 (AI Studio init)")
            print(f"{ICONS['ok']} {p.key}: 저장소 생성 · {sha[:7] if sha else '빈 커밋 없음'}")
        else:
            print(f"{ICONS['ok']} {p.key}: 저장소 있음 · {gitops.current_branch(p.repo)} @ {gitops.head(p.repo)[:7]}")
    if not store.list():
        seeds = read_json(cfg.company_dir / "seed-tasks.json", []) or []
        for seed in seeds:
            t = store.create_task(created_by="ceo", note="초기 작업", **seed)
            print(f"{ICONS['ok']} 첫 작업 {t.id}: {t.title}")
    else:
        print(f"{ICONS['ok']} 작업 {len(store.list())}개가 이미 있어 초기 작업은 건너뜀")
    return 0


def cmd_doctor(cfg) -> int:
    result = run_doctor(cfg)
    for c in result["checks"]:
        print(f"{ICONS[c['status']]} {c['label']}: {c['detail']}")
        if c.get("hint") and c["status"] != "ok":
            print(f"        → {c['hint']}")
    print(f"\n종합: {ICONS[result['overall']]}")
    return 0 if result["overall"] != "fail" else 1


def cmd_selftest(cfg, key: str) -> int:
    project = cfg.projects.get(key)
    if not project:
        print(f"알 수 없는 프로젝트: {key}")
        return 2
    work = cfg.data_dir / "selftest" / key
    sha = gitops.head(project.repo, project.main_branch)
    report = run_selftest(cfg, project, sha, work / stamp())
    (work / "selftest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for c in report["cases"]:
        mark = ICONS["ok"] if c["ok"] else ICONS["fail"]
        print(f"{mark} {c['fixture']}: 기대 {c['expect']} / 결과 {c['got']} · 실패한 테스트 {c['failed_tests']}")
    print("신뢰 테스트가 결함을 잡아냄" if report["ok"] else "신뢰 테스트가 결함을 놓침 — 테스트 보강 필요")
    return 0 if report["ok"] else 1


def cmd_status(cfg) -> int:
    store = Store(cfg.data_dir)
    for t in store.list():
        print(f"{t.id}  {t.status:<18} {t.project:<14} {t.title}")
    return 0
