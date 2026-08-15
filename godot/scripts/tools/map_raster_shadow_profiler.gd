extends SceneTree

## #212 Phase B debug-only raster/tiled presentation shadow profiler.
##
## This tooling never changes Earth3 authority. It keeps the production PolygonMap
## alive for picking/selection/ownership state, hides only Earth3PolygonRoot while a
## derived static cache is visible, and leaves sparse/dynamic overlays on main.tscn.
##
## Evaluated steady-state presentation modes:
##   polygon_mesh   - current production static polygon presentation
##   full_cache     - one 2x full-theatre cached texture
##   tile_512       - same cache split into 512px tiles with viewport culling
##   tile_1024      - same cache split into 1024px tiles with viewport culling
##
## Every cache/scenario measurement is bracketed:
##   polygon_before -> cache_mode -> polygon_after
## and frame deltas use the midpoint of the two local polygon baselines.

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/e3_operational.json"
const DEFAULT_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const CACHE_SCALE := 2
const WARMUP_FRAMES := 4
const DEFAULT_FRAMES := 16
const MAX_BASELINE_DRIFT_RATIO := 0.15
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}

var _out_path := ""
var _screens_dir := ""
var _snapshot_path := DEFAULT_SNAPSHOT
var _fixture_path := DEFAULT_FIXTURE
var _manifest_path := DEFAULT_MANIFEST
var _width := 1920
var _height := 1080
var _frames := DEFAULT_FRAMES
var _scene: Node = null
var _cache_image: Image = null
var _shadow_root: Node2D = null
var _shadow_tiles: Array = []
var _live_root: Node2D = null
var _active_shadow_mode := "polygon_mesh"
var _authority_hashes_before: Dictionary = {}
var _authority_hashes_after: Dictionary = {}


func _initialize() -> void:
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
	if _out_path.is_empty():
		_out_path = "user://issue212-raster-shadow.json"
	if _screens_dir.is_empty():
		_screens_dir = "user://issue212-raster-shadow-screens"
	call_deferred("_run")


