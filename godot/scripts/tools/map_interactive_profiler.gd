extends SceneTree

## Deterministic interactive profiler for Earth3 operational presentation (#74 PR A).
## Drives main.tscn through scripted idle/pan/zoom/selection/overlay scenarios and
## records frame-time percentiles plus discrete operation timings.
##
## Requires a real rendering backend (windowed or xvfb) — not pure dummy headless.
##
## Godot.exe --path godot --audio-driver Dummy -s res://scripts/tools/map_interactive_profiler.gd -- \
##   --out=../docs/godot-presentation/earth3_interactive_baseline.json \
##   --report=../docs/godot-presentation/earth3_interactive_baseline.md \
##   --width=1920 --height=1080 --frames=48

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/e3_operational.json"
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}
const WARMUP_FRAMES := 8
const DEFAULT_SCENARIO_FRAMES := 48

var _out_path := ""
var _report_path := ""
var _snapshot_path := DEFAULT_SNAPSHOT
var _fixture_path := DEFAULT_FIXTURE
var _manifest_path := DEFAULT_MANIFEST
var _width := 1920
var _height := 1080
var _frames := DEFAULT_SCENARIO_FRAMES
var _scene: Node = null
var _build_label := "editor-debug"


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--report="):
			_report_path = text.substr(9).strip_edges()
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
			_frames = maxi(int(text.substr(9)), 16)
		elif text.begins_with("--build="):
			_build_label = text.substr(8).strip_edges()
	if _out_path.is_empty():
		_out_path = "user://earth3_interactive_baseline.json"
	call_deferred("_run")


