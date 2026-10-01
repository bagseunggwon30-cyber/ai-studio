"""역할별 프롬프트 조립.

프롬프트 재료는 모두 파일이다: company/agent-rules.md(공통 규칙), company/roles/<역할>.md,
작업 카드, 프로젝트 문서. 여기서는 그 파일들을 순서대로 붙이기만 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import skills
from .config import Config, ProjectConfig
from .model import KIND_LABELS, Task

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "tasks", "risks", "questions", "skills_used"],
    "properties": {
        "summary": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "kind", "brief", "acceptance", "allowed_paths", "depends_on", "difficulty"],
                "properties": {
                    "title": {"type": "string"},
                    "kind": {"type": "string", "enum": ["build", "research"]},
                    "difficulty": {"type": "integer", "enum": [1, 2, 3]},
                    "brief": {"type": "string"},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                    "allowed_paths": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {"type": "array", "items": {"type": "integer"}},
                },
            },
        },
        "risks": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "skills_used": {"type": "array", "items": {"type": "string"}},  # 실제로 따른 배운 스킬 이름 (없으면 빈 배열)
    },
}

REVIEW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "summary", "findings", "skills_used"],
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "changes_requested"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "file", "issue", "suggestion"],
                "properties": {
                    "severity": {"type": "string", "enum": ["blocking", "minor"]},
                    "file": {"type": "string"},
                    "issue": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
            },
        },
        "skills_used": {"type": "array", "items": {"type": "string"}},  # 실제로 따른 배운 스킬 이름 (없으면 빈 배열)
    },
}


def _read(path: Path, limit: int = 20000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    return text if len(text) <= limit else text[:limit] + "\n…(생략)…\n"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (없음)"


def skill_context(task: Task | None, kind: str = "") -> dict[str, str]:
    """배운 스킬을 고를 때 쓰는 이 일의 정보 (engine이 실행 기록을 남길 때도 같은 값으로 고른다)."""
    if task is None:
        return {"project": "", "kind": kind, "text": ""}
    return {"project": task.project or "", "kind": kind, "text": f"{task.title}\n{task.brief}"}


def _header(cfg: Config, role: str, task: Task | None = None, kind: str = "", learned_skills: bool = True) -> str:
    """learned_skills=False: 배운 스킬 블록을 넣지 않는다.
    스킬 공부·회고는 kind='study', MCP 만들기는 kind='tool'이라 쓰는 곳에 그 종류를 골라 둔 스킬만 붙는다 (skills.in_scope)."""
    r = cfg.roles.get(role)
    job = r.job_key if r else role  # 새 직원은 같은 일을 하는 기본 직원의 역할 설명을 쓴다
    rules = _read(cfg.company_dir / "agent-rules.md")
    role_text = _read(cfg.company_dir / "roles" / f"{job}.md")
    learned = skills.prompt_block(cfg, role, **skill_context(task, kind)) if learned_skills else ""  # 이 일에 맞는 배운 스킬 (없으면 빈 글)
    me = f"당신의 이름: {r.name}\n\n" if r and r.name else ""
    return f"# 회사 공통 규칙\n\n{rules}\n\n# 당신의 역할\n\n{me}{role_text}\n" + (f"\n{learned}" if learned else "")


def _skill_report_line(cfg: Config, role: str, task: Task, kind: str) -> str:
    """개발·리서치 마지막 메시지 양식에 붙이는 한 줄: 배운 스킬을 붙여 줬을 때만, 따른 스킬 이름을 마지막 줄에 적게 한다.
    (머리말에도 같은 요청이 있지만 진짜 모델은 맨 끝 양식을 따르므로 여기에도 둔다. skills.parse_applied가 이 줄을 읽는다.)"""
    full, brief = skills.select(cfg, role, **skill_context(task, kind))
    if not full and not brief:
        return ""
    return "\n배운 스킬을 붙여 줬다: 마지막 줄에 `사용한 스킬: 이름, 이름` (실제로 따른 스킬의 영어 이름, 따른 게 없으면 `사용한 스킬: 없음`)."


def project_context(cfg: Config, project: ProjectConfig, max_files: int = 200) -> str:
    """기획에 필요한 만큼만: 프로젝트 설명, 파일 목록, 계약 문서."""
    parts = [f"## 프로젝트: {project.title} (`{project.key}`)", project.description or ""]
    repo = project.repo
    if repo.exists():
        files = [
            p.relative_to(repo).as_posix()
            for p in sorted(repo.rglob("*"))
            if p.is_file() and ".git" not in p.parts and ".godot" not in p.parts
        ]
        shown = files[:max_files]
        parts.append("### 현재 파일\n" + "\n".join(f"- {f}" for f in shown) + ("\n- …" if len(files) > max_files else ""))
        for doc in ("README.md", "docs/GAME_BRIEF.md", "docs/INTERFACES.md"):
            text = _read(repo / doc, 8000)
            if text:
                parts.append(f"### {doc}\n\n{text}")
    return "\n\n".join(p for p in parts if p)


def plan_prompt(cfg: Config, task: Task, project: ProjectConfig, existing: list[Task], role: str = "producer") -> str:
    open_tasks = [t for t in existing if t.project == project.key and t.status not in ("done", "cancelled") and t.id != task.id]
    done_tasks = [t for t in existing if t.project == project.key and t.status == "done"][-15:]
    limit = cfg.limit("max_children_per_plan")
    feedback = "\n".join(f"- {f['text']}" for f in task.feedback) or "- (없음)"
    return f"""{_header(cfg, role, task, "plan")}

