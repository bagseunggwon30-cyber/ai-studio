---
name: godot-scene-wiring
description: Core Courier의 Godot 씬과 노드 스크립트를 만들거나 검토하면서 RunState의 이동·코어·출구 규칙을 연결할 때 쓴다.
metadata:
  title: Godot 씬을 RunState에 잇기
  learned_by: builder
  projects: core-courier
  kinds: build, review
  source: T0004
  how: reflect
  created: 2026-09-29
  version: 2
  updated: 2026-09-29
  change: 출구 안에서 조건이 바뀌는 경우의 재판정과 화면·충돌 기하 값의 일치 확인을 추가했습니다.
---

### 순서
1. 규칙은 `src/core/run_state.gd`의 `RunState`만 호출한다. 씬 스크립트에 시간·체력·승패 계산을 새로 쓰지 않는다.
2. `src/world/main.gd`에서 `RunState` 하나를 만들고 `_ready()`에서 `state.setup(ARENA, START_POS)`을 호출한다.
3. `_physics_process(delta)`에서 입력 방향을 `state.tick(delta, move_dir)`에 넘긴 뒤 플레이어 노드 위치를 `state.player_pos`에 맞춘다. 플레이어 노드가 별도로 이동하지 않게 한다.
4. 방향키와 WASD는 `Input.get_vector("move_left", "move_right", "move_up", "move_down")`로 받는다. 입력 동작을 추가해야 한다면 작업 카드가 `project.godot` 변경을 허용하는지 확인한다.
5. 코어의 `area_entered`에서 플레이어인지 확인하고 `state.collect(core_id)`가 `true`일 때만 코어를 숨긴다. 출구는 진입 순간에 `state.reach_exit()`를 호출할 수 있지만, 진입 후에도 승리 조건이 바뀔 수 있다면 `_physics_process`에서 `exit_area.overlaps_area(player)`인 동안 다시 호출해 판정한다. 승리 여부는 `RunState`의 결과를 따른다.
6. `ARENA`를 이동 영역의 기준으로 두고, `src/world/main.gd`의 벽 그리기 좌표는 가능하면 `ARENA`에서 계산한다. `START_POS`와 `scenes/main.tscn`의 플레이어 시작 위치가 맞는지 확인한다. 플레이어 중심이 영역 경계까지 갈 수 있으므로 벽과의 간격을 충돌 반지름까지 고려한다.
7. `src/player/player.gd`, `src/world/core.gd`, `src/world/exit.gd`의 도형 크기와 `scenes/main.tscn`의 `CollisionShape2D` 크기를 같은 기준으로 맞춘다. 한쪽 크기를 바꾸면 다른 쪽도 함께 확인한다.

### 흔한 실수
- 씬에서 `state.hp`나 `state.phase`를 직접 바꾸기 → `RunState` 메서드만 호출한다.
- 노드를 별도로 움직여 `state.player_pos`와 어긋나기 → 위치는 매 프레임 상태 값을 따른다.
- 출구의 `area_entered`만으로 승리를 판정하기 → 출구 안에 머무는 동안 조건이 충족될 수 있는지 살핀다.
- 벽 좌표나 도형 반지름을 스크립트와 씬에 따로 바꾸기 → 그리기·충돌·이동 영역을 함께 확인한다.
- 스페이스 들여쓰기나 불필요한 무타입 변수 → 탭 들여쓰기와 가능한 정적 타입을 쓴다.
- Godot 함수 이름을 짐작하기 → 사용 중인 Godot 도움말에서 확인한다.

### 확인
- `project.godot`의 `run/main_scene`이 `res://scenes/main.tscn`을 가리키는지 확인한다.
- 가능하면 Godot에서 씬을 열어 스크립트 오류를 확인한다.
- 이동 경계에서 플레이어 도형과 벽이 어긋나지 않는지, 코어 획득 뒤 도형이 사라지는지, 코어를 모두 모은 뒤 출구에서 승리하는지 확인한다.
- 출구 안에서 승리 조건이 나중에 충족될 수 있는 배치라면, 다시 출구에 들어가지 않아도 판정되는지 확인한다.
