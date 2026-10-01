# 일부러 틀리게 만든 구현. `python studio.py selftest core-courier`가
# 신뢰 테스트가 이것을 '실패'로 판정하는지 확인한다. (QA 때 스냅샷에는 들어가지 않는다)
extends RefCounted

enum Phase { PLAYING, WON, LOST }

const MAX_HP := 3
const TIME_LIMIT := 90.0
const CORE_COUNT := 5
const PLAYER_SPEED := 160.0
const INVULN_TIME := 1.0

var hp: int = MAX_HP
var time_left: float = TIME_LIMIT
var collected: Array = []
var player_pos: Vector2 = Vector2.ZERO
var arena: Rect2 = Rect2(0, 0, 640, 360)
var start_pos: Vector2 = Vector2(320, 180)
var phase: int = Phase.PLAYING
var paused: bool = false


func setup(arena_rect: Rect2, start: Vector2) -> void:
	arena = arena_rect
	start_pos = start
	reset()


func reset() -> void:
	hp = MAX_HP
	time_left = TIME_LIMIT
	collected = []
	player_pos = start_pos
	phase = Phase.PLAYING
	paused = false


func tick(delta: float, move_dir: Vector2) -> void:
	time_left -= delta  # 버그: 0 아래로 내려가고, 패배·일시정지 처리 없음
	player_pos += move_dir * PLAYER_SPEED * delta  # 버그: 정규화·영역 제한 없음


func collect(core_id: int) -> bool:
	collected.append(core_id)  # 버그: 중복·잘못된 id 허용
	return true


func take_hit() -> bool:
	hp -= 1  # 버그: 무적 시간 없음
	if hp <= 0:
		phase = Phase.LOST
	return true


func reach_exit() -> bool:
	if collected.size() >= CORE_COUNT:
		phase = Phase.WON
		return true
	return false


func set_paused(value: bool) -> void:
	paused = value


func is_finished() -> bool:
	return phase != Phase.PLAYING
