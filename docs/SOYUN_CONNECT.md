# GPT dots 소윤이를 메인 감독으로 연결하기

소윤이는 지시를 정리하고 AI Studio에 제출한 뒤 상태·결과·근거를 확인하는 메인 감독이다. AI Studio는 작업 저장·복구·병렬 처리·권한·검증을 담당한다. Codex는 기존 ChatGPT 로그인으로 코드 작업을, Grok은 기존 grok.com 로그인으로 입력 텍스트의 조사·기획 보조·읽기 전용 리뷰를 맡는다. Claude는 필수가 아니다. 모델 API 키나 새 구독으로 전환하지 않는다.

## 현재 확인한 것

- Grok CLI 1.0.41로 기존 로그인 기반 텍스트 리뷰 1회 성공. 요청 모델은 `grok-4.7`; 응답의 정확한 모델 ID는 확인 불가.
- 설치된 Codex app-server의 실제 MCP 클라이언트가 도구 6개를 등록하고 임시 회사에 왕복 호출했다. Codex 모델 호출은 0회. 이 검사는 소윤이의 도구 등록을 증명하지 않는다.
- 사용자가 이 PC의 접근 허용을 확인했고, 2026-10-03에 아래 로컬 MCP·토큰·프로젝트 범위 적용을 승인했다. 로컬 MCP 등록과 실제 회사 API 왕복은 완료했다. **소윤이 클라우드에서 직접 도구를 호출했는지는 아직 확인하지 않았다.**

## 1. 이 PC를 소윤이에 연결

이 PC의 ChatGPT 데스크톱 앱에서 소윤이 프로필 → **Computers / 컴퓨터** → **Your computer / 내 컴퓨터** → **Allow access / 접근 허용**을 선택하고 확인 창에서 다시 허용한다. PC를 켜 두고 ChatGPT 앱을 열어 둬야 한다. Codex 컴퓨터 연결이나 Work Sync와는 별도 권한이다.

이 기능은 로컬 파일·코드·앱을 사용하는 접근 권한이다. AI Studio 프로젝트별 범위를 자동으로 설정해 주는 것은 아니다. 소윤이는 연결된 PC에 로컬 Work/Codex 작업을 만들 수 있다. 클라우드에 있는 소윤이가 이 PC의 `127.0.0.1`이나 stdio 서버를 바로 사용할 수 있다고 가정하지 않는다.

공식 안내: [dots 컴퓨터 연결](https://learn.chatgpt.com/docs/dots/computers-and-apps), [dots 권한 관리](https://learn.chatgpt.com/docs/dots/controls).

## 2. 승인받아 적용한 연결 범위 (2026-10-03)

| 항목 | 적용 범위 |
|---|---|
| 메인 감독 | GPT dots 소윤이 |
| 로컬 실행 경로 | 소윤이가 위 PC의 로컬 Work/Codex 작업을 통해 등록된 감독 MCP를 호출 |
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

소윤이가 이미 열어 둔 작업에는 새 도구가 바로 반영되지 않을 수 있다. **이 PC를 사용하는 새 로컬 Codex 작업에서 `ai_studio`를 확인**한다. 소윤이가 클라우드에서 로컬 stdio를 직접 호출한다고 가정하지 않는다. 새 모델을 실행하거나 소윤이에 메시지를 보내는 검사는 이번에 수행하지 않았다.

연결 전용 서버 재실행: `python -X utf8 -B tools/supervisor-host.py --port 8765`.
승인된 연결 재확인(모델 없음, 자신의 확인 카드만 제출·취소): `python -X utf8 -B tools/dev/supervisor_connection_check.py --owner-approved`.
연결 해제는 서버의 `soyun.enabled=false`와 로컬 `mcp_servers.ai_studio.enabled=false`로 할 수 있다. 토큰을 다른 PC에 복사하거나 채팅으로 전달하지 않는다.

## 소윤이에 전달할 요청문

```text
소윤이, 너를 AI Studio의 메인 감독으로 사용하려고 해.
연결한 내 PC의 S:\AI\ai studio에 있는 docs/SOYUN_CONNECT.md와 docs/SUPERVISOR_MVP.md를 먼저 읽어 줘.
로컬 작업에서 ai_studio MCP 도구 6개가 실제로 보이는지 확인하고, 없으면 연결되지 않았다고 알려 줘.
클라우드의 localhost로 접근하거나 새 API 키·구독·터널을 만들지 마.
실제 회사에 대한 제한된 접근 권한과 로컬 ai_studio MCP 등록은 승인받아 적용됐어.
토큰은 Windows 사용자 암호화 파일에 있으니 값이나 파일 내용을 읽어 대화·프롬프트에 넣지 마.
로컬 작업에서 도구를 확인한 다음 허용된 studio-docs의 reports/connection-check/** 범위에서만
작업 제출·상태·이벤트·결과·파일·취소를 확인해 줘. 같은 요청 키는 재사용해 중복 제출을 막아 줘.
실행, 기획 결재, 최종 병합은 사람의 승인을 유지하고 차단 사유와 필요한 조치를 알려 줘.
실제 모델 호출이나 구독 사용량이 발생하기 전 목적·횟수·경로를 설명하고 승인을 받아 줘.
현재 서버는 연결 전용이므로 작업을 실행하거나 결과 파일이 생성됐다고 주장하지 마.
```

위 요청문은 아직 소윤이에 전송하지 않았다. 사용자 직접 전달용이며 실행 요청과 권한 승인을 구분한다.