func _run() -> void:
	print("map_interactive_profiler: start build=%s %sx%s frames=%s" % [_build_label, _width, _height, _frames])
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	if not FileAccess.file_exists(_snapshot_path):
		_fail("snapshot missing: %s" % _snapshot_path)
		return
	if not FileAccess.file_exists(_fixture_path):
		_fail("fixture missing: %s" % _fixture_path)
		return
	if not FileAccess.file_exists(_manifest_path):
		_fail("manifest missing: %s" % _manifest_path)
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
	if not str(_scene.get("load_error") if _scene.get("load_error") != null else "").is_empty():
		_fail("snapshot load_error=%s" % _scene.load_error)
		return
	if _scene.get("map_manifest_source_path") != null:
		_scene.map_manifest_source_path = _manifest_path
	if _scene.has_method("_load_presentation_fixture"):
		_scene.call("_load_presentation_fixture", _fixture_path)
	if _scene.has_method("_open_color_id_map"):
		_scene.call("_open_color_id_map")
	if _scene.get("map_debug") != null:
		_scene.map_debug.enabled = true
		if _scene.has_method("set_process"):
			_scene.set_process(true)
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")

	# Apply fixture selection after map open.
	if _scene.get("presentation_fixture") != null and _scene.presentation_fixture is Dictionary:
		var pf: Dictionary = _scene.presentation_fixture
		var sp := String(pf.get("selected_province_id", ""))
		if not sp.is_empty() and _scene.get("selected_province_id") != null:
			_scene.selected_province_id = sp
			if _scene.has_method("_rebuild_legal_targets"):
				_scene.call("_rebuild_legal_targets")

	_mark_layers_dirty()
	await _pump_frames(WARMUP_FRAMES, Callable())

	var am = _active_map()
	if am == null or not bool(am.is_ready):
		_fail("map backend not ready")
		return
	if not bool(_scene.get("map_backend_is_polygon")):
		_fail("expected polygon backend for Earth3 operational baseline")
		return

	var ids: PackedStringArray = _collect_province_ids(am)
	if ids.is_empty():
		_fail("no province ids for interactive scenarios")
		return
	var selected0 := String(_scene.selected_province_id) if _scene.get("selected_province_id") != null else ""
	if selected0.is_empty():
		selected0 = String(ids[0])
	var selected1 := String(ids[mini(1, ids.size() - 1)])
	if selected1 == selected0 and ids.size() > 2:
		selected1 = String(ids[2])
	var hover_ids: Array = []
	for i in range(mini(12, ids.size())):
		hover_ids.append(String(ids[i]))

	var scenarios: Dictionary = {}
	scenarios["idle_full_theatre"] = await _measure_scenario("idle_full_theatre", _frames, func(i: int) -> void:
		# Steady full-theatre view; only redraw/sync.
		pass
	)
	scenarios["continuous_pan"] = await _measure_scenario("continuous_pan", _frames, func(i: int) -> void:
		if _scene.get("view_offset") == null:
			return
		var t := float(i) / float(maxi(_frames - 1, 1))
		_scene.view_offset = Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0)
	)
	scenarios["continuous_zoom"] = await _measure_scenario("continuous_zoom", _frames, func(i: int) -> void:
		if _scene.get("view_scale") == null:
			return
		var t := float(i) / float(maxi(_frames - 1, 1))
		# Oscillate ~1.0x home to ~4.0x operational zoom.
		_scene.view_scale = lerpf(1.0, 4.0, 0.5 + 0.5 * sin(t * TAU))
		if _scene.get("view_offset") != null:
			_scene.view_offset = Vector2(cos(t * TAU) * 40.0, sin(t * TAU) * 30.0)
	)
	scenarios["province_hover_select"] = await _measure_scenario("province_hover_select", _frames, func(i: int) -> void:
		var hid := String(hover_ids[i % hover_ids.size()])
		if _scene.get("hovered_province_id") != null:
			_scene.hovered_province_id = hid
		if (i % 6) == 0:
			_scene.selected_province_id = hid
			if _scene.has_method("_rebuild_legal_targets"):
				_scene.call("_rebuild_legal_targets")
			if _scene.has_method("_rebuild_focus_set"):
				_scene.call("_rebuild_focus_set")
	)
	scenarios["legal_target_rebuild"] = await _measure_scenario("legal_target_rebuild", _frames, func(i: int) -> void:
		_scene.selected_province_id = selected0 if (i % 2) == 0 else selected1
		if _scene.has_method("_rebuild_legal_targets"):
			_scene.call("_rebuild_legal_targets")
	)
	scenarios["ownership_recolor"] = await _measure_scenario("ownership_recolor", _frames, func(i: int) -> void:
		_flip_one_owner(am, i)
		if am.has_method("refresh_snapshot"):
			am.refresh_snapshot(_scene.snapshot, FACTION_COLORS)
		if _scene.has_method("_invalidate_overlay_cache"):
			_scene.call("_invalidate_overlay_cache")
	)
	scenarios["overlay_routes_sites_counters"] = await _measure_scenario("overlay_routes_sites_counters", _frames, func(i: int) -> void:
		# Force overlay cache invalidation + pan jitter so markers re-layout.
		if _scene.has_method("_invalidate_overlay_cache"):
			_scene.call("_invalidate_overlay_cache")
		if _scene.get("view_offset") != null:
			_scene.view_offset = Vector2(float(i % 7) * 3.0, float(i % 5) * -2.0)
		if _scene.get("hovered_province_id") != null:
			_scene.hovered_province_id = String(hover_ids[i % hover_ids.size()])
	)
	scenarios["pending_battle_presentation"] = await _measure_scenario("pending_battle_presentation", _frames, func(i: int) -> void:
		# Keep pending battle visible; mild zoom around eastern contact.
		if _scene.get("view_scale") != null:
			_scene.view_scale = lerpf(1.6, 2.8, float(i % 10) / 9.0)
		if _scene.get("view_offset") != null:
			_scene.view_offset = Vector2(220.0 + float(i % 8) * 4.0, -40.0 + float(i % 6) * 3.0)
		if _scene.has_method("_invalidate_overlay_cache"):
			_scene.call("_invalidate_overlay_cache")
	)

	# Discrete op timings (CPU only, outside frame loop).
	var op_timings := _measure_discrete_ops(am, selected0, selected1)

	# Restore home framing once for final process snapshot.
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")
	_mark_layers_dirty()
	await _pump_frames(4, Callable())
	var process_snapshot := _sample_performance()

	var result := {
		"ok": true,
		"label": "earth3-interactive-baseline",
		"issue": 74,
		"pr_phase": "A",
		"build": _build_label,
		"timestamp_unix": Time.get_unix_time_from_system(),
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": _video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"scenario_frames": _frames,
		"warmup_frames": WARMUP_FRAMES,
		"snapshot_path": _snapshot_path,
		"fixture_path": _fixture_path,
		"manifest_path": _manifest_path,
		"map": {
			"map_id": "earth3_europe_mediterranean",
			"renderer": "polygon_mesh",
			"province_count": int(am.province_count),
			"mesh_count": int(am.mesh_count),
			"image_width": int(am.image_size().x),
			"image_height": int(am.image_size().y),
			"load_ms": snappedf(float(am.load_ms), 0.01),
			"geometry_immutable": true,
		},
		"authority": {
			"provinces": 3512,
			"land_water": "3297/215",
			"included_ids_sha256": "507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7",
			"production_merge": "7182f8c6002e48f7235ba5ce6b7dd57ee20f4f68",
		},
		"scenarios": scenarios,
		"discrete_ops_ms": op_timings,
		"process_snapshot": process_snapshot,
		"notes": [
			"Frame times are wall-clock ms around force_draw + one process tick (interactive path).",
			"script_cpu_ms uses Performance.TIME_PROCESS; render counters from Performance.RENDER_*.",
			"GPU time is only present when the backend exposes it; otherwise null.",
			"No renderer rewrite in PR A — baseline measurement only.",
			"Do not change Earth3 crop/IDs/adjacency/water geometry.",
		],
	}

	_write_json(_out_path, result)
	if not _report_path.is_empty():
		_write_report(_report_path, result)
	print("map_interactive_profiler: PASS out=%s" % _out_path)
	if not _report_path.is_empty():
		print("map_interactive_profiler: report=%s" % _report_path)
	_cleanup_and_quit(0)


