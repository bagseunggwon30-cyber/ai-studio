# 연습용(--fake) 회사에서만 쓴다: 가짜 실행기가 돌려준 그림(지금 모습 그대로)의 옷 색만 돌려 새 옷처럼 보이게 한다.
# 진짜 그림 생성(Codex·Grok)에는 쓰지 않는다 (감독 프로그램 engine._draw가 연습용일 때만 부른다).
#
#   godot --headless --path tools/sprites --script res://fake_tint.gd -- --root=<프로젝트 폴더> --in=<그림> --out=<결과.png> --hue=<도> \
#         [--h=<시작>,<끝> --s=<최소>,<최대> --v=<최소>,<최대> | --auto=1]
#
# 돌릴 픽셀: sheets.json 색 규칙(parts[<캐릭터>].outfit의 색상·채도·밝기)을 --h --s --v로 받으면 그 규칙에 맞는 픽셀만.
# 규칙이 없으면(--auto=1: 새 직원, 다른 세트 위에 다시 꾸민 모습) 채도가 높은 픽셀 중 피부·머리 갈색 쪽(0~55도, 340~360도)을 뺀 것.
# 자홍 배경(#FF00FF)은 건드리지 않는다. 돌린 색이 배경과 비슷해지면 자르기 도구가 배경으로 지우므로, 옷 색의 평균이
# 자홍 쪽으로 가지 않게 각도를 더 돌리고, 그래도 배경과 가까운 픽셀은 그대로 둔다.
# 빨강·주황·갈색 쪽(피부·머리와 같은 색)으로도 돌리지 않는다: 그러면 다음 주문 때 자동 규칙이 그 옷을 피부로 보고 색을 안 바꾼다.
# 그래서 돌린 옷 색은 언제나 55~265도(노랑·초록·청록·파랑)에 놓인다.
extends SceneTree

const SRC_BG_DIST := 110.0   # 원본에서 자홍 배경으로 볼 거리 (자르기 도구의 KEY_DIST 90보다 조금 넓게)
const OUT_BG_DIST := 130.0   # 돌린 색이 배경과 이만큼 가까우면 그 픽셀은 그대로
const DANGER_FROM := 265.0   # 이 색상 이상(자홍·빨강 쪽)이거나
const DANGER_TO := 55.0      # 이 색상 미만(빨강·주황·갈색 쪽)이면 피한다


func _initialize() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		if kv.size() == 2:
			args[kv[0]] = kv[1]
	var root: String = args.get("root", "")
	if not args.has("in") or not args.has("out") or not args.has("hue"):
		push_error("--in=<그림> --out=<결과.png> --hue=<도> 가 필요합니다")
		quit(2)
		return
	var img := Image.load_from_file(_abs(root, args["in"]))
	if img == null or img.is_empty():
		push_error("그림을 읽을 수 없음: " + String(args["in"]))
		quit(2)
		return
	img.convert(Image.FORMAT_RGBA8)

	var rule := {}
	if not args.has("auto") and args.has("h") and args.has("s") and args.has("v"):
		for k in ["h", "s", "v"]:
			var pair := String(args[k]).split(",")
			if pair.size() != 2:
				push_error("--%s=<최소>,<최대> 모양이어야 합니다" % k)
				quit(2)
				return
			rule[k] = [float(pair[0]), float(pair[1])]

	var w := img.get_width()
	var h := img.get_height()
	var data := img.get_data()

	# 1) 옷 픽셀을 고르고 평균 색상을 잰다 (색상은 원 위에서: sin/cos 평균)
	var picked := PackedInt32Array()
	var sum_cos := 0.0
	var sum_sin := 0.0
	for p in w * h:
		var o := p * 4
		if data[o + 3] < 128 or _near_bg(data[o], data[o + 1], data[o + 2], SRC_BG_DIST):
			continue
		var c := Color8(data[o], data[o + 1], data[o + 2])
		if _is_outfit(c, rule):
			picked.append(p)
			sum_cos += cos(c.h * TAU)
			sum_sin += sin(c.h * TAU)

	var shift := float(args["hue"])
	if picked.is_empty():
		print("옷 픽셀을 찾지 못해 그림을 그대로 둡니다: ", args["in"])
	else:
		var mean := fposmod(atan2(sum_sin, sum_cos) / TAU, 1.0) * 360.0
		for i in 24:
			var target := fposmod(mean + shift, 360.0)
			var turn := fposmod(shift, 360.0)  # 한 바퀴에 가깝게 돌면 색이 그대로라 너무 작게(45도 미만) 돌리지 않는다
			if target < DANGER_FROM and target >= DANGER_TO and turn >= 45.0 and turn <= 315.0:
				break
			shift += 15.0
		# 2) 골라 둔 픽셀의 색상만 돌린다 (채도·밝기는 그대로라 음영이 남는다)
		var changed := 0
		for p in picked:
			var o := p * 4
			var c := Color8(data[o], data[o + 1], data[o + 2])
			var n := Color.from_hsv(fposmod(c.h + shift / 360.0, 1.0), c.s, c.v)
			if _near_bg(n.r8, n.g8, n.b8, OUT_BG_DIST):
				continue
			data[o] = n.r8
			data[o + 1] = n.g8
			data[o + 2] = n.b8
			changed += 1
		print("옷 색 %d도 돌림: 픽셀 %d개 (평균 색상 %d도)" % [int(shift), changed, int(mean)])

	img.set_data(w, h, false, Image.FORMAT_RGBA8, data)
	var dst := _abs(root, args["out"])
	DirAccess.make_dir_recursive_absolute(dst.get_base_dir())
	if img.save_png(dst) != OK:
		push_error("저장 실패: " + dst)
		quit(2)
		return
	quit(0)


static func _near_bg(r: int, g: int, b: int, dist: float) -> bool:
	var dr := 255 - r
	var dg := g
	var db := 255 - b
	return sqrt(float(dr * dr + dg * dg + db * db)) < dist


static func _in_hue(hue: float, r: Array) -> bool:
	var a := float(r[0])
	var b := float(r[1])
	return (hue >= a and hue <= b) if a <= b else (hue >= a or hue <= b)


# 색 규칙이 있으면 그 규칙(make_masks.gd의 _match와 같은 색상·채도·밝기), 없으면 자동 (채도 높고 피부·갈색이 아닌 것)
static func _is_outfit(c: Color, rule: Dictionary) -> bool:
	var hue := c.h * 360.0
	if rule.is_empty():
		return c.s >= 0.35 and c.v >= 0.3 and hue >= 55.0 and hue < 340.0
	return _in_hue(hue, rule["h"]) and c.s >= float(rule["s"][0]) and c.s <= float(rule["s"][1]) \
		and c.v >= float(rule["v"][0]) and c.v <= float(rule["v"][1])


static func _abs(root: String, p: String) -> String:
	return p if p.is_absolute_path() else root.path_join(p)
