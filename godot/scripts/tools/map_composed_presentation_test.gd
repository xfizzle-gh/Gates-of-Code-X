extends SceneTree

## #212 E2 real-scene composition gate.
##
## First proves E1 hybrid alone does not mount E2. Then opts into both gates and
## proves atlas + LOD + layer control + cached minimap while PolygonMap remains
## the exact 3,514-province authority. The committed operational snapshot is
## loaded through the real `_load_snapshot()` boundary after main `_ready()` so
## the harness cannot be silently reset to the default campaign snapshot.

const SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const FIXTURE := "res://fixtures/presentation/e3_operational.json"
const MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const HYBRID_ENV := "GOCX_PRESENTATION_CANDIDATE"
const COMPOSED_ENV := "GOCX_PRESENTATION_COMPOSED"
const WAIT_FRAMES := 300

var _screens_dir := "user://issue212-composed-screens"


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--screens-dir="):
			_screens_dir = text.substr(14).strip_edges()
	call_deferred("_run")


func _run() -> void:
	for path_value in [SNAPSHOT, FIXTURE, MANIFEST]:
		if not FileAccess.file_exists(String(path_value)):
			_fail("required E2 input missing: %s" % String(path_value))
			return
	var hashes_before := _authority_hashes()
	DirAccess.make_dir_recursive_absolute(_screens_dir)
	DisplayServer.window_set_size(Vector2i(1600, 1000))
	if root is Window:
		(root as Window).size = Vector2i(1600, 1000)
		(root as Window).mode = Window.MODE_WINDOWED

	# E1-only control: the second gate must be truly absent by default.
	OS.set_environment(HYBRID_ENV, "hybrid")
	OS.set_environment(COMPOSED_ENV, "")
	var hybrid_only := await _build_scene()
	if hybrid_only == null:
		return
	if not await _wait_hybrid(hybrid_only):
		return
	if not await _load_operational_snapshot(hybrid_only, false):
		return
	var hybrid_composed: Dictionary = hybrid_only.call("composed_presentation_debug_state")
	if bool(hybrid_composed.get("requested", true)) or bool(hybrid_composed.get("active", true)):
		_fail("E1-only launch unexpectedly mounted composition: %s" % JSON.stringify(hybrid_composed))
		return
	if hybrid_only.find_child("Issue212ComposedAtlas", true, false) != null \
	or hybrid_only.find_child("Issue212MapLayerControl", true, false) != null \
	or hybrid_only.find_child("Issue212CachedMinimap", true, false) != null:
		_fail("E1-only launch contains E2 nodes")
		return
	var authority_reference := _authority_pick(hybrid_only)
	if not bool(authority_reference.get("ok", false)):
		_fail("E1 authority pick failed: %s" % JSON.stringify(authority_reference))
		return
	await _dispose(hybrid_only)

	# Full composition.
	OS.set_environment(HYBRID_ENV, "hybrid")
	OS.set_environment(COMPOSED_ENV, "1")
	var scene := await _build_scene()
	if scene == null:
		return
	if not await _wait_hybrid(scene):
		return
	if not await _wait_composed(scene):
		return
	if not await _load_operational_snapshot(scene, true):
		return
	var full_state: Dictionary = scene.call("composed_presentation_debug_state")
	var state: Dictionary = full_state.get("state", {})
	if String(full_state.get("lod", "")) != "full_theatre":
		_fail("expected full-theatre initial LOD: %s" % JSON.stringify(full_state))
		return
	if not bool(full_state.get("atlas_mounted", false)) or not bool(full_state.get("atlas_visible", false)):
		_fail("full-theatre atlas missing/hidden: %s" % JSON.stringify(full_state))
		return
	if int(full_state.get("atlas_vocabulary_count", 0)) != 18:
		_fail("atlas vocabulary contract changed")
		return
	if int(full_state.get("atlas_entry_count", 0)) <= 0:
		_fail("real operational snapshot produced no atlas entries")
		return
	if bool(full_state.get("atlas_strength_text", true)):
		_fail("full-theatre must suppress ambient numeric strength text")
		return
	if not bool(full_state.get("layer_control_mounted", false)):
		_fail("layer control not mounted")
		return
	if not bool(full_state.get("minimap_mounted", false)):
		_fail("cached minimap not mounted")
		return
	if bool(full_state.get("minimap_has_live_map_descendant", true)):
		_fail("minimap mounted a live map descendant")
		return
	var minimap_size: Vector2i = full_state.get("minimap_texture_size", Vector2i.ZERO)
	if minimap_size.x != 250 or minimap_size.y <= 0:
		_fail("minimap texture size contract failed: %s" % minimap_size)
		return
	if not bool(state.get("formation_symbols", false)) \
	or bool(state.get("names", true)) \
	or bool(state.get("infrastructure_sites", true)) \
	or bool(state.get("operational_routes", true)) \
	or bool(state.get("debug_overlays", true)):
		_fail("full-theatre LOD state wrong: %s" % JSON.stringify(state))
		return
	if _authority_pick(scene) != authority_reference:
		_fail("E2 full-theatre changed authority pick")
		return
	if not await _capture("full_theatre.png"):
		return

	# Detailed LOD restores the user-enabled detail surfaces and strength text.
	scene.view_scale = 3.0
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	for _i in range(10):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var detailed_state: Dictionary = scene.call("composed_presentation_debug_state")
	var detailed: Dictionary = detailed_state.get("state", {})
	if String(detailed_state.get("lod", "")) != "detailed":
		_fail("zoom did not enter detailed LOD: %s" % JSON.stringify(detailed_state))
		return
	if not bool(detailed.get("names", false)) \
	or not bool(detailed.get("infrastructure_sites", false)) \
	or not bool(detailed.get("operational_routes", false)):
		_fail("detailed LOD did not restore enabled detail surfaces: %s" % JSON.stringify(detailed))
		return
	if not bool(detailed_state.get("atlas_strength_text", false)):
		_fail("detailed LOD did not restore numeric strength text")
		return
	if _authority_pick(scene) != authority_reference:
		_fail("E2 detailed LOD changed authority pick")
		return
	if not await _capture("detailed.png"):
		return
	if not await _prove_edge_counter_alignment(scene):
		return

	# Real integrated layer toggles, not control-only state.
	if not bool(scene.call("set_composed_layer_toggle", "formation_symbols", false)):
		_fail("formation toggle refused")
		return
	await process_frame
	var toggled: Dictionary = scene.call("composed_presentation_debug_state")
	if bool(toggled.get("atlas_visible", true)) or bool(toggled.get("state", {}).get("formation_symbols", true)):
		_fail("formation toggle did not hide integrated atlas: %s" % JSON.stringify(toggled))
		return
	if not bool(scene.call("set_composed_layer_toggle", "operational_routes", false)):
		_fail("route toggle refused")
		return
	await process_frame
	toggled = scene.call("composed_presentation_debug_state")
	if bool(toggled.get("route_enabled", true)):
		_fail("route toggle did not reach integrated route state")
		return
	if not bool(scene.call("set_composed_layer_toggle", "infrastructure_sites", false)):
		_fail("infrastructure toggle refused")
		return
	if not bool(scene.call("set_composed_layer_toggle", "names", false)):
		_fail("names toggle refused")
		return
	await process_frame
	toggled = scene.call("composed_presentation_debug_state")
	if bool(toggled.get("state", {}).get("infrastructure_sites", true)) \
	or bool(toggled.get("state", {}).get("names", true)):
		_fail("detail surface toggles did not apply: %s" % JSON.stringify(toggled))
		return
	if _authority_pick(scene) != authority_reference:
		_fail("E2 toggles changed authority pick")
		return

	# Snapshot lifecycle: E1 must temporarily fall back to polygons and E2 must
	# rebuild exactly one atlas/control/minimap surface against the fresh cache.
	scene.call("_load_snapshot", SNAPSHOT)
	await process_frame
	var refresh_transition: Dictionary = scene.call("composed_presentation_debug_state")
	if bool(refresh_transition.get("active", true)):
		_fail("composed surface remained active while E1 cache was stale: %s" % JSON.stringify(refresh_transition))
		return
	if _authority_pick(scene) != authority_reference:
		_fail("E2 refresh transition changed authority pick")
		return
	if not await _wait_hybrid(scene):
		return
	if not await _wait_composed(scene):
		return
	var refresh_state: Dictionary = scene.call("composed_presentation_debug_state")
	if scene.find_children("Issue212ComposedAtlas", "Node2D", true, false).size() != 1:
		_fail("snapshot refresh duplicated composed atlas")
		return
	if scene.find_children("Issue212MapLayerControl", "Control", true, false).size() != 1:
		_fail("snapshot refresh duplicated layer control")
		return
	if scene.find_children("Issue212CachedMinimap", "Control", true, false).size() != 1:
		_fail("snapshot refresh duplicated minimap")
		return
	var refresh_layers: Dictionary = refresh_state.get("state", {})
	if bool(refresh_layers.get("formation_symbols", true)) \
	or bool(refresh_layers.get("operational_routes", true)) \
	or bool(refresh_layers.get("infrastructure_sites", true)) \
	or bool(refresh_layers.get("names", true)) \
	or bool(refresh_state.get("atlas_visible", true)) \
	or bool(refresh_state.get("route_enabled", true)):
		_fail("snapshot refresh did not preserve user layer disables: %s" % JSON.stringify(refresh_state))
		return
	if _authority_pick(scene) != authority_reference:
		_fail("E2 refreshed composition changed authority pick")
		return

	var hashes_after := _authority_hashes()
	if hashes_after != hashes_before:
		_fail("E2 changed authority bytes")
		return
	print("ISSUE212_COMPOSED_PRESENTATION_TEST %s" % JSON.stringify({
		"authority_pick": authority_reference,
		"hybrid_only": hybrid_composed,
		"full_theatre": full_state,
		"detailed": detailed_state,
		"toggled": toggled,
		"refresh_transition": refresh_transition,
		"refresh": refresh_state,
		"screenshots": ["full_theatre.png", "detailed.png"],
	}))
	print("map_composed_presentation_test: PASS")
	await _dispose(scene)
	_clear_env()
	quit(0)


