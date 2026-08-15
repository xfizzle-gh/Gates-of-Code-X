extends "res://scripts/tools/map_raster_shadow_profiler_audited.gd"

## #212 Phase D executable audit harness.
## Explicitly typed where Godot 4.7 cannot infer values returned by PolygonMap.

const LOD_WARMUP := 6
const MAX_LOD_BASELINE_DRIFT_RATIO := 0.15
const PROFILE_DEFS := [
	{"name": "full_theatre_auto", "scale": 1.0, "all_disabled": false},
	{"name": "operational_auto", "scale": 2.0, "all_disabled": false},
	{"name": "detailed_auto", "scale": 3.0, "all_disabled": false},
	{"name": "all_measurable_disabled", "scale": 3.0, "all_disabled": true},
]

var _lod_screens_dir := "user://issue212-ux-lod-screens"
var _minimap_source: Image = null
var _map_image_size: Vector2 = Vector2.ONE


func _initialize() -> void:
	_snapshot_path = DEFAULT_SNAPSHOT
	_fixture_path = DEFAULT_FIXTURE
	_manifest_path = DEFAULT_MANIFEST
	_frames = 24
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--screens-dir="):
			_lod_screens_dir = text.substr(14).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--fixture="):
			_fixture_path = text.substr(10).strip_edges()
		elif text.begins_with("--manifest="):
			_manifest_path = text.substr(11).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
		elif text.begins_with("--frames="):
			_frames = maxi(int(text.substr(9)), 24)
	call_deferred("_run_ux_lod")


func _run_ux_lod() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)
	for path_value in [_snapshot_path, _fixture_path, _manifest_path]:
		var path := String(path_value)
		if not FileAccess.file_exists(path):
			_fail("required UX/LOD input missing: %s" % path)
			return

	var authority_before: Dictionary = _authority_hashes()
	var source_result: Dictionary = await _build_scene()
	if not bool(source_result.get("ok", false)):
		_fail("UX/LOD source scene failed: %s" % source_result.get("error", "unknown"))
		return
	var source_scene: Node = source_result.get("scene") as Node
	var source_map = _active_map(source_scene)
	var authority_error := _authority_error(source_scene, source_map)
	if not authority_error.is_empty():
		await _dispose_scene(source_scene)
		_fail(authority_error)
		return
	var reference: Dictionary = _authority_parity(source_scene, source_map)
	_minimap_source = await _capture_static_map(source_scene, source_map)
	var image_size_value: Variant = source_map.image_size()
	if image_size_value is Vector2:
		_map_image_size = image_size_value as Vector2
	elif image_size_value is Vector2i:
		var size_i := image_size_value as Vector2i
		_map_image_size = Vector2(float(size_i.x), float(size_i.y))
	await _dispose_scene(source_scene)
	if not bool(reference.get("ok", false)) or _minimap_source == null or _minimap_source.is_empty():
		_fail("UX/LOD reference or minimap cache failed")
		return

	var policy := StrategicMapLodPolicy.new()
	var defaults: Dictionary = policy.default_toggles()
	var profile_results: Dictionary = {}
	var profile_states: Dictionary = {}
	for profile_value in PROFILE_DEFS:
		var profile: Dictionary = profile_value as Dictionary
		var name := String(profile.get("name", ""))
		var scale := float(profile.get("scale", 1.0))
		var toggles: Dictionary = defaults.duplicate(true)
		if bool(profile.get("all_disabled", false)):
			for key_value in policy.measurable_layer_keys():
				toggles[String(key_value)] = false
		var state: Dictionary = policy.state_for_scale(scale, toggles)
		var bracket: Dictionary = await _measure_lod_bracket(scale, state, reference)
		if not bool(bracket.get("ok", false)):
			_fail("LOD bracket failed profile=%s detail=%s" % [name, JSON.stringify(bracket)])
			return
		profile_results[name] = bracket
		profile_states[name] = state

	DirAccess.make_dir_recursive_absolute(_lod_screens_dir)
	if not await _capture_lod_ui("full_theatre_auto", 1.0, policy.state_for_scale(1.0, defaults), reference):
		_fail("full-theatre LOD/UI screenshot failed")
		return
	if not await _capture_lod_ui("detailed_auto", 3.0, policy.state_for_scale(3.0, defaults), reference):
		_fail("detailed LOD/UI screenshot failed")
		return

	var minimap_proof: Dictionary = await _minimap_structure_proof(reference)
	if not bool(minimap_proof.get("ok", false)):
		_fail("cached minimap proof failed: %s" % JSON.stringify(minimap_proof))
		return

	var authority_after: Dictionary = _authority_hashes()
	if authority_after != authority_before:
		_fail("authority bytes changed during UX/LOD experiment")
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-ux-lod",
		"schema_version": 1,
		"issue": 212,
		"phase": "D-debug-ux-lod",
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": RenderingServer.get_video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"frames_per_sample": _frames,
		"control": {
			"design": "all-current-layers -> event-applied LOD state -> all-current-layers",
			"max_baseline_drift_ratio": MAX_LOD_BASELINE_DRIFT_RATIO,
			"policy_apply_count_per_scene": 1,
			"policy_has_process_loop": false,
			"layer_control_has_process_loop": false,
		},
		"layer_contract": {
			"keys": StrategicMapLodPolicy.LAYER_KEYS,
			"default_toggles": defaults,
			"measurable_current_surfaces": policy.measurable_layer_keys(),
			"contract_only_not_independently_measurable": policy.contract_only_layer_keys(),
			"profiles": profile_states,
		},
		"authority": {
			"unchanged": true,
			"hashes_before": authority_before,
			"hashes_after": authority_after,
			"polygon_backend_remains_live": true,
		},
		"profiles": profile_results,
		"minimap": minimap_proof,
		"screenshots": ["full_theatre_auto.png", "detailed_auto.png"],
		"notes": [
			"Full-theatre LOD keeps formation symbols while suppressing ordinary names, infrastructure/sites, operational routes, and debug overlays.",
			"Supply, objective, and fog/intelligence toggles are contract-only because the current fixture has no independent presentation surfaces for them.",
			"The minimap is one downsampled cached ImageTexture with lightweight overlays and no second live Earth3 scene.",
			"No Phase D prototype is mounted in production main.tscn by this PR.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_UX_LOD %s" % JSON.stringify({"profiles": profile_results.keys(), "minimap": minimap_proof.get("texture_size", {})}))
	print("map_ux_lod_profiler: PASS out=%s" % _out_path)
	quit(0)


