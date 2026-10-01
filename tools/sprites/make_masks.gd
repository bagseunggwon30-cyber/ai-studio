# 색 바꾸기(꾸미기)용 표시 그림을 만든다.
#
#   godot --headless --path tools/sprites --script res://make_masks.gd -- --root=<프로젝트 폴더> [--config=<설정>]
#
# 설정에 "faceAtlases"가 있으면 얼굴 아틀라스는 그것만 본다: [{"file": 아틀라스, "whos": [칸마다 이름], "characters": [칸마다 캐릭터]}].
# 색 규칙(parts)이 없는 캐릭터(새로 만든 직원 등)는 표시를 만들지 않는다 (그 직원은 색 바꾸기를 쓰지 않는다).
# 띠(<키>.strip.png)와 얼굴 아틀라스마다 같은 크기의 <이름>.mask.png를 만든다: 빨강 = 머리, 초록 = 옷.
# 규칙은 sheets.json의 "parts" (색상·채도·밝기 범위와 높이). 화면(ui/looks.js)은 이 표시가 있는 픽셀만
# 부분별 평균 색(ui/assets/sprites/parts.json) 대비 비율을 지키며 새 색으로 칠한다.
# 순서: make_strips.gd → make_portraits.gd → make_masks.gd (make_strips가 index.json을 새로 쓰므로).
extends SceneTree

const FACE_DEFAULT := {"hair": {"y": [0, 1]}, "outfit": {"y": [0.76, 1]}}


func _initialize() -> void:
	var root := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
	var cfg = JSON.parse_string(FileAccess.get_file_as_string(_config_path(root)))
	if root == "" or typeof(cfg) != TYPE_DICTIONARY or not cfg.has("parts"):
		push_error("--root=<프로젝트 폴더>와 sheets.json의 parts 설정이 필요합니다")
		quit(2)
		return
	var parts: Dictionary = cfg["parts"]
	var min_area: Dictionary = cfg.get("minArea", {})
	var out_dir: String = _abs(root, cfg.get("out", "ui/assets/sprites"))
	var index = JSON.parse_string(FileAccess.get_file_as_string(out_dir.path_join("index.json")))
	var sums := {}

	for key in index:
		var who: String = String(key).split(".")[0]
		var character := who.split("@")[0]
		if not parts.has(character):
			continue
		var meta: Dictionary = index[key]
		var img := Image.load_from_file(out_dir.path_join(meta["file"]))
		img.convert(Image.FORMAT_RGBA8)
		var mask := _mask(img, parts[character])
		_drop_small(mask, 1, int(min_area.get("outfit", 0)))
		_accumulate(img, mask, sums, who)
		meta["mask"] = String(meta["file"]).replace(".strip.png", ".mask.png")
		mask.save_png(out_dir.path_join(meta["mask"]))

	# 얼굴 아틀라스: 열이 직원(sheets.json portraits.characters), 줄이 표정. 칸마다 따로 잰다.
	var p: Dictionary = cfg["portraits"]
	var atlases: Array = []
	if cfg.has("faceAtlases"):
		for a in cfg["faceAtlases"]:
			atlases.append([String(a["file"]), a["whos"], a["characters"]])
	else:
		var whos := func(suffix: String) -> Array: return p["characters"].map(func(c): return String(c) + suffix)
		atlases.append([String(p["out"]), whos.call(""), p["characters"]])
		for set_name in cfg.get("sets", []):
			atlases.append(["%s@%s.png" % [String(p["out"]).get_basename(), set_name], whos.call("@" + set_name), p["characters"]])
	for entry in atlases:
		var path := _abs(root, entry[0])
		if not FileAccess.file_exists(path):
			continue
		var img := Image.load_from_file(path)
		img.convert(Image.FORMAT_RGBA8)
		var cols: Array = entry[2]
		var n_rows: int = p["moods"].size()
		var cw := img.get_width() / cols.size()
		var chh := img.get_height() / n_rows
		var mask := Image.create_empty(img.get_width(), img.get_height(), false, Image.FORMAT_RGBA8)
		for c in cols.size():
			if not parts.has(cols[c]):
				continue
			var rules := _face_rules(parts[cols[c]])
			for r in n_rows:
				var rect := Rect2i(c * cw, r * chh, cw, chh)
				var cell := img.get_region(rect)
				var cell_mask := _mask(cell, rules)
				_drop_small(cell_mask, 1, int(min_area.get("faceOutfit", 0)))
				_accumulate(cell, cell_mask, sums, "%s:face" % entry[1][c])
				mask.blit_rect(cell_mask, Rect2i(Vector2i.ZERO, rect.size), rect.position)
		mask.save_png(path.get_basename() + ".mask.png")
		print("얼굴 표시 → ", path.get_basename(), ".mask.png")

	var stats := {}
	for who in sums:
		stats[who] = {}
		for part in sums[who]:
			var s: Array = sums[who][part]
			if s[2] > 0:
				stats[who][part] = {
					"h": snappedf(fposmod(atan2(s[4], s[3]) / TAU, 1.0) * 360.0, 0.1),
					"s": snappedf(s[0] / s[2], 0.001),
					"v": snappedf(s[1] / s[2], 0.001),
					"n": s[2],
				}
	_write_json(out_dir.path_join("parts.json"), stats)
	_write_json(out_dir.path_join("index.json"), index)
	for who in stats:
		print("%-18s %s" % [who, JSON.stringify(stats[who])])
	quit(0)


