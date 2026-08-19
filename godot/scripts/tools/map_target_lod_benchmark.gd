extends SceneTree

## #212 same-harness owner-snapshot benchmark. Read-only.
## Works on both 249690eb and the target-LOD branch.

const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const DEFAULT_SCALE := 1.150
const DEFAULT_OFFSET := Vector2(0.0, 1.58721923828125)

var _out_path := "user://overmap-target-lod-benchmark.json"
var _snapshot_path := ""
var _campaign_path := ""
var _label := ""
var _width := 1920
var _height := 1080
var _frames := 240
var _warmup := 6
var _scale := DEFAULT_SCALE
var _thresholds: PackedFloat32Array = PackedFloat32Array()


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--campaign="):
			_campaign_path = text.substr(11).strip_edges()
		elif text.begins_with("--label="):
			_label = text.substr(8).strip_edges()
		elif text.begins_with("--frames="):
			_frames = maxi(int(text.substr(9)), 24)
		elif text.begins_with("--warmup="):
			_warmup = maxi(int(text.substr(9)), 1)
		elif text.begins_with("--scale="):
			_scale = float(text.substr(8))
		elif text.begins_with("--thresholds="):
			for part in text.substr(13).split(","):
				var s := String(part).strip_edges()
				if not s.is_empty():
					_thresholds.append(float(s))
	call_deferred("_run")


func _run() -> void:
	if DisplayServer.has_method("window_set_vsync_mode"):
		DisplayServer.window_set_vsync_mode(DisplayServer.VSYNC_DISABLED)
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)
	if _snapshot_path.is_empty() or not FileAccess.file_exists(_snapshot_path):
		push_error("map_target_lod_benchmark: missing --snapshot=")
		quit(1)
		return
	var packed := load("res://main.tscn")
	if packed == null:
		push_error("map_target_lod_benchmark: failed to load main.tscn")
		quit(1)
		return
	var scene: Node = packed.instantiate()
	if scene == null or not scene.has_method("_load_snapshot"):
		push_error("map_target_lod_benchmark: main.tscn script did not attach")
		quit(1)
		return
	root.add_child(scene)
	if scene.get("map_debug") != null:
		scene.map_debug.enabled = false
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = DEFAULT_MANIFEST
	scene.call("_load_snapshot", _snapshot_path)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	_apply_camera(scene, _scale, DEFAULT_OFFSET)
	await _warmup_scene(scene)
	var inventory := _inventory(scene)
	var idle := await _sample(scene, func(_i: int) -> void: pass)
	var hover := await _sample(scene, func(_i: int) -> void:
		if scene.get("hovered_province_id") != null:
			scene.hovered_province_id = _nth_legal(scene, 0)
	)
	if scene.get("hovered_province_id") != null:
		scene.hovered_province_id = ""
	var pan := await _sample(scene, func(i: int) -> void:
		var t := float(i) / float(maxi(_frames - 1, 1))
		scene.view_offset = Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0)
		scene.view_scale = _scale
	)
	_apply_camera(scene, _scale, DEFAULT_OFFSET)
	var threshold_rows: Dictionary = {}
	for i in range(_thresholds.size()):
		var zoom := float(_thresholds[i])
		_apply_camera(scene, zoom, DEFAULT_OFFSET)
		await _warmup_scene(scene)
		var row_idle := await _sample(scene, func(_j: int) -> void: pass)
		threshold_rows[str(zoom)] = {
			"inventory": _inventory(scene),
			"idle": row_idle,
		}
		print("map_target_lod_benchmark: threshold=%s draws=%s p50=%s" % [
			zoom,
			row_idle.get("draw_calls_p50", 0.0),
			row_idle.get("p50_ms", 0.0),
		])
	var payload := {
		"schema": "gates-of-codex.overmap-target-lod-benchmark",
		"schema_version": 2,
		"read_only": true,
		"harness": "map_target_lod_benchmark.gd",
		"label": _label,
		"snapshot_path": _snapshot_path,
		"campaign_path": _campaign_path,
		"frames": _frames,
		"warmup": _warmup,
		"viewport": {"width": _width, "height": _height},
		"camera": {"view_scale": _scale, "view_offset": [DEFAULT_OFFSET.x, DEFAULT_OFFSET.y]},
		"inventory": inventory,
		"idle": idle,
		"hover": hover,
		"pan": pan,
		"thresholds": threshold_rows,
	}
	_write_json(_out_path, payload)
	print("map_target_lod_benchmark: PASS")
	print(JSON.stringify({
		"label": _label,
		"idle": idle,
		"hover": hover,
		"pan": pan,
		"inventory": {
			"legal_targets": inventory.get("legal_targets", 0),
			"overlay_active_ids": inventory.get("overlay_active_ids", 0),
			"detailed_targets": inventory.get("detailed_targets", 0),
			"on_screen_legal_targets": inventory.get("on_screen_legal_targets", 0),
			"selected_formation_id": inventory.get("selected_formation_id", ""),
		},
	}, "\t"))
	quit(0)


