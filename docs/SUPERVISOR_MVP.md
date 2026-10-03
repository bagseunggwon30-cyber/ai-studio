# 외부 감독 MVP

2026-10-03. 작업 위치 `S:\AI\ai studio`, 기준 `origin/main`의 `23da5a2`, 작업 브랜치 `codex/external-supervisor-mvp`.

## 실행과 연결

기존 프로그램 실행 명령은 `python studio.py serve`다. 실제 회사의 자동 업무가 켜져 있으면 모델 사용량이 발생하므로, 이번 검증에서는 실제 회사를 가동하지 않았다.

사용량 없는 독립 데모:

```powershell
python tools/dev/supervisor_demo.py --port 8797
```

임시 회사와 임시 Git 제품을 만들고, 가짜 모델·실제 Git·실제 검증 명령으로 작업 하나를 결재 대기까지 보낸다. `http://127.0.0.1:8797/#view=board`에서 카드를 열고 **진행 단계·완료 근거**를 누른다. Ctrl+C로 끝낸다. 실제 `data/`, `projects/`, `worktrees/`를 테스트에 쓰지 않는다.

외부 감독 통로는 기존 직원용 MCP 장착과 별개다. `POST /supervisor/v1`은 프로젝트별 권한을 검사하고 기존 Engine에 위임한다. 같은 서버의 localhost 연결에서만 제공하며, LAN·Tailscale·휴대폰 경로에서는 제공하지 않는다. 기존 Host·Origin 검사와 CEO용 쓰기 토큰 검사는 유지한다.

`data/supervisors.json`이 없거나 enabled가 false이면 외부 통로는 닫혀 있다. 이번 작업은 **실제 연결용 토큰을 발급하거나 권한을 등록하지 않았다**. 예시는 `docs/supervisors.example.json`이다. 실제 연결 단계에서 CEO가 연결 대상, 프로젝트, read/write, 경로를 정하고 별도의 고엔트로피 토큰의 SHA256만 서버에 등록해야 한다. 클라이언트에는 토큰 원문이 환경변수 `STUDIO_SUPERVISOR_TOKEN`으로 필요하다. 원문을 저장소·명령줄·프롬프트에 넣지 않는다.

MCP 클라이언트가 stdio 서버를 등록할 수 있다면 다음 명령을 등록한다(환경변수는 클라이언트의 비밀 설정에서 제공).

```powershell
python "S:\AI\ai studio\tools\supervisor-mcp.py" --port 8765
```

도구는 `submit_task`, `task_status`, `task_events`, `task_result`, `task_artifact`, `cancel_task` 여섯 개다. 이 브리지는 HTTP 어댑터를 호출할 뿐, 회사 저장소를 직접 수정하거나 CEO 토큰을 읽지 않는다. 토큰을 CEO 대시보드 API에 대신 사용할 수 없다. 다만 같은 OS 사용자 권한으로 임의 코드를 실행할 수 있는 로컬 프로그램까지 격리하는 보안 장치는 아니다. 그런 상대에는 OS 수준의 별도 격리가 필요하다.

## 요청 예시

```json
{
  "operation": "submit",
  "project": "demo",
  "key": "write-answer-v1",
  "payload": {
    "kind": "build",
    "title": "정답 파일",
    "brief": "docs/answer.txt에 42를 저장한다",
    "allowed_paths": ["docs/**"],
    "resources": [],
    "requirements": [
      {"id":"A1", "text":"정답 파일과 검사 결과가 있어야 한다", "evidence":[
        {"type":"file", "path":"docs/answer.txt"},
        {"type":"test", "name":"answer_is_42"}
      ]}
    ]
  }
}
```

`demo`는 테스트 회사에서만 존재한다. 실제로는 `trusted/projects/`에 등록한 프로젝트 키를 쓴다. 허용 경로는 정확한 파일 또는 `폴더/**` 범위로 등록한다. API가 실행기, 샌드박스, 후보 SHA, 승인 상태를 입력으로 받지는 않는다.

| 작업 | 입력 | 결과 |
|---|---|---|
| submit | project, key, payload | task, replayed, approval_required |
| status | project, task | 상태, 단계, 차단 사유, 필요한 승인 |
| events | project, task, after=0 | 영속 작업 이벤트와 next 커서 |
| result | project, task | 검증 기준별 근거, 결과 파일 목록, 실행 기록 |
| artifact | project, task, path | 허용된 후보 결과 파일의 base64·SHA256, 최대 1MB |
| cancel | project, task | 해당 연결이 제출한 작업만 취소 |

