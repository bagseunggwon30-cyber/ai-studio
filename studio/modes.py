"""작업 모드: 개발 · 디자인 · 소설 작성 (CEO 요청 2026-10-06 "개발 모드 외 디자인 및 소설 작성 부분도 추가").

모드는 **프로젝트 종류(kind)** 가 정한다. 같은 직원·같은 작업 흐름(기획 → 작업 폴더에서 만들기 → 리뷰 → CEO 결재 → 병합)을 쓰고,
프로젝트 종류에 따라 ① 직원에게 주는 작업 지침(기획·집필/제작·리뷰) ② 새 프로젝트의 기본 뼈대 ③ 기본 수정 허용 경로
④ 화면의 이름과 시작 버튼(템플릿)이 달라진다. 이 모듈은 그 글과 값을 한 곳에 모은 것이다 (표준 라이브러리만).
"""
from __future__ import annotations

# 프로젝트 종류 → 모드. docs는 개발 모드 안의 '문서'다.
KIND_MODE = {"generic": "dev", "godot": "dev", "docs": "dev", "design": "design", "novel": "novel"}
KINDS = tuple(KIND_MODE)
CREATABLE = ("novel", "design")  # 화면에서 새로 만들 수 있는 종류 (개발 프로젝트는 기존 Git 폴더를 등록)
MODE_LABELS = {"dev": "개발", "design": "디자인", "novel": "소설 작성"}
KIND_LABELS = {"generic": "일반 개발", "godot": "Godot 게임", "docs": "문서", "design": "디자인", "novel": "소설"}

# 같은 일 종류(build·research)라도 이 프로젝트에서는 이렇게 부른다 (카드·목록의 종류 이름)
TASK_LABELS = {
    "design": {"plan": "기획", "build": "디자인", "research": "디자인 조사"},
    "novel": {"plan": "기획", "build": "집필", "research": "자료 조사"},
}

DEFAULT_PATHS = {
    "novel": ["bible/**", "chapters/**", "notes/**", "README.md"],
    "design": ["brief/**", "system/**", "screens/**", "assets/**", "reviews/**", "README.md"],
}

# 읽기에 쓰는 기준 문서 (기획 담당에게 프로젝트 정보로 보여 주는 파일, 위에서부터)
CONTEXT_DOCS = {
    "novel": ("README.md", "bible/premise.md", "bible/characters.md", "bible/world.md", "bible/outline.md", "bible/style.md", "notes/continuity.md"),
    "design": ("README.md", "brief/brief.md", "system/design-tokens.md"),
}


def mode_of(kind: str) -> str:
    return KIND_MODE.get(kind or "", "dev")


def task_label(project_kind: str, task_kind: str, default: str = "") -> str:
    return TASK_LABELS.get(project_kind or "", {}).get(task_kind, default)


