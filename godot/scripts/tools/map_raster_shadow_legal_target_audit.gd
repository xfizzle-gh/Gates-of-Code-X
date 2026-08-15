extends "res://scripts/tools/map_raster_shadow_profiler_audited.gd"

## #212 Phase B legal-target authority audit.
##
## The performance fixture intentionally does not invent graph orders. This tool
## discovers a committed Earth3 snapshot that already contains backend-authored
## operational_orders, selects one deterministic real order, and proves the exact
## non-empty legal-target set is unchanged by polygon/full-cache/512/1024
## presentation while PolygonMap remains live.

const SNAPSHOT_CANDIDATES := [
	"res://fixtures/snapshots/earth3_operational.json",
	"res://fixtures/snapshots/earth3_theatre.json",
]
const LEGAL_SCREEN_FRAMES := 12

var _legal_screens_dir := "user://issue212-raster-shadow-legal-screens"


func _initialize() -> void:
	_fixture_path = DEFAULT_FIXTURE
	_manifest_path = DEFAULT_MANIFEST
	_frames = 24
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--screens-dir="):
			_legal_screens_dir = text.substr(14).strip_edges()
		elif text.begins_with("--fixture="):
			_fixture_path = text.substr(10).strip_edges()
		elif text.begins_with("--manifest="):
			_manifest_path = text.substr(11).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
	call_deferred("_run_legal_audit")


func _run_legal_audit() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	var discovered := _discover_real_order_snapshot()
	if not bool(discovered.get("ok", false)):
		_fail("no committed Earth3 snapshot with backend-authored operational_orders: %s" % JSON.stringify(discovered))
		return
	_snapshot_path = String(discovered.get("snapshot_path", ""))
	var order: Dictionary = discovered.get("order", {})
	var authority_before := _authority_hashes()

	var source_result := await _build_scene()
	if not bool(source_result.get("ok", false)):
		_fail("legal source scene failed: %s" % source_result.get("error", "unknown"))
		return
	var source_scene: Node = source_result.get("scene")
	var source_map = _active_map(source_scene)
	var authority_error := _authority_error(source_scene, source_map)
	if not authority_error.is_empty():
		await _dispose_scene(source_scene)
		_fail(authority_error)
		return
	var reference := _configure_real_order(source_scene, order)
	if not bool(reference.get("ok", false)):
		await _dispose_scene(source_scene)
		_fail("real legal-target state failed: %s" % JSON.stringify(reference))
		return
	_cache_image = await _capture_static_map(source_scene, source_map)
	await _dispose_scene(source_scene)
	if _cache_image == null or _cache_image.is_empty():
		_fail("legal audit static cache capture empty")
		return

	DirAccess.make_dir_recursive_absolute(_legal_screens_dir)
	var mode_results: Dictionary = {}
	var screenshots: Array = []
	var modes := [
		{"name": "polygon", "tile": 0},
		{"name": "full_cache", "tile": 0},
		{"name": "tile_512", "tile": 512},
		{"name": "tile_1024", "tile": 1024},
	]
	for mode_value in modes:
		var mode: Dictionary = mode_value
		var name := String(mode.get("name", ""))
		var tile_size := int(mode.get("tile", 0))
		var checked := await _check_mode(name, tile_size, order, reference)
		if not bool(checked.get("ok", false)):
			_fail("legal-target parity failed mode=%s detail=%s" % [name, JSON.stringify(checked)])
			return
		mode_results[name] = checked
		var shot := String(checked.get("screenshot", ""))
		if shot.is_empty():
			_fail("legal-target screenshot missing mode=%s" % name)
			return
		screenshots.append(shot)

	var authority_after := _authority_hashes()
	if authority_after != authority_before:
		_fail("authority bytes changed during legal-target audit")
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-raster-shadow-legal-target-audit",
		"schema_version": 1,
		"issue": 212,
		"phase": "B-debug-shadow-legal-target-parity",
		"snapshot_path": _snapshot_path,
		"snapshot_sha256": FileAccess.get_sha256(_snapshot_path),
		"order_source": "committed backend-authored operational_orders",
		"order": {
			"formation_id": order.get("formation_id", ""),
			"origin_province_id": order.get("origin_province_id", ""),
			"target_province_id": order.get("target_province_id", ""),
		},
		"reference": reference,
		"modes": mode_results,
		"authority": {
			"unchanged": true,
			"hashes_before": authority_before,
			"hashes_after": authority_after,
			"polygon_backend_remains_live": true,
		},
		"screenshots": screenshots,
	}
	_write_json(_out_path, result)
	print("ISSUE212_REAL_LEGAL_TARGET_PARITY %s" % JSON.stringify({
		"snapshot": _snapshot_path,
		"formation": order.get("formation_id", ""),
		"legal_targets": reference.get("legal_target_ids", []),
	}))
	print("map_raster_shadow_legal_target_audit: PASS out=%s" % _out_path)
	quit(0)


