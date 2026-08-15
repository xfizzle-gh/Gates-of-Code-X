extends "res://scripts/tools/map_production_layer_attribution_profiler.gd"

## #212 Phase B, checkpoint 1.
##
## Build a debug-only full-theatre raster shadow from the real Earth3 production
## scene, then render that shadow while keeping the authoritative PolygonMap
## loaded for stable IDs, water policy, point picking, and campaign state.
##
## This is intentionally not a production renderer switch. The cache is derived
## presentation only, is discarded with the benchmark process, and never becomes
## simulation or validation authority.

const CACHE_FIXTURE := "res://fixtures/presentation/e3_operational.json"
const CACHE_CAPTURE_WARMUP_FRAMES := 8
const CACHE_SAMPLE_FRAMES := 24

var _shadow_out_path := "user://issue_212_raster_shadow.json"


func _initialize() -> void:
	_snapshot_path = DEFAULT_SNAPSHOT
	_fixture_path = CACHE_FIXTURE
	_manifest_path = DEFAULT_MANIFEST
	_frames = CACHE_SAMPLE_FRAMES
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_shadow_out_path = text.substr(6).strip_edges()
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
	call_deferred("_run_shadow_benchmark")


func _run_shadow_benchmark() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for required_path in [_snapshot_path, _fixture_path, _manifest_path]:
		if not FileAccess.file_exists(String(required_path)):
			_fail("required fixture missing: %s" % String(required_path))
			return

	var baseline_result := await _measure_polygon_baseline()
	if not bool(baseline_result.get("ok", false)):
		_fail("polygon baseline failed: %s" % baseline_result.get("error", "unknown"))
		return

	var cache_result := await _capture_full_theatre_cache()
	if not bool(cache_result.get("ok", false)):
		_fail("cache capture failed: %s" % cache_result.get("error", "unknown"))
		return
	var cache_image: Image = cache_result.get("image")
	if cache_image == null or cache_image.is_empty():
		_fail("cache capture returned an empty image")
		return

	var shadow_result := await _measure_raster_shadow(cache_image, baseline_result.get("picking", []))
	if not bool(shadow_result.get("ok", false)):
		_fail("raster shadow failed: %s" % shadow_result.get("error", "unknown"))
		return

	var baseline_metrics: Dictionary = baseline_result.get("metrics", {})
	var shadow_metrics: Dictionary = shadow_result.get("metrics", {})
	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-raster-shadow",
		"schema_version": 1,
		"issue": 212,
		"phase": "B",
		"checkpoint": "full_theatre_cache",
		"authority": {
			"map_id": "earth3_europe_mediterranean",
			"province_count": 3514,
			"polygon_authority_retained": true,
			"picking_parity": true,
			"water_policy_retained": true,
		},
		"cache": {
			"kind": "debug_only_full_viewport_raster_shadow",
			"width": cache_image.get_width(),
			"height": cache_image.get_height(),
			"bytes_rgba8": cache_image.get_width() * cache_image.get_height() * 4,
			"persistent": false,
			"campaign_authority": false,
		},
		"baseline": baseline_metrics,
		"raster_shadow": shadow_metrics,
		"delta": _delta_from_baseline(baseline_metrics, shadow_metrics),
		"picking": baseline_result.get("picking", []),
		"notes": [
			"The raster cache is derived from the production Earth3 scene and exists only inside this benchmark process.",
			"The authoritative PolygonMap remains loaded while the cached presentation is measured.",
			"Stable province picking is executed through the PolygonMap before and after the presentation swap.",
			"This checkpoint evaluates the full-theatre cache control only; map-space 512/1024 tiled cache plus viewport culling is a separate Phase B checkpoint.",
			"No production renderer, polygon dataset, topology, stable IDs, water policy, campaign state, or schema is modified.",
			"Absolute CI frame times are llvmpipe evidence only and are not owner-native acceptance metrics.",
		],
	}
	_write_json(_shadow_out_path, result)
	print("ISSUE212_RASTER_SHADOW %s" % JSON.stringify(result))
	print("map_raster_shadow_benchmark: PASS out=%s" % _shadow_out_path)
	quit(0)