# CEO 지시

{task.brief}

# 이전 기획에 대한 CEO 의견

{feedback}

# 프로젝트 정보

{project_context(cfg, project)}

# 진행 중이거나 대기 중인 작업
{_bullets([f"{t.id} [{t.status}] {t.title}" for t in open_tasks])}

# 최근 완료한 작업
{_bullets([f"{t.id} {t.title}" for t in done_tasks])}

# 출력

- 작업은 최대 {limit}개. 한 작업은 관찰 가능한 변화 하나, 파일 1~5개 정도.
- allowed_paths는 저장소 기준 상대경로 패턴(예: `src/core/**`). `acceptance/`, `AGENTS.md`, `.gitignore`는 넣지 않는다.
- depends_on은 이 목록 안의 0부터 시작하는 번호.
- difficulty는 1(작고 분명함), 2(보통), 3(여러 파일·판단이 필요함) 중 하나. 퀘스트 보드의 별 개수로 보인다.
- 수용 기준은 테스트나 파일로 확인할 수 있게 쓴다.
- 지시가 모호하거나 범위가 너무 크면 작업을 줄이고 questions에 적는다.
- 파일은 수정하지 말고 JSON만 답한다.
"""


def build_prompt(cfg: Config, task: Task, project: ProjectConfig, attempt: int, last_feedback: str, role: str = "") -> str:
    role = role or ("analyst" if task.kind == "research" else "builder")
    max_attempts = cfg.limit("max_attempts")
    fb = ""
    if attempt > 1 and last_feedback:
        fb = f"""
# 이전 시도에서 받은 피드백 (시도 {attempt}/{max_attempts})

{last_feedback}

위 문제를 고치는 데 집중한다. 이미 맞는 부분은 건드리지 않는다.
"""
    ceo_notes = "\n".join(f"- {f['text']}" for f in task.feedback if f.get("by") == "ceo")
    qa = project.qa or {}
    qa_line = f"감독 프로그램이 신뢰 수용 테스트 {qa.get('expected_total') or ''}개를 따로 실행한다." if qa.get("commands") else "자동 테스트가 없으므로 리뷰와 CEO가 확인한다."
    kind = task.kind if task.kind in ("build", "research") else "build"
    return f"""{_header(cfg, role, task, kind)}

# 작업 {task.id}: {task.title}

## 목표
{task.brief}

## 수용 기준
{_bullets(task.acceptance)}

## 수정해도 되는 경로 (이 밖의 변경은 자동으로 되돌려진다)
{_bullets(task.allowed_paths)}

## 수정 금지
{_bullets(project.all_protected())}

## CEO 메모
{ceo_notes or '- (없음)'}
{fb}
## 검증 방식
{qa_line} 당신의 완료 보고는 참고용이다.

