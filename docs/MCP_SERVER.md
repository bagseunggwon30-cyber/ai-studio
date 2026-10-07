# AI Studio MCP 서버

AI Studio에 작업을 맡기고 진행·결과·검증 파일을 조회하는 외부 감독 MCP다. 기존 감독 엔진과 API를 재사용하며 Python 3.11 이상 표준 라이브러리만 사용한다. 직원에게 도구를 장착하는 MCP 보관소와는 별개의 기능이다.

> ChatGPT·Dots 같은 **클라우드 에이전트**가 이 MCP를 쓰게 하려면 인터넷 주소와 OAuth 로그인이 필요해요. 그 문(기본 꺼짐, 127.0.0.1에만 열림)은 [MCP 연결 문 안내](MCP_GATEWAY.md)를 보세요.

## 바로 사용하기

로컬 stdio·감독 토큰 연결은 사용자가 승인한 연결 정보가 준비된 PC에서 사용한다. 공개 저장소에는 로그인 정보·토큰·개인 클라이언트 등록이 포함되지 않는다. 처음 원격 클라이언트를 연결하려면 [OAuth 게이트웨이 안내](MCP_GATEWAY.md)를 따른다. 연결 전용 호스트가 실행 중이라면 중복 실행하지 않는다.

```powershell
# 저장소 루트에서 실행
python -X utf8 -B tools/supervisor-host.py --port 8765
```

이 호스트는 MCP와 감독 API만 제공한다. 직원·스케줄러·기존 작업 재실행·모델 호출을 시작하지 않으며 CEO 대시보드 쓰기 API도 제공하지 않는다. 기존 작업 상태와 승인 경계를 유지한다.

### stdio 클라이언트

```powershell
python -X utf8 -B studio.py mcp --config json
python -X utf8 -B studio.py mcp --config codex
```

첫 명령은 `mcpServers` JSON, 둘째는 Codex TOML 설정을 출력한다. 현재 Python과 절대 실행 경로를 사용하므로 등록할 때 생성한 설정을 그대로 사용한다. 토큰 값이나 암호화 파일 내용은 출력하지 않는다. 기존 `ai_studio` 등록이 있다면 중복 등록하지 않고 이 항목만 확인한다. 이 명령은 기존 사용자 설정 파일을 덮어쓰지 않는다.

실제 stdio 실행 명령:

```powershell
python -X utf8 -B studio.py mcp --port 8765 --user-credential
```

MCP 클라이언트가 위 프로세스를 실행하고 stdin/stdout으로 통신한다. stdout에는 MCP JSON-RPC 메시지만 나온다. 프로그램이 현재 Windows 사용자의 기존 DPAPI 연결 파일을 내부적으로 사용하며 토큰을 모델·명령줄·출력에 넣지 않는다. 다른 사용자 계정의 비밀정보를 읽거나 복사하지 않는다.

기존 `tools/supervisor-mcp.py --port ... --credential ...` 실행도 계속 지원한다. 지정한 암호화 연결 파일 또는 `STUDIO_SUPERVISOR_TOKEN` 환경변수를 사용하는 기존 클라이언트는 유지할 수 있다. 회사 초기화·제품 저장소 생성은 stdio 연결에 필요하지 않다.

### Streamable HTTP 클라이언트

연결 주소: **`http://127.0.0.1:8765/mcp`**

연결 전용 호스트와 일반 대시보드 서버 모두 같은 경로를 제공한다. HTTP에는 기존 감독 연결 토큰을 Bearer 헤더로 전달해야 한다. CEO 페이지 토큰·휴대폰 토큰·MCP 세션 ID는 이 인증을 대신하지 못한다. 토큰은 클라이언트의 비공개 환경/인증 저장소에서 전달하고 코드·채팅·로그에 넣지 않는다. 수동 토큰 전달을 피하려면 위 stdio 방식을 사용한다.

Codex의 HTTP 설정 형태는 아래와 같다. 환경변수 값은 이 문서나 설정에 넣지 않는다.

```toml
[mcp_servers.ai_studio]
url = "http://127.0.0.1:8765/mcp"
bearer_token_env_var = "STUDIO_SUPERVISOR_TOKEN"
enabled_tools = ["submit_task", "task_status", "task_events", "task_result", "task_artifact", "cancel_task"]
default_tools_approval_mode = "writes"
```