func _measure_polygon_baseline() -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	_configure_common_scene(scene)
	await _pump_frames(scene, CACHE_CAPTURE_WARMUP_FRAMES)
	var active_map = _active_map(scene)
	var authority_error := _authority_error(scene, active_map)
	if not authority_error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": authority_error}
	var picks := _pick_suite(active_map)
	if not _picks_match(picks):
		await _dispose_scene(scene)
		return {"ok": false, "error": "polygon baseline picking mismatch: %s" % picks}
	var metrics := await _measure(scene, "polygon_baseline")
	await _dispose_scene(scene)
	return {"ok": true, "metrics": metrics, "picking": picks}


func _capture_full_theatre_cache() -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	_configure_common_scene(scene)
	await _pump_frames(scene, CACHE_CAPTURE_WARMUP_FRAMES)
	var active_map = _active_map(scene)
	var authority_error := _authority_error(scene, active_map)
	if not authority_error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": authority_error}

	RenderingServer.force_draw(false, 0.0)
	await process_frame
	await process_frame
	var image: Image = null
	if root is Viewport:
		var texture := (root as Viewport).get_texture()
		if texture != null:
			image = texture.get_image()
	if image == null or image.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": "root viewport cache capture is empty"}
	var copy := image.duplicate()
	await _dispose_scene(scene)
	return {"ok": true, "image": copy}


func _measure_raster_shadow(cache_image: Image, baseline_picks: Array) -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	_configure_common_scene(scene)
	await _pump_frames(scene, CACHE_CAPTURE_WARMUP_FRAMES)
	var active_map = _active_map(scene)
	var authority_error := _authority_error(scene, active_map)
	if not authority_error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": authority_error}

	var before_picks := _pick_suite(active_map)
	if before_picks != baseline_picks or not _picks_match(before_picks):
		await _dispose_scene(scene)
		return {"ok": false, "error": "pre-shadow picking parity failed: %s" % before_picks}

	var poly_root := scene.find_child("Earth3PolygonRoot", true, false)
	if poly_root == null or not poly_root is CanvasItem:
		await _dispose_scene(scene)
		return {"ok": false, "error": "Earth3PolygonRoot missing"}
	(poly_root as CanvasItem).visible = false

	var cache_layer := CanvasLayer.new()
	cache_layer.name = "Issue212RasterShadowLayer"
	cache_layer.layer = -50
	var cache_rect := TextureRect.new()
	cache_rect.name = "Issue212RasterShadow"
	cache_rect.mouse_filter = Control.MOUSE_FILTER_IGNORE
	cache_rect.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	cache_rect.position = Vector2.ZERO
	cache_rect.size = Vector2(float(_width), float(_height))
	cache_rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	cache_rect.stretch_mode = TextureRect.STRETCH_SCALE
	cache_rect.texture = ImageTexture.create_from_image(cache_image)
	cache_layer.add_child(cache_rect)
	scene.add_child(cache_layer)

	await _pump_frames(scene, CACHE_CAPTURE_WARMUP_FRAMES)
	var after_picks := _pick_suite(active_map)
	if after_picks != baseline_picks or not _picks_match(after_picks):
		await _dispose_scene(scene)
		return {"ok": false, "error": "post-shadow picking parity failed: %s" % after_picks}

	var metrics := await _measure(scene, "full_theatre_raster_shadow")
	await _dispose_scene(scene)
	return {"ok": true, "metrics": metrics, "picking": after_picks}


func _configure_common_scene(scene: Node) -> void:
	if scene.get("map_debug") != null and scene.map_debug != null:
		scene.map_debug.enabled = false
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()


func _authority_error(scene: Node, active_map) -> String:
	if active_map == null or not bool(active_map.is_ready):
		return "Earth3 map backend not ready"
	if not bool(scene.get("map_backend_is_polygon")):
		return "expected polygon authority backend"
	if int(active_map.province_count) != 3514:
		return "Earth3 authority changed: province_count=%s" % int(active_map.province_count)
	return ""


func _picks_match(rows: Array) -> bool:
	if rows.is_empty():
		return false
	for row_variant in rows:
		if not row_variant is Dictionary:
			return false
		if not bool((row_variant as Dictionary).get("match", false)):
			return false
	return true
