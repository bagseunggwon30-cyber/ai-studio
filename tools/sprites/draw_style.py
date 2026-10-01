"""화풍 전환 시안 — 새 그림체(발표 캐릭터와 같은 일러스트)로 직원·사무실을 그려 CEO가 고르게 한다 (개발용 도구, CEO 허락 2026-09-29).

    python tools/sprites/draw_style.py staff            # 직원 4명 (하나·솔·클로·루나) 한 장
    python tools/sprites/draw_style.py office           # 사무실 한 장면 (사람 없음)
    python tools/sprites/draw_style.py staff --as staff-b   # 다른 이름으로 (시안 여러 벌)

결과: assets-raw/style-drafts/<이름>.png. 화면에는 아직 넣지 않는다 (CEO가 고른 뒤 부위별로 다시 그린다 — HANDOFF 0-4).
Codex는 실행기(studio/runtimes.py CodexRuntime)를 그대로 쓴다: --ignore-user-config, 읽기 전용 샌드박스, API 키 없는 환경.
그림 기준(CEO에게 말한 것): 자연스러운 성인 체형, 평범한 사무실 옷. 과장된 체형·노출 옷은 그리지 않는다.
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

OUT = ROOT / "assets-raw" / "style-drafts"
STYLE_REF = ROOT / "assets-raw" / "mascot" / "normal.png"

STYLE = ("Art style: match the ART STYLE of the attached reference illustration only (glossy, highly polished modern anime illustration "
         "of mobile-game key-art quality: large sparkling expressive eyes with detailed highlights, soft blush, glossy hair with bright "
         "highlights, rich soft shading, gentle rim light, clean refined line art, a warm bright summer palette with teal and white accents). "
         "Do NOT copy the reference character's face, hair or dress — the people below are different characters.")

PROMPTS = {
    "staff": f"""Use your image generation tool to create one NEW illustration: a character line-up sheet of the four staff members of a small, friendly game studio, standing side by side, full body, facing the viewer, evenly spaced, on a plain soft cream background with a light floor shadow. No text, no labels, no logos.
{STYLE}
All four are adults in their twenties with natural everyday proportions (nothing exaggerated), wearing modest office-casual clothes:
1. (far left) Hana, the planner: a cheerful young woman with a black high ponytail, a lavender-purple button-up shirt with rolled sleeves, dark slacks, holding a planning notebook and a pen.
2. Sol, the developer: a relaxed young man with messy fluffy brown hair, a blue hoodie, jeans and sneakers, headphones around his neck, holding a laptop under one arm.
3. Clo, the reviewer: a calm young woman with a short black bob, a coral-pink knit sweater, a grey skirt below the knee and tights, holding a clipboard checklist and a red pen.
4. (far right) Luna, the researcher: a gentle young woman with long wavy brown hair and round glasses, an amber-orange cardigan over a white blouse, a long skirt, hugging two books.
Each character has a distinct, readable silhouette and color. Output one image, landscape 1536x1024.""",
    "office": f"""Use your image generation tool to create one NEW illustration: the interior of a cozy, bright small game-studio office, seen from a slightly high three-quarter view like a management game, wide shot, no people, no text, no logos.
{STYLE}
Layout (keep it readable like a game stage): tall bookshelves on the far left; six office desks with monitors and chairs in two rows in the middle; a cork quest board with colorful sticky notes on the back wall between two big windows showing a sunny city; a round wall clock; a glass-walled meeting room with a round table and purple chairs on the right side; a long wooden trophy shelf under it; a cozy lounge corner at the bottom right with a cream sofa, bean bags, a small round coffee table and a coffee machine; many green potted plants; a staircase railing at the bottom left. Warm afternoon sunlight, clean and uncluttered, teal and white accents.
Output one image, landscape 1536x1024.""",
}


# 고쳐 그리기 (첫 시안을 참고 그림으로): CEO "여성 캐릭터들이 너무 말랐다" → 보통 20대 여성의 자연스러운 체형으로만.
# 강조·몸에 붙는 옷·노출은 하지 않는다 (옷·목선은 그대로).
PROMPTS["staff-figure"] = """Use your image generation tool in EDIT mode with the attached image as the input reference. Keep absolutely everything else the same: the same four characters, faces, expressions, hair, the same outfits with the same modest necklines and lengths, the same poses and props, the same colors, art style, framing and plain cream background.
Change ONLY the body shape of the three women (Hana far left, Clo third, Luna far right): they currently look too thin and flat; give them natural, average adult female figures like ordinary women in their twenties — a gently rounded bust and a softer waist-to-hip line that shows naturally through their clothes. Keep it natural and modest: nothing exaggerated or emphasized, the clothes stay loose-fitting office-casual and fully covering exactly as they are. Do not change Sol (second from left).
Output one image, landscape 1536x1024."""
REFS = {"staff-figure": OUT / "staff.png"}  # 없으면 그림체 참고(발표 캐릭터)


def draw(name: str, save_as: str = "") -> bool:
    if name not in PROMPTS:
        print(f"모르는 이름: {name} ({', '.join(PROMPTS)})")
        return False
    ref = REFS.get(name, STYLE_REF)
    if not ref.is_file():
        print(f"{name}: 참고 그림이 없어요 ({ref})")
        return False
    cfg = load_config(ROOT)
    runtime = make_runtime("codex", cfg.runtimes)
    run_dir = Path(tempfile.gettempdir()) / "ais-style" / (save_as or name)
    work = Path(tempfile.mkdtemp(prefix="ais-style-cwd-"))
    spec = RunSpec(run_id=f"style-{name}-{int(time.time())}", role="style", prompt=PROMPTS[name], cwd=work, run_dir=run_dir,
                   sandbox="read-only", model=IMAGE_MODEL, effort=IMAGE_EFFORT, timeout_s=900, skip_git_check=True,
                   images=[ref], want_image=True)
    started = time.time()
    result = runtime.run(spec, lambda: False)
    shutil.rmtree(work, ignore_errors=True)
    print(f"{name}: ok={result.ok} {time.time() - started:.0f}초 그림 {len(result.images)}장 {result.error or ''}".strip())
    if not result.ok or not result.images:
        print((result.final_message or "")[:500])
        return False
    OUT.mkdir(parents=True, exist_ok=True)
    dst = OUT / f"{save_as or name}.png"
    shutil.copyfile(result.images[0], dst)
    print(f"  → {dst}")
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    save_as = ""
    if "--as" in args:
        i = args.index("--as")
        save_as = args[i + 1]
        del args[i:i + 2]
    names = args or ["staff"]
    if save_as and len(names) != 1:
        sys.exit("--as는 한 장만")
    sys.exit(0 if all(draw(n, save_as) for n in names) else 1)
