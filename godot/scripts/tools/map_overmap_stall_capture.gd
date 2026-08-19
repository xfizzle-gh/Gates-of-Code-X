extends SceneTree

## Capture spikes on a real production snapshot. Read-only by default.
## Does not write the owner campaign or its snapshot.

const FIXTURE_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const FIXTURE_PRESENTATION := "res://fixtures/presentation/e3_operational.json"
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const WARMUP := 6
const FRAMES := 24

var _out_path := "user://overmap-stall-capture.json"
var _snapshot_path := ""
var _campaign_path := ""
var _manifest_path := DEFAULT_MANIFEST
var _label := "owner"
var _width := 1920
var _height := 1080
var _scene: Node = null
var _disable_vsync := true


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--campaign="):
			_campaign_path = text.substr(11).strip_edges()
		elif text.begins_with("--manifest="):
			_manifest_path = text.substr(11).strip_edges()
		elif text.begins_with("--label="):
			_label = text.substr(8).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
		elif text == "--vsync":
			_disable_vsync = false
	call_deferred("_run")


func _run() -> void:
	if _disable_vsync and DisplayServer.has_method("window_set_vsync_mode"):
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	if _snapshot_path.is_empty():
		_fail("missing --snapshot=")
		return
	var owner_block := await _capture_one(_snapshot_path, _campaign_path, _label)
	var fixture_block := await _capture_one(FIXTURE_SNAPSHOT, "", "fixture")
	var payload := {
		"schema": "gates-of-codex.overmap-stall-capture",
		"schema_version": 1,
		"read_only": true,
		"vsync_disabled": _disable_vsync,
		"viewport": {"width": _width, "height": _height, "frames": FRAMES},
		"owner": owner_block,
		"fixture": fixture_block,
		"comparison": _compare(owner_block, fixture_block),
	}
	_write_json(_out_path, payload)
	print("overmap_stall_capture: PASS")
	print(JSON.stringify(payload.get("comparison", {}), "\t"))
	quit(0)


func _capture_one(snapshot_path: String, campaign_path: String, label: String) -> Dictionary:
	var io := _time_io(snapshot_path, campaign_path)
	var packed := load("res://main.tscn")
	if packed == null:
		return {"label": label, "ok": false, "error": "failed to load main.tscn", "io": io}
	if _scene != null:
		_scene.queue_free()
		_scene = null
		await process_frame
		await process_frame
	_scene = packed.instantiate()
	if _scene == null:
		return {"label": label, "ok": false, "error": "failed to instantiate main.tscn", "io": io}
	if not _scene.has_method("_load_snapshot"):
		return {"label": label, "ok": false, "error": "main.tscn script did not attach", "io": io}
	root.add_child(_scene)
	if _scene.get("map_debug") != null:
		_scene.map_debug.enabled = false
	if _scene.get("map_manifest_source_path") != null:
		_scene.map_manifest_source_path = _manifest_path
	var t_load := Time.get_ticks_usec()
	if _scene.has_method("_load_snapshot"):
		_scene.call("_load_snapshot", snapshot_path)
	if _scene.has_method("_open_color_id_map"):
		_scene.call("_open_color_id_map")
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")
	var load_ms := (Time.get_ticks_usec() - t_load) / 1000.0
	var load_error := str(_scene.get("load_error") if _scene.get("load_error") != null else "")
	for _i in range(WARMUP):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var counts := _snapshot_counts()
	var idle := await _sample_frames("idle", func(_i: int) -> void: pass)
	var hover := await _sample_input("hover", func() -> void:
		var pid := _nth_province(3)
		if _scene.get("hovered_province_id") != null:
			_scene.set("hovered_province_id", pid)
	)
	var province_select := await _sample_input("province_select", func() -> void:
		var pid := _nth_province(8)
		if pid.is_empty():
			return
		_scene.set("selected_province_id", pid)
		if _scene.has_method("_rebuild_legal_targets"):
			_scene.call("_rebuild_legal_targets")
		if _scene.has_method("_rebuild_focus_set"):
			_scene.call("_rebuild_focus_set")
	)
	var formation_select := await _sample_input("formation_select", func() -> void:
		var fid := _first_formation_id()
		if fid.is_empty():
			return
		if _scene.get("selected_strategic_formation_id") != null:
			_scene.set("selected_strategic_formation_id", fid)
		if _scene.has_method("_rebuild_legal_targets"):
			_scene.call("_rebuild_legal_targets")
	)
	var begin_pan := await _sample_input("begin_pan", func() -> void:
		_scene.set("view_offset", Vector2(80, -40))
	)
	var pan := await _sample_frames("continuous_pan", func(i: int) -> void:
		var t := float(i) / float(maxi(FRAMES - 1, 1))
		_scene.set("view_offset", Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0))
	)
	var end_pan := await _sample_frames("end_pan", func(_i: int) -> void:
		_scene.set("view_offset", Vector2(80, -40))
	)
	var zoom := await _sample_frames("continuous_zoom", func(i: int) -> void:
		var t := float(i) / float(maxi(FRAMES - 1, 1))
		_scene.set("view_scale", 0.7 + t * 2.0)
	)
	var lod := {}
	for threshold in [0.95, 1.05, 1.15, 2.4]:
		lod["cross_%s" % str(threshold)] = await _sample_input("lod_%s" % str(threshold), func() -> void:
			_scene.set("view_scale", float(threshold) + 0.02)
		)
	var panel := await _sample_input("toggle_management_ui", func() -> void:
		if _scene.get("stack_panel_expanded") != null:
			_scene.set("stack_panel_expanded", not bool(_scene.stack_panel_expanded))
	)
	return {
		"label": label,
		"ok": load_error.is_empty(),
		"error": load_error,
		"snapshot_path": snapshot_path,
		"campaign_path": campaign_path,
		"io": io,
		"scene_load_ms": load_ms,
		"counts": counts,
		"scenarios": {
			"idle": idle,
			"hover": hover,
			"province_select": province_select,
			"formation_select": formation_select,
			"begin_pan": begin_pan,
			"continuous_pan": pan,
			"end_pan": end_pan,
			"continuous_zoom": zoom,
			"lod_crossings": lod,
			"toggle_management_ui": panel,
		},
	}


