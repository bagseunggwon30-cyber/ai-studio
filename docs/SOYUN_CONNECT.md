# GPT dots 소윤이를 메인 감독으로 연결하기

소윤이는 지시를 정리하고 AI Studio에 제출한 뒤 상태·결과·근거를 확인하는 메인 감독이다. AI Studio는 작업 저장·복구·병렬 처리·권한·검증을 담당한다. Codex는 기존 ChatGPT 로그인으로 코드 작업을, Grok은 기존 grok.com 로그인으로 입력 텍스트의 조사·기획 보조·읽기 전용 리뷰를 맡는다. Claude는 필수가 아니다. 모델 API 키나 새 구독으로 전환하지 않는다.

## 현재 확인한 것

- Grok CLI 1.0.41로 기존 로그인 기반 텍스트 리뷰 1회 성공. 요청 모델은 `grok-4.7`; 응답의 정확한 모델 ID는 확인 불가.
- 설치된 Codex app-server의 실제 MCP 클라이언트가 도구 6개를 등록하고 임시 회사에 왕복 호출했다. Codex 모델 호출은 0회. 이 검사는 소윤이의 도구 등록을 증명하지 않는다.
- 사용자가 이 PC의 접근 허용을 확인했고, 2026-10-03에 아래 로컬 MCP·토큰·프로젝트 범위 적용을 승인했다. 로컬 MCP 등록과 실제 회사 API 왕복은 완료했다. **소윤이 클라우드에서 직접 도구를 호출했는지는 아직 확인하지 않았다.**
- 이후 소윤이의 새 `AI Studio 도구 목록 확인` 작업에서도 `ai_studio`가 세션 도구 목록에 없었다. 해당 작업은 클라우드가 조정하면서 연결된 PC를 사용하는 형태다. PC의 설정 등록과 이 세션의 도구 노출은 별개이며, 새 작업을 만드는 것만으로 해결된다고 안내한 부분을 정정한다. 인증·연결 오류가 없다는 사실만으로 서버 접속이나 인증 성공을 판단하지 않는다.
- 사용자 전달로 **소윤이의 연결 PC 조회 성공**을 확인했다: `ai-studio-supervisor`, 도구 6개, `mode=connection-only`, `workers=0`, `model_generation_calls=0`. 이는 PC 명령 실행 경로의 목록/health 성공이며 세션 도구 목록에 직접 등록된 것은 아니다.
- 다음 단계인 인증된 조회 명령을 추가했다. 이 PC의 실제 Codex MCP 클라이언트에서 기존 확인 카드의 상태·이벤트·결과 조회가 성공했다. 새 제출·취소·모델 호출은 0회다. **소윤이 측 인증된 조회는 아직 미확인**이다. [조회 근거](verification/soyun-authenticated-readonly.json).
- 소윤이가 `--read-only`를 1회 실행했지만 `blocked / ValueError`를 반환했다. 당시 집계 오류에 실패 단계가 없어 정확한 원인은 미확정이다. 이 PC에서는 설정 일치·기존 카드·서버 상태가 정상이다. 이제 `--diagnose`로 인증 없이 단계와 다른 설정 항목 이름만 확인한다. 토큰·설정 값·개인 경로는 출력하지 않는다.

## 1. 이 PC를 소윤이에 연결

이 PC의 ChatGPT 데스크톱 앱에서 소윤이 프로필 → **Computers / 컴퓨터** → **Your computer / 내 컴퓨터** → **Allow access / 접근 허용**을 선택하고 확인 창에서 다시 허용한다. PC를 켜 두고 ChatGPT 앱을 열어 둬야 한다. Codex 컴퓨터 연결이나 Work Sync와는 별도 권한이다.

이 기능은 로컬 파일·코드·앱을 사용하는 접근 권한이다. AI Studio 프로젝트별 범위를 자동으로 설정해 주는 것은 아니다. 소윤이는 연결된 PC에 로컬 Work/Codex 작업을 만들 수 있다. 클라우드에 있는 소윤이가 이 PC의 `127.0.0.1`이나 stdio 서버를 바로 사용할 수 있다고 가정하지 않는다.

