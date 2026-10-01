# 화면 이미지 프롬프트

Codex 이미지 생성에 쓴 프롬프트입니다. 메인 화면을 먼저 만들고, 나머지는 **메인 화면 이미지를 첨부한 뒤** 보내야 캐릭터와 그림체가 유지됩니다.
설명은 영어(이미지 모델이 더 잘 따름), 화면 속 글자는 한국어입니다.

| 화면 | 상태 | 결과 |
|---|---|---|
| 메인 (본사) | 생성됨 | [01-main-office.webp](01-main-office.webp) |
| 퀘스트 보드 | 생성됨 | [02-quest-board.webp](02-quest-board.webp) |
| 결재 창 | 생성됨 | [03-approval.webp](03-approval.webp) |
| 직원 상태창 | 생성됨 | [04-employee-sheet.webp](04-employee-sheet.webp) |
| 회의실 | 생성됨 | [05-meeting-room.webp](05-meeting-room.webp) |
| 보고서 | 생성됨 | [06-report.webp](06-report.webp) |
| 업무 일지 | 생성됨 | [07-work-diary.webp](07-work-diary.webp) |
| 결재함 | 생성됨 | [08-inbox.webp](08-inbox.webp) |
| 긴급 정지 | 생성됨 | [09-emergency-stop.webp](09-emergency-stop.webp) |
| 완성작 진열장 | 생성됨 | [10-trophy-shelf.webp](10-trophy-shelf.webp) |

---

## 메인 화면 (본사)

```text
아래 영어 프롬프트대로 이미지를 1장 생성해 줘. 가로 1536x1024.

[STYLE]
A polished in-game screenshot (UI concept mockup) of a cozy desktop management-simulation game called "AI 스튜디오". AI agents work as employees of a tiny indie game studio, and the player is the CEO.
Crisp 16-bit pixel art, 3/4 top-down view, clean pixel edges, no blur, no photorealism. Warm, friendly mood: honey-wood floor, cream walls, soft daylight from windows. Inspired by classic studio-management games, but fully original: no existing characters, logos or brands.
Limited palette: cream and warm wood for the world; UI panels in deep plum (#2E2B3D) with cream text; accent lavender (#7F77DD); status colors teal (done), amber (working), coral (needs attention).
It must feel like a game, not a business dashboard: information is shown through characters, speech bubbles, icons and objects in the room. No tables, no dense lists, no charts. Lots of breathing room. Only a few short Korean labels in a clean, legible pixel font.

[LAYOUT]
1. Top HUD strip (thin, full width, deep plum):
   - left: small lavender square logo + "AI 스튜디오", then the game clock "3일차 · 오전 10:20"
   - center: yellow lightning icon + orange energy bar about 80% full, label "에너지 32/40"
   - right: envelope icon with a red badge "2" (approval inbox), a bell icon, and a round red emergency button with a white square icon
2. Main scene (most of the screen): a cutaway office room.
   - Back wall: two windows with blue sky, a wall clock, and a large cork board titled "퀘스트 보드" with four colorful sticky-note quest cards.
   - Center: four desks in a 2x2 cluster. Each has one pixel character working at a computer, a small speech bubble above, and a name plate below:
     • purple shirt, dark ponytail — bubble "기획안 쓰는 중…" — plate "기획 · 하나"
     • blue hoodie, messy brown hair, glowing code on the monitor — bubble "코딩 중" with a small progress bar at 70% — plate "개발 · 솔"
     • coral sweater, short black hair, holding a red ink stamp over a paper — bubble with a green check "합격!" — plate "리뷰 · 클로"
     • amber cardigan, round glasses, a stack of books — bubble "자료 찾는 중…" — plate "리서치 · 루나"
   - Right side: a meeting corner with a round table on a lavender rug, small sign "회의실". Below it, a wooden trophy shelf "완성작" holding one golden trophy, two game cartridges, and several empty dotted slots for future games.
   - Life details: a potted plant, a coffee machine, a small cat sleeping on a cushion.
3. Notification bubble just below the HUD on the right: tiny portrait of the developer + "솔: 결재 부탁드려요!"
4. Bottom: a floating rounded command bar in cream with the placeholder "무엇을 시킬까요?" and a round lavender send button. To its left, three small round icon-only buttons: scroll (quests), people (employees), book (records).

[RULES]
- Use every Korean string exactly as written above. No other text, no lorem ipsum.
- Keep the HUD layer, the room scene, and the bottom command bar clearly separated, so the design could be rebuilt as a web app with pixel sprites.
- No watermark, no signature, no real brand logos, no blurry or garbled letters.
```

