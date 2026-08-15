extends SceneTree

## #212 E3 owner-native acceptance harness.
##
## This profiler is deliberately incapable of authorizing the production switch.
## It gathers same-process, locally bracketed polygon -> composed candidate ->
## polygon evidence plus screenshots and authority hashes. The resulting JSON
## always leaves owner visual/performance acceptance and switch authorization
## false for an explicit human/independent-review decision after inspection.

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_theatre.json"
const MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const HYBRID_ENV := "GOCX_PRESENTATION_CANDIDATE"
const COMPOSED_ENV := "GOCX_PRESENTATION_COMPOSED"
const FRAMES := 24
const WARMUP_FRAMES := 8
const STABILIZATION_PASSES := 2
const MAX_BASELINE_DRIFT_RATIO := 0.15
const WAIT_FRAMES := 360
const SCENARIOS := ["idle_full_theatre", "continuous_pan", "continuous_zoom"]
const LAND_PROBE_TARGETS := [
	Vector2(0.16, 0.18),
	Vector2(0.84, 0.18),
	Vector2(0.50, 0.50),
	Vector2(0.20, 0.82),
	Vector2(0.80, 0.82),
]
const WATER_PROBE_TARGETS := [
	Vector2(0.12, 0.48),
	Vector2(0.55, 0.30),
	Vector2(0.86, 0.64),
]

var _snapshot_path := DEFAULT_SNAPSHOT
var _out_path := "user://issue212-native-acceptance.json"
var _screens_dir := "user://issue212-native-acceptance-screens"
var _width := 1920
var _height := 1080


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--screens-dir="):
			_screens_dir = text.substr(14).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 1280)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 720)
	call_deferred("_run")


func _run() -> void:
	if not FileAccess.file_exists(_snapshot_path):
		_fail("snapshot missing: %s" % _snapshot_path)
		return
	if not FileAccess.file_exists(MANIFEST):
		_fail("Earth3 manifest missing")
		return
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)
	DirAccess.make_dir_recursive_absolute(_screens_dir)

	var authority_before := _authority_hashes()
	var reference_scene := await _build_scene(false)
	if reference_scene == null:
		return
	var reference := _authority_state(reference_scene)
	if not bool(reference.get("ok", false)):
		await _dispose(reference_scene)
		_fail("reference authority state failed: %s" % JSON.stringify(reference))
		return
	await _dispose(reference_scene)

	# Burn process-first renderer/font/resource warmup outside every recorded bracket.
	for pass_index in range(STABILIZATION_PASSES):
		var warm := await _measure_one(false, "idle_full_theatre", reference)
		if not bool(warm.get("ok", false)):
			_fail("stabilization failed pass=%s detail=%s" % [pass_index, JSON.stringify(warm)])
			return

	var scenarios: Dictionary = {}
	var max_drift := 0.0
	for scenario_value in SCENARIOS:
		var scenario := String(scenario_value)
		var bracket := await _measure_bracket(scenario, reference)
		if not bool(bracket.get("ok", false)):
			_fail("acceptance bracket failed scenario=%s detail=%s" % [scenario, JSON.stringify(bracket)])
			return
		scenarios[scenario] = bracket
		var drift: Dictionary = bracket.get("baseline_drift", {})
		max_drift = maxf(max_drift, float(drift.get("frame_ms_p50_ratio", 0.0)))
		max_drift = maxf(max_drift, float(drift.get("frame_ms_p95_ratio", 0.0)))

	if not await _capture_mode(false, "polygon_full_theatre.png", 1.0, reference):
		return
	if not await _capture_mode(true, "candidate_full_theatre.png", 1.0, reference):
		return
	if not await _capture_mode(false, "polygon_detailed.png", 3.0, reference):
		return
	if not await _capture_mode(true, "candidate_detailed.png", 3.0, reference):
		return

	var authority_after := _authority_hashes()
	if authority_after != authority_before:
		_fail("acceptance harness changed authority bytes")
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-native-acceptance",
		"schema_version": 2,
		"issue": 212,
		"phase": "E3-owner-native-acceptance-harness",
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": RenderingServer.get_video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"snapshot_path": _snapshot_path,
		"frames_per_sample": FRAMES,
		"stabilization_passes": STABILIZATION_PASSES,
		"max_baseline_drift_ratio": MAX_BASELINE_DRIFT_RATIO,
		"max_observed_baseline_drift_ratio": snappedf(max_drift, 0.0001),
		"candidate_activation": "requested snapshot loaded before raster/composed activation",
		"authority": {
			"reference": reference,
			"hashes_before": authority_before,
			"hashes_after": authority_after,
			"unchanged": true,
			"polygon_backend_remains_live_in_candidate": true,
		},
		"scenarios": scenarios,
		"screenshots": [
			"polygon_full_theatre.png",
			"candidate_full_theatre.png",
			"polygon_detailed.png",
			"candidate_detailed.png",
		],
		"decision": {
			"ci_harness_only": OS.get_name() != "Windows",
			"owner_native_evidence_collected": false,
			"owner_visual_accepted": false,
			"owner_native_performance_accepted": false,
			"independent_review_accepted": false,
			"production_switch_authorized": false,
			"note": "Metrics are evidence only. A separate owner/native visual and performance decision plus independent review is required before any default renderer switch.",
		},
	}
	_write_json(_out_path, result)
	print("ISSUE212_NATIVE_ACCEPTANCE %s" % JSON.stringify(_summary(result)))
	print("map_candidate_native_acceptance: PASS out=%s" % _out_path)
	_clear_env()
	quit(0)


