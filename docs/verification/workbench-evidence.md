# 접고 펼치는 업무 묶음과 후보별 완료 근거

로컬 기능 브랜치 `codex/workbench-evidence-20261004`, 기준 `6b8bfa1`에 구현했다. 기존 main 개선을 유지하며 이번에는 main 병합·원격 push·배포·운영 서버 재시작을 하지 않았다.

## 구현 결과

- 서랍 / 펼친 업무 / 보관함에서 저장한 폴더를 열고 접는다. 넓은 작업면, 노드 옆 상세, 선택해서 여는 기능 도구함, 업무에 붙은 접이식 실행 이력을 제공한다. 독립 SVG와 기존 웜화이트/청록 색상을 사용한다. 접기는 실행 중 업무를 취소하지 않는다.
- 완료 기준의 문장과 신뢰 테스트/파일/이미지 근거를 구분한다. 최신 후보와 QA 영수증·스냅샷·신뢰 검사 버전·현재 리뷰를 확인해 각 기준의 충족/누락을 표시한다. 근거가 없거나 바뀌면 기존 결재 UI와 직접 승인 API를 막는다. 결과정리도 승인한 최신 후보의 근거를 다시 확인한다.
- 기존 결재 창의 CEO 수정 요청은 새 후보의 구현/테스트/검토/승인/결과 노드를 갱신한다. 이전 후보의 입출력과 근거는 별도 이력에 보존하고 최신/이전/전체 호출 수를 실제 실행 기록으로 계산한다.
- 완료된 기존 장부는 일괄 변경하지 않는다. 진행 중인 이전 구현은 CEO가 현재 후보에 기존 기준의 근거를 명시적으로 지정할 수 있다. 기준 변경·모델 재호출 없이 기존 QA를 확인한다.
- 기존 Engine, QA, 읽기 전용 리뷰, CEO 승인, 일지/산출물을 사용한다. 설명에서 임의 코드·셸을 실행하지 않으며 새 실행기·자동 재귀·자동 재시도·개발 세션 의존성을 추가하지 않았다.

## 검증

| 검사 | 결과 |
| --- | --- |
| 전체 Python unittest discovery | 358개 중 357통과, 실패/오류 0, POSIX 전용 1개 생략 |
| 추가 완료 근거 검사 | 위 전체 회귀에 포함된 12개 통과 |
| 기존 실제 Edge UI 회귀 | 60항목 통과 |
| 서랍/접기/상세/누락/수정 이력 UI | 38항목 통과 |
| QA 영수증·스냅샷 변조, 복구, 기존 결재와 완료 | 23항목 통과 |
| 실제 포인터 드래그/연결 포트/상세 겹침/키보드 | 7항목 통과 |
| 진행판 | 12항목 통과 |
| JS 문법, Python 파싱, git diff 검사 | 통과 |
| doctor | 정상 Windows 사용자 권한에서 종료 0, Claude 사용 불가 주의 |
| 실제 모델 호출/실제 회사 제출·취소 | 0 |

검사는 127.0.0.1:8798의 별도 임시 회사와 기존 `tests.helpers.FakeRuntime`만 사용했다. 실제 QA/후보 Git/결재를 사용했으며 운영 회사에 쓰지 않았다. 승인 중복 클릭은 한 번만 전송되고, 응답 유실 재전송은 같은 실행 장부를 반환한다. 변조 검사 파일은 원본 바이트로 복구했다. UI의 기대한 네트워크 실패는 실행 응답 유실 시험이며 스크립트 실행 오류는 0이다.

전체 Python 검사 뒤 변경한 부분은 화면의 작은 화면 배치·드래그 표시와 개발용 검사기다. Python 제품 구현은 전체 회귀 이후 동일하며, 마지막 화면 변경은 실제 포인터 및 화면 회귀로 검증했다. 검사 결과를 중복 합산하지 않는다.

근거: [전체 회귀](workbench-evidence-regression.json), [업무 묶음 UI](workbench-evidence-browser.json), [기존 UI 회귀](workbench-evidence-ui-regression.json), [변조/완료](workbench-evidence-browser-finish.json), [포인터](workbench-evidence-pointer.json), [보존](workbench-evidence-preservation.json).

## 사용 조건과 보존

보호 대상 파일 1939개 해시 변경 0개. `trusted/`, `company/`, `studio.toml`, 실제 `data/`, `projects/`, `worktrees/`를 바꾸지 않았다. 기존 `.playwright-cli/`와 `output/`를 유지하며 이번 캡처는 별도 접두사를 사용했다.

구버전 운영 서버는 다음 안전한 재시작 때 새 API를 읽는다. 이번에는 운영 서버를 다시 시작하지 않았다. 실제 구현/기획은 사용자가 계획·범위·기존 모델 사용을 확인해야 시작한다. 이 개발 세션이나 소윤/별도 로컬 Codex 중개 세션은 런타임에 필요 없다. Grok 확장·사무실/펫 복원·Sites/PC 릴레이 권한 변경은 하지 않았다.

파일 존재 근거는 의미를 판단하는 검사가 아니다. 내용의 요구사항은 이미 제공된 신뢰 테스트 이름에 연결한다. 테스트 노드는 기존 QA를 다시 읽으며 새로운 임의 검사 명령을 실행하지 않는다. 초기 호출 상한은 최초 실행 기준이며 CEO가 명시적으로 요청한 수정 실행은 별도 이력과 호출 집계에 포함된다.

## 실제 화면 전달

- `output/playwright/workbench-evidence-folders.png`: 폴더로 접은 업무.
- `output/playwright/workbench-evidence-missing.png`: 계약 파일 누락과 승인 잠금.
- `output/playwright/workbench-evidence-latest.png`: 수정 후보의 기준 충족과 현재/이전 호출 집계.
- `output/playwright/workbench-evidence-small.png`: 390px 화면.
- `output/playwright/workbench-evidence-completed.png`: 같은 실행의 승인/완료와 이전 후보 이력.

Library 업로드 성공: 최신 후보 화면 `file_0000000058dc81f5a6f11537a0423c1c` (`libfile_42278481f2ac8191a3e5859a931d772f`), 완료 화면 `file_000000005ef081f5a1a36cd3727a5f1e` (`libfile_3d4f698b2ed88191a0140f2a14de9220`). 실제 격리 UI 캡처이며 업로드 결과의 Library 확장 속성도 Windows 파일에 기록했다.
