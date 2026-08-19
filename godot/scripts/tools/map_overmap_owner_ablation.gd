extends SceneTree

## #212 diagnostic. Same owner snapshot, same camera. Disable one presentation
## category at a time. Does not write the owner campaign or its snapshot.

const WARMUP := 6
const FRAMES := 24
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const PROBES := [
	"baseline",
	"land_fill",
	"ocean_mesh",
	"shared_borders",
	"labels",
	"formation_counters",
	"infrastructure_sites",
	"routes",
	"legal_targets_focus",
	"operational_orders",
	"map_debug",
]

var _out_path := "user://overmap-owner-ablation.json"
var _snapshot_path := ""
var _campaign_path := ""
var _manifest_path := DEFAULT_MANIFEST
var _width := 1920
var _height := 1080
var _camera := {"view_scale": 1.0, "view_offset": Vector2.ZERO}
var _camera_ready := false


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
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
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
		_fail("missing --snapshot=")
		return

	var probes: Dictionary = {}
	for probe_variant in PROBES:
		var probe := String(probe_variant)
		var measured := await _measure_probe(probe)
		if not bool(measured.get("ok", false)):
			_fail("probe failed: %s detail=%s" % [probe, measured.get("error", "unknown")])
			return
		probes[probe] = measured
		print("overmap_owner_ablation: probe=%s p50=%s max=%s draws=%s" % [
			probe,
			measured.get("p50_ms", 0.0),
			measured.get("max_ms", 0.0),
			measured.get("draw_calls_p50", 0.0),
		])

	var baseline: Dictionary = probes.get("baseline", {})
	var deltas: Dictionary = {}
	for probe_variant in PROBES:
		var probe := String(probe_variant)
		if probe == "baseline":
			continue
		var row: Dictionary = probes.get(probe, {})
		deltas[probe] = {
			"p50_ms": snappedf(float(baseline.get("p50_ms", 0.0)) - float(row.get("p50_ms", 0.0)), 0.001),
			"max_ms": snappedf(float(baseline.get("max_ms", 0.0)) - float(row.get("max_ms", 0.0)), 0.001),
			"draw_calls_p50": float(baseline.get("draw_calls_p50", 0.0)) - float(row.get("draw_calls_p50", 0.0)),
		}

	var payload := {
		"schema": "gates-of-codex.overmap-owner-ablation",
		"schema_version": 1,
		"read_only": true,
		"issue": 212,
		"snapshot_path": _snapshot_path,
		"campaign_path": _campaign_path,
		"camera": {
			"view_scale": _camera.get("view_scale", 1.0),
			"view_offset": [_camera.view_offset.x, _camera.view_offset.y],
		},
		"viewport": {"width": _width, "height": _height, "frames": FRAMES},
		"probes": probes,
		"deltas_from_baseline": deltas,
		"notes": [
			"Same owner snapshot and the same fitted-theatre camera for every probe.",
			"Each probe uses a fresh main scene so mutations do not leak.",
			"MapDebug is forced off except the map_debug probe, which enables it.",
			"Owner campaign files are not written.",
		],
	}
	_write_json(_out_path, payload)
	print("overmap_owner_ablation: PASS")
	print(JSON.stringify(deltas, "\t"))
	quit(0)


func _measure_probe(probe: String) -> Dictionary:
	var packed := load("res://main.tscn")
	if packed == null:
		return {"ok": false, "error": "failed to load main.tscn"}
	var scene: Node = packed.instantiate()
	if scene == null or not scene.has_method("_load_snapshot"):
		return {"ok": false, "error": "main.tscn script did not attach"}
	root.add_child(scene)
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = _manifest_path
	if scene.get("map_debug") != null:
		scene.map_debug.enabled = probe == "map_debug"
	scene.call("_load_snapshot", _snapshot_path)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	var load_error := str(scene.get("load_error") if scene.get("load_error") != null else "")
	if not load_error.is_empty():
		await _dispose(scene)
		return {"ok": false, "error": load_error}
	if not _camera_ready:
		_camera = {
			"view_scale": float(scene.view_scale),
			"view_offset": Vector2(scene.view_offset),
		}
		_camera_ready = true
	scene.view_scale = float(_camera.get("view_scale", 1.0))
	scene.view_offset = Vector2(_camera.view_offset)
	_apply_probe(scene, probe)
	if scene.has_method("_invalidate_overlay_cache"):
		scene.call("_invalidate_overlay_cache")
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	for _i in range(WARMUP):
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var inventory := _inventory(scene)
	var times: Array = []
	var draws: Array = []
	for _i in range(FRAMES):
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		var t0 := Time.get_ticks_usec()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		times.append((Time.get_ticks_usec() - t0) / 1000.0)
		draws.append(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME))
	times.sort()
	draws.sort()
	await _dispose(scene)
	return {
		"ok": true,
		"probe": probe,
		"p50_ms": _pct(times, 0.50),
		"p95_ms": _pct(times, 0.95),
		"max_ms": 0.0 if times.is_empty() else float(times[times.size() - 1]),
		"draw_calls_p50": _pct(draws, 0.50),
		"draw_calls_p95": _pct(draws, 0.95),
		"inventory": inventory,
	}