# ---------------------------------------------------------------- 새 프로젝트 뼈대 (영어 폴더·파일 이름 — Git 경로를 단순하게)
def _novel_skeleton(title: str, description: str) -> dict[str, str]:
    about = description.strip() or "(아직 적지 않음)"
    return {
        "README.md": f"# {title}\n\n{about}\n\n## 폴더\n\n- `bible/` — 작품의 기준 문서(한 줄 소개, 인물, 세계, 줄거리, 문체)\n- `chapters/` — 원고. 한 장에 파일 하나(`001.md`, `002.md` …)\n- `notes/` — 연속성 장부와 자료 조사 메모\n\n"
                     "직원은 쓰기 전에 `bible/`과 `notes/continuity.md`를 읽고, 쓴 뒤에는 새로 생긴 사실을 `notes/continuity.md`에 더합니다.\n",
        "bible/premise.md": "# 한 줄 소개와 기본 정보\n\n- 한 줄 소개: (주인공이 무엇을 원하고, 무엇이 막고, 무엇을 걸었는지 한 문장)\n- 장르:\n- 분위기:\n- 주제(이 이야기가 말하고 싶은 것):\n- 독자: \n- 분량 목표: 전체 몇 장, 한 장 몇 자\n- 시점과 시제: (예: 1인칭 과거 / 3인칭 제한 시점 과거)\n",
        "bible/characters.md": "# 인물\n\n## 주인공 이름\n- 나이·직업·겉모습:\n- 원하는 것(겉으로):\n- 정말 필요한 것(속으로):\n- 결점·두려움:\n- 말투·버릇(대사 예시 두 줄):\n- 이야기 속 변화:\n\n## 주요 인물 (3~5명 같은 형식으로 추가)\n",
        "bible/world.md": "# 세계와 규칙\n\n- 시간과 장소:\n- 이 세계에서 달라진 점(규칙): 어겨선 안 되는 것\n- 중요한 장소:\n- 용어 목록(이름과 뜻):\n",
        "bible/outline.md": "# 줄거리와 장 구성\n\n## 전체 줄거리 (시작 · 중간 전환점 · 가장 어두운 순간 · 결말)\n\n## 장 구성 (장마다 한 줄: 누가, 어디서, 무슨 일이, 어떤 변화가)\n1. \n",
        "bible/style.md": "# 문체 규칙\n\n- 문장 길이와 호흡:\n- 대사와 서술의 비율:\n- 쓰고 싶은 표현 / 쓰지 않을 표현:\n- 묘사 수위(폭력·성적 표현은 이야기에 필요한 만큼만, 노골적으로 쓰지 않는다):\n- 맞춤법과 띄어쓰기는 표준어 규정을 따른다.\n",
        "chapters/README.md": "# 원고 폴더\n\n한 장에 파일 하나. `001.md`처럼 세 자리 번호로 이름을 붙이고 첫 줄은 `# 제1장 제목`으로 씁니다.\n",
        "notes/continuity.md": "# 연속성 장부\n\n장마다 새로 생긴 사실을 더한다 (시간·장소·인물 상태·던진 복선·회수한 복선).\n\n## 복선 목록 (던진 장 → 회수한 장)\n\n## 시간 흐름\n\n## 인물 상태\n",
    }


def _design_skeleton(title: str, description: str) -> dict[str, str]:
    about = description.strip() or "(아직 적지 않음)"
    return {
        "README.md": f"# {title}\n\n{about}\n\n## 폴더\n\n- `brief/` — 디자인 기획서(목표·대상·분위기·제약)\n- `system/` — 디자인 규칙(색·글자·간격·부품)\n- `screens/` — 화면 시안(자체 완결 HTML+CSS, SVG)\n- `assets/` — 그림 파일과 그림 요청서(`requests.md`)\n- `reviews/` — 점검 기록\n\n"
                     "사진·일러스트가 필요하면 `assets/requests.md`에 적고, 이 PC의 '이미지·영상 작업대'에서 만든 뒤 가져옵니다.\n",
        "brief/brief.md": "# 디자인 기획서\n\n- 무엇을 만드는가(한 문장):\n- 누가 쓰는가:\n- 그 사람이 가장 먼저 해야 할 일 한 가지:\n- 분위기(형용사 세 개):\n- 꼭 지킬 것 / 하지 말 것:\n- 쓰는 곳과 크기(화면·인쇄·영상):\n- 이미 있는 자료·참고:\n",
        "brief/references.md": "# 참고 자료\n\n좋아하는 모양과 그 이유, 피하고 싶은 모양과 그 이유를 적는다.\n",
        "system/design-tokens.md": "# 디자인 규칙\n\n색(바탕·글자·강조 3가지 이름과 값), 글자 크기 단계 4개, 간격 단위(4 또는 8의 배수), 모서리 크기, 그림자를 적는다.\n글자와 바탕의 대비는 4.5:1 이상이어야 한다.\n",
        "system/components.md": "# 부품 목록\n\n단추·카드·입력칸·칩 등 자주 쓰는 부품의 모양과 상태(기본·누름·꺼짐·오류)를 적는다.\n",
        "screens/README.md": "# 화면 시안\n\n시안은 파일 하나로 열리는 HTML(스타일은 같은 파일의 `<style>`)이나 SVG로 만든다. 외부 글꼴·CDN은 쓰지 않는다.\n",
        "assets/requests.md": "# 그림 요청서\n\n그림이 필요하면 용도·크기·분위기·넣지 않을 것(글자·로고)을 한 항목씩 적는다.\n",
        "reviews/README.md": "# 점검 기록\n\n점검할 때마다 날짜와 결과를 더한다.\n",
    }


