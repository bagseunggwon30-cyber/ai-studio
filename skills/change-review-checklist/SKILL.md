---
name: change-review-checklist
description: "개발 작업의 변경(diff), 리서치 보고서, 직원이 만든 MCP 도구 코드를 리뷰해 approve나 changes_requested를 정할 때 쓴다."
metadata:
  title: 변경 리뷰 점검표
  learned_by: reviewer
  projects: 
  kinds: review
  source: ceo
  how: ceo
  created: 2026-09-29
  version: 1
---

### 순서
1. 작업 카드의 목표와 수용 기준을 먼저 읽는다. 기준마다 "어느 파일의 어느 줄이 이것을 채우나"를 diff에서 찾는다.
2. 자동 검증 결과를 본다. 통과했어도 테스트를 속이는지 확인한다 (테스트 입력만 특별 처리, 값 박아 넣기, 검사 끄기). 자동 검사가 없으면(`none`) 통과로 치지 않고 코드와 파일로 직접 확인한다.
3. 계약 문서(`docs/INTERFACES.md` 등)의 이름·인자·상수와 diff를 대조한다.
4. diff가 잘렸다고 나오면 빠진 파일을 직접 열어 읽는다. 지금 폴더는 후보 커밋의 스냅샷이다.
5. 바뀐 파일이 작업 카드의 허용 경로 안인지, 관련 없는 파일을 건드리지 않았는지 본다.

### blocking과 minor 가르기
- blocking: 수용 기준을 못 채움, 계약 위반, 테스트 속이기, 크래시나 무한 반복 가능성, 비밀키·바깥 호출·출처 모를 에셋, 허용 경로 밖 변경.
- minor: 이름·중복·주석·작은 구조 개선, 확신이 없는 의심, 계약에 없는 방어 코드.
- 취향 차이로 반려하지 않는다. 확신이 없으면 minor로 남긴다.

### findings와 summary 쓰는 법
- file은 `경로:줄번호`. issue는 무엇이 왜 문제인지 한 문장, suggestion은 고칠 방법 한 문장.
- summary는 한국어 2~4문장: 무엇을 대조했고 결론이 무엇인지. 직접 확인하지 못한 것은 "(실행 안 함)"이나 "[미확인]"이라고 쓴다.

### Godot 변경일 때
- 규칙 계산은 `src/core/`의 로직(RunState)에만 있고, 씬 스크립트는 그 메서드를 부르기만 하는지.
- 탭 들여쓰기와 정적 타입, 노드 경로(`$이름`)와 `.tscn`의 노드 이름이 맞는지, 시그널이 씬 파일이나 `_ready`에서 이어지는지.
- 함수 이름이 실제 Godot 4 API인지 확신이 없으면 minor로 "확인 필요".

### 리서치 보고서일 때
- 핵심 주장마다 출처 번호, 출처 줄의 형식과 확인 날짜, 공식 문서 우선, 확인 못 한 것은 '미확인·한계'로 나눴는지.
- 출처 페이지를 열어 볼 수 없으면 summary에 "원문 대조 안 함"이라고 쓴다.

### MCP 도구 코드일 때
- 프롬프트의 '지킬 것'을 줄마다 대조한다. `subprocess`·`eval`·`exec`, 파일 쓰기·지우기, 비밀 읽기, 이 PC·집 안 주소 접속, 표준 라이브러리 밖 import는 blocking.
- 경로 입력을 `resolve()`한 뒤 프로젝트 폴더 안인지 검사하는지, 도구 스키마의 속성과 함수 인자가 같은지, 오류를 `ToolError`로 알리는지.
- stdout으로 print하는 곳이 있으면 blocking (MCP 통신이 깨진다).

### 확인
- 모든 수용 기준에 대해 채우는 곳을 찾았거나, 못 찾은 것을 blocking으로 적었는가.
- verdict와 findings가 맞는가 (blocking이 하나라도 있으면 changes_requested).
