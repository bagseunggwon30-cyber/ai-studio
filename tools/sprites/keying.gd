# 단색 배경(자홍색) 시트를 투명하게 만드는 공용 함수. make_strips.gd, make_portraits.gd가 쓴다.
extends RefCounted

const KEY_DIST := 90.0   # 배경색과의 거리(0~441)가 이보다 가까우면 투명
const FRINGE := 40       # 가장자리 픽셀의 자홍기(min(r,b)-g)가 이보다 크면 반투명 처리


# 네 귀퉁이 8x8 평균을 배경색으로 본다.
static func background_color(img: Image) -> Color:
	var w := img.get_width()
	var h := img.get_height()
	var sum := Color(0, 0, 0, 0)
	var count := 0
	for corner in [Vector2i(0, 0), Vector2i(w - 8, 0), Vector2i(0, h - 8), Vector2i(w - 8, h - 8)]:
		for y in 8:
			for x in 8:
				sum += img.get_pixelv(corner + Vector2i(x, y))
				count += 1
	return sum / float(count)


# 1단계: 배경색에 가까운 픽셀을 투명하게.
# 2단계: 투명 픽셀과 맞닿은 가장자리 중 자홍색이 섞인 픽셀만 반투명으로 하고 자홍기를 뺀다.
static func key(img: Image, bg: Color) -> void:
	var w := img.get_width()
	var h := img.get_height()
	var data := img.get_data()
	var br := bg.r8
	var bgc := bg.g8
	var bb := bg.b8
	var i := 0
	while i < data.size():
		var dr := data[i] - br
		var dg := data[i + 1] - bgc
		var db := data[i + 2] - bb
		if sqrt(float(dr * dr + dg * dg + db * db)) < KEY_DIST:
			# 색까지 지운다. 남겨 두면 크기를 바꿀 때 자홍색이 가장자리로 번진다.
			data[i] = 0
			data[i + 1] = 0
			data[i + 2] = 0
			data[i + 3] = 0
		i += 4

	var alpha := PackedByteArray()
	alpha.resize(w * h)
	for p in w * h:
		alpha[p] = data[p * 4 + 3]
	for y in range(1, h - 1):
		for x in range(1, w - 1):
			var p := y * w + x
			if alpha[p] == 0:
				continue
			if alpha[p - 1] != 0 and alpha[p + 1] != 0 and alpha[p - w] != 0 and alpha[p + w] != 0:
				continue
			var o := p * 4
			var r := data[o]
			var g := data[o + 1]
			var b := data[o + 2]
			var m := mini(r, b) - g
			if m > FRINGE:
				var t := clampf(float(m - FRINGE) / 120.0, 0.0, 1.0)
				data[o + 3] = int(data[o + 3] * (1.0 - t * 0.85))
				data[o] = mini(r, g + 24)
				data[o + 2] = mini(b, g + 24)
	img.set_data(w, h, false, Image.FORMAT_RGBA8, data)
