# 신뢰 수용 테스트 — Core Courier RunState (8개)
#
# 감독 프로그램이 후보 커밋 스냅샷의 res://acceptance/ 에 이 폴더를 넣고 실행한다.
# 작업자(에이전트)는 이 파일을 볼 수는 있어도 바꿀 수는 없다.
#
#   godot --headless --path <스냅샷> --script res://acceptance/run.gd -- --out=<결과.json>
#
# 계약 문서: projects/core-courier/docs/INTERFACES.md
extends SceneTree

const TARGET := "res://src/core/run_state.gd"
const EPS := 0.001

# 계약 값 (구현의 상수를 믿지 않고 테스트가 직접 들고 있는다)
const MAX_HP := 3
const TIME_LIMIT := 90.0
const CORE_COUNT := 5
const PLAYER_SPEED := 160.0
const INVULN_TIME := 1.0
const PLAYING := 0
const WON := 1
const LOST := 2

const TESTS := [
	"movement_stays_in_arena",
	"core_collected_once",
	"hit_invulnerability",
	"hp_zero_loses",
	"timeout_loses",
	"win_needs_all_cores",
	"restart_resets_everything",
	"pause_freezes",
]

var _script: GDScript = null
var _fails: Array[String] = []


func _initialize() -> void:
	var out_path := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			out_path = arg.substr(6)

	var load_error := ""
	if not ResourceLoader.exists(TARGET):
		load_error = "파일 없음: " + TARGET
	else:
		_script = load(TARGET) as GDScript
		if _script == null or not _script.can_instantiate():
			load_error = "스크립트를 불러오지 못함 (문법 오류 또는 인스턴스화 불가)"

	var results: Array = []
	var passed := 0
	for test_name in TESTS:
		var r := _run_test(test_name, load_error)
		results.append(r)
		if r["ok"]:
			passed += 1

	var report := {
		"suite": "core-courier/run_state",
		"engine": Engine.get_version_info().get("string", ""),
		"total": results.size(),
		"passed": passed,
		"tests": results,
	}
	if out_path != "":
		var f := FileAccess.open(out_path, FileAccess.WRITE)
		if f:
			f.store_string(JSON.stringify(report, "  "))
			f.close()
		else:
			push_error("결과 파일을 쓸 수 없음: " + out_path)
	print("ACCEPTANCE %d/%d" % [passed, results.size()])
	quit(0 if passed == results.size() else 1)


func _run_test(test_name: String, load_error: String) -> Dictionary:
	if load_error != "":
		return {"name": test_name, "ok": false, "message": load_error}
	_fails.clear()
	var finished = call("test_" + test_name)
	if finished != true:
		_fails.append("테스트가 끝까지 실행되지 않음 (없는 메서드·속성 또는 런타임 오류)")
	return {"name": test_name, "ok": _fails.is_empty(), "message": "; ".join(_fails)}


func _new_state():
	var s = _script.new()
	s.setup(Rect2(0, 0, 100, 100), Vector2(50, 50))
	return s


func _check(cond: bool, msg: String) -> void:
	if not cond:
		_fails.append(msg)


func _near(a: float, b: float) -> bool:
	return absf(a - b) <= EPS


# 1. 이동: 방향은 정규화하고, 영역(arena) 밖으로 나가지 않으며, 시간이 흐른다.
func test_movement_stays_in_arena() -> bool:
	var s = _new_state()
	s.tick(0.1, Vector2(1, 1))
	var moved: float = (s.player_pos - Vector2(50, 50)).length()
	_check(_near(moved, PLAYER_SPEED * 0.1), "대각선 이동 거리 %.3f (기대 %.3f — 방향을 정규화해야 함)" % [moved, PLAYER_SPEED * 0.1])
	s.tick(2.0, Vector2.RIGHT)
	_check(_near(s.player_pos.x, 100.0), "오른쪽 끝 x=%.3f (기대 100 — 영역 밖으로 나가면 안 됨)" % s.player_pos.x)
	s.tick(2.0, Vector2(-1, -1))
	_check(_near(s.player_pos.x, 0.0) and _near(s.player_pos.y, 0.0), "왼쪽 위 끝 위치 %s (기대 (0, 0))" % str(s.player_pos))
	_check(_near(s.time_left, TIME_LIMIT - 4.1), "time_left=%.3f (기대 %.3f — tick마다 시간이 줄어야 함)" % [s.time_left, TIME_LIMIT - 4.1])
	return true


# 2. 코어: 같은 코어는 한 번만, 없는 id는 거절.
func test_core_collected_once() -> bool:
	var s = _new_state()
	_check(s.collect(2) == true, "처음 줍는 코어 2가 true가 아님")
	_check(s.collect(2) == false, "같은 코어 2를 두 번 주울 수 있음")
	_check(s.collect(CORE_COUNT) == false, "없는 코어 id %d를 주울 수 있음" % CORE_COUNT)
	_check(s.collect(-1) == false, "음수 코어 id를 주울 수 있음")
	_check(s.collected.size() == 1, "collected 개수 %d (기대 1)" % s.collected.size())
	return true


