# 새로 뽑은 시트에서 몇 칸만 원래 시트로 옮긴다 (나머지 칸은 원래 그대로 두어 자르기·색 바꾸기 규칙이 흔들리지 않게).
#
#   godot --headless --path tools/sprites --script res://compose_cells.gd -- --root=<프로젝트 폴더> \
#       --from=assets-raw/seated/base/char-hana.png --to=assets-raw/char-hana.png --cells=0,1,5 [--cols=4 --rows=2]
#
# 칸 번호는 0부터 (왼쪽 위 → 오른쪽). 처음 바꿀 때 원래 시트를 assets-raw/old/<같은 경로>에 한 번 남긴다.
# 두 시트의 크기가 다르면 새 시트를 원래 크기로 맞춘 뒤 옮긴다.
extends SceneTree


func _initialize() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--") and a.contains("="):
			var kv := a.substr(2).split("=", true, 1)
			args[kv[0]] = kv[1]
	for need in ["root", "from", "to", "cells"]:
		if not args.has(need):
			push_error("--%s=… 가 필요합니다" % need)
			quit(2)
			return
	var root: String = args["root"]
	var from_path := _abs(root, args["from"])
	var to_path := _abs(root, args["to"])
	var cols := int(args.get("cols", "4"))
	var rows := int(args.get("rows", "2"))
	var src := Image.load_from_file(from_path)
	var dst := Image.load_from_file(to_path)
	if src == null or dst == null or src.is_empty() or dst.is_empty():
		push_error("그림을 읽을 수 없음")
		quit(2)
		return
	src.convert(Image.FORMAT_RGBA8)
	dst.convert(Image.FORMAT_RGBA8)
	if src.get_size() != dst.get_size():
		src.resize(dst.get_width(), dst.get_height(), Image.INTERPOLATE_LANCZOS)

	var rel := to_path.substr(root.length()).trim_prefix("/").trim_prefix("assets-raw/")
	var backup := root.path_join("assets-raw/old").path_join(rel)
	if not FileAccess.file_exists(backup):
		DirAccess.make_dir_recursive_absolute(backup.get_base_dir())
		dst.save_png(backup)
		print("원래 시트를 남김: ", backup)

	var cw := dst.get_width() / cols
	var ch := dst.get_height() / rows
	for s in String(args["cells"]).split(","):
		var i := int(s)
		var r := Rect2i((i % cols) * cw, (i / cols) * ch, cw, ch)
		dst.blit_rect(src, r, r.position)
	dst.save_png(to_path)
	print("완료: %s ← %s (칸 %s)" % [args["to"], args["from"], args["cells"]])
	quit(0)


static func _abs(root: String, p: String) -> String:
	return p if p.is_absolute_path() else root.path_join(p)
