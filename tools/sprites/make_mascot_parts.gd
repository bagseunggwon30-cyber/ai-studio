# 진행판 발표 캐릭터 '하나'의 부위별 그림 (라이브2D식 층): assets-raw/mascot/*.png → assets-raw/mascot/parts/
#
#   godot --headless --path tools/sprites --script res://make_mascot_parts.gd -- --root=<프로젝트 폴더> [--height=800] [--only=blink,eyes-half,mouth-closed,mouth-half,hair] [--feather=4]
#
# make_mascot.gd와 같은 초록 지우기(_key)·자르기 상자(평소·기쁨·걱정 세 표정으로 정함)·크기(높이 800)로 바꾼 뒤,
# 평소 그림(normal)과 달라진 곳만 뽑아 낸다. 결과는 assets-raw/mascot/parts/ 에만 쓴다 (ui/에는 쓰지 않음 — 통합은 따로).
#
# 조각 (blink · eyes-half · mouth-closed · mouth-half): blink처럼 평소 그림과 달라진 '가장 큰 촘촘한 덩어리'(위 45%)만 잘라
#   parts/<이름>.png + 자리(x,y,w,h). 전체에서 달라진 픽셀이 너무 많으면(그림이 밀림) 거절한다 → 그 이름을 다시 그려야 함.
#   blink는 지금 ui/assets/mascot/blink.png와 같은 조각·자리가 나오는지 확인하는 시험용 (ui/는 읽기만).
# 머리카락 (nohair.png = 긴 머리를 지우고 밑을 채운 그림):
#   평소와 nohair가 달라진 가장 큰 덩어리(위아래 전체)의 칸 안에서 실제로 다른 픽셀 → 2px 넓히고 2px 부드럽게 = 마스크.
#   parts/hair.png            530×800 전체 크기. 마스크 안에서만 평소 그림 (알파 = 원래 알파 × 마스크), 나머지 투명
#   parts/normal-nohair.png   마스크 밖은 평소, 안은 nohair (마스크로 섞음). happy·worried·point도 같은 방식 (<표정>-nohair.png)
#   parts/check-*.png         눈으로 보기용 합성 (크림색 바탕)
# 마지막에 PARTS {json} 한 줄을 출력하고 parts/parts.json에도 저장한다.
#
# 사장님 그림 (이미 잘라 둔 그림 + GPT로 한 곳만 고친 그림들):
#   godot --headless --path tools/sprites --script res://make_mascot_parts.gd -- --prepared --source=<폴더> [--normal=<normal.png 경로>] --out=<폴더> [--align=none] [--eyes=x,y,w,h] [--mouth=x,y,w,h]
#   (--source와 --out을 모두 주면 --root는 필요 없다)
#   <폴더>에 normal.png (배경이 투명하거나 초록/단색인 완성 그림, 크기 그대로 씀), nohair.png · mouth-closed.png · mouth-half.png · eyes-half.png (있는 것만).
#   고친 그림은 크기·위치·배경이 원본과 조금 달라도 된다: 배경(투명·초록·단색)을 지우고 (단색 배경은 머리카락·목 사이에 갇힌 배경 조각도),
#   원본 자리에 자동으로 맞춘다 (가로·세로 크기와 이동을 찾아 겹침 — 맞춘 그림은 out 폴더의 aligned-*.png, 찾은 값은 parts.json의 inputs).
#   순서: 머리카락 먼저(사장님 그림) → 조각. 조각(눈·입)을 찾을 때는 머리카락이 있던 곳을 빼고, 두 그림을 살짝 흐리게 해 비교한다 (다시 그리며 생긴 얇은 잔번짐이 입 모양 변화보다 크게 잡히지 않게).
#   반쯤 연 입은 다문 입을 찾은 자리 근처에서만 찾는다. 그래도 엉뚱한 곳을 자르면 --eyes=/--mouth= 로 눈·입이 있는 곳(원본 그림 좌표)을 알려 준다: 그 안에서만 찾는다.
#   색만 다른 곳은 1픽셀 어긋난 것(양쪽 이웃과 모두 맞을 때)을 같은 곳으로 본다. 알파가 크게 다르거나 얇은 선이 사라진 곳(지운 머리카락 올, 닫은 입에서 사라진 아랫입술 윤곽)은 다른 곳이다.
#   맞춘 뒤에도 원본과 너무 다르면(평균 색 차이 24 넘음, 바뀐 곳이 그림의 6% 넘음) 그 그림만 거절한다. 픽셀 기준값(칸 크기·번짐 폭 등)은 그림 높이/800에 비례해 늘린다 (800이면 그대로).
extends SceneTree

const MOODS := ["normal", "happy", "worried"]
const PIECES := ["blink", "eyes-half", "mouth-closed", "mouth-half"]
const HAIR_SRC := "nohair"
const HAIR_MOODS := ["happy", "worried", "point"]
const DIFF := 48     # 두 그림의 한 픽셀이 이만큼(채널 최대 차) 다르면 '바뀐 곳'
const LO := 30.0    # 초록기(g - max(r,b))가 이보다 작으면 불투명
const HI := 120.0   # 이보다 크면 투명 (사이는 반투명)
const PAD := 12
const CELL := 8
const CELL_MIN := 10   # 한 칸(64픽셀)에서 이만큼 바뀌어야 '촘촘'
const MASK_GROW := 2   # 마스크를 넓히는 픽셀
const MASK_BLUR := 2   # 마스크 가장자리를 부드럽게 하는 픽셀
const EXTRA_MIN := 150   # 머리카락: 가장 큰 덩어리 옆에 닿은 다른 덩어리는 바뀐 픽셀이 이만큼 이상이면 함께 (팔·옷 위의 머리카락)
const STRAND_REACH := 12  # 머리카락: 덩어리 사각형에서 이만큼 밖까지 가는 올을 찾는다
const STRAND_ALPHA := 100 # 이 알파보다 작아진 곳(배경이 된 곳)의 다른 픽셀은 촘촘한 칸 밖이어도 마스크 재료
const GROW_MIN_DELTA := 14  # 마스크를 넓힌 픽셀은 평소와 색이 이만큼(채널 최대 차)은 달라야 남는다
const EXPAND := 10     # 조각 사각형을 이 안에서 삐져나온 다른 픽셀까지 넓힌다 (새 조각만)
const FEATHER := 4     # 조각 가장자리를 부드럽게 하는 픽셀 (조각을 자를 때 더한 여백 4px와 같다)
const WARN_MOOD := 0.05  # 다른 표정 그림이 마스크 안(마스크 픽셀의 이 비율)을 넘게 평소와 다르면 경고
const BG := Color(0.93, 0.89, 0.83)  # 확인용 합성 그림의 바탕
const ALIGN_CAP := 60.0      # 정렬: 한 픽셀의 색 차이를 이 값에서 자른다 (바뀐 곳이 맞추기를 흔들지 않게)
const ALIGN_MAX_LOSS := 24.0 # 정렬 뒤 평균 차이(0~60)가 이보다 크면 그림이 딴판이라 거절
const BG_LO := 14.0   # 단색 배경 지우기: 배경색과 이만큼(채널 최대 차)까지는 (바깥에서 이어진 곳만) 완전 투명
const BG_HI := 64.0   # 가장자리 반투명: 이 차이까지는 배경이 섞인 것으로 보고 색을 되돌린다