func _prove_edge_counter_alignment(scene: Node) -> bool:
	var atlas := scene.find_child("Issue212ComposedAtlas", true, false) as StrategicIconAtlasLayer
	var battalions_value: Variant = scene.get("battalions_by_province")
	var active_map = scene.call("_active_map")
	if atlas == null or not battalions_value is Dictionary or active_map == null:
		_fail("edge alignment proof missing atlas/battalion/map state")
		return false
	var battalions := battalions_value as Dictionary
	var province_ids: Array = battalions.keys()
	province_ids.sort()
	if province_ids.is_empty():
		_fail("edge alignment proof has no battalion")
		return false
	var pid := String(province_ids[0])
	var battalion_value: Variant = battalions.get(pid, {})
	if not battalion_value is Dictionary:
		_fail("edge alignment proof battalion malformed")
		return false
	var battalion := battalion_value as Dictionary
	var had_display := battalion.has("display_pixel")
	var saved_display: Variant = battalion.get("display_pixel", null)
	var map_size_value: Vector2 = active_map.image_size()
	var edge_pixels := [
		Vector2(0.0, map_size_value.y * 0.5),
		Vector2(map_size_value.x, map_size_value.y * 0.5),
		Vector2(map_size_value.x * 0.5, 0.0),
		Vector2(map_size_value.x * 0.5, map_size_value.y),
	]
	var bounds: Rect2 = scene.call("_overlay_clamp_rect")
	for edge_pixel: Vector2 in edge_pixels:
		battalion["display_pixel"] = [edge_pixel.x, edge_pixel.y]
		battalions[pid] = battalion
		scene.call("_rebuild_composed_atlas_entries")
		var expected: Vector2 = scene.call("_composed_counter_screen_position", pid, battalion, active_map, bounds)
		var atlas_center := Vector2.INF
		for row_value in atlas.entries:
			if row_value is Dictionary and String((row_value as Dictionary).get("province_id", "")) == pid:
				var screen_value: Variant = (row_value as Dictionary).get("screen_position", null)
				if screen_value is Vector2:
					atlas_center = screen_value as Vector2
				break
		if atlas_center == Vector2.INF or atlas_center.distance_to(expected) > 0.01:
			_fail("atlas counter diverged from shared clamped center at edge %s expected=%s actual=%s" % [edge_pixel, expected, atlas_center])
			return false
		if atlas_center.x < bounds.position.x or atlas_center.x > bounds.end.x \
		or atlas_center.y < bounds.position.y or atlas_center.y > bounds.end.y:
			_fail("clamped counter center escaped overlay bounds at edge %s center=%s bounds=%s" % [edge_pixel, atlas_center, bounds])
			return false
		scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await RenderingServer.frame_post_draw
		var reserved_value: Variant = scene.get("_cached_reserved_rects")
		var found_reserved := false
		if reserved_value is Array:
			for rect_value in reserved_value as Array:
				if rect_value is Rect2 and (rect_value as Rect2).get_center().distance_to(expected) <= 0.01:
					found_reserved = true
					break
		if not found_reserved:
			_fail("live overlay reservation did not share atlas counter center at edge %s center=%s" % [edge_pixel, expected])
			return false
	if had_display:
		battalion["display_pixel"] = saved_display
	else:
		battalion.erase("display_pixel")
	battalions[pid] = battalion
	scene.call("_rebuild_composed_atlas_entries")
	scene.queue_redraw()
	return true


