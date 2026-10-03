# AI Studio MCP 구현·검증 보고

최종 갱신: 2026-10-04. 기존 감독 API/권한/작업 엔진을 재사용해 외부 감독 MCP를 실제 사용할 수 있게 했다. 신규 모델 호출은 0회이며 회사의 프로젝트 권한·토큰·직원 도구 설정은 확대하지 않았다.

## 구현한 기능

- `python studio.py mcp` stdio 실행, `--config json/codex`로 비밀값 없는 절대 경로 등록 설정 출력. 기존 wrapper와 암호화 연결 파일 방식은 계속 지원한다.
- 기존 로컬 서버와 연결 전용 호스트에 `/mcp` Streamable HTTP 추가. 2025 MCP 3개 버전, JSON 응답, 세션 없는 방식이다. 공개 서버·터널·SSE는 만들지 않았다.
- stdio/HTTP가 하나의 6도구 목록과 같은 Supervisor 권한·영속 idempotency를 사용한다. 제출·상태·이벤트·결과·검증 파일·자신의 작업 취소를 제공한다.
- Host/Origin/Bearer 인증, 읽기/쓰기·프로젝트/경로 제한, 입력/크기/프로토콜 검증, 감사 기록을 유지한다. 도구 등록/제출은 모델 실행이나 사람 승인/병합을 대신하지 않는다.
- HTTP 응답·감사 기록에 알 수 없는 요청 문자열이나 토큰을 반사하지 않는다. CEO 페이지 토큰·휴대폰 토큰·MCP 세션 ID는 감독 인증을 대신하지 못한다.

변경 코드: `studio/cli.py`, `studio/server.py`, `studio/supervisor_mcp.py`, 신규 `studio/supervisor_mcp_http.py`, `tools/supervisor-host.py`, 신규 `tests/test_supervisor_mcp_http.py`. 사용법: [MCP_SERVER.md](../MCP_SERVER.md). README와 HANDOFF에 최신 안내를 연결했다.

## 실제 실행으로 확인한 범위

| 검사 | 결과 | 실행 환경/한계 |
|---|---|---|
| 새 MCP/CLI/권한 검사 | 10개 통과 | 임시 회사·합성 인증. 실제 HTTP 서버, 가짜 기획/구현/QA/리뷰 파일 조회 |
| 기존 감독/등록/읽기 검사 | 36개 통과 | 임시 환경. 아래 전체 검사와 합산하지 않음 |
| 설치된 Codex MCP 클라이언트 HTTP 왕복 | 통과, 도구 6개 | `codex-cli 0.160.0`의 app-server, 임시 회사에서 6개 도구 전부 호출: 제출→재전송→가짜 구현/QA→상태/이벤트/결과/파일(SHA256 확인)→별도 자기 작업 취소. 모델 turn 0 |
| 실제 회사 stdio/HTTP 인증 조회 | 둘 다 통과, 각 도구 6개 | 동일 설치 클라이언트로 기존 취소 확인 카드의 상태/이벤트/결과만 조회. 새 제출/취소/모델 호출 0, 기존 작업 파일·설정 불변 |
| 소윤이 클라우드의 직접 MCP 등록 | 미확인 | 로컬 클라이언트 성공과 별개. localhost에 클라우드가 접속됐다고 판단하지 않음 |

근거: [임시 회사의 실제 MCP 클라이언트](mcp-native-http-codex.json), [실제 회사 읽기 전용 연결](mcp-native-production-readonly.json). 토큰·개인 경로·실제 카드 ID·원문 로그는 공개 근거에 포함하지 않는다.

현재 실제 회사의 연결 전용 호스트는 `127.0.0.1:8765`, MCP 주소는 `http://127.0.0.1:8765/mcp`다. 이 호스트는 workers 0·모델 생성 0이며 기존 작업을 복구/실행하지 않는다. 실제 직원 실행이 필요하면 기존 CEO 승인 절차에 따라 별도로 일반 서버를 켜야 한다.

## 마지막 수정 후 전체 검사

S 드라이브에서 `python -X utf8 -B tools/dev/regression.py --report docs/verification/mcp-native-local-regression.json`을 실행했다.

- Python 총 **292개: 291통과·1생략·0실패·0오류**. 생략은 `tests.test_lifecycle.ChildProcessTests.test_timeout_isolates_and_reaps_child`이며 통과로 세지 않았다.
- 진행판 12개 통과, JavaScript 문법 10파일 통과. 815.2초, 검사 중 소스 불변.
- 기준 HEAD `3e75093ab0f23625e18483f9d4a997437140bfec`에 이번 MCP 변경과 사용자의 기존 직원/UI 변경이 함께 적용된 로컬 코드다. HEAD 자체만 검증했다고 표시하지 않는다.
- 검증한 소스 SHA256: `0f38bd5d5c0a69591b462e17bb43d690b774df20ed558963498b872dd646ebc0` (403파일).
- [전체 검사 JSON](mcp-native-local-regression.json). 이전 검사/부분 검사를 합산하지 않았다.

MCP 별도 브랜치의 Windows Actions 전체 검사도 **통과**했다. 이 브랜치는 사용자의 병행 직원/UI 변경을 포함하지 않아 S 드라이브 결과와 합산하지 않는다.

- 코드 커밋 `b999f5960822688a9d5e4837eea061a64fe46230`; CI 체크아웃 `5885523288ad469cec20e7a6aeb7248664fb7676`의 Git 트리가 이 코드 커밋과 동일하다.
- Python 총 **291개: 271통과·20생략·0실패·0오류**. 생략 항목은 JSON에 기록했고 통과로 세지 않았다.
- 진행판 12개·JS 문법 10파일·가짜 모델 stdio 왕복 통과. 전체 검사 246.8초, 검사 중 소스 불변.
- 검증한 소스 SHA256: `273241cb14904e756cdb675f1e7ce45c13d1e7e0889430dbdda4d66e98db0b4a` (403파일). 이후 갱신은 문서·집계 근거만이며 이 소스 해시가 같다.
- [CI 실행](https://github.com/bagseunggwon30-cyber/ai-studio/actions/runs/37132330592), [CI 전체 검사](mcp-native-ci-regression.json), [CI 가짜 모델 왕복](mcp-native-ci-supervisor-fake.json), [커밋/소스 일치 확인](mcp-native-ci.json).

GitHub 변경은 `codex/ai-studio-mcp`의 [초안 PR #2](https://github.com/bagseunggwon30-cyber/ai-studio/pull/2)로 올렸다. 기존 MVP 브랜치 위의 별도 변경이며 main에 병합하지 않았다.

## 아직 확인하지 못한 것과 다음 조치

이 PC의 로컬 MCP 서버와 실제 인증 조회는 완료했다. **소윤이 클라우드 세션에 직접 MCP가 등록·노출되는 상태는 아직 확인하지 못했으며 연결 완료로 보고하지 않는다.** 클라이언트가 로컬 stdio를 지원하면 생성한 설정을 등록하고 도구 6개를 확인한다. 클라우드 전용 클라이언트라면 연결 PC의 MCP 실행/등록을 지원하는 경로가 필요하다. 공개 URL·권한 확대가 필요한 경로는 이번 범위에 포함하지 않는다.

이번 MCP 작업에서 실제 Codex/Grok 생성은 추가 실행하지 않았다. 이전 승인된 모델 실험 결과를 새 MCP 코드의 실제 생성 검증으로 표시하지 않는다. main 병합·외부 배포·새 자격 증명 생성은 하지 않았다.
