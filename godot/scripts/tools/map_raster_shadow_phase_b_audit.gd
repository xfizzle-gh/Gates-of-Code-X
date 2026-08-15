extends "res://scripts/tools/map_raster_shadow_profiler_audited.gd"

## #212 Phase B audit completion harness.
##
## Adds the scenario/evidence surface omitted by the original cache matrix:
## hover/select, dense formation counters, infrastructure/routes, and pending
## battle/contact. Every cache mode is locally bracketed against polygon samples,
## receives an identical-camera screenshot, and proves that map-space dynamic
## overlay points and the cache transform stay coincident while pan/zoom changes.

const AUDIT_SCENARIOS := [
	"hover_select",
	"large_formation_counters",
	"infrastructure_routes",
	"pending_battle_contact",
]
const MANY_COUNTERS_FIXTURE := "res://fixtures/presentation/many_counters.json"
const ALIGNMENT_TOLERANCE_PX := 0.25

var _audit_screens_dir := "user://issue212-raster-shadow-audit-screens"


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
			_audit_screens_dir = text.substr(14).strip_edges()
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
	call_deferred("_run_scenario_audit")


func _run_scenario_audit() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for path in [_snapshot_path, _fixture_path, _manifest_path, MANY_COUNTERS_FIXTURE]:
		if not FileAccess.file_exists(String(path)):
			_fail("required audit input missing: %s" % String(path))
			return

	var authority_before := _authority_hashes()
	var source_result := await _build_scene()
	if not bool(source_result.get("ok", false)):
		_fail("audit source scene failed: %s" % source_result.get("error", "unknown"))
		return
	var source_scene: Node = source_result.get("scene")
	var source_map = _active_map(source_scene)
	var authority_error := _authority_error(source_scene, source_map)
	if not authority_error.is_empty():
		await _dispose_scene(source_scene)
		_fail(authority_error)
		return
	var reference_parity := _authority_parity(source_scene, source_map)
	if not bool(reference_parity.get("ok", false)):
		await _dispose_scene(source_scene)
		_fail("reference parity failed: %s" % JSON.stringify(reference_parity))
		return
	_cache_image = await _capture_static_map(source_scene, source_map)
	await _dispose_scene(source_scene)
	if _cache_image == null or _cache_image.is_empty():
		_fail("audit static cache capture empty")
		return

	DirAccess.make_dir_recursive_absolute(_audit_screens_dir)
	var results: Dictionary = {}
	var screenshots: Array = []
	for scenario_value in AUDIT_SCENARIOS:
		var scenario := String(scenario_value)
		var polygon_validation := await _validate_scenario_surface("polygon", 0, scenario, reference_parity)
		if not bool(polygon_validation.get("ok", false)):
			_fail("polygon scenario validation failed scenario=%s detail=%s" % [scenario, JSON.stringify(polygon_validation)])
			return
		var polygon_shot := await _capture_scenario_screenshot("polygon", 0, scenario, reference_parity)
		if polygon_shot.is_empty():
			_fail("polygon scenario screenshot failed: %s" % scenario)
			return
		screenshots.append(polygon_shot)
		var scenario_modes: Dictionary = {}
		for mode_def_value in CACHE_MODES:
			var mode_def: Dictionary = mode_def_value
			var mode_name := String(mode_def.get("name", ""))
			var tile_size := int(mode_def.get("tile", 0))
			var bracket := await _measure_bracket(mode_name, tile_size, scenario, reference_parity)
			if not bool(bracket.get("ok", false)):
				_fail("audit bracket failed mode=%s scenario=%s detail=%s" % [mode_name, scenario, JSON.stringify(bracket)])
				return
			var validation := await _validate_scenario_surface(mode_name, tile_size, scenario, reference_parity)
			if not bool(validation.get("ok", false)):
				_fail("cache scenario validation failed mode=%s scenario=%s detail=%s" % [mode_name, scenario, JSON.stringify(validation)])
				return
			var shot := await _capture_scenario_screenshot(mode_name, tile_size, scenario, reference_parity)
			if shot.is_empty():
				_fail("cache scenario screenshot failed mode=%s scenario=%s" % [mode_name, scenario])
				return
			screenshots.append(shot)
			scenario_modes[mode_name] = {
				"bracket": bracket,
				"alignment": validation.get("alignment", {}),
				"surface": validation.get("surface", {}),
			}
		results[scenario] = {
			"polygon": polygon_validation,
			"modes": scenario_modes,
		}

	var authority_after := _authority_hashes()
	if authority_after != authority_before:
		_fail("authority bytes changed during dynamic scenario audit")
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-raster-shadow-phase-b-audit",
		"schema_version": 1,
		"issue": 212,
		"phase": "B-debug-shadow-dynamic-scenarios",
		"frames_per_sample": _frames,
		"control": {
			"bracket": "polygon_before -> cache_mode -> polygon_after",
			"max_baseline_drift_ratio": MAX_BASELINE_DRIFT_RATIO,
			"alignment_tolerance_px": ALIGNMENT_TOLERANCE_PX,
			"process_stabilization_passes": STABILIZATION_PASSES,
		},
		"authority": {
			"unchanged": true,
			"hashes_before": authority_before,
			"hashes_after": authority_after,
			"polygon_backend_remains_live": true,
		},
		"reference_parity": reference_parity,
		"scenarios": results,
		"screenshots": screenshots,
	}
	_write_json(_out_path, result)
	print("ISSUE212_PHASE_B_SCENARIOS %s" % JSON.stringify({
		"scenarios": AUDIT_SCENARIOS,
		"screenshots": screenshots.size(),
		"legal_targets": reference_parity.get("legal_target_ids", []),
	}))
	print("map_raster_shadow_phase_b_audit: PASS out=%s screens=%s" % [_out_path, _audit_screens_dir])
	quit(0)