def skeleton(kind: str, title: str, description: str = "") -> dict[str, str]:
    if kind == "novel":
        return _novel_skeleton(title, description)
    if kind == "design":
        return _design_skeleton(title, description)
    raise ValueError("새로 만들 수 있는 종류는 소설과 디자인입니다.")


# ---------------------------------------------------------------- 직원에게 주는 모드별 작업 지침 (프롬프트에 그대로 붙는다)
_NOVEL_PLAN = """# 이 프로젝트는 소설 작품이다 (기획 방식)

- 작업 하나는 **한 장 집필**, 또는 한 가지 설정 문서 작성·다듬기, 또는 한 가지 점검으로 나눈다. 한 장에 두 가지 이상 큰 사건을 넣지 않는다.
- 장 집필 카드는 이렇게 쓴다: 제목 `제N장 쓰기`, 목표에 이 장에서 일어날 일(누가·어디서·무슨 일이·어떤 변화)과 분량(없으면 공백 포함 3,000~5,000자), allowed_paths는 `chapters/NNN.md`, `notes/continuity.md`.
- 수용 기준은 확인 가능하게: 파일 존재, 첫 줄 `# 제N장 …`, 분량 범위, bible과 모순 없음, 연속성 장부에 이번 장 사실 추가, 다음 장으로 이어지는 마무리.
- 장 사이는 depends_on으로 순서를 건다. bible이 비어 있으면 먼저 설정 문서(한 줄 소개·인물·세계·줄거리·문체) 작성 카드부터 만든다.
- 자료 조사(시대·직업·장소의 사실)는 kind를 research로 하고 결과를 `notes/`의 새 파일에 적게 한다. 실제 출처가 없는 사실을 지어내 적지 않게 한다.
"""

_NOVEL_BUILD = """# 작업 방식: 소설 집필 (이 프로젝트는 소설 작품이다)

- 기준 문서는 `bible/`(premise·characters·world·outline·style)과 `notes/continuity.md`다. **쓰기 전에 먼저 읽는다.** 근거 문서와 어긋나면 원고를 맞추지 말고 어긋난 점을 보고에 적는다. 새 설정을 만들면 해당 bible 파일에도 짧게 더한다.
- 원고는 `chapters/NNN.md`(세 자리 번호)에 쓴다. 첫 줄은 `# 제N장 제목`. 분량은 작업 카드가 정한 범위(없으면 공백 포함 3,000~5,000자)를 지킨다. 줄거리 요약이 아니라 **장면**으로 쓴다.
- 장면마다 목표·갈등·변화가 있어야 한다. 설명하지 말고 보여 준다(행동·대사·감각). 같은 표현·같은 문장 모양을 반복하지 않는다. "~라는 사실을 깨달았다" 같은 설명투를 남발하지 않는다.
- 인물마다 말투와 어휘가 달라야 한다(characters.md의 예시 대사를 따른다). 시점·시제·시간 순서·인물의 나이와 상태를 바꾸지 않는다.
- 장을 마친 뒤 `notes/continuity.md`에 이번 장에서 생긴 사실(날짜·장소·인물 상태·던진 복선·회수한 복선)을 더한다.
- 문체는 `bible/style.md`를 따르고 맞춤법·띄어쓰기를 지킨다. 실존 인물과 실제 사건을 왜곡·모욕하지 않고, 다른 작품의 문장을 옮겨 쓰지 않는다. 폭력·성적 표현은 이야기에 필요한 만큼만 하고 노골적으로 쓰지 않는다.
- `TODO`·`(이어서 쓰기)` 같은 미완성 표시, 설명 문장("다음은 …입니다")을 원고에 남기지 않는다. 끝낼 때 보고에 글자 수(공백 포함)와 바뀐 설정을 적는다.
"""

