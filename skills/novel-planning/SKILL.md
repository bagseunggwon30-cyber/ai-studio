---
name: novel-planning
description: 소설 프로젝트에서 CEO 지시를 작업 카드로 나눌 때 쓴다. 설정집이 비어 있으면 설정 문서부터, 있으면 장 하나씩 집필 카드로 나누고 순서·분량·수용 기준을 정한다.
metadata:
  title: 소설 기획과 장 나누기
  learned_by: producer
  projects:
  kinds: plan, novel
  source: ceo
  how: ceo
  created: 2026-10-06
  version: 1
---

### 먼저 확인한다
1. `bible/`의 premise·characters·world·outline·style이 채워져 있는지 본다. 비어 있으면 **설정 문서 작성 카드를 맨 앞에** 둔다 (한 카드에 문서 1~2개).
2. `chapters/`의 마지막 번호를 확인한다. 새 장은 그 다음 번호부터.
3. `notes/continuity.md`에 아직 회수하지 않은 복선이 있는지 본다.

### 카드로 나누는 법
- 장 하나가 카드 하나다. 제목은 `제N장 쓰기`. 한 장에 큰 사건을 둘 이상 넣지 않는다.
- 목표 칸에 쓸 것: 이 장의 사건(누가·어디서·무슨 일이·어떤 변화), 꼭 지킬 설정, 던지거나 회수할 복선, 분량(없으면 공백 포함 3,000~5,000자).
- allowed_paths는 `chapters/NNN.md`와 `notes/continuity.md` (설정을 새로 만들면 해당 `bible/` 파일도).
- 수용 기준은 확인할 수 있게: 파일이 있다 · 첫 줄이 `# 제N장 …` · 분량이 범위 안 · bible과 모순 없다 · 연속성 장부에 이번 장 사실이 더해졌다 · 마지막이 다음 장으로 이어진다.
- 장 사이는 depends_on으로 순서를 건다. 앞 장이 끝나야 다음 장 카드가 풀린다.

### 흔한 실수
- 한 카드에 여러 장을 몰아 넣어 뒤로 갈수록 대충 쓰게 만드는 것.
- 줄거리(outline)에 없는 큰 전개를 카드가 새로 만드는 것. 바꿔야 하면 outline 수정 카드를 먼저 둔다.
- 자료가 필요한 장(시대·직업·장소)인데 자료 조사 카드(research)를 앞에 두지 않는 것.
