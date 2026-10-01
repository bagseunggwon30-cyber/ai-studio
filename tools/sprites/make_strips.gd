# 캐릭터 시트(단색 배경)를 동작별 가로 띠(<캐릭터>.<동작>.strip.png + .strip.json)로 자른다.
#
#   godot --headless --path tools/sprites --script res://make_strips.gd -- --root=<프로젝트 폴더> [--config=<설정>]
#
# 설정은 tools/sprites/sheets.json. 없는 시트 파일은 건너뛴다.
# 여러 프레임짜리 동작은 모든 칸을 같은 영역(합집합)으로 잘라서, 칸 안의 위치가 그대로 유지된다(흔들림 방지).
extends SceneTree

const Keying := preload("res://keying.gd")
const PAD := 4


func _initialize() -> void:
	var root := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
	if root == "":
		push_error("--root=<프로젝트 폴더> 가 필요합니다")
		quit(2)
		return
	var cfg = JSON.parse_string(FileAccess.get_file_as_string(_config_path(root)))
	if typeof(cfg) != TYPE_DICTIONARY:
		push_error(_config_path(root) + "을 읽을 수 없습니다")
		quit(2)
		return

	var out_dir: String = _abs(root, cfg.get("out", "ui/assets/sprites"))
	DirAccess.make_dir_recursive_absolute(out_dir)
	var index_path := out_dir.path_join("index.json")
	var index: Dictionary = {}
	var failed := false

	# 의상 세트: 같은 칸 배치의 시트가 assets-raw/looks/<세트>/에 있다. 키는 <캐릭터>@<세트>.<동작>.
	# 동작 시트는 서 있는 자세(step)의 키를 기본 시트에 맞춰 시트 전체를 같은 비율로 키우거나 줄인다.
	var sheets: Array = cfg["sheets"].duplicate(true)
	for set_name in cfg.get("sets", []):
		for base in cfg["sheets"]:
			var s: Dictionary = base.duplicate(true)
			s["file"] = "assets-raw/looks/%s/%s" % [set_name, String(base["file"]).get_file()]
			s["character"] = "%s@%s" % [base["character"], set_name]
			if not base.has("matchHeightOf"):
				s["scaleTo"] = "%s.step" % base["character"]
			sheets.append(s)

	for sheet in sheets:
		var path: String = _abs(root, sheet["file"])
		if not FileAccess.file_exists(path):
			print("건너뜀 (파일 없음): ", sheet["file"])
			continue
		var img := Image.load_from_file(path)
		if img == null or img.is_empty():
			push_error("그림을 읽을 수 없음: " + sheet["file"])
			failed = true
			continue
		img.convert(Image.FORMAT_RGBA8)
		Keying.key(img, Keying.background_color(img))

		var cols := int(sheet["cols"])
		var rows := int(sheet["rows"])
		var cw := img.get_width() / cols
		var ch := img.get_height() / rows
		var cells: Array[Image] = []
		for r in rows:
			for c in cols:
				cells.append(img.get_region(Rect2i(c * cw, r * ch, cw, ch)))

		var character: String = sheet["character"]
		var sheet_factor := 1.0
		if sheet.has("scaleTo") and index.has(sheet["scaleTo"]):
			var tallest_step := 0
			for i in sheet["actions"].get("step", []):
				tallest_step = maxi(tallest_step, cells[int(i)].get_used_rect().size.y)
			if tallest_step > 0:
				sheet_factor = float(index[sheet["scaleTo"]]["contentHeight"]) / float(tallest_step)
		for action in sheet["actions"]:
			var idxs: Array = sheet["actions"][action]
			var area := Rect2i()
			var first := true
			for i in idxs:
				var used := cells[int(i)].get_used_rect()
				if used.size == Vector2i.ZERO:
					continue
				area = used if first else area.merge(used)
				first = false
			if first:
				push_error("%s.%s: 칸이 비어 있음" % [character, action])
				failed = true
				continue

			var n := idxs.size()
			var fw := area.size.x + PAD * 2
			var fh := area.size.y + PAD
			var strip: Image
			if sheet.get("align", "") == "head" and n > 1:
				# 걷기처럼 칸마다 위치가 흔들리는 시트: 머리 가운데를 가로 기준, 발바닥을 세로 기준으로 맞춘다.
				var rects: Array[Rect2i] = []
				var heads: Array[int] = []
				var left := 0
				var right := 0
				var tallest := 0
				for i in idxs:
					var used := cells[int(i)].get_used_rect()
					var head_h := maxi(1, int(used.size.y * 0.3))
					var head := cells[int(i)].get_region(Rect2i(used.position, Vector2i(used.size.x, head_h))).get_used_rect()
					var cx := used.position.x + head.position.x + head.size.x / 2
					rects.append(used)
					heads.append(cx)
					left = maxi(left, cx - used.position.x)
					right = maxi(right, used.end.x - cx)
					tallest = maxi(tallest, used.size.y)
				fw = left + right + PAD * 2
				fh = tallest + PAD
				strip = Image.create_empty(fw * n, fh, false, Image.FORMAT_RGBA8)
				for k in n:
					var r := rects[k]
					var dst := Vector2i(k * fw + PAD + left - (heads[k] - r.position.x), fh - r.size.y)
					strip.blit_rect(cells[int(idxs[k])], r, dst)
				area = Rect2i(0, 0, fw - PAD * 2, tallest)
			else:
				strip = Image.create_empty(fw * n, fh, false, Image.FORMAT_RGBA8)
				for k in n:
					strip.blit_rect(cells[int(idxs[k])], area, Vector2i(k * fw + PAD, PAD))

			# 따로 뽑은 시트(걷기 등)는 크기가 다를 수 있어, 같은 캐릭터의 기준 동작 키에 맞춘다.
			var content_h := area.size.y
			var ref_name := "%s.%s" % [character, sheet.get("matchHeightOf", "")]
			var factor := sheet_factor
			if sheet.has("matchHeightOf") and index.has(ref_name):
				factor = float(index[ref_name]["contentHeight"]) / float(area.size.y)
			if absf(factor - 1.0) > 0.001:
				fw = int(round(fw * factor))
				fh = int(round(fh * factor))
				strip.resize(fw * n, fh, Image.INTERPOLATE_LANCZOS)
				content_h = int(round(area.size.y * factor))

			var name := "%s.%s" % [character, action]
			strip.save_png(out_dir.path_join(name + ".strip.png"))
			var fps_cfg: Dictionary = cfg.get("fps", {})
			var meta := {
				"character": character,
				"action": action,
				"file": name + ".strip.png",
				"frames": n,
				"frameWidth": fw,
				"frameHeight": fh,
				"contentHeight": content_h,
				"fps": int(fps_cfg.get(action, fps_cfg.get("default", 1))),
				"loop": n > 1 and action in cfg.get("loops", []),
				"anchor": {"x": fw / 2, "y": fh},
				"facing": sheet.get("facing", "right"),
				"source": sheet["file"],
				"cells": idxs,
			}
			if meta["loop"] and n >= 3:
				meta["seam"] = _seam(strip, n, fw, fh)
			_write_json(out_dir.path_join(name + ".strip.json"), meta)
			index[name] = meta
			print("%-16s %d프레임 %dx%d%s" % [name, n, fw, fh, ("  이음새 %.3f" % meta["seam"]) if meta.has("seam") else ""])

	_write_json(index_path, index)
	if cfg.get("preview", true):
		_write_preview(root, cfg.get("out", "ui/assets/sprites"), index)
	print("완료: %d개 → %s" % [index.size(), out_dir])
	quit(1 if failed else 0)


