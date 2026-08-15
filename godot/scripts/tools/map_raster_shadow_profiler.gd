extends "res://scripts/tools/map_production_layer_attribution_profiler.gd"

## #212 Phase B: debug-only static raster shadow matrix.
##
## The production PolygonMap remains loaded and authoritative. This profiler only
## swaps presentation: a cache derived from Earth3PolygonRoot is shown while the
## live root is hidden. Picking, stable IDs, water policy, ownership records,
## selection/legal-target identity, and anchors continue to come from PolygonMap.

const CACHE_SCALE := 2
const MATRIX_FRAMES := 16
const MATRIX_WARMUP := 4
const MAX_BASELINE_DRIFT_RATIO := 0.15
const MODES := [
	{"name": "full_cache", "tile": 0},
	{"name": "tile_512", "tile": 512},
	{"name": "tile_1024", "tile": 1024},
]
const SCENARIOS := ["idle_full_theatre", "continuous_pan", "continuous_zoom"]
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}

var _screens_dir := "user://issue212-raster-shadow-screens"
var _cache_image: Image = null
var _authority_before: Dictionary = {}


func _initialize() -> void:
	_snapshot_path = DEFAULT_SNAPSHOT
	_fixture_path = DEFAULT_FIXTURE
	_manifest_path = DEFAULT_MANIFEST
	_frames = MATRIX_FRAMES
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--screens-dir="):
			_screens_dir = text.substr(14).strip_edges()
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
			_frames = maxi(int(text.substr(9)), 8)
	call_deferred("_run_matrix")


func _run_matrix() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for path in [_snapshot_path, _fixture_path, _manifest_path]:
		if not FileAccess.file_exists(String(path)):
			_fail("required input missing: %s" % String(path))
			return

	_authority_before = _authority_hashes()
	var source_result := await _build_scene()
	if not bool(source_result.get("ok", false)):
		_fail("cache source scene failed: %s" % source_result.get("error", "unknown"))
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
		_fail("reference authority parity failed: %s" % JSON.stringify(reference_parity))
		return
	_cache_image = await _capture_static_map(source_scene, source_map)
	await _dispose_scene(source_scene)
	if _cache_image == null or _cache_image.is_empty():
		_fail("static cache capture empty")
		return

	DirAccess.make_dir_recursive_absolute(_screens_dir)
	var screenshot_ok := await _capture_mode_screenshot("polygon", 0, reference_parity)
	if not screenshot_ok:
		_fail("polygon screenshot failed")
		return

	var mode_results: Dictionary = {}
	for mode_def_value in MODES:
		var mode_def: Dictionary = mode_def_value
		var mode_name := String(mode_def.get("name", ""))
		var tile_size := int(mode_def.get("tile", 0))
		if not await _capture_mode_screenshot(mode_name, tile_size, reference_parity):
			_fail("screenshot/parity failed for %s" % mode_name)
			return
		var scenarios: Dictionary = {}
		for scenario_value in SCENARIOS:
			var scenario := String(scenario_value)
			var bracket := await _measure_bracket(mode_name, tile_size, scenario, reference_parity)
			if not bool(bracket.get("ok", false)):
				_fail("bracket failed mode=%s scenario=%s detail=%s" % [mode_name, scenario, JSON.stringify(bracket)])
				return
			scenarios[scenario] = bracket
		mode_results[mode_name] = {
			"tile_size_px": tile_size,
			"cache_scale": CACHE_SCALE,
			"cache_texture_size": {"width": _cache_image.get_width(), "height": _cache_image.get_height()},
			"scenarios": scenarios,
		}

	var owner_refresh := await _owner_refresh_check()
	if not bool(owner_refresh.get("ok", false)):
		_fail("owner refresh check failed: %s" % JSON.stringify(owner_refresh))
		return

	var authority_after := _authority_hashes()
	if authority_after != _authority_before:
		_fail("authority bytes changed during matrix")
		return

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-raster-shadow",
		"schema_version": 2,
		"issue": 212,
		"phase": "B-debug-shadow",
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": RenderingServer.get_video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"frames_per_sample": _frames,
		"cache": {
			"scale": CACHE_SCALE,
			"width": _cache_image.get_width(),
			"height": _cache_image.get_height(),
			"bytes_rgba8": _cache_image.get_width() * _cache_image.get_height() * 4,
			"source": "isolated duplicate of live Earth3PolygonRoot",
			"persistent": false,
			"campaign_authority": false,
		},
		"map": {
			"map_id": "earth3_europe_mediterranean",
			"province_count": 3514,
			"production_renderer": "polygon_mesh",
		},
		"control": {
			"design": "polygon_before -> cache_mode -> polygon_after",
			"local_baseline": "arithmetic midpoint of surrounding polygon samples",
			"max_baseline_drift_ratio": MAX_BASELINE_DRIFT_RATIO,
		},
		"authority": {
			"unchanged": true,
			"hashes_before": _authority_before,
			"hashes_after": authority_after,
			"polygon_backend_remains_live": true,
			"cache_is_presentation_only": true,
		},
		"reference_parity": reference_parity,
		"owner_refresh_parity": owner_refresh,
		"modes": mode_results,
		"screenshots": ["polygon.png", "full_cache.png", "tile_512.png", "tile_1024.png"],
		"notes": [
			"Sparse dynamic overlays remain live and are not baked into the static cache.",
			"512/1024 tiles are map-space slices of the same 2x static cache and are culled against the viewport after applying the live PolygonMap transform.",
			"Every performance comparison uses fresh scenes inside one Godot process and a local before/after polygon bracket.",
			"Absolute CI frame time is llvmpipe evidence only, not owner-native acceptance.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_RASTER_SHADOW %s" % JSON.stringify(_summary(result)))
	print("map_raster_shadow_profiler: PASS out=%s screens=%s" % [_out_path, _screens_dir])
	quit(0)