## 끝낼 때
마지막 메시지에 한국어로 짧게: 한 일 / 바꾼 파일 / 직접 확인한 것 / 남은 문제.{_skill_report_line(cfg, role, task, kind)}
git 명령(commit, branch, reset, push)은 쓰지 않는다.
글 파일은 BOM 없는 UTF-8로 저장한다 (PowerShell `Set-Content -Encoding utf8NoBOM`, 파이썬 `encoding="utf-8"`).
"""


def review_prompt(cfg: Config, task: Task, project: ProjectConfig, diff: str, truncated: bool, qa: dict | None,
                  reviewer: str = "reviewer") -> str:
    qa_text = "자동 검증 없음"
    if qa:
        lines = [f"결과: {qa.get('verdict')} ({qa.get('passed')}/{qa.get('total')})"]
        for t in (qa.get("tests") or [])[:30]:
            lines.append(f"- {'통과' if t.get('ok') else '실패'} {t.get('name')}: {t.get('message', '')}")
        qa_text = "\n".join(lines)
    return f"""{_header(cfg, reviewer, task, "review")}

# 검토할 작업 {task.id}: {task.title}

## 목표
{task.brief}

## 수용 기준
{_bullets(task.acceptance)}

## 자동 검증 결과 (감독 프로그램이 실행)
{qa_text}

## 변경 내용 (git diff{' — 길어서 일부 생략' if truncated else ''})

```diff
{diff}
```

현재 폴더는 후보 커밋의 스냅샷이다. 필요하면 파일을 읽어서 확인한다.
JSON으로만 답한다.
"""


def _skill_output() -> str:
    """스킬 공부·회고가 함께 쓰는 출력 규칙 (skills.SKILL_SCHEMA)."""
    return f"""# 출력 (Claude 스킬 SKILL.md와 같은 형식, JSON)

- action: `new`(새 스킬) · `update`(target 스킬을 고친 전체 글) · `none`(배울 것 없음)
- target: update일 때 고칠 스킬 이름(목록의 `이름`), 아니면 빈 글
- reason: 이 스킬이 왜 필요한지 (none이면 배울 것이 없는 이유). CEO가 읽는다: 쉬운 한국어 한두 문장, {skills.MAX_REASON}자 이내
- change: update일 때 이번에 바뀐 점 한 줄, 아니면 빈 글
- name: 영어 소문자·숫자·하이픈 (예: `godot-signal-wiring`), {skills.MAX_NAME}자 이내
- title: 화면에 보일 한국어 제목, {skills.MAX_TITLE}자 이내
- description: 언제 쓰는 스킬인지 한두 문장 ("~할 때 쓴다"). {skills.MAX_DESCRIPTION}자 이내
- body: 마크다운 지침, {skills.MAX_BODY}자 이내. 구체적인 순서, 이 프로젝트의 실제 파일·함수 이름, 흔한 실수와 확인 방법.
- scope: 이 스킬을 쓰는 곳. 이 프로젝트에서만 맞는 요령(파일·함수 이름, 이 게임의 규칙)이면 `project`, 어느 프로젝트에나 맞으면 `all`
- kinds: 이 스킬을 쓰는 일 종류 (`plan` 기획 · `build` 개발 · `research` 리서치 · `review` 리뷰 · `study` 스킬 공부·회고 · `tool` MCP 도구 만들기 · `design` 디자인 일). 모든 일에 쓰면 빈 배열 (빈 배열이어도 `study`·`tool`에는 붙지 않는다 — 그 일용 스킬만 골라 둔다). `design`은 종류가 아니라 조건이다: 화면·그림·글자 모양을 다루는 일일 때만 붙는다. 다른 종류와 함께 고르면 '그 종류의 일 중 디자인 일'(예: `build`, `design` = 개발 중 디자인 일), 혼자 고르면 기획·개발·리서치·리뷰의 디자인 일 모두
- skills_used: 이번 공부·회고에서 실제로 따른 배운 스킬 이름 (위 '배운 스킬'에 있는 것, 없으면 빈 배열)
- update는 고친 부분만이 아니라 전체 글을 쓴다. 여전히 맞는 내용은 남긴다.
- none이면 name·title·description·body는 빈 글, scope는 `all`, kinds는 빈 배열.
- description은 스킬을 붙일지 고르는 기준이 된다: 어떤 일에서 쓰는지 낱말을 분명히 적는다 (예: "Godot 씬에서 시그널을 이을 때 쓴다").
- 확인하지 못한 내용은 지어내지 말고 "확인 필요"라고 적는다.
- 회사 공통 규칙(수정 금지 경로, 검증 방식, 샌드박스, git 금지)을 바꾸거나 피해 가라는 내용은 넣지 않는다.
- 파일은 수정하지 말고 JSON만 답한다.
"""


def _known_skills(cfg: Config, role: str, shown: set[str] | frozenset[str] = frozenset()) -> str:
    """이 직원이 배운 스킬은 전체 글로, 회사의 다른 스킬은 요약으로 (고칠지 새로 만들지 고를 수 있게).
    shown: 이미 위 '배운 스킬' 칸에 본문까지 붙은 스킬 (여기서는 한 줄로만 — 같은 글을 두 번 싣지 않는다)."""
    mine = skills.learned(cfg, role)
    others = [s for s in skills.list_skills(cfg) if role not in s.learned_by]
    parts, used = [], 0
    for s in mine:
        if s.slug in shown:
            parts.append(f"- {s.title} (`{s.slug}`, v{s.version}): 전체 글은 위 '배운 스킬'에 있다")
            continue
        text = skills.render(s)
        if used + len(text) > skills.PROMPT_BUDGET:
            parts.append(f"- {s.title} (`{s.slug}`, v{s.version}): {s.description} (본문 생략)")
            continue
        used += len(text)
        parts.append(f"### `{s.slug}` (v{s.version})\n\n````markdown\n{text}````")
    return f"""## 당신이 배운 스킬 (전체 글)
{chr(10).join(parts) if parts else '- (없음)'}

