extends "res://scripts/tools/map_raster_shadow_profiler_audited.gd"

## #212 Phase C: compare the current procedural counter path against one
## repository-owned atlas texture on one CanvasItem. Numeric strength remains
## separate text and is never baked into per-strength textures.

const COUNTS := [64, 256, 512]
const MAX_COUNTER_BASELINE_DRIFT_RATIO := 0.15
const COUNTER_WARMUP := 6
const FACTIONS := ["nato", "ukr", "rusa", "prc", "neutral"]
const GLYPHS := ["I", "m", "M", "T", "A", "R", "D", "E", "C", "L", "H", "S", "O", "B", "!", "!", "!", "F"]

var _atlas_screens_dir := "user://issue212-icon-atlas-screens"


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
			_atlas_screens_dir = text.substr(14).strip_edges()
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
	call_deferred("_run_icon_atlas")


func _run_icon_atlas() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)
	for path_value in [_snapshot_path, _fixture_path, _manifest_path]:
		if not FileAccess.file_exists(String(path_value)):
			_fail("required icon-atlas input missing: %s" % String(path_value))
			return

	var authority_before := _authority_hashes()
	var source_result := await _build_scene()
	if not bool(source_result.get("ok", false)):
		_fail("icon-atlas source failed: %s" % source_result.get("error", "unknown"))
		return
	var source_scene: Node = source_result.get("scene")
	var source_map = _active_map(source_scene)
	var error := _authority_error(source_scene, source_map)
	if not error.is_empty():
		await _dispose_scene(source_scene)
		_fail(error)
		return
	var reference := _authority_parity(source_scene, source_map)
	await _dispose_scene(source_scene)
	if not bool(reference.get("ok", false)):
		_fail("icon-atlas reference parity failed")
		return

	DirAccess.make_dir_recursive_absolute(_atlas_screens_dir)
	var results: Dictionary = {}
	for count_value in COUNTS:
		var count := int(count_value)
		var row := {}
		for mode in ["procedural", "atlas_text"]:
			var bracket := await _measure_counter_bracket(String(mode), count, "idle_full_theatre", reference)
			if not bool(bracket.get("ok", false)):
				_fail("counter bracket failed mode=%s count=%s detail=%s" % [mode, count, JSON.stringify(bracket)])
				return
			row[String(mode)] = bracket
		results[str(count)] = {"idle_full_theatre": row}

	# The largest fixture also exercises zoom motion and a symbol-only atlas
	# diagnostic, proving numeric strength is separable from the symbol texture.
	for mode in ["procedural", "atlas_text", "atlas_symbols_only"]:
		var bracket := await _measure_counter_bracket(String(mode), 512, "continuous_zoom", reference)
		if not bool(bracket.get("ok", false)):
			_fail("zoom counter bracket failed mode=%s detail=%s" % [mode, JSON.stringify(bracket)])
			return
		(results["512"] as Dictionary)["continuous_zoom_%s" % String(mode)] = bracket

	if not await _capture_counter_screenshot("procedural", 512, reference):
		_fail("procedural 512 screenshot failed")
		return
	if not await _capture_counter_screenshot("atlas_text", 512, reference):
		_fail("atlas 512 screenshot failed")
		return

	var authority_after := _authority_hashes()
	if authority_after != authority_before:
		_fail("authority bytes changed during icon-atlas experiment")
		return

	var prototype := StrategicIconAtlasLayer.new()
	var vocabulary := prototype.vocabulary()
	var atlas_size := prototype.atlas_size()
	prototype.free()
	if vocabulary.size() != 18:
		_fail("strategic icon vocabulary incomplete: %s" % vocabulary.size())
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-icon-atlas-comparison",
		"schema_version": 1,
		"issue": 212,
		"phase": "C-debug-icon-atlas",
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": RenderingServer.get_video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"frames_per_sample": _frames,
		"control": {
			"design": "baseline_without_stress -> counter_mode -> baseline_without_stress",
			"max_baseline_drift_ratio": MAX_COUNTER_BASELINE_DRIFT_RATIO,
		},
		"atlas": {
			"source": "repository-owned procedural 7x7 pixel patterns",
			"copied_reference_art": false,
			"texture_count": 1,
			"size": {"width": atlas_size.x, "height": atlas_size.y},
			"cell_size": StrategicIconAtlasLayer.CELL_SIZE,
			"vocabulary": vocabulary,
			"numeric_strength_baked": false,
			"strength_text_separate": true,
		},
		"authority": {
			"unchanged": true,
			"hashes_before": authority_before,
			"hashes_after": authority_after,
			"polygon_backend_remains_live": true,
		},
		"stress_counts": COUNTS,
		"results": results,
		"screenshots": ["procedural_512.png", "atlas_text_512.png"],
		"notes": [
			"The procedural control uses the existing presentation_fixture synthetic_counters path and MapMarkers.draw_formation_counter.",
			"The atlas path uses one ImageTexture and draw_texture_rect_region calls on one Node2D CanvasItem; numeric strength remains draw_string text.",
			"The atlas prototype is not mounted by production main.tscn in this PR.",
			"Absolute CI frame time is llvmpipe evidence only, not owner-native acceptance.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_ICON_ATLAS %s" % JSON.stringify({
		"vocabulary_count": vocabulary.size(),
		"counts": COUNTS,
	}))
	print("map_icon_atlas_profiler: PASS out=%s" % _out_path)
	quit(0)