2025-11-25 / 2025-06-18 / 2025-03-26 MCP의 JSON 응답 방식이며 세션 ID를 발급하지 않는다. POST는 JSON-RPC 한 건과 JSON/SSE Accept 헤더를 사용한다. 알림에는 본문 없는 202를 반환한다. 서버 SSE 스트림과 세션 종료 요청은 제공하지 않아 GET/DELETE는 405다. 미지원 프로토콜·잘못된 JSON·본문 상한 초과·허용되지 않은 Host/Origin을 차단한다. [MCP 통신 규격](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

## 도구와 권한

| 도구 | 용도 | 변경 여부 |
|---|---|---|
| list_projects | 이 연결이 볼 수 있는 프로젝트(키·이름·종류·제출 가능 여부 `can_submit`·실행 시작 가능 여부 `can_run`·폴더 범위) 목록 | 읽기 |
| list_tasks | 프로젝트의 최근 작업 목록(번호·제목·상태·종류, filter=all·open·상태 이름, 최대 50개; 지시 본문·보고서는 담지 않음) | 읽기 |
| submit_task | project/key/payload로 작업 제출; 영속 중복 방지 | 승인된 범위에 카드 생성 |
| task_status | 상태·차단 사유·필요한 결재·재개 방법 | 읽기 |
| task_events | after 커서로 진행 이벤트 조회 | 읽기 |
| task_result | 산출물·수용 기준 근거·실행 기록 조회 | 읽기 |
| task_artifact | 검증한 허용 경로의 파일과 SHA256 조회 | 읽기 |
| cancel_task | 이 연결이 제출한 미완료 작업 취소 | 자신의 작업 취소 |
| run_task | 이 연결이 제출한 작업의 **실행 시작**(화면의 [실행]과 같은 `Engine.request_run`). 프로젝트 권한에 `run: true`가 있을 때만 목록에 보이고 동작한다 | 자신의 작업에 실행 요청 표시만 켬 (결재·병합·완료 아님) |

같은 키·같은 내용은 기존 카드를 반환하고 다른 내용은 충돌이다. 프로젝트/경로 권한은 기존 감독 등록을 따른다. 기획 결재·최종 승인·main 병합·설정/권한 변경 도구는 없다. 읽기 전용 연결은 제출·취소·실행 시작을 할 수 없다. 결과가 AI의 완료 주장인지 실제 검증/사람 승인인지 구분한다.

**실행 시작(`run_task`)**: 제출만으로는 모델이 실행되지 않는다(CEO가 [실행]을 눌러야 하거나 자동 실행이 켜져 있어야 한다). 실행 시작은 CEO가 프로젝트마다 `run`을 켠 곳에서만 되고 기본은 **꺼짐**이다. 옛 `data/supervisors.json`의 프로젝트 권한에는 `run` 칸이 없어서 그대로 거절되며, 켜려면 CEO가 그 프로젝트 권한에 `"run": true`(와 `"write": true`)를 직접 넣어야 한다. 조건: 이 연결이 제출한 작업만, 상태가 `queued`·`ready`일 때(이미 시작했거나 `running`·`checking`·`awaiting_approval`이면 오류 없이 현재 상태를 `replayed: true`로 반환, 끝났거나 막힌 작업은 409), 긴급 정지 중이 아닐 때(409), 같은 연결이 동시에 실행을 시작해 둔 작업이 3개 미만일 때(`MAX_RUNNING`, 409). 응답은 `task_status`와 같은 모양에 `started`·`replayed`·`run_requested`가 더해진다. HTTP 목록에서는 어느 프로젝트에도 `run: true`가 없는 옛 토큰에게 `run_task`를 숨기고(호출해도 거절), stdio 브리지는 권한을 미리 알 수 없어 항상 보여 주되 호출은 같은 검사로 거절한다.

MCP 텍스트 응답 상한은 기존 60,000자를 유지한다. 큰 결과 파일은 감독 API의 별도 크기 제한 안에서 조회해야 하며, 잘린 JSON을 성공 결과로 반환하지 않는다.

## 연결 상태의 구분

로컬 Codex의 실제 MCP 클라이언트에서 stdio와 HTTP 연결을 검증한다. 클라우드의 소윤이/ChatGPT가 PC의 localhost에 직접 접속하거나 로컬 Codex 설정을 자동으로 읽는 것은 별개의 문제다. 이 서버 구현/로컬 검증을 소윤이 클라우드 등록 완료로 표시하지 않는다. 현재 공개 서버·터널·새 API 키를 생성하지 않았고 연결은 127.0.0.1에만 제공한다.

최신 구현·검증 근거는 [MCP 보고](verification/mcp-native-report.md)를 참고한다.