# 3. 피격: 맞으면 hp 1 감소, 이후 INVULN_TIME 동안 무적.
func test_hit_invulnerability() -> bool:
	var s = _new_state()
	_check(s.take_hit() == true, "첫 피격이 적용되지 않음")
	_check(s.hp == MAX_HP - 1, "피격 후 hp %d (기대 %d)" % [s.hp, MAX_HP - 1])
	_check(s.take_hit() == false, "무적 시간 중에 또 맞음")
	s.tick(INVULN_TIME * 0.5, Vector2.ZERO)
	_check(s.take_hit() == false, "무적 시간(%.1f초)보다 일찍 풀림" % INVULN_TIME)
	s.tick(INVULN_TIME * 0.5 + 0.05, Vector2.ZERO)
	_check(s.take_hit() == true, "무적 시간이 지났는데 맞지 않음")
	_check(s.hp == MAX_HP - 2, "두 번째 피격 후 hp %d (기대 %d)" % [s.hp, MAX_HP - 2])
	return true


# 4. 체력 0: 패배하고, 끝난 판은 더 이상 변하지 않는다.
func test_hp_zero_loses() -> bool:
	var s = _new_state()
	for i in MAX_HP:
		_check(s.take_hit() == true, "%d번째 피격이 적용되지 않음" % (i + 1))
		s.tick(INVULN_TIME + 0.05, Vector2.ZERO)
	_check(s.hp == 0, "hp %d (기대 0)" % s.hp)
	_check(s.phase == LOST, "hp 0인데 패배(LOST=2)가 아님: phase=%d" % s.phase)
	_check(s.is_finished() == true, "패배 후 is_finished()가 false")
	var t: float = s.time_left
	s.tick(1.0, Vector2.RIGHT)
	_check(_near(s.time_left, t), "끝난 판에서 시간이 계속 흐름")
	_check(s.collect(0) == false, "끝난 판에서 코어를 주울 수 있음")
	_check(s.take_hit() == false, "끝난 판에서 또 맞음")
	_check(s.hp >= 0, "hp가 0 아래로 내려감 (hp=%d)" % s.hp)
	return true


# 5. 시간 초과: 0에서 멈추고 패배.
func test_timeout_loses() -> bool:
	var s = _new_state()
	s.tick(TIME_LIMIT - 1.0, Vector2.ZERO)
	_check(s.phase == PLAYING, "시간이 남았는데 판이 끝남")
	s.tick(5.0, Vector2.ZERO)
	_check(_near(s.time_left, 0.0), "time_left=%.3f (기대 0 — 음수로 내려가면 안 됨)" % s.time_left)
	_check(s.phase == LOST, "시간 초과인데 패배(LOST=2)가 아님: phase=%d" % s.phase)
	_check(s.reach_exit() == false, "시간 초과 뒤에 출구 판정이 됨")
	return true


# 6. 승리: 코어를 모두 모은 뒤 출구에 닿아야만 승리.
func test_win_needs_all_cores() -> bool:
	var s = _new_state()
	for id in range(CORE_COUNT - 1):
		s.collect(id)
	_check(s.reach_exit() == false, "코어 %d개로 승리함" % (CORE_COUNT - 1))
	_check(s.phase == PLAYING, "코어가 모자란데 판이 끝남")
	s.collect(CORE_COUNT - 1)
	_check(s.reach_exit() == true, "코어 %d개를 모두 모았는데 승리하지 못함" % CORE_COUNT)
	_check(s.phase == WON, "승리(WON=1)가 아님: phase=%d" % s.phase)
	_check(s.is_finished() == true, "승리 후 is_finished()가 false")
	_check(s.take_hit() == false, "승리 후에 맞음")
	return true


# 7. 재시작: 모든 값이 시작 상태로.
func test_restart_resets_everything() -> bool:
	var s = _new_state()
	s.collect(0)
	s.collect(1)
	s.take_hit()
	s.tick(3.0, Vector2.RIGHT)
	s.set_paused(true)
	s.reset()
	_check(s.hp == MAX_HP, "재시작 후 hp %d (기대 %d)" % [s.hp, MAX_HP])
	_check(_near(s.time_left, TIME_LIMIT), "재시작 후 time_left=%.3f (기대 %.1f)" % [s.time_left, TIME_LIMIT])
	_check(s.collected.size() == 0, "재시작 후 collected가 비지 않음")
	_check(s.player_pos.is_equal_approx(Vector2(50, 50)), "재시작 후 위치 %s (기대 시작 위치 (50, 50))" % str(s.player_pos))
	_check(s.phase == PLAYING, "재시작 후 진행 중(PLAYING=0)이 아님")
	_check(s.paused == false, "재시작 후 일시정지가 풀리지 않음")
	_check(s.take_hit() == true, "재시작 후 무적 시간이 남아 있음")
	_check(s.collect(0) == true, "재시작 후 코어 0을 다시 주울 수 없음")
	return true


# 8. 일시정지: 시간·위치·획득·피격이 모두 멈춘다.
func test_pause_freezes() -> bool:
	var s = _new_state()
	s.set_paused(true)
	_check(s.paused == true, "set_paused(true) 후 paused가 false")
	var t: float = s.time_left
	var p: Vector2 = s.player_pos
	s.tick(1.0, Vector2.RIGHT)
	_check(_near(s.time_left, t), "일시정지 중 시간이 흐름")
	_check(s.player_pos.is_equal_approx(p), "일시정지 중 움직임")
	_check(s.collect(0) == false, "일시정지 중 코어를 주움")
	_check(s.take_hit() == false, "일시정지 중 맞음")
	s.set_paused(false)
	s.tick(1.0, Vector2.RIGHT)
	_check(s.time_left < t, "일시정지를 풀었는데 시간이 멈춰 있음")
	_check(s.player_pos.x > p.x, "일시정지를 풀었는데 움직이지 않음")
	return true