func _apply_probe(scene: Node, probe: String) -> void:
	match probe:
		"baseline":
			pass
		"land_fill":
			_set_polygon_children_visible(scene, "Earth3Chunk_", false)
		"ocean_mesh":
			_set_named_child_visible(scene, "Earth3Ocean", false)
		"shared_borders":
			_set_named_child_visible(scene, "Earth3Borders", false)
		"labels":
			_clear_fixture_keys(scene, ["proof_labels"])
			var candidates: Variant = scene.get("_cached_label_candidates")
			if candidates is Array:
				(candidates as Array).clear()
			var bounds: Variant = scene.get("_cached_label_bounds")
			if bounds is Array:
				(bounds as Array).clear()
		"formation_counters":
			_clear_dict(scene, "battalions_by_province")
			_clear_dict(scene, "battalion_stacks_by_province")
			_clear_fixture_keys(scene, ["synthetic_counters", "force_stack_badges"])
		"infrastructure_sites":
			_zero_snapshot_infrastructure(scene)
			_clear_fixture_keys(scene, ["control_sites"])
		"routes":
			_clear_fixture_keys(scene, ["routes"])
			if scene.get("selected_strategic_formation_id") != null:
				scene.selected_strategic_formation_id = ""
		"legal_targets_focus":
			_clear_dict(scene, "legal_targets")
			_clear_dict(scene, "focus_province_ids")
			var am = scene.get("polygon_map")
			if am != null and am.has_method("refresh_highlights"):
				am.refresh_highlights(String(scene.selected_province_id), {})
		"operational_orders":
			var snap_value: Variant = scene.get("snapshot")
			if snap_value is Dictionary:
				(snap_value as Dictionary)["operational_orders"] = []
			if scene.has_method("index_operational_orders"):
				var indexed: Dictionary = scene.call("index_operational_orders", scene.snapshot)
				scene.orders_by_formation = indexed.get("by_formation", {})
				scene.order_formations_by_province = indexed.get("by_province", {})
			if scene.get("selected_strategic_formation_id") != null:
				scene.selected_strategic_formation_id = ""
			if scene.has_method("_rebuild_legal_targets"):
				scene.call("_rebuild_legal_targets")
			if scene.has_method("_rebuild_focus_set"):
				scene.call("_rebuild_focus_set")
		"map_debug":
			if scene.get("map_debug") != null:
				scene.map_debug.enabled = true
		_:
			push_error("unknown ablation probe: %s" % probe)


func _inventory(scene: Node) -> Dictionary:
	var snap: Dictionary = scene.snapshot if scene.get("snapshot") != null else {}
	var orders: Array = snap.get("operational_orders", [])
	var legal: Dictionary = scene.legal_targets if scene.get("legal_targets") != null else {}
	var focus: Dictionary = scene.focus_province_ids if scene.get("focus_province_ids") != null else {}
	var labels: Array = scene._cached_label_candidates if scene.get("_cached_label_candidates") != null else []
	var overlay_ids := 0
	if scene.has_method("get_overlay_active_province_ids_for_test"):
		overlay_ids = scene.call("get_overlay_active_province_ids_for_test").size()
	var holder := scene.get_node_or_null("Earth3PolygonRoot")
	var chunks := 0
	var visible_chunks := 0
	if holder != null:
		for child in holder.get_children():
			if String(child.name).begins_with("Earth3Chunk_"):
				chunks += 1
				if child is CanvasItem and (child as CanvasItem).visible:
					visible_chunks += 1
	var debug_on := false
	if scene.get("map_debug") != null:
		debug_on = bool(scene.map_debug.enabled)
	return {
		"orders": orders.size(),
		"legal_targets": legal.size(),
		"focus_provinces": focus.size(),
		"labels": labels.size(),
		"overlay_active_ids": overlay_ids,
		"land_chunks": chunks,
		"visible_land_chunks": visible_chunks,
		"map_debug_enabled": debug_on,
		"view_scale": float(scene.view_scale),
		"selected_province_id": String(scene.selected_province_id),
		"selected_formation_id": String(scene.selected_strategic_formation_id),
	}


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


func _clear_dict(scene: Node, property_name: String) -> void:
	var value: Variant = scene.get(property_name)
	if value is Dictionary:
		(value as Dictionary).clear()


func _zero_snapshot_infrastructure(scene: Node) -> void:
	var snapshot_value: Variant = scene.get("snapshot")
	if not snapshot_value is Dictionary:
		return
	for row_variant in (snapshot_value as Dictionary).get("provinces", []):
		if row_variant is Dictionary:
			(row_variant as Dictionary)["infrastructure"] = {}
	if scene.get("_snap_by_id_src") != null:
		scene._snap_by_id_src = null
	if scene.has_method("_ensure_snapshot_overlay_indexes"):
		scene.call("_ensure_snapshot_overlay_indexes")


func _dispose(scene: Node) -> void:
	if scene != null and is_instance_valid(scene):
		scene.queue_free()
	await process_frame
	await process_frame


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
	push_error("overmap_owner_ablation: %s" % message)
	quit(1)