# 그림 크기(높이/800)에 맞춘 픽셀 기준값 — _set_scale이 정한다 (높이 800이면 위의 상수와 똑같다)
var _k := 1.0
var _cell := CELL
var _cell_min := CELL_MIN
var _mask_grow := MASK_GROW
var _mask_blur := MASK_BLUR
var _extra_min := EXTRA_MIN
var _strand_reach := STRAND_REACH
var _expand := EXPAND
var _feather_px := FEATHER
var _near := 12
var _prepared := false     # --prepared: 이미 잘라 둔 그림 (사장님 그림)
var _align_on := true
var _bg_notes := {}        # 고친 그림마다 배경·정렬 기록 (parts.json)
var _tol := false          # 사장님 그림: 1픽셀 어긋난 것은 같은 곳으로 본다 (가장자리 번짐·다시 그린 흔들림에 조각이 흔들리지 않게)
var _wid := 0              # 비교하는 그림의 가로 (_tol에서 이웃 픽셀을 찾을 때)
var _out_dir := ""
var _skip_base := PackedByteArray()  # 머리카락이 있던 곳만 (조각마다 _skip = 이것 + 그 조각의 위치 힌트 밖)
var _hints := {}            # 조각 이름 → 그 조각이 있을 곳 (--eyes=, --mouth=: x,y,w,h). 잔번짐이 큰 그림에서 엉뚱한 곳을 자르지 않게
var _skip := PackedByteArray()   # 사장님 그림: 머리카락이 있던 곳(1) — 조각(눈·입)을 찾을 때 바뀐 곳으로 세지 않는다


func _initialize() -> void:
	var root := ""
	var height := 800
	var only := PackedStringArray()
	var feather_opt := -1
	var source := ""
	var out_opt := ""
	var normal_opt := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
		elif a.begins_with("--height="):
			height = int(a.substr(9))
		elif a.begins_with("--feather="):
			feather_opt = int(a.substr(10))
		elif a.begins_with("--only="):
			only = a.substr(7).split(",", false)
		elif a == "--prepared":
			_prepared = true
		elif a.begins_with("--source="):
			source = a.substr(9)
		elif a.begins_with("--out="):
			out_opt = a.substr(6)
		elif a.begins_with("--normal="):
			normal_opt = a.substr(9)
		elif a.begins_with("--eyes=") or a.begins_with("--mouth="):
			var rc := _parse_rect(a.substr(a.find("=") + 1))
			if rc.size == Vector2i.ZERO:
				push_error("위치는 x,y,w,h 로 적어 주세요: " + a)
				quit(2)
				return
			for piece in (["eyes-half"] if a.begins_with("--eyes=") else ["mouth-closed", "mouth-half"]):
				_hints[piece] = rc
		elif a.begins_with("--align="):
			_align_on = a.substr(8) != "none"
	if root == "" and (source == "" or out_opt == ""):
		push_error("--root=<프로젝트 폴더> 가 필요합니다 (--source=와 --out=을 모두 주면 생략 가능)")
		quit(2)
		return
	var raw_dir: String = (source if source != "" else root + "/assets-raw/mascot").trim_suffix("/") + "/"
	var out_dir: String = (out_opt if out_opt != "" else raw_dir + "parts").trim_suffix("/") + "/"
	DirAccess.make_dir_recursive_absolute(out_dir)
	_out_dir = out_dir

	# 1) 기본 하나: make_mascot.gd와 같은 상자·크기 (세 표정으로만 정한다). --prepared(사장님 그림): normal.png를 잘라 둔 그대로 쓴다
	var imgs := {}
	var box := Rect2i()
	var width := 0
	var src_size := Vector2i.ZERO
	var outs := {}
	if _prepared:
		var normal_path := normal_opt if normal_opt != "" else raw_dir + "normal.png"
		var nimg := Image.load_from_file(normal_path)
		if nimg == null or nimg.is_empty():
			push_error("그림을 읽을 수 없음: " + normal_path)
			quit(2)
			return
		nimg.convert(Image.FORMAT_RGBA8)
		var kind := _bg_kind(nimg)
		if kind == "green":
			_key(nimg)
		elif kind == "solid":
			_remove_solid_bg(nimg)
		elif kind == "unknown":
			push_error("normal.png의 배경을 알 수 없어요 (투명·초록·단색 중 하나여야 해요)")
			quit(2)
			return
		_clean_alpha(nimg)
		width = nimg.get_width()
		height = nimg.get_height()
		src_size = nimg.get_size()
		box = Rect2i(Vector2i.ZERO, src_size)
		outs["normal"] = nimg
		_bg_notes["normal"] = {"bg": kind}
		_tol = true
		_wid = width
	else:
		for mood in MOODS:
			var img := Image.load_from_file(raw_dir + mood + ".png")
			if img == null or img.is_empty():
				push_error("그림을 읽을 수 없음: " + raw_dir + mood + ".png")
				quit(2)
				return
			img.convert(Image.FORMAT_RGBA8)
			_key(img)
			var r := img.get_used_rect()
			box = r if box.size == Vector2i.ZERO else box.merge(r)
			imgs[mood] = img
		var any: Image = imgs["normal"]
		src_size = any.get_size()
		box = box.grow(PAD).intersection(Rect2i(Vector2i.ZERO, src_size))
		width = int(round(box.size.x * float(height) / box.size.y))
		for mood in MOODS:
			var img: Image = imgs[mood]
			_bleed(img, 4)
			var out := img.get_region(box)
			out.resize(width, height, Image.INTERPOLATE_LANCZOS)
			_clean_alpha(out)
			outs[mood] = out
	_set_scale(height)
	var feather_px := feather_opt if feather_opt >= 0 else _feather_px
	var normal: Image = outs["normal"]
	var report := {
		"size": {"w": width, "h": height},
		"box": {"x": box.position.x, "y": box.position.y, "w": box.size.x, "h": box.size.y},
		"pieces": {},
		"problems": [],
	}
	var problems: Array = report["problems"]

	# 머리카락 (3): 기본 하나는 조각 다음에, 사장님 그림은 조각보다 먼저 — 머리카락이 있던 곳은 조각 찾기에서 뺀다 (_skip)
	var do_hair := func() -> void:
		if only.is_empty() or "hair" in only:
			var hair_path: String = raw_dir + HAIR_SRC + ".png"
			if FileAccess.file_exists(hair_path):
				var nh := _load_edit("nohair", hair_path, box, width, height, src_size, normal)
				if nh == null:
					problems.append({"name": "hair", "error": "nohair 그림을 쓸 수 없음 (읽기 실패, 크기가 다름, 또는 원본과 너무 달라 맞추지 못함)"})
				else:
					report["hair"] = _hair(root, raw_dir, out_dir, box, width, height, outs, nh, problems)
	if _prepared:
		do_hair.call()
		_skip_base = _skip

	# 2) 조각
	var det_normal: Image = null
	var mouth_rect := Rect2i()
	for piece_name in PIECES:
		if not only.is_empty() and not (piece_name in only):
			continue
		if _prepared and piece_name == "blink":
			continue  # 사장님 그림의 감은 눈(blink.png)은 전신 그림 그대로 쓴다 (뼈대의 eyes 영역 마스크)
		_skip = _skip_base
		if _hints.has(piece_name):
			_skip = _skip_outside(_hints[piece_name], width, height, _skip_base)
		elif _prepared and piece_name == "mouth-half" and mouth_rect.size != Vector2i.ZERO:
			# 반쯤 연 입은 다문 입과 같은 입이다: 다문 입을 찾은 자리 근처에서만 찾는다 (다른 곳의 잔번짐이 더 크게 잡히지 않게)
			_skip = _skip_outside(mouth_rect.grow(_expand * 2), width, height, _skip_base)
		var path: String = raw_dir + piece_name + ".png"
		if not FileAccess.file_exists(path):
			continue
		var out := _load_edit(piece_name, path, box, width, height, src_size, normal)
		if out == null:
			problems.append({"name": piece_name, "error": "그림을 쓸 수 없음 (읽기 실패, 크기가 다름, 또는 원본과 너무 달라 맞추지 못함)"})
			continue
		# 조각 찾기용 그림: 사장님 그림은 둘 다 살짝 흐리게 해서 비교한다 (다시 그리며 생긴 얇은 잔번짐은 지워지고, 입 안쪽 색처럼 넓은 변화는 남는다)
		var det_a: Image = normal
		var det_b: Image = out
		if _prepared:
			if det_normal == null:
				det_normal = _lowpass(normal)
			det_a = det_normal
			det_b = _lowpass(out)
		var whole := _diff_count(det_a, det_b, Rect2i(Vector2i.ZERO, out.get_size()))
		var r := _diff_blob(det_a, det_b, int(height * 0.45), _cell_min)["rect"] as Rect2i
		if r.size == Vector2i.ZERO or whole > out.get_width() * out.get_height() * (0.06 if _prepared else 0.02):
			var msg := "평소 그림과 너무 달라요 (바뀐 픽셀 %d) — 다시 그려 주세요" % whole
			push_error(piece_name + ": " + msg)
			problems.append({"name": piece_name, "error": msg, "changed": whole})
			continue
		# blink는 지금 화면에 쓰는 조각과 똑같이 두고(시험용), 새 조각은 (1) 촘촘한 덩어리 밖 가까이(EXPAND px)에 삐져나온 다른 픽셀까지 사각형을 넓히고
		# (입꼬리 끝처럼 가는 곳이 잘리지 않게) (2) 가장자리 4px의 알파를 서서히 줄여 평소 그림과 색이 조금 달라도 경계가 안 보이게 한다
		var legacy: bool = piece_name == "blink"
		var feather := 0 if legacy else feather_px
		if not legacy:
			r = _expand_rect(det_a, det_b, r, int(height * 0.45))
		r = r.grow(_feather_px).intersection(Rect2i(Vector2i.ZERO, out.get_size()))  # (기본 하나: 4px = 가장자리 흐림 폭과 같다)
		if piece_name == "mouth-closed":
			mouth_rect = r
		var piece := out.get_region(r)
		if feather > 0:
			_feather(piece, feather)
		if piece.save_png(out_dir + piece_name + ".png") != OK:
			problems.append({"name": piece_name, "error": "저장 실패"})
			continue
		var info := {"x": r.position.x, "y": r.position.y, "w": r.size.x, "h": r.size.y, "changed": whole, "feather": feather}
		# 평소 그림 위에 겹쳐 본다 (겹쳐서 평소와 달라진 픽셀 = 조각이 바꾼 곳)
		var comp: Image = normal.duplicate()
		comp.blend_rect(piece, Rect2i(Vector2i.ZERO, piece.get_size()), r.position)
		# 조각이 다 담지 못한 것: 새로 그린 그림(out)과 평소에 조각을 겹친 그림(comp)이 조각 둘레(12px)에서 아직 다른 픽셀 수 (0에 가까워야 함).
		# 먼 곳의 흩어진 차이(Codex가 머리카락·옷 무늬를 조금씩 다시 그린 것)는 일부러 쓰지 않으니 세지 않는다
		info["residual_near"] = _diff_count(out, comp, r.grow(_near).intersection(Rect2i(Vector2i.ZERO, out.get_size())))
		info["changed_inside"] = _diff_count(normal, out, r)
		_residual_img(normal, out, comp, r).save_png(out_dir + "check-" + piece_name + "-residual.png")
		_flatten(comp).save_png(out_dir + "check-" + piece_name + ".png")
		_zoom_pair(normal, comp, r).save_png(out_dir + "check-" + piece_name + "-zoom.png")
		if piece_name == "blink":
			# 시험: 지금 화면용 blink.png와 같은 자리·같은 조각이 나오는지 (ui/는 읽기만)
			var ui_path: String = root + "/ui/assets/mascot/blink.png"
			var same_bytes := false
			if FileAccess.file_exists(ui_path):
				same_bytes = FileAccess.get_file_as_bytes(ui_path) == FileAccess.get_file_as_bytes(out_dir + "blink.png")
			info["same_as_ui_blink_bytes"] = same_bytes
		report["pieces"][piece_name] = info

	_skip = _skip_base
	if not _prepared:
		do_hair.call()  # 3) 머리카락
	if not _bg_notes.is_empty():
		report["inputs"] = _bg_notes
	var text := JSON.stringify(report)
	print("PARTS " + text)
	var f := FileAccess.open(out_dir + "parts.json", FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(report, "  ") + "\n")
		f.close()
	quit(0)


