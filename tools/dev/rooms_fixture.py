"""연습용 서버 (소설 집필실 · 디자인 작업실 확인용): 임시 회사 + 가짜 실행기 + 소설·디자인 예시 프로젝트 하나씩.

실제 직원·Grok·진짜 회사(8765)는 부르지 않는다. 임시 폴더에 회사를 만들고 이 저장소의 ui/를 복사해 서버를 띄운다 (끝나면 모두 지운다).
  python tools/dev/rooms_fixture.py --port 8801        # 시작하면 JSON 한 줄로 주소를 알린다. 끄려면 표준 입력에 stop
  python tools/dev/rooms_fixture.py --empty            # 소설·디자인 프로젝트가 하나도 없는 상태 (처음 쓰는 화면)
프로젝트: novel-1 '비 오는 날의 서점'(원고 1~3장·설정집·연속성 장부) · design-1 '동네 카페 메뉴판'(기획서·규칙·로그인 시안·그림 둘).
가짜 직원은 소설이면 4장 원고를, 디자인이면 시안 하나를 써 온다 (결재하면 병합 → 파일 목록이 늘어나는지 눌러 볼 수 있다).
"""
import argparse
import json
import os
import shutil
import struct
import sys
import threading
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.helpers import TempStudio, default_behavior  # noqa: E402
from studio.server import StudioServer  # noqa: E402
from studio import gitops  # noqa: E402


