---
name: godot-enemy-patrol-hit
description: Core Courier의 Godot 씬에서 적을 정해진 경로로 왕복 순찰시키고, 플레이어 접촉을 RunState.take_hit()와 무적 시간에 연결할 때 쓴다.
metadata:
  title: 적 순찰과 피격 연결
  learned_by: builder
  projects: core-courier
  kinds: build, review
  source: T0006
  how: study
  created: 2026-09-29
  version: 1
---

### 순서
1. `scenes/main.tscn`의 기존 `Player`가 `Area2D`이며 충돌 레이어가 `1`인지 확인한다. 적의 감지용 `Area2D`에는 `CollisionShape2D`를 두고 `monitoring`과 플레이어 레이어를 포함하는 `collision_mask`를 확인한다.
2. 정해진 길은 `Path2D`의 `Curve2D`로 놓고, 그 아래 `PathFollow2D`, 그 아래 적 `Area2D`를 둔다. `PathFollow2D.loop = false`로 설정해 끝에서 처음으로 순간 이동하지 않게 한다. [`Path2D`](https://docs.godotengine.org/en/stable/classes/class_path2d.html), [`PathFollow2D`](https://docs.godotengine.org/en/stable/classes/class_pathfollow2d.html)
3. 경로 길이는 `Path2D.curve.get_baked_length()`로 읽는다. `_physics_process(delta)`에서 진행 거리를 속도 × `delta`만큼 바꾸고, 양 끝에서 이동 방향을 반대로 바꾼다. 경로 길이가 0이면 이동을 시도하지 않는다. [`Curve2D`](https://docs.godotengine.org/en/stable/classes/class_curve2d.html)
4. `src/world/main.gd`에서 기존 `state.tick(delta, move_dir)` 호출을 유지한다. 적의 순찰은 `state.phase == RunState.Phase.PLAYING`이고 `state.paused == false`일 때만 진행하며, 재시작 시 경로 진행 거리와 방향도 시작값으로 돌린다.
5. 적이 플레이어와 닿으면 `src/world/main.gd`의 `state.take_hit()`을 호출한다. `true`를 돌려준 피격만 화면 효과에 반영한다. 체력 감소, 1초 무적, 패배 판정은 `src/core/run_state.gd`에 맡긴다.
6. `area_entered`는 첫 접촉을 감지한다. 플레이어가 계속 겹쳐 있는 동안 무적 시간이 끝난 뒤에도 피격돼야 하므로, 물리 프레임에서 `enemy.overlaps_area(player)`도 확인해 `take_hit()`을 호출한다. 겹침 목록은 물리 단계마다 갱신되므로 이동 직후의 즉시 판정으로 여기지 않는다. [`Area2D`](https://docs.godotengine.org/en/stable/classes/class_area2d.html)

### 흔한 실수
- `area_entered`에서만 피격 처리하기 → 접촉이 지속될 때도 `overlaps_area(player)`로 재판정한다.
- 씬 스크립트에서 체력이나 무적 타이머를 따로 계산하기 → `take_hit()` 결과와 `RunState.tick()`을 사용한다.
- `PathFollow2D.loop` 기본값을 그대로 두기 → 왕복 경로에서는 `false`로 설정하고 끝에서 방향을 뒤집는다.
- 적의 그림만 이동시키기 → 적 `Area2D`와 충돌 모양이 함께 경로를 따르게 한다.

### 확인
- 적이 경로 양 끝에서 되돌아오고, 충돌 모양이 그림과 함께 움직이는지 본다.
- 첫 접촉에서 체력이 1 줄고, 계속 접촉하면 1초 무적 동안 추가로 줄지 않다가 이후 다시 줄어드는지 본다.
- 일시정지·패배 중 순찰과 피격이 멈추고, 재시작하면 적 위치와 진행 방향이 초기화되는지 본다.