func _load_operational_snapshot(scene: Node, expect_composed: bool) -> bool:
	# main.gd::_ready() intentionally owns snapshot_source_path and overwrites any
	# pre-tree property injection. Exercise the actual reload boundary instead.
	scene.call("_load_snapshot", SNAPSHOT)
	var transition: Dictionary = scene.call("presentation_candidate_debug_state")
	if bool(transition.get("active", true)):
		_fail("operational snapshot load did not synchronously drop stale hybrid cache: %s" % JSON.stringify(transition))
		return false
	if expect_composed:
		var composed_transition: Dictionary = scene.call("composed_presentation_debug_state")
		if bool(composed_transition.get("active", true)):
			_fail("operational snapshot load left stale composed surface active: %s" % JSON.stringify(composed_transition))
			return false
	if not await _wait_hybrid(scene):
		return false
	if expect_composed and not await _wait_composed(scene):
		return false
	var battalions_value: Variant = scene.get("battalions_by_province")
	if not battalions_value is Dictionary or (battalions_value as Dictionary).is_empty():
		_fail("operational snapshot did not populate real battalions_by_province")
		return false
	return true


func _build_scene() -> Node:
	var packed := load("res://main.tscn") as PackedScene
	if packed == null:
		_fail("failed to load main.tscn")
		return null
	var scene := packed.instantiate()
	if scene == null:
		_fail("failed to instantiate main.tscn")
		return null
	if scene.get("presentation_fixture_path") != null:
		scene.presentation_fixture_path = FIXTURE
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = MANIFEST
	root.add_child(scene)
	for _i in range(12):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	if not bool(scene.get("map_backend_is_polygon")):
		_fail("main scene is not using PolygonMap authority")
		return null
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready) or int(pmap.province_count) != 3514:
		_fail("PolygonMap authority not ready/3514")
		return null
	return scene