# 반복 동작의 이음새: (마지막→첫 프레임 차이) / (나머지 연속 프레임 차이 평균). 1.0에 가까울수록 자연스럽다.
func _seam(strip: Image, n: int, fw: int, fh: int) -> float:
	var diffs: Array[float] = []
	for k in n:
		diffs.append(_frame_diff(strip, k, (k + 1) % n, fw, fh))
	var inner := 0.0
	for k in n - 1:
		inner += diffs[k]
	inner /= float(n - 1)
	return snappedf(diffs[n - 1] / inner, 0.001) if inner > 0.0 else 0.0


func _frame_diff(strip: Image, a: int, b: int, fw: int, fh: int) -> float:
	var total := 0.0
	var count := 0
	for y in range(0, fh, 3):
		for x in range(0, fw, 3):
			var ca := strip.get_pixel(a * fw + x, y)
			var cb := strip.get_pixel(b * fw + x, y)
			var both := minf(ca.a, cb.a)
			total += absf(ca.a - cb.a) + (absf(ca.r - cb.r) + absf(ca.g - cb.g) + absf(ca.b - cb.b)) * both
			count += 1
	return total / float(count)


# 개발용 미리보기: 모든 띠를 캔버스로 넘겨서 재생한다 (tools/sprites/preview.html, 로컬 서버로 열기).
func _write_preview(root: String, out_rel: String, index: Dictionary) -> void:
	var html := """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>스프라이트 미리보기</title>
<link rel="stylesheet" href="preview.css"></head>
<body><h1>스프라이트 미리보기</h1><p>배경: <button data-bg="check">체크</button> <button data-bg="office">사무실색</button> <button data-bg="dark">어둡게</button></p>
<main id="grid"></main>
<script>const BASE = "/%s/"; const STRIPS = %s;</script>
<script src="preview.js"></script></body></html>
""" % [out_rel, JSON.stringify(index)]
	var f := FileAccess.open(root.path_join("tools/sprites/preview.html"), FileAccess.WRITE)
	f.store_string(html)
	f.close()


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
