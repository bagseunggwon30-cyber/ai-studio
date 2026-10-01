---
name: mcp-tool-making
description: "직원들이 쓸 MCP 도구(server.py 한 파일)를 새로 만들거나, 리뷰 지적을 받아 고쳐 올 때 쓴다."
metadata:
  title: MCP 도구 만드는 법
  learned_by: producer, builder, analyst
  projects: 
  kinds: tool
  source: ceo
  how: ceo
  created: 2026-09-29
  version: 1
---

### 먼저
1. 요청을 작은 도구 1~4개로 줄인다. 도구 하나는 동사 하나다 (`read_csv`, `find_text`, `count_files`). 여러 일을 한 도구에 몰지 않는다.
2. 내장 도구와 겹치는지 본다: 회사 기록 찾기(`studio-records`), 회사 기억장(`team-memory`), 시계(`clock`), 제품 기록 보기(`git-history`), 웹 페이지 읽기(`web-reader`), 차근차근 생각(`step-thinking`), Godot 도움말(`godot-docs`). 같은 일이면 새로 만들지 말고 reason에 그렇다고 쓴다.

### 틀 (프롬프트의 틀 예시 그대로)
- `from mcp_base import Server, ToolError, setup_stdio`, `srv = Server("이름", "1.0", "설명")`.
- 도구는 `@srv.tool("도구_이름", "언제 쓰는지", {속성}, ["필수 속성"])`로 등록한다.
- 맨 아래는 `if __name__ == "__main__":` 안에서 `setup_stdio()` 다음 `srv.serve()`.
- 도구 함수의 인자 이름은 입력 스키마의 속성 이름과 똑같이 쓴다. 필수가 아닌 인자에는 모두 기본값을 준다.
- 결과는 사람이 읽는 짧은 글(str)로 돌려준다. 2만 자를 넘으면 잘라서 "…(길어서 앞부분만)"을 붙인다.
- 잘못된 입력이나 못 찾은 경우는 `raise ToolError("쉬운 한국어 이유")`. 다른 예외가 새지 않게 파일 읽기는 try로 감싼다.
- 결과가 비었을 때도 "찾은 것이 없어요"처럼 알아볼 수 있는 글을 돌려준다.

### 경로 입력 (리뷰에서 가장 많이 걸리는 곳)
- 기준 폴더는 `root = Path.cwd().resolve()`(도구가 켜지는 프로젝트 폴더).
- 받은 경로는 `target = (root / path).resolve()`로 풀고, `target.is_relative_to(root)`가 아니면 ToolError. 절대 경로, `..`, 드라이브 문자(`C:`)가 이렇게 막힌다.
- 파일 크기를 먼저 보고, 크면 앞부분만 읽는다. 글은 `encoding="utf-8", errors="replace"`로 읽는다.

### 하지 않는 것 (하나라도 있으면 반려)
- 표준 라이브러리 밖 import, `subprocess`·`os.system`·`eval`·`exec`, 파일 만들기·고치기·지우기, stdout에 print (로그는 `sys.stderr`).
- 홈 폴더의 `.codex`·`.claude`·`.ssh`·`.grok`, `.env`, 이름에 KEY·TOKEN·SECRET이 든 환경변수 읽기.
- 인터넷은 요청에 꼭 필요할 때만, https 공개 주소만. `127.0.0.1`·`localhost`·집 안 주소(`192.168.`, `10.`, `172.16`~`172.31`)는 막는다.

### 고쳐 올 때
- name은 그대로 두고 change에 바뀐 점을 쓴다.
- 지난 리뷰의 blocking 지적은 모두 고친다. reason에 지적마다 어떻게 고쳤는지 한 줄씩 쓴다.

### 확인 (코드를 실행할 수 없으니 읽어서 확인)
- 도구마다 스키마 속성과 함수 인자가 같은가, 필수가 아닌 인자에 기본값이 있는가.
- 경로를 받는 도구마다 프로젝트 폴더 밖으로 못 나가게 막았는가.
- `print(`가 stdout으로 가는 곳이 없는가.
- tools 목록의 이름·설명이 코드의 등록과 같은가.
