"""직원 스킬 (Claude 스킬 방식, SPEC '스킬 학습').

스킬 하나 = skills/<이름>/SKILL.md. 맨 위 머리말(frontmatter)에 Claude 스킬과 같은 name·description을 적고,
metadata에 화면용 제목, 배운 직원(역할), 이 판을 만든 곳(출처·방법), 만든 날, 판(version)과 이번 판에서 바뀐 점을 적는다.
본문은 마크다운 지침이다.

- 스킬은 CEO가 직접 가르치거나(바로 저장), 직원이 공부·회고해 온 것을 CEO가 승인해야만 생기거나 바뀐다 (engine: kind="skill").
- 스스로 배우기: 한 번에 안 풀린 일을 끝낸 직원이 돌아보고(회고) 새 스킬이나 고친 스킬을 제안한다 (engine._maybe_reflect).
- 고치면 판이 하나 오르고, 옛 판은 skills/<이름>/history/v<판>.md에 그대로 남긴다 (진화 기록).
- 배운 직원의 프롬프트에 본문이 붙는다 (prompts._header → prompt_block). 회사 공통 규칙보다 앞서지 않는다.
- 스킬 학습 강화 (2026-09-29, 네 번째 세션):
  · 쓰는 곳(projects·kinds): 비어 있으면 모든 프로젝트·모든 일. 범위 밖 일에는 붙이지 않는다.
  · 디자인 일(kinds의 design): 다른 종류를 좁히는 조건이 아니라 '일 글(제목·목표)이 디자인 일로 보일 때만' 붙이라는 조건이다 (is_design_text).
    design만 고르면 기획·개발·리서치·리뷰의 디자인 일 모두, 다른 종류와 함께 고르면 그 종류의 일 중 디자인 일만. 일 글을 모르면 조건을 보지 않는다.
  · 지금 일과 관련 있는 스킬부터 본문을 붙이고(select, 최대 MAX_FULL개·PROMPT_BUDGET자), 나머지는 설명만 (Claude 스킬의 '필요할 때만 불러오기').
  · 직원이 실제로 따른 스킬을 보고받는다 (출력의 skills_used 또는 마지막 줄 '사용한 스킬: …', parse_applied).
  · 새 스킬을 제안받으면 비슷한 스킬을 찾아 CEO에게 알린다 (similar).
- 파일은 감독 프로그램만 쓴다. 에이전트가 쓴 글은 믿지 않는 입력이라 길이·형식을 다듬어 저장한다.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .util import atomic_write_text, stamp, today_str

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_TITLE = 30
MAX_DESCRIPTION = 300
MAX_BODY = 4000
MAX_CHANGE = 200
MAX_REASON = 400
HOW = ("ceo", "study", "reflect")  # 직접 가르침 · 공부해 옴 · 스스로 돌아보고 만듦
PROMPT_BUDGET = 12000  # 한 직원 프롬프트에 붙이는 스킬 본문 합계 (넘으면 설명만)
MAX_FULL = 5           # 본문까지 붙이는 스킬 수 (관련 높은 것부터)
# 스킬을 쓰는 일 종류 (기획·개발·리서치·리뷰·스킬 공부·MCP 만들기·디자인 일). study = 스킬 공부·회고, tool = MCP 도구 만들기 —
# '스킬 쓰는 법'·'MCP 만드는 법' 같은 스킬이 보통 일에 붙지 않게 따로 둔다. 이 둘에는 쓰는 곳에 그 종류를 **골라 둔** 스킬만 붙는다 (in_scope).
# design = 일 종류가 아니라 '디자인 일일 때만'이라는 조건이다 (is_design_text). 다른 종류와 함께 고르면 그 종류의 디자인 일만.
WORK_KINDS = ("plan", "build", "research", "review", "study", "tool", "design", "novel")
CONDITION_KINDS = ("design", "novel")  # 일 종류가 아니라 조건: 디자인 일일 때만 · 소설 프로젝트의 일일 때만
KIND_NAMES = {"plan": "기획", "build": "개발", "research": "리서치", "review": "리뷰", "study": "스킬 공부", "tool": "MCP 만들기",
              "design": "디자인 일"}
EXPLICIT_KINDS = ("study", "tool")  # 골라 둔 스킬만 붙는 일 종류
ORDINARY_KINDS = tuple(k for k in WORK_KINDS if k not in EXPLICIT_KINDS and k not in CONDITION_KINDS)  # 보통 일: design만 고른 스킬이 붙는 종류

# 디자인 일 판정 낱말 (is_design_text). 강한 낱말이 하나라도 있거나 약한 낱말이 DESIGN_WEAK_NEEDED개 이상 (서로 다른 낱말) 있으면 디자인 일.
# 한글은 조사가 붙어도 걸리게 글 안에서 찾고, 영어는 낱말 경계(앞뒤가 영문자·숫자가 아님)로 찾는다 ('ui'가 'build'에 걸리지 않게. 'HUD에'는 걸린다).
DESIGN_STRONG_KO = (
    "디자인", "시안", "목업", "와이어프레임", "프로토타입", "레이아웃", "팔레트", "글꼴", "폰트", "타이포", "아이콘", "로고",
    "일러스트", "도트", "픽셀", "스프라이트", "화면", "버튼", "메뉴", "배경", "색상", "색깔", "여백", "가독성", "애니메이션",
    "이펙트", "테마", "스타일", "팝업",
)
DESIGN_WEAK_KO = ("그림", "이미지", "효과", "카드", "캐릭터", "글자", "크기", "정렬")
DESIGN_STRONG_EN = (
    "design", "designed", "designing", "designer", "layout", "palette", "font", "typography", "typeface", "icon", "logo",
    "illustration", "sprite", "pixel", "mockup", "wireframe", "prototype", "theme", "screen", "button", "menu", "popup",
    "animation", "hud", "ui", "ux", "gui",
)
DESIGN_WEAK_EN = ("image", "card", "character", "effect", "style", "color", "colour", "size", "alignment")
DESIGN_WEAK_NEEDED = 2
# 줄 맨 앞에 목록 표시(-, *, •, 번호)·인용(>)이 붙어도, 굵은 글씨(**)·기울임(_)로 감싸도 읽는다 (parse_applied가 강조 기호를 먼저 지운다)
APPLIED_RE = re.compile(r"^[\s>•\-]*(?:\d+[.)]\s*)?사용한\s*스킬\s*[:：]\s*(.*)$", re.M)
_NAME_EDGE = " .,;:()[]{}'\"`「」"  # 이름 둘레에 붙어 오는 기호

# 공부·회고 결과. action: new(새 스킬) · update(target 스킬을 고친 전체 글) · none(배울 것 없음, reason에 이유)
SKILL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "target", "reason", "change", "name", "title", "description", "body", "scope", "kinds", "skills_used"],
    "properties": {
        "action": {"type": "string", "enum": ["new", "update", "none"]},
        "scope": {"type": "string", "enum": ["all", "project"]},  # all: 모든 프로젝트, project: 이 프로젝트에서만
        "kinds": {"type": "array", "items": {"type": "string", "enum": list(WORK_KINDS)}},  # 빈 배열 = 모든 일
        "target": {"type": "string"},
        "reason": {"type": "string"},
        "change": {"type": "string"},
        "name": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "body": {"type": "string"},
        "skills_used": {"type": "array", "items": {"type": "string"}},  # 공부·회고하면서 실제로 따른 배운 스킬 (없으면 빈 배열)
    },
}


class SkillError(ValueError):
    pass


@dataclass
class Skill:
    slug: str
    title: str
    description: str
    body: str
    learned_by: list[str] = field(default_factory=list)
    source: str = "ceo"  # 이 판을 만든 곳: ceo 또는 작업 번호
    created: str = ""
    version: int = 1
    updated: str = ""  # 이 판을 만든 날 (1판은 비움)
    change: str = ""  # 이 판에서 바뀐 점 (1판은 비움)
    how: str = "ceo"  # HOW
    projects: list[str] = field(default_factory=list)  # 쓰는 프로젝트 (비면 모두)
    kinds: list[str] = field(default_factory=list)  # 쓰는 일 종류 WORK_KINDS (비면 모두)

    def summary(self) -> dict:
        """상태 화면용 (본문 빼고)."""
        return {
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "learned_by": self.learned_by,
            "source": self.source,
            "created": self.created,
            "version": self.version,
            "updated": self.updated,
            "change": self.change,
            "how": self.how,
            "projects": self.projects,
            "kinds": self.kinds,
        }

    def to_dict(self) -> dict:
        return {**self.summary(), "body": self.body}


def skills_dir(cfg: Config) -> Path:
    return cfg.root / "skills"


# ---------------------------------------------------------------- 파일 형식
def _one_line(text: object, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# 한글 → 로마자 (국어의 로마자 표기법을 줄인 것). 한글 제목만 있어도 `skill-2` 대신 알아보기 쉬운 이름이 된다 (메모 규칙 → memo-gyuchik).
_INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_MEDIALS = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
_FINALS = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k",
           "t", "p", "t"]


def romanize(text: str) -> str:
    out = []
    for ch in str(text or ""):
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_INITIALS[code // 588] + _MEDIALS[code % 588 // 28] + _FINALS[code % 28])
        else:
            out.append(ch)
    return "".join(out)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", romanize(str(name or "")).lower()).strip("-")
    return s[:MAX_NAME].strip("-") or "skill"


_PLAIN_RE = re.compile(r"[^\s\-?:,\[\]{}#&*!|>'\"%@`][^:#]*")
_SPECIAL_RE = re.compile(r"(?i)true|false|yes|no|on|off|null|~|[-+.\d].*")


def _yaml_str(value: str) -> str:
    """머리말 값. 그대로 두면 YAML이 다르게 읽는 글(쌍점, #, 숫자·참거짓 등)은 큰따옴표로 감싼다."""
    if _PLAIN_RE.fullmatch(value) and not _SPECIAL_RE.fullmatch(value) and value == value.strip():
        return value
    return json.dumps(value, ensure_ascii=False)  # JSON 문자열은 YAML 큰따옴표 문자열로도 맞다


def _yaml_value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        try:
            return str(json.loads(raw))
        except ValueError:
            return raw[1:-1]
    return raw.strip("'")


def render(skill: Skill) -> str:
    # 값은 한 줄로 다듬어 두었으므로 머리말이 깨지지 않는다 (줄바꿈·'---'가 들어갈 수 없다)
    later = f"  updated: {skill.updated}\n  change: {_yaml_str(skill.change)}\n" if skill.version > 1 else ""
    return (
        "---\n"
        f"name: {skill.slug}\n"
        f"description: {_yaml_str(skill.description)}\n"
        "metadata:\n"
        f"  title: {_yaml_str(skill.title)}\n"
        f"  learned_by: {', '.join(skill.learned_by)}\n"
        f"  projects: {', '.join(skill.projects)}\n"
        f"  kinds: {', '.join(skill.kinds)}\n"
        f"  source: {skill.source}\n"
        f"  how: {skill.how}\n"
        f"  created: {skill.created}\n"
        f"  version: {skill.version}\n"
        f"{later}"
        "---\n\n"
        f"{skill.body.strip()}\n"
    )


def parse(text: str, slug: str) -> Skill:
    """머리말은 우리가 쓰는 모양(key: value, metadata 아래 두 칸 들여쓰기)만 읽는다."""
    meta: dict[str, str] = {}
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            line = lines[i]
            if line.strip() == "---":
                body = "\n".join(lines[i + 1 :])
                break
            m = re.match(r"^\s*([A-Za-z_]+):\s*(.*)$", line)
            if m and m.group(2).strip():
                meta[m.group(1)] = _yaml_value(m.group(2))
    learned = [r.strip() for r in meta.get("learned_by", "").split(",") if r.strip()]
    projects = [x.strip() for x in meta.get("projects", "").split(",") if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", x.strip())]
    kinds = [x.strip() for x in meta.get("kinds", "").split(",") if x.strip() in WORK_KINDS]
    source = meta.get("source", "ceo")
    how = meta.get("how", "")
    version = meta.get("version", "1")
    return Skill(
        slug=slug,
        title=_one_line(meta.get("title") or meta.get("name") or slug, MAX_TITLE),
        description=_one_line(meta.get("description", ""), MAX_DESCRIPTION),
        body=body.strip()[:MAX_BODY],
        learned_by=learned,
        source=source,
        created=meta.get("created", ""),
        version=max(1, int(version)) if version.isdigit() else 1,
        updated=meta.get("updated", ""),
        change=_one_line(meta.get("change", ""), MAX_CHANGE),
        how=how if how in HOW else ("ceo" if source == "ceo" else "study"),
        projects=projects,
        kinds=kinds,
    )


# ---------------------------------------------------------------- 읽기·쓰기
def list_skills(cfg: Config) -> list[Skill]:
    root = skills_dir(cfg)
    if not root.exists():
        return []
    out = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and NAME_RE.match(p.name)):
        f = folder / "SKILL.md"
        if f.is_file():
            out.append(parse(f.read_text(encoding="utf-8", errors="replace"), folder.name))
    return sorted(out, key=lambda s: (s.created, s.slug))


def get(cfg: Config, slug: str) -> Skill:
    if not NAME_RE.match(str(slug or "")):
        raise SkillError("스킬 이름이 올바르지 않습니다.")
    f = skills_dir(cfg) / slug / "SKILL.md"
    if not f.is_file():
        raise SkillError("스킬을 찾을 수 없습니다.")
    return parse(f.read_text(encoding="utf-8", errors="replace"), slug)


def _write(cfg: Config, skill: Skill) -> None:
    atomic_write_text(skills_dir(cfg) / skill.slug / "SKILL.md", render(skill))


def _roles(cfg: Config, roles: object) -> list[str]:
    if not isinstance(roles, list):
        return []
    return [r for r in cfg.roles if r in {str(x) for x in roles}]


def _clean(title: str, description: str, body: str) -> tuple[str, str, str]:
    title = _one_line(title, MAX_TITLE)
    description = _one_line(description, MAX_DESCRIPTION)
    body = str(body or "").replace("\r\n", "\n").strip()
    if not title or not description or not body:
        raise SkillError("스킬에는 제목, 언제 쓰는지, 지침이 모두 필요합니다.")
    if len(body) > MAX_BODY:
        raise SkillError(f"지침은 {MAX_BODY}자 이내로 써 주세요.")
    return title, description, body


def _scope(cfg: Config, projects: object, kinds: object) -> tuple[list[str], list[str]]:
    """쓰는 곳 다듬기: 있는 프로젝트·정해진 일 종류만 (순서는 설정·WORK_KINDS 순)."""
    p = {str(x) for x in projects} if isinstance(projects, list) else set()
    k = {str(x) for x in kinds} if isinstance(kinds, list) else set()
    return [x for x in cfg.projects if x in p], [x for x in WORK_KINDS if x in k]


def create(cfg: Config, *, name: str, title: str, description: str, body: str, learned_by: object, source: str,
           how: str = "ceo", projects: object = None, kinds: object = None) -> Skill:
    """새 스킬을 저장한다. 이름이 겹치면 뒤에 -2, -3을 붙인다."""
    title, description, body = _clean(title, description, body)
    base = slugify(name) if NAME_RE.match(slugify(name)) else "skill"
    slug, n = base, 2
    while (skills_dir(cfg) / slug).exists():
        slug = f"{base[: MAX_NAME - 4]}-{n}"
        n += 1
    skill = Skill(slug, title, description, body, _roles(cfg, learned_by), _one_line(source, 40) or "ceo", today_str(),
                  how=how if how in HOW else "ceo")
    skill.projects, skill.kinds = _scope(cfg, projects, kinds)
    _write(cfg, skill)
    return skill


def history_dir(cfg: Config, slug: str) -> Path:
    return skills_dir(cfg) / slug / "history"


def update(cfg: Config, slug: str, *, title: str, description: str, body: str, learned_by: object, source: str,
           how: str, change: str, projects: object = None, kinds: object = None) -> Skill:
    """스킬을 고친다 (진화). 옛 판은 history/v<판>.md에 그대로 남기고 판을 하나 올린다."""
    old = get(cfg, slug)
    title, description, body = _clean(title, description, body)
    atomic_write_text(history_dir(cfg, slug) / f"v{old.version}.md", render(old))
    skill = Skill(slug, title, description, body, _roles(cfg, learned_by), _one_line(source, 40) or "ceo", old.created,
                  version=old.version + 1, updated=today_str(), change=_one_line(change, MAX_CHANGE) or "고쳤다",
                  how=how if how in HOW else "ceo")
    # 쓰는 곳은 주지 않으면 그대로 둔다
    skill.projects, skill.kinds = _scope(cfg, old.projects if projects is None else projects, old.kinds if kinds is None else kinds)
    _write(cfg, skill)
    return skill


def history(cfg: Config, skill: Skill) -> list[dict]:
    """진화 기록: 옛 판들과 지금 판 (오래된 것부터). 판마다 만든 날·바뀐 점·만든 곳."""
    out = []
    folder = history_dir(cfg, skill.slug)
    if folder.is_dir():
        for f in folder.glob("v*.md"):
            m = re.fullmatch(r"v(\d+)\.md", f.name)
            if m and int(m.group(1)) < skill.version:
                old = parse(f.read_text(encoding="utf-8", errors="replace"), skill.slug)
                out.append({"version": int(m.group(1)), "date": old.updated or old.created, "change": old.change,
                            "source": old.source, "how": old.how, "title": old.title})
    out.sort(key=lambda x: x["version"])
    out.append({"version": skill.version, "date": skill.updated or skill.created, "change": skill.change,
                "source": skill.source, "how": skill.how, "title": skill.title})
    return out


def learned(cfg: Config, role: str) -> list[Skill]:
    return [s for s in list_skills(cfg) if role in s.learned_by]


def set_learned(cfg: Config, slug: str, role: str, learned: bool) -> Skill:
    if role not in cfg.roles:
        raise SkillError(f"알 수 없는 직원: {role}")
    skill = get(cfg, slug)
    roles = [r for r in skill.learned_by if r != role] + ([role] if learned else [])
    skill.learned_by = [r for r in cfg.roles if r in roles]  # 설정 순서대로
    _write(cfg, skill)
    return skill


def set_scope(cfg: Config, slug: str, projects: object, kinds: object) -> Skill:
    """쓰는 곳(프로젝트·일 종류)만 바꾼다. 내용이 아니라 판은 그대로."""
    skill = get(cfg, slug)
    skill.projects, skill.kinds = _scope(cfg, projects, kinds)
    _write(cfg, skill)
    return skill


def remove(cfg: Config, slug: str) -> Skill:
    """지운 스킬은 바로 없애지 않고 data/skills-trash/로 옮긴다 (되살릴 수 있게)."""
    skill = get(cfg, slug)
    trash = cfg.data_dir / "skills-trash"
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(skills_dir(cfg) / slug), str(trash / f"{slug}-{stamp()}"))
    return skill


