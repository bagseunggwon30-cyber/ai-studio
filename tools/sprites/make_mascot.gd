# 진행판 발표 캐릭터: 초록 배경 일러스트(assets-raw/mascot/<표정>.png, draw_mascot.py)를 화면용 PNG로.
#
#   godot --headless --path tools/sprites --script res://make_mascot.gd -- --root=<프로젝트 폴더> [--height=800]
#
# 1) 초록(#00FF00) 배경을 부드럽게 지운다 (머리카락 가장자리는 반투명, 초록기는 뺀다).
# 2) 세 표정을 같은 자리로 잘라(모두의 테두리를 합친 상자) 같은 크기로 줄인다 — 표정을 바꿔도 몸이 움직이지 않게.
# 3) 크기와 표정마다 그림이 있는 사각형을 JSON 한 줄로 알린다 → ui/assets/mascot/mascot.json을 맞출 때 본다.
# 4) (있으면) 애니메이션 그림: blink = 눈 깜빡임 — 평소 그림과 **달라진 곳만** 잘라 blink.png로 (위에 겹쳐 그려서 몸이 튀지 않게),
#    point = 판이 돌 때 손짓 (같은 상자로 자른 전신). 자르는 상자는 세 표정으로만 정한다 (예전 그림 자리가 바뀌지 않게).
# 결과: ui/assets/mascot/<표정>.png
extends SceneTree

const MOODS := ["normal", "happy", "worried"]
const EXTRAS := ["blink", "point"]
const DIFF := 48     # 두 그림의 한 픽셀이 이만큼(채널 최대 차) 다르면 '바뀐 곳'
const LO := 30.0    # 초록기(g - max(r,b))가 이보다 작으면 불투명
const HI := 120.0   # 이보다 크면 투명 (사이는 반투명)
const PAD := 12


func _initialize() -> void:
	var root := ""
	var height := 800
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
		elif a.begins_with("--height="):
			height = int(a.substr(9))
	if root == "":
		push_error("--root=<프로젝트 폴더> 가 필요합니다")
		quit(2)
		return
	var imgs := {}
	var box := Rect2i()
	for mood in MOODS:
		var path: String = root + "/assets-raw/mascot/" + mood + ".png"
		var img := Image.load_from_file(path)
		if img == null or img.is_empty():
			push_error("그림을 읽을 수 없음: " + path)
			quit(2)
			return
		img.convert(Image.FORMAT_RGBA8)
		_key(img)
		var r := img.get_used_rect()
		box = r if box.size == Vector2i.ZERO else box.merge(r)
		imgs[mood] = img
	var any: Image = imgs["normal"]
	box = box.grow(PAD).intersection(Rect2i(Vector2i.ZERO, any.get_size()))
	var width := int(round(box.size.x * float(height) / box.size.y))
	var used := {}
	var outs := {}
	for mood in MOODS:
		var img: Image = imgs[mood]
		_bleed(img, 4)
		var out := img.get_region(box)
		out.resize(width, height, Image.INTERPOLATE_LANCZOS)
		_clean_alpha(out)
		var dst: String = root + "/ui/assets/mascot/" + mood + ".png"
		if out.save_png(dst) != OK:
			push_error("저장 실패: " + dst)
			quit(2)
			return
		outs[mood] = out
		var r := out.get_used_rect()
		used[mood] = {"x": r.position.x, "y": r.position.y, "w": r.size.x, "h": r.size.y}
	for extra in EXTRAS:
		var path: String = root + "/assets-raw/mascot/" + extra + ".png"
		if not FileAccess.file_exists(path):
			continue
		var img := Image.load_from_file(path)
		if img == null or img.is_empty() or img.get_size() != any.get_size():
			push_error("애니메이션 그림을 쓸 수 없음 (크기가 다름): " + path)
			continue
		img.convert(Image.FORMAT_RGBA8)
		_key(img)
		_bleed(img, 4)
		var out := img.get_region(box)
		out.resize(width, height, Image.INTERPOLATE_LANCZOS)
		_clean_alpha(out)
		if extra == "blink":
			# 머리 쪽(위 45%)에서 달라진 곳만. 전체에서 달라진 곳이 많으면 그림이 밀린 것 → 쓰지 않는다
			var whole := _diff_count(outs["normal"], out, Rect2i(Vector2i.ZERO, out.get_size()))
			var r := _diff_rect(outs["normal"], out, int(height * 0.45))
			if r.size == Vector2i.ZERO or whole > out.get_width() * out.get_height() / 50:
				push_error("깜빡임 그림이 평소 그림과 너무 달라요 (바뀐 픽셀 %d) — 다시 그려 주세요" % whole)
				continue
			r = r.grow(4).intersection(Rect2i(Vector2i.ZERO, out.get_size()))
			if out.get_region(r).save_png(root + "/ui/assets/mascot/blink.png") != OK:
				push_error("저장 실패: blink.png")
				continue
			used["blink"] = {"x": r.position.x, "y": r.position.y, "w": r.size.x, "h": r.size.y, "changed": whole}
		else:
			if out.save_png(root + "/ui/assets/mascot/" + extra + ".png") != OK:
				push_error("저장 실패: " + extra)
				continue
			var ur := out.get_used_rect()
			used[extra] = {"x": ur.position.x, "y": ur.position.y, "w": ur.size.x, "h": ur.size.y,
				"changed": _diff_count(outs["normal"], out, Rect2i(Vector2i.ZERO, out.get_size()))}
	print("MASCOT " + JSON.stringify({"size": {"w": width, "h": height}, "used": used}))
	quit(0)


