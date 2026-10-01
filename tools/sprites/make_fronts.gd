# 층 배경에서 의자만 오려 '앞 그림'(<배경>.front-<i>.png, 1536x1024 투명 바탕)을 만든다.
# 직원이 의자에 앉으면 이 그림이 몸 위에 한 겹 더 그려져, 등받이가 허리 아래를 가린다 (scene.js FRONT).
#
#   godot --headless --path tools/sprites --script res://make_fronts.gd -- --root=<프로젝트 폴더>
#
# 설정: ui/assets/bg/floors.json 의 floors[].desks[].chair (의자 상자 x0,y0,x1,y1)와 fronts (한 줄씩 묶음, z).
# 의자는 검은 의자라서, 상자 안의 어두운 픽셀을 등받이 가운데에서부터 이어 칠하고(flood fill) 안쪽 구멍을 메운다.
# 상자 윗변은 등받이 윗선에 맞춘다 (그 위의 키보드·책상 선이 섞이면 몸 위에 줄이 그어진다).
extends SceneTree

const DARK := 0.36   # 이보다 어두우면 의자


func _initialize() -> void:
	var root := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
	if root == "":
		push_error("--root=<프로젝트 폴더> 가 필요합니다")
		quit(2)
		return
	var bg_dir := root.path_join("ui/assets/bg")
	var cfg = JSON.parse_string(FileAccess.get_file_as_string(bg_dir.path_join("floors.json")))
	if typeof(cfg) != TYPE_DICTIONARY:
		push_error("floors.json을 읽을 수 없습니다")
		quit(2)
		return
	for floor in cfg["floors"]:
		if floor.has("like"):
			continue
		var bg := Image.load_from_file(bg_dir.path_join(floor["bg"]))
		bg.convert(Image.FORMAT_RGBA8)
		var stem := String(floor["bg"]).get_basename()
		var fronts: Array = floor.get("fronts", [])
		for i in fronts.size():
			var out := Image.create_empty(bg.get_width(), bg.get_height(), false, Image.FORMAT_RGBA8)
			var count := 0
			for d in fronts[i]["desks"]:
				var box: Array = floor["desks"][int(d)]["chair"]
				count += _cut_chair(bg, out, Rect2i(int(box[0]), int(box[1]), int(box[2]) - int(box[0]), int(box[3]) - int(box[1])))
			var name := "%s.front-%d.png" % [stem, i]
			out.save_png(bg_dir.path_join(name))
			print("%-24s %s: 의자 %d개, %d픽셀" % [name, fronts[i]["name"], fronts[i]["desks"].size(), count])
	quit(0)


# 상자 안에서 의자 모양을 찾아 out에 옮긴다. 옮긴 픽셀 수를 돌려준다.
func _cut_chair(bg: Image, out: Image, box: Rect2i) -> int:
	var w := box.size.x
	var h := box.size.y
	var dark := PackedByteArray()
	dark.resize(w * h)
	for y in h:
		for x in w:
			dark[y * w + x] = 1 if bg.get_pixel(box.position.x + x, box.position.y + y).get_luminance() < DARK else 0
	# 1) 등받이 가운데(상자 가운데, 위에서 1/5)에서 가장 가까운 어두운 픽셀부터 이어 칠하기
	var seed := Vector2i(w / 2, h / 5)
	while seed.y < h and dark[seed.y * w + seed.x] == 0:
		seed.y += 1
	if seed.y >= h:
		push_warning("의자를 찾지 못함: %s" % box)
		return 0
	var mask := _fill(dark, w, h, [seed], 1)
	# 2) 안쪽 구멍 메우기: 상자 가장자리에서 의자가 아닌 곳을 이어 칠하고, 거기 닿지 않은 곳은 의자로 본다
	var outside_src := PackedByteArray()
	outside_src.resize(w * h)
	for p in w * h:
		outside_src[p] = 1 - mask[p]
	var border: Array = []
	for x in w:
		border.append(Vector2i(x, 0))
		border.append(Vector2i(x, h - 1))
	for y in h:
		border.append(Vector2i(0, y))
		border.append(Vector2i(w - 1, y))
	var outside := _fill(outside_src, w, h, border, 1)
	var n := 0
	for y in h:
		for x in w:
			if outside[y * w + x] == 0:
				out.set_pixel(box.position.x + x, box.position.y + y, bg.get_pixel(box.position.x + x, box.position.y + y))
				n += 1
	return n


# src[p] == want 인 픽셀을 시작점들에서 4방향으로 이어 칠한 결과 (1 = 칠함)
func _fill(src: PackedByteArray, w: int, h: int, seeds: Array, want: int) -> PackedByteArray:
	var hit := PackedByteArray()
	hit.resize(w * h)
	var stack: Array[Vector2i] = []
	for s in seeds:
		var p: Vector2i = s
		if src[p.y * w + p.x] == want and hit[p.y * w + p.x] == 0:
			hit[p.y * w + p.x] = 1
			stack.append(p)
	while not stack.is_empty():
		var p: Vector2i = stack.pop_back()
		for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var q: Vector2i = p + d
			if q.x < 0 or q.y < 0 or q.x >= w or q.y >= h:
				continue
			var i := q.y * w + q.x
			if hit[i] == 0 and src[i] == want:
				hit[i] = 1
				stack.append(q)
	return hit
