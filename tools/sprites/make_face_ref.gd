# 얼굴 아틀라스(투명 배경)에서 한 사람 칸(표정 3줄)을 꺼내 자홍색 바탕의 참고 그림으로 만든다.
# 의상·캐릭터 제조실이 "이 얼굴 3장에서 옷만 바꿔 그려" 또는 "이 칸 배치로 새 직원 얼굴을 그려"라고 할 때 첨부한다.
#
#   godot --headless --path tools/sprites --script res://make_face_ref.gd -- --root=<프로젝트 폴더> --atlas=<png> --col=<열> --cols=<열 수> --out=<png>
#
# 결과: 1열 3줄 (보통·기쁨·걱정), 칸 사이는 자홍색 여백 (make_portraits.gd가 빈 줄로 칸을 찾는다).
extends SceneTree

const SCALE := 2
const GAP := 48


func _initialize() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		if kv.size() == 2:
			args[kv[0]] = kv[1]
	var root: String = args.get("root", "")
	if root == "" or not args.has("atlas") or not args.has("out"):
		push_error("--root, --atlas, --out 이 필요합니다")
		quit(2)
		return
	var atlas := Image.load_from_file(_abs(root, args["atlas"]))
	if atlas == null or atlas.is_empty():
		push_error("그림을 읽을 수 없음: " + String(args["atlas"]))
		quit(2)
		return
	atlas.convert(Image.FORMAT_RGBA8)
	var cols := maxi(1, int(args.get("cols", "1")))
	var col := clampi(int(args.get("col", "0")), 0, cols - 1)
	var rows := maxi(1, int(args.get("rows", "3")))
	var cw := atlas.get_width() / cols
	var ch := atlas.get_height() / rows
	var out := Image.create_empty(cw * SCALE + GAP * 2, (ch * SCALE + GAP) * rows + GAP, false, Image.FORMAT_RGBA8)
	out.fill(Color(1, 0, 1, 1))
	for r in rows:
		var cell := atlas.get_region(Rect2i(col * cw, r * ch, cw, ch))
		cell.resize(cw * SCALE, ch * SCALE, Image.INTERPOLATE_NEAREST)
		out.blend_rect(cell, Rect2i(Vector2i.ZERO, cell.get_size()), Vector2i(GAP, GAP + r * (ch * SCALE + GAP)))
	var path := _abs(root, args["out"])
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	out.save_png(path)
	print("얼굴 참고 → ", path)
	quit(0)


static func _abs(root: String, p: String) -> String:
	return p if p.is_absolute_path() else root.path_join(p)