_NOVEL_REVIEW = """# 검토 방식: 소설 원고 (편집자 관점)

변경된 원고를 읽기 전용으로 읽고 판단한다. 파일을 고치지 않는다.
- ① 설정·시간·인물 일관성: `bible/`과 `notes/continuity.md`에 어긋나는가 ② 장면: 목표·갈등·변화가 있는가, 요약으로 때우지 않았는가 ③ 인물 말투가 구분되는가 ④ 문체: style.md를 지켰는가, 반복·상투적 표현이 많은가 ⑤ 분량이 작업 카드의 범위인가 ⑥ 맞춤법·띄어쓰기 ⑦ 연속성 장부가 갱신됐는가 ⑧ 미완성 표시·설명 문장이 남지 않았는가.
- blocking: 설정 모순, 분량이 범위를 크게 벗어남, 수용 기준 미충족, 미완성 표시, 연속성 장부 미갱신, 다른 작품 문장의 옮겨 씀. minor: 표현 다듬기.
- 지적은 파일과 어느 장면인지를 적고, 어떻게 고치면 되는지 한 줄 제안을 붙인다.
"""

_DESIGN_PLAN = """# 이 프로젝트는 디자인 프로젝트다 (기획 방식)

- 일을 이렇게 나눈다: 기획서(`brief/`) → 디자인 규칙(`system/`) → 화면 시안(`screens/`) → 점검(`reviews/`). 앞 단계가 비어 있으면 그 단계부터 카드를 만든다.
- 카드 하나는 시안 한 화면, 또는 규칙 문서 하나, 또는 점검 하나. 수용 기준은 눈으로·값으로 확인할 수 있게(색 대비 4.5:1 이상, 글자 크기·간격이 규칙 값만 사용, 긴 글자가 넘치지 않음, 상태별 모양 존재).
- 그림·사진이 필요한 일은 builder가 직접 그리지 않는다. `assets/requests.md`에 요청서(용도·크기·분위기·넣지 않을 것)를 적는 카드로 나누고, 실제 그림은 CEO가 '이미지·영상 작업대'에서 만든다고 보고에 쓴다.
- allowed_paths는 해당 폴더 안으로 좁힌다 (`screens/login.html`처럼).
"""

_DESIGN_BUILD = """# 작업 방식: 디자인 작업 (이 프로젝트는 디자인 프로젝트다)

- 기준 문서: `brief/brief.md`(목표·대상·분위기·제약)와 `system/design-tokens.md`(색·글자·간격). **쓰기 전에 먼저 읽고** 어긋나지 않게 한다. 새 규칙이 필요하면 `system/`에도 적는다.
- 결과물은 파일이다: 설명서(.md), 화면 시안(파일 하나로 열리는 HTML+CSS — 외부 글꼴·CDN·인라인 스크립트 없음), 그림(SVG), 규칙 문서. 사진·일러스트는 직접 만들지 말고 `assets/requests.md`에 요청 사항을 적는다.
- 지킬 기준: 글자와 바탕 대비 4.5:1 이상, 글자 크기와 간격은 규칙의 값만, 한글 시스템 글꼴, 색만으로 뜻을 전하지 않기, 긴 글자가 칸을 넘지 않기, 기본·누름·꺼짐·오류 상태. 배운 스킬 `visual-design-basics`가 있으면 따른다.
- 대비·크기 같은 값은 `design-kit` 도구(붙어 있으면)로 계산해 보고에 적는다. 계산하지 못한 값은 '계산 안 함'이라고 적고 값을 지어내지 않는다.
- 끝낼 때 보고에 만든 파일, 확인한 기준(값과 함께), 확인하지 못한 것을 적는다.
"""