# 머리카락 층: 마스크를 만들고 hair.png와 <표정>-nohair.png를 쓴다.
func _hair(root: String, raw_dir: String, out_dir: String, box: Rect2i, width: int, height: int,
		outs: Dictionary, nh: Image, problems: Array) -> Dictionary:
	var normal: Image = outs["normal"]
	var full := Rect2i(0, 0, width, height)
	var whole := _diff_count(normal, nh, full)
	var blob := _diff_blob(normal, nh, height, _cell_min, _extra_min)
	var rect: Rect2i = blob["rect"]
	if rect.size == Vector2i.ZERO:
		problems.append({"name": "hair", "error": "nohair가 평소 그림과 거의 같아요 — 다시 그려 주세요"})
		return {}
	var cells: PackedByteArray = blob["cells"]
	var cw: int = blob["cw"]
	var nd := normal.get_data()
	var hd := nh.get_data()
	# 덩어리 칸 안에서 실제로 다른 픽셀
	var raw := PackedByteArray()
	raw.resize(width * height)
	var raw_count := 0
	var strand_count := 0
	var faint_count := 0
	var strand_area := rect.grow(_strand_reach).intersection(full)
	for y in range(strand_area.position.y, strand_area.end.y):
		for x in range(strand_area.position.x, strand_area.end.x):
			var o := (y * width + x) * 4
			if not _differs(nd, hd, o):
				# 알파가 작아 '달라졌다'고 잡히지 않은 흐린 머리카락 끝: 평소엔 조금 있고 nohair에선 아무것도 없는 머리색 픽셀
				if hd[o + 3] < 8 and nd[o + 3] >= 8 and _hairish(nd, o):
					raw[y * width + x] = 1
					faint_count += 1
				continue
			if rect.has_point(Vector2i(x, y)) and cells[(y / _cell) * cw + x / _cell] != 0:
				raw[y * width + x] = 1
				raw_count += 1
			elif hd[o + 3] < STRAND_ALPHA:
				# 촘촘한 칸 밖의 가는 머리카락 올: 평소엔 있고 nohair에선 배경이 된 곳
				raw[y * width + x] = 1
				strand_count += 1
	var area := rect.grow(_strand_reach + _mask_grow + _mask_blur + 2).intersection(full)
	var grown := _dilate(raw, width, height, area, _mask_grow)
	# 넓힌 곳(바뀌지 않은 픽셀) 중 투명하지도 머리색(갈색)도 아닌 것은 뺀다 — 머리카락 틈의 옷·살·귀걸이가 층에 딸려 오지 않게
	var trimmed := 0
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			var k := y * width + x
			if grown[k] != 0 and raw[k] == 0 and _delta(nd, hd, k * 4) < GROW_MIN_DELTA and not _hairish(nd, k * 4):
				grown[k] = 0
				trimmed += 1
	var mask := _blur(grown, width, height, area, _mask_blur)
	var mask_count := 0
	var mask_lo := Vector2i(width, height)
	var mask_hi := Vector2i(-1, -1)
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			if mask[y * width + x] > 0.0:
				mask_count += 1
				mask_lo = Vector2i(mini(mask_lo.x, x), mini(mask_lo.y, y))
				mask_hi = Vector2i(maxi(mask_hi.x, x), maxi(mask_hi.y, y))
	var mrect := Rect2i(mask_lo, mask_hi - mask_lo + Vector2i.ONE)

	# hair.png: 마스크 안에서만 평소 그림 (알파 × 마스크)
	var hair_data := nd.duplicate()
	var i := 3
	while i < hair_data.size():
		hair_data[i] = 0
		i += 4
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			var t := mask[y * width + x]
			if t > 0.0:
				var o := (y * width + x) * 4
				hair_data[o + 3] = clampi(int(round(nd[o + 3] * t)), 0, 255)
	var hair := Image.create_from_data(width, height, false, Image.FORMAT_RGBA8, hair_data)
	_clean_alpha(hair)
	if hair.save_png(out_dir + "hair.png") != OK:
		problems.append({"name": "hair", "error": "hair.png 저장 실패"})

	# <표정>-nohair.png: 그 표정 그림 밖 + nohair 안
	var base_normal := _mix(normal, nh, mask, area)
	if base_normal.save_png(out_dir + "normal-nohair.png") != OK:
		problems.append({"name": "hair", "error": "normal-nohair.png 저장 실패"})
	var warns: Array = []
	var mood_diffs := {}
	var bases := {"normal": base_normal}
	for mood in HAIR_MOODS:
		var mimg: Image
		if outs.has(mood):
			mimg = outs[mood]
		else:
			if _prepared:
				continue  # 사장님 그림은 평소 표정 하나뿐 (다른 표정은 뼈대에서 평소 그림을 쓴다)
			var p: String = raw_dir + mood + ".png"
			if not FileAccess.file_exists(p):
				continue
			mimg = _load_processed(p, box, width, height, Vector2i.ZERO)
			if mimg == null:
				continue
		var md := mimg.get_data()
		var inside := 0
		for y in range(area.position.y, area.end.y):
			for x in range(area.position.x, area.end.x):
				if mask[y * width + x] > 0.5 and _differs(nd, md, (y * width + x) * 4):
					inside += 1
		mood_diffs[mood] = inside
		if inside > WARN_MOOD * mask_count:
			warns.append({"mood": mood, "differs_inside_mask": inside, "of_mask_pixels": mask_count})
		var mixed := _mix(mimg, nh, mask, area)
		if mixed.save_png(out_dir + mood + "-nohair.png") != OK:
			problems.append({"name": "hair", "error": mood + "-nohair.png 저장 실패"})
		bases[mood] = mixed

	# 확인: hair.png를 normal-nohair.png 위에 겹친 것이 normal.png와 거의 같은가
	var comp: Image = base_normal.duplicate()
	comp.blend_rect(hair, full, Vector2i.ZERO)
	var comp_diff := _diff_count(normal, comp, full)
	var comp_diff_area := _diff_count(normal, comp, area)
	var opaque := 0
	i = 3
	while i < nd.size():
		if nd[i] > 127:
			opaque += 1
		i += 4
	# 달라진 픽셀 그림: 흰색 = 마스크 재료(덩어리 칸 안), 빨강 = 달라졌지만 마스크에 못 들어간 것 (남은 머리카락 조각 찾기)
	var dimg := Image.create(width, height, false, Image.FORMAT_RGB8)
	dimg.fill(Color(0.12, 0.12, 0.12))
	for y in height:
		for x in width:
			if _differs(nd, hd, (y * width + x) * 4):
				dimg.set_pixel(x, y, Color(1, 1, 1) if raw[y * width + x] != 0 else Color(1, 0.1, 0.1))
	dimg.save_png(out_dir + "check-hair-diff.png")
	_flatten(comp).save_png(out_dir + "check-hair-composite.png")
	_flatten(base_normal).save_png(out_dir + "check-normal-nohair.png")
	_flatten(hair).save_png(out_dir + "check-hair-only.png")
	# 마스크 그림 (흰색 = 마스크 1)
	var mimg2 := Image.create(width, height, false, Image.FORMAT_RGB8)
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			var v := mask[y * width + x]
			mimg2.set_pixel(x, y, Color(v, v, v))
	mimg2.save_png(out_dir + "check-hair-mask.png")
	# 다른 표정 위에서도 겹쳐 본다 (hair.png는 평소 그림에서 왔으므로 자리가 같으면 자연스러워야 함)
	for mood in HAIR_MOODS:
		if not bases.has(mood) or mood == "normal":
			continue
		var c2: Image = (bases[mood] as Image).duplicate()
		c2.blend_rect(hair, full, Vector2i.ZERO)
		_flatten(c2).save_png(out_dir + "check-hair-on-" + mood + ".png")

	if _prepared:
		var seed := PackedByteArray()
		seed.resize(width * height)
		for y in range(area.position.y, area.end.y):
			for x in range(area.position.x, area.end.x):
				if mask[y * width + x] > 0.05:
					seed[y * width + x] = 1
		var wide := _mask_grow * 2 + 1
		_skip = _dilate(seed, width, height, area.grow(wide).intersection(full), wide)
	return {
		"mask_rect": {"x": mrect.position.x, "y": mrect.position.y, "w": mrect.size.x, "h": mrect.size.y},
		"blob_rect": {"x": rect.position.x, "y": rect.position.y, "w": rect.size.x, "h": rect.size.y},
		"changed_whole": whole,
		"raw_pixels": raw_count,
		"strand_pixels": strand_count,
		"faint_pixels": faint_count,
		"trimmed_pixels": trimmed,
		"joined_blobs": blob["joined"],
		"mask_pixels": mask_count,
		"check": {"composite_diff": comp_diff, "composite_diff_in_area": comp_diff_area, "opaque_pixels": opaque},
		"mood_differs_inside_mask": mood_diffs,
		"warns": warns,
		"files": ["hair.png", "normal-nohair.png"] + HAIR_MOODS.map(func(m): return m + "-nohair.png"),
	}


