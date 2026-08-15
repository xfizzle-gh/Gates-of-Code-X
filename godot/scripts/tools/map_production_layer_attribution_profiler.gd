extends SceneTree

## #212 Phase A, checkpoint 2.
##
## Attribute the corrected ordinary-player Earth3 baseline by disabling one
## production-visible presentation category at a time. Every mode gets a fresh
## main scene, so measurement mutations never leak into another sample and no
## production renderer / authority code needs instrumentation hooks.

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/e3_operational.json"
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const WARMUP_FRAMES := 6
const DEFAULT_FRAMES := 24
const MODES := [
	"baseline",
	"land_fill",
	"ocean_mesh",
	"shared_borders",
	"secondary_outlines",
	"labels",
	"formation_counters",
	"infrastructure_sites",
	"routes",
	"contact_battle",
	"fixture_debug_overlays",
	"ui_only_floor",
]

var _out_path := "user://issue_212_production_layer_attribution.json"
var _snapshot_path := DEFAULT_SNAPSHOT
var _fixture_path := DEFAULT_FIXTURE
var _manifest_path := DEFAULT_MANIFEST
var _width := 1920
var _height := 1080
var _frames := DEFAULT_FRAMES


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
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
			_frames = maxi(int(text.substr(9)), 12)
	call_deferred("_run")


func _run() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for required_path in [_snapshot_path, _fixture_path, _manifest_path]:
		if not FileAccess.file_exists(String(required_path)):
			_fail("required fixture missing: %s" % String(required_path))
			return

	var mode_results: Dictionary = {}
	var baseline_picks: Array = []
	var node_inventory: Dictionary = {}
	for mode_variant in MODES:
		var mode := String(mode_variant)
		var measured := await _measure_fresh_mode(mode)
		if not bool(measured.get("ok", false)):
			_fail("mode failed: %s detail=%s" % [mode, measured.get("error", "unknown")])
			return
		if mode == "baseline":
			baseline_picks = measured.get("picking", [])
			node_inventory = measured.get("map_nodes", {})
		else:
			if measured.get("picking", []) != baseline_picks:
				_fail("mode changed deterministic picking: %s" % mode)
				return
		mode_results[mode] = measured.get("metrics", {})

	var baseline: Dictionary = mode_results.get("baseline", {})
	var deltas: Dictionary = {}
	for mode_variant in MODES:
		var mode := String(mode_variant)
		if mode == "baseline" or mode == "ui_only_floor":
			continue
		var row: Dictionary = mode_results.get(mode, {})
		deltas[mode] = _delta_from_baseline(baseline, row)

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-production-layer-attribution",
		"schema_version": 1,
		"issue": 212,
		"viewport": {"width": _width, "height": _height},
		"frames": _frames,
		"map": {
			"map_id": "earth3_europe_mediterranean",
			"renderer": "polygon_mesh",
			"province_count": 3514,
			"nodes": node_inventory,
		},
		"picking": {
			"parity": true,
			"baseline": baseline_picks,
		},
		"modes": mode_results,
		"disabled_layer_deltas": deltas,
		"notes": [
			"All modes run with MapDebug disabled.",
			"Every disabled-layer sample uses a fresh main scene and the same camera/fixtures.",
			"Deltas are baseline minus disabled-layer measurements; positive draw-call deltas indicate calls attributable to that category in this fixture.",
			"Categories are presentation probes, not additive accounting buckets; some fixture content intentionally overlaps semantic layers.",
			"ui_only_floor is a residual floor with all measured map presentation categories suppressed; it is not a one-layer delta.",
			"Absolute CI frame times are llvmpipe measurements and are not owner-native acceptance metrics.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_PRODUCTION_ATTRIBUTION %s" % JSON.stringify(result))
	print("map_production_layer_attribution_profiler: PASS out=%s" % _out_path)
	quit(0)


