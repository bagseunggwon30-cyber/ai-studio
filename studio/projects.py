"""CEO dashboard registration of existing local Git repositories."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import gitops
from .config import Config, ProjectConfig
from .util import atomic_write_text

STUDIO_PROTECTED = ["trusted/**", "company/**", "studio.toml", "data/**", "worktrees/**", "projects/**"]


def path_list(raw, project: ProjectConfig | None = None) -> list[str]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
        raise ValueError("수정 허용 경로를 1~30개 입력하세요.")
    out = []
    for item in raw:
        rel = gitops.normalize_rel(item) if isinstance(item, str) else None
        # Registration accepts exact paths and directory/**, not arbitrary glob expressions.
        stem = rel[:-3] if rel and rel.endswith("/**") else rel
        if not stem or len(rel) > 240 or any(c in stem for c in "*?[]:\x00\r\n"):
            raise ValueError("허용 경로는 상대 파일 경로나 폴더/** 형식이어야 합니다.")
        protected = [p.lower() for p in project.all_protected()] if project else []
        if project and gitops.matches_any(stem.lower(), protected):
            raise ValueError("보호된 경로는 수정 범위에 넣을 수 없습니다.")
        if project and any(p == stem.lower() or p.startswith(stem.lower() + "/") for p in protected):
            raise ValueError("보호된 영역 전체를 포함하는 범위는 사용할 수 없습니다.")
        if rel not in out:
            out.append(rel)
    return out


def register(cfg: Config, data: dict) -> ProjectConfig:
    key = data.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", key):
        raise ValueError("프로젝트 ID는 소문자 영문으로 시작하고 영문·숫자·-만 사용하세요.")
    for name, limit in (("title", 80), ("repo", 1000), ("main_branch", 150)):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("프로젝트 이름·Git 폴더·기준 브랜치를 올바르게 입력하세요.")
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 1000:
        raise ValueError("프로젝트 설명은 1000자 이내로 입력하세요.")
    if data.get("confirm_scope") is not True:
        raise ValueError("작업 폴더·수정 범위·자동 검증 없음 안내를 확인하세요.")
    if data.get("kind", "generic") not in ("generic", "godot", "docs") or "qa" in data:
        raise ValueError("이 화면에서 검증 명령이나 임의 실행 설정을 등록할 수 없습니다.")
    path = cfg.root / "trusted" / "projects" / (key + ".toml")
    if key in cfg.projects or path.exists():
        raise ValueError("이미 등록된 프로젝트 ID입니다.")
    if str(data["repo"]).startswith(("\\\\", "//")):
        raise ValueError("네트워크 폴더 대신 이 PC의 Git 폴더를 선택하세요.")
    repo = Path(data["repo"]).expanduser()
    if not repo.is_absolute():
        raise ValueError("Git 폴더의 전체 경로를 입력하세요.")
    repo = repo.resolve()
    for reserved in (cfg.data_dir, cfg.worktrees_dir, cfg.root / "trusted", cfg.root / "company"):
        if repo.is_relative_to(reserved.resolve()):
            raise ValueError("회사 기록·작업 사본·신뢰 설정 폴더는 제품으로 등록할 수 없습니다.")
    if any(p.repo.resolve() == repo for p in cfg.projects.values()):
        raise ValueError("이 Git 폴더는 이미 다른 프로젝트로 등록되어 있습니다.")
    if not gitops.is_repo(repo):
        raise ValueError("기존 Git 저장소의 최상위 폴더를 선택하세요. 저장소를 새로 만들지는 않습니다.")
    top = gitops.git(["rev-parse", "--show-toplevel"], repo, timeout=10).stdout.strip()
    if Path(top).resolve() != repo:
        raise ValueError("Git 저장소의 최상위 폴더를 선택하세요.")
    branch = data["main_branch"].strip()
    if gitops.git(["check-ref-format", "--branch", branch], repo, check=False, timeout=10).returncode:
        raise ValueError("올바른 로컬 브랜치 이름을 입력하세요.")
    if not gitops.ref_exists(repo, "refs/heads/" + branch):
        raise ValueError("기준 브랜치가 없습니다. 기존 로컬 브랜치를 선택하세요.")
    project = ProjectConfig(key=key, title=data["title"].strip(), kind=data.get("kind", "generic"),
                            repo=repo, main_branch=branch, description=description,
                            protected_paths=STUDIO_PROTECTED.copy() if repo == cfg.root else [], source=path)
    project.default_allowed_paths = path_list(data.get("allowed_paths"), project)
    values = {"key": key, "title": project.title, "kind": project.kind, "repo": str(repo),
              "main_branch": branch, "description": description, "protected_paths": project.protected_paths,
              "default_allowed_paths": project.default_allowed_paths}
    atomic_write_text(path, "# CEO dashboard registration. Automatic QA is not configured.\n" +
                      "\n".join(f"{name} = {json.dumps(value, ensure_ascii=False)}" for name, value in values.items()) + "\n")
    cfg.projects[key] = project
    return project