def make_png(w: int = 96, h: int = 64) -> bytes:
    """작은 남보라 그라데이션 PNG (표준 라이브러리만)."""
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            row += bytes((79 + x * 100 // w, 70 + y * 120 // h, 229 - x * 60 // w))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


NOVEL_FILES = {
    "bible/premise.md": """# 한 줄 소개와 기본 정보

- 한 줄 소개: 문을 닫기 직전인 동네 서점의 주인이, 비 오는 날마다 찾아오는 노인 손님의 사연을 알게 되며 마지막 계절을 정성껏 보낸다.
- 장르: 일상, 따뜻한 드라마
- 분위기: 조용하고 포근한, 조금 쓸쓸한
- 주제: 작은 가게가 사람들에게 남기는 것
- 독자: 퇴근길에 가볍게 읽고 싶은 어른
- 분량 목표: 전체 12장, 한 장 4,000자 안팎
- 시점과 시제: 3인칭 제한 시점, 과거형
""",
    "bible/characters.md": """# 인물

## 한서윤
- 나이·직업·겉모습: 서른여덟 살, 서점 주인. 늘 안경을 쓰고 소매를 걷고 있다.
- 원하는 것(겉으로): 가게의 마지막 계절을 무사히 보내는 것.
- 정말 필요한 것(속으로): 이 일을 좋아했다는 것을 스스로 인정하는 것.
- 결점·두려움: 마음이 상해도 말없이 삼키는 버릇.
- 말투·버릇: 짧게 묻고 천천히 듣는다. "그럴 수도 있겠네요." / "차 한 잔 드릴까요?"

## 박 선생님
- 나이·직업: 일흔 안팎, 퇴직한 국어 교사. 비 오는 날에만 서점에 온다.
- 말투·버릇: "오늘도 비가 오는구먼." 하고 인사한다. 시집 코너를 좋아한다.
""",
    "bible/world.md": """# 세계와 규칙

- 시간과 장소: 현재, 서울 변두리 해솔동의 골목 안 서점 '느린책방'.
- 이 세계의 규칙: 특별한 점은 없다. 지켜야 할 것은 계절과 날씨의 흐름이다.
- 중요한 장소: 느린책방(창가 의자, 계산대, 지하 창고), 골목 끝 빵집, 버스 정류장.
- 용어: 단골(비 오는 날 오는 손님), 마감장부(서윤이 쓰는 매출 장부).
""",
    "bible/outline.md": """# 줄거리와 장 구성

## 전체 줄거리
서점은 가을이 끝나면 문을 닫는다. 서윤은 그 사실을 아무에게도 말하지 않은 채 하루하루를 보낸다. 비 오는 날마다 오는 박 선생님이 찾던 시집 한 권을 계기로, 두 사람은 서로의 사정을 조금씩 알게 된다.

## 장 구성
1. 비가 오는 아침: 서윤이 가게를 열고 박 선생님이 처음 등장한다.
2. 오래된 시집: 노인이 찾는 책을 창고에서 함께 찾는다.
3. 이름 없는 메모: 시집 사이에서 나온 메모가 사연을 열어 준다.
""",
    "bible/style.md": """# 문체 규칙

- 문장은 짧고 담백하게, 한 문단은 서너 문장 안에서 끝낸다.
- 대사는 짧게. 설명하지 말고 행동과 소리로 보여 준다.
- 쓰지 않을 표현: "~라는 사실을 깨달았다" 같은 설명투.
- 폭력·성적 표현은 쓰지 않는다. 맞춤법과 띄어쓰기는 표준어 규정을 따른다.
""",
    "notes/continuity.md": """# 연속성 장부

## 복선 목록 (던진 장 → 회수한 장)
- 시집 사이에 끼워진 메모 (3장 → 아직)
- 마감장부의 빨간 줄 (1장 → 아직)

## 시간 흐름
- 1장: 10월 둘째 주 화요일, 비.
- 2장: 같은 주 금요일, 흐림 뒤 비.

## 인물 상태
- 서윤: 폐업 사실을 아직 아무에게도 말하지 않았다.
- 박 선생님: 가방에 늘 낡은 노트를 넣고 다닌다.
""",
    "chapters/001.md": """# 제1장 비가 오는 아침

아침부터 비가 내렸다. 서윤은 서점 문 앞에 우산꽂이를 내놓고, 젖은 바닥을 마른걸레로 한 번 훔쳤다. 이 동네에서 서른한 해를 버틴 가게라고는 해도, 비 오는 날의 손님은 손으로 셀 수 있을 만큼이었다.

계산대 뒤에 앉아 장부를 펼쳤다. 지난달 매출은 월세를 내고 나니 겨우 이만 원이 남았다. 서윤은 숫자를 한참 들여다보다가 장부를 덮고 따뜻한 보리차를 한 잔 따랐다. 김이 천천히 올라와 안경알을 뿌옇게 만들었다.

열 시가 조금 넘어 문에 달린 종이 울렸다. 우산을 접으며 들어선 사람은 늘 오던 노인이었다. "오늘도 비가 오는구먼." 노인은 인사처럼 그렇게 말하고, 늘 앉던 창가 의자에 가방을 내려놓았다.

서윤은 말없이 보리차를 한 잔 더 따라 가져다 놓았다. 노인은 고맙다는 말 대신 고개를 한 번 끄덕였다. 창밖에서는 빗소리가 낮게 이어지고 있었다.
""",
    "chapters/002.md": """# 제2장 오래된 시집

그날 노인은 시집 코너 앞에서 오래 서 있었다. 손가락이 책등을 따라 천천히 움직이다가 어느 자리에서 멈추었다. 있어야 할 책이 없는 자리였다.

"혹시 오래전에 나온 시집인데요." 노인이 조심스럽게 물었다. 표지가 연두색이고, 제목에 '여름'이 들어간다고 했다. 서윤은 잠깐 생각하다가 지하 창고에 몇 상자가 남아 있을 거라고 대답했다.

둘은 함께 계단을 내려갔다. 창고는 종이 냄새가 짙었고 전구는 깜빡거렸다. 서윤이 상자를 하나씩 열 때마다 노인은 허리를 굽히고 안을 들여다보았다. 세 번째 상자의 맨 밑에서 연두색 표지가 먼저 보였다.

노인은 책을 두 손으로 받아 들었다. 표지의 먼지를 소매로 닦아 내고, 한참 말이 없었다. "고맙소." 그 한마디가 창고 안에 오래 남았다. 계단을 올라오자 비가 조금 잦아들어 있었다.
""",
    "chapters/003.md": """# 제3장 이름 없는 메모

다음 비 오는 날, 노인은 시집을 다시 가져왔다. 계산대 위에 책을 올려놓더니 책장 사이에서 접힌 종이 한 장을 꺼냈다. "이게 끼워져 있었소. 내가 쓴 것은 아닌데."

종이에는 연필로 쓴 짧은 글이 있었다. 이름은 없었고, 여름 저녁에 이 책을 읽으며 기다리겠다는 내용이었다. 날짜는 삼십 년 전 칠월이었다. 서윤은 종이를 조심스럽게 펴서 계산대 유리 아래에 넣어 두었다.

"누가 누구를 기다렸을까요." 서윤이 묻자 노인은 창밖을 보며 웃었다. 대답은 하지 않았다. 대신 가방에서 낡은 노트를 꺼내 첫 장을 펼쳐 보였다. 같은 글씨체였다.

서윤은 보리차를 두 잔 따랐다. 빗소리 사이로 버스가 정류장에 서는 소리가 들렸다. 두 사람은 한참 동안 아무 말도 하지 않고 따뜻한 잔을 두 손으로 감싸고 있었다.
""",
}

DESIGN_FILES = {
    "brief/brief.md": """# 디자인 기획서

- 무엇을 만드는가: 동네 카페의 신메뉴 안내판과 모바일 로그인 화면.
- 누가 쓰는가: 단골 손님과 새로 온 손님.
- 그 사람이 가장 먼저 해야 할 일: 오늘의 메뉴를 한눈에 고른다.
- 분위기: 따뜻하다, 단정하다, 가볍다.
- 꼭 지킬 것 / 하지 말 것: 글자는 크게, 색은 세 가지만. 사진처럼 보이는 장식은 쓰지 않는다.
- 쓰는 곳과 크기: 모바일 화면 390×844, 인쇄 A4 세로.
""",
    "brief/references.md": """# 참고 자료

- 좋아하는 모양: 둥근 모서리와 넉넉한 여백. 이유: 부드럽고 읽기 쉽다.
- 피하고 싶은 모양: 빽빽한 표와 작은 글씨. 이유: 카운터 앞에서 읽기 어렵다.
""",
    "system/design-tokens.md": """# 디자인 규칙

## 색 (글자와 바탕의 대비 4.5:1 이상)
- 바탕: #faf6f0
- 글자: #2b2118
- 강조: #b4531f

## 글자 크기
- 제목 28 · 본문 16 · 보조 14 · 작은 글 13

## 간격과 모서리
- 간격은 8의 배수, 모서리는 16 또는 20.
""",
    "system/components.md": """# 부품 목록

- 단추: 기본 · 누름 · 꺼짐 · 오류 네 가지 상태, 높이 48.
- 입력칸: 라벨은 항상 위에 보이고, 오류는 아래 한 줄로 알린다.
""",
    "screens/login.html": """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>로그인 시안</title>
<style>
:root { --bg: #faf6f0; --ink: #2b2118; --accent: #b4531f; }
body { margin: 0; background: var(--bg); color: var(--ink); font-family: "Malgun Gothic", sans-serif; }
.card { max-width: 360px; margin: 64px auto; padding: 32px; border-radius: 20px; background: #fff; }
h1 { margin: 0 0 24px; font-size: 28px; }
label { display: block; margin-bottom: 16px; font-size: 14px; }
input { display: block; width: 100%; height: 48px; margin-top: 6px; padding: 0 12px; border: 1px solid #d8cfc4; border-radius: 16px; }
button { width: 100%; height: 48px; border: 0; border-radius: 16px; background: var(--accent); color: #fff; font-size: 16px; }
</style>
</head>
<body>
<main class="card">
  <h1>어서 오세요</h1>
  <label>이메일<input type="email"></label>
  <label>비밀번호<input type="password"></label>
  <button type="button">로그인</button>
</main>
</body>
</html>
""",
    "assets/logo.svg": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">
  <rect width="200" height="200" rx="40" fill="#b4531f"/>
  <circle cx="100" cy="100" r="52" fill="#faf6f0"/>
  <path d="M78 100h44M100 78v44" stroke="#b4531f" stroke-width="10" stroke-linecap="round"/>
</svg>
""",
    "assets/requests.md": """# 그림 요청서

- 메뉴판 위쪽 장식: 용도 인쇄·모바일 / 크기 800×200 / 분위기 따뜻한 커피 한 잔 / 넣지 않을 것 글자·로고.
""",
}

NOVEL_CHAPTER4 = """# 제4장 두 잔의 보리차

금요일 오후에는 비가 오지 않았다. 그래도 노인은 왔다. 우산 없이 들어선 그는 겸연쩍게 웃으며 말했다. "오늘은 비 핑계가 없구먼."

서윤은 대답 대신 보리차를 두 잔 따랐다. 계산대 위에서 김이 천천히 피어올랐다. 노인은 낡은 노트를 펼쳐 놓고 연필로 무언가를 적기 시작했다.

가게 안에는 연필 소리와 시계 소리만 있었다. 서윤은 장부 맨 뒷장에 오늘 날짜를 적고, 그 아래에 '좋은 하루'라고 한 줄을 더 써 넣었다.
"""

CARDS_HTML = """<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>메뉴 카드 시안</title>
<style>body{margin:0;background:#faf6f0;color:#2b2118;font-family:"Malgun Gothic",sans-serif}.card{margin:24px auto;max-width:320px;padding:24px;border-radius:20px;background:#fff}</style></head>
<body><div class="card"><h2>오늘의 커피</h2><p>고소한 견과류 향 · 4,500원</p></div></body></html>
"""


def seed_projects(company: TempStudio) -> list[str]:
    """소설 하나·디자인 하나를 새 프로젝트로 만들고 예시 파일을 커밋한다."""
    engine = company.engine
    keys = []
    for key, title, kind, desc, files in (
        ("novel-1", "비 오는 날의 서점", "novel", "문을 닫기 직전인 동네 서점과 비 오는 날마다 찾아오는 노인 손님의 이야기.", NOVEL_FILES),
        ("design-1", "동네 카페 메뉴판", "design", "동네 카페의 신메뉴 안내판과 모바일 로그인 화면 디자인.", DESIGN_FILES),
    ):
        project = engine.create_project({"key": key, "title": title, "kind": kind, "description": desc})
        for rel, text in files.items():
            target = project.repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        if kind == "design":
            (project.repo / "assets" / "sample.png").write_bytes(make_png())
        gitops.commit_all(project.repo, f"예시 {kind} 파일")
        keys.append(key)
    # 맡길 일 몇 개 (실행은 사람이 눌러야 한다: 자동 실행 꺼짐)
    engine.create_task({"title": "제4장 쓰기", "kind": "build", "project": "novel-1", "brief": "3장 다음 장을 쓴다.", "acceptance": ["chapters/004.md 존재"],
                        "allowed_paths": ["chapters/004.md", "notes/continuity.md"]})
    engine.create_task({"title": "1990년대 동네 서점 자료 조사", "kind": "research", "project": "novel-1", "brief": "시대 자료를 notes에 정리한다.", "allowed_paths": ["notes/**"]})
    engine.create_task({"title": "메뉴 카드 시안 만들기", "kind": "build", "project": "design-1", "brief": "오늘의 커피 카드 시안.", "acceptance": ["screens/cards.html 존재"],
                        "allowed_paths": ["screens/cards.html"]})
    return keys


def detach_stdin():
    """멈춤 신호(표준 입력 파이프)를 읽는 동안 자식 프로세스(git)가 같은 파이프를 물려받으면 윈도우에서 멈춘다.
    그래서 파이프는 따로 떼어 이쪽만 읽고, 자식에게 넘어가는 표준 입력은 빈 입력(NUL)으로 바꾼다."""
    reader = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, 0)
    os.close(nul)
    if os.name == "nt":
        import ctypes
        import msvcrt
        kernel = ctypes.windll.kernel32
        kernel.SetStdHandle.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        kernel.SetStdHandle(ctypes.c_ulong(-10).value, msvcrt.get_osfhandle(0))  # STD_INPUT_HANDLE
    return reader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8801)
    parser.add_argument("--empty", action="store_true", help="소설·디자인 프로젝트 없이 시작 (처음 쓰는 화면)")
    args = parser.parse_args()
    stop_reader = detach_stdin()
    company = TempStudio()

    def behavior(spec, runtime):
        prompt = spec.prompt
        if spec.role == "producer" and ("소설 작품이다" in prompt or "디자인 프로젝트다" in prompt):
            novel = "소설 작품이다" in prompt
            task = ({"title": "제4장 쓰기", "kind": "build", "brief": "3장 다음 장을 쓴다.", "acceptance": ["chapters/004.md 존재"], "allowed_paths": ["chapters/004.md", "notes/continuity.md"], "depends_on": []}
                    if novel else
                    {"title": "메뉴 카드 시안", "kind": "build", "brief": "오늘의 커피 카드 시안을 만든다.", "acceptance": ["screens/cards.html 존재"], "allowed_paths": ["screens/cards.html"], "depends_on": []})
            return {"structured": {"summary": "한 단계로 나눕니다.", "tasks": [task], "risks": [], "questions": []}}
        if spec.role == "builder":
            if (spec.cwd / "chapters").is_dir():
                notes = (spec.cwd / "notes" / "continuity.md").read_text(encoding="utf-8")
                return {"files": {"chapters/004.md": NOVEL_CHAPTER4, "notes/continuity.md": notes + "\n- 4장: 금요일 오후, 비 없음.\n"}, "message": "4장을 썼습니다 (약 400자)."}
            if (spec.cwd / "screens").is_dir():
                return {"files": {"screens/cards.html": CARDS_HTML}, "message": "메뉴 카드 시안을 만들었습니다."}
        return default_behavior(spec, runtime)

    company.behavior = behavior
    server = None
    try:
        company.cfg.fake_runtimes = True
        shutil.copytree(ROOT / "ui", company.root / "ui")
        keys = [] if args.empty else seed_projects(company)
        server = StudioServer(company.cfg, company.store, company.engine, args.port)
        company.store.acquire_process_lock()
        company.engine.start()
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True).start()
        print(json.dumps({"url": f"http://127.0.0.1:{args.port}/", "root": str(company.root), "projects": keys,
                          "mode": "disposable company / existing fake runtime", "real_model_calls": 0}), flush=True)
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