func _measure_fresh_mode(mode: String) -> Dictionary:
	var scene_result := await _build_scene()
	if not bool(scene_result.get("ok", false)):
		return scene_result
	var scene: Node = scene_result.get("scene")
	var active_map = _active_map(scene)
	if active_map == null or not bool(active_map.is_ready):
		await _dispose_scene(scene)
		return {"ok": false, "error": "Earth3 map backend not ready"}
	if not bool(scene.get("map_backend_is_polygon")):
		await _dispose_scene(scene)
		return {"ok": false, "error": "expected Earth3 polygon backend"}
	if int(active_map.province_count) != 3514:
		await _dispose_scene(scene)
		return {"ok": false, "error": "Earth3 authority changed: province_count=%s" % int(active_map.province_count)}

	await _prime_overlay_cache(scene)
	_apply_mode(scene, mode)
	await _pump_frames(scene, WARMUP_FRAMES)
	var picks := _pick_suite(active_map)
	for row_variant in picks:
		var row: Dictionary = row_variant
		if not bool(row.get("match", false)):
			await _dispose_scene(scene)
			return {"ok": false, "error": "picking mismatch in %s: %s" % [mode, row]}

	var inventory := _map_node_inventory(scene)
	var metrics := await _measure(scene, mode)
	await _dispose_scene(scene)
	return {
		"ok": true,
		"picking": picks,
		"metrics": metrics,
		"map_nodes": inventory,
	}


func _build_scene() -> Dictionary:
	var packed := load("res://main.tscn")
	if packed == null:
		return {"ok": false, "error": "failed to load main.tscn"}
	var scene: Node = packed.instantiate()
	if scene == null:
		return {"ok": false, "error": "failed to instantiate main.tscn"}
	root.add_child(scene)

	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = _snapshot_path
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", _snapshot_path)
	var load_error := str(scene.get("load_error") if scene.get("load_error") != null else "")
	if not load_error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": "snapshot load_error=%s" % load_error}
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = _manifest_path
	if scene.has_method("_load_presentation_fixture"):
		scene.call("_load_presentation_fixture", _fixture_path)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	var debug = scene.get("map_debug")
	if debug != null:
		debug.enabled = false
	if scene.has_method("set_process"):
		scene.set_process(true)
	await _pump_frames(scene, WARMUP_FRAMES)
	return {"ok": true, "scene": scene}


func _apply_mode(scene: Node, mode: String) -> void:
	match mode:
		"baseline":
			pass
		"land_fill":
			_set_polygon_children_visible(scene, "Earth3Chunk_", false)
		"ocean_mesh":
			_set_named_child_visible(scene, "Earth3Ocean", false)
		"shared_borders":
			_set_named_child_visible(scene, "Earth3Borders", false)
		"secondary_outlines":
			_clear_fixture_keys(scene, ["federal_subject_outlines", "europe_asia_boundary_pixels"])
		"labels":
			_clear_fixture_keys(scene, ["proof_labels"])
			_suppress_dynamic_labels(scene)
		"formation_counters":
			_clear_dict_property(scene, "battalions_by_province")
			_clear_dict_property(scene, "battalion_stacks_by_province")
			_clear_fixture_keys(scene, ["synthetic_counters", "force_stack_badges"])
		"infrastructure_sites":
			_zero_snapshot_infrastructure(scene)
			_clear_fixture_keys(scene, ["control_sites"])
		"routes":
			_clear_fixture_keys(scene, ["routes"])
			if scene.get("selected_strategic_formation_id") != null:
				scene.selected_strategic_formation_id = ""
		"contact_battle":
			_remove_pending_battle(scene)
			_clear_fixture_keys(scene, ["battles", "contacts"])
		"fixture_debug_overlays":
			_clear_fixture_keys(scene, ["proof_labels", "federal_subject_outlines", "europe_asia_boundary_pixels"])
		"ui_only_floor":
			_set_polygon_children_visible(scene, "Earth3Chunk_", false)
			_set_named_child_visible(scene, "Earth3Ocean", false)
			_set_named_child_visible(scene, "Earth3Borders", false)
			_clear_dict_property(scene, "battalions_by_province")
			_clear_dict_property(scene, "battalion_stacks_by_province")
			_zero_snapshot_infrastructure(scene)
			_remove_pending_battle(scene)
			_clear_fixture_keys(scene, [
				"routes",
				"battles",
				"contacts",
				"control_sites",
				"synthetic_counters",
				"force_stack_badges",
				"proof_labels",
				"federal_subject_outlines",
				"europe_asia_boundary_pixels",
			])
			_suppress_dynamic_labels(scene)
			if scene.get("selected_strategic_formation_id") != null:
				scene.selected_strategic_formation_id = ""
		_:
			push_error("unknown attribution mode: %s" % mode)
	_mark_layers_dirty(scene)
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()


func _set_polygon_children_visible(scene: Node, prefix: String, visible: bool) -> void:
	var holder := scene.get_node_or_null("Earth3PolygonRoot")
	if holder == null:
		return
	for child in holder.get_children():
		if String(child.name).begins_with(prefix) and child is CanvasItem:
			(child as CanvasItem).visible = visible