def from_study(cfg: Config, structured: object, target: str = "") -> tuple[dict | None, list[str]]:
    """직원이 공부·회고해 온 결과(SKILL_SCHEMA)를 다듬는다.

    돌려주는 것: ({action, target, reason, change, skill}, 알릴 점). action이 none이면 skill 없이 이유만.
    target: CEO가 '더 좋게 고쳐 오기'로 정한 스킬 (있으면 그 스킬을 고친 것으로 받는다).
    쓸 수 없으면 (None, 이유).
    """
    s = structured if isinstance(structured, dict) else {}
    problems: list[str] = []
    action = str(s.get("action") or "new").strip().lower()
    if action not in ("new", "update", "none"):
        problems.append(f"알 수 없는 action '{action[:20]}' → 새 스킬로 받았습니다.")
        action = "new"
    reason = _one_line(s.get("reason"), MAX_REASON)
    if action == "none":
        return {"action": "none", "target": "", "reason": reason or "새로 배울 것이 없다고 합니다.", "change": "",
                "skill": None}, problems
    body = str(s.get("body", "") or "").replace("\r\n", "\n").strip()
    if len(body) > MAX_BODY:
        problems.append(f"지침이 길어 {MAX_BODY}자로 잘랐습니다.")
        body = body[:MAX_BODY]
    kinds = s.get("kinds") if isinstance(s.get("kinds"), list) else []
    out = {
        "name": slugify(str(s.get("name", ""))),
        "title": _one_line(s.get("title"), MAX_TITLE),
        "description": _one_line(s.get("description"), MAX_DESCRIPTION),
        "body": body,
        "scope": "project" if str(s.get("scope", "")).strip().lower() == "project" else "all",  # 없으면 모든 프로젝트
        "kinds": [k for k in WORK_KINDS if k in {str(x).strip().lower() for x in kinds}],
    }
    missing = [k for k in ("title", "description", "body") if not out[k]]
    if missing:
        return None, [f"비어 있는 항목: {', '.join(missing)}"]
    picked = str(s.get("target") or "").strip()
    if target:
        if action != "update" or picked != target:
            problems.append("고쳐 오라고 한 스킬을 고친 것으로 받았습니다.")
        action, picked = "update", target
    if action == "update":
        try:
            get(cfg, picked)
        except SkillError:
            problems.append(f"고칠 스킬 '{picked[:40]}'을 찾지 못해 새 스킬로 받았습니다.")
            action, picked = "new", ""
    else:
        picked = ""
    return {"action": action, "target": picked, "reason": reason, "change": _one_line(s.get("change"), MAX_CHANGE),
            "skill": out}, problems