## 결재 창

```text
첨부한 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Approval popup: the office is dimmed in the background. In the center, a large parchment document card:
- title "결재 · 게임 규칙 만들기"
- three checklist rows with icons: "품질 검사 8/8 합격" (green check), "리뷰: 클로 승인" (tiny portrait of 클로), "바뀐 파일 1개"
- bottom: a big round red stamp button "승인" and a smaller outlined button "수정 요청"
- the developer 솔 peeks nervously from the right edge of the card
Korean text exactly as written, nothing else.
```

## 퀘스트 보드

```text
첨부한 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Close-up of the cork board "퀘스트 보드" filling the screen, with four columns and pixel headers "대기", "진행 중", "결재 대기", "완료".
Each quest is a sticky note with a short Korean title, a tiny portrait of the assigned employee, and 1–3 difficulty stars:
"플레이어 이동" (솔, 진행 중), "적 순찰" (솔, 대기), "HUD 만들기" (하나, 대기), "출시 절차 조사" (루나, 결재 대기), "게임 규칙 만들기" (솔, 완료, with a gold stamp).
A pinned paper at the top: "이번 주 목표: 코어 쿠리어 완성".
The top HUD strip and the bottom command bar from the main screen stay visible.
```

## 직원 상태창

```text
첨부한 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

RPG-style character sheet popup for the developer 솔 over the dimmed office:
- left: large pixel portrait of 솔 (blue hoodie, messy brown hair)
- right: "개발 담당 · 솔", "Lv.3", an XP bar, and three stat bars "속도", "정확도", "꼼꼼함"
- skill badges "Godot" and "GDScript"
- small line "오늘 완료 2 · 수정 1"
- a smiling mood icon and a coffee cup
Korean text exactly as written.
```

---

아래 프롬프트는 모두 같은 머리말로 시작합니다 (각 블록에 포함).

## 회의실 (기획 회의)

```text
첨부한 메인 화면 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Keep the top HUD strip and the bottom command bar exactly as in the main screen.
Same characters: 하나 (purple shirt, dark ponytail), 솔 (blue hoodie, messy brown hair), 클로 (coral sweater, short black bob), 루나 (amber cardigan, long brown hair, round glasses).
Use every Korean string exactly as written below; no other text.

Planning meeting inside the glass-walled meeting room: round wooden table, purple chairs, lavender rug, a whiteboard on the wall.
- 하나 stands at the whiteboard, presenting. The whiteboard shows "지시: 플레이 가능한 첫 화면" and a doodle of three boxes joined by arrows.
- 솔, 클로 and 루나 sit around the table listening; 솔 raises one hand.
- The seat nearest the viewer is an empty chair with gold trim and a small plate "CEO" (the player's seat).
- Three large proposal cards lie on the table like cards in a card game. Each card has a short title, a tiny portrait of the assignee, difficulty stars and a round checkbox:
  "플레이어와 방" (솔, 2 stars, checked), "적 순찰과 피격" (솔, 2 stars, checked), "HUD와 결과 화면" (하나, 1 star, unchecked)
- Speech bubble from 하나: "세 단계로 나눴어요. 골라 주세요!"
- Just above the command bar: a lavender button "퀘스트로 붙이기" and an outlined button "다시 기획".
```

## 보고서 (CEO가 받는 보고서)

```text
첨부한 메인 화면 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Keep the top HUD strip and the bottom command bar exactly as in the main screen.
Same characters: 하나 (purple shirt, dark ponytail), 솔 (blue hoodie, messy brown hair), 클로 (coral sweater, short black bob), 루나 (amber cardigan, long brown hair, round glasses).
Use every Korean string exactly as written below; no other text.

Report reading screen. The office is dimmed in the background; in the center, a neat report sheet on a wooden clipboard:
- top: small portrait of 루나 and the label "리서치 보고서 · 루나"
- title "Steam AI 콘텐츠 공개 규정"
- highlighted box: "한 줄 결론: AI로 만든 그림·소리는 출시 전에 신고해요"
- three short numbered lines: "1. 미리 만든 AI 콘텐츠는 설문에 적기", "2. 실시간 생성은 안전장치 설명", "3. 에셋 장부에 도구·날짜 기록"
- two chips: teal "출처 3개" with small link icons, amber "확인 필요 1"
- bottom: a lavender button "확인 완료", an outlined button "질문하기", and a small archive-box icon button
- 루나 peeks in from the left edge, holding a sticky note "궁금한 점은 물어봐 주세요!"
```

