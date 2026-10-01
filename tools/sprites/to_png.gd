# 그림 한 장을 PNG로 바꾼다 (Grok 그림 도구는 JPG로 저장한다. 자르기 도구는 PNG를 읽는다).
#
#   godot --headless --path tools/sprites --script res://to_png.gd -- --root=<프로젝트 폴더> --in=<그림> --out=<결과.png>
extends SceneTree


func _initialize() -> void:
	var src := ""
	var dst := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--in="):
			src = a.substr(5)
		elif a.begins_with("--out="):
			dst = a.substr(6)
	if src == "" or dst == "":
		push_error("--in=<그림> --out=<결과.png> 가 필요합니다")
		quit(2)
		return
	var img := Image.load_from_file(src)
	if img == null or img.is_empty():
		push_error("그림을 읽을 수 없음: " + src)
		quit(2)
		return
	img.convert(Image.FORMAT_RGBA8)
	var err := img.save_png(dst)
	if err != OK:
		push_error("저장 실패: " + dst)
		quit(2)
		return
	print("완료: %dx%d → %s" % [img.get_width(), img.get_height(), dst])
	quit(0)