func _set_named_child_visible(scene: Node, child_name: String, visible: bool) -> void:
	var holder := scene.get_node_or_null("Earth3PolygonRoot")
	if holder == null:
		return
	var child := holder.get_node_or_null(child_name)
	if child != null and child is CanvasItem:
		(child as CanvasItem).visible = visible


func _clear_fixture_keys(scene: Node, keys: Array) -> void:
	var fixture_value: Variant = scene.get("presentation_fixture")
	if not fixture_value is Dictionary:
		return
	var fixture := fixture_value as Dictionary
	for key_variant in keys:
		fixture[String(key_variant)] = []


func _clear_dict_property(scene: Node, property_name: String) -> void:
	var value: Variant = scene.get(property_name)
	if value is Dictionary:
		(value as Dictionary).clear()


func _zero_snapshot_infrastructure(scene: Node) -> void:
	var snapshot_value: Variant = scene.get("snapshot")
	if not snapshot_value is Dictionary:
		return
	var snapshot: Dictionary = snapshot_value
	for row_variant in snapshot.get("provinces", []):
		if not row_variant is Dictionary:
			continue
		var row := row_variant as Dictionary
		row["infrastructure"] = {}
	if scene.get("_snap_by_id_src") != null:
		scene._snap_by_id_src = null
	if scene.has_method("_ensure_snapshot_overlay_indexes"):
		scene.call("_ensure_snapshot_overlay_indexes")


func _remove_pending_battle(scene: Node) -> void:
	var snapshot_value: Variant = scene.get("snapshot")
	if snapshot_value is Dictionary:
		(snapshot_value as Dictionary).erase("pending_battle")


func _prime_overlay_cache(scene: Node) -> void:
	_mark_layers_dirty(scene)
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()
	RenderingServer.force_draw(false, 0.0)
	await process_frame
	await process_frame


func _suppress_dynamic_labels(scene: Node) -> void:
	# Preserve the current overlay cache key but remove accepted label candidates.
	# With camera/selection held constant, the production overlay path then treats
	# the cache as current and draws counters/sites without rebuilding labels.
	var candidates: Variant = scene.get("_cached_label_candidates")
	if candidates is Array:
		(candidates as Array).clear()
	var bounds: Variant = scene.get("_cached_label_bounds")
	if bounds is Array:
		(bounds as Array).clear()
	if scene.get("hovered_province_id") != null:
		scene.hovered_province_id = ""


func _map_node_inventory(scene: Node) -> Dictionary:
	var holder := scene.get_node_or_null("Earth3PolygonRoot")
	var chunks := 0
	var ocean := 0
	var borders := 0
	if holder != null:
		for child in holder.get_children():
			var name := String(child.name)
			if name.begins_with("Earth3Chunk_"):
				chunks += 1
			elif name == "Earth3Ocean":
				ocean += 1
			elif name == "Earth3Borders":
				borders += 1
	return {
		"land_chunk_canvas_items": chunks,
		"ocean_canvas_items": ocean,
		"border_canvas_items": borders,
		"total_scene_nodes": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)),
	}


