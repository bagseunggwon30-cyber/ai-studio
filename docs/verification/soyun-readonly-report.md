# 소윤이 PC 경로 확인과 인증된 읽기 전용 검사

사용자가 소윤이의 연결 PC 조회 결과를 전달했다: `ai-studio-supervisor`, 도구 6개, `connection-only`, worker 0, 모델 생성 호출 0. 따라서 PC 명령 실행으로 도구 목록과 서버 상태를 조회하는 경로가 확인됐다. 소윤이의 세션 도구 목록에 직접 MCP를 등록한 결과는 아니다.

## 구현과 실제 확인

기존 `tools/dev/supervisor_connection_check.py`에 `--read-only`를 추가했다. 등록 설정·연결 전용 서버·회사 식별을 확인한 다음 기존 `soyun` 요청 키의 취소된 카드만 재사용한다. 카드가 없거나 상태·소유자·프로젝트가 바뀌거나 중복이면 새 제출 없이 멈춘다. 상태·이벤트·결과의 3개 읽기 도구만 호출하며 결과에는 토큰·개인 경로·작업 ID·내용을 넣지 않는다. 실패 출력도 원문 예외를 숨긴다.

이 PC에서 실제 Codex CLI 0.160.0의 app-server MCP 클라이언트와 등록된 연결 설정을 사용해 인증된 조회 3개가 성공했다. 새 작업 제출 0회, 취소 호출 0회, 모델 생성 0회, 클라이언트 모델 turn 0회다. 확인 카드는 취소 상태이고 구현·모델 실행 기록이 없다. [실제 집계 JSON](soyun-authenticated-readonly.json). 성공 결과는 재사용하며 소윤이 측 조회 결과로 바꿔 표시하지 않는다. 실제 조회 뒤 추가한 worker/호출 수 0 확인 조건은 보고받은 health 값과 일치하며 모의 클라이언트 검사로 검증했다.

토큰을 검사 프로그램이 읽지 않고 MCP 하위 프로세스만 기존 DPAPI 파일을 내부 처리한다. 임시 클라이언트 설정은 종료 시 정리한다. 서버의 감사 기록은 정상적으로 추가하지만 회사 설정·직원 MCP·제품 파일·기존 카드 상태는 수정하지 않는다. 쓰기 검사의 기존 `--owner-approved` 승인 경계를 유지한다.

## 검증 범위

새 검사 4개와 기존 연결 관련 4개, 총 8개가 통과했다. 취소 카드 재사용·읽기만 호출·클라이언트 종료, 누락/변경/중복 카드에서 자동 제출 금지, 설정 충돌 시 인증/클라이언트 시작 금지, 오류 출력 비밀값 미노출을 확인했다. 이 모의 검사와 실제 인증 조회는 구분한다.

최종 전체 회귀 검사는 코드 `7ac7681c8899af1af57e8ba35051e8b55ca62404`에서 `python -X utf8 -B tools/dev/regression.py --report docs/verification/soyun-readonly-regression.json`으로 실행했다. 검사 중 코드 불변과 검사 뒤 현재 소스가 같은 상태임을 확인했다. 이후 커밋은 문서·근거만 추가한다. 이전 275개 결과와 합산하지 않는다.

| 환경 | 전체 Python | 통과 | 생략 | 실패/오류 |
|---|---:|---:|---:|---:|
| 이 PC | 279 | 278 | 1 | 0 |
| Windows GitHub Actions | 279 | 259 | 20 | 0 |

PC 생략은 POSIX 프로세스 그룹 1개다. CI는 Godot 부재 19개를 추가로 생략했다. 두 환경 모두 진행판 12개와 JavaScript 문법 10파일 통과. PC 검사 시간은 662.7초, CI는 218.9초다. [PC JSON](soyun-readonly-regression.json), [CI JSON](soyun-readonly-ci/regression.json), [CI 가짜 모델 stdio 왕복](soyun-readonly-ci/supervisor-fake.json), [CI 실행](https://github.com/bagseunggwon30-cyber/ai-studio/actions/runs/37122170814).

위 CI는 GitHub의 PR 검사 커밋 `1c6c39ffc27130a9f48734f0e563df7c181f89e1`에서 실행했다. GitHub API로 이 커밋과 `7ac7681`의 Git 트리가 모두 `a907079dac9bcd959e79902182c1ef6f6dd3eb06`인 것을 확인했다. 실제 main 병합은 아니다. 코드 `7ac7681`의 push 검사도 [성공](https://github.com/bagseunggwon30-cyber/ai-studio/actions/runs/37122168721)했다. 환경별 바이트 해시는 각각의 JSON에 보존하며 같은 값이라고 표시하지 않는다. CI의 가짜 모델 왕복을 실제 회사·모델·소윤이 인증 검사로 표시하지 않는다. 원문 로그는 공개하지 않는다.

## 남은 확인과 실행 방법

소윤이의 연결 Windows PC에서 다음 명령을 1회 실행해야 **소윤이의 PC 경유 인증된 조회**가 확인된다. [전달 요청문](../SOYUN_CONNECT.md).

```powershell
Set-Location -LiteralPath 'S:\AI\ai studio'
python -X utf8 -B tools/dev/supervisor_connection_check.py --read-only
```

소윤이 측 인증 조회, 소윤이 세션의 직접 MCP 등록, 실제 직원 실행·QA·결재·결과 파일 생성은 이번에 확인하지 않았다. 서버는 연결 전용 상태로 유지하며 실제 모델 실행에는 별도 사용량 승인이 필요하다. 새 인증 정보·구독·공개 서버·터널은 만들지 않았다. main 병합과 배포도 하지 않았다.

변경 코드: `tools/dev/supervisor_connection_check.py`, `tests/test_supervisor_readonly_check.py`. 회사/토큰 파일은 공개 Git에 포함하지 않는다.
