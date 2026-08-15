extends "res://scripts/tools/map_raster_shadow_profiler_audited.gd"

## #212 Phase B2: lazy 1024px residency experiment.
##
## This remains a debug-only presentation experiment. PolygonMap stays loaded and
## authoritative. Unlike the Phase B all-resident tiled shadow, this profiler
## creates GPU tile textures only for visible/near-visible tiles and evicts cold
## tiles after a short hysteresis window.

const LAZY_TILE_SIZE := 1024
const LAZY_RETAIN_FRAMES := 2
const PREFETCH_MARGIN_PX := 96.0
const LEGAL_PARITY_FRAMES := 12
const LAZY_SCENARIOS := ["idle_full_theatre", "continuous_pan", "continuous_zoom"]

var _legal_snapshot_path := ""
var _lazy_screens_dir := "user://issue212-lazy-1024-screens"


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
			_lazy_screens_dir = text.substr(14).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--legal-snapshot="):
			_legal_snapshot_path = text.substr(17).strip_edges()
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
	call_deferred("_run_lazy_residency")


func _run_lazy_residency() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for path_value in [_snapshot_path, _fixture_path, _manifest_path, _legal_snapshot_path]:
		var path := String(path_value)
		if path.is_empty() or not FileAccess.file_exists(path):
			_fail("required lazy-residency input missing: %s" % path)
			return

	var authority_before := _authority_hashes()
	var source_result := await _build_scene()
	if not bool(source_result.get("ok", false)):
		_fail("lazy source scene failed: %s" % source_result.get("error", "unknown"))
		return
	var source_scene: Node = source_result.get("scene")
	var source_map = _active_map(source_scene)
	var authority_error := _authority_error(source_scene, source_map)
	if not authority_error.is_empty():
		await _dispose_scene(source_scene)
		_fail(authority_error)
		return
	var reference := _authority_parity(source_scene, source_map)
	if not bool(reference.get("ok", false)):
		await _dispose_scene(source_scene)
		_fail("lazy reference parity failed: %s" % JSON.stringify(reference))
		return
	_cache_image = await _capture_static_map(source_scene, source_map)
	await _dispose_scene(source_scene)
	if _cache_image == null or _cache_image.is_empty():
		_fail("lazy static cache capture empty")
		return

	DirAccess.make_dir_recursive_absolute(_lazy_screens_dir)
	if not await _capture_lazy_screenshot(reference):
		_fail("lazy 1024 screenshot/parity failed")
		return

	var scenarios: Dictionary = {}
	for scenario_value in LAZY_SCENARIOS:
		var scenario := String(scenario_value)
		var all_resident := await super._measure_bracket("tile_1024", LAZY_TILE_SIZE, scenario, reference)
		if not bool(all_resident.get("ok", false)):
			_fail("all-resident control failed scenario=%s detail=%s" % [scenario, JSON.stringify(all_resident)])
			return
		var lazy := await _measure_lazy_bracket(scenario, reference)
		if not bool(lazy.get("ok", false)):
			_fail("lazy bracket failed scenario=%s detail=%s" % [scenario, JSON.stringify(lazy)])
			return
		scenarios[scenario] = {
			"all_resident_1024": all_resident,
			"lazy_1024": lazy,
		}

	var legal_parity := await _real_legal_lazy_parity()
	if not bool(legal_parity.get("ok", false)):
		_fail("lazy real legal-target parity failed: %s" % JSON.stringify(legal_parity))
		return

	var authority_after := _authority_hashes()
	if authority_after != authority_before:
		_fail("authority bytes changed during lazy residency experiment")
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-lazy-1024-residency",
		"schema_version": 1,
		"issue": 212,
		"phase": "B2-debug-shadow-lazy-residency",
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": RenderingServer.get_video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"frames_per_sample": _frames,
		"cache": {
			"scale": CACHE_SCALE,
			"width": _cache_image.get_width(),
			"height": _cache_image.get_height(),
			"tile_size_px": LAZY_TILE_SIZE,
			"total_tiles": _total_tile_count(),
			"full_rgba8_bytes": _cache_image.get_width() * _cache_image.get_height() * 4,
			"lazy_retain_frames": LAZY_RETAIN_FRAMES,
			"prefetch_margin_px": PREFETCH_MARGIN_PX,
			"persistent": false,
			"campaign_authority": false,
		},
		"authority": {
			"unchanged": true,
			"hashes_before": authority_before,
			"hashes_after": authority_after,
			"polygon_backend_remains_live": true,
			"lazy_cache_is_presentation_only": true,
		},
		"reference_parity": reference,
		"real_legal_target_parity": legal_parity,
		"scenarios": scenarios,
		"screenshots": ["lazy_1024.png"],
		"notes": [
			"Lazy tiles are materialized from the same derived 2x static cache used by Phase B.",
			"No tile texture exists until its map rectangle intersects the viewport plus the declared prefetch margin.",
			"Cold tiles are freed after the declared retain-frame hysteresis.",
			"Full-theatre view may still require every tile; the experiment reports that limitation rather than assuming lazy residency fixes wide-view memory.",
			"Absolute CI frame/video-memory values are llvmpipe evidence only, not owner-native acceptance.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_LAZY_1024 %s" % JSON.stringify({
		"total_tiles": result["cache"]["total_tiles"],
		"legal_target_count": legal_parity.get("legal_target_count", 0),
		"scenarios": LAZY_SCENARIOS,
	}))
	print("map_raster_lazy_1024_profiler: PASS out=%s" % _out_path)
	quit(0)


