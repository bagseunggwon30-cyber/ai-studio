# Rigid beach cutouts. Stage only; publish with studio.util.atomic_copy.
extends SceneTree

const HAIR := [Vector2(600,280),Vector2(648,283),Vector2(682,314),Vector2(733,345),Vector2(783,385),Vector2(817,434),Vector2(842,480),Vector2(845,528),Vector2(827,568),Vector2(785,615),Vector2(715,620),Vector2(676,587),Vector2(619,575),Vector2(592,546),Vector2(596,499),Vector2(593,450),Vector2(602,416),Vector2(601,372),Vector2(580,335)]
const FRONT_BODY := [Vector2(0,280),Vector2(578,280),Vector2(608,309),Vector2(620,342),Vector2(641,385),Vector2(656,454),Vector2(657,514),Vector2(652,543),Vector2(622,575),Vector2(644,612),Vector2(0,640)]
const ARM := [Vector2(603,311),Vector2(643,309),Vector2(674,333),Vector2(690,380),Vector2(698,434),Vector2(708,514),Vector2(708,574),Vector2(665,612),Vector2(594,636),Vector2(453,640),Vector2(430,610),Vector2(458,569),Vector2(605,558),Vector2(647,549),Vector2(652,501),Vector2(640,467),Vector2(626,425),Vector2(611,395)]
const HEAD := Rect2i(0, 0, 1021, 331)
const TORSO := [Vector2(0,312),Vector2(1021,312),Vector2(1021,690),Vector2(699,690),Vector2(665,668),Vector2(626,687),Vector2(592,728),Vector2(555,765),Vector2(518,796),Vector2(479,760),Vector2(440,720),Vector2(405,685),Vector2(381,655),Vector2(335,698),Vector2(0,698)]
const CHEST := [Vector2(443,344),Vector2(493,359),Vector2(560,350),Vector2(587,334),Vector2(613,390),Vector2(632,420),Vector2(651,474),Vector2(654,524),Vector2(609,546),Vector2(441,537),Vector2(379,523),Vector2(370,494),Vector2(373,445),Vector2(407,393)]
const CLOTH := [Vector2(626,623),Vector2(691,638),Vector2(713,689),Vector2(766,744),Vector2(811,793),Vector2(810,888),Vector2(785,986),Vector2(745,1098),Vector2(699,1120),Vector2(673,1035),Vector2(648,950),Vector2(619,879),Vector2(577,820),Vector2(588,749)]
const HIP := [Vector2(376,623),Vector2(630,641),Vector2(676,665),Vector2(626,687),Vector2(592,728),Vector2(555,765),Vector2(518,796),Vector2(479,760),Vector2(440,720),Vector2(405,685),Vector2(381,655)]