# 두 그림에서 한 픽셀이라도 크게 다른 곳 (알파를 곱한 색으로 비교)
func _differs(a: PackedByteArray, b: PackedByteArray, o: int) -> bool:
	var aa := a[o + 3] / 255.0
	var ba := b[o + 3] / 255.0
	for c in 3:
		if absf(a[o + c] * aa - b[o + c] * ba) > DIFF:
			return true
	return absi(a[o + 3] - b[o + 3]) > DIFF


func _diff_count(a: Image, b: Image, area: Rect2i) -> int:
	var da := a.get_data()
	var db := b.get_data()
	var w := a.get_width()
	var n := 0
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			if _differs(da, db, (y * w + x) * 4):
				n += 1
	return n


# 위쪽 max_y 줄 안에서 '가장 많이 바뀐 덩어리'(눈)를 담는 사각형.
# Codex가 고친 그림은 머리카락 몇 가닥도 조금씩 다시 그리므로, 8×8 칸마다 바뀐 픽셀을 세어 촘촘한 칸만 이은 덩어리 중 가장 큰 것만 쓴다.
const CELL := 8
const CELL_MIN := 10  # 한 칸(64픽셀)에서 이만큼 바뀌어야 '촘촘'

func _diff_rect(a: Image, b: Image, max_y: int) -> Rect2i:
	var da := a.get_data()
	var db := b.get_data()
	var w := a.get_width()
	var cw := int(ceil(w / float(CELL)))
	var ch := int(ceil(max_y / float(CELL)))
	var counts := PackedInt32Array()
	counts.resize(cw * ch)
	for y in max_y:
		for x in w:
			if _differs(da, db, (y * w + x) * 4):
				counts[(y / CELL) * cw + x / CELL] += 1
	var seen := PackedByteArray()
	seen.resize(cw * ch)
	var best := Rect2i()
	var best_sum := 0
	for start in cw * ch:
		if seen[start] or counts[start] < CELL_MIN:
			continue
		var stack: Array[int] = [start]
		seen[start] = 1
		var lo := Vector2i(cw, ch)
		var hi := Vector2i(-1, -1)
		var total := 0
		while not stack.is_empty():
			var c: int = stack.pop_back()
			var cx := c % cw
			var cy := c / cw
			total += counts[c]
			lo = Vector2i(mini(lo.x, cx), mini(lo.y, cy))
			hi = Vector2i(maxi(hi.x, cx), maxi(hi.y, cy))
			for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
				var nx: int = cx + d.x
				var ny: int = cy + d.y
				if nx < 0 or ny < 0 or nx >= cw or ny >= ch:
					continue
				var n := ny * cw + nx
				if not seen[n] and counts[n] >= CELL_MIN:
					seen[n] = 1
					stack.append(n)
		if total > best_sum:
			best_sum = total
			best = Rect2i(lo * CELL, (hi - lo + Vector2i.ONE) * CELL)
	return best.intersection(Rect2i(0, 0, w, max_y))


# 초록 배경 지우기: 초록기가 크면 투명, 가장자리는 반투명으로 하고 초록기를 뺀다 (지운 곳은 색도 0).
func _key(img: Image) -> void:
	var data := img.get_data()
	var i := 0
	while i < data.size():
		var r := data[i]
		var g := data[i + 1]
		var b := data[i + 2]
		var hi := maxi(r, b)
		var gness := float(g - hi)
		if gness >= HI:
			data[i] = 0
			data[i + 1] = 0
			data[i + 2] = 0
			data[i + 3] = 0
		elif gness > 0.0:
			if gness > LO:
				data[i + 3] = int(round(255.0 * (HI - gness) / (HI - LO)))
			data[i + 1] = hi  # 초록기 빼기
		i += 4
	img.set_data(img.get_width(), img.get_height(), false, Image.FORMAT_RGBA8, data)


# 줄일 때 투명한 곳의 검은색이 가장자리로 번지지 않게, 투명한 픽셀에 옆 픽셀 색을 채운다 (알파는 그대로 0).
func _bleed(img: Image, passes: int) -> void:
	var w := img.get_width()
	var h := img.get_height()
	var data := img.get_data()
	for _p in passes:
		var src := data.duplicate()
		for y in h:
			for x in w:
				var o := (y * w + x) * 4
				if src[o + 3] != 0 or data[o] != 0 or data[o + 1] != 0 or data[o + 2] != 0:
					continue
				for d in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
					var nx: int = x + d.x
					var ny: int = y + d.y
					if nx < 0 or ny < 0 or nx >= w or ny >= h:
						continue
					var n := (ny * w + nx) * 4
					if src[n] != 0 or src[n + 1] != 0 or src[n + 2] != 0:
						data[o] = src[n]
						data[o + 1] = src[n + 1]
						data[o + 2] = src[n + 2]
						break
	img.set_data(w, h, false, Image.FORMAT_RGBA8, data)


func _clean_alpha(img: Image) -> void:
	var data := img.get_data()
	var i := 3
	while i < data.size():
		if data[i] < 8:
			data[i] = 0
		i += 4
	img.set_data(img.get_width(), img.get_height(), false, Image.FORMAT_RGBA8, data)