# 초록 지우기 → 번짐 채우기 → 상자로 자르기 → 줄이기 → 알파 정리 (make_mascot.gd의 애니메이션 그림과 같은 순서).
# want_size가 (0,0)이면 크기 검사를 하지 않는다 (원본은 항상 1024x1536이어야 하지만 표정 그림은 이미 걸러졌다).
func _load_processed(path: String, box: Rect2i, width: int, height: int, want_size: Vector2i) -> Image:
	var img := Image.load_from_file(path)
	if img == null or img.is_empty():
		push_error("그림을 읽을 수 없음: " + path)
		return null
	if want_size != Vector2i.ZERO and img.get_size() != want_size:
		push_error("그림을 쓸 수 없음 (크기가 다름): " + path)
		return null
	img.convert(Image.FORMAT_RGBA8)
	_key(img)
	_bleed(img, 4)
	var out := img.get_region(box)
	out.resize(width, height, Image.INTERPOLATE_LANCZOS)
	_clean_alpha(out)
	return out


# 조각 가장자리에서 f픽셀 안쪽까지 알파를 서서히 줄인다 (맨 가장자리 = 알파 1/(f+1), f픽셀 안쪽부터 그대로)
func _feather(img: Image, f: int) -> void:
	var w := img.get_width()
	var h := img.get_height()
	var d := img.get_data()
	for y in h:
		for x in w:
			var dist := mini(mini(x, y), mini(w - 1 - x, h - 1 - y))
			if dist >= f:
				continue
			var o := (y * w + x) * 4
			d[o + 3] = int(round(d[o + 3] * float(dist + 1) / float(f + 1)))
	img.set_data(w, h, false, Image.FORMAT_RGBA8, d)


# 알파를 섞은 색으로 두 그림을 마스크(0..1)로 섞는다: 마스크 0 = a, 1 = b. (마스크 밖은 a 그대로)
func _mix(a: Image, b: Image, m: PackedFloat32Array, area: Rect2i) -> Image:
	var w := a.get_width()
	var ad := a.get_data()
	var bd := b.get_data()
	var od := ad.duplicate()
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			var k := y * w + x
			var t := m[k]
			if t <= 0.0:
				continue
			var o := k * 4
			var aa := ad[o + 3] / 255.0
			var ba := bd[o + 3] / 255.0
			var alpha := aa * (1.0 - t) + ba * t
			for c in 3:
				var v: float
				if alpha > 0.001:
					v = (ad[o + c] * aa * (1.0 - t) + bd[o + c] * ba * t) / alpha
				else:
					v = ad[o + c] * (1.0 - t) + bd[o + c] * t
				od[o + c] = clampi(int(round(v)), 0, 255)
			od[o + 3] = clampi(int(round(alpha * 255.0)), 0, 255)
	var res := Image.create_from_data(w, a.get_height(), false, Image.FORMAT_RGBA8, od)
	_clean_alpha(res)
	return res


