"""CEO dashboard registration of existing local Git repositories."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import gitops, modes
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
    if data.get("kind", "generic") not in modes.KINDS or "qa" in data:
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


# ---------------------------------------------------------------- 새 작품·새 디자인 프로젝트 만들기 (개발 프로젝트는 기존 Git 폴더를 등록한다)
def create_new(cfg: Config, data: dict) -> ProjectConfig:
    """소설·디자인 프로젝트를 `projects/<ID>`에 새 Git 저장소로 만들고(기본 뼈대 + 첫 커밋) 같은 규칙으로 등록한다."""
    if not isinstance(data, dict) or set(data) - {"key", "title", "kind", "description"}:
        raise ValueError("알 수 없는 입력이 있습니다.")
    kind = data.get("kind")
    if kind not in modes.CREATABLE:
        raise ValueError("새로 만들 수 있는 종류는 소설과 디자인입니다. 개발 프로젝트는 기존 Git 폴더를 등록하세요.")
    key, title = data.get("key"), data.get("title")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", key):
        raise ValueError("프로젝트 ID는 소문자 영문으로 시작하고 영문·숫자·-만 사용하세요.")
    if not isinstance(title, str) or not title.strip() or len(title) > 80 or any(ord(c) < 32 for c in title):
        raise ValueError("이름은 80자 이내로 적어 주세요.")
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 1000:
        raise ValueError("설명은 1000자 이내로 적어 주세요.")
    if key in cfg.projects or (cfg.root / "trusted" / "projects" / (key + ".toml")).exists():
        raise ValueError("이미 있는 프로젝트 ID입니다.")
    repo = (cfg.root / "projects" / key)
    if repo.exists():
        raise ValueError("같은 이름의 폴더가 이미 있습니다. 다른 ID를 쓰세요.")
    files = modes.skeleton(kind, title.strip(), description)
    try:
        gitops.init_repo(repo, "main")
        for rel, text in files.items():
            atomic_write_text(repo / rel, text)
        gitops.commit_all(repo, f"{modes.KIND_LABELS[kind]} 프로젝트 시작: {title.strip()}")
    except Exception:
        if repo.exists():  # 반쯤 만든 폴더는 남기지 않는다 (방금 우리가 만든 것)
            import shutil
            shutil.rmtree(repo, ignore_errors=True)
        raise
    return register(cfg, {"key": key, "title": title.strip(), "kind": kind, "repo": str(repo), "main_branch": "main",
                          "description": description, "allowed_paths": list(modes.DEFAULT_PATHS[kind]), "confirm_scope": True})


# ---------------------------------------------------------------- 파일 읽기 (기준 브랜치의 내용만, 읽기 전용)
TEXT_SUFFIXES = (".md", ".txt", ".json", ".html", ".css", ".svg", ".csv", ".toml", ".yaml", ".yml")
IMAGE_SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}
MAX_TEXT_BYTES = 300_000
MAX_IMAGE_BYTES = 8_000_000
MAX_TREE = 400


def _project(cfg: Config, key: str) -> ProjectConfig:
    project = cfg.projects.get(key) if isinstance(key, str) else None
    if not project or not gitops.is_repo(project.repo) or not gitops.ref_exists(project.repo, "refs/heads/" + project.main_branch):
        raise ValueError("프로젝트를 찾을 수 없습니다.")
    return project


def tree(cfg: Config, key: str) -> list[dict]:
    """기준 브랜치의 글·그림 파일 목록 [{path, size, kind}] (경로순, 최대 400개)."""
    project = _project(cfg, key)
    out = gitops.git(["ls-tree", "-r", "-l", "-z", project.main_branch], project.repo, timeout=20).stdout
    rows = []
    for entry in out.split("\0"):
        if not entry or "\t" not in entry:
            continue
        meta, rel = entry.split("\t", 1)
        parts = meta.split()
        if len(parts) < 4 or parts[1] != "blob" or not parts[3].isdigit():
            continue
        norm = gitops.normalize_rel(rel)
        low = rel.lower()
        if norm is None or norm != rel or rel.startswith(".git") or "/.git/" in rel:
            continue
        size = int(parts[3])
        if low.endswith(TEXT_SUFFIXES) and size <= MAX_TEXT_BYTES:
            kind = "text"
        elif any(low.endswith(s) for s in IMAGE_SUFFIXES) and size <= MAX_IMAGE_BYTES:
            kind = "image"
        else:
            continue
        rows.append({"path": rel, "size": size, "kind": kind})
    rows.sort(key=lambda r: r["path"])
    return rows[:MAX_TREE]


def read_text(cfg: Config, key: str, rel: str) -> dict:
    project = _project(cfg, key)
    listed = {r["path"]: r for r in tree(cfg, key)}
    if not isinstance(rel, str) or rel not in listed or listed[rel]["kind"] != "text":
        raise ValueError("읽을 수 없는 파일입니다.")
    raw = gitops.git_bytes(["show", f"{project.main_branch}:{rel}"], project.repo, timeout=20)
    return {"path": rel, "size": len(raw), "text": raw.decode("utf-8", "replace")}


def read_raw(cfg: Config, key: str, rel: str) -> tuple[bytes, str]:
    """그림 파일 원본 (내용 종류는 확장자로만 정한다. HTML은 글로만 읽을 수 있다)."""
    project = _project(cfg, key)
    listed = {r["path"]: r for r in tree(cfg, key)}
    low = rel.lower() if isinstance(rel, str) else ""
    ctype = next((v for s, v in IMAGE_SUFFIXES.items() if low.endswith(s)), None)
    if not ctype or rel not in listed:
        raise ValueError("그림 파일이 아닙니다.")
    return gitops.git_bytes(["show", f"{project.main_branch}:{rel}"], project.repo, timeout=30), ctype
