# 얼굴 초상화 시트(단색 배경, 직원 × 표정 격자)를 크기가 고른 한 장짜리 아틀라스로 만든다.
#
#   godot --headless --path tools/sprites --script res://make_portraits.gd -- --root=<프로젝트 폴더> [--config=<설정>]
#
# 설정은 tools/sprites/sheets.json의 "portraits". 설정에 "faceJobs"가 있으면 그것만 만든다
# (의상·캐릭터 제조실: [{"src": 시트, "out": 아틀라스, "characters": [한 명]}] — 한 사람짜리 1열 3줄 시트).
# 그림 모델이 칸을 똑같이 나누지 않으므로(어깨가 옆 칸으로 넘어가는 등) 등분하지 않고,
# 빈 줄·빈 열을 찾아 얼굴마다 잘라 낸 뒤 머리 가운데와 아래 끝을 맞춰 같은 크기 칸에 넣는다.
extends SceneTree

const Keying := preload("res://keying.gd")
const MIN_GAP := 6   # 이만큼 비어 있어야 칸 사이로 본다
const PAD := 8


func _initialize() -> void:
	var root := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
	var cfg = JSON.parse_string(FileAccess.get_file_as_string(_config_path(root)))
	if root == "" or typeof(cfg) != TYPE_DICTIONARY or not cfg.has("portraits"):
		push_error("--root=<프로젝트 폴더>와 sheets.json의 portraits 설정이 필요합니다")
		quit(2)
		return
	var p: Dictionary = cfg["portraits"]
	if cfg.has("faceJobs"):
		var all_ok := true
		for job in cfg["faceJobs"]:
			var q: Dictionary = p.duplicate(true)
			q["characters"] = job["characters"]
			all_ok = _make(root, q, job["src"], job["out"]) and all_ok
		quit(0 if all_ok else 1)
		return
	var ok := _make(root, p, p["file"], p["out"])
	# 의상 세트: assets-raw/looks/<세트>/portraits.png → ui/assets/portraits@<세트>.png
	for set_name in cfg.get("sets", []):
		var src := "assets-raw/looks/%s/portraits.png" % set_name
		if FileAccess.file_exists(root.path_join(src)):
			var base_out: String = p["out"]
			ok = _make(root, p, src, "%s@%s.png" % [base_out.get_basename(), set_name]) and ok
		else:
			print("건너뜀 (파일 없음): ", src)
	quit(0 if ok else 1)


func _make(root: String, p: Dictionary, src: String, out_rel: String) -> bool:
	var img := Image.load_from_file(_abs(root, src))
	if img == null or img.is_empty():
		push_error("그림을 읽을 수 없음: " + src)
		return false
	img.convert(Image.FORMAT_RGBA8)
	Keying.key(img, Keying.background_color(img))

	var characters: Array = p["characters"]
	var moods: Array = p["moods"]
	var cols := _bands(img, true)
	var rows := _bands(img, false)
	if cols.size() != characters.size() or rows.size() != moods.size():
		push_error("%s: 칸을 찾지 못함: 열 %d개(기대 %d), 줄 %d개(기대 %d)" % [src, cols.size(), characters.size(), rows.size(), moods.size()])
		return false

	# 얼굴마다 잘라 내고, 머리 가운데(위쪽 40%의 가운데)를 기준으로 삼는다.
	var faces: Array[Image] = []
	var heads: Array[int] = []
	var left := 0
	var right := 0
	var tallest := 0
	for r in rows.size():
		for c in cols.size():
			var cell := Rect2i(cols[c].x, rows[r].x, cols[c].y - cols[c].x, rows[r].y - rows[r].x)
			var face := img.get_region(cell)
			var used := face.get_used_rect()
			face = face.get_region(used)
			var top := face.get_region(Rect2i(0, 0, face.get_width(), maxi(1, int(face.get_height() * 0.4)))).get_used_rect()
			var cx := top.position.x + top.size.x / 2
			faces.append(face)
			heads.append(cx)
			left = maxi(left, cx)
			right = maxi(right, face.get_width() - cx)
			tallest = maxi(tallest, face.get_height())

	# 정사각형 칸: 머리 가운데를 칸 가운데에, 아래 끝(어깨)을 칸 아래에 맞춘다.
	var side := maxi(maxi(left, right) * 2, tallest) + PAD * 2
	var out_cell := int(p.get("cell", 256))
	var n_cols := characters.size()
	var atlas := Image.create_empty(side * n_cols, side * moods.size(), false, Image.FORMAT_RGBA8)
	for k in faces.size():
		var face := faces[k]
		var col := k % n_cols
		var row := k / n_cols
		var dst := Vector2i(col * side + side / 2 - heads[k], row * side + side - face.get_height())
		atlas.blit_rect(face, Rect2i(Vector2i.ZERO, face.get_size()), dst)
	atlas.resize(out_cell * n_cols, out_cell * moods.size(), Image.INTERPOLATE_LANCZOS)

	var out: String = _abs(root, out_rel)
	DirAccess.make_dir_recursive_absolute(out.get_base_dir())
	atlas.save_png(out)
	var meta := {"file": out.get_file(), "cell": out_cell, "characters": characters, "moods": moods, "source": src}
	var f := FileAccess.open(out.get_basename() + ".json", FileAccess.WRITE)
	f.store_string(JSON.stringify(meta, "  ") + "\n")
	f.close()
	print("얼굴 %d개 → %s (%dx%d, 칸 %d)" % [faces.size(), out_rel, atlas.get_width(), atlas.get_height(), out_cell])
	return true


# 불투명 픽셀이 있는 열(vertical=true) 또는 줄의 구간을 찾는다. 결과는 (시작, 끝) 목록.
func _bands(img: Image, vertical: bool) -> Array[Vector2i]:
	var n := img.get_width() if vertical else img.get_height()
	var m := img.get_height() if vertical else img.get_width()
	var filled: Array[bool] = []
	for i in n:
		var any := false
		for j in range(0, m, 2):
			var a := img.get_pixel(i, j).a if vertical else img.get_pixel(j, i).a
			if a > 0.5:
				any = true
				break
		filled.append(any)
	var bands: Array[Vector2i] = []
	var start := -1
	var gap := 0
	for i in n:
		if filled[i]:
			if start < 0:
				start = i
			gap = 0
		elif start >= 0:
			gap += 1
			if gap >= MIN_GAP:
				bands.append(Vector2i(start, i - gap + 1))
				start = -1
				gap = 0
	if start >= 0:
		bands.append(Vector2i(start, n))
	# 먼지 같은 작은 조각은 버린다.
	return bands.filter(func(b): return b.y - b.x > 40)


# --config=<파일>: sheets.json 대신 쓸 설정 (감독 프로그램의 의상·캐릭터 제조실이 작업마다 만든다).
static func _config_path(root: String) -> String:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--config="):
			return _abs(root, a.substr(9))
	return root.path_join("tools/sprites/sheets.json")


# 설정의 경로는 프로젝트 기준 상대 경로 또는 절대 경로.
static func _abs(root: String, p: String) -> String:
	return p if p.is_absolute_path() else root.path_join(p)
