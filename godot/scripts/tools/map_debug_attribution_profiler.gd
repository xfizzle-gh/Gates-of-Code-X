extends SceneTree

## #212 Phase A measurement checkpoint.
##
## The accepted #74 interactive profiler intentionally enables MapDebug before
## sampling. MapDebug draws one anchor circle for every loaded province, so its
## ~3.7k draw-call result cannot be treated as an ordinary-player baseline.
## This harness measures the exact same Earth3 camera with debug OFF, debug ON,
## and debug OFF again while proving province picking/authority is unchanged.

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/e3_operational.json"
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const WARMUP_FRAMES := 6
const DEFAULT_FRAMES := 24

var _out_path := "user://issue_212_debug_attribution.json"
var _snapshot_path := DEFAULT_SNAPSHOT
var _fixture_path := DEFAULT_FIXTURE
var _manifest_path := DEFAULT_MANIFEST
var _width := 1920
var _height := 1080
var _frames := DEFAULT_FRAMES
var _scene: Node = null


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

	var packed := load("res://main.tscn")
	if packed == null:
		_fail("failed to load main.tscn")
		return
	_scene = packed.instantiate()
	if _scene == null:
		_fail("failed to instantiate main.tscn")
		return
	root.add_child(_scene)

	if _scene.get("snapshot_source_path") != null:
		_scene.snapshot_source_path = _snapshot_path
	if _scene.has_method("_load_snapshot"):
		_scene.call("_load_snapshot", _snapshot_path)
	var load_error := str(_scene.get("load_error") if _scene.get("load_error") != null else "")
	if not load_error.is_empty():
		_fail("snapshot load_error=%s" % load_error)
		return
	if _scene.get("map_manifest_source_path") != null:
		_scene.map_manifest_source_path = _manifest_path
	if _scene.has_method("_load_presentation_fixture"):
		_scene.call("_load_presentation_fixture", _fixture_path)
	if _scene.has_method("_open_color_id_map"):
		_scene.call("_open_color_id_map")
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")
	if _scene.has_method("set_process"):
		_scene.set_process(true)

	_set_debug(false)
	await _pump_frames(WARMUP_FRAMES)
	var active_map = _active_map()
	if active_map == null or not bool(active_map.is_ready):
		_fail("Earth3 map backend not ready")
		return
	if not bool(_scene.get("map_backend_is_polygon")):
		_fail("expected Earth3 polygon backend")
		return
	if int(active_map.province_count) != 3514:
		_fail("Earth3 authority changed: province_count=%s" % int(active_map.province_count))
		return

	var picks_before := _pick_suite(active_map)
	var debug_off := await _measure_mode("debug_off")

	_set_debug(true)
	var picks_debug_on := _pick_suite(active_map)
	var debug_on := await _measure_mode("debug_on")

	_set_debug(false)
	var picks_restored := _pick_suite(active_map)
	var debug_off_restored := await _measure_mode("debug_off_restored")

	var picking_parity := picks_before == picks_debug_on and picks_before == picks_restored
	var result := {
		"ok": picking_parity,
		"schema": "gates-of-codex.issue-212-map-debug-attribution",
		"schema_version": 1,
		"issue": 212,
		"viewport": {"width": _width, "height": _height},
		"frames": _frames,
		"map": {
			"map_id": "earth3_europe_mediterranean",
			"renderer": "polygon_mesh",
			"province_count": int(active_map.province_count),
			"debug_anchor_count": int(active_map.row_by_province.size()),
		},
		"picking": {
			"parity": picking_parity,
			"before": picks_before,
			"debug_on": picks_debug_on,
			"restored": picks_restored,
		},
		"modes": {
			"debug_off": debug_off,
			"debug_on": debug_on,
			"debug_off_restored": debug_off_restored,
		},
		"attribution": {
			"debug_draw_calls_p50_delta": int(debug_on.draw_calls.p50) - int(debug_off.draw_calls.p50),
			"debug_draw_calls_p95_delta": int(debug_on.draw_calls.p95) - int(debug_off.draw_calls.p95),
			"debug_frame_ms_p50_delta": snappedf(float(debug_on.frame_time_ms.p50) - float(debug_off.frame_time_ms.p50), 0.001),
			"debug_frame_ms_p95_delta": snappedf(float(debug_on.frame_time_ms.p95) - float(debug_off.frame_time_ms.p95), 0.001),
		},
		"notes": [
			"Ordinary player presentation keeps MapDebug disabled.",
			"The previous #74 baseline enables MapDebug before sampling.",
			"MapDebug draws one anchor circle per loaded province when show_anchors is true.",
			"This checkpoint corrects baseline attribution only; it does not change production rendering or Earth3 authority.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_ATTRIBUTION %s" % JSON.stringify(result))
	if not picking_parity:
		_fail("debug toggle changed deterministic picking")
		return
	print("map_debug_attribution_profiler: PASS out=%s" % _out_path)
	_cleanup_and_quit(0)


func _set_debug(enabled: bool) -> void:
	var debug = _scene.get("map_debug") if _scene != null else null
	if debug != null:
		debug.enabled = enabled
	_mark_layers_dirty()
	if _scene != null and _scene.has_method("queue_redraw"):
		_scene.queue_redraw()


func _measure_mode(name: String) -> Dictionary:
	await _pump_frames(4)
	var frame_ms: Array = []
	var script_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var nodes: Array = []
	var objects: Array = []
	var texture_mem: Array = []
	var video_mem: Array = []
	for _i in range(_frames):
		_mark_layers_dirty()
		var t0 := Time.get_ticks_usec()
		if _scene.has_method("_sync_presentation_layers"):
			_scene.call("_sync_presentation_layers")
		if _scene.has_method("queue_redraw"):
			_scene.queue_redraw()
		if _scene.has_method("_process"):
			_scene.call("_process", 0.016)
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
	print("map_debug_attribution_profiler: mode=%s draw_p50=%s frame_p95=%s" % [
		name,
		measured.draw_calls.p50,
		measured.frame_time_ms.p95,
	])
	return measured


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


func _active_map():
	if _scene == null:
		return null
	if _scene.has_method("_active_map"):
		return _scene.call("_active_map")
	return _scene.get("polygon_map")


func _mark_layers_dirty() -> void:
	if _scene != null and _scene.get("_layers_dirty") != null:
		_scene._layers_dirty = true


func _pump_frames(count: int) -> void:
	for _i in range(count):
		_mark_layers_dirty()
		if _scene != null:
			if _scene.has_method("_sync_presentation_layers"):
				_scene.call("_sync_presentation_layers")
			if _scene.has_method("queue_redraw"):
				_scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
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
		push_error("map_debug_attribution_profiler: cannot write %s" % path)
		return
	file.store_string(JSON.stringify(data, "\t"))
	file.close()


func _fail(message: String) -> void:
	push_error("map_debug_attribution_profiler: %s" % message)
	_cleanup_and_quit(2)


func _cleanup_and_quit(code: int) -> void:
	if _scene != null and is_instance_valid(_scene):
		_scene.queue_free()
	await process_frame
	quit(code)