# 얼굴용 규칙: 몸 규칙에 FACE_DEFAULT(높이)와 캐릭터별 "face"를 차례로 덮어쓴다.
func _face_rules(base: Dictionary) -> Dictionary:
	var out := {}
	var face: Dictionary = base.get("face", {})
	for part in ["hair", "outfit"]:
		var rule: Dictionary = base[part].duplicate()
		rule.merge(FACE_DEFAULT[part], true)
		rule.merge(face.get(part, {}), true)
		out[part] = rule
	return out


func _in_hue(h: float, r: Array) -> bool:
	var a := float(r[0])
	var b := float(r[1])
	return (h >= a and h <= b) if a <= b else (h >= a or h <= b)


func _match(c: Color, rule: Dictionary, y: float) -> bool:
	if c.a < 0.5 or not _in_hue(c.h * 360.0, rule["h"]):
		return false
	if c.s < float(rule["s"][0]) or c.s > float(rule["s"][1]):
		return false
	if c.v < float(rule["v"][0]) or c.v > float(rule["v"][1]):
		return false
	if rule.has("y") and (y < float(rule["y"][0]) or y > float(rule["y"][1])):
		return false
	return true


func _mask(img: Image, rules: Dictionary) -> Image:
	var w := img.get_width()
	var h := img.get_height()
	var mask := Image.create_empty(w, h, false, Image.FORMAT_RGBA8)
	for y in h:
		var fy := float(y) / h
		for x in w:
			var c := img.get_pixel(x, y)
			if _match(c, rules["hair"], fy):
				mask.set_pixel(x, y, Color(1, 0, 0, 1))
			elif _match(c, rules["outfit"], fy):
				mask.set_pixel(x, y, Color(0, 1, 0, 1))
	return mask


# channel 0 = 머리(빨강), 1 = 옷(초록). 이 채널에서 이어진 조각이 min보다 작으면 지운다 (입, 반짝이 등).
func _drop_small(mask: Image, channel: int, min_size: int) -> void:
	if min_size <= 0:
		return
	var w := mask.get_width()
	var h := mask.get_height()
	var seen := PackedByteArray()
	seen.resize(w * h)
	for start in w * h:
		if seen[start] or mask.get_pixel(start % w, start / w)[channel] < 0.5:
			continue
		var comp: Array[int] = [start]
		seen[start] = 1
		var i := 0
		while i < comp.size():
			var p := comp[i]
			i += 1
			var px := p % w
			var py := p / w
			for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
				var nx: int = px + d.x
				var ny: int = py + d.y
				if nx < 0 or ny < 0 or nx >= w or ny >= h:
					continue
				var q := ny * w + nx
				if not seen[q] and mask.get_pixel(nx, ny)[channel] >= 0.5:
					seen[q] = 1
					comp.append(q)
		if comp.size() < min_size:
			for q in comp:
				mask.set_pixel(q % w, q / w, Color(0, 0, 0, 0))


# 부분별 평균 색 (색상은 원 위에서: sin/cos 평균)
func _accumulate(img: Image, mask: Image, sums: Dictionary, who: String) -> void:
	if not sums.has(who):
		sums[who] = {"hair": [0.0, 0.0, 0, 0.0, 0.0], "outfit": [0.0, 0.0, 0, 0.0, 0.0]}
	for y in img.get_height():
		for x in img.get_width():
			var m := mask.get_pixel(x, y)
			if m.a < 0.5:
				continue
			var c := img.get_pixel(x, y)
			var s: Array = sums[who]["hair" if m.r > 0.5 else "outfit"]
			s[0] += c.s
			s[1] += c.v
			s[2] += 1
			s[3] += cos(c.h * TAU)
			s[4] += sin(c.h * TAU)


func _write_json(path: String, value: Variant) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(value, "  ") + "\n")
	f.close()


# --config=<파일>: sheets.json 대신 쓸 설정 (감독 프로그램의 의상·캐릭터 제조실이 작업마다 만든다).
static func _config_path(root: String) -> String:
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--config="):
			return _abs(root, a.substr(9))
	return root.path_join("tools/sprites/sheets.json")


# 설정의 경로는 프로젝트 기준 상대 경로 또는 절대 경로.
static func _abs(root: String, p: String) -> String:
	return p if p.is_absolute_path() else root.path_join(p)