func _measure_counter_bracket(mode: String, count: int, scenario: String, reference: Dictionary) -> Dictionary:
	var before := await _measure_counter_one("baseline", count, scenario, reference)
	if not bool(before.get("ok", false)):
		return before
	var candidate := await _measure_counter_one(mode, count, scenario, reference)
	if not bool(candidate.get("ok", false)):
		return candidate
	var after := await _measure_counter_one("baseline", count, scenario, reference)
	if not bool(after.get("ok", false)):
		return after
	var bm: Dictionary = before.get("metrics", {})
	var cm: Dictionary = candidate.get("metrics", {})
	var am: Dictionary = after.get("metrics", {})
	var local := _midpoint_metrics(bm, am)
	var drift := _baseline_drift(bm, am)
	var drift_ok := int(drift.get("draw_calls_p50_abs", 1)) == 0 \
		and int(drift.get("primitives_p50_abs", 1)) == 0 \
		and float(drift.get("frame_ms_p50_ratio", 1.0)) <= MAX_COUNTER_BASELINE_DRIFT_RATIO \
		and float(drift.get("frame_ms_p95_ratio", 1.0)) <= MAX_COUNTER_BASELINE_DRIFT_RATIO
	return {
		"ok": drift_ok,
		"baseline_before": bm,
		"candidate": cm,
		"baseline_after": am,
		"local_baseline": local,
		"baseline_drift": drift,
		"incremental": {
			"frame_ms_p50": snappedf(float(cm["frame_time_ms"]["p50"]) - float(local["frame_time_ms"]["p50"]), 0.001),
			"frame_ms_p95": snappedf(float(cm["frame_time_ms"]["p95"]) - float(local["frame_time_ms"]["p95"]), 0.001),
			"draw_calls_p50": int(cm["draw_calls"]["p50"]) - int(local["draw_calls"]["p50"]),
			"primitives_p50": int(cm["primitives"]["p50"]) - int(local["primitives"]["p50"]),
		},
	}


func _measure_counter_one(mode: String, count: int, scenario: String, reference: Dictionary) -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}
	var layer := _configure_counter_mode(scene, mode, count)
	await _pump_counter_frames(scene, layer, COUNTER_WARMUP, scenario)
	var parity := _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return {"ok": false, "error": "counter mode changed authority parity", "mode": mode, "parity": parity}
	var metrics := await _measure_counter_frames(scene, layer, scenario)
	await _dispose_scene(scene)
	return {"ok": true, "metrics": metrics, "parity": parity}