func _measure_bracket(scenario: String, reference: Dictionary) -> Dictionary:
	var before := await _measure_one(false, scenario, reference)
	if not bool(before.get("ok", false)):
		return before
	var candidate := await _measure_one(true, scenario, reference)
	if not bool(candidate.get("ok", false)):
		return candidate
	var after := await _measure_one(false, scenario, reference)
	if not bool(after.get("ok", false)):
		return after
	var bm: Dictionary = before.get("metrics", {})
	var cm: Dictionary = candidate.get("metrics", {})
	var am: Dictionary = after.get("metrics", {})
	var local := _midpoint_metrics(bm, am)
	var drift := _baseline_drift(bm, am)
	var drift_ok := int(drift.get("draw_calls_p50_abs", 1)) == 0 \
		and int(drift.get("primitives_p50_abs", 1)) == 0 \
		and float(drift.get("frame_ms_p50_ratio", 1.0)) <= MAX_BASELINE_DRIFT_RATIO \
		and float(drift.get("frame_ms_p95_ratio", 1.0)) <= MAX_BASELINE_DRIFT_RATIO
	return {
		"ok": drift_ok,
		"polygon_before": bm,
		"candidate": cm,
		"polygon_after": am,
		"local_polygon_baseline": local,
		"baseline_drift": drift,
		"candidate_state": candidate.get("candidate_state", {}),
		"improvement": {
			"frame_ms_p50": snappedf(float(local["frame_time_ms"]["p50"]) - float(cm["frame_time_ms"]["p50"]), 0.001),
			"frame_ms_p95": snappedf(float(local["frame_time_ms"]["p95"]) - float(cm["frame_time_ms"]["p95"]), 0.001),
			"frame_p50_ratio": snappedf(_improvement_ratio(float(local["frame_time_ms"]["p50"]), float(cm["frame_time_ms"]["p50"])), 0.0001),
			"frame_p95_ratio": snappedf(_improvement_ratio(float(local["frame_time_ms"]["p95"]), float(cm["frame_time_ms"]["p95"])), 0.0001),
			"draw_calls_p50": int(local["draw_calls"]["p50"]) - int(cm["draw_calls"]["p50"]),
			"primitives_p50": int(local["primitives"]["p50"]) - int(cm["primitives"]["p50"]),
			"video_mem_bytes_p50": int(local["video_mem_bytes"]["p50"]) - int(cm["video_mem_bytes"]["p50"]),
		},
	}