func _authority_error(scene: Node, active_map) -> String:
	if active_map == null or not bool(active_map.is_ready):
		return "Earth3 map backend not ready"
	if not bool(scene.get("map_backend_is_polygon")):
		return "expected polygon authority backend"
	if int(active_map.province_count) != 3514:
		return "Earth3 authority changed: province_count=%s" % int(active_map.province_count)
	return ""


func _capture_static_map(scene: Node, active_map) -> Image:
	var live_root := scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if live_root == null:
		return null
	var map_size := Vector2i(int(active_map.image_size().x), int(active_map.image_size().y))
	var viewport := SubViewport.new()
	viewport.size = map_size * CACHE_SCALE
	viewport.transparent_bg = true
	viewport.disable_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ONCE
	var duplicate_root := live_root.duplicate() as Node2D
	if duplicate_root == null:
		return null
	duplicate_root.position = Vector2.ZERO
	duplicate_root.scale = Vector2(CACHE_SCALE, CACHE_SCALE)
	viewport.add_child(duplicate_root)
	root.add_child(viewport)
	await process_frame
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var image := viewport.get_texture().get_image()
	var copy: Image = image.duplicate() if image != null and not image.is_empty() else null
	viewport.queue_free()
	await process_frame
	return copy


func _capture_mode_screenshot(mode_name: String, tile_size: int, reference: Dictionary) -> bool:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return false
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	if not _authority_error(scene, active_map).is_empty():
		await _dispose_scene(scene)
		return false
	var shadow := {}
	if mode_name != "polygon":
		shadow = _mount_shadow(scene, tile_size)
		if shadow.is_empty():
			await _dispose_scene(scene)
			return false
	await _pump_matrix_frames(scene, shadow, 3, "idle_full_theatre")
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
		var path := _screens_dir.path_join("%s.png" % mode_name)
		ok = image.save_png(path) == OK
	await _dispose_scene(scene)
	return ok


func _measure_bracket(mode_name: String, tile_size: int, scenario: String, reference: Dictionary) -> Dictionary:
	var before := await _measure_one("polygon", 0, scenario, reference)
	if not bool(before.get("ok", false)):
		return before
	var cached := await _measure_one(mode_name, tile_size, scenario, reference)
	if not bool(cached.get("ok", false)):
		return cached
	var after := await _measure_one("polygon", 0, scenario, reference)
	if not bool(after.get("ok", false)):
		return after

	var bm: Dictionary = before.get("metrics", {})
	var cm: Dictionary = cached.get("metrics", {})
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
		"cache": cm,
		"polygon_after": am,
		"local_polygon_baseline": local,
		"baseline_drift": drift,
		"delta": {
			"frame_ms_p50": snappedf(float(local["frame_time_ms"]["p50"]) - float(cm["frame_time_ms"]["p50"]), 0.001),
			"frame_ms_p95": snappedf(float(local["frame_time_ms"]["p95"]) - float(cm["frame_time_ms"]["p95"]), 0.001),
			"draw_calls_p50": int(local["draw_calls"]["p50"]) - int(cm["draw_calls"]["p50"]),
			"primitives_p50": int(local["primitives"]["p50"]) - int(cm["primitives"]["p50"]),
		},
	}