func _apply_camera(scene: Node, scale: float, offset: Vector2) -> void:
	scene.view_scale = scale
	scene.view_offset = offset
	if scene.has_method("_rebuild_legal_targets"):
		scene.call("_rebuild_legal_targets")
	if scene.has_method("_rebuild_focus_set"):
		scene.call("_rebuild_focus_set")
	if scene.has_method("_invalidate_overlay_cache"):
		scene.call("_invalidate_overlay_cache")
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true


func _warmup_scene(scene: Node) -> void:
	for _i in range(_warmup):
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _inventory(scene: Node) -> Dictionary:
	var legal: Dictionary = scene.legal_targets if scene.get("legal_targets") != null else {}
	var focus: Dictionary = scene.focus_province_ids if scene.get("focus_province_ids") != null else {}
	var markers := 0
	if scene.has_method("get_visible_target_marker_ids_for_test"):
		markers = scene.call("get_visible_target_marker_ids_for_test").size()
	var overlay := 0
	if scene.has_method("get_overlay_active_province_ids_for_test"):
		overlay = scene.call("get_overlay_active_province_ids_for_test").size()
	var emphasis := 0
	if scene.has_method("get_emphasis_legal_target_ids_for_test"):
		emphasis = scene.call("get_emphasis_legal_target_ids_for_test").size()
	var detailed := 0
	if scene.has_method("_highlight_targets_for_draw"):
		detailed = (scene.call("_highlight_targets_for_draw") as Dictionary).size()
	return {
		"selected_formation_id": String(scene.selected_strategic_formation_id),
		"selected_province_id": String(scene.selected_province_id),
		"legal_targets": legal.size(),
		"legal_target_ids": legal.keys(),
		"focus_provinces": focus.size(),
		"visible_target_markers": markers,
		"emphasis_targets": emphasis,
		"detailed_targets": detailed,
		"overlay_active_ids": overlay,
		"on_screen_legal_targets": _on_screen_legal_count(scene),
		"view_scale": float(scene.view_scale),
	}


func _on_screen_legal_count(scene: Node) -> int:
	if not scene.has_method("_overlay_clamp_rect") or not scene.has_method("_image_to_screen"):
		return -1
	var am = null
	if scene.has_method("_active_map"):
		am = scene.call("_active_map")
	if am == null or not bool(am.get("is_ready")):
		return -1
	var bounds: Rect2 = scene.call("_overlay_clamp_rect")
	var n := 0
	var legal: Dictionary = scene.legal_targets if scene.get("legal_targets") != null else {}
	for tid in legal.keys():
		var pid := String(tid)
		if not am.row_by_province.has(pid):
			continue
		var screen: Vector2 = scene.call("_image_to_screen", am.anchor_pixel(pid))
		if bounds.has_point(screen):
			n += 1
	return n


func _nth_legal(scene: Node, index: int) -> String:
	var legal: Dictionary = scene.legal_targets if scene.get("legal_targets") != null else {}
	var keys: Array = legal.keys()
	if keys.is_empty():
		return ""
	return String(keys[clampi(index, 0, keys.size() - 1)])


func _sample(scene: Node, mutate: Callable) -> Dictionary:
	var times: Array = []
	var draws: Array = []
	for i in range(_frames):
		mutate.call(i)
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		var t0 := Time.get_ticks_usec()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		times.append((Time.get_ticks_usec() - t0) / 1000.0)
		draws.append(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
	times.sort()
	draws.sort()
	return {
		"samples": times.size(),
		"p50_ms": _pct(times, 0.50),
		"p95_ms": _pct(times, 0.95),
		"p99_ms": _pct(times, 0.99),
		"max_ms": 0.0 if times.is_empty() else float(times[times.size() - 1]),
		"draw_calls_p50": _pct(draws, 0.50),
		"draw_calls_p95": _pct(draws, 0.95),
		"draw_calls_p99": _pct(draws, 0.99),
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