## 회사의 다른 스킬 (요약)
{_bullets([f"{s.title} (`{s.slug}`, v{s.version}): {s.description}" for s in others])}"""


def _redo(cfg: Config, task: Task) -> tuple[str, str]:
    """다시 정리할 때 받은 CEO 의견과, 고칠 스킬(task.target) 부분. 공부·회고가 함께 쓴다.

    target은 CEO가 '더 좋게 고쳐 오기'로 맡겼거나, 새 스킬 제안을 '비슷한 스킬에 합쳐 고쳐 오기'로 돌려보낸 것이다."""
    feedback = "\n".join(f"- {f['text']}" for f in task.feedback) or "- (없음)"
    target = ""
    if task.target:
        try:
            t = skills.get(cfg, task.target)
            target = f"""
## 고칠 스킬: `{t.slug}` (지금 v{t.version})

CEO가 이 스킬을 더 좋게 고쳐 오라고 했다. action은 `update`, target은 `{t.slug}`.
이 스킬에 원래 있던 맞는 내용은 지우지 말고, 새로 알게 된 것을 알맞은 자리에 합친다.

````markdown
{skills.render(t)}````
"""
        except skills.SkillError:
            target = f"\n## 고칠 스킬\n\n`{task.target}`는 이미 지워졌다. 주제에 맞게 새 스킬로 정리한다.\n"
    return feedback, target


def skill_prompt(cfg: Config, task: Task, project: ProjectConfig) -> str:
    """스킬 공부: CEO가 준 주제를 공부해 Claude 스킬(SKILL.md) 형식의 지침서로 정리한다. 파일은 고치지 않는다.

    task.target이 있으면 CEO가 그 스킬을 '더 좋게 고쳐 오기'로 맡긴 것이다.
    """
    feedback, target = _redo(cfg, task)
    return f"""{_header(cfg, task.role, task, "study")}

# 스킬 공부: {task.title}

CEO가 아래 주제를 공부해서 회사 스킬로 정리해 오라고 했다.
정리한 스킬은 CEO가 읽고 승인하면, 배운 직원이 다음 작업부터 프롬프트에 붙여 그대로 따르게 된다.
이미 있는 스킬이 같은 내용을 다루면 새로 만들지 말고 그 스킬을 고친다 (`update`).

## 주제와 요청
{task.brief}

## 다시 공부할 때 받은 CEO 의견
{feedback}
{target}
## 프로젝트 (참고용, 파일을 읽어 실제 이름·구조를 확인한다)

{project_context(cfg, project)}

{_known_skills(cfg, task.role, _study_shown(cfg, task.role, task))}