func _measure_one(mode_name: String, tile_size: int, scenario: String, reference: Dictionary) -> Dictionary:
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
	await _pump_matrix_frames(scene, shadow, MATRIX_WARMUP, scenario)
	var parity := _authority_parity(scene, active_map)
	if not _same_parity(reference, parity):
		await _dispose_scene(scene)
		return {"ok": false, "error": "authority parity changed", "parity": parity}
	var metrics := await _measure_matrix(scene, shadow, scenario)
	await _dispose_scene(scene)
	return {"ok": true, "metrics": metrics, "parity": parity}


func _mount_shadow(scene: Node, tile_size: int) -> Dictionary:
	var live_root := scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if live_root == null:
		return {}
	live_root.visible = false
	var shadow_root := Node2D.new()
	shadow_root.name = "Issue212RasterShadow"
	shadow_root.z_index = -15
	scene.add_child(shadow_root)
	var tiles: Array = []
	if tile_size <= 0:
		var sprite := Sprite2D.new()
		sprite.centered = false
		sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		sprite.texture = ImageTexture.create_from_image(_cache_image)
		sprite.scale = Vector2.ONE / float(CACHE_SCALE)
		shadow_root.add_child(sprite)
		tiles.append({
			"sprite": sprite,
			"map_rect": Rect2(Vector2.ZERO, Vector2(_cache_image.get_width(), _cache_image.get_height()) / float(CACHE_SCALE)),
		})
	else:
		for y in range(0, _cache_image.get_height(), tile_size):
			for x in range(0, _cache_image.get_width(), tile_size):
				var w := mini(tile_size, _cache_image.get_width() - x)
				var h := mini(tile_size, _cache_image.get_height() - y)
				var sprite := Sprite2D.new()
				sprite.centered = false
				sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
				sprite.texture = ImageTexture.create_from_image(_cache_image.get_region(Rect2i(x, y, w, h)))
				sprite.position = Vector2(x, y) / float(CACHE_SCALE)
				sprite.scale = Vector2.ONE / float(CACHE_SCALE)
				shadow_root.add_child(sprite)
				tiles.append({
					"sprite": sprite,
					"map_rect": Rect2(Vector2(x, y) / float(CACHE_SCALE), Vector2(w, h) / float(CACHE_SCALE)),
				})
	var shadow := {"root": shadow_root, "live": live_root, "tiles": tiles, "tile_size": tile_size}
	_sync_shadow(shadow)
	return shadow


func _sync_shadow(shadow: Dictionary) -> int:
	if shadow.is_empty():
		return 0
	var shadow_root := shadow.get("root") as Node2D
	var live_root := shadow.get("live") as Node2D
	if shadow_root == null or live_root == null:
		return 0
	shadow_root.position = live_root.position
	shadow_root.scale = live_root.scale
	var viewport_rect := Rect2(Vector2.ZERO, Vector2(_width, _height))
	var visible := 0
	for entry_value in shadow.get("tiles", []):
		var entry: Dictionary = entry_value
		var sprite := entry.get("sprite") as Sprite2D
		if sprite == null:
			continue
		var show := true
		if int(shadow.get("tile_size", 0)) > 0:
			var local_rect: Rect2 = entry.get("map_rect", Rect2())
			var screen_rect := Rect2(
				shadow_root.position + local_rect.position * shadow_root.scale,
				local_rect.size * shadow_root.scale
			)
			show = screen_rect.intersects(viewport_rect)
		sprite.visible = show
		if show:
			visible += 1
	return visible