func _measure_scenario(name: String, frames: int, setup: Callable) -> Dictionary:
	var frame_ms: Array = []
	var script_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var nodes: Array = []
	var objects: Array = []
	var tex_mem: Array = []
	var video_mem: Array = []
	var gpu_ms: Array = []

	# Warm a couple frames in the scenario pose.
	for w in range(2):
		if setup.is_valid():
			setup.call(w)
		_mark_layers_dirty()
		await _pump_frames(1, Callable())

	for i in range(frames):
		if setup.is_valid():
			setup.call(i)
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
		var elapsed := (Time.get_ticks_usec() - t0) / 1000.0
		frame_ms.append(elapsed)
		var snap := _sample_performance()
		script_ms.append(float(snap.get("script_cpu_ms", 0.0)))
		draw_calls.append(int(snap.get("draw_calls", 0)))
		primitives.append(int(snap.get("primitives", 0)))
		nodes.append(int(snap.get("node_count", 0)))
		objects.append(int(snap.get("object_count", 0)))
		tex_mem.append(int(snap.get("texture_mem_bytes", 0)))
		video_mem.append(int(snap.get("video_mem_bytes", 0)))
		if snap.get("gpu_ms", null) != null:
			gpu_ms.append(float(snap.get("gpu_ms")))

	print("map_interactive_profiler: scenario=%s avg_ms=%.3f p95=%.3f p99=%.3f" % [
		name,
		_avg(frame_ms),
		_percentile(frame_ms, 0.95),
		_percentile(frame_ms, 0.99),
	])
	return {
		"frames": frames,
		"frame_time_ms": _stats(frame_ms),
		"script_cpu_ms": _stats(script_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"node_count": _stats_int(nodes),
		"object_count": _stats_int(objects),
		"texture_mem_bytes": _stats_int(tex_mem),
		"video_mem_bytes": _stats_int(video_mem),
		"gpu_ms": _stats(gpu_ms) if not gpu_ms.is_empty() else null,
		"rendering_cpu_ms_note": "Godot Performance monadic has no stable RENDER_CPU_ms; wall frame_time_ms includes draw.",
	}


func _measure_discrete_ops(am, selected0: String, selected1: String) -> Dictionary:
	var legal0 := {}
	var legal1 := {}
	if _scene.get("snapshot") != null and _scene.snapshot is Dictionary:
		legal0 = _legal_for(_scene.snapshot, selected0)
		legal1 = _legal_for(_scene.snapshot, selected1)

	var ownership_samples: Array = []
	for i in range(20):
		_flip_one_owner(am, i)
		var t0 := Time.get_ticks_usec()
		am.refresh_snapshot(_scene.snapshot, FACTION_COLORS)
		ownership_samples.append((Time.get_ticks_usec() - t0) / 1000.0)

	var highlight_samples: Array = []
	for i in range(20):
		var use_id := selected0 if (i % 2) == 0 else selected1
		var legal: Dictionary = legal0 if (i % 2) == 0 else legal1
		var t1 := Time.get_ticks_usec()
		am.refresh_highlights(use_id, legal)
		highlight_samples.append((Time.get_ticks_usec() - t1) / 1000.0)

	var legal_rebuild_samples: Array = []
	for i in range(20):
		_scene.selected_province_id = selected0 if (i % 2) == 0 else selected1
		var t2 := Time.get_ticks_usec()
		if _scene.has_method("_rebuild_legal_targets"):
			_scene.call("_rebuild_legal_targets")
		legal_rebuild_samples.append((Time.get_ticks_usec() - t2) / 1000.0)

	var hit_samples: Array = []
	var pick_pos := Vector2(400, 450)
	if am.centroids.size() > 10:
		pick_pos = am.centroids[10]
	for _i in range(100):
		var t3 := Time.get_ticks_usec()
		am.province_at_image_pos(pick_pos)
		hit_samples.append((Time.get_ticks_usec() - t3) / 1000.0)

	var overlay_invalidate_samples: Array = []
	for _i in range(20):
		var t4 := Time.get_ticks_usec()
		if _scene.has_method("_invalidate_overlay_cache"):
			_scene.call("_invalidate_overlay_cache")
		if _scene.has_method("_sync_presentation_layers"):
			_scene.call("_sync_presentation_layers")
		if _scene.has_method("queue_redraw"):
			_scene.queue_redraw()
		overlay_invalidate_samples.append((Time.get_ticks_usec() - t4) / 1000.0)

	return {
		"ownership_refresh_ms": _stats(ownership_samples),
		"highlight_refresh_ms": _stats(highlight_samples),
		"legal_target_rebuild_ms": _stats(legal_rebuild_samples),
		"hit_test_ms": _stats(hit_samples),
		"overlay_invalidate_sync_ms": _stats(overlay_invalidate_samples),
	}


func _flip_one_owner(am, salt: int) -> void:
	if _scene.get("snapshot") == null or not (_scene.snapshot is Dictionary):
		return
	var snap: Dictionary = _scene.snapshot
	var provinces: Array = snap.get("provinces", [])
	if provinces.is_empty():
		return
	var idx := int(absi(salt)) % provinces.size()
	var row: Dictionary = provinces[idx]
	var owner := String(row.get("owner", "neutral"))
	row["owner"] = "nato" if owner != "nato" else "rusa"
	provinces[idx] = row
	snap["provinces"] = provinces
	_scene.snapshot = snap


func _legal_for(snapshot: Dictionary, selected: String) -> Dictionary:
	var legal := {}
	for option: Dictionary in snapshot.get("front_options", []):
		if String(option.get("origin", "")) == selected:
			legal[String(option.get("target", ""))] = option
	return legal


func _collect_province_ids(am) -> PackedStringArray:
	var out := PackedStringArray()
	if am.get("province_by_index") != null and am.province_by_index is PackedStringArray:
		return am.province_by_index
	if am.get("row_by_province") != null and am.row_by_province is Dictionary:
		for k in am.row_by_province.keys():
			out.append(String(k))
			if out.size() >= 64:
				break
	return out


func _active_map():
	if _scene == null:
		return null
	if _scene.has_method("_active_map"):
		return _scene.call("_active_map")
	return _scene.get("polygon_map")


func _mark_layers_dirty() -> void:
	if _scene == null:
		return
	if _scene.get("_layers_dirty") != null:
		_scene._layers_dirty = true


func _pump_frames(count: int, setup: Callable) -> void:
	for i in range(count):
		if setup.is_valid():
			setup.call(i)
		_mark_layers_dirty()
		if _scene != null:
			if _scene.has_method("_sync_presentation_layers"):
				_scene.call("_sync_presentation_layers")
			if _scene.has_method("queue_redraw"):
				_scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _sample_performance() -> Dictionary:
	var gpu_ms = null
	# Best-effort: some builds expose custom monitors; keep null when absent.
	var custom_names: PackedStringArray = Performance.get_custom_monitor_names()
	for n in custom_names:
		var key := String(n).to_lower()
		if key.find("gpu") >= 0 and key.find("time") >= 0:
			gpu_ms = float(Performance.get_custom_monitor(n))
			break
	return {
		"script_cpu_ms": snappedf(float(Performance.get_monitor(Performance.TIME_PROCESS)) * 1000.0, 0.001),
		"fps": snappedf(float(Performance.get_monitor(Performance.TIME_FPS)), 0.01),
		"draw_calls": int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
		"primitives": int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),
		"object_count": int(Performance.get_monitor(Performance.OBJECT_COUNT)),
		"resource_count": int(Performance.get_monitor(Performance.OBJECT_RESOURCE_COUNT)),
		"node_count": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)),
		"texture_mem_bytes": int(Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)),
		"buffer_mem_bytes": int(Performance.get_monitor(Performance.RENDER_BUFFER_MEM_USED)),
		"video_mem_bytes": int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)),
		"static_memory_bytes": int(Performance.get_monitor(Performance.MEMORY_STATIC)),
		"gpu_ms": gpu_ms,
	}