func _measure_lod_bracket(scale: float, state: Dictionary, reference: Dictionary) -> Dictionary:
	var before: Dictionary = await _measure_lod_one(scale, {}, false, reference)
	if not bool(before.get("ok", false)):
		return before
	var candidate: Dictionary = await _measure_lod_one(scale, state, true, reference)
	if not bool(candidate.get("ok", false)):
		return candidate
	var after: Dictionary = await _measure_lod_one(scale, {}, false, reference)
	if not bool(after.get("ok", false)):
		return after
	var bm: Dictionary = before.get("metrics", {})
	var cm: Dictionary = candidate.get("metrics", {})
	var am: Dictionary = after.get("metrics", {})
	var local: Dictionary = _midpoint_metrics(bm, am)
	var drift: Dictionary = _baseline_drift(bm, am)
	var drift_ok := int(drift.get("draw_calls_p50_abs", 1)) == 0 \
		and int(drift.get("primitives_p50_abs", 1)) == 0 \
		and float(drift.get("frame_ms_p50_ratio", 1.0)) <= MAX_LOD_BASELINE_DRIFT_RATIO \
		and float(drift.get("frame_ms_p95_ratio", 1.0)) <= MAX_LOD_BASELINE_DRIFT_RATIO
	return {
		"ok": drift_ok,
		"baseline_before": bm,
		"lod": cm,
		"baseline_after": am,
		"local_baseline": local,
		"baseline_drift": drift,
		"delta": {
			"frame_ms_p50": snappedf(float(local["frame_time_ms"]["p50"]) - float(cm["frame_time_ms"]["p50"]), 0.001),
			"frame_ms_p95": snappedf(float(local["frame_time_ms"]["p95"]) - float(cm["frame_time_ms"]["p95"]), 0.001),
			"draw_calls_p50": int(local["draw_calls"]["p50"]) - int(cm["draw_calls"]["p50"]),
			"primitives_p50": int(local["primitives"]["p50"]) - int(cm["primitives"]["p50"]),
		},
	}


func _measure_lod_one(scale: float, state: Dictionary, apply_state: bool, reference: Dictionary) -> Dictionary:
	var built: Dictionary = await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene") as Node
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}
	if scene.get("view_scale") != null:
		scene.view_scale = scale
	if scene.get("view_offset") != null:
		scene.view_offset = Vector2.ZERO
	if apply_state:
		_apply_lod_state(scene, state)
	await _pump_fixed_frames(scene, LOD_WARMUP)
	var parity: Dictionary = _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return {"ok": false, "error": "LOD changed authority parity", "state": state, "parity": parity}
	var metrics: Dictionary = await _measure_fixed_frames(scene)
	await _dispose_scene(scene)
	return {"ok": true, "metrics": metrics, "parity": parity}


func _apply_lod_state(scene: Node, state: Dictionary) -> void:
	if not bool(state.get("formation_symbols", true)):
		_clear_dict_property(scene, "battalions_by_province")
		_clear_dict_property(scene, "battalion_stacks_by_province")
		_clear_fixture_keys(scene, ["synthetic_counters", "force_stack_badges"])
	if not bool(state.get("names", true)):
		_clear_fixture_keys(scene, ["proof_labels"])
		_suppress_dynamic_labels(scene)
	if not bool(state.get("infrastructure_sites", true)):
		_zero_snapshot_infrastructure(scene)
		_clear_fixture_keys(scene, ["control_sites"])
	if not bool(state.get("operational_routes", true)):
		_clear_fixture_keys(scene, ["routes"])
	if not bool(state.get("debug_overlays", true)):
		_clear_fixture_keys(scene, ["federal_subject_outlines", "europe_asia_boundary_pixels"])
	_mark_layers_dirty(scene)
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()


