# Beach mascot: preserve reference pixels outside the approved face/hair patches.
# Outputs are staged; publish with studio.util.atomic_copy after visual checks.
extends "res://make_mascot_parts.gd"

const FACE_RECTS := {
    "mouth-closed": Rect2i(497, 229, 56, 40),
    "mouth-half": Rect2i(497, 229, 56, 40),
    "eyes-half": Rect2i(442, 168, 137, 61),
    "blink": Rect2i(442, 168, 137, 61),
}

func _initialize() -> void:
    var raw_dir := ""
    var output := ""
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--raw="):
            raw_dir = arg.substr(6).trim_suffix("/") + "/"
        elif arg.begins_with("--out="):
            output = arg.substr(6).trim_suffix("/") + "/"
    if raw_dir.is_empty() or output.is_empty():
        push_error("--raw and --out are required")
        quit(2)
        return
    var normal := Image.load_from_file(raw_dir + "normal.png")
    if normal == null or normal.is_empty() or normal.get_size() != Vector2i(1021, 1540):
        push_error("Reference must be the reviewed 1021x1540 standing image")
        quit(2)
        return
    normal.convert(Image.FORMAT_RGBA8)
    DirAccess.make_dir_recursive_absolute(output)
    var report := {"size": {"w": normal.get_width(), "h": normal.get_height()}, "pieces": {}, "problems": []}
    var problems: Array = report["problems"]
    for name in FACE_RECTS:
        var edited := _read_edit(raw_dir + "generated/" + name + ".png", normal.get_size())
        if edited == null:
            problems.append({"name": name, "error": "Missing or incompatible generated edit"})
            continue
        var rect: Rect2i = FACE_RECTS[name]
        var piece := edited.get_region(rect)
        _feather(piece, 4)
        if piece.save_png(output + name + ".png") != OK:
            problems.append({"name": name, "error": "Patch save failed"})
            continue
        var composite: Image = normal.duplicate()
        composite.blend_rect(piece, Rect2i(Vector2i.ZERO, piece.get_size()), rect.position)
        composite.save_png(output + "raw-" + name + ".png")
        _zoom_pair(normal, composite, rect).save_png(output + "check-" + name + "-zoom.png")
        report["pieces"][name] = {"x": rect.position.x, "y": rect.position.y, "w": rect.size.x, "h": rect.size.y,
            "changed_inside": _diff_count(normal, composite, rect), "feather": 4}
    var erased := _read_edit(raw_dir + "generated/nohair.png", normal.get_size())
    if erased == null:
        problems.append({"name": "hair", "error": "Missing or incompatible nohair edit"})
    else:
        var bounded: Image = normal.duplicate()
        var cut := Rect2i(592, 285, 245, 325)
        bounded.blit_rect(erased, cut, cut.position)
        report["hair"] = _hair("", raw_dir, output,
            Rect2i(Vector2i.ZERO, normal.get_size()), normal.get_width(), normal.get_height(),
            {"normal": normal}, bounded, problems)
    if report.has("hair") and not report["hair"].is_empty():
        _trim_hair(normal, output, report["hair"])
    var file := FileAccess.open(output + "parts.json", FileAccess.WRITE)
    if file:
        file.store_string(JSON.stringify(report, "  ") + "\n")
        file.close()
    print("PARTS " + JSON.stringify(report))
    quit(0 if problems.is_empty() else 2)

func _read_edit(path: String, wanted: Vector2i) -> Image:
    var img := Image.load_from_file(path)
    if img == null or img.is_empty():
        return null
    if absi(img.get_width() - wanted.x) > 2 or absi(img.get_height() - wanted.y) > 2:
        push_error("Edit framing changed by more than two pixels: " + path)
        return null
    img.convert(Image.FORMAT_RGBA8)
    if img.get_size() != wanted:
        img.resize(wanted.x, wanted.y, Image.INTERPOLATE_LANCZOS)
    return img

# Keep clothing/arm pixels out of the movable hair; restore those pixels on the base.
func _trim_hair(normal: Image, output: String, info: Dictionary) -> void:
    var hair := Image.load_from_file(output + "hair.png")
    var body := Image.load_from_file(output + "normal-nohair.png")
    hair.convert(Image.FORMAT_RGBA8)
    body.convert(Image.FORMAT_RGBA8)
    var hd := hair.get_data()
    var bd := body.get_data()
    var nd := normal.get_data()
    var w := normal.get_width()
    var removed := 0
    for y in normal.get_height():
        for x in w:
            var o := (y * w + x) * 4
            if hd[o + 3] == 0:
                continue
            var not_hair: bool = hd[o + 2] >= hd[o] or (hd[o] > 215 and hd[o + 1] > hd[o] * 0.73)
            var arm_edge: bool = x > 660 and x < 712 and y > 500
            if not_hair or arm_edge:
                for ch in 4:
                    bd[o + ch] = nd[o + ch]
                    hd[o + ch] = 0
                removed += 1
    hair.set_data(w, normal.get_height(), false, Image.FORMAT_RGBA8, hd)
    body.set_data(w, normal.get_height(), false, Image.FORMAT_RGBA8, bd)
    hair.save_png(output + "hair.png")
    body.save_png(output + "normal-nohair.png")
    var comp: Image = body.duplicate()
    comp.blend_rect(hair, Rect2i(Vector2i.ZERO, hair.get_size()), Vector2i.ZERO)
    _flatten(hair).save_png(output + "check-hair-only.png")
    _flatten(body).save_png(output + "check-normal-nohair.png")
    _flatten(comp).save_png(output + "check-hair-composite.png")
    info["nonhair_pixels_removed"] = removed
    info["check"]["composite_diff"] = _diff_count(normal, comp, Rect2i(Vector2i.ZERO, normal.get_size()))
    info["files"] = ["hair.png", "normal-nohair.png"]
