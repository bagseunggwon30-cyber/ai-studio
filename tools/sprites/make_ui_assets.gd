# 소품(C1)·아이콘(C2)·창 틀(C3) 시트(자홍 배경)를 조각마다 잘라 투명 PNG로 만든다.
#
#   godot --headless --path tools/sprites --script res://make_ui_assets.gd -- --root=<프로젝트 폴더>
#
# 입력: assets-raw/props.png, icons.png, panels.png (make_ui_sheets.ps1)
# 출력: ui/assets/ui/<이름>.png
# - props·icons는 4x4 같은 칸이라 칸마다 자른다.
# - panels는 칸이 고르지 않아, 이 시트에서 잰 대략의 자리(PANELS)를 잘라 쓴 부분만 남긴다.
#   시트를 다시 뽑으면 PANELS 자리를 다시 재야 한다 (자리 밖으로 조각이 넘치면 오류로 알린다).
extends SceneTree

const Keying := preload("res://keying.gd")
const MAX_SIDE := 256  # 소품·아이콘은 긴 변을 이만큼으로 줄인다 (화면에서는 48~130px로 쓴다)

const PROPS := [
	"screen-code", "screen-doc", "screen-chart", "screen-pause",
	"trophy", "cartridge", "frame", "cat",
	"wax-red", "wax-purple", "wax-gold", "beacon",
	"note-yellow", "note-green", "note-pink", "note-purple",
]
const ICONS := [
	"icon-logo", "icon-bolt", "icon-mail", "icon-bell",
	"icon-stop", "icon-scroll", "icon-team", "icon-book",
	"icon-send", "icon-check", "icon-warn", "icon-link",
	"icon-doc", "icon-shield", "icon-folder", "icon-archive",
]
# panels.png(1536x1024)에서 잰 자리 (x, y, 너비, 높이)
const PANELS := {
	"panel-parchment": Rect2i(60, 40, 360, 340),
	"panel-cork": Rect2i(495, 50, 560, 355),
	"panel-clipboard": Rect2i(1165, 25, 305, 405),
	"panel-journal": Rect2i(15, 415, 600, 320),
	"panel-tray": Rect2i(1035, 440, 470, 265),
	"panel-shelf": Rect2i(580, 690, 415, 280),
	"panel-bubble": Rect2i(1160, 740, 310, 230),
}


func _initialize() -> void:
	var root := ""
	for a in OS.get_cmdline_user_args():
		if a.begins_with("--root="):
			root = a.substr(7)
	if root == "":
		push_error("--root=<프로젝트 폴더>가 필요합니다")
		quit(2)
		return
	var out_dir := root.path_join("ui/assets/ui")
	DirAccess.make_dir_recursive_absolute(out_dir)
	var ok := true
	ok = _grid(root, "assets-raw/props.png", PROPS, out_dir) and ok
	ok = _grid(root, "assets-raw/icons.png", ICONS, out_dir) and ok
	ok = _panels(root, "assets-raw/panels.png", out_dir) and ok
	quit(0 if ok else 1)


func _load(root: String, rel: String) -> Image:
	var img := Image.load_from_file(root.path_join(rel))
	if img == null or img.is_empty():
		push_error("그림을 읽을 수 없음: " + rel)
		return null
	img.convert(Image.FORMAT_RGBA8)
	Keying.key(img, Keying.background_color(img))
	return img


func _grid(root: String, rel: String, names: Array, out_dir: String) -> bool:
	var img := _load(root, rel)
	if img == null:
		return false
	var cw := img.get_width() / 4
	var ch := img.get_height() / 4
	for i in names.size():
		var cell := img.get_region(Rect2i((i % 4) * cw, (i / 4) * ch, cw, ch))
		var used := _main_rect(cell)
		if used.size.x < 8 or used.size.y < 8:
			push_error("%s: %d번 칸이 비어 있음 (%s)" % [rel, i + 1, names[i]])
			return false
		var piece := cell.get_region(used)
		var k := float(MAX_SIDE) / maxf(piece.get_width(), piece.get_height())
		if k < 1.0:
			piece.resize(int(round(piece.get_width() * k)), int(round(piece.get_height() * k)), Image.INTERPOLATE_LANCZOS)
		_save(piece, out_dir, names[i])
	return true


# 칸 안의 주인공 조각 범위: 이어진 덩어리를 찾아, 가장 큰 덩어리와 그 근처(반짝이 선 같은 작은 조각)만 합친다.
# 칸 가장자리에 옆 칸 그림 끝이 조금 들어와 있어도 버린다 (그림 모델이 칸을 정확히 지키지 않는다).
func _main_rect(cell: Image) -> Rect2i:
	var w := cell.get_width()
	var h := cell.get_height()
	var data := cell.get_data()
	var label := PackedInt32Array()
	label.resize(w * h)
	var boxes: Array[Rect2i] = []
	var sizes: Array[int] = []
	for start in w * h:
		if label[start] != 0 or data[start * 4 + 3] < 24:
			continue
		var id := boxes.size() + 1
		var stack := [start]
		label[start] = id
		var lo := Vector2i(w, h)
		var hi := Vector2i(-1, -1)
		var n := 0
		while not stack.is_empty():
			var p: int = stack.pop_back()
			var x := p % w
			var y := p / w
			lo = Vector2i(mini(lo.x, x), mini(lo.y, y))
			hi = Vector2i(maxi(hi.x, x), maxi(hi.y, y))
			n += 1
			for q in [p - 1, p + 1, p - w, p + w]:
				if q < 0 or q >= w * h or label[q] != 0 or data[q * 4 + 3] < 24:
					continue
				if (q == p - 1 and x == 0) or (q == p + 1 and x == w - 1):
					continue
				label[q] = id
				stack.append(q)
		boxes.append(Rect2i(lo, hi - lo + Vector2i.ONE))
		sizes.append(n)
	if boxes.is_empty():
		return Rect2i()
	var big := 0
	for k in sizes.size():
		if sizes[k] > sizes[big]:
			big = k
	var rect := boxes[big]
	var near := rect.grow(40)
	for k in boxes.size():
		# 가장 큰 덩어리 근처의 작은 조각만 (칸 가장자리에 붙은 옆 칸 조각은 버린다)
		var b := boxes[k]
		var edge := b.position.x == 0 or b.position.y == 0 or b.end.x == w or b.end.y == h
		if k != big and not edge and near.encloses(b):
			rect = rect.merge(b)
	return rect


func _panels(root: String, rel: String, out_dir: String) -> bool:
	var img := _load(root, rel)
	if img == null:
		return false
	for name in PANELS:
		var r: Rect2i = PANELS[name]
		var part := img.get_region(r)
		var used := _main_rect(part)
		# 조각이 자리 끝에 닿아 있으면 자리를 잘못 잰 것이다 (잘려 나갔을 수 있다)
		if used.position.x == 0 or used.position.y == 0 or used.end.x == r.size.x or used.end.y == r.size.y:
			push_error("%s: %s 자리가 조각을 다 담지 못함 (쓴 부분 %s, 자리 %s)" % [rel, name, used, r])
			return false
		_save(part.get_region(used), out_dir, name)
	return true


func _save(piece: Image, out_dir: String, name: String) -> void:
	var path := out_dir.path_join(name + ".png")
	piece.save_png(path)
	print("%s %dx%d" % [name, piece.get_width(), piece.get_height()])