_DESIGN_REVIEW = """# 검토 방식: 디자인 작업 (디자인 리뷰어 관점)

변경된 파일을 읽기 전용으로 읽고 판단한다. 파일을 고치지 않는다.
- ① 기획서(brief)의 목표·대상·분위기를 지켰는가 ② 디자인 규칙(tokens)의 색·글자·간격만 썼는가 ③ 글자 대비 4.5:1 이상, 색만으로 뜻을 전하지 않았는가 ④ 위계(가장 중요한 것이 먼저 보이는가)와 정렬·간격의 일관성 ⑤ 긴 글자·빈 상태·오류 상태의 처리 ⑥ 상태별 모양 ⑦ 불필요한 장식·외부 자원 ⑧ 보고한 값이 파일과 맞는가.
- blocking: 기획서나 규칙과 어긋남, 대비 미달, 보고한 값이 사실과 다름, 수용 기준 미충족, 외부 글꼴·CDN·인라인 스크립트. minor: 간격·정렬 다듬기.
- 지적은 파일과 줄(또는 요소)을 적고 고칠 값을 한 줄로 제안한다. 근거 없는 취향 지적은 minor로만 한다.
"""

_NOVEL_RESEARCH = """# 작업 방식: 소설 자료 조사 (이 프로젝트는 소설 작품이다)

- 결과는 `notes/`의 **새 파일**에 적는다(원고와 설정 문서는 고치지 않는다). 제목, 조사한 날짜, 항목별로 사실·출처·소설에 쓸 수 있는 장면 아이디어 순서로 쓴다.
- 출처가 없는 사실을 지어내지 않는다. 확인하지 못한 것은 '확인 못 함'이라고 쓴다. `bible/`의 설정과 충돌하는 사실은 따로 표시한다.
- 끝낼 때 보고에 만든 파일과 확인하지 못한 것을 적는다.
"""

_DESIGN_RESEARCH = """# 작업 방식: 디자인 조사 (이 프로젝트는 디자인 프로젝트다)

- 결과는 `brief/references.md`나 `brief/`의 새 파일에 적는다. 본 것(출처)·좋은 점·우리에게 쓸 점·피할 점 순서로 쓴다.
- 출처가 없는 말을 지어내지 않는다. 직접 확인하지 못한 것은 '확인 못 함'이라고 쓴다. 다른 사람의 그림·글을 그대로 옮기지 않는다.
- 끝낼 때 보고에 만든 파일과 확인하지 못한 것을 적는다.
"""

GUIDANCE = {
    ("novel", "plan"): _NOVEL_PLAN, ("novel", "build"): _NOVEL_BUILD, ("novel", "research"): _NOVEL_RESEARCH, ("novel", "review"): _NOVEL_REVIEW,
    ("design", "plan"): _DESIGN_PLAN, ("design", "build"): _DESIGN_BUILD, ("design", "research"): _DESIGN_RESEARCH, ("design", "review"): _DESIGN_REVIEW,
}


def guidance(project_kind: str, stage: str) -> str:
    """이 프로젝트 종류와 단계(plan·build·research·review)에 붙일 지침. 개발·문서 프로젝트는 빈 글(지금처럼)."""
    return GUIDANCE.get((project_kind or "", stage), "")


