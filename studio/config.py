"""studio.toml(회사 설정)과 trusted/projects/*.toml(프로젝트·검증 설정)을 읽는다.

프로젝트의 검증 명령은 trusted/ 아래에 둔다. 작업자(에이전트)는 제품 저장소만
수정할 수 있으므로, 자기 결과를 검사하는 방법을 스스로 바꿀 수 없다.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import floors

DEFAULT_LIMITS = {
    "max_parallel": 2,
    "task_timeout_min": 20,
    "max_attempts": 2,
    "max_children_per_plan": 8,
    "max_runs_per_day": 40,
    "max_agent_minutes_per_day": 240,
    "review_diff_max_chars": 60000,
    "qa_timeout_min": 5,
    "max_auto_skills_per_day": 3,  # 스스로 배우기(회고)를 하루에 몇 번까지
}

# 어떤 작업도 건드릴 수 없는 경로. 프로젝트 설정의 protected_paths가 여기에 더해진다.
ALWAYS_PROTECTED = [
    ".git/**",
    "acceptance/**",
    "AGENTS.md",
    "CLAUDE.md",
    ".gitignore",
]


@dataclass
class RoleConfig:
    key: str
    title: str
    runtime: str
    model: str = ""
    effort: str = ""
    sandbox: str = "read-only"
    fallback_runtime: str = ""
    fallback_model: str = ""
    web_search: bool = False
    avatar: str = ""
    description: str = ""
    # 게임 화면의 직원 (SPEC 5.1, 7장 백엔드 추가 2번)
    name: str = ""
    character: str = ""  # 그림 이름: hana | sol | clo | luna
    memo: str = ""  # 상태창 사진 옆 한마디
    skills: list[str] = field(default_factory=list)
    # 맡은 일 (producer | builder | reviewer | analyst). 비우면 key와 같다 — 설정의 기본 직원 4명.
    # CEO가 만든 새 직원(data/staff.json)은 key가 staff1… 이고 job이 같은 일을 하는 기본 직원의 key다.
    job: str = ""

    @property
    def job_key(self) -> str:
        return self.job or self.key


JOBS = ("producer", "builder", "reviewer", "analyst")
STAFF_KEY_RE = re.compile(r"^staff\d{1,3}$")
MAX_STAFF = floors.MAX_STAFF  # 새 직원 수 상한 (층을 모두 늘렸을 때). 지금 뽑을 수 있는 수는 floors.capacity


# 역할마다 기본 직원. studio.toml에 name·character·memo·skills가 없으면 이 값을 쓴다.
DEFAULT_PEOPLE = {
    "producer": ("하나", "hana", "재밌게 나눠 볼게요!", ["기획서", "일정 나누기"]),
    "builder": ("솔", "sol", "좋은 게임을 만들고 싶어요!", ["Godot", "GDScript"]),
    "reviewer": ("클로", "clo", "꼼꼼히 볼게요.", ["코드 리뷰", "테스트 읽기"]),
    "analyst": ("루나", "luna", "궁금한 건 찾아올게요.", ["자료 조사", "보고서"]),
}


@dataclass
class ProjectConfig:
    key: str
    title: str
    kind: str
    repo: Path
    main_branch: str = "main"
    description: str = ""
    protected_paths: list[str] = field(default_factory=list)
    default_allowed_paths: list[str] = field(default_factory=list)
    qa: dict = field(default_factory=dict)
    source: Path | None = None

    def all_protected(self) -> list[str]:
        return ALWAYS_PROTECTED + [p for p in self.protected_paths if p not in ALWAYS_PROTECTED]


@dataclass
class Config:
    root: Path
    data_dir: Path
    name: str
    tagline: str
    port: int
    auto_run: bool
    limits: dict
    tools: dict
    runtimes: dict
    roles: dict[str, RoleConfig]
    projects: dict[str, ProjectConfig]
    fake_runtimes: bool = False
    goals: dict = field(default_factory=dict)

    @property
    def company_dir(self) -> Path:
        return self.root / "company"

    @property
    def trusted_dir(self) -> Path:
        return self.root / "trusted"

    @property
    def worktrees_dir(self) -> Path:
        return self.root / "worktrees"

    @property
    def ui_dir(self) -> Path:
        return self.root / "ui"

    def limit(self, key: str) -> int:
        return int(self.limits.get(key, DEFAULT_LIMITS.get(key, 0)))

    def godot_path(self) -> str:
        return str(self.tools.get("godot", "") or "")

    def python_path(self) -> str:
        return str(self.tools.get("python", "") or sys.executable)

    def runtime_cfg(self, name: str) -> dict:
        return dict(self.runtimes.get(name, {}))


def load_config(root: Path, data_dir: Path | None = None, fake_runtimes: bool = False) -> Config:
    root = Path(root).resolve()
    path = root / "studio.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    studio = raw.get("studio", {})
    limits = dict(DEFAULT_LIMITS)
    limits.update(raw.get("limits", {}))

    roles: dict[str, RoleConfig] = {}
    for key, r in raw.get("roles", {}).items():
        d_name, d_char, d_memo, d_skills = DEFAULT_PEOPLE.get(key, (key, "", "", []))
        roles[key] = RoleConfig(
            key=key,
            title=str(r.get("title", key)),
            runtime=str(r.get("runtime", "codex")),
            model=str(r.get("model", "")),
            effort=str(r.get("effort", "")),
            sandbox=str(r.get("sandbox", "read-only")),
            fallback_runtime=str(r.get("fallback_runtime", "")),
            fallback_model=str(r.get("fallback_model", "")),
            web_search=bool(r.get("web_search", False)),
            avatar=str(r.get("avatar", "")),
            description=str(r.get("description", "")),
            name=str(r.get("name", d_name))[:12],
            character=str(r.get("character", d_char)),
            memo=str(r.get("memo", d_memo))[:60],
            skills=[str(s)[:20] for s in r.get("skills", d_skills)][:6],
        )
    goals = raw.get("goals", {})

    cfg = Config(
        root=root,
        data_dir=Path(data_dir).resolve() if data_dir else root / "data",
        name=str(studio.get("name", "AI Studio")),
        tagline=str(studio.get("tagline", "")),
        port=int(studio.get("port", 8765)),
        auto_run=bool(studio.get("auto_run", False)),
        limits=limits,
        tools=dict(raw.get("tools", {})),
        runtimes=dict(raw.get("runtimes", {})),
        roles=roles,
        projects=load_projects(root),
        fake_runtimes=fake_runtimes,
        goals={"week": str(goals.get("week", ""))[:40], "month": int(goals.get("month", 5))},
    )
    load_staff(cfg)
    return cfg


def staff_role(cfg: "Config", entry: dict) -> RoleConfig | None:
    """CEO가 만든 새 직원 한 명: 같은 일을 하는 기본 직원의 권한·AI·설명을 물려받고, 이름·그림·한마디·특기는 자기 것."""
    key, job = str(entry.get("key", "")), str(entry.get("job", ""))
    base = cfg.roles.get(job)
    if not STAFF_KEY_RE.match(key) or job not in JOBS or base is None or base.job or key in cfg.roles:
        return None
    return RoleConfig(
        key=key, title=base.title, runtime=base.runtime, model=base.model, effort=base.effort, sandbox=base.sandbox,
        fallback_runtime=base.fallback_runtime, fallback_model=base.fallback_model, web_search=base.web_search,
        avatar=base.avatar, description=base.description,
        name=str(entry.get("name", key))[:12], character=key, memo=str(entry.get("memo", ""))[:60],
        skills=[str(x)[:20] for x in entry.get("skills", []) if str(x).strip()][:6], job=job,
    )


def load_staff(cfg: "Config") -> None:
    """data/staff.json의 새 직원을 직원 목록에 더한다 (studio.toml은 건드리지 않는다)."""
    try:
        raw = json.loads((cfg.data_dir / "staff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for entry in (raw.get("staff") or [])[:MAX_STAFF]:
        role = staff_role(cfg, entry) if isinstance(entry, dict) else None
        if role:
            cfg.roles[role.key] = role


def load_projects(root: Path) -> dict[str, ProjectConfig]:
    out: dict[str, ProjectConfig] = {}
    folder = root / "trusted" / "projects"
    for p in sorted(folder.glob("*.toml")):
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        key = str(raw.get("key", p.stem))
        out[key] = ProjectConfig(
            key=key,
            title=str(raw.get("title", key)),
            kind=str(raw.get("kind", "generic")),
            repo=(root / str(raw.get("repo", f"projects/{key}"))).resolve(),
            main_branch=str(raw.get("main_branch", "main")),
            description=str(raw.get("description", "")),
            protected_paths=list(raw.get("protected_paths", [])),
            default_allowed_paths=list(raw.get("default_allowed_paths", [])),
            qa=dict(raw.get("qa", {})),
            source=p,
        )
    return out