## 업무 일지

```text
첨부한 메인 화면 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Keep the top HUD strip and the bottom command bar exactly as in the main screen.
Same characters: 하나 (purple shirt, dark ponytail), 솔 (blue hoodie, messy brown hair), 클로 (coral sweater, short black bob), 루나 (amber cardigan, long brown hair, round glasses).
Use every Korean string exactly as written below; no other text.

Work diary screen. An open leather-bound journal fills most of the screen, lying on a wooden desk with a coffee cup and a pencil. Colored tab dividers stick out on the right edge: "1일차", "2일차", "3일차" (the last one active).
- Left page titled "3일차 업무 일지": a short timeline, each row with a time, a tiny portrait and one line:
  "09:10 솔 · 게임 규칙 완성", "10:05 루나 · 보고서 제출", "10:20 클로 · 리뷰 2건", "11:40 하나 · 기획 회의"
- Right page titled "오늘의 요약", like a hand-made scrapbook: three stamp-style stats with icons "완료 3", "결재 2", "에너지 28", a gold sticker "첫 시도 합격 3/4", a doodle of the sleeping cat, and a handwritten line "내일: 적 순찰 만들기"
- Page-turn arrows in the bottom corners of the book.
```

## 결재함 (편지함)

```text
첨부한 메인 화면 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Keep the top HUD strip and the bottom command bar exactly as in the main screen.
Same characters: 하나 (purple shirt, dark ponytail), 솔 (blue hoodie, messy brown hair), 클로 (coral sweater, short black bob), 루나 (amber cardigan, long brown hair, round glasses).
Use every Korean string exactly as written below; no other text.

Approval inbox. The office is dimmed; in the center, an open wooden letter tray panel titled "결재함 3". The envelope badge in the HUD also shows "3".
Three letters as horizontal rows, each with a colored wax seal, a tiny sender portrait, a short title and a tag chip:
  "게임 규칙 만들기" from 솔, teal chip "품질 합격"
  "Steam AI 규정 보고서" from 루나, lavender chip "보고서"
  "기획안: 적과 HUD" from 하나, amber chip "기획 회의"
Each row ends with a small outlined button "열기". The top letter glows softly as the newest.
```

## 긴급 정지

```text
첨부한 메인 화면 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Keep the top HUD strip and the bottom command bar exactly as in the main screen.
Same characters: 하나 (purple shirt, dark ponytail), 솔 (blue hoodie, messy brown hair), 클로 (coral sweater, short black bob), 루나 (amber cardigan, long brown hair, round glasses).
Use every Korean string exactly as written below; no other text.

The same main office in emergency-stop state: ceiling lights off, a red alarm lamp spinning on the wall, all four employees frozen mid-action with red "!" icons above their heads, monitors showing a pause symbol.
- Center banner "긴급 정지 · 모든 작업 멈춤" with a large green button "재개".
- The red button in the HUD looks pressed in.
```

## 완성작 진열장

```text
첨부한 메인 화면 이미지와 같은 게임, 같은 픽셀 아트 스타일, 같은 캐릭터로 이미지를 1장 생성해 줘. 가로 1536x1024.

Keep the top HUD strip and the bottom command bar exactly as in the main screen.
Same characters: 하나 (purple shirt, dark ponytail), 솔 (blue hoodie, messy brown hair), 클로 (coral sweater, short black bob), 루나 (amber cardigan, long brown hair, round glasses).
Use every Korean string exactly as written below; no other text.

Collection screen. Close-up of the wooden trophy shelf titled "완성작", filling the screen like a gallery.
- Top shelf: a game cartridge "코어 쿠리어" with a pixel thumbnail (a tiny character collecting glowing cores in a room), a gold trophy next to it, and a button "플레이".
- Second shelf: a framed document "Steam AI 규정 보고서" with a tiny portrait of 루나 and a small button "열기".
- The remaining slots are dashed outlines with a "+" and the label "다음 작품?".
- A small brass plaque at the bottom: "완성 2 · 이번 달 목표 5".
```