func _run() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for path in [_snapshot_path, _fixture_path, _manifest_path]:
		if not FileAccess.file_exists(String(path)):
			_fail("missing input: %s" % String(path))
			return

	_authority_hashes_before = _authority_hashes()
	var packed := load("res://main.tscn")
	if packed == null:
		_fail("failed to load main.tscn")
		return
	_scene = packed.instantiate()
	root.add_child(_scene)
	if _scene.get("snapshot_source_path") != null:
		_scene.snapshot_source_path = _snapshot_path
	if _scene.has_method("_load_snapshot"):
		_scene.call("_load_snapshot", _snapshot_path)
	if not str(_scene.get("load_error") if _scene.get("load_error") != null else "").is_empty():
		_fail("snapshot load_error=%s" % str(_scene.load_error))
		return
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
	_mark_layers_dirty()
	await _pump_frames(WARMUP_FRAMES, Callable())

	var am = _active_map()
	if am == null or not bool(am.is_ready):
		_fail("Earth3 map backend not ready")
		return
	if not bool(_scene.get("map_backend_is_polygon")):
		_fail("expected Earth3 polygon backend")
		return
	if int(am.province_count) != 3514:
		_fail("province authority mismatch: %s" % str(am.province_count))
		return

	_live_root = _scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if _live_root == null:
		_fail("Earth3PolygonRoot missing")
		return

	var parity_before := _capture_parity(am)
	if not bool(parity_before.get("ok", false)):
		_fail("pre-cache parity failed: %s" % JSON.stringify(parity_before))
		return

	_cache_image = await _render_static_cache_image()
	if _cache_image == null or _cache_image.is_empty():
		_fail("failed to derive static presentation cache")
		return

	DirAccess.make_dir_recursive_absolute(_screens_dir)
	_set_polygon_mode()
	_reset_home_view()
	await _pump_frames(2, Callable())
	_capture_screen(_screens_dir.path_join("polygon.png"))

	var modes: Dictionary = {}
	for mode_def in [
		{"name": "full_cache", "tile": 0},
		{"name": "tile_512", "tile": 512},
		{"name": "tile_1024", "tile": 1024},
	]:
		var mode_name := String(mode_def["name"])
		var tile_size := int(mode_def["tile"])
		var built := _build_shadow(mode_name, tile_size)
		if not built:
			_fail("failed to build shadow mode %s" % mode_name)
			return
		_set_shadow_mode(mode_name)
		_reset_home_view()
		await _pump_frames(2, Callable())
		_capture_screen(_screens_dir.path_join("%s.png" % mode_name))
		var parity_mode := _capture_parity(am)
		if not bool(parity_mode.get("ok", false)):
			_fail("parity failed in %s: %s" % [mode_name, JSON.stringify(parity_mode)])
			return

		var scenarios: Dictionary = {}
		for scenario_name in ["idle_full_theatre", "continuous_pan", "continuous_zoom"]:
			var bracket := await _measure_bracket(mode_name, String(scenario_name))
			if not bool(bracket.get("ok", false)):
				_fail("measurement bracket failed mode=%s scenario=%s detail=%s" % [mode_name, scenario_name, JSON.stringify(bracket)])
				return
			scenarios[String(scenario_name)] = bracket
		modes[mode_name] = {
			"tile_size_px": tile_size,
			"cache_scale": CACHE_SCALE,
			"cache_texture_size": {"width": _cache_image.get_width(), "height": _cache_image.get_height()},
			"tile_count": _shadow_tiles.size(),
			"visible_tiles_home": _visible_tile_count(),
			"scenarios": scenarios,
			"parity": parity_mode,
		}
		_destroy_shadow()

	_set_polygon_mode()
	_reset_home_view()
	await _pump_frames(2, Callable())
	var owner_refresh := await _owner_refresh_parity(am)
	if not bool(owner_refresh.get("ok", false)):
		_fail("owner refresh parity failed: %s" % JSON.stringify(owner_refresh))
		return
	var parity_after := _capture_parity(am)
	_authority_hashes_after = _authority_hashes()
	var hashes_ok := _authority_hashes_before == _authority_hashes_after
	if not hashes_ok:
		_fail("authority bytes changed during debug-only profiler")
		return

	var result := {
		"schema": "gates-of-codex.issue-212-raster-shadow",
		"schema_version": 1,
		"issue": 212,
		"phase": "B-debug-shadow",
		"ok": true,
		"godot_version": Engine.get_version_info(),
		"os": OS.get_name(),
		"video_adapter": RenderingServer.get_video_adapter_name(),
		"viewport": {"width": _width, "height": _height},
		"frames_per_sample": _frames,
		"warmup_frames": WARMUP_FRAMES,
		"cache_scale": CACHE_SCALE,
		"cache_source": "duplicate of live Earth3PolygonRoot rendered once into an isolated SubViewport",
		"map": {
			"map_id": String(am.map_id),
			"province_count": int(am.province_count),
			"image_width": int(am.image_size().x),
			"image_height": int(am.image_size().y),
			"production_renderer": String(am.renderer_name),
		},
		"control": {
			"design": "polygon_before -> cache_mode -> polygon_after",
			"local_baseline": "arithmetic midpoint of surrounding polygon statistics",
			"max_baseline_drift_ratio": MAX_BASELINE_DRIFT_RATIO,
		},
		"authority": {
			"hashes_before": _authority_hashes_before,
			"hashes_after": _authority_hashes_after,
			"unchanged": hashes_ok,
			"polygon_backend_remains_live": true,
			"cache_is_presentation_only": true,
		},
		"parity_before": parity_before,
		"parity_after": parity_after,
		"owner_refresh_parity": owner_refresh,
		"modes": modes,
		"screenshots": ["polygon.png", "full_cache.png", "tile_512.png", "tile_1024.png"],
		"notes": [
			"No production renderer switch is made by this profiler.",
			"Earth3 PolygonMap remains instantiated and authoritative for picking, stable IDs, owner state, legal-target identity and anchors while cached presentation is visible.",
			"Sparse dynamic overlays remain on main.tscn and are not baked into the static cache.",
			"2x cache resolution gives 512 and 1024 tile modes multiple tiles on the current Earth3 theatre while keeping all modes visually comparable.",
			"Absolute llvmpipe frame times are not owner-native acceptance targets; local bracket deltas are experimental evidence.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_RASTER_SHADOW %s" % JSON.stringify(_compact_summary(result)))
	print("map_raster_shadow_profiler: PASS out=%s screens=%s" % [_out_path, _screens_dir])
	_cleanup_and_quit(0)


func _render_static_cache_image() -> Image:
	var am = _active_map()
	var map_size := Vector2i(int(am.image_size().x), int(am.image_size().y))
	var viewport := SubViewport.new()
	viewport.name = "Issue212StaticCacheViewport"
	viewport.size = map_size * CACHE_SCALE
	viewport.transparent_bg = true
	viewport.disable_3d = true
	viewport.render_target_update_mode = SubViewport.UPDATE_ONCE
	var duplicate_root := _live_root.duplicate()
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
	viewport.queue_free()
	await process_frame
	return image


func _build_shadow(mode_name: String, tile_size: int) -> bool:
	_destroy_shadow()
	if _cache_image == null or _cache_image.is_empty():
		return false
	_shadow_root = Node2D.new()
	_shadow_root.name = "Issue212RasterShadow"
	_shadow_root.z_index = -15
	_scene.add_child(_shadow_root)
	_shadow_tiles.clear()
	if tile_size <= 0:
		var texture := ImageTexture.create_from_image(_cache_image)
		var sprite := Sprite2D.new()
		sprite.centered = false
		sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
		sprite.texture = texture
		sprite.scale = Vector2.ONE / float(CACHE_SCALE)
		_shadow_root.add_child(sprite)
		_shadow_tiles.append({"sprite": sprite, "map_rect": Rect2(Vector2.ZERO, Vector2(_cache_image.get_size()) / float(CACHE_SCALE))})
	else:
		for y in range(0, _cache_image.get_height(), tile_size):
			for x in range(0, _cache_image.get_width(), tile_size):
				var w := mini(tile_size, _cache_image.get_width() - x)
				var h := mini(tile_size, _cache_image.get_height() - y)
				var region := _cache_image.get_region(Rect2i(x, y, w, h))
				var texture := ImageTexture.create_from_image(region)
				var sprite := Sprite2D.new()
				sprite.centered = false
				sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
				sprite.texture = texture
				sprite.position = Vector2(x, y) / float(CACHE_SCALE)
				sprite.scale = Vector2.ONE / float(CACHE_SCALE)
				_shadow_root.add_child(sprite)
				_shadow_tiles.append({
					"sprite": sprite,
					"map_rect": Rect2(Vector2(x, y) / float(CACHE_SCALE), Vector2(w, h) / float(CACHE_SCALE)),
				})
	_shadow_root.visible = false
	_active_shadow_mode = mode_name
	_sync_shadow_transform_and_cull()
	return true


func _destroy_shadow() -> void:
	if _shadow_root != null and is_instance_valid(_shadow_root):
		_shadow_root.queue_free()
	_shadow_root = null
	_shadow_tiles.clear()
	_active_shadow_mode = "polygon_mesh"
	if _live_root != null and is_instance_valid(_live_root):
		_live_root.visible = true


func _set_polygon_mode() -> void:
	_active_shadow_mode = "polygon_mesh"
	if _live_root != null and is_instance_valid(_live_root):
		_live_root.visible = true
	if _shadow_root != null and is_instance_valid(_shadow_root):
		_shadow_root.visible = false


func _set_shadow_mode(mode_name: String) -> void:
	_active_shadow_mode = mode_name
	if _live_root != null and is_instance_valid(_live_root):
		_live_root.visible = false
	if _shadow_root != null and is_instance_valid(_shadow_root):
		_shadow_root.visible = true
	_sync_shadow_transform_and_cull()


func _sync_shadow_transform_and_cull() -> void:
	if _shadow_root == null or not is_instance_valid(_shadow_root):
		return
	if _live_root == null or not is_instance_valid(_live_root):
		return
	_shadow_root.position = _live_root.position
	_shadow_root.scale = _live_root.scale
	var viewport_rect := Rect2(Vector2.ZERO, Vector2(_width, _height))
	for entry_value in _shadow_tiles:
		var entry: Dictionary = entry_value
		var sprite := entry.get("sprite") as Sprite2D
		if sprite == null:
			continue
		if _active_shadow_mode == "full_cache":
			sprite.visible = true
			continue
		var local_rect: Rect2 = entry.get("map_rect", Rect2())
		var screen_pos := _shadow_root.position + local_rect.position * _shadow_root.scale
		var screen_size := local_rect.size * _shadow_root.scale
		var screen_rect := Rect2(screen_pos, screen_size)
		sprite.visible = screen_rect.intersects(viewport_rect)


func _visible_tile_count() -> int:
	var count := 0
	for entry_value in _shadow_tiles:
		var sprite := (entry_value as Dictionary).get("sprite") as Sprite2D
		if sprite != null and sprite.visible:
			count += 1
	return count


func _measure_bracket(mode_name: String, scenario_name: String) -> Dictionary:
	_reset_home_view()
	_set_polygon_mode()
	var before := await _measure_scenario("%s/%s/polygon_before" % [mode_name, scenario_name], scenario_name)
	_reset_home_view()
	_set_shadow_mode(mode_name)
	var cached := await _measure_scenario("%s/%s/cache" % [mode_name, scenario_name], scenario_name)
	_reset_home_view()
	_set_polygon_mode()
	var after := await _measure_scenario("%s/%s/polygon_after" % [mode_name, scenario_name], scenario_name)
	var local := _midpoint_stats(before, after)
	var drift := _baseline_drift(before, after)
	var drift_ok := float(drift.get("frame_ms_p50_ratio", 1.0)) <= MAX_BASELINE_DRIFT_RATIO \
		and float(drift.get("frame_ms_p95_ratio", 1.0)) <= MAX_BASELINE_DRIFT_RATIO \
		and int(drift.get("draw_calls_p50_abs", 1)) == 0 \
		and int(drift.get("primitives_p50_abs", 1)) == 0
	return {
		"ok": drift_ok,
		"polygon_before": before,
		"cache": cached,
		"polygon_after": after,
		"local_polygon_baseline": local,
		"baseline_drift": drift,
		"delta": {
			"frame_ms_p50": snappedf(float(local["frame_time_ms"]["p50"]) - float(cached["frame_time_ms"]["p50"]), 0.001),
			"frame_ms_p95": snappedf(float(local["frame_time_ms"]["p95"]) - float(cached["frame_time_ms"]["p95"]), 0.001),
			"draw_calls_p50": int(local["draw_calls"]["p50"]) - int(cached["draw_calls"]["p50"]),
			"primitives_p50": int(local["primitives"]["p50"]) - int(cached["primitives"]["p50"]),
			"video_mem_bytes_p50": int(cached["video_mem_bytes"]["p50"]) - int(local["video_mem_bytes"]["p50"]),
		},
	}


func _measure_scenario(label: String, scenario_name: String) -> Dictionary:
	var frame_ms: Array = []
	var script_ms: Array = []
	var draw_calls: Array = []
	var primitives: Array = []
	var nodes: Array = []
	var objects: Array = []
	var tex_mem: Array = []
	var video_mem: Array = []

	for w in range(2):
		_apply_scenario(scenario_name, w)
		await _pump_frames(1, Callable())

	for i in range(_frames):
		_apply_scenario(scenario_name, i)
		_mark_layers_dirty()
		var t0 := Time.get_ticks_usec()
		if _scene.has_method("_sync_presentation_layers"):
			_scene.call("_sync_presentation_layers")
		_sync_shadow_transform_and_cull()
		if _scene.has_method("queue_redraw"):
			_scene.queue_redraw()
		if _scene.has_method("_process"):
			_scene.call("_process", 0.016)
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		frame_ms.append((Time.get_ticks_usec() - t0) / 1000.0)
		var snap := _sample_performance()
		script_ms.append(float(snap["script_cpu_ms"]))
		draw_calls.append(int(snap["draw_calls"]))
		primitives.append(int(snap["primitives"]))
		nodes.append(int(snap["node_count"]))
		objects.append(int(snap["object_count"]))
		tex_mem.append(int(snap["texture_mem_bytes"]))
		video_mem.append(int(snap["video_mem_bytes"]))

	var result := {
		"frames": _frames,
		"frame_time_ms": _stats(frame_ms),
		"script_cpu_ms": _stats(script_ms),
		"draw_calls": _stats_int(draw_calls),
		"primitives": _stats_int(primitives),
		"node_count": _stats_int(nodes),
		"object_count": _stats_int(objects),
		"texture_mem_bytes": _stats_int(tex_mem),
		"video_mem_bytes": _stats_int(video_mem),
		"visible_tiles_end": _visible_tile_count(),
	}
	print("map_raster_shadow_profiler: sample=%s frame_p50=%.3f frame_p95=%.3f draws=%s prim=%s tiles=%s" % [
		label,
		float(result["frame_time_ms"]["p50"]),
		float(result["frame_time_ms"]["p95"]),
		str(result["draw_calls"]["p50"]),
		str(result["primitives"]["p50"]),
		str(result["visible_tiles_end"]),
	])
	return result


func _apply_scenario(name: String, i: int) -> void:
	if name == "idle_full_theatre":
		return
	var t := float(i) / float(maxi(_frames - 1, 1))
	if name == "continuous_pan":
		if _scene.get("view_offset") != null:
			_scene.view_offset = Vector2(sin(t * TAU * 2.0) * 180.0, cos(t * TAU * 1.5) * 120.0)
	elif name == "continuous_zoom":
		if _scene.get("view_scale") != null:
			_scene.view_scale = lerpf(1.0, 4.0, 0.5 + 0.5 * sin(t * TAU))
		if _scene.get("view_offset") != null:
			_scene.view_offset = Vector2(cos(t * TAU) * 40.0, sin(t * TAU) * 30.0)


func _reset_home_view() -> void:
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")
	if _scene.get("view_offset") != null:
		_scene.view_offset = Vector2.ZERO
	_mark_layers_dirty()
	_sync_shadow_transform_and_cull()


func _capture_parity(am) -> Dictionary:
	var picks: Array = []
	var ok := true
	for idx in [0, 503, 1009, 2017, 3001]:
		if idx < 0 or idx >= am.province_by_index.size():
			continue
		var expected := String(am.province_by_index[idx])
		var point: Vector2 = am.centroids[idx]
		var picked := String(am.province_at_image_pos(point))
		var match := picked == expected
		picks.append({"index": idx, "expected": expected, "picked": picked, "match": match})
		ok = ok and match
	var water := {"index": -1, "province_id": "", "picked": "", "non_selectable": false}
	for i in range(am.is_water.size()):
		if int(am.is_water[i]) == 1:
			var wp := String(am.province_by_index[i])
			var picked_water := String(am.province_at_image_pos(am.centroids[i]))
			water = {"index": i, "province_id": wp, "picked": picked_water, "non_selectable": picked_water != wp}
			ok = ok and bool(water["non_selectable"])
			break
	var selected := String(_scene.selected_province_id) if _scene.get("selected_province_id") != null else ""
	var legal_keys: Array = []
	if _scene.get("legal_targets") != null and _scene.legal_targets is Dictionary:
		legal_keys = (_scene.legal_targets as Dictionary).keys()
		legal_keys.sort()
	var anchors: Dictionary = {}
	for row in picks:
		var pid := String(row["expected"])
		anchors[pid] = _vec2_dict(am.get_anchor(pid))
	return {
		"ok": ok,
		"picks": picks,
		"water": water,
		"selected_province_id": selected,
		"legal_target_ids": legal_keys,
		"anchors": anchors,
	}


func _owner_refresh_parity(am) -> Dictionary:
	var target_index := -1
	for i in range(am.is_water.size()):
		if int(am.is_water[i]) == 0:
			target_index = i
			break
	if target_index < 0:
		return {"ok": false, "error": "no land province"}
	var pid := String(am.province_by_index[target_index])
	var snapshot_copy: Dictionary = _scene.snapshot.duplicate(true)
	var provinces: Array = snapshot_copy.get("provinces", [])
	var old_owner := ""
	var new_owner := ""
	var found := false
	for j in range(provinces.size()):
		var row: Dictionary = provinces[j]
		if String(row.get("id", "")) != pid:
			continue
		old_owner = String(row.get("owner", "neutral"))
		new_owner = "rusa" if old_owner != "rusa" else "nato"
		row["owner"] = new_owner
		provinces[j] = row
		found = true
		break
	if not found:
		return {"ok": false, "error": "target province missing from snapshot", "province_id": pid}

	var before_image := await _render_static_cache_image()
	snapshot_copy["provinces"] = provinces
	_scene.snapshot = snapshot_copy
	am.refresh_snapshot(_scene.snapshot, FACTION_COLORS)
	await _pump_frames(2, Callable())
	var after_image := await _render_static_cache_image()
	var tex_pos := Vector2i(
		clampi(int(round(am.centroids[target_index].x * CACHE_SCALE)), 0, after_image.get_width() - 1),
		clampi(int(round(am.centroids[target_index].y * CACHE_SCALE)), 0, after_image.get_height() - 1)
	)
	var before_color := before_image.get_pixelv(tex_pos)
	var after_color := after_image.get_pixelv(tex_pos)
	var owner_applied := String(am.owners[target_index]) == new_owner
	var color_changed := before_color.distance_to(after_color) > 0.01

	_scene.call("_load_snapshot", _snapshot_path)
	if _scene.has_method("_open_color_id_map"):
		_scene.map_manifest_source_path = _manifest_path
		_scene.call("_open_color_id_map")
	_live_root = _scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	await _pump_frames(2, Callable())
	return {
		"ok": owner_applied and color_changed,
		"province_id": pid,
		"old_owner": old_owner,
		"new_owner": new_owner,
		"polygon_owner_state_applied": owner_applied,
		"cached_pixel_changed": color_changed,
		"before_rgba": [before_color.r, before_color.g, before_color.b, before_color.a],
		"after_rgba": [after_color.r, after_color.g, after_color.b, after_color.a],
	}


func _authority_hashes() -> Dictionary:
	var manifest_hash := FileAccess.get_sha256(_manifest_path)
	var snapshot_hash := FileAccess.get_sha256(_snapshot_path)
	var dataset_path := ""
	var file := FileAccess.open(_manifest_path, FileAccess.READ)
	if file != null:
		var parsed: Variant = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			var rel := String((parsed as Dictionary).get("polygon_dataset", {}).get("path", "polygon_dataset.json"))
			dataset_path = _manifest_path.get_base_dir().path_join(rel)
	return {
		"manifest_sha256": manifest_hash,
		"polygon_dataset_sha256": FileAccess.get_sha256(dataset_path) if not dataset_path.is_empty() else "",
		"snapshot_fixture_sha256": snapshot_hash,
	}


func _capture_screen(path: String) -> void:
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var image := root.get_texture().get_image() if root is Window else null
	if image == null or image.is_empty():
		return
	image.save_png(path)


func _midpoint_stats(a: Dictionary, b: Dictionary) -> Dictionary:
	var out := {}
	for key in ["frame_time_ms", "script_cpu_ms", "draw_calls", "primitives", "node_count", "object_count", "texture_mem_bytes", "video_mem_bytes"]:
		var av: Dictionary = a.get(key, {})
		var bv: Dictionary = b.get(key, {})
		var row := {}
		for stat in ["count", "avg", "p50", "p95", "p99", "max", "min"]:
			row[stat] = (float(av.get(stat, 0.0)) + float(bv.get(stat, 0.0))) * 0.5
		out[key] = row
	return out


func _baseline_drift(a: Dictionary, b: Dictionary) -> Dictionary:
	var a50 := float(a["frame_time_ms"]["p50"])
	var b50 := float(b["frame_time_ms"]["p50"])
	var a95 := float(a["frame_time_ms"]["p95"])
	var b95 := float(b["frame_time_ms"]["p95"])
	return {
		"frame_ms_p50_abs": snappedf(absf(a50 - b50), 0.001),
		"frame_ms_p50_ratio": snappedf(absf(a50 - b50) / maxf((a50 + b50) * 0.5, 0.001), 0.0001),
		"frame_ms_p95_abs": snappedf(absf(a95 - b95), 0.001),
		"frame_ms_p95_ratio": snappedf(absf(a95 - b95) / maxf((a95 + b95) * 0.5, 0.001), 0.0001),
		"draw_calls_p50_abs": absi(int(a["draw_calls"]["p50"]) - int(b["draw_calls"]["p50"])),
		"primitives_p50_abs": absi(int(a["primitives"]["p50"]) - int(b["primitives"]["p50"])),
	}


func _compact_summary(result: Dictionary) -> Dictionary:
	var summary := {}
	for mode_name in result.get("modes", {}).keys():
		var mode: Dictionary = result["modes"][mode_name]
		var scenario_summary := {}
		for scenario_name in mode.get("scenarios", {}).keys():
			var bracket: Dictionary = mode["scenarios"][scenario_name]
			scenario_summary[scenario_name] = bracket.get("delta", {})
		summary[mode_name] = scenario_summary
	return summary


func _active_map():
	if _scene != null and _scene.has_method("_active_map"):
		return _scene.call("_active_map")
	return _scene.get("polygon_map") if _scene != null else null


func _mark_layers_dirty() -> void:
	if _scene != null and _scene.get("_layers_dirty") != null:
		_scene._layers_dirty = true


func _pump_frames(count: int, setup: Callable) -> void:
	for i in range(count):
		if setup.is_valid():
			setup.call(i)
		_mark_layers_dirty()
		if _scene != null:
			if _scene.has_method("_sync_presentation_layers"):
				_scene.call("_sync_presentation_layers")
			_sync_shadow_transform_and_cull()
			if _scene.has_method("queue_redraw"):
				_scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame


func _sample_performance() -> Dictionary:
	return {
		"script_cpu_ms": snappedf(float(Performance.get_monitor(Performance.TIME_PROCESS)) * 1000.0, 0.001),
		"draw_calls": int(Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME)),
		"primitives": int(Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME)),
		"object_count": int(Performance.get_monitor(Performance.OBJECT_COUNT)),
		"node_count": int(Performance.get_monitor(Performance.OBJECT_NODE_COUNT)),
		"texture_mem_bytes": int(Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)),
		"video_mem_bytes": int(Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED)),
	}


