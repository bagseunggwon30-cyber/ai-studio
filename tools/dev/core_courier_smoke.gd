# 코어 쿠리어 자동 확인 (AI 스튜디오 감독 프로그램 쪽에서 복사본에서만 돌린다, 제품 저장소에는 넣지 않는다)
# godot --headless --path <복사본> --script res://smoke.gd
extends SceneTree

var main: Node
var fails := 0
var total := 0


func check(name: String, ok: bool, detail: String = "") -> void:
	total += 1
	if not ok:
		fails += 1
	print(("PASS  " if ok else "FAIL  ") + name + ("  — " + detail if detail != "" else ""))


func frames(n: int) -> void:
	for i in n:
		await physics_frame


func key_event(code: Key) -> InputEventKey:
	var ev := InputEventKey.new()
	ev.keycode = code
	ev.physical_keycode = code
	ev.pressed = true
	return ev


func _initialize() -> void:
	run.call_deferred()


func run() -> void:
	var packed: PackedScene = load("res://scenes/main.tscn")
	main = packed.instantiate()
	root.add_child(main)
	await frames(3)
	var st = main.state

	# 1) 시작 상태와 HUD
	check("시작: 진행 중, 체력 3, 코어 0개", st.phase == RunState.Phase.PLAYING and st.hp == 3 and st.collected.size() == 0)
	check("HUD 글자", main.hp_label.text == "HP 3" and main.core_label.text == "CORES ○○○○○" and main.time_label.text in ["TIME 90.0", "TIME 89.9"],
			"%s | %s | %s" % [main.hp_label.text, main.core_label.text, main.time_label.text])
	check("일시정지·결과 화면은 숨김", not main.pause_overlay.visible and not main.result_overlay.visible)

	# 2) 이동: 오른쪽 키를 1초 누르면 오른쪽으로 간다
	var x0: float = st.player_pos.x
	Input.action_press("move_right")
	await frames(60)
	Input.action_release("move_right")
	check("오른쪽으로 이동 (1초)", st.player_pos.x > x0 + 100.0, "x %.1f → %.1f" % [x0, st.player_pos.x])
	check("그림이 상태를 따라감", main.player.position.is_equal_approx(st.player_pos))

	# 3) 방 안에서만: 왼쪽 벽까지 오래 누르기
	Input.action_press("move_left")
	await frames(400)
	Input.action_release("move_left")
	check("왼쪽 벽에서 멈춤 (밖으로 안 나감)", is_equal_approx(st.player_pos.x, main.ARENA.position.x), "x %.1f (벽 %.1f)" % [st.player_pos.x, main.ARENA.position.x])

	# 4) 일시정지: Esc → 멈춤·표시, 다시 Esc → 풀림
	main._input(key_event(KEY_ESCAPE))
	await frames(2)
	check("Esc: 일시정지 표시", st.paused and main.pause_overlay.visible)
	var t_paused: float = st.time_left
	await frames(60)
	check("일시정지 중 시간이 안 흐름", is_equal_approx(st.time_left, t_paused), "%.2f → %.2f" % [t_paused, st.time_left])
	main._input(key_event(KEY_ESCAPE))
	await frames(2)
	check("Esc 다시: 풀림", not st.paused and not main.pause_overlay.visible)
	await frames(20)
	check("풀린 뒤 시간이 다시 흐름", st.time_left < t_paused, "%.3f → %.3f" % [t_paused, st.time_left])

	# 5) 코어 5개 줍기 (코어 위치로 옮겨 겹침 판정을 일으킨다) → 출구 → 승리
	for id in range(RunState.CORE_COUNT):
		var core: Area2D = main.get_node("Cores/Core%d" % id)
		st.player_pos = core.position
		await frames(4)
	check("코어 5개 모두 주움", st.collected.size() == 5, str(st.collected))
	check("HUD 코어 표시 ●●●●●", main.core_label.text == "CORES ●●●●●", main.core_label.text)
	var all_hidden := true
	for id in range(RunState.CORE_COUNT):
		if main.get_node("Cores/Core%d" % id).visible:
			all_hidden = false
	check("주운 코어는 화면에서 사라짐", all_hidden)
	st.player_pos = main.exit_area.position
	await frames(4)
	check("출구 → 승리", st.phase == RunState.Phase.WON)
	check("결과 화면: VICTORY와 걸린 시간", main.result_overlay.visible and main.result_title.text == "VICTORY" and main.result_time.text.begins_with("TIME TAKEN"),
			"%s | %s" % [main.result_title.text, main.result_time.text])

	# 6) R: 처음 상태로
	main._input(key_event(KEY_R))
	await frames(4)
	var cores_back := true
	for id in range(RunState.CORE_COUNT):
		var c: Area2D = main.get_node("Cores/Core%d" % id)
		if not c.visible or not c.monitoring:
			cores_back = false
	check("R: 처음 상태 (진행 중, 체력 3, 코어 0, 시간 90 근처)", st.phase == RunState.Phase.PLAYING and st.hp == 3 and st.collected.size() == 0 and st.time_left > 89.0)
	check("R: 코어가 다시 보이고 주울 수 있음", cores_back)
	check("R: 결과 화면 숨김, 플레이어는 시작 자리", not main.result_overlay.visible and main.player.position.is_equal_approx(main.START_POS), str(main.player.position))
	# 다시 주울 수 있는지
	var core0: Area2D = main.get_node("Cores/Core0")
	st.player_pos = core0.position
	await frames(4)
	check("R 뒤에 코어를 다시 주울 수 있음", st.collected.has(0))

	# 7) 적에게 닿기: 체력 1 감소 + 무적 동안 또 안 줄고, 깜빡임
	main._input(key_event(KEY_R))
	await frames(3)
	st.player_pos = main.enemy.global_position
	await frames(4)
	check("적에 닿으면 체력 3 → 2", st.hp == 2, "hp %d" % st.hp)
	check("무적 시간이 시작됨", st.invuln_left > 0.5, "%.2f" % st.invuln_left)
	st.player_pos = main.enemy.global_position
	await frames(10)
	check("무적 동안 또 닿아도 체력 그대로", st.hp == 2, "hp %d" % st.hp)
	var saw_hidden := false
	var saw_shown := false
	for i in 20:
		await physics_frame
		st.player_pos = main.enemy.global_position
		if main.player.visible:
			saw_shown = true
		else:
			saw_hidden = true
	check("무적 동안 플레이어가 깜빡임 (보였다 안 보였다)", saw_hidden and saw_shown, "hidden=%s shown=%s" % [saw_hidden, saw_shown])

	# 8) 시간 초과 → 패배 화면
	main._input(key_event(KEY_R))
	await frames(3)
	st.time_left = 0.05
	await frames(6)
	check("시간 초과 → 패배", st.phase == RunState.Phase.LOST)
	check("결과 화면: DEFEAT", main.result_overlay.visible and main.result_title.text == "DEFEAT", main.result_title.text)

	print("\n결과: %d개 중 %d개 통과" % [total, total - fails])
	quit(fails)