공식 안내: [dots 컴퓨터 연결](https://learn.chatgpt.com/docs/dots/computers-and-apps), [dots 권한 관리](https://learn.chatgpt.com/docs/dots/controls).

## 2. 승인받아 적용한 연결 범위 (2026-10-03)

| 항목 | 적용 범위 |
|---|---|
| 메인 감독 | GPT dots 소윤이 |
| 로컬 실행 경로 | 이 PC의 Codex MCP 등록·API 왕복 확인 완료; 소윤이 세션의 도구 노출은 미연결 |
| 허용 프로젝트 | 기존 `studio-docs` 하나 |
| 허용 결과 경로 | `reports/connection-check/**` |
| 읽기 | `studio-docs` 프로젝트의 작업 상태·이벤트·검사 근거, 위 경로의 결과 파일 |
| 쓰기 | 위 범위의 작업 제출, 자신의 미완료 작업 취소 |
| 실행·승인 | 기존 CEO 실행·기획 결재·최종 병합 경계 유지; MCP에는 승인 도구 없음 |
| 모델 검증 | 새 승인 전 실제 모델 호출 0회 |

승인에 따라 `data/supervisors.json`에 `soyun` 연결을 등록했다. 서버에는 토큰의 SHA256만 저장하고 원문은 Windows **DPAPI CurrentUser**로 암호화해 Git 저장소 밖의 사용자 로컬 폴더에 보관한다. 파일 ACL도 현재 사용자로 제한한다. MCP 설정에는 토큰 값과 토큰 환경변수가 없으며 암호화 파일의 위치만 전달한다. 구독 로그인과 별개인 로컬 접근 토큰이며 유료 모델 API 키가 아니다. 직원의 MCP 장착·모델·회사 규칙과 실제 제품 파일은 바꾸지 않았다.

설치된 Codex의 사용자 `config.toml`에 `ai_studio` 도구 6개를 등록했다. 기존 MCP와 다른 설정은 보존했다. 실제 등록 블록으로 Codex MCP 클라이언트를 띄워 실제 회사에 제출·상태·이벤트·결과·취소를 확인했고, 경로 밖/다른 프로젝트/요청 키 충돌을 차단했다. 모델 turn 0회다. 결과 파일은 작업을 실행하지 않아 아직 없으며, 파일 조회는 그 이유로 거절됐다. 파일 생성 성공을 주장하지 않는다. [실제 회사 연결 근거](verification/soyun-production-connection.json).

현재 서버는 **연결 전용**이다. `127.0.0.1:8765`의 감독 API만 제공하며 직원·스케줄러·모델은 시작하지 않고 기존 카드를 복구/재실행하지 않는다. CEO 대시보드 쓰기 API도 제공하지 않는다. 실제 작업을 실행하려면 모델 사용을 승인한 뒤 연결 전용 서버를 종료하고 같은 포트의 일반 `python studio.py serve`로 전환해야 한다. 일반 serve 실행은 이번 설정 검사에 포함하지 않았다.

## 3. MCP 등록과 소윤이의 실제 도구 확인

현재 설치된 Codex는 로컬 stdio MCP를 지원한다. 실제 등록은 다음 형태이며 설치 과정에서 Python과 암호화 파일의 실제 위치를 넣었다. 아래는 비밀값 없는 개념 예시이며 그대로 복사하지 않는다.

```toml
[mcp_servers.ai_studio]
command = "python"
args = ["-X", "utf8", "-B", "S:\\AI\\ai studio\\tools\\supervisor-mcp.py", "--port", "8765", "--credential", "OWNER_PRIVATE_DPAPI_FILE"]
enabled = true
enabled_tools = ["submit_task", "task_status", "task_events", "task_result", "task_artifact", "cancel_task"]
startup_timeout_sec = 20
tool_timeout_sec = 20
default_tools_approval_mode = "writes"
```

도구: `submit_task`, `task_status`, `task_events`, `task_result`, `task_artifact`, `cancel_task`.

공식 [MCP 안내](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)의 로컬 클라이언트 설정이 소윤이 클라우드에 자동 상속된다는 보장은 없다. 연결된 로컬 작업에서 도구를 확인하고 왕복 호출한 뒤에만 소윤이 연결 완료라고 보고한다. 로컬 작업에서 등록이 불가능하면 그 단계가 미완료다. API 키가 필요한 터널이나 서버 공개로 우회하지 않는다.

**2026-10-03 후속 진단:** 소윤이의 확인 작업은 현재 세션의 도구 메타데이터만 확인했고 PC의 MCP 설정·서버 접속·인증 검사는 수행하지 않았다. 이 PC에서는 등록이 활성 상태이고 연결 전용 서버도 응답한다. 토큰 없이 별도 stdio 프로세스의 `initialize`와 `tools/list`만 실행해 6개 도구가 광고되는 것도 확인했다. 이 검사는 도구 호출·작업 제출·취소·인증 검사가 아니며, 소윤이의 세션에서 도구가 보였다는 증거도 아니다.

공식 [dots 컴퓨터 안내](https://learn.chatgpt.com/docs/dots/computers-and-apps)는 PC를 사용하는 작업도 클라우드에서 관리될 수 있다고 설명한다. 공식 [MCP 안내](https://learn.chatgpt.com/docs/extend/mcp?surface=app)는 호스팅된 Work의 플러그인 도구와 로컬 Codex 설정을 구분하고 ChatGPT web은 로컬 설정 파일을 읽지 않는다고 명시한다. **설정이 해당 클라우드 세션까지 전달되지 않은 것이 유력한 설명**이다. 계정 정책·등록 전달 경로의 정확한 내부 원인은 시작 로그가 없어 확정하지 않는다. 토큰 재발급·권한 확대·서버 공개로 해결하려고 하지 않는다.

현재 가능한 경로는 다음처럼 구분한다.

- 로컬에서 조정·실행하는 Codex: 기존 `ai_studio` 설정을 사용한 실제 클라이언트 검증 완료.
- 소윤이/클라우드 세션의 도구 목록에 직접 등록: 미완료. 공식 [개발용 MCP 연결](https://developers.openai.com/plugins/deploy/connect-chatgpt)은 공개 HTTPS 또는 Secure MCP Tunnel을 안내한다. [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)은 runtime API key와 별도 터널 권한이 필요하므로 기존 로그인만 재사용하는 승인 범위에서 설치·생성·등록하지 않았다. 로컬 플러그인을 설치하는 것만으로 dots 클라우드에서 사용할 수 있는지도 확인되지 않았다.
- 이미 연결한 PC의 명령 실행으로 stdio MCP 사용: 서버를 공개하지 않는 별도 접근 경로다. 우선 아래 토큰 없는 목록·서버 상태 조회만 소윤이 측에서 확인한다. 이후 인증된 호출을 하려면 로컬 실행기가 비공개 연결 파일을 내부적으로 처리해야 하며, 토큰 값을 모델에 전달하지 않는다. 이 경로를 세션 MCP 등록 완료로 표시하면 안 된다.

### 연결된 Windows PC에서 할 무인증 확인

아래 명령은 연결된 PC에서 실행한다. 클라우드 컴퓨터의 localhost에는 실행하지 않는다. 토큰·사용자 설정을 읽지 않고 `tools/call`도 보내지 않는다. `-B`로 Python 캐시 쓰기도 막는다. 이 PC의 직접 조회와 사용자가 전달한 소윤이 측 조회 모두 성공했다. 다음 단계는 아래 인증된 조회이며 같은 무인증 목록 확인을 반복하지 않는다.

```powershell
Set-Location -LiteralPath 'S:\AI\ai studio'
@'
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"soyun-discovery-only","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
'@ | python -X utf8 -B -c "from studio.supervisor_mcp import build; build(8765, '').serve()" | ForEach-Object {
    $studioDiscovery = $_ | ConvertFrom-Json
    if ($studioDiscovery.id -eq 1) { $studioDiscovery.result.serverInfo | ConvertTo-Json -Compress }
    if ($studioDiscovery.id -eq 2) { @($studioDiscovery.result.tools | Select-Object name, annotations) | ConvertTo-Json -Depth 4 -Compress }
}
Invoke-RestMethod -Uri 'http://127.0.0.1:8765/supervisor/health' -TimeoutSec 5 |
    Select-Object schema, mode, workers, model_generation_calls | ConvertTo-Json -Compress
```

예상: 서버 이름 `ai-studio-supervisor`, 도구 6개, health의 `mode=connection-only`, `workers=0`, `model_generation_calls=0`. 실패하면 어느 명령을 어느 실행 환경에서 실행했는지와 비밀값 없는 오류만 보고한다. 등록되지 않은 도구의 목록을 계속 재확인하는 것으로 이 단계를 대체하지 않는다.

### 연결된 Windows PC에서 할 인증된 읽기 전용 확인

```powershell
Set-Location -LiteralPath 'S:\AI\ai studio'
python -X utf8 -B tools/dev/supervisor_connection_check.py --read-only
```

새 승인이나 토큰 생성 없이 이미 승인된 `soyun` 연결과 `studio-docs` 범위를 사용한다. 검사 프로그램은 등록 설정을 확인하고, 로컬 MCP 하위 프로세스만 기존 DPAPI 연결 파일을 내부적으로 복호화한다. 토큰을 부모 검사 프로그램·명령줄·모델·출력에 전달하지 않는다. 현재 Windows 사용자가 다르거나 설정이 바뀌면 실패로 멈춘다.

기존 요청 키의 **취소된 확인 카드**를 찾아 `task_status`, `task_events`, `task_result`만 호출한다. 카드가 없거나 상태가 바뀌거나 중복되면 새 카드를 만들지 않고 멈춘다. 제출·취소·결과 파일 생성·모델 turn·CEO 결재·병합은 수행하지 않는다. 클라이언트의 비공개 임시 설정은 종료 시 정리하며 서버는 정상 감사 기록을 추가한다. 제품·회사 설정은 수정하지 않는다. 이전 제출/취소 검사의 `--owner-approved` 명령과 혼동하지 않는다.

출력은 비밀값 없는 집계 JSON이다. 성공 기준은 `status=pass`, `mode=authenticated-read-only`, `existing_probe_reused=true`, `task_status=cancelled`, `authenticated_reads` 3개, `new_tasks_submitted=0`, `cancellation_calls=0`, `model_generation_calls=0`, `client_model_turns=0`이다. 실제 작업 ID·작업 내용·토큰·개인 경로는 출력하지 않는다. 실패하면 `status=blocked`, `stage`, 오류 종류와 고정된 설명을 보여 주며 자동 복구·재제출하지 않는다.

이 PC에서 실제 등록된 Codex MCP 클라이언트의 인증된 조회는 성공했다. 소윤이가 이 명령으로 같은 결과를 받으면 **PC 명령 실행을 통한 인증된 MCP 조회**가 확인된 것이다. 소윤이 세션에 직접 MCP 도구가 등록된 것, 직원 실행·QA·결재·결과 파일 생성이 성공한 것과는 구분한다.

### 인증 조회가 막혔을 때: 인증 없는 단계 진단

소윤이 측 인증 조회는 실패한 상태다. 같은 인증 명령을 그대로 반복하거나 토큰을 새로 만들지 않는다. 연결된 Windows PC에서 아래 명령만 1회 실행한다.

```powershell
Set-Location -LiteralPath 'S:\AI\ai studio'
python -X utf8 -B tools/dev/supervisor_connection_check.py --diagnose
```

진단은 현재 실행 환경의 사용자 설정에 등록된 블록과 예상 블록을 비교하고, localhost의 GET health와 기존 확인 카드만 읽는다. **MCP 프로세스를 시작하지 않고 인증 파일·토큰을 읽지 않으며 인증된 도구도 호출하지 않는다.** `--owner-approved`를 함께 주어도 진단만 실행한다. 성공 출력은 `mode=unauthenticated-preflight`, `stage=preflight_complete`, `mcp_started=false`, `credential_read=false`, `authenticated_reads=0`이다. 인증 성공이나 연결 완료를 뜻하지 않는다.

실패 시 `stage`가 `local_paths`, `config_load`, `config_match`, `server_health`, `existing_probe` 중 하나다. `config_match`이면 `different_fields`에 알려진 항목 이름만, `additional_fields_present`에 알 수 없는 추가 항목 존재 여부만 표시한다. 현재 Python 버전과 CODEX_HOME 재정의 여부도 값·경로 없이 표시한다. 어떤 설정 값이나 알 수 없는 항목 이름도 출력하지 않는다. 예를 들어 `command`가 다르면 검사 실행기의 Python과 등록한 Python이 다른지 확인할 단서지만, 실제 소윤이 결과를 받기 전에는 그 원인으로 확정하지 않는다.

인증된 검사에는 추가로 `mcp_start`, `task_status`, `task_events`, `task_result`, `probe_state` 단계가 표시된다. 제어 흐름에 예상하지 못한 오류는 `unexpected`로 표시한다. 출력 집계만 전달하고, 설정·계정·권한을 바꾸거나 다른 실행기로 자동 재시도하지 않는다.

연결 전용 서버 재실행: `python -X utf8 -B tools/supervisor-host.py --port 8765`.
승인된 연결 재확인(모델 없음, 자신의 확인 카드만 제출·취소): `python -X utf8 -B tools/dev/supervisor_connection_check.py --owner-approved`.
연결 해제는 서버의 `soyun.enabled=false`와 로컬 `mcp_servers.ai_studio.enabled=false`로 할 수 있다. 토큰을 다른 PC에 복사하거나 채팅으로 전달하지 않는다.

## 소윤이에 전달할 요청문

```text
소윤이, 너를 AI Studio의 메인 감독으로 사용하려고 해.
인증 조회가 blocked / ValueError로 끝난 결과는 받았어. 같은 인증 호출은 반복하지 마.
연결한 내 Windows PC에서 다음 명령만 1회 실행해 줘.
Set-Location -LiteralPath 'S:\AI\ai studio'
python -X utf8 -B tools/dev/supervisor_connection_check.py --diagnose
이 프로그램의 내부 설정 비교·서버 GET health·기존 카드 확인만 허용해.
토큰·인증 파일을 읽거나 설정 내용을 직접 출력하지 마.
MCP 시작·인증된 도구 호출·모델 실행·새 작업 제출·취소·파일 수정은 하지 마.
반환된 집계 JSON만 보고하고, 실패하면 자동 재시도 없이 종료해 줘.
진단 성공을 인증 성공·직접 MCP 등록·실제 직원 작업 실행 성공으로 표시하지 마.
```

위 요청문은 아직 소윤이에 전송하지 않았다. 사용자 직접 전달용이며 실행 요청과 권한 승인을 구분한다.