func _pump_matrix_frames(scene: Node, shadow: Dictionary, count: int, scenario: String) -> void:
	for i in range(count):
		_apply_scenario(scene, scenario, i, count)
		_mark_layers_dirty(scene)
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		_sync_shadow(shadow)
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _measure_matrix(scene: Node, shadow: Dictionary, scenario: String) -> Dictionary:
	var frame_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var script_ms: Array = []
	var video_mem: Array = []
	var visible_tiles: Array = []
	for i in range(_frames):
		_apply_scenario(scene, scenario, i, _frames)
		_mark_layers_dirty(scene)
		var t0 := Time.get_ticks_usec()
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		var visible := _sync_shadow(shadow)
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
		visible_tiles.append(visible)
	return {
		"frame_time_ms": _stats(frame_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"script_cpu_ms": _stats(script_ms),
		"video_mem_bytes": _stats_int(video_mem),
		"visible_tiles": _stats_int(visible_tiles),
	}


func _apply_scenario(scene: Node, scenario: String, i: int, total: int) -> void:
	if scenario == "idle_full_theatre":
		return
	var t := float(i) / float(maxi(total - 1, 1))
	if scenario == "continuous_pan":
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0)
	elif scenario == "continuous_zoom":
		if scene.get("view_scale") != null:
			scene.view_scale = lerpf(1.0, 4.0, 0.5 + 0.5 * sin(t * TAU))
		if scene.get("view_offset") != null:
			scene.view_offset = Vector2(cos(t * TAU) * 40.0, sin(t * TAU) * 30.0)


func _authority_parity(scene: Node, active_map) -> Dictionary:
	var picks := _pick_suite(active_map)
	var picks_ok := true
	for row_value in picks:
		picks_ok = picks_ok and bool((row_value as Dictionary).get("match", false))
	var water_id := ""
	var water_pick := ""
	for i in range(active_map.is_water.size()):
		if int(active_map.is_water[i]) == 1:
			water_id = String(active_map.province_by_index[i])
			water_pick = String(active_map.province_at_image_pos(active_map.centroids[i]))
			break
	var legal_ids: Array = []
	var legal_value: Variant = scene.get("legal_targets")
	if legal_value is Dictionary:
		legal_ids = (legal_value as Dictionary).keys()
		legal_ids.sort()
	var anchors := {}
	for row_value in picks:
		var pid := String((row_value as Dictionary).get("expected", ""))
		var anchor: Vector2 = active_map.anchor_pixel(pid)
		anchors[pid] = [snappedf(anchor.x, 0.001), snappedf(anchor.y, 0.001)]
	return {
		"ok": picks_ok and not water_id.is_empty() and water_pick != water_id,
		"picks": picks,
		"water_id": water_id,
		"water_pick": water_pick,
		"water_not_selectable": water_pick != water_id,
		"selected_province_id": String(scene.get("selected_province_id") if scene.get("selected_province_id") != null else ""),
		"legal_target_ids": legal_ids,
		"anchors": anchors,
	}


func _same_parity(reference: Dictionary, candidate: Dictionary) -> bool:
	return bool(candidate.get("ok", false)) \
		and candidate.get("picks", []) == reference.get("picks", []) \
		and candidate.get("water_id", "") == reference.get("water_id", "") \
		and candidate.get("water_pick", "") == reference.get("water_pick", "") \
		and candidate.get("selected_province_id", "") == reference.get("selected_province_id", "") \
		and candidate.get("legal_target_ids", []) == reference.get("legal_target_ids", []) \
		and candidate.get("anchors", {}) == reference.get("anchors", {})