func _video_adapter_name() -> String:
	var info := RenderingServer.get_video_adapter_name()
	if info.is_empty():
		return "unknown"
	return info


func _stats(samples: Array) -> Dictionary:
	if samples.is_empty():
		return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "min": 0.0}
	return {
		"count": samples.size(),
		"avg": snappedf(_avg(samples), 0.001),
		"p50": snappedf(_percentile(samples, 0.50), 0.001),
		"p95": snappedf(_percentile(samples, 0.95), 0.001),
		"p99": snappedf(_percentile(samples, 0.99), 0.001),
		"max": snappedf(_maxv(samples), 0.001),
		"min": snappedf(_minv(samples), 0.001),
	}


func _stats_int(samples: Array) -> Dictionary:
	var s := _stats(samples)
	return {
		"count": int(s.get("count", 0)),
		"avg": snappedf(float(s.get("avg", 0.0)), 0.01),
		"p50": int(round(float(s.get("p50", 0.0)))),
		"p95": int(round(float(s.get("p95", 0.0)))),
		"p99": int(round(float(s.get("p99", 0.0)))),
		"max": int(round(float(s.get("max", 0.0)))),
		"min": int(round(float(s.get("min", 0.0)))),
	}


func _avg(samples: Array) -> float:
	if samples.is_empty():
		return 0.0
	var total := 0.0
	for v in samples:
		total += float(v)
	return total / float(samples.size())