# ---------------------------------------------------------------- 고르기 (지금 일에 맞는 스킬)
_WORD_RE = re.compile(r"[0-9a-z]+|[가-힣]+")


def tokens(text: object) -> set[str]:
    """관련도 비교용 낱말: 영어·숫자는 3자 이상 낱말, 한글은 두 글자씩 (조사가 붙어도 겹치게)."""
    out: set[str] = set()
    for w in _WORD_RE.findall(str(text or "").lower()):
        if "가" <= w[0] <= "힣":
            out.update(w[i:i + 2] for i in range(len(w) - 1))
        elif len(w) >= 3:
            out.add(w)
    return out


def _skill_words(s: Skill) -> set[str]:
    return tokens(f"{s.title} {s.description} {s.slug.replace('-', ' ')}")


def _en_words_re(words: tuple[str, ...]) -> re.Pattern[str]:
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?P<w>{alt})(?:s|es)?(?![a-z0-9])")


_DESIGN_STRONG_EN_RE = _en_words_re(DESIGN_STRONG_EN)
_DESIGN_WEAK_EN_RE = _en_words_re(DESIGN_WEAK_EN)


def is_design_text(text: object) -> bool:
    """일 글(제목·목표)이 디자인 일(화면·그림·글자 모양)로 보이는지. 강한 낱말이 하나라도 있거나 약한 낱말이 둘 이상이면 True. 빈 글은 False."""
    t = str(text or "").lower()
    if not t.strip():
        return False
    if any(w in t for w in DESIGN_STRONG_KO) or _DESIGN_STRONG_EN_RE.search(t):
        return True
    weak = {w for w in DESIGN_WEAK_KO if w in t} | {m.group("w") for m in _DESIGN_WEAK_EN_RE.finditer(t)}
    return len(weak) >= DESIGN_WEAK_NEEDED