func _owner_refresh_check() -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}
	var target := -1
	for i in range(active_map.is_water.size()):
		if int(active_map.is_water[i]) == 0:
			target = i
			break
	if target < 0:
		await _dispose_scene(scene)
		return {"ok": false, "error": "no land province"}
	var before := await _capture_static_map(scene, active_map)
	var snapshot_copy: Dictionary = scene.snapshot.duplicate(true)
	var provinces: Array = snapshot_copy.get("provinces", [])
	var pid := String(active_map.province_by_index[target])
	var old_owner := ""
	var new_owner := ""
	for j in range(provinces.size()):
		var row: Dictionary = provinces[j]
		if String(row.get("id", "")) == pid:
			old_owner = String(row.get("owner", "neutral"))
			new_owner = "rusa" if old_owner != "rusa" else "nato"
			row["owner"] = new_owner
			provinces[j] = row
			break
	if new_owner.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": "province missing from snapshot", "province_id": pid}
	snapshot_copy["provinces"] = provinces
	scene.snapshot = snapshot_copy
	active_map.refresh_snapshot(scene.snapshot, FACTION_COLORS)
	await _pump_frames(scene, 2)
	var after := await _capture_static_map(scene, active_map)
	var pos := Vector2i(
		clampi(int(round(active_map.centroids[target].x * CACHE_SCALE)), 0, before.get_width() - 1),
		clampi(int(round(active_map.centroids[target].y * CACHE_SCALE)), 0, before.get_height() - 1)
	)
	var a := before.get_pixelv(pos)
	var b := after.get_pixelv(pos)
	var color_delta := absf(a.r - b.r) + absf(a.g - b.g) + absf(a.b - b.b) + absf(a.a - b.a)
	var owner_ok := String(active_map.owners[target]) == new_owner
	await _dispose_scene(scene)
	return {
		"ok": owner_ok and color_delta > 0.01,
		"province_id": pid,
		"old_owner": old_owner,
		"new_owner": new_owner,
		"polygon_owner_state_applied": owner_ok,
		"cached_pixel_delta": snappedf(color_delta, 0.0001),
		"cached_pixel_changed": color_delta > 0.01,
	}


func _authority_hashes() -> Dictionary:
	var dataset_path := ""
	var file := FileAccess.open(_manifest_path, FileAccess.READ)
	if file != null:
		var parsed: Variant = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			var polygon_value: Variant = (parsed as Dictionary).get("polygon_dataset", {})
			if polygon_value is Dictionary:
				var rel := String((polygon_value as Dictionary).get("path", "polygon_dataset.json"))
				dataset_path = _manifest_path.get_base_dir().path_join(rel)
	return {
		"manifest_sha256": FileAccess.get_sha256(_manifest_path),
		"polygon_dataset_sha256": FileAccess.get_sha256(dataset_path) if not dataset_path.is_empty() else "",
		"snapshot_fixture_sha256": FileAccess.get_sha256(_snapshot_path),
	}


func _midpoint_metrics(a: Dictionary, b: Dictionary) -> Dictionary:
	var out := {}
	for metric_value in ["frame_time_ms", "draw_calls", "primitives", "script_cpu_ms", "video_mem_bytes"]:
		var metric := String(metric_value)
		var av: Dictionary = a.get(metric, {})
		var bv: Dictionary = b.get(metric, {})
		var row := {}
		for stat_value in ["count", "avg", "p50", "p95", "max", "min"]:
			var stat := String(stat_value)
			row[stat] = (float(av.get(stat, 0.0)) + float(bv.get(stat, 0.0))) * 0.5
		out[metric] = row
	return out


func _baseline_drift(a: Dictionary, b: Dictionary) -> Dictionary:
	var a50 := float(a.get("frame_time_ms", {}).get("p50", 0.0))
	var b50 := float(b.get("frame_time_ms", {}).get("p50", 0.0))
	var a95 := float(a.get("frame_time_ms", {}).get("p95", 0.0))
	var b95 := float(b.get("frame_time_ms", {}).get("p95", 0.0))
	return {
		"frame_ms_p50_abs": snappedf(absf(a50 - b50), 0.001),
		"frame_ms_p50_ratio": snappedf(absf(a50 - b50) / maxf((a50 + b50) * 0.5, 0.001), 0.0001),
		"frame_ms_p95_abs": snappedf(absf(a95 - b95), 0.001),
		"frame_ms_p95_ratio": snappedf(absf(a95 - b95) / maxf((a95 + b95) * 0.5, 0.001), 0.0001),
		"draw_calls_p50_abs": absi(int(a.get("draw_calls", {}).get("p50", 0)) - int(b.get("draw_calls", {}).get("p50", 0))),
		"primitives_p50_abs": absi(int(a.get("primitives", {}).get("p50", 0)) - int(b.get("primitives", {}).get("p50", 0))),
	}


func _summary(result: Dictionary) -> Dictionary:
	var out := {}
	var modes: Dictionary = result.get("modes", {})
	for mode_value in modes.keys():
		var mode := String(mode_value)
		var scenarios: Dictionary = modes[mode].get("scenarios", {})
		var rows := {}
		for scenario_value in scenarios.keys():
			var scenario := String(scenario_value)
			rows[scenario] = scenarios[scenario].get("delta", {})
		out[mode] = rows
	return out