{_skill_output()}"""


def _study_shown(cfg: Config, role: str, task: Task) -> set[str]:
    """스킬 공부·회고 머리말에 본문까지 붙은 '스킬 공부' 스킬 (목록에서 겹쳐 싣지 않게)."""
    full, _ = skills.select(cfg, role, **skill_context(task, "study"))
    return {s.slug for s in full}


TROUBLE_LABELS = {"qa": "신뢰 검사 탈락", "review": "리뷰 수정 요청", "error": "실행 오류", "no_change": "바꾼 파일 없음",
                  "blocked": "막힘"}


def _skills_in_runs(runs: list[dict]) -> list[str]:
    """그 작업의 실행마다 붙어 있던 스킬과 직원이 따랐다고 알린 것 (스킬마다 한 줄)."""
    seen: dict[str, dict] = {}
    for r in runs:
        applied = r.get("skills_applied")
        for x in r.get("skills") or []:
            slug, _, ver = str(x).partition("@")
            row = seen.setdefault(slug, {"ver": ver, "runs": 0, "yes": 0, "no": 0, "unknown": 0})
            row["ver"], row["runs"] = ver or row["ver"], row["runs"] + 1
            key = "unknown" if applied is None else "yes" if slug in applied else "no"
            row[key] += 1
    out = []
    for slug, r in seen.items():
        told = [f"따랐다고 함 {r['yes']}번" if r["yes"] else "", f"안 따랐다고 함 {r['no']}번" if r["no"] else "",
                f"알리지 않음 {r['unknown']}번" if r["unknown"] else ""]
        out.append(f"`{slug}` v{r['ver'] or '?'} — 실행 {r['runs']}번에 붙음 ({', '.join(t for t in told if t)})")
    return out


def reflect_prompt(cfg: Config, task: Task, origin: Task, project: ProjectConfig, runs: list[dict] | None = None) -> str:
    """스스로 배우기 (회고): 한 번에 안 풀린 작업을 끝낸 직원이 돌아보고 스킬을 새로 만들거나 고쳐서 제안한다.

    runs: 그 작업의 실행 기록 (어떤 스킬이 붙어 있었고 따랐는지 — 따른 스킬로도 걸렸다면 그 스킬을 고치게 한다)."""
    troubles = [f"[{TROUBLE_LABELS.get(t.get('kind'), t.get('kind'))}] {str(t.get('text', ''))[:1200]}" for t in origin.troubles]
    ceo = [str(f.get("text", ""))[:800] for f in origin.feedback if f.get("by") == "ceo"]
    minor = [f"{f.get('file', '')}: {f.get('issue', '')} → {f.get('suggestion', '')}"[:400]
             for f in ((origin.review or {}).get("findings") or []) if isinstance(f, dict)]
    build_runs = [r for r in origin.runs if "-build" in r]
    if cfg.roles[task.role].job_key == "reviewer":
        focus = ("당신은 이 작업의 리뷰를 승인했지만, 그 뒤 CEO가 고쳐 달라고 했다 (아래 CEO 의견). "
                 "리뷰에서 무엇을 확인했으면 잡을 수 있었는지 돌아본다.")
    elif origin.kind == "plan":
        focus = "CEO가 기획안을 고쳐 달라고 했다 (아래 CEO 의견). 다음 기획이 한 번에 통과하려면 무엇을 알아 두어야 하는지 돌아본다."
    else:
        focus = "이 작업은 한 번에 통과하지 못했다 (아래 걸린 일). 다음에 같은 종류의 일을 한 번에 해내려면 무엇을 알아 두어야 하는지 돌아본다."
    feedback, target = _redo(cfg, task)
    return f"""{_header(cfg, task.role, origin, "study")}

# 돌아보기 (회고): {origin.id} {origin.title}

{focus}
배운 것은 회사 스킬로 정리해 제안한다. CEO가 읽고 승인해야 배운다.

## 끝난 작업
- 종류: {KIND_LABELS.get(origin.kind, origin.kind)}
- 실행 횟수: {len(build_runs) or 1}
- 목표: {origin.brief[:2000]}

### 수용 기준
{_bullets(origin.acceptance)}

## 걸린 일 (일어난 순서)
{_bullets(troubles)}

## CEO 의견
{_bullets(ceo)}

## 마지막 리뷰가 남긴 작은 지적
{_bullets(minor)}

## 이 작업 때 붙어 있던 배운 스킬
{_bullets(_skills_in_runs(runs or []))}

## 다시 정리할 때 받은 CEO 의견
{feedback}
{target}
## 프로젝트 (참고용, 파일을 읽어 실제 이름·구조를 확인한다. 끝난 작업의 결과는 이미 main에 있다)

{project_context(cfg, project)}

{_known_skills(cfg, task.role, _study_shown(cfg, task.role, origin))}

# 판단

