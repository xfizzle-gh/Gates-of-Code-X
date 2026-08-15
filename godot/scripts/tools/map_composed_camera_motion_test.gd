extends SceneTree

## #212 regression: atlas counter centers must follow ordinary camera motion.
## This test deliberately never calls _rebuild_composed_atlas_entries().

const SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const FIXTURE := "res://fixtures/presentation/e3_operational.json"
const MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const HYBRID_ENV := "GOCX_PRESENTATION_CANDIDATE"
const COMPOSED_ENV := "GOCX_PRESENTATION_COMPOSED"
const WAIT_FRAMES := 300


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	OS.set_environment(HYBRID_ENV, "hybrid")
	OS.set_environment(COMPOSED_ENV, "1")
	var scene := await _build_scene()
	if scene == null:
		return
	scene.call("_load_snapshot", SNAPSHOT)
	if not await _wait_active(scene):
		return
	for _i in range(4):
		RenderingServer.force_draw(false, 0.0)
		await process_frame

	var atlas = scene.find_child("Issue212ComposedAtlas", true, false)
	var battalions_value: Variant = scene.get("battalions_by_province")
	var active_map = scene.call("_active_map")
	if atlas == null or not battalions_value is Dictionary or active_map == null:
		_fail("missing atlas/battalion/map state")
		return
	var battalions := battalions_value as Dictionary
	var bounds: Rect2 = scene.call("_overlay_clamp_rect")
	var chosen := _choose_interior_entry(scene, atlas.entries, battalions, active_map, bounds)
	if chosen.is_empty():
		_fail("could not find an interior atlas entry for camera-motion proof")
		return
	var pid := String(chosen.get("province_id", ""))
	var battalion: Dictionary = battalions.get(pid, {})
	var baseline := _entry_screen_position(atlas.entries, pid)
	var baseline_expected: Vector2 = scene.call("_composed_counter_screen_position", pid, battalion, active_map, bounds)
	if baseline == Vector2.INF or baseline.distance_to(baseline_expected) > 0.01:
		_fail("baseline atlas center does not match shared authority pid=%s actual=%s expected=%s" % [pid, baseline, baseline_expected])
		return

	var state_before: Dictionary = scene.call("composed_presentation_debug_state")
	var updates_before := int(state_before.get("atlas_camera_updates", 0))
	var original_offset: Vector2 = scene.view_offset
	scene.view_offset = original_offset + Vector2(72.0, 48.0)
	if not await _wait_camera_update(scene, updates_before, "pan"):
		return
	var panned := _entry_screen_position(atlas.entries, pid)
	var pan_expected: Vector2 = scene.call("_composed_counter_screen_position", pid, battalion, active_map, scene.call("_overlay_clamp_rect"))
	if panned == Vector2.INF or panned.distance_to(pan_expected) > 0.01:
		_fail("atlas did not follow normal pan pid=%s actual=%s expected=%s" % [pid, panned, pan_expected])
		return
	if panned.distance_to(baseline) < 1.0:
		_fail("normal pan left atlas counter at stale screen position pid=%s before=%s after=%s" % [pid, baseline, panned])
		return

	var pan_state: Dictionary = scene.call("composed_presentation_debug_state")
	var updates_after_pan := int(pan_state.get("atlas_camera_updates", 0))
	var original_scale: float = scene.view_scale
	scene.view_scale = 2.35 if original_scale < 2.0 else original_scale + 0.6
	if not await _wait_camera_update(scene, updates_after_pan, "zoom"):
		return
	var zoomed := _entry_screen_position(atlas.entries, pid)
	var zoom_expected: Vector2 = scene.call("_composed_counter_screen_position", pid, battalion, active_map, scene.call("_overlay_clamp_rect"))
	if zoomed == Vector2.INF or zoomed.distance_to(zoom_expected) > 0.01:
		_fail("atlas did not follow normal zoom pid=%s actual=%s expected=%s" % [pid, zoomed, zoom_expected])
		return
	if zoomed.distance_to(panned) < 1.0:
		_fail("normal zoom left atlas counter at stale screen position pid=%s pan=%s zoom=%s" % [pid, panned, zoomed])
		return

	var final_state: Dictionary = scene.call("composed_presentation_debug_state")
	if int(final_state.get("atlas_camera_updates", 0)) < updates_before + 2:
		_fail("camera update authority did not record both pan and zoom: %s" % JSON.stringify(final_state))
		return
	print("ISSUE212_COMPOSED_CAMERA_MOTION_TEST %s" % JSON.stringify({
		"province_id": pid,
		"baseline": baseline,
		"panned": panned,
		"zoomed": zoomed,
		"camera_updates_before": updates_before,
		"camera_updates_after": int(final_state.get("atlas_camera_updates", 0)),
	}))
	print("map_composed_camera_motion_test: PASS")
	await _dispose(scene)
	_clear_env()
	quit(0)


func _choose_interior_entry(scene: Node, entries: Array, battalions: Dictionary, active_map, bounds: Rect2) -> Dictionary:
	for row_value in entries:
		if not row_value is Dictionary:
			continue
		var row := row_value as Dictionary
		var pid := String(row.get("province_id", ""))
		var battalion_value: Variant = battalions.get(pid, {})
		if pid.is_empty() or not battalion_value is Dictionary:
			continue
		var battalion := battalion_value as Dictionary
		var center: Vector2 = scene.call("_composed_counter_screen_position", pid, battalion, active_map, bounds)
		if center.x > bounds.position.x + 120.0 and center.x < bounds.end.x - 120.0 \
		and center.y > bounds.position.y + 120.0 and center.y < bounds.end.y - 120.0:
			return row
	return {}


func _entry_screen_position(entries: Array, pid: String) -> Vector2:
	for row_value in entries:
		if not row_value is Dictionary:
			continue
		var row := row_value as Dictionary
		if String(row.get("province_id", "")) != pid:
			continue
		var value: Variant = row.get("screen_position", null)
		if value is Vector2:
			return value as Vector2
	return Vector2.INF


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


func _wait_active(scene: Node) -> bool:
	for _i in range(WAIT_FRAMES):
		var hybrid: Dictionary = scene.call("presentation_candidate_debug_state")
		var composed: Dictionary = scene.call("composed_presentation_debug_state")
		if bool(hybrid.get("active", false)) and bool(composed.get("active", false)):
			var battalions_value: Variant = scene.get("battalions_by_province")
			if battalions_value is Dictionary and not (battalions_value as Dictionary).is_empty():
				return true
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	_fail("candidate/composition did not become active")
	return false


func _wait_camera_update(scene: Node, previous: int, label: String) -> bool:
	for _i in range(WAIT_FRAMES):
		var state: Dictionary = scene.call("composed_presentation_debug_state")
		if int(state.get("atlas_camera_updates", 0)) > previous:
			return true
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	_fail("atlas camera update did not occur after %s" % label)
	return false


func _dispose(scene: Node) -> void:
	if scene != null and is_instance_valid(scene):
		scene.queue_free()
	await process_frame
	await process_frame


func _clear_env() -> void:
	OS.set_environment(HYBRID_ENV, "")
	OS.set_environment(COMPOSED_ENV, "")


func _fail(message: String) -> void:
	push_error("map_composed_camera_motion_test: %s" % message)
	_clear_env()
	quit(1)
