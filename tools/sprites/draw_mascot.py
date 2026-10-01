"""진행판 발표 캐릭터 일러스트를 Codex(본인 구독)로 그린다 — 개발용 도구 (CEO 허락 2026-09-29).

    python tools/sprites/draw_mascot.py normal          # 새 일러스트 (참고 그림 없이, CEO가 고른 목업 그림체 — 옷·체형은 자연스럽게)
    python tools/sprites/draw_mascot.py happy worried   # normal 그림을 고쳐 표정만 바꾼 그림
    python tools/sprites/draw_mascot.py normal --as normal-b   # 시안을 다른 이름으로
    python tools/sprites/draw_mascot.py present --from drafts/normal-d-chosen --as normal   # 고른 시안을 기상 캐스터 자세로 (클립보드 빼기)
    python tools/sprites/draw_mascot.py nohair          # 부위별 그림(라이브2D식 층): 긴 머리카락을 지운 그림 — 이어서 make_mascot_parts.gd
    python tools/sprites/draw_mascot.py mouth-closed    # 입 모양(다문 입) · mouth-half(반쯤 연 입) · eyes-half(뜬 눈 반쯤 감김)

결과는 assets-raw/mascot/<표정>.png (초록 배경 그대로). 배경 지우기·자르기·판 자리 재기는 make_mascot.gd, 부위별 조각·머리카락 층은 make_mascot_parts.gd.
Codex는 실행기(studio/runtimes.py CodexRuntime)를 그대로 쓴다: --ignore-user-config, 읽기 전용 샌드박스, API 키 없는 환경.
실행 기록은 %TEMP%/ais-mascot/<표정>/에 남는다 (프롬프트·이벤트).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from studio.config import load_config  # noqa: E402
from studio.runtimes import RunSpec, make_runtime  # noqa: E402
from studio.wardrobe import IMAGE_EFFORT, IMAGE_MODEL  # noqa: E402

RAW = ROOT / "assets-raw" / "mascot"

BOARD = ("She holds a large light-wood clipboard with both hands in front of her body, at chest-to-waist height, "
         "so her whole face and neck stay visible above it. The clipboard is portrait-oriented, about 45% of the image width, "
         "with a small silver clip at the top center, and holds one sheet of plain pure white paper. The white paper is completely "
         "blank (no text, no lines, no drawings), flat, facing the viewer straight on, not tilted and not rotated, evenly lit. "
         "Her fingers hold only the left and right edges of the wooden board and never cover the white paper.")
BACKGROUND = ("Background: a perfectly flat solid pure green (#00FF00) background with no shadow, no floor, no gradient and no other "
              "objects. Leave clear green space around her head and both sides.")

NORMAL = f"""Use your image generation tool to create one NEW illustration of an original character: Hana, the friendly progress presenter of our small game studio.

Art style: a glossy, highly polished modern anime illustration of mobile-game key-art quality: large sparkling expressive eyes with detailed highlights, a soft blush on the cheeks, glossy hair with many bright highlights and flowing loose strands, rich soft shading and gentle rim light, clean refined line art, a warm bright summer seaside color palette (teal, white, coral, sunny yellow).
Character: a cheerful adult woman in her mid twenties, a warm bright smile, one eye winking is fine, looking at the viewer. A clearly feminine adult figure with a natural, graceful silhouette (natural everyday proportions, nothing exaggerated). Knees-up view, standing, facing the viewer.
Hair: very long dark-brown hair in a high ponytail with soft side bangs, a white hibiscus flower clip on one side and sunglasses resting on top of her head.
Outfit (modest summer look): a knee-length teal-and-white hibiscus-print summer sundress with short flutter sleeves and a modest rounded neckline, a thin gold bracelet.
{BOARD}
{BACKGROUND}
Output one image, portrait 1024x1536."""

KEEP = ("Keep absolutely everything else the same: the same character, hair and accessories, outfit, body, pose, arms and hands in "
        "exactly the same position, the same framing and art style, and the same flat solid pure green (#00FF00) background.")

EDITS = {
    "present": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. Keep the same character exactly: the same face with the same wink and happy open smile, the same hair and ponytail, the sunglasses on her head, the white hibiscus flower clip, the same earrings and bracelet, the same teal-and-white hibiscus summer sundress, the same art style and colors, the same knees-up framing, and the same flat solid pure green (#00FF00) background.
The dress keeps the same modest rounded neckline as the original, fully covering the chest (no V-neck, no wrap front, no cleavage). Remove the clipboard completely. Change only her pose to a friendly TV weather presenter: she stands turned slightly toward the left side of the image, her arm on the image's left side extended out to the side at chest height with an open palm facing up, presenting something at the left edge of the image; her other hand rests relaxed near her waist. Keep her whole figure, including the extended hand, inside the image with green margin around her, and place her a little right of center.
Output one image, portrait 1024x1536.""",
    "happy": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. {KEEP}
Change ONLY her face: a very happy expression, both eyes closed in a big smile, mouth open laughing. Add two or three small yellow sparkles near her head.
Output one image, portrait 1024x1536.""",
    "worried": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. {KEEP}
Change ONLY her face: a worried expression with both eyes open, eyebrows raised and tilted in concern, a small uncertain mouth. Add one small blue sweat drop near her head.
Output one image, portrait 1024x1536.""",
    # 애니메이션용 (여덟 번째 세션): 눈 깜빡임 — 눈 둘레만 바꾼다 (make_mascot.gd가 바뀐 곳만 잘라 붙인다)
    "blink": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. {KEEP}