# 사각(체비쇼프) 넓히기: 0/1 마스크를 g픽셀 넓힌다 (area 안에서만 계산)
func _dilate(m: PackedByteArray, w: int, h: int, area: Rect2i, g: int) -> PackedByteArray:
	var tmp := PackedByteArray()
	tmp.resize(m.size())
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			for dx in range(-g, g + 1):
				var nx := x + dx
				if nx >= 0 and nx < w and m[y * w + nx] != 0:
					tmp[y * w + x] = 1
					break
	var res := PackedByteArray()
	res.resize(m.size())
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			for dy in range(-g, g + 1):
				var ny := y + dy
				if ny >= 0 and ny < h and tmp[ny * w + x] != 0:
					res[y * w + x] = 1
					break
	return res


# 상자 흐림(가로·세로 한 번씩): 0/1 마스크의 가장자리를 b픽셀 부드럽게 (0..1)
func _blur(m: PackedByteArray, w: int, h: int, area: Rect2i, b: int) -> PackedFloat32Array:
	var n := float(2 * b + 1)
	var tmp := PackedFloat32Array()
	tmp.resize(m.size())
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			var s := 0.0
			for dx in range(-b, b + 1):
				var nx := clampi(x + dx, 0, w - 1)
				s += m[y * w + nx]
			tmp[y * w + x] = s / n
	var res := PackedFloat32Array()
	res.resize(m.size())
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			var s := 0.0
			for dy in range(-b, b + 1):
				var ny := clampi(y + dy, 0, h - 1)
				s += tmp[ny * w + x]
			res[y * w + x] = s / n
	return res


# 크림색 바탕에 얹은 확인용 그림
func _flatten(img: Image) -> Image:
	var bg := Image.create(img.get_width(), img.get_height(), false, Image.FORMAT_RGBA8)
	bg.fill(BG)
	bg.blend_rect(img, Rect2i(Vector2i.ZERO, img.get_size()), Vector2i.ZERO)
	return bg


# 사각형 r 둘레 EXPAND px 안에서 달라진 픽셀이 있으면 사각형이 그것까지 덮도록 넓힌다 (위쪽 max_y 줄 안에서만)
func _expand_rect(a: Image, b: Image, r: Rect2i, max_y: int) -> Rect2i:
	var da := a.get_data()
	var db := b.get_data()
	var w := a.get_width()
	var reach := r.grow(_expand).intersection(Rect2i(0, 0, w, max_y))
	var lo := r.position
	var hi := r.end - Vector2i.ONE
	for y in range(reach.position.y, reach.end.y):
		for x in range(reach.position.x, reach.end.x):
			if _differs(da, db, (y * w + x) * 4) and not _skipped(y * w + x):
				lo = Vector2i(mini(lo.x, x), mini(lo.y, y))
				hi = Vector2i(maxi(hi.x, x), maxi(hi.y, y))
	return Rect2i(lo, hi - lo + Vector2i.ONE)


# 조각 둘레(12px)에서 새로 그린 그림이 평소와 다른 곳(빨강 = 조각이 못 담은 곳, 흰색 = 조각이 담은 곳)을 크게 (파란 선 = 조각 사각형)
func _residual_img(normal: Image, out: Image, comp: Image, r: Rect2i) -> Image:
	var zr := r.grow(12).intersection(Rect2i(Vector2i.ZERO, normal.get_size()))
	var nd := normal.get_data()
	var od := out.get_data()
	var cd := comp.get_data()
	var w := normal.get_width()
	var img := Image.create(zr.size.x, zr.size.y, false, Image.FORMAT_RGB8)
	img.fill(Color(0.12, 0.12, 0.12))
	for y in range(zr.position.y, zr.end.y):
		for x in range(zr.position.x, zr.end.x):
			var o := (y * w + x) * 4
			if _differs(nd, od, o):
				img.set_pixel(x - zr.position.x, y - zr.position.y, Color(1, 1, 1) if not _differs(cd, od, o) else Color(1, 0.1, 0.1))
	for x in range(r.position.x, r.end.x):
		for y in [r.position.y, r.end.y - 1]:
			img.set_pixel(x - zr.position.x, y - zr.position.y, Color(0.2, 0.4, 1.0))
	for y in range(r.position.y, r.end.y):
		for x in [r.position.x, r.end.x - 1]:
			img.set_pixel(x - zr.position.x, y - zr.position.y, Color(0.2, 0.4, 1.0))
	img.resize(zr.size.x * 8, zr.size.y * 8, Image.INTERPOLATE_NEAREST)
	return img


# 조각 둘레를 크게 키워 (왼쪽 = 평소, 오른쪽 = 조각을 겹친 것) 나란히
func _zoom_pair(normal: Image, comp: Image, r: Rect2i) -> Image:
	var zr := r.grow(40).intersection(Rect2i(Vector2i.ZERO, normal.get_size()))
	var a := _flatten(normal).get_region(zr)
	var b := _flatten(comp).get_region(zr)
	var sbs := Image.create(zr.size.x * 2 + 8, zr.size.y, false, Image.FORMAT_RGBA8)
	sbs.fill(Color(0.2, 0.2, 0.2))
	sbs.blit_rect(a, Rect2i(Vector2i.ZERO, zr.size), Vector2i.ZERO)
	sbs.blit_rect(b, Rect2i(Vector2i.ZERO, zr.size), Vector2i(zr.size.x + 8, 0))
	sbs.resize(sbs.get_width() * 3, sbs.get_height() * 3, Image.INTERPOLATE_CUBIC)
	return sbs


# ---- 사장님 그림(--prepared): 배경 지우기 · 원본 자리에 맞추기 ----

# 그림 높이(/800)에 맞춰 픽셀 기준값을 정한다 (800이면 위의 상수와 똑같다)
func _set_scale(h: int) -> void:
	_k = h / 800.0
	_cell = maxi(4, int(round(CELL * _k)))
	_cell_min = maxi(4, int(round(CELL_MIN * _k * _k)))
	_mask_grow = maxi(1, int(round(MASK_GROW * _k)))
	_mask_blur = maxi(1, int(round(MASK_BLUR * _k)))
	_extra_min = maxi(20, int(round(EXTRA_MIN * _k * _k)))
	_strand_reach = maxi(4, int(round(STRAND_REACH * _k)))
	_expand = maxi(3, int(round(EXPAND * _k)))
	_feather_px = maxi(1, int(round(FEATHER * _k)))
	_near = maxi(4, int(round(12 * _k)))


# 고친 그림 하나를 원본(normal) 자리·크기로 맞춰 읽는다. 기본 하나(--prepared 아님)는 예전 방식 그대로.
# 돌려주는 것: 원본과 같은 크기의 그림 (배경은 투명). 읽을 수 없거나 원본과 너무 달라 맞추지 못하면 null.
func _load_edit(name: String, path: String, box: Rect2i, width: int, height: int, src_size: Vector2i, normal: Image) -> Image:
	if not _prepared:
		return _load_processed(path, box, width, height, src_size)
	var img := Image.load_from_file(path)
	if img == null or img.is_empty():
		push_error("그림을 읽을 수 없음: " + path)
		return null
	img.convert(Image.FORMAT_RGBA8)
	var note := {"size": [img.get_width(), img.get_height()]}
	_bg_notes[name] = note
	var kind := _bg_kind(img)
	note["bg"] = kind
	var bg_color := img.get_pixel(0, 0)
	if kind == "green":
		_key(img)
	elif kind == "solid":
		_remove_solid_bg(img)
	elif kind == "unknown":
		note["error"] = "배경을 알 수 없어요"
		push_error(name + ": 배경을 알 수 없어요 (투명·초록·단색 중 하나여야 해요)")
		return null
	_clean_alpha(img)
	if not _align_on:
		if img.get_size() != normal.get_size():
			note["error"] = "크기가 원본과 달라요"
			push_error(name + ": 크기가 원본과 달라요 (--align=none)")
			return null
		if kind == "solid":
			_clear_pockets(img, normal, bg_color)
		return img
	var res := _align(img, normal)
	note["align"] = res["params"]
	note["loss"] = snappedf(res["loss"], 0.01)
	if res["loss"] > ALIGN_MAX_LOSS:
		note["error"] = "원본과 너무 달라서 맞추지 못했어요"
		push_error("%s: 원본과 너무 달라서 맞추지 못했어요 (평균 차이 %.1f) — 크기와 위치를 원본과 똑같이 다시 만들어 주세요" % [name, res["loss"]])
		return null
	if kind == "solid":
		_clear_pockets(res["img"], normal, bg_color)  # 머리카락·목 사이에 갇힌 배경(테두리와 안 이어진 배경색)도 지운다
	(res["img"] as Image).save_png(_out_dir + "aligned-" + name + ".png")  # 원본 자리에 맞춘 그림 (눈으로 확인용)
	return res["img"]


