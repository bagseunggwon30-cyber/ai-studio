# GPT dots 소윤이를 메인 감독으로 연결하기

소윤이는 지시를 정리하고 AI Studio에 제출한 뒤 상태·결과·근거를 확인하는 메인 감독이다. AI Studio는 작업 저장·복구·병렬 처리·권한·검증을 담당한다. Codex는 기존 ChatGPT 로그인으로 코드 작업을, Grok은 기존 grok.com 로그인으로 입력 텍스트의 조사·기획 보조·읽기 전용 리뷰를 맡는다. Claude는 필수가 아니다. 모델 API 키나 새 구독으로 전환하지 않는다.

## 현재 확인한 것

- Grok CLI 1.0.41로 기존 로그인 기반 텍스트 리뷰 1회 성공. 요청 모델은 `grok-4.7`; 응답의 정확한 모델 ID는 확인 불가.
- 설치된 Codex app-server의 실제 MCP 클라이언트가 도구 6개를 등록하고 임시 회사에 왕복 호출했다. Codex 모델 호출은 0회. 이 검사는 소윤이의 도구 등록을 증명하지 않는다.
- 사용자가 소윤이에 이 PC를 아직 연결하지 않았다고 확인했다. 현재 소윤이·실제 회사 연결은 **미완료**이며 실제 회사의 권한·토큰·설정은 바꾸지 않았다.

## 1. 이 PC를 소윤이에 연결

이 PC의 ChatGPT 데스크톱 앱에서 소윤이 프로필 → **Computers / 컴퓨터** → **Your computer / 내 컴퓨터** → **Allow access / 접근 허용**을 선택하고 확인 창에서 다시 허용한다. PC를 켜 두고 ChatGPT 앱을 열어 둬야 한다. Codex 컴퓨터 연결이나 Work Sync와는 별도 권한이다.

이 기능은 로컬 파일·코드·앱을 사용하는 접근 권한이다. AI Studio 프로젝트별 범위를 자동으로 설정해 주는 것은 아니다. 소윤이는 연결된 PC에 로컬 Work/Codex 작업을 만들 수 있다. 클라우드에 있는 소윤이가 이 PC의 `127.0.0.1`이나 stdio 서버를 바로 사용할 수 있다고 가정하지 않는다.

공식 안내: [dots 컴퓨터 연결](https://learn.chatgpt.com/docs/dots/computers-and-apps), [dots 권한 관리](https://learn.chatgpt.com/docs/dots/controls).

## 2. 연결할 대상과 최소 범위 — 승인 전 제안

| 항목 | 제안 |
|---|---|
| 메인 감독 | GPT dots 소윤이 |
| 로컬 실행 경로 | 소윤이가 위 PC의 로컬 Work/Codex 작업을 통해 등록된 감독 MCP를 호출 |
| 허용 프로젝트 | 기존 `studio-docs` 하나 |
| 허용 결과 경로 | `reports/connection-check/**` |
| 읽기 | 해당 연결이 접근 가능한 작업 상태·이벤트·결과·허용 파일 |
| 쓰기 | 위 범위의 작업 제출, 자신의 미완료 작업 취소 |
| 실행·승인 | 기존 CEO 실행·기획 결재·최종 병합 경계 유지; MCP에는 승인 도구 없음 |
| 모델 검증 | 새 승인 전 실제 모델 호출 0회 |

실제 회사의 `data/supervisors.json`을 켜고 프로젝트 쓰기 권한을 주는 단계는 사용자의 별도 승인이 필요하다. 위 제안은 아직 적용되지 않았다. 구독 로그인과 별개로, 로컬 감독 API를 보호하는 연결 토큰이 필요하다. 이것은 유료 모델 API 키가 아니다. 서버에는 토큰의 SHA256만 저장하고 클라이언트의 비밀 환경에 원문을 전달한다. 채팅·프롬프트·명령줄·공개 설정·로그에 원문을 쓰지 않는다.

## 3. MCP 등록과 소윤이의 실제 도구 확인

현재 설치된 Codex는 로컬 stdio MCP를 지원하며 아래는 비밀값 없는 **등록 예시**다. 실제 로컬 작업의 MCP 설정에 등록하는 단계는 별도다. Python 실행 경로와 포트는 실제 실행 환경에서 확인한다. 등록 후 도구 목록에 아래 6개가 보이는지 확인한다.

```toml
[mcp_servers.ai_studio]
command = "python"
args = ["-X", "utf8", "S:\\AI\\ai studio\\tools\\supervisor-mcp.py", "--port", "8765"]
env_vars = ["STUDIO_SUPERVISOR_TOKEN"]
startup_timeout_sec = 20
tool_timeout_sec = 20
```

도구: `submit_task`, `task_status`, `task_events`, `task_result`, `task_artifact`, `cancel_task`.

공식 [MCP 안내](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)의 로컬 클라이언트 설정이 소윤이 클라우드에 자동 상속된다는 보장은 없다. 연결된 로컬 작업에서 도구를 확인하고 왕복 호출한 뒤에만 소윤이 연결 완료라고 보고한다. 로컬 작업에서 등록이 불가능하면 그 단계가 미완료다. API 키가 필요한 터널이나 서버 공개로 우회하지 않는다.

## 소윤이에 전달할 요청문

```text
소윤이, 너를 AI Studio의 메인 감독으로 사용하려고 해.
연결한 내 PC의 S:\AI\ai studio에 있는 docs/SOYUN_CONNECT.md와 docs/SUPERVISOR_MVP.md를 먼저 읽어 줘.
로컬 작업에서 ai_studio MCP 도구 6개가 실제로 보이는지 확인하고, 없으면 연결되지 않았다고 알려 줘.
클라우드의 localhost로 접근하거나 새 API 키·구독·터널을 만들지 마.
아직 실제 회사에 대한 접근 권한 설정은 승인 대기야. 토큰을 대화나 프롬프트에 넣지 마.
권한이 승인되고 도구 등록이 확인되면 허용된 studio-docs의 reports/connection-check/** 범위에서만
작업 제출·상태·이벤트·결과·파일·취소를 확인해 줘. 같은 요청 키는 재사용해 중복 제출을 막아 줘.
실행, 기획 결재, 최종 병합은 사람의 승인을 유지하고 차단 사유와 필요한 조치를 알려 줘.
실제 모델 호출이나 구독 사용량이 발생하기 전 목적·횟수·경로를 설명하고 승인을 받아 줘.
```

위 요청문은 아직 소윤이에 전송하지 않았다. 사용자 직접 전달용이며 실행 요청과 권한 승인을 구분한다.
