# 소윤이 로컬 MCP·실제 회사 연결 적용 (2026-10-03)

사용자가 소윤이용 로컬 MCP·연결 토큰과 `studio-docs` 진행 조회, `reports/connection-check/**` 제출·본인 작업 취소 권한을 승인했다. 이 범위를 실제 설정에 적용했고 등록된 MCP로 실제 회사 API를 확인했다. **추가 모델 생성 호출 0회**다. 소윤이 클라우드에서 직접 호출한 결과는 아니며 그 부분은 미검증이다.

## 적용과 실제 확인

- 사용자 Codex 설정에 `ai_studio` 도구 6개를 등록했다. 기존 모델·다른 MCP 설정은 보존했다. 쓰기 도구에는 클라이언트의 승인 설정 `writes`를 사용한다.
- 토큰은 Git 밖의 Windows DPAPI CurrentUser 암호화 파일로 저장하고 현재 사용자 ACL로 제한했다. 설정·명령줄에는 암호화 파일 위치만 전달하며 값과 토큰 환경변수는 넣지 않았다. 서버의 `data/supervisors.json`은 SHA256과 승인받은 범위만 보관한다. 개인 경로·토큰·실제 회사 작업 ID는 공개 보고서에서 제외한다.
- 직원 MCP 장착·실행 모델·회사 규칙·실제 제품 파일은 바꾸지 않았다. 확인용 카드 하나만 제출하고 취소했다. 재전송은 같은 카드를 반환했고 다른 내용은 충돌로 처리됐다.
- 실제 등록 블록을 복사한 설치된 Codex app-server MCP 클라이언트로 도구 목록·제출·상태·이벤트·결과·취소를 확인했다. Codex 모델 turn 0회다. 폴더 밖 제출과 다른 프로젝트 조회는 거절됐다. [실제 회사 근거](soyun-production-connection.json).
- 파일 조회 도구도 호출했지만, 작업을 실행하지 않아 후보 산출물이 없다는 이유로 거절됐다. 실제 결과 파일 조회 성공을 주장하지 않는다. 이전 임시 회사의 파일 조회 성공은 별도 결과다.

## 실행 상태와 남은 단계

현재 `127.0.0.1:8765`는 **연결 전용** 서버다. 감독 API만 제공하고 직원·스케줄러·기존 작업 복구/재실행·모델 호출·CEO 쓰기 API를 시작하지 않는다. 이 상태에서 제출된 작업은 실행 대기이며 완료로 표시하면 안 된다.

서버 재시작: `python -X utf8 -B tools/supervisor-host.py --port 8765`.
승인된 연결 검사 재실행: `python -X utf8 -B tools/dev/supervisor_connection_check.py --owner-approved`.
실제 직원 실행은 모델 사용 승인 후 연결 전용 서버를 종료하고 일반 `python studio.py serve`로 전환한다. 일반 serve는 이번에 실행하지 않았다.

소윤이의 연결된 PC를 사용하는 **새 로컬 Codex 작업**에서 `ai_studio` 도구 목록을 확인해야 한다. 로컬 설정이 클라우드 대화에 자동 상속된다고 가정하지 않는다. 이번에 소윤이에 메시지를 보내거나 새 모델 작업을 시작하지 않았다. [현재 연결 안내와 전달문](../SOYUN_CONNECT.md).

## 최종 전체 검사

검증한 마지막 코드: `c1d1c1071f4e2f38ef29706ba3297a0ac4263a87`. 이후 커밋은 이 보고서와 근거만 추가하며 코드 해시가 유지되는지 확인한다. 이전 271개 검사와 합산하지 않는다.

| 환경 | 전체 Python | 통과 | 생략 | 실패/오류 |
|---|---:|---:|---:|---:|
| 이 PC | 275 | 274 | 1 | 0 |
| Windows GitHub Actions | 275 | 255 | 20 | 0 |

PC 생략은 POSIX 프로세스 그룹 1개다. CI는 여기에 Godot 부재로 19개를 더 생략했다. 진행판 12개와 JavaScript 문법 10파일도 각 환경에서 통과했다. 검사 중 코드 불변을 확인했다. [PC JSON](connection-regression.json), [CI JSON](connection-ci/regression.json), [CI 실행](https://github.com/bagseunggwon30-cyber/ai-studio/actions/runs/37115250223). CI stdio 검사는 가짜 모델·임시 회사이며 실제 회사 검사와 구분한다.

새 검사는 Windows 사용자 암호화 왕복/평문 미저장, 기존 설정 보존·반복 설치, 기존 MCP 충돌 시 변경 금지, 연결 전용 서버의 접수와 CEO API 차단을 확인한다. 실제 권한·도구 호출은 위 실제 회사 근거에 별도로 남겼다.

## 변경 파일

`studio/supervisor_credentials.py`, `studio/supervisor_setup.py`, `studio/supervisor_mcp.py`, `tools/setup-supervisor.py`, `tools/supervisor-host.py`, `tools/dev/codex_supervisor_client.py`, `tools/dev/supervisor_connection_check.py`, `tests/test_supervisor_setup.py`, 연결 안내·인수인계·근거 문서.

실제 `data/supervisors.json`, 사용자 MCP 설정과 암호화 토큰 파일은 공개 저장소에 넣지 않는다. main 병합·외부 배포·localhost 공개는 하지 않았다.
