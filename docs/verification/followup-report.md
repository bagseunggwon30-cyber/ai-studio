# AI Studio 후속 구현·검증 (2026-10-03)

메인 감독은 **GPT dots 소윤이**이며 AI Studio는 작업 실행·기록·복구·검증을 담당한다. Codex는 기존 ChatGPT 로그인, Grok은 기존 grok.com 로그인을 사용한다. 새 모델 API 키·구독·배포·main 병합은 하지 않았다. **소윤이의 MCP 등록 및 실제 회사 연결은 미완료**다.

## 구현한 기능

- Grok 텍스트 CLI 호출: 매 실행마다 개인 설정·MCP·훅·플러그인·LSP·상속 지침·스킬을 차단하고, 입력 텍스트만 전달한다. 쓰기·셸·서브에이전트·직원 MCP·웹 검색은 허용하지 않는다. 검사 계약이 바뀌면 호출 전에 중단한다.
- 기존 로그인 파일을 임시 하드 링크로 재사용한다. 값을 직접 읽거나 복사하지 않으며 정상·취소·시간 초과 뒤 연결을 지운다. Windows OS 샌드박스를 보장한다는 뜻은 아니다. 감독 프로세스 강제 종료 뒤 비공개 임시 연결이 남을 수 있다는 제한은 유지한다.
- 설치된 Grok CLI가 반환한 점이 포함된 모델 ID를 선택 화면에 표시한다. 읽기 전용 역할에만 선택할 수 있다. 첫 모델 목록 로딩과 미저장 선택 유지 문제도 고쳤다.
- 요청 공급자/모델, 실제 실행기/버전, 응답 모델, 사용량, 대체 실행과 실패 원인을 구분한다. Grok 로그인 실패를 분류하며 CLI 상세 문구는 화면에 노출하지 않는다. 직원에게 외부 감독 토큰을 환경변수로 상속하지 않는다.
- 기존 API·체크포인트·병렬 스케줄러를 재사용한다. 제한된 Grok 텍스트 역할에는 사용할 수 없는 employee MCP의 잠금을 예약하지 않고, 명시적인 공유 자원은 유지한다.
- 모델 호출 없는 전체 회귀 검사·stdio 왕복 검사를 GitHub Actions에 추가했다. 공개 근거에는 횟수·검사 ID·코드 해시만 남기고 raw 로그는 올리지 않는다.

## 실제로 실행한 확인

| 확인 | 실행 범위와 근거 |
|---|---|
| Grok 텍스트 리뷰 | 사용자가 허용한 총 **1회**. 임시 회사, 요청 `grok-4.7`, 기존 구독 로그인, CLI 1.0.41. 47.2초, 입력 5070·출력 556토큰. 응답 모델 ID와 비용은 확인 불가. [실행 기록](supervisor-grok-review-real.json) |
| 계획·구현·QA·리뷰·결과·취소 | 기획·구현은 가짜 모델, Git·QA는 실제. QA 이후 중단·재시작에서 구현/QA 재사용, 실제 Grok 리뷰 1회, 근거 변조 후 결재 차단과 취소 정리 확인. 위 기록 참조 |
| 실제 MCP 클라이언트 | 설치된 Codex app-server에서 도구 6개 등록 및 호출. 임시 회사, Codex 모델 turn 0회. [최종 가짜 모델 왕복](supervisor-codex-client-final-fake.json) |
| stdio 왕복 | 별도 stdio 클라이언트로 도구 6개 호출, 가짜 모델만 사용. [실행 기록](supervisor-stdio-final-fake.json) |
| UI | 임시 회사의 실제 브라우저에서 Grok 4.7 선택, 개발 역할 차단, Claude 비활성, 초기 로딩 갱신, 미저장 선택 유지 확인. [기획 화면](followup-grok-producer.png), [개발 화면](followup-grok-builder.png) |

실제 Grok 호출은 구현 중의 1회이고 이후 마지막 실패 분류·환경변수·추적 보완 뒤에는 추가 호출하지 않았다. 해당 보완은 가짜 CLI·가짜 모델로 검사했다. 실제 실행 기록의 adapter 해시와 코드 상태를 보존했다. 원래 실행 기록에서 Grok 공급자/실행기 별칭 때문에 잘못 표시된 `fallback=true`는 기록 주석으로 설명하고 원본 필드는 유지한다. 최종 코드는 이 문제와 실제 대체 실행의 원인 기록을 수정했다.

## 아직 실제 실행하지 않은 기능과 연결

Grok 기획 보조·입력 텍스트 조사와 실제 Codex 기획·구현 전체 과정은 이번 실제 모델 검사에 포함하지 않았다. Claude 없는 전체 흐름은 가짜 실행기로 확인했으며 실제 모델 전체 흐름과 같은 의미가 아니다. Grok 자체의 웹 조사·파일 검색은 이번 범위에 없다. 필요한 출처는 기존 수집·검증 경로로 따로 제공해야 한다.