같은 연결·프로젝트·키의 동일한 정규화 내용은 기존 작업을 반환한다. 내용이 다르면 HTTP 409다. 키 해시와 내용 해시는 **작업 카드와 같은 원자적 파일 쓰기**로 남으므로 작업 저장 직후 응답이 끊겨도 재전송 시 새 작업을 만들지 않는다. 기존 Store의 프로세스 잠금과 스레드 잠금을 사용한다. 작업 카드 자체를 관리자가 삭제하면 중복 방지 기록도 사라지므로, 이 MVP에서는 제출 기록이 있는 카드를 삭제하지 않는다.

외부 제출은 실행을 몰래 승인하지 않는다. 직접 작업은 준비, 기획은 기획 대기로 저장되고 CEO 실행 버튼이나 기존 자동 진행 설정을 따른다. 기획 결과의 작업 생성과 최종 병합은 기존 CEO 결재를 거친다. 기획에서 생성한 자식 작업도 원래 경로와 수용 기준을 유지한다.

## 단계 저장과 복구

`data/checkpoints/<task>.json`에 단계·입력 해시·실행 ID·결과·파일 해시·후보 SHA를 저장한다. 실행별 `receipt.json`과 기존 `meta.json`, 실행 인덱스도 남는다. 기획·구현·검증·리뷰 결과가 재사용 조건에 맞으면 해당 모델이나 검증 명령을 반복하지 않는다.

| 상황 | 저장 상태/처리 | 다음 행동 |
|---|---|---|
| 기획/읽기 전용 리뷰 중단 | interrupted | 입력·대상 확인 후 CEO 재시도 |
| 성공한 구현 결과 저장 후 중단 | complete | 결과 파일 해시가 같으면 모델 응답 재사용 |
| 후보와 QA 저장 후 중단 | candidate/qa | SHA·suite hash·스냅샷 해시 확인 후 다음 단계 |
| 커밋 저장 중 중단, 쓰기/외부 효과의 결과 불확실 | unknown_outcome | 결과 보존, 자동 재실행 금지, 사람이 실제 상태 확인 |
| 취소 | cancelled | 프로세스 종료와 작업 폴더 정리를 마친 후 실행 슬롯 해제 |
| 시간 초과 | timeout | 읽기 작업인지, 확인되지 않은 쓰기인지 구분 |
| 서버 종료/긴급 정지 | server_shutdown/emergency_stop | 중지 원인 보존; 다음 모델 단계 시작 금지 |

재시작할 때는 기존 fail-closed 규칙대로 활동 중 카드를 blocked로 만든다. 이후 CEO의 재시도는 검증된 경계에서 재개한다. `unknown_outcome`은 일반 재시도로 풀지 않는다. 외부 업로드·메시지 등의 완료를 원격 영수증으로 확인하는 범용 어댑터는 아직 없으므로 해당 경우에는 수동 확인이 필요하다. 완료된 후보에서 main이 바뀌었다면 결과가 그대로인지 먼저 확인하고, 명시적인 재시도에서만 새 기준으로 다시 만든다. 이전 QA·실행 기록은 남는다.

현재 작업·중단 원인·재개 안내·수용 기준별 근거를 작업 카드에 표시한다. 결재 창의 **진행 단계·완료 근거**로도 확인할 수 있다.

## 병렬화와 사용량

동시 작업 기본값은 2이며 `[limits] max_parallel`을 설정하더라도 1~3 범위다. 실행 요청과 선행 작업 조건을 지키며, 서로 다른 프로젝트나 겹치지 않는 경로의 격리 worktree는 동시에 진행할 수 있다. 경로 패턴이 복잡하면 보수적으로 충돌로 처리한다. 후보가 결재 대기 중이어도 충돌하는 경로는 기다린다.

같은 worktree, 공유 자원 이름, 직원/스킬/그림 설정을 바꾸는 작업은 직렬화한다. 장착한 외부 MCP와 내장 `team-memory`도 공유 쓰기 자원으로 본다. **기본 직원에게 공유 기억장이 장착돼 있으면 그 직원의 작업은 경로가 달라도 직렬화될 수 있다.** 병렬 작업이 필요할 때 CEO가 공유 쓰기 도구 장착을 해제하거나 서로 다른 자원으로 구성해야 한다. 이번 작업은 실제 회사의 MCP 장착 설정을 바꾸지 않았다.

Git worktree 등록·정리와 병합은 프로젝트 잠금을 사용한다. 작업 종료, 실패, 취소 시 finally에서 실행 슬롯·사용량 예약을 정리한다. 결과 불확실로 차단된 공유 쓰기는 관련 작업을 계속 대기시키며 독립 자원은 진행할 수 있다. 하루 실행 수·시간은 실행 중 예약분까지 계산한다.