func _pump_fixed_frames(scene: Node, count: int) -> void:
	for _i in range(count):
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _measure_fixed_frames(scene: Node) -> Dictionary:
	var frame_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var script_ms: Array = []
	var video_mem: Array = []
	for _i in range(_frames):
		_mark_layers_dirty(scene)
		var t0 := Time.get_ticks_usec()
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		frame_ms.append((Time.get_ticks_usec() - t0) / 1000.0)
		draw_calls.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)))
		primitives.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)))
		script_ms.append(float(Performance.get_monitor(Performance.TIME_PROCESS)) * 1000.0)
		video_mem.append(int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)))
	return {
		"frame_time_ms": _stats(frame_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"script_cpu_ms": _stats(script_ms),
		"video_mem_bytes": _stats_int(video_mem),
	}


func _capture_lod_ui(name: String, scale: float, state: Dictionary, reference: Dictionary) -> bool:
	var built: Dictionary = await _build_scene()
	if not bool(built.get("ok", false)):
		return false
	var scene: Node = built.get("scene") as Node
	var active_map = _active_map(scene)
	if not _authority_error(scene, active_map).is_empty():
		await _dispose_scene(scene)
		return false
	if scene.get("view_scale") != null:
		scene.view_scale = scale
	_apply_lod_state(scene, state)
	var ui: Dictionary = _mount_prototype_ui(scene, active_map)
	await _pump_fixed_frames(scene, 5)
	if not _same_parity(reference, _authority_parity(scene, active_map)):
		await _dispose_scene(scene)
		return false
	var control := ui.get("control") as StrategicMapLayerControl
	if control != null:
		control.configure(StrategicMapLodPolicy.new().default_toggles())
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image: Image = viewport.get_texture().get_image() if viewport != null else null
	var ok := image != null and not image.is_empty()
	if ok:
		ok = image.save_png(_lod_screens_dir.path_join("%s.png" % name)) == OK
	await _dispose_scene(scene)
	return ok


func _mount_prototype_ui(scene: Node, active_map) -> Dictionary:
	var canvas := CanvasLayer.new()
	canvas.name = "Issue212UxLodPrototype"
	canvas.layer = 30
	scene.add_child(canvas)
	var policy := StrategicMapLodPolicy.new()
	var control := StrategicMapLayerControl.new()
	control.position = Vector2(16, 72)
	control.configure(policy.default_toggles())
	canvas.add_child(control)

	var selected_id := String(scene.get("selected_province_id") if scene.get("selected_province_id") != null else "")
	var selected_pixel: Vector2 = Vector2(-1, -1)
	if not selected_id.is_empty():
		var anchor_value: Variant = active_map.anchor_pixel(selected_id)
		if anchor_value is Vector2:
			selected_pixel = anchor_value as Vector2
		elif anchor_value is Vector2i:
			var anchor_i := anchor_value as Vector2i
			selected_pixel = Vector2(float(anchor_i.x), float(anchor_i.y))
	var front_pixels: Array = _fixture_front_pixels(scene)
	var minimap := StrategicMinimapPrototype.new()
	minimap.configure(_minimap_source, _map_image_size, selected_pixel, front_pixels)
	minimap.position = Vector2(16, 430)
	canvas.add_child(minimap)
	return {"canvas": canvas, "control": control, "minimap": minimap}


func _minimap_structure_proof(reference: Dictionary) -> Dictionary:
	var built: Dictionary = await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene") as Node
	var active_map = _active_map(scene)
	var ui: Dictionary = _mount_prototype_ui(scene, active_map)
	await _pump_fixed_frames(scene, 3)
	var minimap := ui.get("minimap") as StrategicMinimapPrototype
	var parity: Dictionary = _authority_parity(scene, active_map)
	var texture_width := 0
	var texture_height := 0
	var has_second_live_map := true
	if minimap != null:
		var texture_size: Vector2i = minimap.texture_size()
		texture_width = texture_size.x
		texture_height = texture_size.y
		has_second_live_map = minimap.has_live_map_descendant()
	var proof := {
		"ok": minimap != null and not has_second_live_map and _same_parity(reference, parity),
		"texture_size": {"width": texture_width, "height": texture_height},
		"second_live_earth3_scene": has_second_live_map,
		"source": "downsampled derived static Earth3 presentation cache",
		"selection_overlay": true,
		"front_contact_overlay_points": _fixture_front_pixels(scene).size(),
		"process_loop": false,
	}
	await _dispose_scene(scene)
	return proof


func _fixture_front_pixels(scene: Node) -> Array:
	var result: Array = []
	var fixture_value: Variant = scene.get("presentation_fixture")
	if not fixture_value is Dictionary:
		return result
	var fixture := fixture_value as Dictionary
	for route_value in fixture.get("routes", []):
		if not route_value is Dictionary:
			continue
		for point_value in (route_value as Dictionary).get("pixels", []):
			result.append(point_value)
	for contact_value in fixture.get("contacts", []):
		if contact_value is Dictionary and (contact_value as Dictionary).has("pixel"):
			result.append((contact_value as Dictionary).get("pixel"))
	return result
