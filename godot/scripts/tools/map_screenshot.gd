extends SceneTree

## Runtime Godot screenshot evidence.
## Loads the real main scene + committed snapshot, exercises map open/refresh, then
## captures the live ImageTexture layers produced by ColorIdMap (Godot runtime objects).
##
## Godot.exe --headless --path godot -s res://scripts/tools/map_screenshot.gd -- \
##   --out=...png --width=1920 --height=1080 \
##   --snapshot=res://fixtures/snapshots/em_theatre_profile.json \
##   --fixture=res://fixtures/presentation/routes_and_battles.json

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/em_theatre_profile.json"
const DEFAULT_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/empty_map.json"
const MapMarkersScript = preload("res://scripts/presentation/map_markers.gd")
const MapSpaceScript = preload("res://scripts/presentation/map_space.gd")
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}

var _out_path := "user://map_shot.png"
var _fixture_path := DEFAULT_FIXTURE
var _snapshot_path := DEFAULT_SNAPSHOT
var _width := 1920
var _height := 1080
var _debug := false
var _select_first := false
var _hover_second := false


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--fixture="):
			_fixture_path = text.substr(10).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
		elif text == "--debug":
			_debug = true
		elif text == "--select-first":
			_select_first = true
		elif text == "--hover-second":
			_hover_second = true

	var packed := load("res://main.tscn")
	if packed == null:
		push_error("Unable to load main.tscn")
		quit(1)
		return
	var scene: Node = packed.instantiate()
	root.add_child(scene)

	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = _snapshot_path
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", _snapshot_path)
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = DEFAULT_MANIFEST
	if scene.has_method("_load_presentation_fixture"):
		scene.call("_load_presentation_fixture", _fixture_path)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	if _debug and scene.get("map_debug") != null:
		scene.map_debug.enabled = true
	_apply_selection_hover(scene)
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")

	var bg := scene.find_child("MapBackgroundLayer", true, false)
	var identity := scene.find_child("MapIdentityLayer", true, false)
	if bg == null or identity == null:
		push_error("presentation layers missing")
		quit(2)
		return
	if int(bg.texture_filter) != int(CanvasItem.TEXTURE_FILTER_LINEAR):
		push_error("background layer filter is not LINEAR")
		quit(2)
		return
	if int(identity.texture_filter) != int(CanvasItem.TEXTURE_FILTER_NEAREST):
		push_error("identity layer filter is not NEAREST")
		quit(2)
		return

	var image := _compose_runtime_image(scene)
	if image == null or image.is_empty():
		push_error("compose failed")
		quit(3)
		return
	if _out_path.contains("/") or _out_path.contains("\\"):
		var base := _out_path.get_base_dir()
		if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
			DirAccess.make_dir_recursive_absolute(base)
	var err := image.save_png(_out_path)
	print(
		"screenshot err=%s path=%s size=%sx%s layers=bg:%s id:%s" % [
			err,
			_out_path,
			image.get_width(),
			image.get_height(),
			bg.texture_filter,
			identity.texture_filter,
		]
	)
	quit(0 if err == OK else 4)


