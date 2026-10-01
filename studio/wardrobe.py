"""꾸미기 공방·캐릭터 제조실 (SPEC '의상 제조실', '꾸미기 공방 메모', '캐릭터 제조'): 새 모습(옷·체형·머리·소품·표정)·새 직원
그림을 그림 생성으로 만들고, 잘라서, CEO 승인 뒤 설치한다.

새 직원(engine: kind="hire")도 같은 길이다. 같은 일을 하는 기본 직원의 그림을 틀(template)로 삼아 자세·크기·앉는 방향은
그대로 두고 얼굴·머리·옷만 새로 그린다 (책상을 같이 쓰므로 방향이 맞아야 한다). 새 직원 그림은 <키>.<동작>, 얼굴은
portraits+<키>.png, 원본은 data/assets/raw/chars/<키>/ (나중에 의상실에서 옷을 만들 때 쓴다). 새 직원은 색 바꾸기 규칙이 없어
머리·옷 색 대신 의상실로 옷을 만든다.

설치한 그림은 프로그램 폴더(ui/·assets-raw/)가 아니라 실행 데이터 폴더 data/assets/에 둔다 (아래 '경로'). 그래야 배포 그림을
make_strips.gd로 다시 만들거나 프로그램 폴더를 다시 복사해도 설치한 옷·직원이 사라지지 않는다.

흐름 (engine: kind="look"):
1. 그림 3장 — 동작 시트(기본 시트를 EDIT 모드로, 옷만 바꿈) → 걷기(기본 걷기 + 새 시트) → 얼굴(한 사람 얼굴 참고 + 새 시트).
   data/looks/<작업>/raw/에 둔다. 그림은 본인 ChatGPT 구독의 Codex가 그린다 (API 키 없음).
2. 자르기 — tools/sprites의 Godot 도구를 작업 전용 설정(--config)으로 돌려 data/looks/<작업>/out/에 띠·얼굴·표시를 만든다.
   기본 시트도 함께 잘라(크기 기준) 두지만 설치할 때는 새 옷 것만 옮긴다.
3. 설치 — CEO가 미리보기를 보고 승인하면 data/assets로 옮기고 그쪽 index.json·parts.json에 더한다. 그때부터 꾸미기에 나온다.
4. 지우기 — 공방에서 만든 옷은 꾸미기 창의 ✕로 휴지통(data/trash/looks/)에 옮기고, 배포 옷(여름 옷 등)은 지우지 않고
   그 직원 목록에서 숨긴다 (data/wardrobe.json의 hidden, 되살릴 수 있다).

- CEO가 쓴 옷 설명은 한 줄로 다듬어 넣는다.
- 옷 세트 이름은 <캐릭터>-<작업 번호> (예: sol-t0021). 이름·설명은 data/wardrobe.json에 남는다.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

from .config import Config
from .util import atomic_copy, atomic_write_json, atomic_write_text, now_iso, read_json, stamp

ACTIONS = ["work", "rest", "call", "celebrate", "frozen", "worried", "step", "walk"]
MAX_LABEL = 16
MAX_DESC = 200
IMAGE_MODEL = "gpt-6-luna"  # make_look_set.ps1과 같은 설정 (그림 도구를 쓰는 가벼운 모델)
IMAGE_EFFORT = "low"
# 그림을 그리는 AI (CEO 요청 E): 기본 Codex, Grok은 본인 grok.com 로그인. Grok은 정사각형 JPG로 그려 PNG로 바꿔 쓴다.
DRAW_AIS = {"codex": "Codex", "grok": "Grok"}


def draw_ai(value: object) -> str:
    return str(value) if str(value) in DRAW_AIS else "codex"
class WardrobeError(ValueError):
    pass


def one_line(text: object, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---------------------------------------------------------------- 경로
# 승인해서 설치한 그림은 실행 데이터 폴더 data/assets/에 둔다 (프로그램 폴더 ui/·assets-raw/에는 런타임에 쓰지 않는다):
#   sprites/                              설치한 띠·표시·strip json (화면 주소 /assets/custom/sprites/…)
#   index.json, parts.json                설치한 띠 목록·색 통계 (배포 목록 ui/assets/sprites/의 것에 더해 쓴다)
#   portraits@<세트>.*, portraits+<키>.*  얼굴 그림 (.png .json .mask.png, 화면 주소 /assets/custom/…)
#   raw/looks/<세트>/, raw/chars/<키>/    원본 그림 (다음 꾸미기·새 옷의 바탕)
# 예전에 설치한 것은 ui/assets(배포 목록)·assets-raw에 그대로 남아 있을 수 있어, 원본은 두 곳 모두 찾는다.
CUSTOM = "custom/"                # 화면 주소 접두어: /assets/custom/<경로> → data/assets/<경로>
CUSTOM_SPRITES = "custom/sprites/"  # 설치한 띠 항목의 dir 값 (화면은 ${BASE}${meta.dir || 'sprites/'}${meta.file})
SET_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_LOCK = threading.RLock()  # data/assets·wardrobe.json을 읽고 고쳐 쓰는 일 (승인·지우기·숨기기가 겹치지 않게)


def assets_dir(cfg: Config) -> Path:
    return cfg.data_dir / "assets"


def sprites_dir(cfg: Config) -> Path:
    """설치한 띠·표시가 있는 곳 (배포 그림은 base_sprites_dir)."""
    return assets_dir(cfg) / "sprites"


def base_sprites_dir(cfg: Config) -> Path:
    return cfg.ui_dir / "assets" / "sprites"


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def sprite_index(cfg: Config) -> dict[str, dict]:
    """그림 띠 목록: 배포 목록(ui/assets/sprites/index.json)에 설치한 목록(data/assets/index.json)을 합친 것."""
    return {**_dict(read_json(base_sprites_dir(cfg) / "index.json", {})), **_dict(read_json(assets_dir(cfg) / "index.json", {}))}


def sprite_parts(cfg: Config) -> dict[str, dict]:
    """색 바꾸기 통계: 배포 것에 설치한 것을 합친 것."""
    return {**_dict(read_json(base_sprites_dir(cfg) / "parts.json", {})), **_dict(read_json(assets_dir(cfg) / "parts.json", {}))}


def asset_path(cfg: Config, file: str) -> Path:
    """얼굴 목록의 file 값(화면 주소 /assets/ 아래 경로)이 가리키는 실제 파일. custom/은 data/assets, 나머지는 ui/assets."""
    if file.startswith(CUSTOM):
        return assets_dir(cfg) / file[len(CUSTOM):]
    return cfg.ui_dir / "assets" / file


def rel_path(cfg: Config, path: Path) -> str:
    """Godot 도구에 넘기는 경로: 프로젝트 폴더 안이면 상대 경로, 밖이면 절대 경로."""
    return path.relative_to(cfg.root).as_posix() if path.is_relative_to(cfg.root) else path.as_posix()


def check_set(set_name: str) -> str:
    if not SET_RE.match(str(set_name)) or str(set_name) == "base":
        raise WardrobeError("옷 이름이 올바르지 않습니다.")
    return str(set_name)


def job_dir(cfg: Config, task_id: str) -> Path:
    if not re.fullmatch(r"T\d{4,}", task_id):
        raise WardrobeError("작업 번호가 올바르지 않습니다.")
    return cfg.data_dir / "looks" / task_id


def sheets_config(cfg: Config) -> dict:
    data = read_json(cfg.root / "tools" / "sprites" / "sheets.json", None)
    if not isinstance(data, dict):
        raise WardrobeError("tools/sprites/sheets.json을 읽을 수 없습니다.")
    return data


# 새 직원의 틀: 같은 일을 하는 기본 직원 (같은 책상, 같은 앉는 방향)
JOB_TEMPLATE = {"producer": "hana", "builder": "sol", "reviewer": "clo", "analyst": "luna"}


def staff_entry(cfg: Config, character: str) -> dict | None:
    reg = read_json(cfg.data_dir / "staff.json", {}) or {}
    return next((e for e in reg.get("staff") or [] if isinstance(e, dict) and e.get("key") == character), None)


def char_dir(cfg: Config, character: str) -> Path:
    """새 직원의 원본 그림을 설치하는 곳 (data/assets/raw/chars/<키>/)."""
    return assets_dir(cfg) / "raw" / "chars" / character


def char_dirs(cfg: Config, character: str) -> list[Path]:
    """새 직원 원본을 찾는 곳: 새 위치 먼저, 예전 위치(assets-raw/chars/<키>/)도 본다."""
    return [char_dir(cfg, character), cfg.root / "assets-raw" / "chars" / character]


def base_sources(cfg: Config, character: str) -> dict[str, Any]:
    """이 캐릭터의 기본 그림: 동작 시트·걷기(원본), 얼굴 아틀라스와 칸. 새 직원은 틀의 칸 배치를 물려받는다."""
    entry = staff_entry(cfg, character)
    if entry:
        t = base_sources(cfg, str(entry.get("template", "")))
        body_name, walk_name = f"char-{character}.png", f"walk-{character}.png"
        folder = next((f for f in char_dirs(cfg, character) if (f / body_name).is_file() and (f / walk_name).is_file()),
                      char_dir(cfg, character))
        body = {**t["body"], "file": rel_path(cfg, folder / body_name), "character": character}
        walk = {**t["walk"], "file": rel_path(cfg, folder / walk_name), "character": character}
        face = faces(cfg).get(character) or {"file": f"portraits+{character}.png"}
        return {"sheets": [body, walk], "body": body, "walk": walk, "face_atlas": rel_path(cfg, asset_path(cfg, face["file"])),
                "face_col": 0, "face_cols": 1}
    base = sheets_config(cfg)
    sheets = [s for s in base["sheets"] if s.get("character") == character]
    body = next((s for s in sheets if "matchHeightOf" not in s), None)
    walk = next((s for s in sheets if "matchHeightOf" in s), None)
    chars = base["portraits"]["characters"]
    if not body or not walk or character not in chars:
        raise WardrobeError(f"'{character}'의 기본 그림 설정이 없습니다.")
    return {"sheets": sheets, "body": body, "walk": walk, "face_atlas": base["portraits"]["out"],
            "face_col": chars.index(character), "face_cols": len(chars)}


# ---------------------------------------------------------------- 꾸미기 종류 (CEO 결정 2026-09-29: 늘리기 대신 새로 그리기)
# 지금 입은 모습(세트)에서 한 가지만 바꿔 새 세트를 그린다. 그래서 여름 옷 + 안경처럼 겹쳐 쌓인다.
# keep: 그대로 둘 것, change: 시트에서 바꿀 것, part: 걷기·얼굴 그림에서 두 번째 그림에 맞출 것, rule: 지킬 것.
KINDS: dict[str, dict[str, str]] = {
    "outfit": {"label": "옷", "keep": "the same face, hair and body proportions",
               "change": "Change ONLY the clothes, in all 8 cells", "part": "the clothes", "rule": ""},
    "body": {"label": "체형", "keep": "the same face, hairstyle, clothes design and colors, and the same head size",
             "change": ("Change ONLY the body type, in all 8 cells, redrawing the clothes so they fit the new body. "
                        "A taller or shorter body keeps the same head size and the feet on the same ground line"),
             "part": "the body type", "rule": ""},
    "hair": {"label": "머리 모양", "keep": "the same face, clothes and body proportions",
             "change": ("Change ONLY the hairstyle (and the hair color only if it is described), in all 8 cells, "
                        "drawn correctly from each pose's angle including the back views in cells 1, 2 and 6"),
             "part": "the hairstyle", "rule": ""},
    "accessory": {"label": "안경·소품", "keep": "the same face, hair, clothes and body proportions",
                  "change": "ADD ONLY this accessory, drawn the same way in all 8 cells from each pose's angle",
                  "part": "the accessory", "rule": ("Everyday office accessories only (glasses, caps, beanies, headbands, "
                                                     "scarves, headphones, bags, badges).")},
    "face": {"label": "표정", "keep": "the same hair, clothes, body proportions, head shape and size",
             "change": ("Change ONLY the face: the eyes, eyebrows and usual expression style, in every cell where the face "
                        "is visible. Each pose keeps its feeling (cheering stays happy, worried stays worried, surprised stays surprised)"),
             "part": "the face style (eyes, eyebrows, expression style)", "rule": ""},
}


def kind_of(kind: object) -> str:
    return str(kind) if str(kind) in KINDS else "outfit"


def sheet_prompt(who: str, desc: str, kind: str = "outfit") -> str:
    k = KINDS[kind_of(kind)]
    return f"""Use your image generation tool in EDIT mode with the attached image as the input reference. It is the sprite sheet of our game character {who}. Keep the exact same 4x2 grid layout, the same 8 poses in the same cells, the same position of the character in every cell, {k['keep']}, the same crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.