- 걸린 일의 원인이 다음에도 되풀이될 '일하는 요령'(프로젝트 규칙, 자주 틀리는 곳, 확인 순서)이면 스킬로 만든다.
- 이미 있는 스킬이 그 내용을 다루는데 틀렸거나 모자랐다면 그 스킬을 고친다 (`update`). 위 목록에서 '따랐다고 함'인 스킬이 있는데도 같은 곳에서 걸렸다면 특히 그렇다.
- 붙어 있었는데 따르지 않아서 걸렸다면, 스킬의 '언제 쓰나'(description)가 흐려서일 수 있다: 언제 쓰는지를 더 분명하게 고친다.
- 한 번뿐인 사고(네트워크, 시간 초과, 구독 한도, 긴급 정지), 작업 카드 자체가 잘못된 경우, 다른 일에 쓸 수 없는 것은 `none`. 억지로 만들지 않는다.
- 이번 작업의 정답을 적지 말고, 다음 작업에 쓸 요령을 적는다.

{_skill_output()}"""


# ---------------------------------------------------------------- MCP 만들기 (직원이 도구를 만든다)
TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "title", "description", "code", "tools", "reason", "change", "skills_used"],
    "properties": {
        "name": {"type": "string"},  # 영어 소문자·숫자·- (예: csv-reader)
        "title": {"type": "string"},  # 보관소에 보일 한국어 이름 (30자 이내)
        "description": {"type": "string"},  # 무엇을 하는 도구인지 (직원이 읽는다, 300자 이내)
        "code": {"type": "string"},  # server.py 전체
        "tools": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "description"],
                                             "properties": {"name": {"type": "string"}, "description": {"type": "string"}}}},
        "reason": {"type": "string"},  # 왜 이렇게 만들었는지 (CEO가 읽는다)
        "change": {"type": "string"},  # 고친 것이면 바뀐 점 (새로 만들면 빈 글)
        "skills_used": {"type": "array", "items": {"type": "string"}},
    },
}

TOOL_TEMPLATE = '''import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_base import Server, ToolError, setup_stdio  # 보관소가 옆에 함께 넣어 준다 (표준 라이브러리만 쓰는 작은 틀)

srv = Server("csv-reader", "1.0", "CSV 파일을 읽어 표로 보여 준다. 읽기만 한다.")


@srv.tool("read_csv", "CSV 파일의 앞부분을 표로 보여 준다.",
          {"path": {"type": "string", "description": "지금 폴더 기준 파일 경로"},
           "rows": {"type": "integer", "minimum": 1, "maximum": 200, "description": "몇 줄까지 (기본 20)"}},
          ["path"])
def read_csv(path: str, rows: int = 20) -> str:
    import csv
    p = Path(path)
    if not p.is_file():
        raise ToolError("파일이 없습니다.")
    with p.open(encoding="utf-8", errors="replace", newline="") as f:
        lines = [" | ".join(r) for _, r in zip(range(rows), csv.reader(f))]
    return "\\n".join(lines) or "빈 파일입니다."


if __name__ == "__main__":
    setup_stdio()
    srv.serve()
'''

TOOL_RULES = """## 지킬 것 (어기면 리뷰에서 반려되고 CEO가 승인하지 않는다)
- 파이썬 표준 라이브러리만 쓴다 (pip 패키지 금지). `server.py` 한 파일. 틀은 `from mcp_base import Server, ToolError, setup_stdio` (위 예시 그대로).
- stdout에는 아무것도 print하지 않는다 (MCP 통신 자리다). 로그가 필요하면 sys.stderr.
- 기본은 읽기만: 파일을 만들거나 고치거나 지우지 않는다. 다른 프로그램을 실행하지 않는다 (subprocess·os.system 금지). eval·exec 금지.
- 비밀을 읽지 않는다: 홈 폴더의 .codex·.claude·.ssh·.grok, .env, 토큰·비밀번호 파일, 환경변수의 KEY·TOKEN·SECRET.
- 인터넷은 요청에 꼭 필요할 때만, 공개 주소(https)만. 이 PC(127.0.0.1·localhost)와 집 안 네트워크 주소는 쓰지 않는다.
- 결과는 사람이 읽는 짧은 글 (도구 한 번에 2만 자 이내). 잘못된 입력·못 찾음은 ToolError로 이유를 알린다.
- 도구가 켜지는 폴더는 직원이 일하는 프로젝트 폴더다. 경로는 그 폴더 안만 받는다 (`..`로 밖에 나가지 않게 막는다).
- 도구 이름은 영어 소문자_밑줄, 설명은 한국어로 언제 쓰는지 분명하게."""


def tool_prompt(cfg: Config, task: Task, old_code: str = "") -> str:
    """MCP 만들기: 직원이 표준 라이브러리 한 파일짜리 MCP 서버(server.py)를 JSON으로 써 온다 (파일은 엔진이 저장).
    코드는 CEO가 승인하기 전에는 실행하지 않는다 (리뷰는 읽기만)."""
    feedback = "\n".join(f"- {f['text']}" for f in task.feedback) or "- (없음)"
    review = task.review or {}
    findings = [f"- [{f.get('severity', '')}] {f.get('issue', '')} → {f.get('suggestion', '')}"
                for f in review.get("findings") or [] if isinstance(f, dict)]
    target = ""
    if task.target:
        target = f"""