사용자는 소윤이의 PC 접근 허용을 확인했다. 이번 작업에서 dots 프로필의 연결 상태를 직접 조회하거나 소윤이에 메시지를 보내지는 않았다. 로컬 Codex MCP 클라이언트 성공은 소윤이 클라우드의 도구 등록 성공을 증명하지 않는다.

실제 회사의 접근 권한·토큰·직원 MCP 설정은 보존했다. 다음 제안은 소윤이의 로컬 작업, `studio-docs` 하나, `reports/connection-check/**` 읽기/제출/자신의 작업 취소 범위다. 실행·기획 결재·최종 병합 권한은 주지 않는다. 실제 권한 설정·비밀 토큰 전달·소윤이 도구 등록 확인은 사용자 승인 후 진행해야 한다. [구체적인 연결 방법과 전달문](../SOYUN_CONNECT.md).

실제 회사의 기본 team-memory는 여러 작업을 직렬화할 수 있다. 병렬 검사는 임시 환경의 자원만 분리했다. 실제 회사에서 병렬화할 때는 공유 쓰기 도구를 어느 직원에게 줄지 사용자가 선택해야 한다. 실제 휴대폰/LAN/Tailscale 동작은 실행 안 함.

## 최종 전체 검사

마지막 코드 커밋은 `09eb901088ed50135fc8e098a78f2a1d8cb81c6d`다. 다음 명령의 별도 [최종 JSON](followup-regression.json)에 전체·통과·생략·실패, 검사 중 코드 불변 여부와 해시를 기록한다. 실행 중 중단한 검사와 이전 MVP 검사 수는 합산하지 않는다.

```powershell
python -X utf8 -B tools/dev/regression.py
python -X utf8 -B tools/dev/supervisor_smoke.py --client stdio
python -X utf8 -B tools/dev/supervisor_smoke.py --client codex
```

위 재현 명령은 모델 생성 호출을 하지 않는다. 실제 모델 수동 검사는 별도 승인이 필요하다. `regression.py`는 전체 unittest, 진행판 12개, UI JavaScript 문법을 실행한다. GitHub Actions에 Godot이 없으면 관련 검사는 생략으로 기록되며 통과로 세지 않는다. 세부 최종 결과는 아래에 확정한다.

| 최종 검사 | 전체 | 통과 | 생략 | 실패/오류 |
|---|---:|---:|---:|---:|
| 이 PC 전체 Python, Python 3.12 | 271 | 270 | 1 | 0 |
| GitHub Actions Windows 전체 Python, Python 3.12.10 | 271 | 251 | 20 | 0 |
| 진행판 (각 환경에서 별도 실행) | 12 | 12 | 0 | 0 |
| UI JavaScript 문법 (각 환경에서 별도 실행) | 10 파일 | 10 파일 | 0 | 0 |

PC 생략 1개는 Windows에서 실행할 수 없는 POSIX 프로세스 그룹 검사다. CI는 여기에 Godot 관련 19개를 추가로 생략했다. 환경별 결과를 합산하지 않는다. PC 전체 실행은 636.5초, CI 전체 실행은 205.5초이며 두 실행 모두 검사 중 소스 불변을 확인했다. [CI 검사](https://github.com/bagseunggwon30-cyber/ai-studio/actions/runs/37112529851), [내려받은 CI 근거](ci-final/regression.json), [CI stdio 왕복](ci-final/supervisor-fake.json). 각 JSON에 해당 환경의 파일 해시를 별도로 기록했다.

임시 브라우저·서버는 종료했다. 자동 승인 검토가 임시 검사 폴더 2개의 삭제 명령을 정책상 차단했고 상세 사유는 제공되지 않았다. 삭제를 재시도하지 않았으며, 정상 종료로 정리된 것을 제외하고 가짜 회사 임시 폴더 1개가 남았다. 실제 회사·프로젝트 폴더 삭제는 요청하거나 실행하지 않았다.

## 주요 변경 파일

- 실행: `studio/grok_text.py`, `studio/runtimes.py`, `studio/engine.py`, `studio/ai.py`, `studio/doctor.py`, `studio/model.py`, `studio/util.py`.
- 화면·정책: `ui/popups.js`, `AGENTS.md`.
- 검사: `tests/test_grok_text.py`, `tests/test_ai.py`, `tests/test_supervisor.py`, `tests/test_util.py`.
- 실제 클라이언트/재현/CI: `tools/dev/codex_supervisor_client.py`, `tools/dev/supervisor_smoke.py`, `tools/dev/regression.py`, `.github/workflows/regression.yml`.
- 인수인계·연결 안내·실행 근거: `docs/HANDOFF.md`, `docs/SUPERVISOR_MVP.md`, `docs/SOYUN_CONNECT.md`, 이 보고서와 연결된 JSON/PNG.

코드 변경은 `36caef1`, `d4c9090`, `daff6e0`, `077d200`, `09eb901`이며 전체 검증 이후 문서·근거만 별도 커밋한다. main은 병합하지 않는다.