def in_scope(s: Skill, project: str = "", kind: str = "", text: str = "", project_kind: str = "") -> bool:
    """이 일에 쓸 스킬인지 (쓰는 곳이 비어 있으면 모두). project·kind·text를 모르면 그 조건은 본다고 친다.
    스킬 공부(study)·MCP 만들기(tool)는 쓰는 곳에 그 종류를 골라 둔 스킬만 — 개발 요령 같은 보통 스킬은 공부·회고 때 목록(_known_skills)으로 따로 본다.
    design은 종류를 좁히는 조건이 아니라 '디자인 일일 때만'이다: design만 골랐으면 보통 일(plan·build·research·review) 모두,
    다른 종류와 함께 골랐으면 그 종류의 일 중에서 — 어느 쪽이든 일 글(text)이 있으면 is_design_text여야 한다."""
    if s.projects and project and project not in s.projects:
        return False
    work = [k for k in s.kinds if k not in CONDITION_KINDS]
    if "novel" in s.kinds and project_kind and project_kind != "novel":  # 소설 조건: 소설 프로젝트의 일일 때만 (모르면 본다고 친다)
        return False
    if "design" in s.kinds and str(text or "").strip() and project_kind != "design" and not is_design_text(text):  # 디자인 프로젝트의 일은 모두 디자인 일
        return False
    if kind in EXPLICIT_KINDS:
        return kind in work
    if not s.kinds:
        return True
    if not work:  # design만
        return not kind or kind in ORDINARY_KINDS
    return not kind or kind in work


