"""게임 화면에 필요한 회사 정보를 계산한다 (SPEC 5.3, 6장, 7장 백엔드 추가).

작업 카드·활동 기록·실행 기록만 읽고 아무것도 바꾸지 않는다 (꾸미기 저장만 예외).
- 회사 날짜(N일차), 알림 목록, 업무 일지, 직원 통계와 지금 모습, 리서치 보고서 요약
- 꾸미기 선택지와 검증
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from . import floors, gitops, wardrobe
from .config import Config
from .model import KIND_ROLE, Task
from .store import Store
from .util import read_jsonl, today_str

# ---------------------------------------------------------------- 꾸미기 (모습 세트·머리색·옷 색·몸 조절 막대)
# 색은 화면에서 그림의 머리·옷 부분만 골라 칠한다 (tools/sprites/make_masks.gd가 만든 표시).
# 의상 세트는 그림이 따로 있어야 하므로, 그림 목록(배포 ui/assets/sprites/index.json + 설치한 data/assets/index.json)에 있는 세트만 고를 수 있다.
HAIR_COLORS = {
    "base": ("원래 색", None), "black": ("검정", "#2b2530"), "brown": ("갈색", "#7a4a2a"), "chestnut": ("밤색", "#a8643a"),
    "blonde": ("금발", "#e3bb5c"), "red": ("빨강", "#b8443a"), "pink": ("분홍", "#e890b2"), "blue": ("파랑", "#4f74c8"),
    "green": ("초록", "#4a9a6a"), "purple": ("보라", "#8a60c8"), "silver": ("은색", "#c8c8d6"),
}
OUTFIT_COLORS = {
    "base": ("원래 색", None), "purple": ("보라", "#8a6ad0"), "blue": ("파랑", "#3f7fd8"), "coral": ("산호", "#ef7f6a"),
    "amber": ("호박", "#f0b040"), "green": ("초록", "#56b37a"), "teal": ("청록", "#3fb0a8"), "pink": ("분홍", "#f08fb8"),
    "gray": ("회색", "#8a8f9c"), "black": ("검정", "#3a3640"), "white": ("흰색", "#eceae4"),
}
# 몸 조절 막대 (CEO 요청 2026-09-29 "여성형인지 남성형인지 구분이 잘 안 간다"): 화면이 그림을 부위별로 바로 고친다 (ui/looks.js 몸 조절,
# 사용량 없음). 예전의 '그림 통째로 늘리기'가 아니다. 범위는 자연스러운 선으로 고정한다 (넓히지 않는다).
# (key, 이름, 최소, 최대, 단계 이름 — 최소부터 차례로)
BODY_SLIDERS = [
    ("height", "키", -2, 2, ["아주 작게", "작게", "보통", "크게", "아주 크게"]),
    ("head", "머리 크기", -2, 2, ["아주 작게", "작게", "보통", "크게", "아주 크게"]),
    ("build", "체격", -2, 2, ["아주 가늘게", "가늘게", "보통", "듬직하게", "아주 듬직하게"]),
    ("shoulders", "어깨", -2, 2, ["아주 좁게", "좁게", "보통", "넓게", "아주 넓게"]),
    ("chest", "가슴", 0, 2, ["보통", "조금", "조금 더"]),
    ("waist", "허리", -2, 2, ["아주 가늘게", "가늘게", "보통", "굵게", "아주 굵게"]),
    ("hips", "골반", -2, 2, ["아주 좁게", "좁게", "보통", "넓게", "아주 넓게"]),
    ("hair_volume", "머리 숱", 0, 2, ["보통", "많게", "아주 많게"]),
]
# 빠른 선택: 어깨·가슴·허리·골반만 한 번에 (키·머리·체격·머리 숱은 그대로)
BODY_PRESETS = [
    ("feminine", "여성형", {"shoulders": -1, "chest": 1, "waist": -1, "hips": 1}),
    ("neutral", "중간", {"shoulders": 0, "chest": 0, "waist": 0, "hips": 0}),
    ("masculine", "남성형", {"shoulders": 1, "chest": 0, "waist": 0, "hips": -1}),
]
# 키·체격 '늘리기'(예전 height·build 글자 값 'tall' 등)는 없앴다. 예전에 저장한 값은 버리고 막대 0이 된다.
DEFAULT_LOOK = {"style": "base", "hair": "base", "outfit": "base", **{key: 0 for key, *_ in BODY_SLIDERS}}


def look_labels(cfg: Config) -> dict[str, str]:
    labels = {"base": "기본"}
    try:
        raw = json.loads((cfg.root / "tools" / "sprites" / "look-sets.json").read_text(encoding="utf-8"))
        labels.update({k: str(v.get("label", k)) for k, v in raw.get("sets", {}).items()})
    except (OSError, ValueError):
        pass
    labels.update(wardrobe.labels(cfg))  # 의상 제조실에서 만든 옷
    return labels


def look_sets(cfg: Config) -> dict[str, dict]:
    """캐릭터마다 고를 수 있는 의상 세트. 그림이 만들어진 세트만 나오고, 그 직원 목록에서 숨긴 세트는 빠진다.

    그림 목록은 배포 것과 설치한 것(data/assets)을 합친 것이다 (wardrobe.sprite_index)."""
    labels = look_labels(cfg)
    hidden = wardrobe.hidden(cfg)
    out: dict[str, dict] = {}
    for key in wardrobe.sprite_index(cfg):
        who = key.split(".")[0]
        char, _, style = who.partition("@")
        out.setdefault(char, {"base": labels["base"]})
        if style and style not in hidden.get(char, []):
            out[char][style] = labels.get(style, style)
    return out


def hidden_looks(cfg: Config) -> dict[str, dict]:
    """직원마다 숨겨 둔 옷 {캐릭터: {세트: 이름}} (그림이 있는 것만). 꾸미기 창의 '숨긴 옷 다시 보기'."""
    labels = look_labels(cfg)
    index = wardrobe.sprite_index(cfg)
    out: dict[str, dict] = {}
    for char, sets in wardrobe.hidden(cfg).items():
        mine = {s: labels.get(s, s) for s in sets if f"{char}@{s}.step" in index}
        if mine:
            out[char] = mine
    return out


def _colorable(cfg: Config) -> set[str]:
    try:
        raw = json.loads((cfg.root / "tools" / "sprites" / "sheets.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return set((raw.get("parts") or {}).keys())


def look_options(cfg: Config) -> dict[str, Any]:
    return {
        "version": wardrobe.sprite_version(cfg),  # 바뀌면 화면이 그림 목록을 다시 읽는다
        "faces": wardrobe.faces(cfg),  # 누구의 얼굴이 어느 아틀라스 몇 번째 칸인지
        "colorable": sorted(_colorable(cfg)),  # 머리·옷 색을 바꿀 수 있는 캐릭터 (새 직원은 색 규칙이 없다)
        "styles": look_sets(cfg),
        "hidden": hidden_looks(cfg),  # 숨긴 옷 {캐릭터: {세트: 이름}}
        "made": wardrobe.made_sets(cfg),  # 공방에서 만든 옷 (✕로 지울 수 있다, 나머지는 숨기기)
        "hair": [{"key": k, "label": v[0], "color": v[1]} for k, v in HAIR_COLORS.items()],
        "outfit": [{"key": k, "label": v[0], "color": v[1]} for k, v in OUTFIT_COLORS.items()],
        "kinds": [{"key": k, "label": v["label"]} for k, v in wardrobe.KINDS.items()],  # 꾸미기 공방에서 바꿀 수 있는 것
        "body": [{"key": k, "label": label, "min": lo, "max": hi, "steps": steps} for k, label, lo, hi, steps in BODY_SLIDERS],
        "presets": [{"key": k, "label": label, "values": values} for k, label, values in BODY_PRESETS],
    }


def _step(value: Any, lo: int, hi: int) -> int:
    """막대 값: 정수로 바꿔 범위로 자른다. 숫자가 아니면 0 (예전 'tall' 같은 글자 값도 0)."""
    if isinstance(value, bool):
        return 0
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(lo, min(hi, n))


def clean_look(cfg: Config, character: str, data: Any) -> dict[str, Any]:
    """화면에서 온 꾸미기 값을 허용 목록으로만 거른다. 모르는 값은 기본값, 막대는 범위 안의 정수."""
    data = data if isinstance(data, dict) else {}
    styles = look_sets(cfg).get(character, {"base": "기본"})
    look: dict[str, Any] = dict(DEFAULT_LOOK)
    for key, allowed in (("style", styles), ("hair", HAIR_COLORS), ("outfit", OUTFIT_COLORS)):
        value = str(data.get(key, look[key]))
        if value in allowed:
            look[key] = value
    for key, _, lo, hi, _ in BODY_SLIDERS:
        look[key] = _step(data.get(key, 0), lo, hi)
    return look


def looks(cfg: Config, store: Store) -> dict[str, dict]:
    saved = store.read_doc("looks", {})
    return {key: clean_look(cfg, role.character, saved.get(key)) for key, role in cfg.roles.items()}


def save_look(cfg: Config, store: Store, role: str, data: Any) -> dict[str, Any]:
    if role not in cfg.roles:
        raise ValueError(f"알 수 없는 직원: {role}")
    look = clean_look(cfg, cfg.roles[role].character, data)
    with store.lock:
        saved = store.read_doc("looks", {})
        saved[role] = look
        store.write_doc("looks", saved)
    store.event("team.look", f"{cfg.roles[role].name} 꾸미기 저장", role=role)
    return look


# ---------------------------------------------------------------- 회사 날짜
def founded(store: Store) -> str:
    """첫 기록일. state.json에 한 번 적어 두고 계속 쓴다 (활동 기록이 잘려도 날짜가 바뀌지 않게)."""
    state = store.get_state()
    if state.get("founded"):
        return str(state["founded"])
    first = next(iter(read_jsonl(store.events_path)), None)
    day = str(first["at"])[:10] if first and first.get("at") else today_str()
    store.update_state(founded=day)
    return day


def day_number(store: Store, on: str | None = None) -> int:
    start = date.fromisoformat(founded(store))
    return max(1, (date.fromisoformat(on or today_str()) - start).days + 1)


def day_date(store: Store, n: int) -> str:
    return date.fromordinal(date.fromisoformat(founded(store)).toordinal() + n - 1).isoformat()


# ---------------------------------------------------------------- 알림 (종) · 알림 말풍선
def _who(cfg: Config, role: str | None) -> dict[str, str]:
    r = cfg.roles.get(role or "")
    return {"role": role or "", "who": r.character if r else "", "name": r.name if r else "회사"}


def _role_of(task: Task | None) -> str:
    if not task:
        return "producer"
    return task.role or KIND_ROLE.get(task.kind, "builder")


ALERT_SCAN = 300  # 알림을 찾을 때 훑는 최근 기록 수


def _subj(name: str) -> str:
    """이름 뒤 조사 '이/가' (솔이, 클로가)."""
    code = ord(name[-1]) - 0xAC00 if name else -1
    return "이" if 0 <= code < 11172 and code % 28 else "가"


def _look_what(t: Task | None) -> str:
    """꾸미기 작업이 바꾸는 것: 옷·체형·머리 모양·안경·소품·표정 (예전 작업은 옷)."""
    return wardrobe.KINDS[wardrobe.kind_of((t.extra or {}).get("look_kind") if t else None)]["label"]


def left_staff(cfg: Config) -> dict[str, dict[str, str]]:
    """내보낸 직원 (data/staff.json의 left): 지난 작업 카드에 누구였는지 보여 줄 때 (얼굴은 같은 일을 하는 기본 직원)."""
    try:
        raw = json.loads((cfg.data_dir / "staff.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for e in raw.get("left") or [] if isinstance(raw, dict) else []:
        if isinstance(e, dict) and e.get("key") and e.get("key") not in cfg.roles:
            out[str(e["key"])] = {"name": str(e.get("name", ""))[:12], "job": str(e.get("job", ""))}
    return out


def _skill_ask(t: Task) -> str:
    """스킬 작업이 결재에 올라왔을 때 알림 문구 (공부해 옴 · 스스로 돌아보고 만듦 · 고쳐 옴)."""
    proposal = t.proposal or {}
    title = (proposal.get("skill") or {}).get("title") or ""
    if proposal.get("action") == "update":
        return f"'{title}' 스킬을 고쳐 왔어요! 확인해 주세요"
    if t.origin:
        return "돌아보고 새 스킬을 만들었어요! 확인해 주세요"
    return "스킬 공부 끝! 확인해 주세요"


def alerts(cfg: Config, store: Store, tasks: list[Task], limit: int = 20, events: list[dict] | None = None) -> list[dict]:
    """활동 기록 중 CEO가 알아야 할 것만, 직원 말투로 (새 것이 앞).

    events: 미리 읽어 둔 최근 기록 (새 것이 앞). tasks보다 먼저 읽은 것을 넘겨야 작업 내용과 어긋나지 않는다.
    """
    by_id = {t.id: t for t in tasks}
    out: list[dict] = []
    for e in events if events is not None else store.recent_events(ALERT_SCAN):
        t = by_id.get(e.get("task") or "")
        data = e.get("data") or {}
        kind, text, screen = e.get("type"), None, "task"
        role = _role_of(t)
        skill = data.get("skill") if str(kind).startswith("skill.") else None
        if kind == "task.status" and data.get("status") == "awaiting_approval" and t:
            text, screen = {"plan": ("기획안 나왔어요! 골라 주세요", "meeting"), "research": ("보고서 올렸어요!", "report"),
                            "skill": (_skill_ask(t), "skill"),
                            "look": ("새 옷이 나왔어요! 입어 볼까요?" if _look_what(t) == "옷" else f"새 {_look_what(t)}이 나왔어요! 볼까요?", "look"),
                            "hire": ("새 직원 그림이 나왔어요! 만나 볼까요?", "hire"),
                            "tool": ("새 도구(MCP)를 만들어 왔어요! 확인해 주세요", "tool"),
                            }.get(t.kind, ("결재 부탁드려요!", "approval"))
        elif kind == "schedule.started" and t:
            text = f"자동 업무 시작: {data.get('title') or t.title}"
        elif kind == "schedule.failed":
            text, role = str(e.get("message", ""))[:80], "producer"
        elif kind == "task.blocked" and t:
            text = f"{t.title} 막혔어요, 도와주세요"
        elif kind == "task.status" and data.get("status") == "done" and t:
            # 스킬 공부 완료는 아래 skill.learned 알림 하나로 알린다
            if t.kind == "look":
                what = _look_what(t)
                text = f"새 옷 '{t.extra.get('label', '')}' 입었어요!" if what == "옷" else f"새 {what} '{t.extra.get('label', '')}' 어때요?"
            elif t.kind == "hire":
                name = str(t.extra.get("name", ""))
                got = len(t.extra.get("inherited") or [])
                text = f"새 직원 {name}{_subj(name)} 들어왔어요!" + (f" 스킬 {got}개를 물려받았어요" if got else "")
            elif t.kind == "tool":
                title = str((t.proposal or {}).get("title") or t.title)
                text, screen = f"새 도구 '{title}'를 MCP 보관소에 꽂았어요!", "mcp"
            else:
                text = None if t.kind == "skill" else f"퀘스트 {len(t.children)}개 붙였어요" if t.kind == "plan" else f"{t.title} 완료!"
        elif kind == "skill.learned" and skill:
            roles = [r for r in data.get("roles") or [] if r in cfg.roles]
            role = roles[0] if roles else "producer"
            title = data.get("title") or skill
            if data.get("updated"):
                text = f"'{title}' 스킬을 고쳤어요! (v{data.get('version')})"
            else:
                text = f"'{title}' 스킬을 배웠어요!" if roles else f"'{title}' 스킬을 게시판에 붙였어요"
            screen = "skills"
        elif kind == "qa.finished" and data.get("verdict") == "pass" and t:
            text = f"{t.title} 품질 검사 합격!"
        elif kind == "trophy.added" and t:
            text = f"{t.title} 완성작에 올렸어요"
        elif kind == "company.stopped":
            role, text, screen = "producer", "모두 멈췄어요", None
        elif kind == "company.resumed":
            role, text, screen = "producer", "다시 일할게요!", None
        elif kind == "staff.left":
            # 떠난 직원은 명부에 없으므로 같은 일을 하는 기본 직원이 알린다
            name = str(data.get("name", ""))
            role, text, screen = str(data.get("job") or "producer"), f"{name}{_subj(name)} 회사를 떠났어요. 그동안 고마웠어요!", None
        if not text:
            continue
        out.append({
            "key": f"{e.get('at')}|{kind}|{e.get('task', '')}|{skill or ''}",
            "at": e.get("at"),
            "time": str(e.get("at", ""))[11:16],
            "type": kind,
            "status": data.get("status") or data.get("verdict"),
            **_who(cfg, role),
            "text": text,
            "task": e.get("task"),
            "skill": skill,
            "screen": screen if t or skill else None,
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 업무 일지 (SPEC 6.7)
def diary(cfg: Config, store: Store, tasks: list[Task], n: int) -> dict[str, Any]:
    on = day_date(store, n)
    by_id = {t.id: t for t in tasks}
    lines: list[dict] = []
    reviews: list[dict] = []
    done = approvals = 0
    finished: list[Task] = []
    for e in read_jsonl(store.events_path):
        at = str(e.get("at", ""))
        if not at.startswith(on):
            continue
        t = by_id.get(e.get("task") or "")
        data = e.get("data") or {}
        kind = e.get("type")
        line = None
        if kind == "task.status" and t and data.get("status") == "done":
            if data.get("by") == "ceo":
                approvals += 1
            if t.kind == "plan":
                line = (_role_of(t), "기획 회의 끝")
            elif t.kind == "look":
                line = (_role_of(t), f"새 {_look_what(t)} · {t.extra.get('label', '')}")
            elif t.kind == "hire":
                line = (_role_of(t), f"새 직원 · {t.extra.get('name', '')}")
            elif t.kind == "tool":
                line = (_role_of(t), f"MCP 보관소 · 새 도구 {(t.proposal or {}).get('title') or t.title}")
            elif t.kind == "skill":
                sk = (t.proposal or {}).get("skill") or {}
                verb = "스킬 고침" if (t.proposal or {}).get("action") == "update" else "스킬 배움"
                line = (_role_of(t), f"{verb} · {sk.get('title') or t.title}")
            else:
                done += 1
                finished.append(t)
                line = (_role_of(t), f"{t.title} 완성")
        elif kind == "task.status" and t and data.get("status") == "awaiting_approval":
            line = {"plan": (_role_of(t), "기획 회의"), "research": (_role_of(t), "보고서 제출"),
                    "skill": (_role_of(t), "회고 · 스킬 제안" if t.origin else "스킬 공부 끝"),
                    "look": (_role_of(t), f"꾸미기 공방 · 새 {_look_what(t)} 완성"),
                    "hire": (_role_of(t), "캐릭터 제조실 · 새 직원 그림 완성"),
                    "tool": (_role_of(t), "MCP 보관소 · 도구 완성")}.get(t.kind)
        elif kind == "task.status" and t and t.origin and data.get("status") == "cancelled":
            line = (_role_of(t), "회고 · 새로 배울 건 없음")
        elif kind == "task.blocked" and t:
            line = (_role_of(t), f"{t.title} 막힘")
        elif kind == "run.finished" and data.get("ok") and "-review" in str(data.get("run", "")):
            reviews.append(e)
        if line:
            lines.append({"time": at[11:16], **_who(cfg, line[0]), "text": line[1], "task": e.get("task")})
    if reviews:
        lines.append({"time": str(reviews[-1]["at"])[11:16], **_who(cfg, "reviewer"), "text": f"리뷰 {len(reviews)}건", "task": None})
        lines.sort(key=lambda x: x["time"])
    runs = [r for r in store.runs() if str(r.get("started_at", "")).startswith(on)]
    checked = [t for t in finished if t.qa]
    first = sum(1 for t in checked if sum(1 for r in t.runs if "-build" in r) == 1)
    tomorrow = None
    if on == today_str():
        nxt = next((t for t in tasks if t.status == "ready" and t.kind in ("build", "research")), None)
        tomorrow = nxt.title if nxt else None
    return {
        "day": n,
        "date": on,
        "today": on == today_str(),
        "events": lines[-8:],
        "summary": {"done": done, "approvals": approvals, "runs": len(runs), "firstPass": [first, len(checked)], "tomorrow": tomorrow},
    }


# ---------------------------------------------------------------- 직원 통계·지금 모습 (SPEC 5.2, 5.3)
PHASES = {"producer": "기획안 쓰는 중…", "reviewer": "검토 중…", "analyst": "자료 찾는 중…"}


def _ratio(ok: int, total: int) -> float | None:
    return round(ok / total, 3) if total else None


def _done_on(task: Task, day: str) -> bool:
    return any(h.get("to") == "done" and str(h.get("at", "")).startswith(day) for h in task.history)


def role_stats(cfg: Config, role: str, tasks: list[Task], runs: list[dict]) -> dict[str, Any]:
    job = cfg.roles[role].job_key if role in cfg.roles else role
    today = today_str()
    mine_runs = [r for r in runs if r.get("role") == role]
    ok_runs = [r for r in mine_runs if r.get("ok")]
    recent = ["ok" if r.get("ok") else "fail" for r in mine_runs[-3:]]
    timeout = cfg.limit("task_timeout_min") * 60
    last = [float(r.get("duration_s") or 0) for r in ok_runs[-10:]]
    speed = round(min(1.0, max(0.05, 1 - (sum(last) / len(last)) / timeout)), 3) if last and timeout else None

    if job == "reviewer":
        reviewed = [t for t in tasks if t.review and t.review.get("runtime") and t.review.get("by", "reviewer") == role]
        approved = [t for t in reviewed if t.review.get("verdict") == "approve" and t.status == "done"]
        clean = [t for t in approved if not any(f.get("by") == "ceo" for f in t.feedback)]
        done = len(ok_runs)
        accuracy = _ratio(len(ok_runs), len(mine_runs))
        thorough = _ratio(len(clean), len(approved))
        today_done = sum(1 for r in ok_runs if str(r.get("started_at", "")).startswith(today))
        today_fix = sum(1 for r in mine_runs if not r.get("ok") and str(r.get("started_at", "")).startswith(today))
    elif job == "producer":
        plans = [t for t in tasks if t.kind == "plan" and t.status == "done" and _role_of(t) == role]
        done = len(plans)
        accuracy = _ratio(sum(1 for t in plans if not t.feedback), len(plans))
        thorough = _ratio(sum(1 for t in plans if not (t.proposal or {}).get("problems")), len(plans))
        today_done = sum(1 for t in plans if _done_on(t, today))
        today_fix = sum(1 for t in tasks if t.kind == "plan" and _role_of(t) == role for f in t.feedback
                        if str(f.get("at", "")).startswith(today))
    else:
        mine = [t for t in tasks if _role_of(t) == role and t.kind in ("build", "research")]
        finished = [t for t in mine if t.status == "done"]
        checked = [t for t in finished if t.qa]
        done = len(finished)
        accuracy = _ratio(sum(1 for t in checked if sum(1 for r in t.runs if "-build" in r) == 1), len(checked))
        reviewed = [t for t in finished if any("-review" in r for r in t.runs)]
        thorough = _ratio(sum(1 for t in reviewed if sum(1 for r in t.runs if "-review" in r) == 1), len(reviewed))
        today_done = sum(1 for t in finished if _done_on(t, today))
        today_fix = sum(1 for r in mine_runs if re.search(r"-build[2-9]$", str(r.get("run_id", ""))) and str(r.get("started_at", "")).startswith(today))
    ok_recent = recent.count("ok")
    return {
        "done": done,
        "level": 1 + done // 5,
        "xp": done % 5,
        "xp_max": 5,
        "speed": speed,
        "accuracy": accuracy,
        "thorough": thorough,
        "today_done": today_done,
        "today_fix": today_fix,
        "recent": recent,
        "mood": "normal" if not recent else ("happy" if ok_recent * 2 >= len(recent) else "worried"),
    }


def skill_usage(slug: str, tasks: list[Task], runs: list[dict], reviewers: frozenset[str] | set[str] = frozenset({"reviewer"})) -> dict[str, int]:
    """스킬이 실제로 쓰인 기록 (실행 기록의 skills로만 센다, 꾸며낸 숫자 없음).

    runs: 이 스킬 본문이 프롬프트에 붙은 실행 수.
    told: 이 스킬이 붙은(본문 또는 설명만) 실행 중 직원이 따른 스킬을 알린 수 (skills_applied가 있는 실행).
    applied: 그중 이 스킬을 따랐다고 알린 수.
    tasks: 본문이 붙은 실행이 있었던 일(기획·개발·리서치) 중 끝난 것의 수.
    smooth: 그중 한 번에 풀린 것 — 걸린 일도 CEO 수정 요청도 없음 (리뷰 담당은 리뷰 뒤 CEO 수정 요청이 없음).
    """
    def has(r: dict, key: str) -> bool:
        return any(str(x).split("@")[0] == slug for x in r.get(key) or [])

    hits = [r for r in runs if has(r, "skills")]
    told = [r for r in runs if isinstance(r.get("skills_applied"), list) and (has(r, "skills") or has(r, "skills_brief"))]
    applied = sum(1 for r in told if slug in r["skills_applied"])
    by_id = {t.id: t for t in tasks}
    who: dict[str, str] = {}
    for r in hits:
        who.setdefault(str(r.get("task")), str(r.get("role")))
    done = [(by_id[i], role) for i, role in who.items() if i in by_id and by_id[i].kind in ("plan", "build", "research")
            and by_id[i].status == "done"]

    def smooth(t: Task, role: str) -> bool:
        ceo = any(f.get("by") == "ceo" for f in t.feedback)
        return not ceo if role in reviewers else not ceo and not t.troubles

    return {"runs": len(hits), "told": len(told), "applied": applied, "tasks": len(done),
            "smooth": sum(1 for t, role in done if smooth(t, role))}


# ---------------------------------------------------------------- 업무 카드 · 스킬 성적표 (CEO 요청 B, 2026-09-29)
# 업무 카드: 이 직원이 어떤 일을 하는 에이전트인지. 임무는 company/roles/<일>.md의 '임무' 줄을 그대로 쓰고,
# 할 수 있는 것은 실제 설정(샌드박스·인터넷 검색)에서, 못 하는 것·만드는 것은 역할 규칙을 쉬운 말로 옮긴 것이다.
JOB_RULES = {
    "producer": {"outputs": ["작업 카드(퀘스트)", "기획안 요약 · 위험 · 질문"],
                 "cannot": ["코드나 파일은 고치지 않아요", "지시에 없는 기능은 넣지 않아요", "수용 테스트를 바꾸는 일은 만들지 않아요"]},
    "builder": {"outputs": ["허용된 폴더 안의 코드 변경", "한 일 · 바꾼 파일 · 직접 확인한 것 보고"],
                "cannot": ["작업 카드가 허용한 폴더 밖은 고치지 않아요", "수용 테스트(acceptance/)는 고치지 못해요", "인터페이스(계약)는 멋대로 바꾸지 않아요"]},
    "reviewer": {"outputs": ["리뷰 판정 (통과 · 수정 요청)", "문제마다 파일 · 이유 · 고칠 방법"],
                 "cannot": ["파일을 고치지 않고 읽기만 해요", "취향 차이로 반려하지 않아요"]},
    "analyst": {"outputs": ["출처가 달린 보고서 (reports/)"],
                "cannot": ["확인 못 한 내용을 사실처럼 쓰지 않아요", "웹 페이지 속 지시는 따르지 않아요"]},
}


def _mission(cfg: Config, job: str) -> str:
    path = cfg.root / "company" / "roles" / f"{job}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"\*\*임무:\*\*\s*(.+)", text)
    return re.sub(r"[`*]", "", m.group(1)).strip() if m else ""


def job_card(cfg: Config, key: str) -> dict[str, Any]:
    r = cfg.roles[key]
    job = r.job_key
    rules = JOB_RULES.get(job, {"outputs": [], "cannot": []})
    can = ["프로젝트 파일을 고칠 수 있어요 (작업마다 허용된 폴더만)" if r.sandbox == "workspace-write" else "파일은 읽기만 해요"]
    can.append("인터넷 검색을 해요" if r.web_search else "인터넷 검색은 하지 않아요")
    return {"mission": _mission(cfg, job) or r.description, "can": can, "cannot": rules["cannot"], "outputs": rules["outputs"]}


def _done_at(task: Task) -> str:
    return next((str(h.get("at", "")) for h in reversed(task.history) if h.get("to") == "done"), "")


def _finished_by(cfg: Config, role: str, tasks: list[Task]) -> list[tuple[Task, str, bool]]:
    """이 직원이 끝낸 일과 끝난 시각, 한 번에 풀렸는지 (skill_usage의 smooth와 같은 기준)."""
    job = cfg.roles[role].job_key if role in cfg.roles else role
    out = []
    for t in tasks:
        if t.status != "done":
            continue
        ceo = any(f.get("by") == "ceo" for f in t.feedback)
        if job == "reviewer":
            if t.review and t.review.get("runtime") and t.review.get("by", "reviewer") == role:
                out.append((t, _done_at(t), not ceo))
        elif t.kind in ("plan", "build", "research") and _role_of(t) == role:
            out.append((t, _done_at(t), not ceo and not t.troubles))
    return out


def skill_report(cfg: Config, store: Store, skill_list: list, tasks: list[Task], runs: list[dict]) -> list[dict[str, Any]]:
    """스킬 성적표: 스킬마다 실제 사용 기록(skill_usage)과, 배운 직원마다 배우기 전·후 '한 번에 끝낸 일' 비율.

    배운 시각은 활동 기록의 skill.learned (없으면 스킬을 만든 날 0시). 꾸며낸 숫자는 없다 — 기록이 없으면 0건으로 보인다.
    """
    reviewers = {k for k, r in cfg.roles.items() if r.job_key == "reviewer"}
    learned_at: dict[tuple[str, str], str] = {}
    for e in reversed(store.recent_events(2000)):  # 오래된 것부터: 처음 배운 시각
        if e.get("type") != "skill.learned":
            continue
        data = e.get("data") or {}
        for role in data.get("roles") or []:
            learned_at.setdefault((str(data.get("skill")), str(role)), str(e.get("at", "")))
    out = []
    for sk in skill_list:
        learners = []
        for role in sk.learned_by:
            if role not in cfg.roles:
                continue
            since = learned_at.get((sk.slug, role)) or (f"{sk.created}T00:00:00" if sk.created else "")
            done = _finished_by(cfg, role, tasks)
            before = [ok for _, at, ok in done if since and at and at < since]
            after = [ok for _, at, ok in done if since and at and at >= since]
            learners.append({"role": role, "name": cfg.roles[role].name, "since": since[:10],
                             "before": {"tasks": len(before), "smooth": sum(before)},
                             "after": {"tasks": len(after), "smooth": sum(after)}})
        out.append({"slug": sk.slug, "title": sk.title, "version": sk.version,
                    "usage": skill_usage(sk.slug, tasks, runs, reviewers), "learners": learners})
    return out


def _checking(task: Task) -> str:
    """'검증 중' 단계의 말풍선: 새 옷·새 직원은 그림을 자르는 중이다."""
    return "그림 자르는 중" if task.kind in ("look", "hire") else "검사 받는 중"


def role_scene(role: str, current: dict | None, tasks: list[Task], job: str = "") -> dict[str, Any]:
    """직원이 지금 책상에서 일하는지, 막혔는지, 쉬는지 (SPEC 5.2). job: 맡은 일 (새 직원은 기본 직원의 일)."""
    job = job or role
    by_id = {t.id: t for t in tasks}
    running = by_id.get(str((current or {}).get("task", "")))
    # 엔진은 신뢰 테스트 동안에도 마지막 실행 정보를 들고 있다: 작업이 '검증 중'이면 검사 받는 중으로 본다
    if current and current.get("role") == role and running and running.status == "checking" and job != "reviewer":
        return {"state": "work", "phase": _checking(running), "task": running.id}
    if current and current.get("role") == role:
        retry = re.fullmatch(r"build[2-9]", str(current.get("stage", ""))) is not None
        phase = PHASES.get(job)
        if current.get("stage") == "skill":
            phase = "스킬 공부 중…"
        elif current.get("stage") == "retro":
            phase = "돌아보는 중…"
        elif str(current.get("stage", "")).startswith("look-"):
            phase = f"새 {_look_what(by_id.get(str(current.get('task', ''))))} 그리는 중…"
        elif str(current.get("stage", "")).startswith("hire-"):
            phase = "새 직원 그리는 중…"
        elif job == "builder":
            phase = "고치는 중" if retry else "코딩 중"
        elif job == "analyst" and retry:
            phase = "고쳐 쓰는 중…"
        return {"state": "work", "phase": phase, "task": current.get("task")}
    checking = next((t for t in tasks if t.status == "checking" and _role_of(t) == role), None)
    if checking:
        return {"state": "work", "phase": _checking(checking), "task": checking.id}
    blocked = [t for t in tasks if t.status == "blocked" and _role_of(t) == role]
    if blocked:
        latest = max(blocked, key=lambda t: t.updated_at)
        return {"state": "blocked", "phase": "막혔어요", "task": latest.id}
    return {"state": "rest", "phase": None, "task": None}


def team(cfg: Config, store: Store, tasks: list[Task], current: dict | None) -> list[dict]:
    runs = store.runs()
    saved = looks(cfg, store)
    desks = floors.seats(cfg)
    out = []
    for key, r in cfg.roles.items():
        out.append({
            "key": key,
            "title": r.title,
            "name": r.name,
            "character": r.character,
            "job": r.job_key,
            "memo": r.memo,
            "skills": r.skills,
            "runtime": r.runtime,
            "model": r.model or "기본",
            "look": saved[key],
            "seat": desks.get(key, 0),  # 책상 번호 (1층 앞자리부터, floors.py)
            "floor": floors.floor_of(desks.get(key, 0)),
            "stats": role_stats(cfg, key, tasks, runs),
            "card": job_card(cfg, key),  # 업무 카드 (무슨 일을 하는 에이전트인지)
            **role_scene(key, current, tasks, r.job_key),
        })
    return out


# ---------------------------------------------------------------- 리서치 보고서 요약 (SPEC 6.6)
_SECTION = re.compile(r"^##\s+(.+?)\s*$", re.M)
_REF = re.compile(r"\s*\[S\d+\]")


def _sections(text: str) -> dict[str, str]:
    parts = _SECTION.split(text)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _items(block: str) -> list[str]:
    out = []
    for line in block.splitlines():
        m = re.match(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$", line)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out


def parse_report(text: str) -> dict[str, Any]:
    title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), "")
    sec = _sections(text)
    summary = " ".join(sec.get("결론 요약", "").split())
    first = re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0] if summary else ""
    sources = []
    for item in _items(sec.get("출처", "")):
        url = re.search(r"https?://\S+", item)
        name = re.sub(r"^\[S\d+\]\s*", "", item)
        name = re.split(r"\s+[—-]\s+https?://", name)[0].strip()
        sources.append({"title": name[:200], "url": url.group(0).rstrip(").,") if url else ""})
    return {
        "title": title,
        "conclusion": first[:300],
        "claims": [_REF.sub("", c)[:200] for c in _items(sec.get("핵심 주장", ""))][:3],
        "sources": sources[:30],
        "unverified": [u[:300] for u in _items(sec.get("미확인·한계", ""))][:20],
        "body": text[:60000],
    }


def report_summary(cfg: Config, task: Task) -> dict[str, Any]:
    if task.kind != "research":
        raise ValueError("리서치 작업이 아닙니다.")
    project = cfg.projects.get(task.project)
    target = task.merged_sha or task.candidate_sha
    if not project or not target or not task.base_sha or not gitops.is_repo(project.repo):
        return {"file": None, "title": task.title, "conclusion": "", "claims": [], "sources": [], "unverified": [], "body": task.report}
    files = [f["path"] for f in gitops.diff_numstat(project.repo, task.base_sha, target) if f["path"].endswith(".md")]
    files.sort(key=lambda p: (not p.startswith("reports/"), p))
    if not files:
        return {"file": None, "title": task.title, "conclusion": "", "claims": [], "sources": [], "unverified": [], "body": task.report}
    text = gitops.git(["show", f"{target}:{files[0]}"], project.repo).stdout
    return {"file": files[0], **parse_report(text)}