func _measure_one(candidate_enabled: bool, scenario: String, reference: Dictionary) -> Dictionary:
	var scene := await _build_scene(candidate_enabled)
	if scene == null:
		return {"ok": false, "error": "scene build failed"}
	_apply_scenario(scene, scenario, 0, FRAMES)
	for i in range(WARMUP_FRAMES):
		_apply_scenario(scene, scenario, i, WARMUP_FRAMES)
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var parity := _authority_state(scene)
	if not _same_authority(reference, parity):
		await _dispose(scene)
		return {"ok": false, "error": "authority parity changed", "candidate": candidate_enabled, "parity": parity}
	var metrics := await _measure_frames(scene, scenario)
	var candidate_state := scene.call("presentation_candidate_debug_state") if candidate_enabled else {}
	if candidate_enabled:
		candidate_state["composed"] = scene.call("composed_presentation_debug_state")
	await _dispose(scene)
	return {"ok": true, "metrics": metrics, "authority": parity, "candidate_state": candidate_state}


func _measure_frames(scene: Node, scenario: String) -> Dictionary:
	var frame_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var video_mem: Array = []
	var script_ms: Array = []
	var resident_tiles: Array = []
	for i in range(FRAMES):
		_apply_scenario(scene, scenario, i, FRAMES)
		var t0 := Time.get_ticks_usec()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		frame_ms.append((Time.get_ticks_usec() - t0) / 1000.0)
		draw_calls.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)))
		primitives.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)))
		video_mem.append(int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)))
		script_ms.append(float(Performance.get_monitor(Performance.TIME_PROCESS)) * 1000.0)
		if bool(scene.get("presentation_candidate_active")):
			var row: Dictionary = scene.call("presentation_candidate_debug_state").get("candidate", {})
			resident_tiles.append(int(row.get("resident_tiles", 0)))
	return {
		"frame_time_ms": _stats(frame_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"video_mem_bytes": _stats_int(video_mem),
		"script_cpu_ms": _stats(script_ms),
		"resident_tiles": _stats_int(resident_tiles) if not resident_tiles.is_empty() else {},
	}


func _build_scene(candidate_enabled: bool) -> Node:
	# The expensive candidate must never render the startup/default snapshot only to
	# throw that cache away. Start with both gates disabled, load the requested
	# authority through the real runtime boundary, then activate E1/E2 explicitly.
	_clear_env()
	var packed := load("res://main.tscn") as PackedScene
	if packed == null:
		_fail("failed to load main.tscn")
		return null
	var scene := packed.instantiate()
	if scene == null:
		_fail("failed to instantiate main.tscn")
		return null
	root.add_child(scene)
	for _i in range(12):
		RenderingServer.force_draw(false, 0.0)
		await process_frame

	scene.call("_load_snapshot", _snapshot_path)
	for _i in range(3):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	if not bool(scene.get("map_backend_is_polygon")):
		_fail("scene did not load PolygonMap authority")
		return null
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready) or int(pmap.province_count) != 3514:
		_fail("scene PolygonMap authority not ready/3514")
		return null
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")

	if candidate_enabled:
		OS.set_environment(HYBRID_ENV, "hybrid")
		OS.set_environment(COMPOSED_ENV, "1")
		scene.set("composed_presentation_requested", true)
		scene.set("composed_presentation_status", "waiting_for_hybrid_candidate")
		scene.call("set_presentation_candidate_enabled", true)
		for _i in range(WAIT_FRAMES):
			var hybrid: Dictionary = scene.call("presentation_candidate_debug_state")
			var composed: Dictionary = scene.call("composed_presentation_debug_state")
			if bool(hybrid.get("active", false)) and bool(composed.get("active", false)):
				return scene
			RenderingServer.force_draw(false, 0.0)
			await process_frame
		_fail("candidate/composition failed to activate after requested snapshot load")
		return null
	var default_hybrid: Dictionary = scene.call("presentation_candidate_debug_state")
	var default_composed: Dictionary = scene.call("composed_presentation_debug_state")
	if bool(default_hybrid.get("active", false)) or bool(default_composed.get("active", false)):
		_fail("polygon control unexpectedly activated candidate")
		return null
	return scene