func _compose_runtime_image(scene: Node) -> Image:
	var cmap = scene.color_id_map
	if cmap == null or not bool(cmap.is_ready):
		return null
	var src_w := int(cmap.image_size().x)
	var src_h := int(cmap.image_size().y)
	var composed := Image.create(src_w, src_h, false, Image.FORMAT_RGBA8)
	composed.fill(Color(0.025, 0.035, 0.047, 1.0))
	for tex_variant in [
		cmap.background_texture,
		cmap.owner_texture,
		cmap.border_texture,
		cmap.highlight_texture,
	]:
		if tex_variant == null:
			continue
		var tex: ImageTexture = tex_variant
		var layer := tex.get_image()
		if layer == null or layer.is_empty():
			continue
		if layer.get_format() != Image.FORMAT_RGBA8:
			layer.convert(Image.FORMAT_RGBA8)
		composed.blend_rect(layer, Rect2i(0, 0, src_w, src_h), Vector2i.ZERO)

	# Draw presentation fixture markers into a transparent overlay via simple pixels.
	var fixture: Dictionary = {}
	if scene.get("presentation_fixture") != null:
		fixture = scene.presentation_fixture
	var map_space = MapSpaceScript.new()
	var content := Rect2(0, 0, float(src_w), float(src_h))
	map_space.configure(Vector2(src_w, src_h), content, 1.0, Vector2.ZERO)

	# Scale to target resolution with nearest for identity clarity.
	var scale := minf(float(_width) / float(src_w), float(_height) / float(src_h)) * 0.92
	var rw := maxi(int(float(src_w) * scale), 1)
	var rh := maxi(int(float(src_h) * scale), 1)
	var scaled := composed.duplicate()
	scaled.resize(rw, rh, Image.INTERPOLATE_NEAREST)
	var out := Image.create(_width, _height, false, Image.FORMAT_RGBA8)
	out.fill(Color(0.025, 0.035, 0.047, 1.0))
	var ox := (_width - rw) / 2
	var oy := (_height - rh) / 2
	out.blit_rect(scaled, Rect2i(0, 0, rw, rh), Vector2i(ox, oy))

	# Annotate selection/hover/debug text using runtime IDs.
	var selected := String(scene.get("selected_province_id") if scene.get("selected_province_id") != null else "")
	var hovered := String(scene.get("hovered_province_id") if scene.get("hovered_province_id") != null else "")
	_draw_label(out, 16, 16, "Godot runtime capture %sx%s" % [_width, _height])
	_draw_label(out, 16, 34, "layers LINEAR bg / NEAREST identity | selected=%s hover=%s" % [selected, hovered])
	if _debug:
		_draw_label(out, 16, 52, "DEBUG F3 overlay enabled")
	if not fixture.is_empty():
		_draw_label(out, 16, _height - 28, "fixture=%s" % String(fixture.get("id", "")))
		# Stamp deterministic marker pixels for route/battle/site fixtures.
		for battle: Variant in fixture.get("battles", []):
			if not battle is Dictionary:
				continue
			var pos := MapMarkersScript.battle_marker_position(battle, map_space)
			var sx := ox + int(pos.x * scale)
			var sy := oy + int(pos.y * scale)
			_stamp_x(out, sx, sy, Color("ff9f43"))
		for site: Variant in fixture.get("control_sites", []):
			if not site is Dictionary:
				continue
			var srow := site as Dictionary
			var sp := MapMarkersScript.battle_marker_position(srow, map_space)
			if sp == Vector2.ZERO and srow.has("pixel"):
				var px: Variant = srow.get("pixel")
				if px is Array and (px as Array).size() >= 2:
					sp = Vector2(float(px[0]), float(px[1]))
			var ssx := ox + int(sp.x * scale)
			var ssy := oy + int(sp.y * scale)
			_stamp_diamond(out, ssx, ssy, Color("63d69f") if bool(srow.get("owned", false)) else Color("b8c0c8"))
	return out


func _draw_label(image: Image, x: int, y: int, text: String) -> void:
	# Minimal bitmap-free label mark (full font raster not available offline).
	for i in range(mini(text.length() * 2, 200)):
		var px := x + i
		if px >= 0 and px < image.get_width() and y >= 0 and y < image.get_height():
			image.set_pixel(px, y, Color(0.85, 1.0, 0.75, 1.0))


func _stamp_x(image: Image, cx: int, cy: int, color: Color) -> void:
	for i in range(-8, 9):
		_put(image, cx + i, cy + i, color)
		_put(image, cx + i, cy - i, color)


func _stamp_diamond(image: Image, cx: int, cy: int, color: Color) -> void:
	for dy in range(-6, 7):
		var w := 6 - absi(dy)
		for dx in range(-w, w + 1):
			_put(image, cx + dx, cy + dy, color)


func _put(image: Image, x: int, y: int, color: Color) -> void:
	if x < 0 or y < 0 or x >= image.get_width() or y >= image.get_height():
		return
	image.set_pixel(x, y, color)


func _apply_selection_hover(scene: Node) -> void:
	if scene.get("color_id_map") == null or not bool(scene.color_id_map.is_ready):
		return
	var ids: Array = []
	for pid: Variant in scene.color_id_map.row_by_province.keys():
		ids.append(String(pid))
		if ids.size() >= 3:
			break
	if ids.is_empty():
		return
	if _select_first:
		scene.selected_province_id = String(ids[0])
		if scene.has_method("_rebuild_legal_targets"):
			scene.call("_rebuild_legal_targets")
		if scene.has_method("_rebuild_focus_set"):
			scene.call("_rebuild_focus_set")
	if _hover_second and ids.size() > 1:
		scene.hovered_province_id = String(ids[1])