func _wait_hybrid(scene: Node) -> bool:
	for _i in range(WAIT_FRAMES):
		var state: Dictionary = scene.call("presentation_candidate_debug_state")
		if bool(state.get("active", false)):
			return true
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	_fail("hybrid candidate did not activate: %s" % JSON.stringify(scene.call("presentation_candidate_debug_state")))
	return false


func _wait_composed(scene: Node) -> bool:
	for _i in range(WAIT_FRAMES):
		var state: Dictionary = scene.call("composed_presentation_debug_state")
		if bool(state.get("active", false)):
			return true
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	_fail("composed candidate did not activate: %s" % JSON.stringify(scene.call("composed_presentation_debug_state")))
	return false


func _authority_pick(scene: Node) -> Dictionary:
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready):
		return {"ok": false}
	var index := -1
	for i in range(int(pmap.province_count)):
		if int(pmap.is_water[i]) == 0:
			index = i
			break
	if index < 0:
		return {"ok": false}
	var expected := String(pmap.province_by_index[index])
	var actual := String(pmap.province_at_image_pos(pmap.centroids[index]))
	return {"ok": expected == actual and not expected.is_empty(), "expected": expected, "actual": actual, "province_count": int(pmap.province_count)}


func _capture(file_name: String) -> bool:
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image := viewport.get_texture().get_image() if viewport != null else null
	if image == null or image.is_empty():
		_fail("empty screenshot %s" % file_name)
		return false
	var path := _screens_dir.path_join(file_name)
	if image.save_png(path) != OK:
		_fail("failed to save screenshot %s" % path)
		return false
	return true


func _authority_hashes() -> Dictionary:
	var dataset_path := ""
	var file := FileAccess.open(MANIFEST, FileAccess.READ)
	if file != null:
		var parsed: Variant = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			var polygon_value: Variant = (parsed as Dictionary).get("polygon_dataset", {})
			if polygon_value is Dictionary:
				var rel := String((polygon_value as Dictionary).get("path", "polygon_dataset.json"))
				dataset_path = MANIFEST.get_base_dir().path_join(rel)
	return {"manifest_sha256": FileAccess.get_sha256(MANIFEST), "polygon_dataset_sha256": FileAccess.get_sha256(dataset_path), "snapshot_sha256": FileAccess.get_sha256(SNAPSHOT)}


func _dispose(scene: Node) -> void:
	if scene != null and is_instance_valid(scene):
		scene.queue_free()
	await process_frame
	await process_frame


func _clear_env() -> void:
	OS.set_environment(HYBRID_ENV, "")
	OS.set_environment(COMPOSED_ENV, "")


func _fail(message: String) -> void:
	push_error("map_composed_presentation_test: %s" % message)
	_clear_env()
	quit(1)