# 단색 배경 그림에서 테두리와 이어지지 않아 안 지워진 배경 조각: 원본이 '투명'인 자리에 배경색(BG_HI 안)이 있으면 배경이라 보고 지운다 (맞춘 뒤에 부른다)
func _clear_pockets(img: Image, ref: Image, bc: Color) -> void:
	var w := img.get_width()
	var d := img.get_data()
	var rd := ref.get_data()
	var br := int(round(bc.r * 255.0))
	var bg := int(round(bc.g * 255.0))
	var bb := int(round(bc.b * 255.0))
	for i in w * img.get_height():
		var o := i * 4
		if rd[o + 3] < 8 and d[o + 3] > 0 and _near_bg(d, o, br, bg, bb) <= int(BG_HI):
			d[o] = 0
			d[o + 1] = 0
			d[o + 2] = 0
			d[o + 3] = 0
	img.set_data(w, img.get_height(), false, Image.FORMAT_RGBA8, d)


func _rgb_dist(a: Color, b: Color) -> float:
	return maxf(maxf(absf(a.r - b.r), absf(a.g - b.g)), absf(a.b - b.b)) * 255.0


# 배경 종류: transparent(네 모서리 중 셋 이상이 투명) · green(초록 #00FF00) · solid(네 모서리가 같은 한 가지 색, 흰색 등) · unknown
func _bg_kind(img: Image) -> String:
	var w := img.get_width()
	var h := img.get_height()
	var corners: Array[Color] = []
	for p in [Vector2i(0, 0), Vector2i(w - 1, 0), Vector2i(0, h - 1), Vector2i(w - 1, h - 1)]:
		corners.append(img.get_pixelv(p))
	var clear := 0
	var green := 0
	for c in corners:
		if c.a < 0.04:
			clear += 1
		elif c.a > 0.9 and (c.g - maxf(c.r, c.b)) * 255.0 >= HI:
			green += 1
	if clear >= 3:
		return "transparent"
	if green == 4:
		return "green"
	for c in corners:
		if c.a < 0.9 or _rgb_dist(c, corners[0]) > 36.0:
			return "unknown"
	return "solid"


# 단색 배경(흰색 등) 지우기: 가장자리에서 이어진 배경색 영역을 투명하게 하고, 그 경계에 걸친 픽셀은 배경이 섞인 만큼 반투명으로 하며 색을 되돌린다.
func _remove_solid_bg(img: Image) -> void:
	var w := img.get_width()
	var h := img.get_height()
	var d := img.get_data()
	var bc := img.get_pixel(0, 0)
	var br := int(round(bc.r * 255.0))
	var bg := int(round(bc.g * 255.0))
	var bb := int(round(bc.b * 255.0))
	var seen := PackedByteArray()
	seen.resize(w * h)
	var stack: Array[int] = []
	var lo := int(BG_LO)
	for x in w:
		for y in [0, h - 1]:
			if _near_bg(d, (y * w + x) * 4, br, bg, bb) <= lo and seen[y * w + x] == 0:
				seen[y * w + x] = 1
				stack.append(y * w + x)
	for y in h:
		for x in [0, w - 1]:
			if _near_bg(d, (y * w + x) * 4, br, bg, bb) <= lo and seen[y * w + x] == 0:
				seen[y * w + x] = 1
				stack.append(y * w + x)
	while not stack.is_empty():
		var idx: int = stack.pop_back()
		var cx := idx % w
		var cy := idx / w
		for dd in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1)]:
			var nx: int = cx + dd.x
			var ny: int = cy + dd.y
			if nx < 0 or ny < 0 or nx >= w or ny >= h:
				continue
			var n := ny * w + nx
			if seen[n] == 0 and _near_bg(d, n * 4, br, bg, bb) <= lo:
				seen[n] = 1
				stack.append(n)
	# 경계 한 겹: 지워진 곳과 닿은 픽셀 중 배경색에 가까운(BG_HI 이하) 것은 배경이 섞인 것
	var edge := PackedInt32Array()
	for y in h:
		for x in w:
			var k := y * w + x
			if seen[k] != 0:
				continue
			var touch := false
			for dd in [Vector2i(1, 0), Vector2i(-1, 0), Vector2i(0, 1), Vector2i(0, -1), Vector2i(1, 1), Vector2i(-1, -1), Vector2i(1, -1), Vector2i(-1, 1)]:
				var nx: int = x + dd.x
				var ny: int = y + dd.y
				if nx >= 0 and ny >= 0 and nx < w and ny < h and seen[ny * w + nx] != 0:
					touch = true
					break
			if touch and _near_bg(d, k * 4, br, bg, bb) < BG_HI:
				edge.append(k)
	for k in edge:
		var o: int = k * 4
		var dist := float(_near_bg(d, o, br, bg, bb))
		var a := clampf((dist - BG_LO) / (BG_HI - BG_LO), 0.1, 1.0)
		var back := [br, bg, bb]
		for c in 3:
			d[o + c] = clampi(int(round((d[o + c] - (1.0 - a) * back[c]) / a)), 0, 255)
		d[o + 3] = int(round(d[o + 3] * a))
	for k in w * h:
		if seen[k] != 0:
			var o := k * 4
			d[o] = 0
			d[o + 1] = 0
			d[o + 2] = 0
			d[o + 3] = 0
	img.set_data(w, h, false, Image.FORMAT_RGBA8, d)


# 픽셀과 배경색의 채널 최대 차 (배경색과 비슷해도 반투명 픽셀은 '배경 아님'으로 셈: 투명하면 배경으로 본다)
func _near_bg(d: PackedByteArray, o: int, br: int, bg: int, bb: int) -> int:
	if d[o + 3] < 8:
		return 0
	return maxi(maxi(absi(d[o] - br), absi(d[o + 1] - bg)), absi(d[o + 2] - bb))


# 회색 위에 얹어 (투명은 회색) 가로세로 f분의 1로 줄인 비교용 그림: {"w","h","c": RGB 실수 배열}
func _flat_small(img: Image, f: int) -> Dictionary:
	var flat := Image.create(img.get_width(), img.get_height(), false, Image.FORMAT_RGBA8)
	flat.fill(Color(0.5, 0.5, 0.5))
	flat.blend_rect(img, Rect2i(Vector2i.ZERO, img.get_size()), Vector2i.ZERO)
	if f > 1:
		flat.resize(maxi(1, img.get_width() / f), maxi(1, img.get_height() / f), Image.INTERPOLATE_LANCZOS)
	var w := flat.get_width()
	var h := flat.get_height()
	var d := flat.get_data()
	var col := PackedFloat32Array()
	col.resize(w * h * 3)
	for i in w * h:
		col[i * 3] = d[i * 4]
		col[i * 3 + 1] = d[i * 4 + 1]
		col[i * 3 + 2] = d[i * 4 + 2]
	return {"w": w, "h": h, "c": col}


# 원본에서 불투명한 곳의 비교 점 (줄인 그림의 픽셀 번호): 가로세로 step칸마다 하나
func _points(ref: Image, f: int, w: int, h: int, step: int) -> PackedInt32Array:
	var rd := ref.get_data()
	var rw := ref.get_width()
	var pts := PackedInt32Array()
	for y in range(0, h, step):
		for x in range(0, w, step):
			var fx := mini(x * f + f / 2, rw - 1)
			var fy := mini(y * f + f / 2, ref.get_height() - 1)
			if rd[(fy * rw + fx) * 4 + 3] > 200:
				pts.append(y * w + x)
	return pts