## 실행기와 모델 추적

Claude는 기본 사용 불가로 취급하고, 설치나 로그인 응답을 기다리지 않고 Codex의 별도 읽기 전용 리뷰로 대체한다. 기존 Claude 코드는 보존하며 `[runtimes.claude] enabled=true`는 CEO가 향후 실제 사용 가능할 때만 설정한다. 같은 Codex를 쓰는 리뷰를 교차 공급자 검증이라고 표시하지 않는다.

실행 기록은 requested_provider/requested_model, actual_runtime/runtime_version, provider_model/model_identity, usage, duration_s, fallback/fallback_reason을 분리한다. provider_model은 공급자 응답의 메타데이터에서만 받는다. 설정이나 모델 자신의 글로 이름을 확정하지 않는다. 모르는 토큰·비용은 null/확인 불가다. 가짜 실행기의 확인된 0과 실제 모델의 미확인을 구분한다.

실제 확인(2026-10-03): Codex CLI 0.160.0, ChatGPT 로그인 확인. CEO가 승인한 1회의 읽기 전용 연결 시험 성공(9초, 입력 17002·출력 15토큰). 응답의 정확한 모델 ID는 없어 확인 불가. `verification/codex-connection.json` 참조. 이 시험은 실제 모델의 구현·QA·리뷰 전체 흐름을 증명하지 않는다.

후속 작업에서 Grok CLI 1.0.41의 실제 도움말·설정 검사·모델 목록·기존 grok.com 로그인을 확인했다. CEO가 승인한 총 1회는 `grok-4.7`을 요청한 읽기 전용 텍스트 리뷰로 사용했다. 응답 성공, 47.2초, 입력 5070·출력 556토큰이며 응답에 정확한 모델 ID가 없어 확인 불가다. 기획·구현은 가짜 모델, Git·QA·MCP 클라이언트는 실제 실행이다. [실행 근거](verification/supervisor-grok-review-real.json). 유료 API 전환과 새 구독은 없다. Grok 이미지 생성은 이번에 실행하지 않았다.

`GrokTextRuntime`은 실제 호출 어댑터다. CEO의 이번 제한적 확장 요청에 따라 AGENTS.md 8번을 함께 정리했다. 매 실행에서 비공개 임시 GROK_HOME·작업 입력 폴더를 사용하고 기존 로그인 파일의 임시 하드 링크만 연결한다(내용을 직접 읽거나 복사하지 않음). MCP 허용 목록을 빈 native 정책으로 고정하고 managed MCP·호환 MCP·훅·플러그인·LSP·프로젝트 지침·개인 스킬이 없다는 실제 `inspect --json` 결과를 확인한다. 발견한 개인 스킬은 이름만 확인해 모두 비활성화한다. 도구 allowlist만으로 남는 MCP 메타 도구도 명시적으로 차단하고 `--deny * --permission-mode dontAsk --no-subagents --disable-web-search --max-turns 1`을 적용한다. API 키 인증과 상속 모델 API 키 환경변수를 차단한다. 검사 형식이 바뀌거나 차단을 확인하지 못하면 생성 호출 전에 중단한다.

코드·셸·임의 파일 쓰기·직원 MCP·서브에이전트 권한은 없다. 입력에 포함된 텍스트만 분석하므로 Grok 자체의 실시간 웹 조사·파일 검색은 제공하지 않는다. 필요한 출처는 별도로 수집·검증해 입력에 넣는다. Windows의 OS 파일 샌드박스를 보장한다는 뜻은 아니며, CLI 도구 없음과 상속 실행 표면 없음이 경계다. 정상 종료·취소·시간 초과 시 로그인 링크와 임시 설정을 지운다. 감독 프로세스가 강제 종료되면 원래 로그인 파일의 ACL을 유지한 임시 링크가 남을 수 있어 해당 임시 폴더 확인이 필요하다. 브라우저 채팅 자동화와 새 API 키는 쓰지 않는다.

설정 화면에서 설치된 CLI가 반환한 모델만 선택하고 Grok 텍스트는 읽기 전용 기획·리뷰 역할에만 끼울 수 있다. 파일을 쓰는 리서치·개발 역할에는 끼울 수 없다. 이 경로에는 장착한 team-memory도 붙지 않으므로 그 도구의 공유 쓰기 잠금을 예약하지 않는다. 명시적으로 요청한 공유 자원 잠금은 유지한다.