## 고칠 도구: `{task.target}`

CEO가 이 도구를 고쳐 오라고 했다. name은 `{task.target}` 그대로, change에 바뀐 점을 적는다. 지금 코드:

```python
{old_code[:30000]}
```
"""
    return f"""{_header(cfg, task.role, task, "tool")}

# MCP 만들기: {task.title}

CEO가 직원들이 일할 때 쓸 도구(MCP 서버)를 만들어 오라고 했다. 만든 코드는 리뷰 담당이 읽고, CEO가 승인하면
MCP 보관소에 꽂혀 장착한 직원이 쓰게 된다. **코드는 출력 JSON의 code에만 쓴다 (파일을 만들지 않는다).**

## 요청
{task.brief}

## CEO 의견
{feedback}

## 지난 리뷰 지적 (있으면 모두 고친다)
{_bullets(findings)}
{target}
## 틀 예시 (이 모양을 따른다)

```python
{TOOL_TEMPLATE}```

{TOOL_RULES}

# 출력

JSON 하나: name(영어 소문자·숫자·-), title(보관소에 보일 한국어 이름), description(무엇을 하는 도구인지, 언제 쓰는지), code(server.py 전체),
tools(도구마다 name·description), reason(왜 이렇게 만들었는지 CEO에게 쉬운 한국어로), change(고친 것이면 바뀐 점, 새로 만들면 빈 글),
skills_used(따른 배운 스킬 이름, 없으면 빈 배열)."""


def tool_review_prompt(cfg: Config, task: Task, proposal: dict, flags: list[str], reviewer: str) -> str:
    """MCP 만들기 리뷰: 리뷰 담당이 코드를 읽기만 하고 안전·동작을 본다 (실행하지 않는다)."""
    tools = "\n".join(f"- {t.get('name')}: {t.get('description')}" for t in proposal.get("tools") or [])
    return f"""{_header(cfg, reviewer, task, "review")}

# 리뷰: 직원이 만든 MCP 도구 `{proposal.get('name')}` ({proposal.get('title')})

직원이 만든 MCP 서버 코드다. 파일을 고치지 말고 **읽기만** 한다. 이 코드는 CEO가 승인하면 이 PC에서 실행된다.
안전과 동작을 확인해 판정한다. 막아야 할 문제가 하나라도 있으면 changes_requested.

## 요청
{task.brief}

## 도구 목록 (직원이 적은 것)
{tools or '- (없음)'}

## 엔진이 표시한 눈여겨볼 곳 (자동 검사, 문제라는 뜻은 아니다)
{_bullets(flags)}

{TOOL_RULES}

## 확인할 것
- 위 '지킬 것'을 어긴 곳 (파일 쓰기·지우기, 다른 프로그램 실행, 비밀 읽기, 이 PC·집 안 주소 접속, 표준 라이브러리 밖 import).
- 틀(mcp_base Server·tool 장식자·setup_stdio·srv.serve) 대로인지, 도구 입력 스키마와 함수 인자가 맞는지, 오류를 ToolError로 알리는지.
- 요청한 일을 실제로 하는지. 경로 입력은 프로젝트 폴더 밖으로 못 나가게 막는지.

## 코드 (server.py)

```python
{str(proposal.get('code', ''))[:40000]}
```

# 출력

JSON: verdict(approve 또는 changes_requested), summary(한두 줄), findings(severity blocking|minor, file은 "server.py:줄번호", issue, suggestion),
skills_used(따른 배운 스킬 이름, 없으면 빈 배열)."""


def dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)