func _apply_scenario(scene: Node, scenario: String, i: int, total: int) -> void:
	var t := float(i) / float(maxi(total - 1, 1))
	if scenario == "idle_full_theatre":
		if scene.get("view_scale") != null:
			scene.view_scale = 1.0
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2.ZERO
	elif scenario == "continuous_pan":
		if scene.get("view_scale") != null:
			scene.view_scale = 2.2
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0)
	elif scenario == "continuous_zoom":
		if scene.get("view_scale") != null:
			scene.view_scale = lerpf(1.0, 4.0, 0.5 + 0.5 * sin(t * TAU))
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2(cos(t * TAU) * 40.0, sin(t * TAU) * 30.0)
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()


func _capture_mode(candidate_enabled: bool, file_name: String, scale_value: float, reference: Dictionary) -> bool:
	var scene := await _build_scene(candidate_enabled)
	if scene == null:
		return false
	if scene.get("view_scale") != null:
		scene.view_scale = scale_value
	if scene.get("view_offset") != null:
		scene.view_offset = Vector2.ZERO
	for _i in range(10):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var parity := _authority_state(scene)
	if not _same_authority(reference, parity):
		await _dispose(scene)
		_fail("screenshot authority parity changed: %s" % file_name)
		return false
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image := viewport.get_texture().get_image() if viewport != null else null
	if image == null or image.is_empty():
		await _dispose(scene)
		_fail("empty screenshot %s" % file_name)
		return false
	var ok := image.save_png(_screens_dir.path_join(file_name)) == OK
	await _dispose(scene)
	if not ok:
		_fail("failed to save screenshot %s" % file_name)
	return ok


func _authority_state(scene: Node) -> Dictionary:
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready):
		return {"ok": false}
	var land_indices := _geographic_probe_indices(pmap, false, LAND_PROBE_TARGETS, false)
	var water_indices := _geographic_probe_indices(pmap, true, WATER_PROBE_TARGETS, true)
	var picks: Array = []
	for index_value in land_indices:
		var index := int(index_value)
		var expected := String(pmap.province_by_index[index])
		var pixel: Vector2 = pmap.centroids[index]
		var actual := String(pmap.province_at_image_pos(pixel))
		picks.append({
			"province_id": expected,
			"pixel": [snappedf(pixel.x, 0.001), snappedf(pixel.y, 0.001)],
			"actual": actual,
			"match": expected == actual,
		})
	var water_probes: Array = []
	for index_value in water_indices:
		var index := int(index_value)
		var water_id := String(pmap.province_by_index[index])
		var pixel: Vector2 = pmap.centroids[index]
		var backend_actual := String(pmap.province_at_image_pos(pixel))
		var screen: Vector2 = scene.call("_image_to_screen", pixel)
		var ui_actual := String(scene.call("_province_at", screen))
		water_probes.append({
			"water_id": water_id,
			"pixel": [snappedf(pixel.x, 0.001), snappedf(pixel.y, 0.001)],
			"backend_actual": backend_actual,
			"ui_actual": ui_actual,
			"match": backend_actual.is_empty() and ui_actual.is_empty(),
		})
	var legal_ids: Array = []
	var legal_value: Variant = scene.get("legal_targets")
	if legal_value is Dictionary:
		legal_ids = (legal_value as Dictionary).keys()
		legal_ids.sort()
	var operational_nodes := _operational_node_coordinate_probes(scene)
	var counter_pixels := _counter_coordinate_probes(scene, pmap)
	var ok := picks.size() == LAND_PROBE_TARGETS.size() and water_probes.size() == WATER_PROBE_TARGETS.size()
	for row_value in picks:
		ok = ok and bool((row_value as Dictionary).get("match", false))
	for row_value in water_probes:
		ok = ok and bool((row_value as Dictionary).get("match", false))
	ok = ok and not operational_nodes.is_empty() and not counter_pixels.is_empty()
	return {
		"ok": ok,
		"province_count": int(pmap.province_count),
		"picks": picks,
		"water_nonselection_probes": water_probes,
		"operational_node_pixels": operational_nodes,
		"counter_pixels": counter_pixels,
		"selected_province_id": String(scene.get("selected_province_id") if scene.get("selected_province_id") != null else ""),
		"legal_target_ids": legal_ids,
	}