func _stats(samples: Array) -> Dictionary:
	if samples.is_empty():
		return {"count": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "min": 0.0}
	var sorted := samples.duplicate()
	sorted.sort()
	var total := 0.0
	for value in sorted:
		total += float(value)
	return {
		"count": sorted.size(),
		"avg": snappedf(total / float(sorted.size()), 0.001),
		"p50": snappedf(_percentile_sorted(sorted, 0.50), 0.001),
		"p95": snappedf(_percentile_sorted(sorted, 0.95), 0.001),
		"p99": snappedf(_percentile_sorted(sorted, 0.99), 0.001),
		"max": snappedf(float(sorted[-1]), 0.001),
		"min": snappedf(float(sorted[0]), 0.001),
	}


func _stats_int(samples: Array) -> Dictionary:
	var s := _stats(samples)
	return {
		"count": int(s["count"]),
		"avg": snappedf(float(s["avg"]), 0.01),
		"p50": int(round(float(s["p50"]))),
		"p95": int(round(float(s["p95"]))),
		"p99": int(round(float(s["p99"]))),
		"max": int(round(float(s["max"]))),
		"min": int(round(float(s["min"]))),
	}


func _percentile_sorted(sorted: Array, p: float) -> float:
	if sorted.is_empty():
		return 0.0
	var idx := clampi(int(ceil(p * float(sorted.size()))) - 1, 0, sorted.size() - 1)
	return float(sorted[idx])


func _vec2_dict(v: Vector2) -> Dictionary:
	return {"x": snappedf(v.x, 0.001), "y": snappedf(v.y, 0.001)}


func _write_json(path: String, value: Dictionary) -> void:
	var dir := path.get_base_dir()
	if not dir.is_empty():
		DirAccess.make_dir_recursive_absolute(dir)
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(value, "  "))


func _fail(message: String) -> void:
	push_error("map_raster_shadow_profiler: %s" % message)
	print("map_raster_shadow_profiler: FAIL %s" % message)
	_cleanup_and_quit(2)


func _cleanup_and_quit(code: int) -> void:
	_destroy_shadow()
	if _scene != null and is_instance_valid(_scene):
		_scene.queue_free()
	quit(code)
