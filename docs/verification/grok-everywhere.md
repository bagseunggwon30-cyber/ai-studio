# Grok Everywhere 어댑터 — 2026-10-05

브랜치: `codex/grok-everywhere-adapter-20261005`. main 병합·push·배포·운영 재시작 없음.

## 구현 범위

- 공개 upstream `sudoHG/grok-everywhere`의 `4c6fad3eca694b4bc1c9fedea41ae236139f2044` / CLI 0.2.0 계약을 읽기만 했다. 설치하거나 실행하지 않았다.
- 조사·이미지·영상의 재사용 기능을 기존 작업대 도구함에 추가했다. 실제 연결은 기본 차단이며 설치·세션 파일 접근·외부 전송·요청 모델·알 수 없는 비용에 대한 별도 검토가 필요하다. `execute` API는 확인 여부와 무관하게 차단한다.
- 기존 Host/Origin/세션 토큰 경계 안에 읽기 전용 catalog와 데이터 초기화 없는 plan을 추가했다. 계획은 실제 입력·고정 옵션·모델·unknown 비용을 해시에 묶는다. 노트나 임의 셸·추가 플래그를 실행하지 않는다.
- 고정 `--auth session` argv 명세, 환경변수 allowlist, 명시적 모델 계약, 엄격한 JSON 응답, unknown 비용 보존, 미완료 조사 결과의 막힘 처리를 추가했다. 요청 모델/보고 모델은 실제 모델 확인을 보장하지 않으므로 `model_verified=false`다.
- 상대 경로·Windows 드라이브/UNC/ADS·역행·예약 이름·제어문자·reparse point를 거부한다. 선택한 제한 크기 PNG/JPEG/MP4/WebM만 검증하며 원본 응답·인증·캐시 JSON은 산출물로 내보내지 않는다.
- 모의 공급자는 OS 임시 폴더의 FakeRuntime 회사에 코드로 주입할 때만 연결된다. 실제 회사 설정이나 API로 모의를 켤 수 없다. 결과는 기존 장부, Store 작업·일지·실행 기록에 연결한다. 모의 작업 카드는 `blocked`, `run_requested=false`, `workflow_no_retry=true`이고 `done`이나 승인으로 바꾸지 않는다. 모의 기록은 실제 모델 호출 집계에서 제외한다.
- 호출 전에 예약을 저장한다. 같은 확인 번호의 중복 클릭은 같은 장부를 반환한다. 타임아웃·중단·결과 불확실은 재제출하지 않는다. 구조화된 영상 request_id가 있는 모의 요청만 명시적으로 같은 ID의 GET을 확인한다. pending/failed는 완료로 표시하지 않고 성공 시 후속 참조 단계만 복구한다.
- 기존 공급자 상세 영역에만 읽을 수 있는 모의 결과 패널·미디어 미리보기·작업 링크를 추가했다. 원래 서랍/레이아웃/흐름 효과를 유지했다. 검증된 `artifact_reference`는 다음 단계로 형식을 유지해 전달하며 텍스트로 암묵 변환하지 않는다.

## 검증 결과

- 최종 전체 discovery: **369개 중 368 통과, POSIX 전용 1 건너뜀, 실패/오류 0**. 34 모듈의 실제 ID가 일반 discovery와 정확히 일치한다. [전체 결과](grok-everywhere-regression-final.json).
- 관련 회귀 73개 통과. 마지막 타입/상태/경로 변경 후 새 모듈 11개 재실행 통과.
- 최초 sandbox 전체 실행은 Godot 임시 로그/시스템 인증서 접근 제약과 시간 초과로 실패했다. 이를 통과로 취급하지 않았다. 격리된 오프라인 전체 실행을 정상 환경 권한으로 다시 실행한 위 결과를 최종 결과로 사용한다.
- 기존 Edge와 TempStudio로 실제 UI 확인: 조사/이미지/영상 MOCK 표시, 1024×768 PNG 디코딩, 로컬 canvas에서 기록한 320px WebM 재생(약 1.4초), 390px 가로 넘침 없음, pageerror 0. 도구함의 목적/입력/산출물/조건, 정확한 input→format 요청과 옵션/unknown 비용 계획, 닫기·재열기·Escape, Tab/Shift+Tab 초점 유지, 잘못된 형식 연결 거부, 중복 클릭 1회 기록, 확인 후 모의 UI 실행 및 기존 기록을 확인했다. [브라우저 결과](grok-everywhere-browser.json).
- 정지 화면: `output/grok-everywhere-browser/{drawer,plan,research,image,video,narrow,executed}-mock.png`. 애니메이션 종료 상태로 캡처했다. WebM 모의 재생은 실제 공급자 MP4 생성·연결을 검증한 것이 아니다.
- Python 컴파일, JS 문법, `git diff --check` 통과. `doctor`는 인증 검사 가능성이 있어 **실행 안 함**. 실제 Grok CLI·모델·유료 API·외부 생성 호출 **0**, 인증 파일 읽기 **0**.
- 보호 파일 **1759개 변경/삭제 0**. 기존 `grok_text.py`, `runtimes.py`, `engine.py` 해시 유지. [보존 확인](grok-everywhere-preservation.json).

## 실제로 남은 일

실제 supplier transport는 미설치·미연결이다. 연결하려면 핀 버전 설치 검토, 기존 CLI와 다른 직접 세션 파일 접근 정책, 외부 전송 내용, 모델별 비용/한도 및 요청별 일회 승인 흐름을 먼저 승인받아 구현·검증해야 한다. 기존 Grok CLI 승인을 새 공급자 접근 승인으로 재사용하지 않았다. API 키 자동 선택이나 무료 보장은 없다.

AI가 저장한 스킬·노트를 선택해 작업대를 자동 구성하는 중앙 기획자는 **미구현**이다. 이번 결과는 기능 경계와 기존 작업대의 수동 계획/모의 실행 연결이다.