func _geographic_probe_indices(pmap, water: bool, targets: Array, require_nonselectable: bool) -> Array:
	var chosen: Array = []
	var image_size: Vector2 = pmap.image_size()
	for target_value in targets:
		var normalized: Vector2 = target_value as Vector2
		var target := Vector2(normalized.x * image_size.x, normalized.y * image_size.y)
		var best := -1
		var best_distance := INF
		for i in range(int(pmap.province_count)):
			if (int(pmap.is_water[i]) == 1) != water or chosen.has(i):
				continue
			if require_nonselectable and not String(pmap.province_at_image_pos(pmap.centroids[i])).is_empty():
				continue
			var distance := (pmap.centroids[i] as Vector2).distance_squared_to(target)
			if distance < best_distance:
				best_distance = distance
				best = i
		if best >= 0:
			chosen.append(best)
	return chosen


func _sample_sorted_keys(keys: Array, limit: int) -> Array:
	var sorted := keys.duplicate()
	sorted.sort()
	if sorted.size() <= limit:
		return sorted
	var result: Array = []
	for i in range(limit):
		var position := int(round(float(i) * float(sorted.size() - 1) / float(maxi(limit - 1, 1))))
		var value: Variant = sorted[position]
		if not result.has(value):
			result.append(value)
	return result


func _operational_node_coordinate_probes(scene: Node) -> Array:
	var graph = scene.get("operational_graph")
	if graph == null or not bool(graph.is_ready):
		return []
	var nodes_value: Variant = graph.index.get("nodes", {})
	if not nodes_value is Dictionary:
		return []
	var nodes := nodes_value as Dictionary
	var result: Array = []
	for node_id_value in _sample_sorted_keys(nodes.keys(), 5):
		var node_id := String(node_id_value)
		var row_value: Variant = nodes.get(node_id, {})
		if not row_value is Dictionary:
			continue
		var pixel_value: Variant = (row_value as Dictionary).get("pixel", null)
		if not pixel_value is Array or (pixel_value as Array).size() < 2:
			continue
		result.append({
			"node_id": node_id,
			"pixel": [snappedf(float(pixel_value[0]), 0.001), snappedf(float(pixel_value[1]), 0.001)],
		})
	return result


func _counter_coordinate_probes(scene: Node, pmap) -> Array:
	var battalions_value: Variant = scene.get("battalions_by_province")
	if not battalions_value is Dictionary:
		return []
	var battalions := battalions_value as Dictionary
	var result: Array = []
	for pid_value in _sample_sorted_keys(battalions.keys(), 5):
		var pid := String(pid_value)
		var battalion_value: Variant = battalions.get(pid, {})
		if not battalion_value is Dictionary or not pmap.row_by_province.has(pid):
			continue
		var battalion := battalion_value as Dictionary
		var pixel: Vector2 = pmap.anchor_pixel(pid)
		var display_value: Variant = battalion.get("display_pixel", null)
		if display_value is Array and (display_value as Array).size() >= 2:
			pixel = Vector2(float(display_value[0]), float(display_value[1]))
		result.append({
			"province_id": pid,
			"pixel": [snappedf(pixel.x, 0.001), snappedf(pixel.y, 0.001)],
		})
	return result


func _same_authority(reference: Dictionary, candidate: Dictionary) -> bool:
	return bool(candidate.get("ok", false)) \
		and candidate.get("province_count", 0) == reference.get("province_count", -1) \
		and candidate.get("picks", []) == reference.get("picks", []) \
		and candidate.get("water_nonselection_probes", []) == reference.get("water_nonselection_probes", []) \
		and candidate.get("operational_node_pixels", []) == reference.get("operational_node_pixels", []) \
		and candidate.get("counter_pixels", []) == reference.get("counter_pixels", []) \
		and candidate.get("selected_province_id", "") == reference.get("selected_province_id", "") \
		and candidate.get("legal_target_ids", []) == reference.get("legal_target_ids", [])


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
	return {
		"manifest_sha256": FileAccess.get_sha256(MANIFEST),
		"polygon_dataset_sha256": FileAccess.get_sha256(dataset_path),
		"snapshot_sha256": FileAccess.get_sha256(_snapshot_path),
	}