func _configure_counter_mode(scene: Node, mode: String, count: int) -> StrategicIconAtlasLayer:
	_clear_dict_property(scene, "battalions_by_province")
	_clear_dict_property(scene, "battalion_stacks_by_province")
	var fixture_value: Variant = scene.get("presentation_fixture")
	if fixture_value is Dictionary:
		var fixture := fixture_value as Dictionary
		fixture["synthetic_counters"] = []
		fixture["force_stack_badges"] = []
	var layer: StrategicIconAtlasLayer = null
	if mode == "procedural":
		if fixture_value is Dictionary:
			(fixture_value as Dictionary)["synthetic_counters"] = _procedural_rows(count)
	elif mode == "atlas_text" or mode == "atlas_symbols_only":
		layer = StrategicIconAtlasLayer.new()
		layer.name = "Issue212StrategicIconAtlas"
		layer.z_index = 20
		var map_space_value: Variant = scene.get("map_space")
		layer.configure(map_space_value, _atlas_rows(count), mode == "atlas_text")
		scene.add_child(layer)
	elif mode != "baseline":
		push_error("unknown counter mode: %s" % mode)
	_mark_layers_dirty(scene)
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()
	return layer


func _pump_counter_frames(scene: Node, layer: StrategicIconAtlasLayer, count: int, scenario: String) -> void:
	for i in range(count):
		_apply_scenario(scene, scenario, i, count)
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if layer != null:
			layer.queue_redraw()
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _measure_counter_frames(scene: Node, layer: StrategicIconAtlasLayer, scenario: String) -> Dictionary:
	var frame_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var script_ms: Array = []
	var video_mem: Array = []
	for i in range(_frames):
		_apply_scenario(scene, scenario, i, _frames)
		_mark_layers_dirty(scene)
		var t0 := Time.get_ticks_usec()
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if layer != null:
			layer.queue_redraw()
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


func _capture_counter_screenshot(mode: String, count: int, reference: Dictionary) -> bool:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return false
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	if not _authority_error(scene, active_map).is_empty():
		await _dispose_scene(scene)
		return false
	var layer := _configure_counter_mode(scene, mode, count)
	await _pump_counter_frames(scene, layer, 4, "idle_full_theatre")
	if not _same_parity(reference, _authority_parity(scene, active_map)):
		await _dispose_scene(scene)
		return false
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image := viewport.get_texture().get_image() if viewport != null else null
	var ok := image != null and not image.is_empty()
	if ok:
		ok = image.save_png(_atlas_screens_dir.path_join("%s_512.png" % mode)) == OK
	await _dispose_scene(scene)
	return ok


func _procedural_rows(count: int) -> Array:
	var atlas := _atlas_rows(count)
	var rows: Array = []
	for i in range(atlas.size()):
		var row: Dictionary = atlas[i]
		rows.append({
			"pixel": row.get("pixel", []),
			"faction": row.get("faction", "neutral"),
			"glyph": GLYPHS[i % GLYPHS.size()],
			"strength": row.get("strength", 0),
			"stack": 1,
		})
	return rows


func _atlas_rows(count: int) -> Array:
	var rows: Array = []
	var colors := {
		"nato": Color("4f8fd8"),
		"ukr": Color("e2c84a"),
		"rusa": Color("c95b5b"),
		"prc": Color("d08a3f"),
		"neutral": Color("707780"),
	}
	var columns := 32
	for i in range(count):
		var col := i % columns
		var row := int(i / columns)
		var faction := String(FACTIONS[i % FACTIONS.size()])
		rows.append({
			"pixel": [240 + col * 120, 240 + row * 170],
			"faction": faction,
			"color": colors[faction],
			"icon_key": StrategicIconAtlasLayer.ICON_KEYS[i % StrategicIconAtlasLayer.ICON_KEYS.size()],
			"strength": 5 + (i % 15),
		})
	return rows
