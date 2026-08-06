extends SceneTree

## Godot 4.7 CI gate: parse project scripts, open color-ID map, instantiate main scene.
## Exit 0 on success.

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


func _initialize() -> void:
	print("map_ci_check: start")
	# Force-load presentation scripts so parser errors fail CI.
	var _layer = MapTextureLayerScript.new()
	var _space = MapSpaceScript.new()
	var _markers = MapMarkersScript
	var _debug = MapDebugScript.new()
	if _layer == null or _space == null or _debug == null:
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

	var packed = load("res://main.tscn")
	if packed == null:
		_fail("failed to load res://main.tscn")
		return
	var scene: Node = packed.instantiate()
	if scene == null:
		_fail("failed to instantiate main scene")
		return
	root.add_child(scene)
	# Drive load using committed fixtures (does not require ignored campaign_snapshot.json).
	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = DEFAULT_SNAPSHOT
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", DEFAULT_SNAPSHOT)
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = DEFAULT_MANIFEST
	if scene.has_method("_load_presentation_fixture"):
		scene.call("_load_presentation_fixture", DEFAULT_FIXTURE)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	if scene.get("color_id_map") != null and not bool(scene.color_id_map.is_ready):
		_fail("main scene color_id_map not ready: %s" % str(scene.color_id_map.error))
		return
	if scene.get("selected_province_id") != null and not alt.is_empty():
		scene.selected_province_id = alt
		if scene.has_method("_rebuild_legal_targets"):
			scene.call("_rebuild_legal_targets")
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()
	# Confirm dedicated filter layers exist after open.
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
	print("map_ci_check: main scene layers ok")
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
