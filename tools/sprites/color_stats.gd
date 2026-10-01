# 개발용: 캐릭터 띠에서 많이 쓰인 색과 그 색의 평균 높이를 뽑는다 (마스크 규칙을 정할 때 참고).
#   godot --headless --path tools/sprites --script res://color_stats.gd -- --root=<프로젝트 폴더> --who=hana
extends SceneTree


func _initialize() -> void:
	var root := ""
	var who := "hana"
	var file := ""
	var col := -1
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
		elif a.begins_with("--who="):
			who = a.substr(6)
		elif a.begins_with("--file="):
			file = a.substr(7)
		elif a.begins_with("--col="):
			col = int(a.substr(6))
	var dir := root.path_join("ui/assets/sprites")
	var index = JSON.parse_string(FileAccess.get_file_as_string(dir.path_join("index.json")))
	var images: Array[Image] = []
	if file != "":
		# 얼굴 아틀라스의 한 열 (4열)
		var atlas := Image.load_from_file(root.path_join(file))
		var cw := atlas.get_width() / 4
		images.append(atlas.get_region(Rect2i(col * cw, 0, cw, atlas.get_height())))
	else:
		for key in index:
			if String(key).begins_with(who + "."):
				images.append(Image.load_from_file(dir.path_join(index[key]["file"])))
	var buckets := {}
	for img in images:
		var h := img.get_height()
		for y in h:
			for x in img.get_width():
				var c := img.get_pixel(x, y)
				if c.a < 0.9:
					continue
				var q := Vector3i(int(c.r * 15), int(c.g * 15), int(c.b * 15))
				if not buckets.has(q):
					buckets[q] = [0, 0.0, Color(0, 0, 0)]
				buckets[q][0] += 1
				buckets[q][1] += float(y) / h
				buckets[q][2] += c
	var rows := []
	for q in buckets:
		var b = buckets[q]
		var avg: Color = b[2] / float(b[0])
		rows.append([b[0], avg, b[1] / b[0]])
	rows.sort_custom(func(a, b): return a[0] > b[0])
	for r in rows.slice(0, 40):
		var c: Color = r[1]
		print("%6d  #%s  h=%3d s=%.2f v=%.2f  y=%.2f" % [r[0], c.to_html(false), int(c.h * 360), c.s, c.v, r[2]])
	quit(0)