func _measure_lazy_bracket(scenario: String, reference: Dictionary) -> Dictionary:
	var before := await super._measure_one("polygon", 0, scenario, reference)
	if not bool(before.get("ok", false)):
		return before
	var lazy := await _measure_lazy_one(scenario, reference)
	if not bool(lazy.get("ok", false)):
		return lazy
	var after := await super._measure_one("polygon", 0, scenario, reference)
	if not bool(after.get("ok", false)):
		return after
	var bm: Dictionary = before.get("metrics", {})
	var lm: Dictionary = lazy.get("metrics", {})
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
		"lazy": lm,
		"polygon_after": am,
		"local_polygon_baseline": local,
		"baseline_drift": drift,
		"delta": {
			"frame_ms_p50": snappedf(float(local["frame_time_ms"]["p50"]) - float(lm["frame_time_ms"]["p50"]), 0.001),
			"frame_ms_p95": snappedf(float(local["frame_time_ms"]["p95"]) - float(lm["frame_time_ms"]["p95"]), 0.001),
			"draw_calls_p50": int(local["draw_calls"]["p50"]) - int(lm["draw_calls"]["p50"]),
			"primitives_p50": int(local["primitives"]["p50"]) - int(lm["primitives"]["p50"]),
		},
	}


func _measure_lazy_one(scenario: String, reference: Dictionary) -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}
	var shadow := _mount_lazy_shadow(scene)
	if shadow.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": "failed to mount lazy shadow"}
	await _pump_lazy_frames(scene, shadow, MATRIX_WARMUP, scenario)
	var parity := _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return {"ok": false, "error": "authority parity changed", "parity": parity}
	var metrics := await _measure_lazy_matrix(scene, shadow, scenario)
	var residency := _residency_summary(shadow)
	await _dispose_scene(scene)
	return {"ok": true, "metrics": metrics, "parity": parity, "residency": residency}


func _mount_lazy_shadow(scene: Node) -> Dictionary:
	var live_root := scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if live_root == null:
		return {}
	live_root.visible = false
	var shadow_root := Node2D.new()
	shadow_root.name = "Issue212Lazy1024Shadow"
	shadow_root.z_index = -15
	scene.add_child(shadow_root)
	var tiles: Array = []
	for y in range(0, _cache_image.get_height(), LAZY_TILE_SIZE):
		for x in range(0, _cache_image.get_width(), LAZY_TILE_SIZE):
			var w := mini(LAZY_TILE_SIZE, _cache_image.get_width() - x)
			var h := mini(LAZY_TILE_SIZE, _cache_image.get_height() - y)
			tiles.append({
				"cache_rect": Rect2i(x, y, w, h),
				"map_rect": Rect2(Vector2(x, y) / float(CACHE_SCALE), Vector2(w, h) / float(CACHE_SCALE)),
				"sprite": null,
				"last_visible_frame": -100000,
				"rgba8_bytes": w * h * 4,
			})
	var shadow := {
		"root": shadow_root,
		"live": live_root,
		"tiles": tiles,
		"frame_index": 0,
		"created_total": 0,
		"evicted_total": 0,
		"peak_resident_tiles": 0,
		"peak_resident_rgba8_bytes": 0,
	}
	_sync_lazy_shadow(shadow)
	return shadow


