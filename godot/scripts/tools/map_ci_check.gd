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
const EARTH3_SNAPSHOT := "res://fixtures/snapshots/earth3_theatre.json"
const EARTH3_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/routes_and_battles.json"
const PolygonMapScript = preload("res://scripts/polygon_map.gd")
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

var _scene: Node = null


func _initialize() -> void:
	print("map_ci_check: start")
	call_deferred("_run")


func _run() -> void:
	var layer = MapTextureLayerScript.new()
	var space = MapSpaceScript.new()
	var debug = MapDebugScript.new()
	if layer == null or space == null or debug == null or MapMarkersScript == null:
		if layer != null and is_instance_valid(layer):
			layer.free()
		_fail("presentation script instantiation failed")
		return
	# MapTextureLayer is a Node2D/CanvasItem — free the orphan immediately after smoke.
	layer.free()
	layer = null
	space = null
	debug = null

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
	color_map = null

	# Earth3 polygon backend gate (when assets committed).
	if FileAccess.file_exists(EARTH3_MANIFEST) and FileAccess.file_exists(EARTH3_SNAPSHOT):
		var esnap := _load_json(EARTH3_SNAPSHOT)
		var pmap = PolygonMapScript.new()
		if not pmap.open(EARTH3_MANIFEST, esnap, FACTION_COLORS):
			_fail("PolygonMap.open failed: %s" % pmap.error)
			return
		if int(pmap.province_count) < 3000:
			_fail("Earth3 province_count expected >=3000 got %s" % pmap.province_count)
			return
		var sample_id := String(pmap.province_by_index[10])
		var hit := pmap.province_at_image_pos(pmap.centroids[10])
		if hit != sample_id:
			_fail("Earth3 hit test expected %s got %s" % [sample_id, hit])
			return
		var mesh_before: int = int(pmap.mesh_count)
		var first_mesh: Variant = null
		if pmap._meshes.size() > 0:
			first_mesh = pmap._meshes[0]
		var mutated_e: Dictionary = esnap.duplicate(true)
		var eprovs: Array = mutated_e.get("provinces", [])
		if not eprovs.is_empty():
			var erow: Dictionary = eprovs[0]
			var eowner := String(erow.get("owner", "neutral"))
			erow["owner"] = "nato" if eowner != "nato" else "rusa"
			eprovs[0] = erow
			mutated_e["provinces"] = eprovs
		pmap.refresh_snapshot(mutated_e, FACTION_COLORS)
		if int(pmap.mesh_count) != mesh_before:
			_fail("Earth3 refresh rebuilt meshes (%s -> %s)" % [mesh_before, pmap.mesh_count])
			return
		if first_mesh != null and pmap._meshes[0] != first_mesh:
			_fail("Earth3 refresh replaced mesh geometry (must be immutable)")
			return
		var perf: Dictionary = pmap.get_perf_stats()
		if not bool(perf.get("geometry_immutable", false)):
			_fail("Earth3 perf stats missing geometry_immutable")
			return
		print("map_ci_check: earth3 polygon ok provinces=%s load_ms=%s refresh_ms=%s meshes=%s" % [
			pmap.province_count, pmap.load_ms, pmap.refresh_ms, pmap.mesh_count
		])
		pmap = null

	DisplayServer.window_set_size(Vector2i(1280, 720))
	if root is Window:
		(root as Window).size = Vector2i(1280, 720)
		(root as Window).mode = Window.MODE_WINDOWED

	var packed = load("res://main.tscn")
	if packed == null:
		_fail("failed to load res://main.tscn")
		return
	_scene = packed.instantiate()
	if _scene == null:
		_fail("failed to instantiate main scene")
		return
	root.add_child(_scene)

	if _scene.get("snapshot_source_path") != null:
		_scene.snapshot_source_path = DEFAULT_SNAPSHOT
	if _scene.has_method("_load_snapshot"):
		_scene.call("_load_snapshot", DEFAULT_SNAPSHOT)
	if not str(_scene.get("load_error") if _scene.get("load_error") != null else "").is_empty():
		_fail("snapshot load_error=%s" % _scene.load_error)
		return
	if _scene.get("map_manifest_source_path") != null:
		_scene.map_manifest_source_path = DEFAULT_MANIFEST
	if _scene.has_method("_load_presentation_fixture"):
		_scene.call("_load_presentation_fixture", DEFAULT_FIXTURE)
	if _scene.has_method("_open_color_id_map"):
		_scene.call("_open_color_id_map")
	if _scene.get("map_debug") != null:
		_scene.map_debug.enabled = true
		if _scene.has_method("set_process"):
			_scene.set_process(true)
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")
	if not alt.is_empty() and _scene.get("selected_province_id") != null:
		_scene.selected_province_id = alt
		if _scene.has_method("_rebuild_legal_targets"):
			_scene.call("_rebuild_legal_targets")
	if _scene.get("_layers_dirty") != null:
		_scene._layers_dirty = true
	if _scene.has_method("_sync_presentation_layers"):
		_scene.call("_sync_presentation_layers")
	if _scene.has_method("queue_redraw"):
		_scene.queue_redraw()

	if _scene.get("color_id_map") == null or not bool(_scene.color_id_map.is_ready):
		var err := ""
		if _scene.get("color_id_map") != null:
			err = str(_scene.color_id_map.error)
		_fail("main scene color_id_map not ready: %s" % err)
		return
	var bg := _scene.find_child("MapBackgroundLayer", true, false)
	var identity := _scene.find_child("MapIdentityLayer", true, false)
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
		if _scene.get("_layers_dirty") != null:
			_scene._layers_dirty = true
		if _scene.has_method("_sync_presentation_layers"):
			_scene.call("_sync_presentation_layers")
		if _scene.has_method("queue_redraw"):
			_scene.queue_redraw()
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
	_cleanup_and_quit(0)


func _cleanup_and_quit(code: int) -> void:
	if _scene != null and is_instance_valid(_scene):
		var parent := _scene.get_parent()
		if parent != null:
			parent.remove_child(_scene)
		_scene.free()
	_scene = null
	quit(code)


func _fail(reason: String) -> void:
	push_error("map_ci_check FAIL: %s" % reason)
	print("map_ci_check: FAIL %s" % reason)
	_cleanup_and_quit(1)


func _load_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		return parsed
	return {}
