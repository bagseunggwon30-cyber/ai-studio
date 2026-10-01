# 에셋 프롬프트

목업(`01`~`10`)은 한 장짜리 그림이라 그대로는 쓸 수 없다. 실제 화면은 배경, 캐릭터, 소품, 창 틀을 따로 그려서 겹쳐 만든다 ([SPEC.md](SPEC.md) 2장, 8장).

- 모든 에셋에 **글자를 넣지 않는다.** 글자는 구현할 때 HTML로 넣는다.
- 스프라이트와 소품은 자홍색(#FF00FF) 단색 배경으로 만든다. 나중에 스크립트로 배경을 투명하게 뺀다.
- 결과는 `assets-raw/`에 표의 파일 이름으로 저장한다.

| 번호 | 파일 | 첨부할 기준 이미지 |
|---|---|---|
| A1 | `bg-office.png` | `01-main-office.webp` |
| A2 | `bg-meeting.png` | `05-meeting-room.webp` |
| B1 | `char-hana.png`, `char-sol.png`, `char-clo.png`, `char-luna.png` | `01-main-office.webp` |
| B2 | `portraits.png` | `01-main-office.webp`, `04-employee-sheet.webp` |
| C1 | `props.png` | `01-main-office.webp` |
| C2 | `icons.png` | `01-main-office.webp` |
| C3 | `panels.png` | `03-approval.webp`, `02-quest-board.webp` |

진행 상황 (2026-09-29): 층 배경(본사 1층·2층)과 뒤에서 본 앉은 자세(기본·여름 옷)를 새로 그렸다 (아래 '층 배경', '앉은 자세'). 옛 본사 배경 `bg-office.png`(A1)는 이제 쓰지 않는다.

진행 상황 (2026-09-28): A1, A2, B1 4장, B2, B3 걷기 4장, 의상 세트 "여름 옷"(시트·걷기·얼굴 9장) 완료 (`assets-raw/`). C1, C2, C3도 완료 (2026-09-28): `tools/sprites/make_ui_sheets.ps1`로 뽑고 `make_ui_assets.gd`로 잘라 `ui/assets/ui/`에 39장. 실제로 쓴 프롬프트는 `make_ui_sheets.ps1` 안에 있다 (아래 글보다 자세함).

## 동작별 띠로 자르기

캐릭터 시트는 게임에서 바로 쓰지 않고, 동작마다 가로 한 줄 띠(`<캐릭터>.<동작>.strip.png` + `.strip.json`)로 잘라 `ui/assets/sprites/`에 둔다.

```powershell
S:\software\Godot_4.7.2\Godot_v4.7.2-stable_win64_console.exe --headless --path tools/sprites --script res://make_strips.gd -- "--root=S:/AI/ai studio"
```

- 설정: `tools/sprites/sheets.json` (시트마다 칸 배치, 동작별 칸 번호, 방향, 기준 키, 정렬 방식)
- 배경색(네 귀퉁이 평균)을 투명으로 빼고, 가장자리의 자홍기를 걷어 낸다.
- 반복 동작은 이음새 값을 json에 적는다. (마지막→첫 프레임 차이) ÷ (나머지 연속 프레임 차이 평균)이고, 1.0에 가까울수록 자연스럽다.
- 걷기는 `matchHeightOf: step`으로 같은 캐릭터의 서 있는 동작 키에 맞추고, `align: head`로 프레임마다 머리 가운데와 발바닥을 맞춘다.
- 결과를 눈으로 보려면 프로젝트 폴더를 로컬 서버로 열고 `tools/sprites/preview.html`을 연다.

얼굴 초상화(B2)는 따로 자른다. 그림 모델이 칸을 똑같이 나누지 않아(어깨가 옆 칸으로 넘어감) 등분하지 않고 빈 줄·빈 열을 찾아 얼굴마다 잘라 낸 뒤, 머리 가운데와 아래 끝을 맞춰 256px 칸 아틀라스(`ui/assets/portraits.png` + `.json`)로 만든다. 설정은 `sheets.json`의 `portraits`.

```powershell
S:\software\Godot_4.7.2\Godot_v4.7.2-stable_win64_console.exe --headless --path tools/sprites --script res://make_portraits.gd -- "--root=S:/AI/ai studio"
```

배경색 빼기는 두 도구가 `tools/sprites/keying.gd`를 같이 쓴다.

## 의상 세트와 색 바꾸기 (직원 꾸미기)

새 의상 세트를 만드는 순서:

1. `tools/sprites/look-sets.json`의 `sets`에 세트 이름·라벨과 직원별 옷 설명을 적는다. 옷 색은 직원의 기본 색을 유지한다 (색 바꾸기 표시가 그대로 먹게).
2. Codex로 그림을 뽑는다 (본인 ChatGPT 로그인, API 키 없음, 4장씩 동시에):
   ```powershell
   pwsh tools/sprites/make_look_set.ps1 -Set summer -Step sheets     # 동작 시트 4장 (기존 시트를 EDIT 모드로, 옷만 바꿈)
   pwsh tools/sprites/make_look_set.ps1 -Set summer -Step walks      # 걷기 4장
   pwsh tools/sprites/make_look_set.ps1 -Set summer -Step portraits  # 얼굴 12장
   ```
   결과는 `assets-raw/looks/<세트>/`. 눈으로 확인하고 이상한 장은 `-Only sol -Force`로 다시 뽑는다.
3. `tools/sprites/sheets.json`의 `sets`에 세트 이름을 넣고 세 도구를 차례로 돌린다:
   ```powershell
   $g = "S:\software\Godot_4.7.2\Godot_v4.7.2-stable_win64_console.exe"
   & $g --headless --path tools/sprites --script res://make_strips.gd -- "--root=S:/AI/ai studio"
   & $g --headless --path tools/sprites --script res://make_portraits.gd -- "--root=S:/AI/ai studio"
   & $g --headless --path tools/sprites --script res://make_masks.gd -- "--root=S:/AI/ai studio"
   ```
   세트의 띠는 `<직원>@<세트>.<동작>`으로 생기고, 기본 시트와 같은 키가 되도록 크기를 맞춘다. 화면의 꾸미기 창에 자동으로 나온다.

색 바꾸기 표시(`make_masks.gd`): `sheets.json`의 `parts`에 직원마다 머리·옷의 색상·채도·밝기·높이 범위를 적는다. 모든 띠와 얼굴 아틀라스에 `.mask.png`(빨강 = 머리, 초록 = 옷)와 부분 평균 색(`ui/assets/sprites/parts.json`)을 만든다. 범위를 정할 때는 `color_stats.gd`로 많이 쓰인 색을 본다:
```powershell
& $g --headless --path tools/sprites --script res://color_stats.gd -- "--root=S:/AI/ai studio" --who=clo@summer
& $g --headless --path tools/sprites --script res://color_stats.gd -- "--root=S:/AI/ai studio" --file=ui/assets/portraits.png --col=2
```
얼굴 그림은 몸 그림과 색이 조금 달라 `face`로 규칙을 덮어쓸 수 있다 (클로의 머리). 작은 조각(입, 반짝이)은 `minArea`로 버린다.

여름 옷 세트(2026-09-28)는 한 번에 잘 나왔다: 12장 모두 자세·위치가 원본과 같고 옷만 바뀌었다.

## 층 배경과 의자 앞 그림 (2026-09-29, CEO 결정: 본사 새로 그리기 + 층 늘리기)

```powershell
pwsh tools/sprites/make_floors.ps1                 # assets-raw/bg-office-f1.png(본사), bg-office-f2.png(2층) — 프롬프트는 스크립트 안
pwsh tools/sprites/make_floors.ps1 -Only f2 -Tag b # 후보를 하나 더 (bg-office-f2-b.png)
```

- 고른 그림을 `ui/assets/bg/office-f1.png`·`office-f2.png`로 복사하고, 격자를 그린 확대 그림으로 자리를 재어 `ui/assets/bg/floors.json`에 적는다 (책상마다 앉는 자리·서는 자리·모니터 화면·이름표·의자 상자, 휴식 자리, 앞 그림 묶음).
- 의자는 등받이가 보이게(뒤에서 본 모습) 그리게 했다. 앉은 직원 위에 의자만 한 겹 더 그려 의자에 앉은 모습을 만든다:
  ```powershell
  & $g --headless --path tools/sprites --script res://make_fronts.gd -- "--root=S:/AI/ai studio"   # <배경>.front-<i>.png
  ```
  의자 상자 윗변은 등받이 윗선에 맞춘다 (위의 키보드·책상 선이 들어가면 몸 위에 줄이 그어진다). F2를 누르면 앞 그림이 분홍으로 보인다.

## 앉은 자세 다시 그리기 (2026-09-29, CEO 요청 "의자에 앉아서 일하는 도트 개선")

```powershell
pwsh tools/sprites/make_seated.ps1               # 기본 옷 4명 → assets-raw/seated/base/char-<직원>.png
pwsh tools/sprites/make_seated.ps1 -Set summer   # 의상 세트
pwsh tools/sprites/make_seated.ps1 -Only hana -Force
& $g --headless --path tools/sprites --script res://compose_cells.gd -- "--root=S:/AI/ai studio" --from=assets-raw/seated/base/char-hana.png --to=assets-raw/char-hana.png --cells=0,1,5
```

- 시트를 EDIT 모드로 넣고 1·2·6번 칸(타자 A·B, 놀람)만 '뒤에서 조금 옆으로 본 앉은 모습'으로 바꾸게 한다. 다른 칸까지 바뀌거나 얼굴이 달라지면(하나 첫 시도: 눈 색이 바뀜) `-Force`로 다시 뽑는다.
- `compose_cells.gd`는 그 칸만 원래 시트로 옮긴다 (원본은 처음 한 번 `assets-raw/old/`에 남긴다). 그다음 make_strips → make_masks.

## 그리는 AI: Codex 또는 Grok (2026-09-29, CEO 요청 E)

- 꾸미기 공방·새 직원 만들기에서 그리는 AI를 고른다 (기본 Codex). 프롬프트는 같다.
- Grok CLI(`grok --prompt-file … --output-format json --tools image_gen,image_edit,read_file`)는 그림을 `~/.grok/sessions/<작업 폴더>/<sessionId>/images/1.jpg`에 **정사각형 1024x1024 JPG**로 둔다. 감독 프로그램이 세션 번호로 찾아 `tools/sprites/to_png.gd`로 PNG로 바꾼다. 배경 자홍색은 잘 지킨다 (시험 그림: 모서리 248,14,197).
- 참고 그림은 작업 폴더에 `ref-1.png`…로 복사해 이름으로 알려 준다. 진짜 Grok으로 EDIT(옷 세트 1벌, 그림 3장)도 한 번 확인했다 (2026-09-29, 1248×832 JPG → PNG, 자르기 성공). 사용량이 적어서 쓸 때마다 CEO에게 먼저 묻는다.

## B3. 걷기 4프레임 (캐릭터마다, 각자의 `char-<이름>.png`를 첨부)

```text
The attached image is the sprite sheet of our game character __WHO__. Use your image generation tool in EDIT mode with the attached image as the input reference — keep the exact same character design, pixel-art style, colors, proportions and size. Output one new image, landscape 1536x1024.

Draw a 4-frame walk cycle of this one character walking to the RIGHT, seen from the side like the walking pose in the attached sheet. Put the 4 frames in ONE horizontal row of 4 equal cells across the whole image, on a flat, solid, pure magenta background (#FF00FF). No shadows, no ground line, no grid lines, no text, no motion marks or effects.
The character walks in place: same size, same head height and the same horizontal position inside every cell. Only the legs, arms and a slight body bob change.
1. contact: left foot forward touching the ground, right arm forward
2. passing: right leg passing under the body, body slightly higher
3. contact: right foot forward touching the ground, left arm forward
4. passing: left leg passing under the body, body slightly higher
Frame 4 must lead naturally back into frame 1 so the cycle loops.
```

## Codex CLI로 뽑는 법 (Claude가 쓰는 방식)

```powershell
Get-Content prompt.txt -Raw | codex exec -i "docs\design\01-main-office.webp" --json --ephemeral --ignore-user-config --skip-git-repo-check -s read-only -C "S:\AI\ai studio" -m gpt-6-luna -c 'model_reasoning_effort="low"'
```

- 프롬프트 첫머리에 **"Use your image generation tool in EDIT mode with the attached image as the input reference"**를 꼭 넣는다. 그냥 "바탕으로 다시 그려"라고 하면 첨부 이미지를 무시하고 새 그림(배치·그림체가 다른 것)을 그린다.
- 결과 파일은 `C:\Users\bark\.codex\generated_images\<thread_id>\exec-*.png`에 생긴다 (`thread_id`는 JSON 출력의 `thread.started`). Codex는 이 하위 폴더를 잘 못 찾으므로, 파일 복사는 Codex에 맡기지 않고 직접 한다.
- 프로젝트 루트는 git 저장소가 아니라서 `--skip-git-repo-check`가 필요하다.
- 한 장에 약 1분, 구독 사용량을 쓴다.
- Codex가 "결과 이미지가 반환되지 않았다"고 답해도 파일은 저장돼 있을 수 있다 (A2, B2 모두 그랬다). 항상 폴더를 직접 확인한다.
- 여러 장을 참고시킬 때는 `-i`를 여러 번 쓴다 (B2는 `07-work-diary.webp`, `04-employee-sheet.webp`).

---

## A1. 빈 본사 배경

```text
첨부한 메인 화면 이미지를 바탕으로 이미지를 1장 생성해 줘. 가로 1536x1024.

Redraw the exact same office room from the same camera angle and framing, as an empty background plate for a game.
- Remove all people, speech bubbles, name plates, the notification bubble, the top HUD strip and the bottom command bar. Extend the room naturally into those areas so the whole 1536x1024 frame is scenery.
- Keep every piece of furniture in the same place: four desks with office chairs, monitors turned off (dark screens), the cork quest board with no notes, the meeting room, the trophy shelf with every slot empty, the lounge with its couch and cushions (no cat), coffee machine, plants, windows, wall clock, and the skill board with a blank sheet.
- No text anywhere: every sign, plate and paper is blank.
- Same crisp 16-bit pixel art, same palette, same daylight.
```

## A2. 빈 회의실 배경 (실제로 쓴 프롬프트, 첨부: `05-meeting-room.webp`)

```text
Use your image generation tool in EDIT mode with the attached image as the input reference — keep the exact same meeting room, camera angle, framing, furniture positions, palette, lighting and crisp 16-bit pixel-art style. Output one new image, landscape 1536x1024.

Redraw this meeting room as an empty background plate for a game:
- Remove all four people, the speech bubble, the three cards on the table and the two buttons at the bottom.
- Remove the top HUD strip and the bottom command bar and the three round buttons, and extend the room naturally into those areas so the whole 1536x1024 frame is scenery.
- The whiteboard is completely blank and clean (no drawings, no text).
- Keep the round wooden table (its top empty except the small plant in the middle, a closed laptop and the coffee mugs), the purple chairs around it, the gold-trimmed CEO chair in the front with a blank plate, the lavender rug, the bookshelf, the plants, the glass walls and windows.
- The poster on the wall is blank. The sign on the left glass wall is blank.
- No text anywhere, no people, no speech bubbles, no UI.
```

## B1. 직원 스프라이트 시트 (4명, 한 명씩)

**하나**
```text
첨부한 메인 화면 이미지와 같은 픽셀 아트 스타일로, 직원 "하나" 한 명의 스프라이트 시트를 1장 생성해 줘. 가로 1536x1024.

Character: 하나 (purple shirt, dark ponytail), exactly as in the attached image, same size relative to the room and the same 3/4 top-down angle. When seated she faces right, toward her monitor.
Layout: a 4x2 grid of equal cells on a flat solid magenta background (#FF00FF). Nothing else on the background: no shadows, no floor, no grid lines, no text. Clear gaps between cells.
Cells (draw only the character, no chair, desk or couch — those are in the background):
1. seated, typing, frame A
2. seated, typing, frame B (hands in a different position, for a 2-frame loop)
3. sitting relaxed holding a coffee mug (resting in the lounge)
4. standing, presenting with a pointer in one hand and a clipboard in the other
5. standing, both arms up, cheering
6. seated, frozen with a surprised face and raised hands
7. standing, scratching her head, worried
8. walking, mid-step
Keep proportions and colors identical in every cell.
```

**솔**
```text
첨부한 메인 화면 이미지와 같은 픽셀 아트 스타일로, 직원 "솔" 한 명의 스프라이트 시트를 1장 생성해 줘. 가로 1536x1024.

Character: 솔 (blue hoodie, messy brown hair), exactly as in the attached image, same size relative to the room and the same 3/4 top-down angle. When seated he faces left, toward his monitor.
Layout: a 4x2 grid of equal cells on a flat solid magenta background (#FF00FF). Nothing else on the background: no shadows, no floor, no grid lines, no text. Clear gaps between cells.
Cells (draw only the character, no chair, desk or couch — those are in the background):
1. seated, typing, frame A
2. seated, typing, frame B (hands in a different position, for a 2-frame loop)
3. sitting relaxed holding a coffee mug (resting in the lounge)
4. standing, waving one hand
5. standing, both arms up, cheering
6. seated, frozen with a surprised face and raised hands
7. standing, scratching his head, worried
8. walking, mid-step
Keep proportions and colors identical in every cell.
```

**클로**
```text
첨부한 메인 화면 이미지와 같은 픽셀 아트 스타일로, 직원 "클로" 한 명의 스프라이트 시트를 1장 생성해 줘. 가로 1536x1024.

Character: 클로 (coral sweater, short black bob), exactly as in the attached image, same size relative to the room and the same 3/4 top-down angle. When seated she faces right, toward her monitor.
Layout: a 4x2 grid of equal cells on a flat solid magenta background (#FF00FF). Nothing else on the background: no shadows, no floor, no grid lines, no text. Clear gaps between cells.
Cells (draw only the character, no chair, desk or couch — those are in the background):
1. seated, reading a document on screen, frame A
2. seated, reading, frame B (small head movement, for a 2-frame loop)
3. sitting relaxed holding a coffee mug (resting in the lounge)
4. standing, waving one hand
5. seated, pressing a red ink stamp onto a paper, happy
6. seated, frozen with a surprised face and raised hands
7. standing, scratching her head, worried
8. walking, mid-step
Keep proportions and colors identical in every cell.
```

**루나**
```text
첨부한 메인 화면 이미지와 같은 픽셀 아트 스타일로, 직원 "루나" 한 명의 스프라이트 시트를 1장 생성해 줘. 가로 1536x1024.

Character: 루나 (amber cardigan, long brown hair, round glasses), exactly as in the attached image, same size relative to the room and the same 3/4 top-down angle. When seated she faces left, toward her monitor.
Layout: a 4x2 grid of equal cells on a flat solid magenta background (#FF00FF). Nothing else on the background: no shadows, no floor, no grid lines, no text. Clear gaps between cells.
Cells (draw only the character, no chair, desk or couch — those are in the background):
1. seated, typing, frame A
2. seated, typing, frame B (hands in a different position, for a 2-frame loop)
3. sitting relaxed holding a coffee mug (resting in the lounge)
4. standing, waving one hand while holding a report
5. standing, both arms up, cheering
6. seated, frozen with a surprised face and raised hands
7. standing, scratching her head, worried
8. walking, mid-step
Keep proportions and colors identical in every cell.
```

## B2. 얼굴 초상화 (실제로 쓴 프롬프트, 첨부: `07-work-diary.webp`, `04-employee-sheet.webp`)

```text
Use your image generation tool in EDIT mode with the attached images as the input reference — keep the exact same four characters, face designs, hair, clothes, colors and crisp 16-bit pixel-art style as in the attached images. Output one new image, landscape 1536x1024.

Draw a sheet of bust portraits (head and shoulders, facing the viewer) on a flat, solid, pure magenta background (#FF00FF).
Layout: a grid of 4 columns x 3 rows of equal cells. Clear gaps between cells. No shadows, no frames, no borders, no grid lines, no text, no speech bubbles, no effects.
Columns (one character per column, left to right):
1. 하나 — purple hoodie, dark hair in a ponytail
2. 솔 — blue hoodie, messy brown hair
3. 클로 — coral sweater, short black bob
4. 루나 — amber cardigan, long brown hair, round glasses
Rows (one expression per row, top to bottom):
1. normal, calm small smile
2. happy, big smile with eyes closed in joy
3. worried, troubled eyebrows, small sweat drop
Every portrait has the same size and framing: the head is centered in its cell, the top of the hair is a little below the top of the cell, and the shoulders reach the bottom of the cell. Keep proportions identical across all 12 portraits.
```

## C1. 소품

```text
첨부한 메인 화면 이미지와 같은 픽셀 아트 스타일로 소품 시트를 1장 생성해 줘. 가로 1536x1024.

A 4x4 grid of small game props on a flat solid magenta background (#FF00FF), each centered in its cell, no text, no shadows on the background:
1. monitor screen showing code (colored lines)
2. monitor screen showing a document
3. monitor screen showing a small chart
4. monitor screen with a pause symbol
5. gold trophy
6. purple game cartridge with an empty label area
7. small framed document (blank paper)
8. calico cat sleeping on a purple cushion
9. red wax seal
10. purple wax seal
11. gold wax seal
12. red alarm lamp, lit
13. yellow sticky note with a red pushpin (blank)
14. green sticky note with a red pushpin (blank)
15. pink sticky note with a red pushpin (blank)
16. lavender sticky note with a red pushpin (blank)
```

## C2. 아이콘

```text
첨부한 메인 화면 이미지와 같은 픽셀 아트 스타일로 아이콘 시트를 1장 생성해 줘. 가로 1536x1024.

A 4x4 grid of pixel UI icons on a flat solid magenta background (#FF00FF), each centered in its cell, no text. Style matches the HUD and bottom buttons of the attached image (dark plum #2E2B3D outlines, cream and lavender #7F77DD fills):
1. studio logo (lavender rounded square with a small molecule mark)
2. yellow lightning bolt
3. envelope
4. bell
5. round red stop button with a white square
6. rolled scroll (quests)
7. group of people (employees)
8. open book (work diary)
9. send arrow inside a lavender circle
10. green check circle
11. amber warning circle with "!"
12. chain link
13. document page
14. shield with a check mark
15. folder
16. archive box
```

## C3. 창 틀

```text
첨부한 이미지들과 같은 픽셀 아트 스타일로 UI 창 틀 시트를 1장 생성해 줘. 가로 1536x1024.

Seven separate UI panel objects on a flat solid magenta background (#FF00FF), arranged in a loose grid with clear gaps. Every panel is completely blank: no text, no icons, no writing.
1. parchment document card with a paper clip at the top left
2. cork board in a wooden frame with four empty column header strips (gray, blue, yellow, green)
3. wooden clipboard holding a blank sheet of paper
4. open leather journal with two blank pages
5. wooden letter tray panel, empty
6. wooden trophy shelf with empty compartments
7. small white speech bubble with a tail
```