{k['change']}: {desc}
{k['rule']}
Everything else stays identical. No text, no shadows, no floor, no grid lines, no effects."""


def walk_prompt(who: str, desc: str, kind: str = "outfit") -> str:
    k = KINDS[kind_of(kind)]
    return f"""Use your image generation tool in EDIT mode with the FIRST attached image as the input reference. It is the 4-frame walk cycle of our game character {who}. Keep the exact same 4 frames in one row, the same poses, positions and crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.

Change ONLY {k['part']} in all 4 frames so it matches the character in the SECOND attached image: {desc}
{k['rule']}
No text, no shadows, no ground line, no grid lines, no motion marks."""


def face_prompt(who: str, desc: str, kind: str = "outfit") -> str:
    k = KINDS[kind_of(kind)]
    return f"""Use your image generation tool in EDIT mode with the FIRST attached image as the input reference. It shows 3 bust portraits of our game character {who} in one column: normal (top), happy (middle), worried (bottom). Keep the exact same single column of 3 portraits with clear magenta space between them, the same three moods, sizes, framing and crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, portrait 1024x1536.

Change ONLY {k['part']} so it matches the character in the SECOND attached image: {desc}
{k['rule']}
No text, no frames, no shadows, no grid lines."""


def set_raw_dir(cfg: Config, set_name: str) -> Path:
    """세트의 원본 그림 폴더 (시트·걷기·얼굴). 설치할 때 여기에 둔다 (data/assets/raw/looks/<세트>/)."""
    return assets_dir(cfg) / "raw" / "looks" / check_set(set_name)


def sources(cfg: Config, character: str, set_name: str | None = None) -> dict[str, Any]:
    """이 캐릭터가 지금 입은 모습의 원본 그림: 세트가 있으면 그 세트의 시트·걷기·얼굴, 없으면 기본 그림 (base_sources).

    세트 원본은 data/assets/raw/looks/<세트>/를 먼저 보고, 없으면 예전 위치를 본다: 배포 세트(여름 옷)와 예전에 설치한 세트는
    assets-raw/looks/<세트>/, 더 예전에 만든 세트는 그 작업 폴더(data/looks/<작업>/raw/).
    """
    src = base_sources(cfg, character)
    if not set_name or set_name == "base":
        return {**src, "set": None}
    folders = [set_raw_dir(cfg, set_name), cfg.root / "assets-raw" / "looks" / set_name]
    entry = ((read_json(cfg.data_dir / "wardrobe.json", {}) or {}).get("looks") or {}).get(set_name) or {}
    task = str(entry.get("task", ""))
    if re.fullmatch(r"T\d{4,}", task):
        folders.append(job_dir(cfg, task) / "raw")
    body_name, walk_name = Path(src["body"]["file"]).name, Path(src["walk"]["file"]).name
    folder = next((f for f in folders if (f / body_name).is_file() and (f / walk_name).is_file()), None)
    face = faces(cfg).get(f"{character}@{set_name}")
    if folder is None or face is None:
        raise WardrobeError(f"지금 모습('{set_name}')의 원본 그림을 찾지 못했어요. 꾸미기에서 기본 모습으로 바꾼 뒤 주문해 주세요.")

    body = {**src["body"], "file": rel_path(cfg, folder / body_name), "character": f"{character}@{set_name}"}
    walk = {**src["walk"], "file": rel_path(cfg, folder / walk_name), "character": f"{character}@{set_name}"}
    body.pop("scaleTo", None)
    return {"sheets": [body, walk], "body": body, "walk": walk, "face_atlas": rel_path(cfg, asset_path(cfg, face["file"])),
            "face_col": face["col"], "face_cols": face["cols"], "set": set_name}




def hire_sheet_prompt(template: str, looks: str) -> str:
    return f"""Use your image generation tool in EDIT mode with the attached image as the LAYOUT reference. It is the sprite sheet of an existing game character ({template}). Draw a DIFFERENT, NEW character instead: {looks}
