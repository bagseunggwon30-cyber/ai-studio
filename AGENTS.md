# AI Studio 감독 프로그램 — 작업자 규칙

이 문서는 **감독 프로그램 자체**(`studio/`, `ui/`, `tests/`)를 고치는 에이전트를 위한 것입니다.
제품 작업 규칙은 `projects/<이름>/AGENTS.md`, 회사 규칙은 `company/`에 있습니다.

**이어서 작업하는 세션은 먼저 [docs/HANDOFF.md](docs/HANDOFF.md)를 읽는다** (진행 상황, 남은 일, 지킬 것, 도구).

## 사용자에게 설명하고 실제 작업으로 이어가기 (CEO 지시 2026-10-04)

- 프로그램의 문제·오류·스크린샷·개선 요청에는 지식 설명이나 사과만 하고 끝내지 않는다. 제품 개선 맥락을 이어서 파악한다.
- 원인 설명 다음에는 수정할 부분, 구체적인 구현 방안, 검증 방법을 함께 제시한다. 여러 방안이 있으면 권장 방안과 이유를 설명한다.
- 이미 승인된 범위의 수정은 실제로 구현하고 검증까지 진행한다. 계획을 말하거나 계속할지 묻는 것으로 작업을 대신하지 않는다.
- 승인·환경 제한으로 막히면 무엇이 필요한지와 실행 가능한 대안을 구체적으로 안내하고, 독립적으로 진행할 수 있는 작업은 계속한다. 최종 보고는 구현·검증 결과와 남은 실제 제약을 구분한다.

## 절대 바꾸지 않는 것 (CEO 승인 없이)

- `trusted/` — 검증 명령과 수용 테스트
- `company/` — 회사 규칙, 역할, 결정 기록
- `studio.toml` — 회사 설정
- `data/`, `worktrees/`, `projects/` — 실행 중 데이터와 제품 저장소

## 기술 규칙

- Python 3.11 이상, **표준 라이브러리만**. 새 의존성은 추가하지 말고 제안한다.
- 대시보드는 바닐라 HTML/CSS/JS. 외부 CDN·폰트 없음.
- CSP(`style-src 'self'; script-src 'self'`)를 지킨다: 인라인 `<script>`, `<style>`, `style="…"` 속성 금지. 동적 스타일은 CSSOM(`el.style.setProperty`)으로.
- 화면에 넣는 모든 동적 문자열은 `textContent`로 넣는다 (innerHTML은 고정 SVG 아이콘만). 에이전트 출력은 신뢰하지 않는 입력이다.
- 파일 쓰기는 `util.atomic_write_*`, 기록은 `append_jsonl`(추가만)을 쓴다.

## 지켜야 할 불변식

1. 에이전트 하위 프로세스에 API 키 환경변수를 넘기지 않는다 (`util.clean_child_env`).
2. Codex는 항상 `--ignore-user-config`와 역할별 `-s` 샌드박스를 명시해 실행한다. `danger-full-access`나 승인 우회 플래그를 쓰지 않는다.
3. Claude Code 리뷰는 `--restricted --strict-mcp-config --tools Read,Grep,Glob`로 읽기 전용. `--bare`는 구독 로그인을 읽지 않으므로 쓰지 않는다.
4. 작업 상태는 `Store.transition`/`Store.block`으로만 바꾼다. `done`은 CEO 승인(`Engine.approve`)으로만.
5. 병합은 `qa.candidate_sha == task.candidate_sha`이고 검증이 `pass`/`none`일 때만.
6. 대시보드 서버는 127.0.0.1에만 열고, Host 검사와 쓰기 요청 토큰 검사를 유지한다. 휴대폰 리모컨(`studio/remote.py`, CEO 승인 2026-09-29)만 예외: CEO가 켠 같은 와이파이 서버(이 PC의 집 안 주소)와 허용한 Tailscale 이름(`*.ts.net`)으로 온 요청은 휴대폰 화면(`/m`, `/m/api/*`, 그림)만 받고, `/m/api`는 짝지은 기기 토큰(해시로 저장, 한 번 쓰는 5분 번호로 발급, 5번 틀리면 1분 잠금)으로만 쓴다. PC용 `/api`와 세션 토큰은 휴대폰 쪽으로 내보내지 않는다. 휴대폰에서도 짝지은 CEO는 기존 결재 흐름으로 MCP 설치·직원 채용을 승인할 수 있다(의도한 기능). 토큰·설정의 직접 편집 등 그 밖의 제한과 인증 검사는 유지한다.
7. 비정상 종료 뒤 '작업 중' 카드는 다시 부르지 않고 막힘으로 돌린다 (fail-closed).
8. Grok CLI는 그림 및 텍스트 조사·기획 보조·읽기 전용 리뷰에 본인 grok.com 로그인으로 쓴다 (CEO 확장 승인 2026-10-03). 텍스트는 `studio/grok_text.py`의 별도 설정 공간·전체 MCP 차단·도구 전체 거부·매 실행 전 적용 설정 검사를 통과한 경우에만 호출한다. 입력 텍스트만 전달하며 코드 수정·셸·임의 파일 쓰기·직원 MCP·하위 에이전트·브라우저 조작을 허용하지 않는다. 기존 로그인은 CLI가 임시 연결로 재사용하고 인증 값은 읽거나 복사하거나 기록하지 않는다. 격리 확인 실패 시 호출하지 않는다. 그림 경로는 기존대로 `--tools`로 그림 도구·파일 읽기만 허용하고 승인 우회 플래그(`--always-approve`, `--yolo`, `bypassPermissions`)를 쓰지 않는다 (윈도우에서는 그록 샌드박스가 강제되지 않는다).
9. MCP 보관소(`studio/mcp.py`, CEO 승인 2026-09-29): 직원에게는 CEO가 장착한 MCP만 붙인다 (Codex는 `--ignore-user-config` 그대로 `-c mcp_servers.*`, Claude는 `--strict-mcp-config --mcp-config <임시 파일>`). 리뷰 담당과 리뷰 실행·그림 실행에는 붙이지 않는다. MCP 토큰은 CEO가 넣은 것만 `data/mcp-secrets.json`에 두고, 명령줄·실행 기록·프롬프트·화면에 값을 내보내지 않으며(Codex는 환경변수 이름만 알려 주고 셸 환경에서는 뺀다, Claude 임시 설정은 실행 뒤 지운다), 모델 API 키 이름(`util.API_KEY_VARS`)은 토큰으로 받지 않는다. 내장 MCP(`studio/mcp_builtin/`)는 표준 라이브러리만, 읽기 전용, 웹 읽기는 이 PC·집 안 네트워크 주소를 막는다.

## 확인 방법

```powershell
python -m unittest discover -s tests -t .
python studio.py doctor
pwsh tools/dev/fake-company.ps1 -Reset; pwsh tools/dev/fake-company.ps1 -Serve -Port 8793   # 화면 확인 (가짜 실행기, 회사 사본)
pwsh tools/dev/capture.ps1 -Port 8793 -Prefix check -Names main,quests                    # 캡처
```

`python studio.py serve`는 실제 에이전트를 부른다(구독 사용량). `--fake`는 진짜 폴더에서 쓰지 않는다 (가짜 변경이 제품 저장소에 병합됨).

실행하지 못한 확인은 보고에 "실행 안 함"으로 적는다.