def select(cfg: Config, role: str, *, project: str = "", kind: str = "", text: str = "") -> tuple[list[Skill], list[Skill]]:
    """이 일에 붙일 스킬: (본문까지 붙일 것, 설명만 붙일 것). 쓰는 곳 밖의 스킬(디자인 일 조건 포함, 일 글 text로 판정)은 빼고,
    지금 일 글(text: 제목·목표)과 제목·설명이 많이 겹치는 스킬부터 본문을 붙인다 (최대 MAX_FULL개, PROMPT_BUDGET자)."""
    words = tokens(text)
    project_kind = cfg.projects[project].kind if project in cfg.projects else ""
    mine = [s for s in learned(cfg, role) if in_scope(s, project, kind, text, project_kind)]
    mine.sort(key=lambda s: (-len(_skill_words(s) & words), s.created, s.slug))
    full: list[Skill] = []
    brief: list[Skill] = []
    used = 0
    for s in mine:
        if len(full) < MAX_FULL and used + len(s.body) <= PROMPT_BUDGET:
            full.append(s)
            used += len(s.body)
        else:
            brief.append(s)
    return full, brief


# ---------------------------------------------------------------- 프롬프트
def prompt_block(cfg: Config, role: str, *, project: str = "", kind: str = "", text: str = "") -> str:
    """이 역할이 배운 스킬을 프롬프트에 붙일 글로. 없으면 빈 글.

    Claude 스킬처럼 '언제 쓰는지'(description)를 먼저 보여 주고, 지금 일과 관련 있는 것만 본문을 붙인다 (select).
    끝날 때 실제로 따른 스킬을 알리게 한다 (parse_applied가 읽는다).
    """
    full, brief = select(cfg, role, project=project, kind=kind, text=text)
    if not full and not brief:
        return ""
    parts = [
        "# 배운 스킬 (CEO가 승인한 회사 지침)",
        "",
        "아래는 당신이 배운 스킬이다. 지금 작업과 관련 있는 스킬만 따른다.",
        "회사 공통 규칙, 수정 금지 경로, 검증 방식, 작업 카드와 부딪히면 그쪽을 따른다.",
        "끝낼 때 실제로 따른 스킬의 이름(괄호 안 영어 이름)을 알린다: 출력 JSON에 `skills_used`가 있으면 거기에 넣고, "
        "없으면 보고의 마지막 줄에 `사용한 스킬: 이름, 이름` (따른 스킬이 없으면 `사용한 스킬: 없음`).",
    ]
    for s in full:
        parts.append(f"\n## {s.title} (`{s.slug}`)\n\n언제 쓰나: {s.description}\n")
        parts.append(nest_headings(s.body))
    for s in brief:
        parts.append(f"\n## {s.title} (`{s.slug}`)\n\n언제 쓰나: {s.description}\n")
        parts.append("(본문은 길거나 이 일과 관련이 적어 생략. 설명만 참고한다.)")
    return "\n".join(parts) + "\n"