func _time_io(snapshot_path: String, campaign_path: String) -> Dictionary:
	var result := {
		"snapshot": _time_file(snapshot_path),
		"campaign": _time_file(campaign_path) if not campaign_path.is_empty() else {},
		"fixture": _time_file(ProjectSettings.globalize_path(FIXTURE_SNAPSHOT)),
	}
	return result


func _time_file(path: String) -> Dictionary:
	if path.is_empty() or not FileAccess.file_exists(path):
		return {"exists": false, "path": path}
	var t0 := Time.get_ticks_usec()
	var file := FileAccess.open(path, FileAccess.READ)
	var text := file.get_as_text() if file != null else ""
	var read_ms := (Time.get_ticks_usec() - t0) / 1000.0
	var t1 := Time.get_ticks_usec()
	var parsed: Variant = JSON.parse_string(text)
	var parse_ms := (Time.get_ticks_usec() - t1) / 1000.0
	var keys := 0
	if parsed is Dictionary:
		keys = (parsed as Dictionary).size()
	return {
		"exists": true,
		"path": path,
		"bytes": text.length(),
		"read_ms": read_ms,
		"parse_ms": parse_ms,
		"json_ok": parsed != null,
		"top_keys": keys,
	}


func _snapshot_counts() -> Dictionary:
	if _scene == null:
		return {}
	var snap: Dictionary = _scene.snapshot if _scene.get("snapshot") != null else {}
	var provinces: Array = snap.get("provinces", [])
	var battalions: Array = snap.get("battalions", [])
	var formations: Array = snap.get("strategic_formations", snap.get("formations", []))
	var routes: Array = snap.get("operational_orders", [])
	var sites := 0
	for province: Dictionary in provinces:
		var infra: Dictionary = province.get("infrastructure", {})
		if int(infra.get("supply_hub", 0)) > 0 or int(infra.get("command_post", 0)) > 0 or int(infra.get("air_base", 0)) > 0:
			sites += 1
	return {
		"provinces": provinces.size(),
		"battalions": battalions.size(),
		"formations": formations.size(),
		"routes": routes.size(),
		"sites": sites,
		"pending_battle": snap.get("pending_battle") != null,
		"schema": String(snap.get("schema", "")),
	}


func _nth_province(index: int) -> String:
	if _scene == null:
		return ""
	var snap: Dictionary = _scene.snapshot if _scene.get("snapshot") != null else {}
	var provinces: Array = snap.get("provinces", [])
	if provinces.is_empty():
		return ""
	var row: Dictionary = provinces[clampi(index, 0, provinces.size() - 1)]
	return String(row.get("id", ""))


func _first_formation_id() -> String:
	if _scene == null:
		return ""
	var snap: Dictionary = _scene.snapshot if _scene.get("snapshot") != null else {}
	var formations: Array = snap.get("strategic_formations", snap.get("formations", []))
	if formations.is_empty():
		return ""
	return String((formations[0] as Dictionary).get("id", ""))