func _minv(samples: Array) -> float:
	var m := float(samples[0])
	for v in samples:
		m = minf(m, float(v))
	return m


func _maxv(samples: Array) -> float:
	var m := float(samples[0])
	for v in samples:
		m = maxf(m, float(v))
	return m


func _percentile(samples: Array, p: float) -> float:
	if samples.is_empty():
		return 0.0
	var sorted: Array = samples.duplicate()
	sorted.sort()
	var idx := int(floor(float(sorted.size() - 1) * clampf(p, 0.0, 1.0)))
	return float(sorted[idx])


func _write_json(path: String, data: Dictionary) -> void:
	var base := path.get_base_dir()
	if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	# user:// paths need globalize for absolute dir creation above when needed.
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("map_interactive_profiler: cannot write %s" % path)
		return
	file.store_string(JSON.stringify(data, "\t"))
	file.close()


func _write_report(path: String, data: Dictionary) -> void:
	var base := path.get_base_dir()
	if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	var map_info: Dictionary = data.get("map", {})
	var auth: Dictionary = data.get("authority", {})
	var scenarios: Dictionary = data.get("scenarios", {})
	var ops: Dictionary = data.get("discrete_ops_ms", {})
	var snap: Dictionary = data.get("process_snapshot", {})
	var lines: PackedStringArray = PackedStringArray()
	lines.append("# Earth3 interactive performance baseline (PR A / #74)")
	lines.append("")
	lines.append("Measurement-only. No renderer rewrite.")
	lines.append("")
	lines.append("## Authority")
	lines.append("")
	lines.append("| Field | Value |")
	lines.append("|---|---|")
	lines.append("| map_id | `earth3_europe_mediterranean` |")
	lines.append("| provinces | %s |" % auth.get("provinces", map_info.get("province_count", "?")))
	lines.append("| land/water | %s |" % auth.get("land_water", "?"))
	lines.append("| included_ids_sha256 | `%s` |" % auth.get("included_ids_sha256", "?"))
	lines.append("| production merge | `%s` |" % auth.get("production_merge", "?"))
	lines.append("| mesh_count | %s |" % map_info.get("mesh_count", "?"))
	lines.append("| image | %sx%s |" % [map_info.get("image_width", "?"), map_info.get("image_height", "?")])
	lines.append("| map open | %s ms |" % map_info.get("load_ms", "?"))
	lines.append("")
	lines.append("## Run")
	lines.append("")
	lines.append("| Field | Value |")
	lines.append("|---|---|")
	lines.append("| build | `%s` |" % data.get("build", "?"))
	lines.append("| OS | %s |" % data.get("os", "?"))
	lines.append("| adapter | %s |" % data.get("video_adapter", "?"))
	lines.append("| viewport | %sx%s |" % [
		data.get("viewport", {}).get("width", "?"),
		data.get("viewport", {}).get("height", "?"),
	])
	lines.append("| scenario frames | %s |" % data.get("scenario_frames", "?"))
	lines.append("| snapshot | `%s` |" % data.get("snapshot_path", "?"))
	lines.append("| fixture | `%s` |" % data.get("fixture_path", "?"))
	lines.append("")
	lines.append("## Scenario frame times (ms)")
	lines.append("")
	lines.append("| Scenario | avg | p50 | p95 | p99 | max | draw_calls p95 | nodes p95 | tex_mem p95 |")
	lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
	var order := [
		"idle_full_theatre",
		"continuous_pan",
		"continuous_zoom",
		"province_hover_select",
		"legal_target_rebuild",
		"ownership_recolor",
		"overlay_routes_sites_counters",
		"pending_battle_presentation",
	]
	for key in order:
		if not scenarios.has(key):
			continue
		var sc: Dictionary = scenarios[key]
		var ft: Dictionary = sc.get("frame_time_ms", {})
		var dc: Dictionary = sc.get("draw_calls", {})
		var nc: Dictionary = sc.get("node_count", {})
		var tm: Dictionary = sc.get("texture_mem_bytes", {})
		lines.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % [
			key,
			ft.get("avg", "?"),
			ft.get("p50", "?"),
			ft.get("p95", "?"),
			ft.get("p99", "?"),
			ft.get("max", "?"),
			dc.get("p95", "?"),
			nc.get("p95", "?"),
			tm.get("p95", "?"),
		])
	lines.append("")
	lines.append("## Discrete operation timings (ms)")
	lines.append("")
	lines.append("| Op | avg | p95 | p99 | max |")
	lines.append("|---|---:|---:|---:|---:|")
	for op_key in [
		"ownership_refresh_ms",
		"highlight_refresh_ms",
		"legal_target_rebuild_ms",
		"hit_test_ms",
		"overlay_invalidate_sync_ms",
	]:
		var st: Dictionary = ops.get(op_key, {})
		lines.append("| `%s` | %s | %s | %s | %s |" % [
			op_key,
			st.get("avg", "?"),
			st.get("p95", "?"),
			st.get("p99", "?"),
			st.get("max", "?"),
		])
	lines.append("")
	lines.append("## Process snapshot (end of run)")
	lines.append("")
	lines.append("| Metric | Value |")
	lines.append("|---|---:|")
	lines.append("| script_cpu_ms | %s |" % snap.get("script_cpu_ms", "?"))
	lines.append("| fps | %s |" % snap.get("fps", "?"))
	lines.append("| draw_calls | %s |" % snap.get("draw_calls", "?"))
	lines.append("| primitives | %s |" % snap.get("primitives", "?"))
	lines.append("| node_count | %s |" % snap.get("node_count", "?"))
	lines.append("| object_count | %s |" % snap.get("object_count", "?"))
	lines.append("| resource_count | %s |" % snap.get("resource_count", "?"))
	lines.append("| texture_mem_bytes | %s |" % snap.get("texture_mem_bytes", "?"))
	lines.append("| video_mem_bytes | %s |" % snap.get("video_mem_bytes", "?"))
	lines.append("| buffer_mem_bytes | %s |" % snap.get("buffer_mem_bytes", "?"))
	lines.append("| static_memory_bytes | %s |" % snap.get("static_memory_bytes", "?"))
	lines.append("| gpu_ms | %s |" % snap.get("gpu_ms", "null"))
	lines.append("")
	lines.append("## Notes")
	lines.append("")
	for note in data.get("notes", []):
		lines.append("- %s" % String(note))
	lines.append("")
	lines.append("## Release export")
	lines.append("")
	lines.append("Release-export capture is optional in PR A when export templates are unavailable on the runner.")
	lines.append("Windows editor-debug results above are the committed authority baseline.")
	lines.append("")
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("map_interactive_profiler: cannot write report %s" % path)
		return
	file.store_string("\n".join(lines))
	file.close()


func _cleanup_and_quit(code: int) -> void:
	if _scene != null and is_instance_valid(_scene):
		var parent := _scene.get_parent()
		if parent != null:
			parent.remove_child(_scene)
		_scene.free()
	_scene = null
	quit(code)


func _fail(reason: String) -> void:
	push_error("map_interactive_profiler FAIL: %s" % reason)
	print("map_interactive_profiler: FAIL %s" % reason)
	_cleanup_and_quit(1)