_HEADING_RE = re.compile(r"^(#{1,6})([ \t].*)$")


def nest_headings(body: str, floor: int = 3) -> str:
    """스킬 본문의 마크다운 제목을 floor단계(### ) 아래로 내린다. 프롬프트의 큰 구획(`# 작업`, `# 회사 공통 규칙`)과 섞이지 않게 하고,
    에이전트가 써 온 본문이 구획을 흉내 내도 스킬 제목(##) 아래 소제목으로만 보이게 한다.
    코드 블록(``` 또는 ~~~) 안의 `#` 줄(주석 등)은 건드리지 않는다. 제목이 없거나 이미 깊으면 그대로."""
    lines = body.split("\n")
    fence = ""
    marks: list[tuple[int, int]] = []  # (줄 번호, 제목 단계)
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            token = stripped[:3]
            fence = "" if fence == token else (fence or token)
            continue
        m = None if fence else _HEADING_RE.match(line)
        if m:
            marks.append((i, len(m.group(1))))
    if not marks:
        return body
    shift = max(0, floor - min(level for _, level in marks))
    for i, level in marks:
        lines[i] = "#" * min(6, level + shift) + _HEADING_RE.match(lines[i]).group(2)
    return "\n".join(lines)


def parse_applied(final: object, structured: object, offered: list[str]) -> list[str] | None:
    """직원이 실제로 따랐다고 알린 스킬 (붙여 준 스킬 이름만 받는다). 알리지 않았으면 None (모름)."""
    names: list[str] | None = None
    if isinstance(structured, dict) and isinstance(structured.get("skills_used"), list):
        names = [str(x) for x in structured["skills_used"]]
    else:
        found = APPLIED_RE.findall(re.sub(r"[*_]", "", str(final or "")))  # 굵은 글씨·기울임 기호는 지우고 읽는다 (스킬 이름에는 * _ 가 없다)
        if found:
            last = found[-1].strip(_NAME_EDGE)
            names = [] if not last or last.startswith("없") or last.lower() in ("none", "-") else re.split(r"[,\s]+", last)
    if names is None:
        return None
    ok = set(offered)
    return [n for n in dict.fromkeys(x.strip(_NAME_EDGE) for x in names) if n in ok]


def similar(cfg: Config, skill: dict, exclude: str = "", limit: int = 3) -> list[dict]:
    """새로 제안된 스킬과 비슷한 기존 스킬 (제목·설명·본문 낱말이 겹치는 정도, 0~1). 새로 만들기보다 고치는 게 나을 때 알린다."""
    mine = tokens(f"{skill.get('title', '')} {skill.get('description', '')} {skill.get('body', '')}")
    if not mine:
        return []
    out = []
    for s in list_skills(cfg):
        if s.slug == exclude:
            continue
        theirs = tokens(f"{s.title} {s.description} {s.body}")
        if not theirs:
            continue
        score = len(mine & theirs) / min(len(mine), len(theirs))
        if score >= 0.35:
            out.append({"slug": s.slug, "title": s.title, "score": round(score, 2)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