func _sample_frames(name: String, mutate: Callable) -> Dictionary:
	var times: Array = []
	var scripts: Array = []
	var draws: Array = []
	for i in range(FRAMES):
		mutate.call(i)
		if _scene.has_method("queue_redraw"):
			_scene.queue_redraw()
		var t0 := Time.get_ticks_usec()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		times.append((Time.get_ticks_usec() - t0) / 1000.0)
		scripts.append(Performance.get_monitor(Performance.TIME_PROCESS) * 1000.0)
		draws.append(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
	return _summarize(name, times, scripts, draws, 0.0)


func _sample_input(name: String, act: Callable) -> Dictionary:
	var t0 := Time.get_ticks_usec()
	act.call()
	if _scene.has_method("queue_redraw"):
		_scene.queue_redraw()
	RenderingServer.force_draw(false, 0.0)
	await process_frame
	var visible_ms := (Time.get_ticks_usec() - t0) / 1000.0
	var follow := await _sample_frames(name + "_follow", func(_i: int) -> void: pass)
	follow["input_to_visible_ms"] = visible_ms
	follow["name"] = name
	return follow


func _summarize(name: String, times: Array, scripts: Array, draws: Array, input_ms: float) -> Dictionary:
	times.sort()
	scripts.sort()
	draws.sort()
	return {
		"name": name,
		"samples": times.size(),
		"p50_ms": _pct(times, 0.50),
		"p95_ms": _pct(times, 0.95),
		"p99_ms": _pct(times, 0.99),
		"max_ms": 0.0 if times.is_empty() else float(times[times.size() - 1]),
		"script_p50_ms": _pct(scripts, 0.50),
		"script_p95_ms": _pct(scripts, 0.95),
		"script_max_ms": 0.0 if scripts.is_empty() else float(scripts[scripts.size() - 1]),
		"draw_calls_p50": _pct(draws, 0.50),
		"draw_calls_p95": _pct(draws, 0.95),
		"input_to_visible_ms": input_ms,
	}


func _compare(owner_block: Dictionary, fixture_block: Dictionary) -> Dictionary:
	var owner_io: Dictionary = owner_block.get("io", {}).get("snapshot", {})
	var fixture_io: Dictionary = fixture_block.get("io", {}).get("fixture", {})
	if fixture_io.is_empty():
		fixture_io = fixture_block.get("io", {}).get("snapshot", {})
	return {
		"owner_snapshot_bytes": int(owner_io.get("bytes", 0)),
		"fixture_snapshot_bytes": int(fixture_io.get("bytes", 0)),
		"owner_snapshot_read_ms": owner_io.get("read_ms", 0.0),
		"fixture_snapshot_read_ms": fixture_io.get("read_ms", 0.0),
		"owner_snapshot_parse_ms": owner_io.get("parse_ms", 0.0),
		"fixture_snapshot_parse_ms": fixture_io.get("parse_ms", 0.0),
		"owner_scene_load_ms": owner_block.get("scene_load_ms", 0.0),
		"fixture_scene_load_ms": fixture_block.get("scene_load_ms", 0.0),
		"owner_provinces": (owner_block.get("counts", {}) as Dictionary).get("provinces", 0),
		"fixture_provinces": (fixture_block.get("counts", {}) as Dictionary).get("provinces", 0),
		"owner_idle_max_ms": ((owner_block.get("scenarios", {}) as Dictionary).get("idle", {}) as Dictionary).get("max_ms", 0.0),
		"fixture_idle_max_ms": ((fixture_block.get("scenarios", {}) as Dictionary).get("idle", {}) as Dictionary).get("max_ms", 0.0),
		"owner_pan_max_ms": ((owner_block.get("scenarios", {}) as Dictionary).get("continuous_pan", {}) as Dictionary).get("max_ms", 0.0),
		"fixture_pan_max_ms": ((fixture_block.get("scenarios", {}) as Dictionary).get("continuous_pan", {}) as Dictionary).get("max_ms", 0.0),
		"owner_select_visible_ms": ((owner_block.get("scenarios", {}) as Dictionary).get("province_select", {}) as Dictionary).get("input_to_visible_ms", 0.0),
		"fixture_select_visible_ms": ((fixture_block.get("scenarios", {}) as Dictionary).get("province_select", {}) as Dictionary).get("input_to_visible_ms", 0.0),
	}


func _pct(values: Array, q: float) -> float:
	if values.is_empty():
		return 0.0
	var index := int(round((values.size() - 1) * q))
	return float(values[clampi(index, 0, values.size() - 1)])


func _write_json(path: String, payload: Dictionary) -> void:
	var text := JSON.stringify(payload, "\t") + "\n"
	if path.begins_with("user://") or path.begins_with("res://"):
		var handle := FileAccess.open(path, FileAccess.WRITE)
		if handle != null:
			handle.store_string(text)
		return
	DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	var disk := FileAccess.open(path, FileAccess.WRITE)
	if disk != null:
		disk.store_string(text)


func _fail(message: String) -> void:
	push_error("overmap_stall_capture: %s" % message)
	quit(1)