func _sync_lazy_shadow(shadow: Dictionary) -> Dictionary:
	var shadow_root := shadow.get("root") as Node2D
	var live_root := shadow.get("live") as Node2D
	if shadow_root == null or live_root == null:
		return {"visible": 0, "resident": 0, "resident_rgba8_bytes": 0}
	shadow_root.position = live_root.position
	shadow_root.scale = live_root.scale
	var frame_index := int(shadow.get("frame_index", 0)) + 1
	shadow["frame_index"] = frame_index
	var viewport_rect := Rect2(Vector2.ZERO, Vector2(_width, _height)).grow(PREFETCH_MARGIN_PX)
	var visible := 0
	var resident := 0
	var resident_bytes := 0
	var tiles: Array = shadow.get("tiles", [])
	for index in range(tiles.size()):
		var entry: Dictionary = tiles[index]
		var local_rect: Rect2 = entry.get("map_rect", Rect2())
		var screen_rect := Rect2(
			shadow_root.position + local_rect.position * shadow_root.scale,
			local_rect.size * shadow_root.scale
		)
		var wanted := screen_rect.intersects(viewport_rect)
		var sprite := entry.get("sprite") as Sprite2D
		if wanted:
			entry["last_visible_frame"] = frame_index
			if sprite == null:
				var cache_rect: Rect2i = entry.get("cache_rect", Rect2i())
				var region := _cache_image.get_region(cache_rect)
				sprite = Sprite2D.new()
				sprite.centered = false
				sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
				sprite.texture = ImageTexture.create_from_image(region)
				sprite.position = Vector2(cache_rect.position) / float(CACHE_SCALE)
				sprite.scale = Vector2.ONE / float(CACHE_SCALE)
				shadow_root.add_child(sprite)
				entry["sprite"] = sprite
				shadow["created_total"] = int(shadow.get("created_total", 0)) + 1
			visible += 1
		elif sprite != null and frame_index - int(entry.get("last_visible_frame", -100000)) > LAZY_RETAIN_FRAMES:
			sprite.queue_free()
			entry["sprite"] = null
			shadow["evicted_total"] = int(shadow.get("evicted_total", 0)) + 1
			sprite = null
		if sprite != null:
			resident += 1
			resident_bytes += int(entry.get("rgba8_bytes", 0))
		tiles[index] = entry
	shadow["tiles"] = tiles
	shadow["peak_resident_tiles"] = maxi(int(shadow.get("peak_resident_tiles", 0)), resident)
	shadow["peak_resident_rgba8_bytes"] = maxi(int(shadow.get("peak_resident_rgba8_bytes", 0)), resident_bytes)
	return {"visible": visible, "resident": resident, "resident_rgba8_bytes": resident_bytes}