Keep the exact same 4x2 grid layout, the same 8 poses in the same cells (same body positions, same facing direction), the same size and position of the character in every cell, the same chibi office-worker proportions and crisp 16-bit pixel-art style, and the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.
The new character must clearly look like a different person: a different face, hairstyle, hair color and clothes, as described.
No text, no shadows, no floor, no grid lines, no effects."""


def hire_walk_prompt(looks: str) -> str:
    return f"""Use your image generation tool in EDIT mode with the FIRST attached image as the LAYOUT reference. It is the 4-frame walk cycle of an existing game character. Draw the NEW character shown in the SECOND attached image ({looks}) with the same face, hair and clothes, in exactly the same 4 frames in one row: same poses, positions, sizes, facing direction and crisp 16-bit pixel-art style, on the same flat solid pure magenta (#FF00FF) background. Output one new image, landscape 1536x1024.
No text, no shadows, no ground line, no grid lines, no motion marks."""


def hire_face_prompt(looks: str) -> str:
    return f"""Use your image generation tool in EDIT mode with the FIRST attached image as the LAYOUT reference. It shows 3 bust portraits of an existing game character in one column: normal (top), happy (middle), worried (bottom). Draw the NEW character shown in the SECOND attached image ({looks}) as the same 3 bust portraits with the same expressions, in exactly the same single column with clear magenta space between them, the same sizes, framing and crisp 16-bit pixel-art style, on the same flat solid pure magenta (#FF00FF) background. Output one new image, portrait 1024x1536.
No text, no frames, no shadows, no grid lines."""


# ---------------------------------------------------------------- 자르기 (Godot 도구)
def job_config(cfg: Config, character: str, set_name: str, raw: Path, out: Path, base_set: str | None = None,
               kind: str = "outfit") -> dict:
    """이 모습 하나만 자르는 설정: 기본 시트 + 바탕 세트 시트(크기 기준) + 새 시트, 얼굴 한 사람, 색 규칙은 이 캐릭터 것만.

    새 시트는 바탕 모습의 서 있는 키에 맞춘다. 체형은 키가 바뀌는 것이 목적이라 맞추지 않는다 (EDIT 모드라 그림 배율은 같다).
    """
    base = sheets_config(cfg)
    plain = base_sources(cfg, character)
    src = sources(cfg, character, base_set)
    ref = f"{character}@{base_set}" if src["set"] else character
    sheets = [dict(s) for s in plain["sheets"]]
    if src["set"]:
        sheets += [dict(s) for s in src["sheets"]]
    for s in plain["sheets"]:
        n = dict(s)
        n["file"] = str(raw / Path(s["file"]).name)
        n["character"] = f"{character}@{set_name}"
        n.pop("scaleTo", None)
        if "matchHeightOf" not in s and kind_of(kind) != "body":
            n["scaleTo"] = f"{ref}.step"
        sheets.append(n)
    face_out = str(out / f"portraits@{set_name}.png")
    parts = base.get("parts", {})
    return {
        "out": str(out / "sprites"),
        "preview": False,
        "loops": base.get("loops", []),
        "fps": base.get("fps", {}),
        "minArea": base.get("minArea", {}),
        "parts": {character: parts[character]} if character in parts else {},
        "sheets": sheets,
        "portraits": {**base["portraits"], "characters": [character]},
        "faceJobs": [{"src": str(raw / "portraits.png"), "out": face_out, "characters": [character]}],
        "faceAtlases": [{"file": face_out, "whos": [f"{character}@{set_name}"], "characters": [character]}],
    }


def hire_config(cfg: Config, template: str, key: str, raw: Path, out: Path) -> dict:
    """새 직원 그림을 자르는 설정: 틀 직원 시트(크기 기준) + 새 직원 시트(틀의 서 있는 키에 맞춤), 얼굴 한 사람, 색 규칙 없음."""
    base = sheets_config(cfg)
    t = base_sources(cfg, template)
    sheets = [dict(x) for x in t["sheets"]]
    for x in t["sheets"]:
        n = dict(x)
        walk = "matchHeightOf" in x
        n["file"] = str(raw / (f"walk-{key}.png" if walk else f"char-{key}.png"))
        n["character"] = key
        if not walk:
            n["scaleTo"] = f"{template}.step"
        sheets.append(n)
    face_out = str(out / f"portraits+{key}.png")
    return {
        "out": str(out / "sprites"),
        "preview": False,
        "loops": base.get("loops", []),
        "fps": base.get("fps", {}),
        "minArea": base.get("minArea", {}),
        "parts": {},
        "sheets": sheets,
        "portraits": {**base["portraits"], "characters": [key]},
        "faceJobs": [{"src": str(raw / "portraits.png"), "out": face_out, "characters": [key]}],
        "faceAtlases": [{"file": face_out, "whos": [key], "characters": [key]}],
    }


def godot(cfg: Config, script: str, *args: str, timeout: int = 600) -> tuple[bool, str]:
    exe = cfg.godot_path()
    if not exe or not Path(exe).is_file():
        return False, "Godot을 찾을 수 없습니다 (studio.toml [tools] godot)."
    cmd = [exe, "--headless", "--path", str(cfg.root / "tools" / "sprites"), "--script", f"res://{script}", "--",
           f"--root={cfg.root.as_posix()}", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=str(cfg.root))
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"Godot 실행 실패: {e}"
    log = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0 and "ERROR" not in log, log


def to_png(cfg: Config, src: Path, dest: Path) -> tuple[bool, str]:
    """그림 한 장을 PNG로 (Grok은 JPG로 저장한다). 이미 PNG면 그대로 복사."""
    if src.suffix.lower() == ".png":
        shutil.copyfile(src, dest)
        return True, ""
    return godot(cfg, "to_png.gd", f"--in={src.as_posix()}", f"--out={dest.as_posix()}")


def face_ref(cfg: Config, character: str, dest: Path, set_name: str | None = None) -> tuple[bool, str]:
    src = sources(cfg, character, set_name)
    return godot(cfg, "make_face_ref.gd", f"--atlas={src['face_atlas']}", f"--col={src['face_col']}",
                 f"--cols={src['face_cols']}", f"--out={dest.as_posix()}")


def process(cfg: Config, character: str, set_name: str, task_id: str, base_set: str | None = None,
            kind: str = "outfit") -> tuple[bool, str]:
    """새 모습: raw/의 그림 3장을 잘라 out/에 띠·얼굴·표시를 만든다. 결과: (성공, 기록)."""
    d = job_dir(cfg, task_id)
    return _run_tools(cfg, d, job_config(cfg, character, set_name, d / "raw", d / "out", base_set, kind),
                      f"{character}@{set_name}", f"portraits@{set_name}.png")


def process_hire(cfg: Config, template: str, key: str, task_id: str) -> tuple[bool, str]:
    """새 직원: raw/의 그림 3장을 잘라 out/에 띠·얼굴을 만든다."""
    d = job_dir(cfg, task_id)
    return _run_tools(cfg, d, hire_config(cfg, template, key, d / "raw", d / "out"), key, f"portraits+{key}.png")


def _run_tools(cfg: Config, d: Path, config: dict, who: str, face: str) -> tuple[bool, str]:
    out = d / "out"
    if out.exists():
        shutil.rmtree(out)
    (out / "sprites").mkdir(parents=True)
    conf = d / "job.json"
    atomic_write_json(conf, config)
    logs = []
    for script in ("make_strips.gd", "make_portraits.gd", "make_masks.gd"):
        ok, log = godot(cfg, script, f"--config={conf.as_posix()}")
        logs.append(f"== {script}\n{log}")
        if not ok:
            atomic_write_text(d / "process.log", "\n".join(logs))
            return False, f"{script} 실패"
    atomic_write_text(d / "process.log", "\n".join(logs))
    missing = _missing(out, who, face)
    return (not missing, "빠진 그림: " + ", ".join(missing) if missing else "")


def _missing(out: Path, who: str, face: str) -> list[str]:
    index = read_json(out / "sprites" / "index.json", {}) or {}
    missing = [a for a in ACTIONS if f"{who}.{a}" not in index]
    if not (out / face).is_file():
        missing.append("얼굴")
    return missing


def check(cfg: Config, character: str, set_name: str, task_id: str) -> list[str]:
    return _missing(job_dir(cfg, task_id) / "out", f"{character}@{set_name}", f"portraits@{set_name}.png")


# ---------------------------------------------------------------- 미리보기·설치
PREVIEW_RE = re.compile(r"^[a-z0-9@.+-]+\.png$")


def preview_file(cfg: Config, task_id: str, name: str) -> Path:
    """승인 전 미리보기 그림 (out/ 아래 PNG만, 이름 규칙으로 경로 밖으로 못 나가게)."""
    if not PREVIEW_RE.match(name) or ".." in name:
        raise WardrobeError("그림 이름이 올바르지 않습니다.")
    out = job_dir(cfg, task_id) / "out"
    for folder in (out / "sprites", out):
        p = folder / name
        if p.is_file():
            return p
    raise WardrobeError("미리보기 그림이 없습니다.")


def install(cfg: Config, character: str, set_name: str, task_id: str, label: str, desc: str, kind: str = "outfit",
            base_set: str | None = None) -> None:
    """승인: 새 모습의 띠·얼굴·표시를 data/assets로 옮기고 그쪽 index.json·parts.json에 더한다 (ui/·assets-raw/에는 쓰지 않는다).
    원본 그림은 data/assets/raw/looks/<세트>/에 남긴다 (이 모습에서 또 꾸밀 때 바탕이 된다)."""
    check_set(set_name)
    d = job_dir(cfg, task_id)
    with _LOCK:
        _install(cfg, d / "out", f"{character}@{set_name}", f"portraits@{set_name}")
        folder = set_raw_dir(cfg, set_name)
        for f in (d / "raw").glob("*.png"):
            if f.name != "face-ref.png":
                atomic_copy(f, folder / f.name)
        reg = _dict(read_json(cfg.data_dir / "wardrobe.json", {}))
        reg.setdefault("looks", {})[set_name] = {"character": character, "label": label, "desc": desc, "task": task_id, "at": now_iso(),
                                                 "kind": kind_of(kind), "base": base_set or "base"}
        atomic_write_json(cfg.data_dir / "wardrobe.json", reg)


def install_character(cfg: Config, key: str, task_id: str) -> None:
    """새 직원 승인: 띠·얼굴을 data/assets로 옮기고, 원본 그림은 data/assets/raw/chars/<키>/에 둔다 (나중에 새 옷의 틀)."""
    d = job_dir(cfg, task_id)
    with _LOCK:
        _install(cfg, d / "out", key, f"portraits+{key}")
        folder = char_dir(cfg, key)
        for name in (f"char-{key}.png", f"walk-{key}.png", "portraits.png"):
            if (d / "raw" / name).is_file():
                atomic_copy(d / "raw" / name, folder / name)


def _install(cfg: Config, out: Path, who: str, face_stem: str) -> None:
    missing = _missing(out, who, face_stem + ".png")
    if missing:
        raise WardrobeError("그림이 모자라 설치할 수 없습니다: " + ", ".join(missing))
    staged = _dict(read_json(out / "sprites" / "index.json", {}))
    staged_parts = _dict(read_json(out / "sprites" / "parts.json", {}))
    assets, dest = assets_dir(cfg), sprites_dir(cfg)
    index = _dict(read_json(assets / "index.json", {}))
    parts = _dict(read_json(assets / "parts.json", {}))
    for key, meta in staged.items():
        if not key.startswith(who + "."):
            continue
        for name in (meta.get("file"), meta.get("mask"), str(meta.get("file", "")).replace(".strip.png", ".strip.json")):
            name = Path(str(name or "")).name
            if name and (out / "sprites" / name).is_file():
                atomic_copy(out / "sprites" / name, dest / name)
        index[key] = {**meta, "dir": CUSTOM_SPRITES}  # 화면이 그림 위치를 알 수 있게 (배포 그림은 dir이 없다)
    for key in (who, f"{who}:face"):
        if key in staged_parts:
            parts[key] = staged_parts[key]
    for suffix in (".png", ".json", ".mask.png"):
        src = out / f"{face_stem}{suffix}"
        if src.is_file():
            atomic_copy(src, assets / src.name)
    atomic_write_json(assets / "parts.json", parts)
    atomic_write_json(assets / "index.json", index)  # 마지막에: 화면은 index.json이 바뀌면 새 그림을 안다


# ---------------------------------------------------------------- 목록·이름·얼굴
def labels(cfg: Config) -> dict[str, str]:
    reg = _dict(read_json(cfg.data_dir / "wardrobe.json", {}))
    return {k: str(v.get("label") or k) for k, v in _dict(reg.get("looks")).items() if isinstance(v, dict)}


def sprite_version(cfg: Config) -> str:
    """화면이 그림 목록(index.json)을 다시 읽어야 하는지 알 수 있게: 배포 목록과 설치 목록 중 새 시각."""
    stamps = []
    for path in (base_sprites_dir(cfg) / "index.json", assets_dir(cfg) / "index.json"):
        try:
            stamps.append(path.stat().st_mtime_ns)
        except OSError:
            pass
    return str(max(stamps)) if stamps else ""


def faces(cfg: Config) -> dict[str, dict]:
    """얼굴 아틀라스 목록: 누구(<캐릭터>[@세트])의 얼굴이 어느 그림의 몇 번째 칸에 있는지.

    portraits.png(기본 4명), portraits@<세트>.png(세트: 여러 명 또는 한 명), portraits+<캐릭터>.png(새 직원).
    파일 이름의 @ 뒤가 세트다 (새 직원 옷: portraits@staff1-t0031.png → staff1@staff1-t0031).
    배포 그림은 ui/assets, 설치한 그림은 data/assets에 있고 그쪽은 file이 "custom/portraits@…png"다 (화면 주소 /assets/ 기준).
    """
    out: dict[str, dict] = {}
    for folder, prefix in ((cfg.ui_dir / "assets", ""), (assets_dir(cfg), CUSTOM)):
        for meta_path in sorted(folder.glob("portraits*.json")):
            meta = read_json(meta_path, None)
            if not isinstance(meta, dict) or not isinstance(meta.get("characters"), list):
                continue
            stem = meta_path.stem  # portraits, portraits@summer, portraits+staff1
            suffix = "@" + stem.split("@", 1)[1] if "@" in stem else ""
            chars = [str(c) for c in meta["characters"]]
            for i, c in enumerate(chars):
                out[c + suffix] = {"file": f"{prefix}{stem}.png", "col": i, "cols": len(chars)}
    return out


# ---------------------------------------------------------------- 지우기·숨기기 (꾸미기 창의 ✕)
def hidden(cfg: Config) -> dict[str, list[str]]:
    """직원(캐릭터)마다 목록에서 숨긴 옷 (data/wardrobe.json의 hidden)."""
    raw = _dict(_dict(read_json(cfg.data_dir / "wardrobe.json", {})).get("hidden"))
    return {str(c): [str(x) for x in v if str(x)] for c, v in raw.items() if isinstance(v, list) and v}


def set_hidden(cfg: Config, character: str, set_name: str, on: bool) -> bool:
    """그 직원 목록에서 옷을 숨기거나(on) 되살린다. 바뀌었으면 True. 그림은 그대로 둔다 (배포 옷은 지울 수 없다)."""
    check_set(set_name)
    with _LOCK:
        reg = _dict(read_json(cfg.data_dir / "wardrobe.json", {}))
        table = {c: list(v) for c, v in hidden(cfg).items()}
        mine = table.get(character, [])
        if (set_name in mine) == on:
            return False
        table[character] = [*mine, set_name] if on else [x for x in mine if x != set_name]
        reg["hidden"] = {c: v for c, v in table.items() if v}
        atomic_write_json(cfg.data_dir / "wardrobe.json", reg)
        return True


def made_sets(cfg: Config) -> list[str]:
    """공방에서 만들어 data/assets에 설치한 옷 (지울 수 있는 것). 예전에 ui/assets에 설치한 옷은 배포 옷처럼 숨기기만 된다."""
    reg = _dict(read_json(cfg.data_dir / "wardrobe.json", {}))
    index = _dict(read_json(assets_dir(cfg) / "index.json", {}))
    out = []
    for name, entry in _dict(reg.get("looks")).items():
        if isinstance(entry, dict) and f"{entry.get('character', '')}@{name}.step" in index:
            out.append(str(name))
    return sorted(out)


def _move(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def trash_look(cfg: Config, character: str, set_name: str) -> Path:
    """공방에서 만든 옷을 휴지통(data/trash/looks/<세트>-<시각>/)으로 옮긴다: 띠·표시·얼굴·원본.
    설치 목록(index.json)·색 통계(parts.json)·이름 목록(wardrobe.json)에서도 뺀다. 휴지통 위치를 돌려준다."""
    check_set(set_name)
    who, stem = f"{character}@{set_name}", f"portraits@{set_name}"
    with _LOCK:
        assets = assets_dir(cfg)
        index = _dict(read_json(assets / "index.json", {}))
        mine = {k: v for k, v in index.items() if k.split(".")[0] == who and isinstance(v, dict)}
        if set_name not in made_sets(cfg) or not mine:
            raise WardrobeError("공방에서 만든 옷이 아니라서 지울 수 없어요.")
        trash = cfg.data_dir / "trash" / "looks" / f"{set_name}-{stamp()}"
        # 목록에서 먼저 뺀다: 화면이 없어진 그림을 더 부르지 않게
        parts = _dict(read_json(assets / "parts.json", {}))
        for k in mine:
            index.pop(k)
        for k in (who, f"{who}:face"):
            parts.pop(k, None)
        atomic_write_json(assets / "parts.json", parts)
        atomic_write_json(assets / "index.json", index)
        for meta in mine.values():
            for name in (meta.get("file"), meta.get("mask"), str(meta.get("file", "")).replace(".strip.png", ".strip.json")):
                name = Path(str(name or "")).name
                if name:
                    _move(sprites_dir(cfg) / name, trash / "sprites" / name)
        for suffix in (".png", ".json", ".mask.png"):
            _move(assets / f"{stem}{suffix}", trash / f"{stem}{suffix}")
        _move(set_raw_dir(cfg, set_name), trash / "raw")
        reg = _dict(read_json(cfg.data_dir / "wardrobe.json", {}))
        _dict(reg.get("looks")).pop(set_name, None)
        atomic_write_json(cfg.data_dir / "wardrobe.json", reg)
        set_hidden(cfg, character, set_name, False)
        return trash


def trash_character(cfg: Config, key: str) -> Path | None:
    """내보낸 새 직원의 그림을 휴지통(data/trash/staff/<키>-<시각>/)으로 옮긴다: 띠·표시·얼굴(자기 것과 옷 세트)·원본.
    설치 목록(index.json)·색 통계(parts.json)·옷 이름 목록(wardrobe.json)에서도 뺀다. 옮긴 것이 없으면 None.
    예전 위치(ui/assets·assets-raw)의 그림은 프로그램 폴더라 건드리지 않는다 (명부에서 빠지면 화면에 나오지 않는다)."""
    if not re.fullmatch(r"staff\d{1,3}", key):
        raise WardrobeError("새 직원만 내보낼 수 있어요.")
    with _LOCK:
        assets = assets_dir(cfg)
        trash = cfg.data_dir / "trash" / "staff" / f"{key}-{stamp()}"
        index = _dict(read_json(assets / "index.json", {}))
        parts = _dict(read_json(assets / "parts.json", {}))
        mine = {k: v for k, v in index.items() if k.split(".")[0].split("@")[0] == key and isinstance(v, dict)}
        sets = sorted({k.split(".")[0].split("@")[1] for k in mine if "@" in k.split(".")[0]})
        for k in mine:
            index.pop(k)
        for k in list(parts):
            if k.split(":")[0].split("@")[0] == key:
                parts.pop(k)
        atomic_write_json(assets / "parts.json", parts)
        atomic_write_json(assets / "index.json", index)
        moved = bool(mine)
        for meta in mine.values():
            for name in (meta.get("file"), meta.get("mask"), str(meta.get("file", "")).replace(".strip.png", ".strip.json")):
                name = Path(str(name or "")).name
                if name and (sprites_dir(cfg) / name).exists():
                    _move(sprites_dir(cfg) / name, trash / "sprites" / name)
        stems = [f"portraits+{key}", *(f"portraits@{s}" for s in sets)]
        for stem in stems:
            for suffix in (".png", ".json", ".mask.png"):
                if (assets / f"{stem}{suffix}").exists():
                    _move(assets / f"{stem}{suffix}", trash / f"{stem}{suffix}")
                    moved = True
        if char_dir(cfg, key).exists():
            _move(char_dir(cfg, key), trash / "raw" / "chars" / key)
            moved = True
        reg = _dict(read_json(cfg.data_dir / "wardrobe.json", {}))
        looks = _dict(reg.get("looks"))
        for name in [n for n, e in looks.items() if isinstance(e, dict) and e.get("character") == key]:
            looks.pop(name)
            if SET_RE.match(name) and set_raw_dir(cfg, name).exists():
                _move(set_raw_dir(cfg, name), trash / "raw" / "looks" / name)
                moved = True
        hidden_table = _dict(reg.get("hidden"))
        hidden_table.pop(key, None)
        atomic_write_json(cfg.data_dir / "wardrobe.json", reg)
        return trash if moved else None


# ---------------------------------------------------------------- 연습용(--fake) 그림 색 바꾸기
def fake_hue(task_id: str) -> int:
    """연습용 그림에서 옷 색을 돌릴 각도 (30~315도, 15도 단위). 작업 번호로 정해서 주문마다 다르게 보인다."""
    n = int(re.sub(r"\D", "", str(task_id)) or 0)
    return 30 + (n * 137) % 300 // 15 * 15


def fake_tint(cfg: Config, task_id: str, character: str, base_set: str | None, path: Path) -> tuple[bool, str]:
    """연습용(--fake) 회사에서만 부른다: 가짜 실행기가 돌려준 그림(지금 모습)의 옷 색만 돌려 새 옷처럼 보이게 한다.

    기본 모습에서 만드는 기본 직원은 sheets.json parts[<캐릭터>].outfit 규칙(색상·채도·밝기)에 맞는 픽셀만,
    규칙이 없는 새 직원이나 다른 세트를 바탕으로 한 모습은 채도가 높은 픽셀 중 피부·머리 갈색 쪽을 뺀 것을 돌린다.
    path의 그림을 그 자리에서 바꾼다 (참고 그림 원본은 건드리지 않는다: path는 복사본).
    """
    rule = None
    if not base_set:
        rule = _dict(_dict(sheets_config(cfg).get("parts")).get(character)).get("outfit")
    tmp = path.with_name(path.stem + ".tint.png")
    args = [f"--in={path.as_posix()}", f"--out={tmp.as_posix()}", f"--hue={fake_hue(task_id)}"]
    if isinstance(rule, dict) and all(isinstance(rule.get(k), list) and len(rule[k]) == 2 for k in ("h", "s", "v")):
        args += [f"--{k}={rule[k][0]},{rule[k][1]}" for k in ("h", "s", "v")]
    else:
        args.append("--auto=1")
    ok, log = godot(cfg, "fake_tint.gd", *args)
    try:
        if ok and tmp.is_file():
            atomic_copy(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return ok, log