func _discover_real_order_snapshot() -> Dictionary:
	var diagnostics: Array = []
	for path_value in SNAPSHOT_CANDIDATES:
		var path := String(path_value)
		var parsed := _read_json_dict(path)
		if parsed.is_empty():
			diagnostics.append({"path": path, "error": "missing or invalid"})
			continue
		var campaign: Dictionary = parsed.get("campaign", {})
		var strategic: Dictionary = parsed.get("strategic_map", {})
		var map_id := String(strategic.get("map_id", campaign.get("map_id", "")))
		if map_id != "earth3_europe_mediterranean":
			diagnostics.append({"path": path, "map_id": map_id, "error": "not Earth3"})
			continue
		var orders_value: Variant = parsed.get("operational_orders", [])
		if not orders_value is Array or (orders_value as Array).is_empty():
			diagnostics.append({"path": path, "operational_order_count": 0})
			continue
		for order_value in orders_value:
			if not order_value is Dictionary:
				continue
			var order := order_value as Dictionary
			var formation := String(order.get("formation_id", ""))
			var origin := String(order.get("origin_province_id", ""))
			var target := String(order.get("target_province_id", ""))
			if not formation.is_empty() and not origin.is_empty() and not target.is_empty():
				return {
					"ok": true,
					"snapshot_path": path,
					"operational_order_count": (orders_value as Array).size(),
					"order": order,
				}
		diagnostics.append({"path": path, "operational_order_count": (orders_value as Array).size(), "error": "no complete order row"})
	return {"ok": false, "candidates": diagnostics}


func _configure_real_order(scene: Node, order: Dictionary) -> Dictionary:
	var formation_id := String(order.get("formation_id", ""))
	var origin := String(order.get("origin_province_id", ""))
	var target := String(order.get("target_province_id", ""))
	if formation_id.is_empty() or origin.is_empty() or target.is_empty():
		return {"ok": false, "error": "incomplete order row"}
	if scene.get("selected_strategic_formation_id") != null:
		scene.selected_strategic_formation_id = formation_id
	if scene.get("selected_province_id") != null:
		scene.selected_province_id = origin
	if scene.has_method("_rebuild_legal_targets"):
		scene.call("_rebuild_legal_targets")
	var legal_value: Variant = scene.get("legal_targets")
	var legal_ids: Array = []
	if legal_value is Dictionary:
		legal_ids = (legal_value as Dictionary).keys()
		legal_ids.sort()
	var orders_value: Variant = scene.get("orders_by_formation")
	var indexed_rows: Array = []
	if orders_value is Dictionary:
		var rows_value: Variant = (orders_value as Dictionary).get(formation_id, [])
		if rows_value is Array:
			indexed_rows = (rows_value as Array).duplicate(true)
	return {
		"ok": not legal_ids.is_empty() and legal_ids.has(target) and not indexed_rows.is_empty(),
		"selected_strategic_formation_id": String(scene.get("selected_strategic_formation_id")),
		"selected_province_id": String(scene.get("selected_province_id")),
		"legal_target_ids": legal_ids,
		"required_target_id": target,
		"indexed_order_count": indexed_rows.size(),
	}


func _check_mode(mode_name: String, tile_size: int, order: Dictionary, reference: Dictionary) -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}
	var configured := _configure_real_order(scene, order)
	if not bool(configured.get("ok", false)):
		await _dispose_scene(scene)
		return {"ok": false, "error": "could not configure real order", "state": configured}
	var shadow := {}
	if mode_name != "polygon":
		shadow = _mount_shadow(scene, tile_size)
		if shadow.is_empty():
			await _dispose_scene(scene)
			return {"ok": false, "error": "failed to mount cache"}
	for i in range(LEGAL_SCREEN_FRAMES):
		var t := float(i) / float(maxi(LEGAL_SCREEN_FRAMES - 1, 1))
		if scene.get("view_scale") != null:
			scene.view_scale = 1.25 + 0.65 * (0.5 + 0.5 * sin(t * TAU))
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2(70.0 * cos(t * TAU), 45.0 * sin(t * TAU))
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		_sync_shadow(shadow)
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var final_state := _configure_real_order(scene, order)
	var exact: bool = bool(final_state.get("ok", false)) \
		and final_state.get("selected_strategic_formation_id", "") == reference.get("selected_strategic_formation_id", "") \
		and final_state.get("selected_province_id", "") == reference.get("selected_province_id", "") \
		and final_state.get("legal_target_ids", []) == reference.get("legal_target_ids", [])
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image := viewport.get_texture().get_image() if viewport != null else null
	var name := "legal_targets__%s.png" % mode_name
	var screenshot_ok: bool = image != null and not image.is_empty() and image.save_png(_legal_screens_dir.path_join(name)) == OK
	var result := {
		"ok": exact and screenshot_ok and bool(scene.get("map_backend_is_polygon")),
		"state": final_state,
		"exact_legal_target_identity": exact,
		"polygon_backend_live": bool(scene.get("map_backend_is_polygon")),
		"screenshot": name if screenshot_ok else "",
	}
	await _dispose_scene(scene)
	return result


func _read_json_dict(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	return parsed as Dictionary if parsed is Dictionary else {}
