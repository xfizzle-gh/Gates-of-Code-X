extends SceneTree

## Godot 4.7 CI gate with true draw-path smoke.
## Requires a real rendering backend (windowed or xvfb) — not pure dummy headless.
##
## - parse presentation scripts
## - ColorIdMap open + ownership/highlight refresh
## - instantiate main.tscn with committed snapshot/fixture
## - wait for multiple force_draw frames
## - capture nonempty viewport image from live CanvasItems

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/em_theatre_profile.json"
const DEFAULT_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/routes_and_battles.json"
const ColorIdMapScript = preload("res://scripts/color_id_map.gd")
const MapTextureLayerScript = preload("res://scripts/presentation/map_texture_layer.gd")
const MapSpaceScript = preload("res://scripts/presentation/map_space.gd")
const MapMarkersScript = preload("res://scripts/presentation/map_markers.gd")
const MapDebugScript = preload("res://scripts/presentation/map_debug.gd")
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}
const RENDER_FRAMES := 12
const SMOKE_SHOT := "user://map_ci_render_smoke.png"


func _initialize() -> void:
	print("map_ci_check: start")
	call_deferred("_run")


func _run() -> void:
	var layer = MapTextureLayerScript.new()
	var space = MapSpaceScript.new()
	var debug = MapDebugScript.new()
	if layer == null or space == null or debug == null or MapMarkersScript == null:
		_fail("presentation script instantiation failed")
		return

	if not FileAccess.file_exists(DEFAULT_SNAPSHOT):
		_fail("missing committed snapshot fixture: %s" % DEFAULT_SNAPSHOT)
		return
	if not FileAccess.file_exists(DEFAULT_MANIFEST):
		_fail("missing map manifest: %s" % DEFAULT_MANIFEST)
		return

	var snapshot := _load_json(DEFAULT_SNAPSHOT)
	if snapshot.is_empty():
		_fail("snapshot JSON empty/invalid")
		return

	var color_map = ColorIdMapScript.new()
	if not color_map.open(DEFAULT_MANIFEST, snapshot, FACTION_COLORS):
		_fail("ColorIdMap.open failed: %s" % color_map.error)
		return
	if int(color_map.row_by_province.size()) < 300:
		_fail("expected full theatre province table, got %s" % color_map.row_by_province.size())
		return

	var selected := ""
	for battalion: Dictionary in snapshot.get("battalions", []):
		selected = String(battalion.get("province_id", ""))
		if not selected.is_empty():
			break
	var legal := {}
	for option: Dictionary in snapshot.get("front_options", []):
		if String(option.get("origin", "")) == selected:
			legal[String(option.get("target", ""))] = option
	color_map.refresh_highlights(selected, legal)
	var alt := selected
	for province: Dictionary in snapshot.get("provinces", []):
		var pid := String(province.get("id", ""))
		if pid != selected and not pid.is_empty():
			alt = pid
			break
	color_map.refresh_highlights(alt, legal)
	var mutated := snapshot.duplicate(true)
	var provinces: Array = mutated.get("provinces", [])
	if not provinces.is_empty():
		var row: Dictionary = provinces[0]
		var owner := String(row.get("owner", "neutral"))
		row["owner"] = "nato" if owner != "nato" else "rusa"
		provinces[0] = row
		mutated["provinces"] = provinces
		color_map.refresh_snapshot(mutated, FACTION_COLORS)
	print("map_ci_check: color_id refresh ok provinces=%s" % color_map.row_by_province.size())

	DisplayServer.window_set_size(Vector2i(1280, 720))
	if root is Window:
		(root as Window).size = Vector2i(1280, 720)
		(root as Window).mode = Window.MODE_WINDOWED

	var packed = load("res://main.tscn")
	if packed == null:
		_fail("failed to load res://main.tscn")
		return
	var scene: Node = packed.instantiate()
	if scene == null:
		_fail("failed to instantiate main scene")
		return
	root.add_child(scene)

	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = DEFAULT_SNAPSHOT
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", DEFAULT_SNAPSHOT)
	if not str(scene.get("load_error") if scene.get("load_error") != null else "").is_empty():
		_fail("snapshot load_error=%s" % scene.load_error)
		return
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = DEFAULT_MANIFEST
	if scene.has_method("_load_presentation_fixture"):
		scene.call("_load_presentation_fixture", DEFAULT_FIXTURE)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	if scene.get("map_debug") != null:
		scene.map_debug.enabled = true
		if scene.has_method("set_process"):
			scene.set_process(true)
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	if not alt.is_empty() and scene.get("selected_province_id") != null:
		scene.selected_province_id = alt
		if scene.has_method("_rebuild_legal_targets"):
			scene.call("_rebuild_legal_targets")
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()

	if scene.get("color_id_map") == null or not bool(scene.color_id_map.is_ready):
		var err := ""
		if scene.get("color_id_map") != null:
			err = str(scene.color_id_map.error)
		_fail("main scene color_id_map not ready: %s" % err)
		return
	var bg := scene.find_child("MapBackgroundLayer", true, false)
	var identity := scene.find_child("MapIdentityLayer", true, false)
	if bg == null or identity == null:
		_fail("expected MapBackgroundLayer and MapIdentityLayer children")
		return
	if int(bg.texture_filter) != int(CanvasItem.TEXTURE_FILTER_LINEAR):
		_fail("background layer filter must be LINEAR")
		return
	if int(identity.texture_filter) != int(CanvasItem.TEXTURE_FILTER_NEAREST):
		_fail("identity layer filter must be NEAREST")
		return
	print("map_ci_check: layers ok; rendering frames")

	for _i in range(RENDER_FRAMES):
		if scene.get("_layers_dirty") != null:
			scene._layers_dirty = true
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await create_timer(0.04).timeout

	var image: Image = null
	if root is Viewport:
		var tex: ViewportTexture = (root as Viewport).get_texture()
		if tex != null:
			image = tex.get_image()
	if image == null or image.is_empty():
		_fail("render smoke: viewport image empty after %s frames" % RENDER_FRAMES)
		return
	var err2 := image.save_png(SMOKE_SHOT)
	if err2 != OK:
		_fail("render smoke: save_png failed err=%s" % err2)
		return
	var sample := image.get_pixel(image.get_width() / 2, image.get_height() / 2)
	if sample.r + sample.g + sample.b < 0.05:
		_fail("render smoke: center pixel nearly black — draw path likely skipped")
		return
	print(
		"map_ci_check: render smoke ok size=%sx%s frames=%s center=(%s,%s,%s)" % [
			image.get_width(),
			image.get_height(),
			RENDER_FRAMES,
			snappedf(sample.r, 0.01),
			snappedf(sample.g, 0.01),
			snappedf(sample.b, 0.01),
		]
	)
	print("map_ci_check: PASS")
	quit(0)


func _fail(reason: String) -> void:
	push_error("map_ci_check FAIL: %s" % reason)
	print("map_ci_check: FAIL %s" % reason)
	quit(1)


func _load_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		return parsed
	return {}