func _measure(scene: Node, mode: String) -> Dictionary:
	await _pump_frames(scene, 4)
	var frame_ms: Array = []
	var script_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var nodes: Array = []
	var objects: Array = []
	var texture_mem: Array = []
	var video_mem: Array = []
	for _i in range(_frames):
		_mark_layers_dirty(scene)
		var t0 := Time.get_ticks_usec()
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		if scene.has_method("_process"):
			scene.call("_process", 0.016)
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		frame_ms.append((Time.get_ticks_usec() - t0) / 1000.0)
		script_ms.append(float(Performance.get_monitor(Performance.TIME_PROCESS)) * 1000.0)
		draw_calls.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)))
		primitives.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)))
		nodes.append(int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)))
		objects.append(int(Performance.get_monitor(Performance.OBJECT_COUNT)))
		texture_mem.append(int(Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)))
		video_mem.append(int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)))
	var measured := {
		"frame_time_ms": _stats(frame_ms),
		"script_cpu_ms": _stats(script_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"node_count": _stats_int(nodes),
		"object_count": _stats_int(objects),
		"texture_mem_bytes": _stats_int(texture_mem),
		"video_mem_bytes": _stats_int(video_mem),
	}
	print("map_production_layer_attribution_profiler: mode=%s draw_p50=%s frame_p95=%s" % [
		mode,
		measured.draw_calls.p50,
		measured.frame_time_ms.p95,
	])
	return measured


func _delta_from_baseline(baseline: Dictionary, disabled: Dictionary) -> Dictionary:
	return {
		"draw_calls_p50": int(baseline.get("draw_calls", {}).get("p50", 0)) - int(disabled.get("draw_calls", {}).get("p50", 0)),
		"draw_calls_p95": int(baseline.get("draw_calls", {}).get("p95", 0)) - int(disabled.get("draw_calls", {}).get("p95", 0)),
		"primitives_p50": int(baseline.get("primitives", {}).get("p50", 0)) - int(disabled.get("primitives", {}).get("p50", 0)),
		"frame_ms_p50": snappedf(float(baseline.get("frame_time_ms", {}).get("p50", 0.0)) - float(disabled.get("frame_time_ms", {}).get("p50", 0.0)), 0.001),
		"frame_ms_p95": snappedf(float(baseline.get("frame_time_ms", {}).get("p95", 0.0)) - float(disabled.get("frame_time_ms", {}).get("p95", 0.0)), 0.001),
		"script_cpu_ms_p50": snappedf(float(baseline.get("script_cpu_ms", {}).get("p50", 0.0)) - float(disabled.get("script_cpu_ms", {}).get("p50", 0.0)), 0.001),
		"video_mem_bytes_p50": int(baseline.get("video_mem_bytes", {}).get("p50", 0)) - int(disabled.get("video_mem_bytes", {}).get("p50", 0)),
	}


func _pick_suite(active_map) -> Array:
	var out: Array = []
	var requested := [0, 503, 1009, 2017, 3001]
	for raw_index in requested:
		var index := mini(int(raw_index), int(active_map.province_count) - 1)
		while index < int(active_map.province_count) and int(active_map.is_water[index]) == 1:
			index += 1
		if index >= int(active_map.province_count):
			continue
		var province_id := String(active_map.province_by_index[index])
		var point: Vector2 = active_map.anchor_pixel(province_id)
		var picked := String(active_map.province_at_image_pos(point))
		out.append({
			"index": index,
			"expected": province_id,
			"picked": picked,
			"match": province_id == picked,
		})
	return out


func _active_map(scene: Node):
	if scene.has_method("_active_map"):
		return scene.call("_active_map")
	return scene.get("polygon_map")


func _mark_layers_dirty(scene: Node) -> void:
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true


func _pump_frames(scene: Node, count: int) -> void:
	for _i in range(count):
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _dispose_scene(scene: Node) -> void:
	if scene != null and is_instance_valid(scene):
		scene.queue_free()
	await process_frame
	await process_frame


func _stats(samples: Array) -> Dictionary:
	if samples.is_empty():
		return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0}
	return {
		"count": samples.size(),
		"avg": snappedf(_avg(samples), 0.001),
		"p50": snappedf(_percentile(samples, 0.50), 0.001),
		"p95": snappedf(_percentile(samples, 0.95), 0.001),
		"max": snappedf(_maxv(samples), 0.001),
		"min": snappedf(_minv(samples), 0.001),
	}


func _stats_int(samples: Array) -> Dictionary:
	var values := _stats(samples)
	return {
		"count": int(values.count),
		"avg": snappedf(float(values.avg), 0.01),
		"p50": int(round(float(values.p50))),
		"p95": int(round(float(values.p95))),
		"max": int(round(float(values.max))),
		"min": int(round(float(values.min))),
	}


func _avg(samples: Array) -> float:
	var total := 0.0
	for value in samples:
		total += float(value)
	return total / float(maxi(samples.size(), 1))


func _percentile(samples: Array, p: float) -> float:
	var ordered: Array = samples.duplicate()
	ordered.sort()
	var index := int(floor(float(ordered.size() - 1) * clampf(p, 0.0, 1.0)))
	return float(ordered[index])


func _maxv(samples: Array) -> float:
	var result := float(samples[0])
	for value in samples:
		result = maxf(result, float(value))
	return result


func _minv(samples: Array) -> float:
	var result := float(samples[0])
	for value in samples:
		result = minf(result, float(value))
	return result


func _write_json(path: String, data: Dictionary) -> void:
	var base := path.get_base_dir()
	if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("map_production_layer_attribution_profiler: cannot write %s" % path)
		return
	file.store_string(JSON.stringify(data, "\t"))
	file.close()


func _fail(message: String) -> void:
	push_error("map_production_layer_attribution_profiler: %s" % message)
	quit(2)