# ---------------------------------------------------------------- 화면의 시작 버튼 (템플릿): 글 칸을 채워 하나 기획 지시로 보낸다
TEMPLATES = {
    "novel": [
        {"id": "novel-start", "title": "작품 기획 시작", "hint": "아이디어를 적으면 설정집(한 줄 소개·인물·세계·줄거리·문체)을 먼저 만들어 와요.",
         "fields": [{"key": "idea", "label": "작품 아이디어", "placeholder": "예: 폐업 직전 동네 서점에 밤마다 사라진 책의 주인이 찾아온다", "required": True, "max": 1500}],
         "text": "이 작품의 기획을 시작해 줘. 아래 아이디어로 `bible/`의 premise·characters·world·outline·style 문서를 채워 줘. 줄거리는 12장 구성까지 적고, 비어 있는 곳은 아이디어에 어울리게 제안해서 채워. 아직 원고는 쓰지 않는다.\n\n아이디어:\n{idea}"},
        {"id": "novel-next", "title": "다음 장 쓰기", "hint": "줄거리와 연속성 장부를 지키며 마지막 장 다음 장을 써 와요.",
         "fields": [{"key": "length", "label": "분량(공백 포함 글자 수)", "placeholder": "4000", "default": "4000", "required": True, "max": 6}, {"key": "note", "label": "이번 장에서 꼭 넣을 것 (선택)", "placeholder": "예: 주인공이 처음으로 거짓말을 한다", "required": False, "max": 600}],
         "text": "`chapters/` 폴더의 마지막 장 다음 장을 써 줘. `bible/outline.md`의 해당 장 계획과 `notes/continuity.md`를 지키고, 분량은 공백 포함 {length}자 안팎으로 한다. 쓴 뒤 연속성 장부에 이번 장의 사실을 더한다.\n이번 장에서 꼭 넣을 것: {note}"},
        {"id": "novel-revise", "title": "장 다듬기 (퇴고)", "hint": "내용 전개는 그대로 두고 문장·반복·설정 모순을 고쳐요.",
         "fields": [{"key": "chapter", "label": "다듬을 장 번호", "placeholder": "예: 3", "required": True, "max": 4}, {"key": "focus", "label": "특히 고칠 점 (선택)", "placeholder": "예: 대사가 설명투다", "required": False, "max": 400}],
         "text": "제{chapter}장을 퇴고해 줘. 어색한 문장과 반복 표현, 설정·시간 모순을 고친다. 줄거리와 사건 순서는 바꾸지 않는다. 고친 이유를 보고에 적어 줘.\n특히 고칠 점: {focus}"},
        {"id": "novel-audit", "title": "설정·복선 점검", "hint": "원고를 읽고 모순·시간 오류·회수 못 한 복선을 장부에 정리해 와요 (원고는 안 고침).",
         "fields": [],
         "text": "`bible/`과 `chapters/`를 처음부터 읽고 설정 모순, 시간 순서 오류, 인물 말투가 흔들리는 곳, 아직 회수하지 못한 복선을 찾아 `notes/continuity.md`에 정리해 줘. 원고는 고치지 않는다."},
        {"id": "novel-research", "title": "자료 조사", "hint": "시대·직업·장소의 사실을 출처와 함께 메모로 정리해 와요.",
         "fields": [{"key": "topic", "label": "조사할 것", "placeholder": "예: 1990년대 서울 동네 서점의 하루", "required": True, "max": 500}],
         "text": "소설에 쓸 자료를 조사해 `notes/`의 새 파일에 정리해 줘. 출처를 적고, 확인하지 못한 사실은 지어내지 말고 '확인 못 함'이라고 쓴다.\n\n조사할 것: {topic}"},
    ],
    "design": [
        {"id": "design-brief", "title": "디자인 기획서 쓰기", "hint": "무엇을 만들지 적으면 `brief/brief.md`와 참고 자료 문서를 채워 와요.",
         "fields": [{"key": "what", "label": "무엇을 디자인할까요?", "placeholder": "예: 동네 카페 신메뉴 안내 포스터", "required": True, "max": 1200}],
         "text": "아래 요청으로 `brief/brief.md`(목표·대상·분위기·제약·크기)를 채우고 `brief/references.md`에 참고할 방향을 적어 줘. 모르는 부분은 어울리는 안을 제안해서 채우되 제안이라고 표시한다.\n\n요청:\n{what}"},
        {"id": "design-system", "title": "디자인 규칙 정리", "hint": "기획서를 보고 색·글자·간격·부품 규칙을 정해 와요.",
         "fields": [],
         "text": "`brief/brief.md`를 읽고 `system/design-tokens.md`(색 3가지·글자 크기 4단계·간격 단위·모서리)와 `system/components.md`(자주 쓰는 부품과 상태)를 채워 줘. 색 대비는 4.5:1 이상으로 하고 값을 도구로 계산해 적는다."},
        {"id": "design-screen", "title": "화면 시안 만들기", "hint": "규칙을 지키는 시안 한 화면을 HTML 파일로 만들어 와요.",
         "fields": [{"key": "screen", "label": "어떤 화면인가요?", "placeholder": "예: 로그인 화면, 메뉴판 포스터", "required": True, "max": 600}, {"key": "file", "label": "파일 이름", "placeholder": "login", "default": "screen", "required": True, "max": 40}],
         "text": "`screens/{file}.html`에 아래 화면의 시안을 만들어 줘. 파일 하나로 열려야 하고(스타일은 같은 파일 안), `system/design-tokens.md`의 값만 쓰며, 외부 글꼴·CDN·인라인 스크립트는 쓰지 않는다. 긴 글자와 빈 상태도 보여 준다.\n\n화면: {screen}"},
        {"id": "design-assets", "title": "그림 요청서 쓰기", "hint": "필요한 그림·사진의 용도·크기·분위기를 요청서로 정리해 와요 (그림은 이미지·영상 작업대에서 만들어요).",
         "fields": [],
         "text": "`brief/brief.md`와 `screens/`의 시안을 읽고 필요한 그림·사진을 `assets/requests.md`에 항목별로 정리해 줘 (용도·크기·분위기·넣지 않을 것: 글자·로고). 그림을 직접 만들지 않는다."},
        {"id": "design-review", "title": "디자인 점검", "hint": "시안이 기획서와 규칙을 지켰는지 점검하고 기록해 와요.",
         "fields": [],
         "text": "`screens/`의 시안을 `brief/brief.md`와 `system/design-tokens.md`에 비춰 점검하고 결과를 `reviews/` 폴더의 새 파일에 적어 줘(대비 값, 간격·정렬, 상태, 넘침). 시안은 고치지 않는다."},
    ],
}