# p = [sx, sy, tx, ty] (tx, ty는 원래 크기의 픽셀): 원본 자리 (x,y)가 고친 그림의 ((x-cx)/sx + cx - tx, …)에서 온다고 보고
# 그 점들의 색 차이(채널 최대 차, ALIGN_CAP에서 자름)의 평균. 고친 그림이 그 밖으로 나가면 최대 벌점.
func _align_loss(r: Dictionary, e: Dictionary, pts: PackedInt32Array, f: int, p: Array) -> float:
	var w: int = r["w"]
	var h: int = r["h"]
	var rc: PackedFloat32Array = r["c"]
	var ec: PackedFloat32Array = e["c"]
	var sx: float = p[0]
	var sy: float = p[1]
	var tx: float = p[2] / f
	var ty: float = p[3] / f
	var cx := (w - 1) * 0.5
	var cy := (h - 1) * 0.5
	var total := 0.0
	for idx in pts:
		var x := idx % w
		var y := idx / w
		var u := (x - cx) / sx + cx - tx
		var v := (y - cy) / sy + cy - ty
		if u < 0.0 or v < 0.0 or u > w - 1.001 or v > h - 1.001:
			total += ALIGN_CAP
			continue
		var x0 := int(u)
		var y0 := int(v)
		var fx := u - x0
		var fy := v - y0
		var i00 := (y0 * w + x0) * 3
		var i01 := i00 + w * 3
		var m := 0.0
		for c in 3:
			var top := ec[i00 + c] + (ec[i00 + 3 + c] - ec[i00 + c]) * fx
			var bot := ec[i01 + c] + (ec[i01 + 3 + c] - ec[i01 + c]) * fx
			m = maxf(m, absf(top + (bot - top) * fy - rc[idx * 3 + c]))
		total += minf(m, ALIGN_CAP)
	return total / maxf(pts.size(), 1)


# 좌표 하나씩 ±step으로 움직여 더 나아지면 받아들이는 탐색 (step은 levels번 절반으로 줄인다). [p, loss]
func _descend(r: Dictionary, e: Dictionary, pts: PackedInt32Array, f: int, p: Array, steps: Array, levels: int) -> Array:
	var best := _align_loss(r, e, pts, f, p)
	var st: Array = steps.duplicate()
	for _lv in levels:
		var moved := true
		var guard := 0
		while moved and guard < 24:
			moved = false
			guard += 1
			for i in 4:
				for dir in [-1.0, 1.0]:
					var q: Array = p.duplicate()
					q[i] = q[i] + dir * st[i]
					var l := _align_loss(r, e, pts, f, q)
					if l < best - 0.002:
						best = l
						p = q
						moved = true
						break
		for i in 4:
			st[i] = st[i] * 0.5
	return [p, best]


# 고친 그림(e)을 원본(ref)의 크기·자리에 맞춘다: 먼저 같은 크기로 늘리거나 줄이고 (가로세로 따로),
# 거친 이동(1/8 크기에서 ±8% 안) → 이동·가로세로 배율 다듬기(1/4 크기) → 한 번 더 다듬기(원래 크기, 점을 드물게)로 찾는다.
# 돌려주는 것: {"img": 맞춘 그림 (원본과 같은 크기), "params": {sx, sy, tx, ty}, "loss": 평균 차이 (0~60)}
func _align(e: Image, ref: Image) -> Dictionary:
	var w := ref.get_width()
	var h := ref.get_height()
	var e2: Image = e.duplicate()
	if e2.get_size() != ref.get_size():
		_bleed(e2, 3)  # 투명한 곳 색을 옆 색으로 채워야 줄일 때 검은 테두리가 안 번진다
		e2.resize(w, h, Image.INTERPOLATE_LANCZOS)
		_clean_alpha(e2)
	# 1) 거친 이동
	var r8 := _flat_small(ref, 8)
	var e8 := _flat_small(e2, 8)
	var p8 := _points(ref, 8, r8["w"], r8["h"], 2)
	var reach := maxi(2, int(round(0.08 * w / 8.0)))
	var best := INF
	var bdx := 0
	var bdy := 0
	for dy in range(-reach, reach + 1):
		for dx in range(-reach, reach + 1):
			var l := _align_loss(r8, e8, p8, 8, [1.0, 1.0, dx * 8.0, dy * 8.0])
			if l < best:
				best = l
				bdx = dx
				bdy = dy
	var p: Array = [1.0, 1.0, bdx * 8.0, bdy * 8.0]
	# 2) 1/4 크기에서 이동·배율 다듬기
	var r4 := _flat_small(ref, 4)
	var e4 := _flat_small(e2, 4)
	var p4 := _points(ref, 4, r4["w"], r4["h"], 2)
	var res: Array = _descend(r4, e4, p4, 4, p, [0.008, 0.008, 4.0, 4.0], 3)
	p = res[0]
	# 3) 원래 크기에서 마무리 (점은 드물게: 가로세로 4칸마다 하나)
	var r1 := _flat_small(ref, 1)
	var e1 := _flat_small(e2, 1)
	var p1 := _points(ref, 1, r1["w"], r1["h"], 4)
	res = _descend(r1, e1, p1, 1, p, [0.002, 0.002, 1.0, 1.0], 3)
	p = res[0]
	var loss: float = res[1]
	var params := {"sx": snappedf(p[0], 0.0001), "sy": snappedf(p[1], 0.0001), "tx": snappedf(p[2], 0.01), "ty": snappedf(p[3], 0.01)}
	var same := absf(p[0] - 1.0) < 0.0006 and absf(p[1] - 1.0) < 0.0006 and absf(p[2]) < 0.35 and absf(p[3]) < 0.35
	return {"img": e2 if same else _warp(e2, p), "params": params, "loss": loss}


# 고친 그림을 [sx, sy, tx, ty]대로 원본 자리에 옮긴다 (알파를 곱한 색으로 두 줄 보간, 밖은 투명)
func _warp(img: Image, p: Array) -> Image:
	var w := img.get_width()
	var h := img.get_height()
	var d := img.get_data()
	var od := PackedByteArray()
	od.resize(d.size())
	var sx: float = p[0]
	var sy: float = p[1]
	var tx: float = p[2]
	var ty: float = p[3]
	var cx := (w - 1) * 0.5
	var cy := (h - 1) * 0.5
	for y in h:
		var v := (y - cy) / sy + cy - ty
		if v < 0.0 or v > h - 1.001:
			continue
		var y0 := int(v)
		var fy := v - y0
		for x in w:
			var u := (x - cx) / sx + cx - tx
			if u < 0.0 or u > w - 1.001:
				continue
			var x0 := int(u)
			var fx := u - x0
			var i00 := (y0 * w + x0) * 4
			var i10 := i00 + 4
			var i01 := i00 + w * 4
			var i11 := i01 + 4
			var w00 := (1.0 - fx) * (1.0 - fy)
			var w10 := fx * (1.0 - fy)
			var w01 := (1.0 - fx) * fy
			var w11 := fx * fy
			var a00 := w00 * d[i00 + 3]
			var a10 := w10 * d[i10 + 3]
			var a01 := w01 * d[i01 + 3]
			var a11 := w11 * d[i11 + 3]
			var a := a00 + a10 + a01 + a11
			if a < 1.0:
				continue
			var o := (y * w + x) * 4
			for c in 3:
				od[o + c] = clampi(int(round((a00 * d[i00 + c] + a10 * d[i10 + c] + a01 * d[i01 + c] + a11 * d[i11 + c]) / a)), 0, 255)
			od[o + 3] = clampi(int(round(a)), 0, 255)
	return Image.create_from_data(w, h, false, Image.FORMAT_RGBA8, od)


# ---- 아래는 make_mascot.gd와 같은 함수 (자르기·비교 규칙을 똑같이 쓰려고 복사; _diff_blob은 _diff_rect에 칸 목록을 더한 것) ----