공식 근거: [headless 호출](https://docs.x.ai/build/cli/headless-scripting), [설정](https://docs.x.ai/build/settings/reference), [권한](https://docs.x.ai/build/features/permissions), [샌드박스](https://docs.x.ai/build/features/sandbox), [MCP](https://docs.x.ai/build/features/mcp-servers). 설치된 CLI의 번들 설명서와 도움말·검사 응답을 우선 확인했다.

## 완료 근거

외부 제출 작업의 requirements에는 고유 ID, 기준 문장, test/file/screenshot/source 참조를 둔다. test는 실제 QA 테스트 이름과 결과, file은 후보 스냅샷의 존재·내용, screenshot은 파일 형식과 존재, source는 감독 프로그램이 직접 수집한 출처 영수증과 본문 해시를 확인한다. 스크린샷이 있다는 것만으로 화면 의미까지 맞다고 판정하지는 않는다. 링크 문자열만 적거나 모델이 확인했다고 말한 것은 source 근거가 아니다.

출처 캡처는 CEO 토큰이 필요한 `POST /api/tasks/<task>/source`에 `{id, url}`을 보낸다. 기존 공개 웹 읽기 제한(로컬·사설망 차단)을 재사용한다. 본문은 `data/sources/<task>/<id>.txt`, 영수증은 같은 이름의 JSON이다. 외부 감독 토큰으로 이 CEO 경로를 호출할 수 없다. 수용 기준의 문장과 출처 ID 연결은 결과 API에 보존된다. 출처에 적힌 주장이 참인지까지 자동으로 입증하는 것은 아니다.

후보 SHA·현재 suite hash·QA 영수증·스냅샷 내용이 바뀌면 기존 근거는 무효다. 기준 근거가 누락됐거나 리뷰가 불가하면 외부 제출 작업은 결재 대기까지 가지 못한다. 승인 시에도 다시 검사한다. 이전 방식으로 만든 내부 카드에는 근거 상태를 표시하되 기존 CEO 검토 흐름을 유지한다.

## 검증 경계와 남은 연결 단계

- API/stdio 왕복, 중복·충돌·응답 직전 중단, 기획 승인 경계, 읽기 권한, 취소 소유권, 결과 파일 접근을 임시 회사에서 검사한다.
- 실제 Git·QA 명령과 가짜 모델로 재시작, 단계 재사용, 변경된 suite, 근거 누락, 병렬 실행, 충돌 대기, 예외 정리를 검사한다.
- 모바일·기존 주요 흐름은 기존 회귀 테스트에 포함한다. 실제 휴대폰/LAN/Tailscale 시험은 실행 안 함.
- 초기 Codex 읽기 전용 1회와 이번 Grok 읽기 전용 리뷰 1회는 별도 기록이다. 이번에 실제 Codex 모델 기획·구현은 실행하지 않았다. 모델 ID는 응답에서 확인되지 않았다. Codex의 실제 MCP 클라이언트 왕복은 성공했지만 임시 회사이며, 메인 비서 GPT dots 소윤이·실제 회사는 미연결이다. [소윤이 연결 단계](SOYUN_CONNECT.md).
- 현재 클라이언트가 stdio MCP를 등록할 수 있는지 먼저 확인하고, CEO가 프로젝트 권한·토큰 등록을 승인한 뒤 등록된 도구로 왕복 시험해야 한다. 이 저장소 업로드는 서비스 배포나 접속 권한 부여가 아니다.

`supervisor-harness.json`은 외부 어댑터 경계의 상태·위험·예산 계약이다. 브라우저/데스크톱 입력과 일반 외부 부작용을 제공하지 않으므로 해당 영수증/격리 규칙은 향후 기능을 열 때의 금지 경계이며, 현재 그런 연결이 구현됐다는 주장이 아니다. 실제 태스크의 done 전이는 기존 Engine.approve가 담당한다.

HTTP 응답은 `schema: studio.supervisor-result/v1`, `status`, `data`, `errors`, `elapsed_ms`를 담고 최대 1.5MB다. MCP는 data를 도구 결과로 제공하며 60,000자를 넘으면 명시적으로 실패한다(잘린 JSON을 반환하지 않음). 큰 파일은 HTTP artifact 조회를 사용한다(파일 1MB 상한).

## 변경 파일과 요구사항별 검사

| 범위 | 구현 파일 | 대표 자동 검사 (가짜 모델·실제 파일/Git/HTTP) |
|---|---|---|
| 접수·읽기·취소·권한·감사·영속 중복 방지 | studio/supervisor.py, studio/supervisor_mcp.py, studio/server.py, tools/supervisor-mcp.py | test_idempotency_concurrent_restart_conflict, test_crash_after_atomic_task_before_response, test_scope_and_approval_cannot_be_bypassed, test_http_and_stdio_bridge |
| 완료 단계 재사용·불확실한 쓰기 차단 | studio/checkpoints.py, studio/engine.py | test_write_disconnect_never_replayed_or_discarded, test_restart_after_completed_write_receipt_reuses_model, test_restart_after_qa_reuses_build_and_verification, test_resumed_review_changes_continue_to_next_build |
| 제한된 병렬화·공유 자원·종료 정리 | studio/scheduler.py, studio/config.py, studio/engine.py | test_independent_parallel_conflicts_wait_cancel_releases, test_completed_worker_releases_mcp_but_candidate_keeps_file_scope, tests/test_lifecycle.py |
| Claude 없는 흐름·실행기/모델 기록 | studio/runtimes.py, studio/ai.py, studio/doctor.py | test_claude_free_pipeline_result_and_missing_evidence, test_grok_text_is_fail_closed_and_never_infers_requested_model |
| 근거 검사·변경 시 무효화 | studio/evidence.py, studio/engine.py | test_missing_criterion_blocks_and_cancel_ownership, test_source_receipt_and_tampered_snapshot, test_changed_suite_invalidates_cached_qa |
| PC/휴대폰 실행 버튼·단계/근거 화면 | ui/popups.js, ui/board.js, ui/m.js | tests/test_server.py, tests/test_remote.py, board_sim.js, 브라우저의 임시 회사 확인 |

새 기능의 자동 검사는 tests/test_supervisor.py에 있다. 기존 tests/test_ai.py·test_engine.py·test_server.py는 Claude 비활성 기본값과 미확인 사용량 표기를 반영했다. board_sim.js의 완료 카드 기대값은 기존 제품 코드의 '최근 5개'와 어긋나 있던 8개를 5개로 바로잡았다. 제품의 카드 수는 바꾸지 않았다.

전체 검사는 `python -m unittest discover -s tests -t .`, 진행판 계산은 `node tools/dev/board_sim.js`, 읽기 전용 설치 점검은 `python studio.py doctor`로 실행한다. 후속 작업은 `python -X utf8 -B tools/dev/regression.py`가 전체 unittest·진행판·JS 문법을 실행하고 커밋·코드 해시·개별 생략/실패 ID만 [최종 후속 검사](verification/followup-regression.json)에 남긴다. [초기 MVP 보고](verification/mvp-report.md)는 과거 결과다. raw 로그는 로컬에만 남긴다. GitHub Actions는 실제 모델·로그인·비밀정보 없이 같은 회귀 검사와 가짜 모델 stdio 왕복을 실행한다. Godot이 없는 CI 환경의 검사는 생략으로 기록하며 통과로 세지 않는다.

## 실제 상태와 설계 문서의 대응

`supervisor-harness.json`은 정형 설계 검토 문서이며 런타임 설정 파일이 아니다. 상태 이름과 영수증 필드가 API와 그대로 일치하는 전체 구현 명세로 사용하면 안 된다. 실제 전이는 아래와 같고 API 응답 계약은 이 문서의 앞부분을 따른다.

| 실제 카드 전이 | 조건 |
|---|---|
| queued → running | 기획 실행 조건과 CEO 실행/자동 진행 설정 충족 |
| ready → running | 의존 작업 완료, 자원 확보, 사용량 예약 |
| running → checking | 후보 SHA 저장 |
| checking → running | QA/리뷰 수정 요청, 남은 시도 있음 |
| checking → awaiting_approval | 현재 후보 근거 확인, 외부 작업은 리뷰 승인도 필요 |
| awaiting_approval → done | 기존 Engine.approve의 CEO 승인, 현재 SHA·suite·근거 재검사 |
| 활동 중 → blocked | 재시작·실패·불확실한 효과; 원인 및 다음 행동 저장 |
| blocked → queued/ready | CEO 재시도; 불확실한 쓰기는 거절 |
| 미완료 → cancelled | 취소 후 하위 프로세스·작업 폴더·예약 정리 |

정형 설계의 observation_id/nonce/단일 사용 승인 영수증과 데스크톱 격리는 향후 일반 외부 효과 연결을 위한 요구사항이며 현재 API가 제공하는 기능은 아니다. 현재 작업 입력은 실행 프롬프트와 input_digest, 실행 ID는 run_id, 예산은 실행 기록과 활성 예약으로 확인한다. 해당 JSON의 검증 통과는 설계 형식 검사이며 기능 시험을 대체하지 않는다.