func _pump_lazy_frames(scene: Node, shadow: Dictionary, count: int, scenario: String) -> void:
	for i in range(count):
		_apply_scenario(scene, scenario, i, count)
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		_sync_lazy_shadow(shadow)
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _measure_lazy_matrix(scene: Node, shadow: Dictionary, scenario: String) -> Dictionary:
	var frame_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var script_ms: Array = []
	var video_mem: Array = []
	var visible_tiles: Array = []
	var resident_tiles: Array = []
	var resident_rgba8_bytes: Array = []
	for i in range(_frames):
		_apply_scenario(scene, scenario, i, _frames)
		_mark_layers_dirty(scene)
		var t0 := Time.get_ticks_usec()
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		var residency := _sync_lazy_shadow(shadow)
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		if scene.has_method("_process"):
			scene.call("_process", 0.016)
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		frame_ms.append((Time.get_ticks_usec() - t0) / 1000.0)
		draw_calls.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)))
		primitives.append(int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)))
		script_ms.append(float(Performance.get_monitor(Performance.TIME_PROCESS)) * 1000.0)
		video_mem.append(int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)))
		visible_tiles.append(int(residency.get("visible", 0)))
		resident_tiles.append(int(residency.get("resident", 0)))
		resident_rgba8_bytes.append(int(residency.get("resident_rgba8_bytes", 0)))
	return {
		"frame_time_ms": _stats(frame_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"script_cpu_ms": _stats(script_ms),
		"video_mem_bytes": _stats_int(video_mem),
		"visible_tiles": _stats_int(visible_tiles),
		"resident_tiles": _stats_int(resident_tiles),
		"resident_rgba8_bytes": _stats_int(resident_rgba8_bytes),
	}


func _capture_lazy_screenshot(reference: Dictionary) -> bool:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return false
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	if not _authority_error(scene, active_map).is_empty():
		await _dispose_scene(scene)
		return false
	var shadow := _mount_lazy_shadow(scene)
	await _pump_lazy_frames(scene, shadow, 4, "idle_full_theatre")
	var parity := _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return false
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var viewport := root as Viewport
	var image := viewport.get_texture().get_image() if viewport != null else null
	var ok := image != null and not image.is_empty()
	if ok:
		ok = image.save_png(_lazy_screens_dir.path_join("lazy_1024.png")) == OK
	await _dispose_scene(scene)
	return ok


func _real_legal_lazy_parity() -> Dictionary:
	var original_snapshot := _snapshot_path
	var original_cache := _cache_image
	_snapshot_path = _legal_snapshot_path
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		_snapshot_path = original_snapshot
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		_snapshot_path = original_snapshot
		return {"ok": false, "error": error}
	if not _prepare_nonempty_legal_targets(scene):
		await _dispose_scene(scene)
		_snapshot_path = original_snapshot
		return {"ok": false, "error": "production snapshot did not rebuild a non-empty legal-target state"}
	var reference := _authority_parity(scene, active_map)
	var legal_ids: Array = reference.get("legal_target_ids", [])
	if legal_ids.is_empty():
		await _dispose_scene(scene)
		_snapshot_path = original_snapshot
		return {"ok": false, "error": "legal target list unexpectedly empty"}
	_cache_image = await _capture_static_map(scene, active_map)
	var shadow := _mount_lazy_shadow(scene)
	if shadow.is_empty():
		await _dispose_scene(scene)
		_snapshot_path = original_snapshot
		_cache_image = original_cache
		return {"ok": false, "error": "failed to mount lazy shadow for legal parity"}
	for i in range(LEGAL_PARITY_FRAMES):
		var t := float(i) / float(maxi(LEGAL_PARITY_FRAMES - 1, 1))
		if scene.get("view_scale") != null:
			scene.view_scale = 1.25 + 0.75 * (0.5 + 0.5 * sin(t * TAU))
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2(80.0 * cos(t * TAU), 50.0 * sin(t * TAU))
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		_sync_lazy_shadow(shadow)
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var candidate := _authority_parity(scene, active_map)
	var same := _same_parity(reference, candidate)
	var residency := _residency_summary(shadow)
	await _dispose_scene(scene)
	_snapshot_path = original_snapshot
	_cache_image = original_cache
	return {
		"ok": same and not legal_ids.is_empty(),
		"legal_target_count": legal_ids.size(),
		"legal_target_ids": legal_ids,
		"selected_province_id": reference.get("selected_province_id", ""),
		"exact_identity": same,
		"polygon_backend_live": true,
		"residency": residency,
		"source": "production player-shell snapshot operational_orders",
	}


func _residency_summary(shadow: Dictionary) -> Dictionary:
	var resident := 0
	var resident_bytes := 0
	for entry_value in shadow.get("tiles", []):
		var entry: Dictionary = entry_value
		if entry.get("sprite") as Sprite2D != null:
			resident += 1
			resident_bytes += int(entry.get("rgba8_bytes", 0))
	return {
		"resident_tiles_end": resident,
		"resident_rgba8_bytes_end": resident_bytes,
		"peak_resident_tiles": int(shadow.get("peak_resident_tiles", 0)),
		"peak_resident_rgba8_bytes": int(shadow.get("peak_resident_rgba8_bytes", 0)),
		"created_total": int(shadow.get("created_total", 0)),
		"evicted_total": int(shadow.get("evicted_total", 0)),
	}


func _total_tile_count() -> int:
	return int(ceili(float(_cache_image.get_width()) / float(LAZY_TILE_SIZE))) \
		* int(ceili(float(_cache_image.get_height()) / float(LAZY_TILE_SIZE)))