def templates(kind: str) -> list[dict]:
    return [dict(t) for t in TEMPLATES.get(kind, [])]


def render_template(kind: str, template_id: str, values: dict) -> str:
    """템플릿 글에 칸 값을 채워 지시 글을 만든다. 모르는 템플릿·빠진 필수 칸·넘치는 글은 ValueError (쉬운 한국어)."""
    for t in TEMPLATES.get(kind, []):
        if t["id"] != template_id:
            continue
        if not isinstance(values, dict):
            raise ValueError("입력 값이 올바르지 않습니다.")
        filled: dict[str, str] = {}
        for f in t["fields"]:
            raw = values.get(f["key"], f.get("default", ""))
            raw = raw.strip() if isinstance(raw, str) else ""
            if not raw and f.get("required"):
                raise ValueError(f"'{f['label']}'을 적어 주세요.")
            if len(raw) > f.get("max", 600):
                raise ValueError(f"'{f['label']}'은 {f.get('max', 600)}자 이내로 적어 주세요.")
            filled[f["key"]] = raw or "(정하지 않음 — 알아서 정해 줘)"
        if set(values) - {f["key"] for f in t["fields"]}:
            raise ValueError("알 수 없는 입력 칸이 있습니다.")
        return t["text"].format(**filled).strip()
    raise ValueError("알 수 없는 시작 버튼입니다.")


def describe() -> dict:
    """화면이 쓰는 모드 설명 (GET /api/modes)."""
    return {
        "modes": [{"id": mode, "label": MODE_LABELS[mode], "kinds": [k for k, m in KIND_MODE.items() if m == mode],
                   "can_create": mode in ("design", "novel")} for mode in ("dev", "design", "novel")],
        "kinds": {k: {"label": KIND_LABELS[k], "mode": KIND_MODE[k], "creatable": k in CREATABLE,
                      "default_paths": DEFAULT_PATHS.get(k, []), "task_labels": TASK_LABELS.get(k, {})} for k in KINDS},
        "templates": {k: templates(k) for k in CREATABLE},
    }