Change ONLY her eyes: both eyes gently closed in a natural, quick blink (soft closed eyelids with lashes), the same eyebrows and the same smiling mouth. Do not move or redraw anything else; every other pixel stays identical.
Output one image, portrait 1024x1536.""",
    # 애니메이션용: 판이 돌 때 손짓 — 펼친 손을 조금 더 들어 왼쪽 위의 판을 검지로 가리킨다
    "point": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. Keep absolutely everything else the same: the same character, face and expression, hair and accessories, outfit, body, the other arm, the same framing and art style, and the same flat solid pure green (#00FF00) background.
Change ONLY her extended arm on the image's left side: raise that hand a little higher to about shoulder height and point with the index finger toward the upper-left corner of the image, as if saying "look at this!". Keep the whole hand inside the image with green margin around it.
Output one image, portrait 1024x1536.""",
    # 라이브2D식 부위 (열두 번째 세션): 긴 머리카락을 떼어 층으로 — 머리카락 밑(옷·팔)을 새로 칠한 그림
    "nohair": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. Keep absolutely everything else the same: the same character, face and expression, head, bangs and the hair on top of her head, the sunglasses and hibiscus clip, outfit, body, pose, arms and hands in exactly the same position, the same framing and art style, and the same flat solid pure green (#00FF00) background.
Change ONLY this: erase the long loose hair of her ponytail that hangs down on the image's right side below the level of her shoulders (the long wavy hair flowing down beside her body toward her hip). Where that hair covered the green background, show the same flat pure green background. Where it covered her dress, arm or hand, continue the same dress print, arm and hand naturally. Do not add anything new. Every other pixel stays identical.
Output one image, portrait 1024x1536.""",
    # 입 모양 (말할 때): 다문 입·반쯤 연 입 — 평소 그림(벌린 입)과 함께 세 단계
    "mouth-closed": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. {KEEP}
Change ONLY her mouth: a gentle closed-lip smile (lips together, no teeth), the same cheerful face and the same eyes with the same wink. Do not move or redraw anything else; every other pixel stays identical.
Output one image, portrait 1024x1536.""",
    "mouth-half": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. {KEEP}
Change ONLY her mouth: a small, slightly open smile, about half as open as now, as if in the middle of saying a word, the same eyes with the same wink. Do not move or redraw anything else; every other pixel stays identical.
Output one image, portrait 1024x1536.""",
    # 눈 반쯤 감기 (깜빡임 중간): 뜬 눈만 반쯤, 윙크한 눈은 그대로
    "eyes-half": f"""Use your image generation tool in EDIT mode with the attached image as the input reference. {KEEP}
Change ONLY her open eye: relaxed and half-closed, the upper eyelid lowered halfway over the iris. Her winking eye stays closed exactly as it is. The same eyebrows and the same smiling mouth. Do not move or redraw anything else; every other pixel stays identical.
Output one image, portrait 1024x1536.""",
}


def draw(mood: str, save_as: str = "", source: str = "normal") -> bool:
    cfg = load_config(ROOT)
    if mood == "normal":
        prompt, ref = NORMAL, None
    elif mood in EDITS:
        prompt, ref = EDITS[mood], RAW / f"{source}.png"
        if not ref.is_file():
            print(f"{mood}: 고칠 그림이 없어요 ({ref})")
            return False
    else:
        print(f"모르는 이름: {mood} (normal, present, happy, worried, blink, point, nohair, mouth-closed, mouth-half, eyes-half)")
        return False
    runtime = make_runtime("codex", cfg.runtimes)
    run_dir = Path(tempfile.gettempdir()) / "ais-mascot" / mood
    work = Path(tempfile.mkdtemp(prefix="ais-mascot-cwd-"))
    spec = RunSpec(run_id=f"mascot-{mood}-{int(time.time())}", role="mascot", prompt=prompt, cwd=work, run_dir=run_dir,
                   sandbox="read-only", model=IMAGE_MODEL, effort=IMAGE_EFFORT, timeout_s=900, skip_git_check=True,
                   images=[ref] if ref else [], want_image=True)
    started = time.time()
    result = runtime.run(spec, lambda: False)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{mood}: ok={result.ok} {time.time() - started:.0f}초 그림 {len(result.images)}장 {result.error or ''}".strip())
    if not result.ok or not result.images:
        print((result.final_message or "")[:500])
        return False
    RAW.mkdir(parents=True, exist_ok=True)
    name = save_as or mood
    shutil.copyfile(result.images[0], RAW / f"{name}.png")
    print(f"  → {RAW / f'{name}.png'}")
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    opts = {}
    for flag in ("--as", "--from"):  # --as 다른 이름으로 저장 (시안 여러 벌), --from 고칠 그림
        if flag in args:
            i = args.index(flag)
            opts[flag] = args[i + 1]
            del args[i:i + 2]
    moods = args or ["normal"]
    if opts.get("--as") and len(moods) != 1:
        sys.exit("--as는 한 장만")
    sys.exit(0 if all(draw(m, opts.get("--as", ""), opts.get("--from", "normal")) for m in moods) else 1)