func _apply_scenario(scene: Node, scenario: String, i: int, total: int) -> void:
	if scenario in ["idle_full_theatre", "continuous_pan", "continuous_zoom"]:
		super._apply_scenario(scene, scenario, i, total)
		return
	var t := float(i) / float(maxi(total - 1, 1))
	_prepare_nonempty_legal_targets(scene)
	match scenario:
		"hover_select":
			if scene.get("hovered_province_id") != null:
				scene.hovered_province_id = "e3_2781"
			if scene.get("view_scale") != null:
				scene.view_scale = 1.6 + 0.35 * sin(t * TAU)
			if scene.get("view_offset") != null:
				scene.view_offset = Vector2(45.0 * cos(t * TAU), 30.0 * sin(t * TAU))
		"large_formation_counters":
			_ensure_many_counters(scene)
			if scene.get("view_offset") != null:
				scene.view_offset = Vector2(140.0 * sin(t * TAU), 90.0 * cos(t * TAU))
		"infrastructure_routes":
			if scene.get("view_scale") != null:
				scene.view_scale = 1.3 + 0.8 * (0.5 + 0.5 * sin(t * TAU))
			if scene.get("view_offset") != null:
				scene.view_offset = Vector2(90.0 * cos(t * TAU), 55.0 * sin(t * TAU))
		"pending_battle_contact":
			if scene.get("selected_province_id") != null:
				scene.selected_province_id = "e3_2781"
			if scene.get("hovered_province_id") != null:
				scene.hovered_province_id = "e3_2783"
			if scene.get("view_offset") != null:
				scene.view_offset = Vector2(110.0 * sin(t * TAU), 65.0 * sin(t * TAU * 0.5))
		_:
			pass


func _ensure_many_counters(scene: Node) -> void:
	var fixture_value: Variant = scene.get("presentation_fixture")
	if not fixture_value is Dictionary:
		return
	var fixture := fixture_value as Dictionary
	var existing: Variant = fixture.get("synthetic_counters", [])
	if existing is Array and (existing as Array).size() >= 12:
		return
	var dense := _read_json_dict(MANY_COUNTERS_FIXTURE)
	var counters: Variant = dense.get("synthetic_counters", [])
	if counters is Array:
		fixture["synthetic_counters"] = (counters as Array).duplicate(true)


