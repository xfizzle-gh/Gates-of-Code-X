extends SceneTree

## #212 production overmap interaction profiler.
## MapDebug stays OFF. This is the ordinary-player pan/zoom path.

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/e3_operational.json"
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const WARMUP_FRAMES := 8
const DEFAULT_FRAMES := 36

var _out_path := "user://overmap-interaction.json"
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
	if _scene.get("map_manifest_source_path") != null:
		_scene.map_manifest_source_path = _manifest_path
	if _scene.has_method("_load_presentation_fixture"):
		_scene.call("_load_presentation_fixture", _fixture_path)
	if _scene.has_method("_open_color_id_map"):
		_scene.call("_open_color_id_map")
	if _scene.get("map_debug") != null:
		_scene.map_debug.enabled = false
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")

	for _i in range(WARMUP_FRAMES):
		RenderingServer.force_draw(false, 0.0)
		await process_frame

	var idle := await _sample("idle", func(_i: int) -> void: pass)
	var pan := await _sample("pan", func(i: int) -> void:
		var t := float(i) / float(maxi(_frames - 1, 1))
		if _scene.get("view_offset") != null:
			_scene.view_offset = Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0)
		if _scene.has_method("mark_camera_moving"):
			_scene.call("mark_camera_moving")
	)
	var zoom := await _sample("zoom", func(i: int) -> void:
		var t := float(i) / float(maxi(_frames - 1, 1))
		_scene.view_scale = 1.0 + t * 2.2
		if _scene.has_method("mark_camera_moving"):
			_scene.call("mark_camera_moving")
	)

	var payload := {
		"schema": "gates-of-codex.overmap-interaction",
		"schema_version": 1,
		"production_renderer": "PolygonMap" if bool(_scene.get("map_backend_is_polygon")) else "unknown",
		"map_debug": false,
		"viewport": {"width": _width, "height": _height, "frames": _frames},
		"scenarios": {"idle": idle, "pan": pan, "zoom": zoom},
	}
	_write_json(_out_path, payload)
	print("overmap_interaction_profiler: PASS")
	print(JSON.stringify(payload, "\t"))
	quit(0)


func _sample(name: String, mutate: Callable) -> Dictionary:
	var times: Array = []
	var draws: Array = []
	var rebuilds_before := int(_scene.get("overlay_rebuild_count") if _scene.get("overlay_rebuild_count") != null else 0)
	var max_scanned := 0
	var saw_scan_all := false
	for i in range(_frames):
		mutate.call(i)
		if _scene.has_method("queue_redraw"):
			_scene.queue_redraw()
		var t0 := Time.get_ticks_usec()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		times.append((Time.get_ticks_usec() - t0) / 1000.0)
		draws.append(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
		max_scanned = maxi(max_scanned, int(_scene.get("overlay_provinces_scanned") if _scene.get("overlay_provinces_scanned") != null else 0))
		if bool(_scene.get("overlay_last_scan_all") if _scene.get("overlay_last_scan_all") != null else false):
			saw_scan_all = true
	var rebuilds_after := int(_scene.get("overlay_rebuild_count") if _scene.get("overlay_rebuild_count") != null else 0)
	times.sort()
	draws.sort()
	return {
		"name": name,
		"p50_ms": _percentile(times, 0.50),
		"p95_ms": _percentile(times, 0.95),
		"draw_calls_p50": _percentile(draws, 0.50),
		"draw_calls_p95": _percentile(draws, 0.95),
		"overlay_rebuilds": rebuilds_after - rebuilds_before,
		"overlay_provinces_scanned_max": max_scanned,
		"overlay_scan_all": saw_scan_all,
	}


func _percentile(values: Array, q: float) -> float:
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
	var abs_path := path
	DirAccess.make_dir_recursive_absolute(abs_path.get_base_dir())
	var disk := FileAccess.open(abs_path, FileAccess.WRITE)
	if disk != null:
		disk.store_string(text)


func _fail(message: String) -> void:
	push_error("overmap_interaction_profiler: %s" % message)
	quit(1)