# 두 그림에서 한 픽셀이라도 크게 다른 곳 (알파를 곱한 색으로 비교)
func _differs(a: PackedByteArray, b: PackedByteArray, o: int) -> bool:
	if _same_px(a, o, b, o):
		return false
	if not _tol:
		return true
	# 사장님 그림: 색만 다른 곳은 이웃(8칸) 픽셀 중 하나와 같으면 가장자리가 1픽셀 어긋난 것뿐이라 같은 곳으로 본다.
	# 있던 것이 없어졌거나 새로 생긴 곳(알파가 크게 다른 곳: 지운 머리카락 올 등)은 여유 없이 다른 곳이다
	if absi(a[o + 3] - b[o + 3]) > 128:
		return true
	# 진짜 1픽셀 옮겨짐이면 양쪽이 다 맞는다: a의 이 픽셀이 b의 이웃과 같고, b의 이 픽셀이 a의 이웃과도 같다.
	# 한쪽만 맞는 것은 얇은 선·올이 사라졌거나 생긴 것이라 (닫은 입에서 사라진 아랫입술 윤곽 등) 다른 곳이다
	var px := o / 4
	var x := px % _wid
	var y := px / _wid
	var h := a.size() / 4 / _wid
	var a_in_b := false
	var b_in_a := false
	for dy in range(-1, 2):
		var ny := y + dy
		if ny < 0 or ny >= h:
			continue
		for dx in range(-1, 2):
			var nx := x + dx
			if nx < 0 or nx >= _wid or (dx == 0 and dy == 0):
				continue
			var no := (ny * _wid + nx) * 4
			if not a_in_b and _same_px(a, o, b, no):
				a_in_b = true
			if not b_in_a and _same_px(a, no, b, o):
				b_in_a = true
	return not (a_in_b and b_in_a)


# 살짝 흐린 그림 (줄였다가 되돌림): 조각 찾기 비교용. 줄이는 배수는 그림 높이에 비례 (800이면 3)
func _lowpass(img: Image) -> Image:
	var f := maxi(2, int(round(3.0 * _k)))
	var small: Image = img.duplicate()
	small.resize(maxi(1, img.get_width() / f), maxi(1, img.get_height() / f), Image.INTERPOLATE_LANCZOS)
	small.resize(img.get_width(), img.get_height(), Image.INTERPOLATE_BILINEAR)
	return small


# "x,y,w,h" → Rect2i (틀리면 빈 사각형)
func _parse_rect(text: String) -> Rect2i:
	var parts := text.split(",", false)
	if parts.size() != 4:
		return Rect2i()
	return Rect2i(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))


# base(머리카락 자리)에 더해, rect 밖을 모두 '제외'로 표시한 것
func _skip_outside(rect: Rect2i, w: int, h: int, base: PackedByteArray) -> PackedByteArray:
	var out := PackedByteArray()
	out.resize(w * h)
	for y in h:
		var inside_y := y >= rect.position.y and y < rect.end.y
		for x in w:
			if not (inside_y and x >= rect.position.x and x < rect.end.x) or (base.size() > 0 and base[y * w + x] != 0):
				out[y * w + x] = 1
	return out


func _skipped(i: int) -> bool:
	return _skip.size() > 0 and _skip[i] != 0


# 두 픽셀(알파를 곱한 색과 알파)이 DIFF 안으로 같은가
func _same_px(a: PackedByteArray, ao: int, b: PackedByteArray, bo: int) -> bool:
	var aa := a[ao + 3] / 255.0
	var ba := b[bo + 3] / 255.0
	for c in 3:
		if absf(a[ao + c] * aa - b[bo + c] * ba) > DIFF:
			return false
	return absi(a[ao + 3] - b[bo + 3]) <= DIFF


# 머리색(갈색)이거나 투명한 픽셀인가: 옷(초록기 파랑·흰색)·살(밝은 살색)·금색 귀걸이는 아니다
func _hairish(d: PackedByteArray, o: int) -> bool:
	if d[o + 3] < 8:
		return true
	var r: int = d[o]
	var g: int = d[o + 1]
	var b: int = d[o + 2]
	if d[o + 3] < 200:  # 반투명(가장자리·흐린 올)은 초록기를 빼면서 g가 r 쪽으로 올라가 있어서 g 검사를 하지 않는다
		return r >= b - 10 and r <= 200 and r - b <= 110
	return r >= b and r <= 200 and g <= r * 0.85 and r - b <= 110


# 두 픽셀의 차이 (알파를 곱한 색과 알파의 채널 최대 차)
func _delta(a: PackedByteArray, b: PackedByteArray, o: int) -> int:
	var aa := a[o + 3] / 255.0
	var ba := b[o + 3] / 255.0
	var m := absi(a[o + 3] - b[o + 3])
	for c in 3:
		m = maxi(m, int(absf(a[o + c] * aa - b[o + c] * ba)))
	return m


func _diff_count(a: Image, b: Image, area: Rect2i) -> int:
	var da := a.get_data()
	var db := b.get_data()
	var w := a.get_width()
	var n := 0
	for y in range(area.position.y, area.end.y):
		for x in range(area.position.x, area.end.x):
			if _differs(da, db, (y * w + x) * 4) and not _skipped(y * w + x):
				n += 1
	return n


# 위쪽 max_y 줄 안에서 '가장 많이 바뀐 덩어리'를 담는 사각형 ("rect")과 그 덩어리의 칸 표시 ("cells", 칸 가로 수 "cw").
# 8×8 칸마다 바뀐 픽셀을 세어 촘촘한 칸(cell_min 이상)만 이은 덩어리 중 가장 큰 것만 쓴다.
# extra_min > 0이면 가장 큰 덩어리 사각형 근처(한 칸 안)에 닿는 다른 덩어리도 (바뀐 픽셀이 extra_min 이상이면) 함께 쓴다 — 머리카락처럼 떨어진 조각이 있는 곳용.
func _diff_blob(a: Image, b: Image, max_y: int, cell_min: int, extra_min: int = 0) -> Dictionary:
	var da := a.get_data()
	var db := b.get_data()
	var w := a.get_width()
	var cw := int(ceil(w / float(_cell)))
	var ch := int(ceil(max_y / float(_cell)))
	var counts := PackedInt32Array()
	counts.resize(cw * ch)
	for y in max_y:
		for x in w:
			if _differs(da, db, (y * w + x) * 4) and not _skipped(y * w + x):
				counts[(y / _cell) * cw + x / _cell] += 1
	var seen := PackedByteArray()
	seen.resize(cw * ch)
	var best := Rect2i()
	var best_sum := 0
	var best_cells: Array[int] = []
	var comps: Array = []  # [칸 목록, 바뀐 픽셀 합, 사각형]
	for start in cw * ch:
		if seen[start] or counts[start] < cell_min:
			continue
		var stack: Array[int] = [start]
		var members: Array[int] = []
		seen[start] = 1
		var lo := Vector2i(cw, ch)
		var hi := Vector2i(-1, -1)
		var total := 0
		while not stack.is_empty():
			var c: int = stack.pop_back()
			members.append(c)
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
				if not seen[n] and counts[n] >= cell_min:
					seen[n] = 1
					stack.append(n)
		var crect := Rect2i(lo * _cell, (hi - lo + Vector2i.ONE) * _cell)
		comps.append([members, total, crect])
		if total > best_sum:
			best_sum = total
			best = crect
			best_cells = members
	var cells := PackedByteArray()
	cells.resize(cw * ch)
	for c in best_cells:
		cells[c] = 1
	var joined := 0
	if extra_min > 0 and best_sum > 0:
		var near := best.grow(_cell)
		var union := best
		for comp in comps:
			var members: Array = comp[0]
			if members == best_cells or (comp[1] as int) < extra_min or not near.intersects(comp[2] as Rect2i):
				continue
			for c in members:
				cells[c] = 1
			union = union.merge(comp[2] as Rect2i)
			joined += 1
		best = union
	return {"rect": best.intersection(Rect2i(0, 0, w, max_y)), "cells": cells, "cw": cw, "total": best_sum, "joined": joined}


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