func _validate_scenario_surface(mode_name: String, tile_size: int, scenario: String, reference: Dictionary) -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}
	var shadow := {}
	if mode_name != "polygon":
		shadow = _mount_shadow(scene, tile_size)
		if shadow.is_empty():
			await _dispose_scene(scene)
			return {"ok": false, "error": "failed to mount shadow"}
	await _pump_matrix_frames(scene, shadow, 8, scenario)
	var parity := _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return {"ok": false, "error": "authority parity changed", "parity": parity}
	var surface := _scenario_surface(scene, scenario)
	if not bool(surface.get("ok", false)):
		await _dispose_scene(scene)
		return {"ok": false, "error": "scenario surface missing", "surface": surface}
	var alignment := _overlay_alignment(scene, shadow, scenario)
	if not bool(alignment.get("ok", false)):
		await _dispose_scene(scene)
		return {"ok": false, "error": "overlay/cache alignment failed", "alignment": alignment}
	await _dispose_scene(scene)
	return {"ok": true, "parity": parity, "surface": surface, "alignment": alignment}


func _scenario_surface(scene: Node, scenario: String) -> Dictionary:
	var fixture_value: Variant = scene.get("presentation_fixture")
	var fixture: Dictionary = fixture_value if fixture_value is Dictionary else {}
	var legal_value: Variant = scene.get("legal_targets")
	var legal_count := (legal_value as Dictionary).size() if legal_value is Dictionary else 0
	match scenario:
		"hover_select":
			var selected := String(scene.get("selected_province_id") if scene.get("selected_province_id") != null else "")
			var hovered := String(scene.get("hovered_province_id") if scene.get("hovered_province_id") != null else "")
			return {"ok": not selected.is_empty() and not hovered.is_empty() and legal_count > 0, "selected": selected, "hovered": hovered, "legal_target_count": legal_count}
		"large_formation_counters":
			var counters: Variant = fixture.get("synthetic_counters", [])
			var count := (counters as Array).size() if counters is Array else 0
			return {"ok": count >= 12, "synthetic_counter_count": count}
		"infrastructure_routes":
			var routes: Variant = fixture.get("routes", [])
			var sites: Variant = fixture.get("control_sites", [])
			var route_count := (routes as Array).size() if routes is Array else 0
			var site_count := (sites as Array).size() if sites is Array else 0
			return {"ok": route_count > 0 and site_count > 0, "route_count": route_count, "site_count": site_count}
		"pending_battle_contact":
			var battles: Variant = fixture.get("battles", [])
			var contacts: Variant = fixture.get("contacts", [])
			var pending: Variant = fixture.get("pending_battle", {})
			var battle_count := (battles as Array).size() if battles is Array else 0
			var contact_count := (contacts as Array).size() if contacts is Array else 0
			return {"ok": battle_count > 0 and contact_count > 0 and pending is Dictionary and not (pending as Dictionary).is_empty(), "battle_count": battle_count, "contact_count": contact_count, "has_pending_battle": pending is Dictionary and not (pending as Dictionary).is_empty()}
	return {"ok": false, "error": "unknown audit scenario"}


func _overlay_alignment(scene: Node, shadow: Dictionary, scenario: String) -> Dictionary:
	var points := _scenario_points(scene, scenario)
	if points.is_empty():
		return {"ok": false, "error": "no dynamic overlay probe points"}
	var map_space: Variant = scene.get("map_space")
	if map_space == null or not map_space.has_method("image_to_screen"):
		return {"ok": false, "error": "map_space image_to_screen unavailable"}
	var shadow_root := shadow.get("root") as Node2D if not shadow.is_empty() else null
	var rows: Array = []
	var max_error := 0.0
	for point_value in points:
		var point_row: Dictionary = point_value
		var pixel: Vector2 = point_row.get("pixel", Vector2.ZERO)
		var expected: Vector2 = map_space.call("image_to_screen", pixel)
		var cache_screen := expected
		if shadow_root != null:
			cache_screen = shadow_root.position + pixel * shadow_root.scale
		var error := expected.distance_to(cache_screen)
		max_error = maxf(max_error, error)
		rows.append({
			"kind": point_row.get("kind", ""),
			"id": point_row.get("id", ""),
			"image_px": _vec_row(pixel),
			"dynamic_screen_px": _vec_row(expected),
			"cache_screen_px": _vec_row(cache_screen),
			"error_px": snappedf(error, 0.001),
		})
	return {
		"ok": max_error <= ALIGNMENT_TOLERANCE_PX,
		"probe_count": rows.size(),
		"max_error_px": snappedf(max_error, 0.001),
		"tolerance_px": ALIGNMENT_TOLERANCE_PX,
		"probes": rows,
	}