func _midpoint_metrics(a: Dictionary, b: Dictionary) -> Dictionary:
	var out := {}
	for metric_value in ["frame_time_ms", "draw_calls", "primitives", "video_mem_bytes", "script_cpu_ms"]:
		var metric := String(metric_value)
		var av: Dictionary = a.get(metric, {})
		var bv: Dictionary = b.get(metric, {})
		var row := {}
		for stat_value in ["count", "avg", "p50", "p95", "max", "min"]:
			var stat := String(stat_value)
			row[stat] = (float(av.get(stat, 0.0)) + float(bv.get(stat, 0.0))) * 0.5
		out[metric] = row
	return out


func _baseline_drift(a: Dictionary, b: Dictionary) -> Dictionary:
	var a50 := float(a.get("frame_time_ms", {}).get("p50", 0.0))
	var b50 := float(b.get("frame_time_ms", {}).get("p50", 0.0))
	var a95 := float(a.get("frame_time_ms", {}).get("p95", 0.0))
	var b95 := float(b.get("frame_time_ms", {}).get("p95", 0.0))
	return {
		"draw_calls_p50_abs": absi(int(a.get("draw_calls", {}).get("p50", 0)) - int(b.get("draw_calls", {}).get("p50", 0))),
		"primitives_p50_abs": absi(int(a.get("primitives", {}).get("p50", 0)) - int(b.get("primitives", {}).get("p50", 0))),
		"frame_ms_p50_abs": absf(a50 - b50),
		"frame_ms_p95_abs": absf(a95 - b95),
		"frame_ms_p50_ratio": _relative_delta(a50, b50),
		"frame_ms_p95_ratio": _relative_delta(a95, b95),
	}


func _relative_delta(a: float, b: float) -> float:
	return absf(a - b) / maxf((absf(a) + absf(b)) * 0.5, 0.001)


func _improvement_ratio(baseline: float, candidate: float) -> float:
	return (baseline - candidate) / maxf(baseline, 0.001)


func _stats(values: Array) -> Dictionary:
	if values.is_empty():
		return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
	var sorted := values.duplicate()
	sorted.sort()
	var total := 0.0
	for value in sorted:
		total += float(value)
	return {
		"count": sorted.size(),
		"avg": snappedf(total / float(sorted.size()), 0.001),
		"p50": snappedf(_percentile(sorted, 0.50), 0.001),
		"p95": snappedf(_percentile(sorted, 0.95), 0.001),
		"min": snappedf(float(sorted[0]), 0.001),
		"max": snappedf(float(sorted[sorted.size() - 1]), 0.001),
	}


func _stats_int(values: Array) -> Dictionary:
	var stats := _stats(values)
	for key in ["avg", "p50", "p95", "min", "max"]:
		stats[key] = int(round(float(stats[key])))
	return stats


func _percentile(sorted: Array, quantile: float) -> float:
	if sorted.size() == 1:
		return float(sorted[0])
	var position := clampf(quantile, 0.0, 1.0) * float(sorted.size() - 1)
	var low := int(floor(position))
	var high := int(ceil(position))
	if low == high:
		return float(sorted[low])
	var weight := position - float(low)
	return lerpf(float(sorted[low]), float(sorted[high]), weight)


func _write_json(path: String, payload: Dictionary) -> void:
	var base := path.get_base_dir()
	if not base.is_empty():
		DirAccess.make_dir_recursive_absolute(base)
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("unable to open output: %s" % path)
		return
	file.store_string(JSON.stringify(payload, "  "))


func _summary(result: Dictionary) -> Dictionary:
	var out := {"scenarios": {}, "production_switch_authorized": false}
	for scenario_value in SCENARIOS:
		var scenario := String(scenario_value)
		var row: Dictionary = result.get("scenarios", {}).get(scenario, {})
		out["scenarios"][scenario] = row.get("improvement", {})
	return out


func _dispose(scene: Node) -> void:
	if scene != null and is_instance_valid(scene):
		scene.queue_free()
	await process_frame
	await process_frame


func _clear_env() -> void:
	OS.set_environment(HYBRID_ENV, "")
	OS.set_environment(COMPOSED_ENV, "")


func _fail(message: String) -> void:
	push_error("map_candidate_native_acceptance: %s" % message)
	_clear_env()
	quit(1)