func _initialize() -> void:
    var source := ""
    var hair_path := ""
    var nohair_path := ""
    var underleg_path := ""
    var out := ""
    for arg in OS.get_cmdline_user_args():
        if arg.begins_with("--source="): source = arg.substr(9)
        elif arg.begins_with("--hair="): hair_path = arg.substr(7)
        elif arg.begins_with("--nohair="): nohair_path = arg.substr(9)
        elif arg.begins_with("--underleg="): underleg_path = arg.substr(11)
        elif arg.begins_with("--out="): out = arg.substr(6).trim_suffix("/") + "/"
    if source.is_empty() or hair_path.is_empty() or out.is_empty():
        push_error("source, hair, out required")
        quit(2)
        return
    var src := Image.load_from_file(source)
    var hair := Image.load_from_file(hair_path)
    if src == null or hair == null or src.get_size() != Vector2i(1021,1540):
        quit(2)
        return
    src.convert(Image.FORMAT_RGBA8)
    var head_source: Image = src.duplicate()
    hair.convert(Image.FORMAT_RGBA8)
    if not nohair_path.is_empty():
        var erased := Image.load_from_file(nohair_path)
        if erased == null or absi(erased.get_width()-1021)>2 or absi(erased.get_height()-1540)>2:
            push_error("Nohair framing mismatch")
            quit(2)
            return
        erased.convert(Image.FORMAT_RGBA8)
        erased.resize(1021,1540,Image.INTERPOLATE_LANCZOS)
        hair = Image.create(1021,1540,false,Image.FORMAT_RGBA8)
        for y in range(280,621):
            for x in range(580,846):
                var point := Vector2(x,y)
                if Geometry2D.is_point_in_polygon(point,HAIR) and not Geometry2D.is_point_in_polygon(point,ARM) and not Geometry2D.is_point_in_polygon(point,FRONT_BODY) and (y < 575 or x >= 710):
                    hair.set_pixel(x,y,src.get_pixel(x,y))
                    src.set_pixel(x,y,erased.get_pixel(x,y) if src.get_pixel(x,y).a >= 0.95 else Color.TRANSPARENT)
    var legs: Image = src.duplicate()
    if not underleg_path.is_empty():
        var underleg := Image.load_from_file(underleg_path)
        if underleg == null or absi(underleg.get_width()-1021)>2 or absi(underleg.get_height()-1540)>2:
            push_error("Underleg framing mismatch")
            quit(2)
            return
        underleg.convert(Image.FORMAT_RGBA8)
        underleg.resize(1021,1540,Image.INTERPOLATE_LANCZOS)
        for y in range(623,1120):
            for x in range(550,814):
                if Geometry2D.is_point_in_polygon(Vector2(x,y),CLOTH):
                    legs.set_pixel(x,y,underleg.get_pixel(x,y))
    DirAccess.make_dir_recursive_absolute(out)
    src.save_png(out+"standing-body-underlay.png")
    hair.save_png(out+"check-hair-semantic.png")
    var pieces := {}
    var feet: Image = src.duplicate()
    for y in range(0,1417):
        for x in 1021: feet.set_pixel(x,y,Color.TRANSPARENT)
    feet.save_png(out + "standing-anchor.png")
    var specs := [
        ["calfL",Rect2i(310,1030,246,414),legs],
        ["calfR",Rect2i(556,1045,270,399),legs],
        ["thighL",Rect2i(300,635,256,430),legs],
        ["thighR",Rect2i(520,660,310,418),legs],
        ["hairR",Rect2i(580,280,280,360),hair],
        ["torso",Rect2i(0,312,1021,485),src],
        ["head",HEAD,head_source],
        ["chest",Rect2i(339,334,344,224),src],
        ["cloth",Rect2i(577,623,235,498),src],
    ]
    var composite: Image = feet.duplicate()
    for spec in specs:
        var name: String = spec[0]
        var rect: Rect2i = spec[1]
        var img: Image = spec[2].get_region(rect)
        for y in img.get_height():
            for x in img.get_width():
                var p := Vector2(x+rect.position.x,y+rect.position.y)
                var keep := true
                if name == "torso":
                    keep = Geometry2D.is_point_in_polygon(p,TORSO)
                    if keep and Geometry2D.is_point_in_polygon(p,CHEST) and _distance(p,CHEST)>6: keep = false
                    if keep and Geometry2D.is_point_in_polygon(p,CLOTH) and _distance(p,CLOTH)>6: keep = false
                elif name == "chest": keep = Geometry2D.is_point_in_polygon(p,CHEST)
                elif name == "cloth": keep = Geometry2D.is_point_in_polygon(p,CLOTH)
                elif name.begins_with("thigh"):
                    if Geometry2D.is_point_in_polygon(p,HIP) and _distance(p,HIP)>6: keep = false
                    if name == "thighL" and p.x >= 522: keep = false
                    if name == "thighR" and p.x < 522: keep = false
                    # The unoccluded torso is the top layer; don't duplicate its arm.
                    if p.y < 658: keep = false
                if not keep:
                    img.set_pixel(x,y,Color.TRANSPARENT)
                elif name == "chest" or name == "cloth":
                    var distance := _distance(p,CHEST if name == "chest" else CLOTH)
                    if distance < 5:
                        var color := img.get_pixel(x,y)
                        color.a *= smoothstep(0.0,5.0,distance)
                        img.set_pixel(x,y,color)
                elif name == "head" and p.y > 325:
                    var color := img.get_pixel(x,y)
                    color.a *= 1.0-smoothstep(325.0,331.0,p.y)
                    img.set_pixel(x,y,color)
                elif name == "torso" and p.y < 317:
                    var color := img.get_pixel(x,y)
                    color.a *= smoothstep(312.0,317.0,p.y)
                    img.set_pixel(x,y,color)
        var used := img.get_used_rect()
        if used.size.x <= 0 or used.size.y <= 0:
            push_error("Empty cutout: " + name)
            quit(2)
            return
        img = img.get_region(used)
        var pos: Vector2i = rect.position + used.position
        var filename := "standing-"+name.to_lower()+".png"
        img.save_png(out + filename)
        pieces[name] = {"image":filename,"x":pos.x,"y":pos.y,"w":img.get_width(),"h":img.get_height()}
        composite.blend_rect(img,Rect2i(Vector2i.ZERO,img.get_size()),pos)
    composite.save_png(out+"check-rigid-composite.png")
    var missing := 0
    var bounds := Rect2i()
    for y in 1540:
        for x in 1021:
            if src.get_pixel(x,y).a > 0.95 and composite.get_pixel(x,y).a < 0.9:
                missing += 1
                bounds = Rect2i(x,y,1,1) if missing == 1 else bounds.expand(Vector2i(x,y))
    print("COVERAGE missing="+str(missing)+" bounds="+str(bounds))
    var file := FileAccess.open(out+"rigid-parts.json",FileAccess.WRITE)
    file.store_string(JSON.stringify({"size":{"w":1021,"h":1540},"pieces":pieces,"underleg":not underleg_path.is_empty(),"missing_opaque_pixels":missing,"missing_bounds":[bounds.position.x,bounds.position.y,bounds.size.x,bounds.size.y]},"  ")+"\n")
    file.close()
    print("RIGID_PARTS " + JSON.stringify(pieces))
    quit()

func _distance(p: Vector2, poly: PackedVector2Array) -> float:
    var distance := INF
    for i in poly.size():
        var a := poly[i]
        var b := poly[(i+1)%poly.size()]
        var q := Geometry2D.get_closest_point_to_segment(p,a,b)
        distance = minf(distance,p.distance_to(q))
    return distance