func _scenario_points(scene: Node, scenario: String) -> Array:
	var fixture_value: Variant = scene.get("presentation_fixture")
	var fixture: Dictionary = fixture_value if fixture_value is Dictionary else {}
	var out: Array = []
	if scenario == "large_formation_counters":
		for row_value in fixture.get("synthetic_counters", []):
			if row_value is Dictionary:
				var row := row_value as Dictionary
				var pixel := _pixel_vec(row.get("pixel", []))
				out.append({"kind": "counter", "id": "counter-%s" % out.size(), "pixel": pixel})
	elif scenario == "infrastructure_routes":
		for row_value in fixture.get("control_sites", []):
			if row_value is Dictionary:
				var row := row_value as Dictionary
				out.append({"kind": "site", "id": row.get("id", ""), "pixel": _pixel_vec(row.get("pixel", []))})
		for row_value in fixture.get("routes", []):
			if not row_value is Dictionary:
				continue
			var row := row_value as Dictionary
			var pixels: Variant = row.get("pixels", [])
			if pixels is Array and not (pixels as Array).is_empty():
				out.append({"kind": "route-start", "id": row.get("id", ""), "pixel": _pixel_vec((pixels as Array)[0])})
				out.append({"kind": "route-end", "id": row.get("id", ""), "pixel": _pixel_vec((pixels as Array)[(pixels as Array).size() - 1])})
	elif scenario == "pending_battle_contact":
		for row_value in fixture.get("contacts", []):
			if row_value is Dictionary:
				var row := row_value as Dictionary
				out.append({"kind": "contact", "id": row.get("id", ""), "pixel": _pixel_vec(row.get("pixel", []))})
		for row_value in fixture.get("battles", []):
			if not row_value is Dictionary:
				continue
			var row := row_value as Dictionary
			if row.has("pixel"):
				out.append({"kind": "battle", "id": row.get("id", ""), "pixel": _pixel_vec(row.get("pixel", []))})
			elif row.has("presentation_edge_a_pixel") and row.has("presentation_edge_b_pixel"):
				var a := _pixel_vec(row.get("presentation_edge_a_pixel", []))
				var b := _pixel_vec(row.get("presentation_edge_b_pixel", []))
				out.append({"kind": "battle-edge", "id": row.get("id", ""), "pixel": a.lerp(b, 0.5)})
		var pending: Variant = fixture.get("pending_battle", {})
		if pending is Dictionary and not (pending as Dictionary).is_empty():
			out.append({"kind": "pending-battle", "id": (pending as Dictionary).get("id", ""), "pixel": _pixel_vec((pending as Dictionary).get("encounter_pixel", []))})
	elif scenario == "hover_select":
		var active_map = _active_map(scene)
		for pid in [String(scene.get("selected_province_id")), String(scene.get("hovered_province_id"))]:
			if not pid.is_empty():
				out.append({"kind": "selection", "id": pid, "pixel": active_map.anchor_pixel(pid)})
	return out


func _capture_scenario_screenshot(mode_name: String, tile_size: int, scenario: String, reference: Dictionary) -> String:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return ""
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	if not _authority_error(scene, active_map).is_empty():
		await _dispose_scene(scene)
		return ""
	var shadow := {}
	if mode_name != "polygon":
		shadow = _mount_shadow(scene, tile_size)
		if shadow.is_empty():
			await _dispose_scene(scene)
			return ""
	await _pump_matrix_frames(scene, shadow, 8, scenario)
	var parity := _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return ""
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image := viewport.get_texture().get_image() if viewport != null else null
	if image == null or image.is_empty():
		await _dispose_scene(scene)
		return ""
	var name := "%s__%s.png" % [scenario, mode_name]
	var path := _audit_screens_dir.path_join(name)
	var ok := image.save_png(path) == OK
	await _dispose_scene(scene)
	return name if ok else ""


func _read_json_dict(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	return parsed as Dictionary if parsed is Dictionary else {}


func _pixel_vec(value: Variant) -> Vector2:
	if value is Array and (value as Array).size() >= 2:
		return Vector2(float((value as Array)[0]), float((value as Array)[1]))
	return Vector2.ZERO


func _vec_row(value: Vector2) -> Array:
	return [snappedf(value.x, 0.001), snappedf(value.y, 0.001)]
