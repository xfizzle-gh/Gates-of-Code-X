extends "res://scripts/main_order_controls.gd"

## #212 E1 production-candidate integration.
##
## Default packaged/runtime behavior is unchanged. The candidate is activated
## only when GOCX_PRESENTATION_CANDIDATE=hybrid is present in the process
## environment. Even then PolygonMap remains loaded and authoritative; only the
## static Earth3 polygon presentation root is shadowed.

const StrategicRasterCandidateScript = preload("res://scripts/presentation/strategic_raster_candidate.gd")
const PRESENTATION_CANDIDATE_ENV := "GOCX_PRESENTATION_CANDIDATE"
const PRESENTATION_CANDIDATE_VALUE := "hybrid"
const CANDIDATE_CACHE_SCALE := 2

var presentation_candidate_requested := false
var presentation_candidate_active := false
var presentation_candidate_status := "default_polygon"
var _presentation_candidate: StrategicRasterCandidate = null
var _presentation_candidate_cache: Image = null
var _presentation_candidate_refresh_pending := false
var _presentation_candidate_building := false
var _presentation_candidate_enabled_intent := false
var _presentation_candidate_build_epoch := 0
var _presentation_candidate_cancelled_builds := 0


func _ready() -> void:
	presentation_candidate_requested = (
		OS.get_environment(PRESENTATION_CANDIDATE_ENV).strip_edges().to_lower()
		== PRESENTATION_CANDIDATE_VALUE
	)
	_presentation_candidate_enabled_intent = presentation_candidate_requested
	super._ready()
	if presentation_candidate_requested:
		presentation_candidate_status = "requested"
		call_deferred("_activate_presentation_candidate")


func _process(delta: float) -> void:
	super._process(delta)
	if _presentation_candidate != null and presentation_candidate_active:
		var viewport_size := get_viewport_rect().size
		var map_viewport := Vector2(maxf(1.0, viewport_size.x - PANEL_WIDTH), viewport_size.y)
		_presentation_candidate.sync(view_scale, map_viewport)
	if _presentation_candidate_refresh_pending and not _presentation_candidate_building:
		_presentation_candidate_refresh_pending = false
		if _presentation_candidate_enabled_intent:
			call_deferred("_refresh_presentation_candidate")


func _load_snapshot(path: String) -> void:
	# Invalidate every in-flight capture before authority changes. A capture owns the
	# epoch it started in and may finish its frame awaits, but it can never publish
	# into a later snapshot generation.
	_presentation_candidate_build_epoch += 1
	# Cache freshness is independent from visibility. A manually disabled candidate
	# may still hold pixels from the previous snapshot, so invalidate every derived
	# cache before loading new authority. Rebuild only when the user's current
	# presentation intent wants the candidate visible.
	var had_candidate_cache := _presentation_candidate != null \
		or (_presentation_candidate_cache != null and not _presentation_candidate_cache.is_empty())
	_presentation_candidate_refresh_pending = false
	if _presentation_candidate != null:
		_presentation_candidate.set_candidate_enabled(false)
	presentation_candidate_active = false
	if had_candidate_cache:
		_discard_presentation_candidate()
		_presentation_candidate_cache = null
	super._load_snapshot(path)
	if presentation_candidate_requested and _presentation_candidate_enabled_intent:
		presentation_candidate_status = "refresh_pending"
		_presentation_candidate_refresh_pending = true
	elif presentation_candidate_requested:
		presentation_candidate_status = "manual_polygon"


func set_presentation_candidate_enabled(enabled: bool) -> void:
	var intent_changed := _presentation_candidate_enabled_intent != enabled
	_presentation_candidate_enabled_intent = enabled
	if not enabled:
		# Disabling is also a cancellation boundary. Any capture already awaiting a
		# frame may finish locally, but its epoch is no longer allowed to publish.
		if intent_changed or _presentation_candidate_building:
			_presentation_candidate_build_epoch += 1
		_presentation_candidate_refresh_pending = false
		if _presentation_candidate != null:
			_presentation_candidate.set_candidate_enabled(false)
		presentation_candidate_active = false
		presentation_candidate_status = "manual_polygon"
		return
	presentation_candidate_requested = true
	if intent_changed:
		_presentation_candidate_build_epoch += 1
	if _presentation_candidate != null:
		_presentation_candidate.set_candidate_enabled(true)
		presentation_candidate_active = true
		presentation_candidate_status = "active"
		return
	call_deferred("_activate_presentation_candidate")


func presentation_candidate_debug_state() -> Dictionary:
	var state := {
		"requested": presentation_candidate_requested,
		"enabled_intent": _presentation_candidate_enabled_intent,
		"active": presentation_candidate_active,
		"status": presentation_candidate_status,
		"authority_backend_polygon": map_backend_is_polygon,
		"environment_gate": PRESENTATION_CANDIDATE_ENV,
		"cache_present": _presentation_candidate_cache != null and not _presentation_candidate_cache.is_empty(),
		"building": _presentation_candidate_building,
		"refresh_pending": _presentation_candidate_refresh_pending,
		"build_epoch": _presentation_candidate_build_epoch,
		"cancelled_builds": _presentation_candidate_cancelled_builds,
	}
	if _presentation_candidate != null:
		state["candidate"] = _presentation_candidate.debug_state()
	else:
		state["candidate"] = {}
	return state


func _activate_presentation_candidate() -> void:
	if _presentation_candidate_building or presentation_candidate_active:
		return
	if not presentation_candidate_requested or not _presentation_candidate_enabled_intent:
		return
	if not map_backend_is_polygon or polygon_map == null or not polygon_map.is_ready:
		presentation_candidate_status = "refused_non_polygon_authority"
		return
	var live_root := get_node_or_null("Earth3PolygonRoot") as Node2D
	if live_root == null:
		presentation_candidate_status = "refused_missing_polygon_root"
		return
	var build_epoch := _presentation_candidate_build_epoch
	_presentation_candidate_building = true
	presentation_candidate_status = "building_cache"
	var cache := await _capture_candidate_static_map(live_root)
	if not _candidate_build_is_current(build_epoch):
		_cancel_candidate_build(build_epoch)
		return
	if cache == null or cache.is_empty():
		_presentation_candidate_building = false
		presentation_candidate_status = "cache_capture_failed"
		return
	_presentation_candidate_cache = cache
	_discard_presentation_candidate()
	var candidate := StrategicRasterCandidateScript.new() as StrategicRasterCandidate
	if candidate == null or not candidate.configure(live_root, _presentation_candidate_cache):
		if candidate != null:
			candidate.queue_free()
		_presentation_candidate_building = false
		presentation_candidate_status = "candidate_configure_failed"
		return
	add_child(candidate)
	_presentation_candidate = candidate
	_presentation_candidate.set_candidate_enabled(true)
	presentation_candidate_active = true
	presentation_candidate_status = "active"
	_presentation_candidate_building = false
	var state := _presentation_candidate.debug_state()
	print("ISSUE212_PRESENTATION_CANDIDATE active mode=%s total_tiles=%s wide_bytes=%s" % [
		String(state.get("mode", "pending")),
		int(state.get("total_tiles", 0)),
		int(state.get("wide_rgba8_bytes", 0)),
	])


func _refresh_presentation_candidate() -> void:
	if _presentation_candidate_building or not presentation_candidate_requested or not _presentation_candidate_enabled_intent:
		return
	if not map_backend_is_polygon or polygon_map == null or not polygon_map.is_ready:
		presentation_candidate_status = "refresh_refused_non_polygon_authority"
		return
	var live_root := get_node_or_null("Earth3PolygonRoot") as Node2D
	if live_root == null:
		presentation_candidate_status = "refresh_refused_missing_polygon_root"
		return
	var build_epoch := _presentation_candidate_build_epoch
	_presentation_candidate_building = true
	presentation_candidate_status = "refresh_building_cache"
	var cache := await _capture_candidate_static_map(live_root)
	if not _candidate_build_is_current(build_epoch):
		_cancel_candidate_build(build_epoch)
		return
	if cache == null or cache.is_empty():
		_presentation_candidate_building = false
		presentation_candidate_status = "refresh_cache_failed"
		return
	_presentation_candidate_cache = cache
	_discard_presentation_candidate()
	var candidate := StrategicRasterCandidateScript.new() as StrategicRasterCandidate
	if candidate == null or not candidate.configure(live_root, _presentation_candidate_cache):
		if candidate != null:
			candidate.queue_free()
		_presentation_candidate_building = false
		presentation_candidate_status = "refresh_configure_failed"
		return
	add_child(candidate)
	_presentation_candidate = candidate
	_presentation_candidate.set_candidate_enabled(true)
	presentation_candidate_active = true
	presentation_candidate_status = "active"
	_presentation_candidate_building = false


func _candidate_build_is_current(build_epoch: int) -> bool:
	return build_epoch == _presentation_candidate_build_epoch \
		and presentation_candidate_requested \
		and _presentation_candidate_enabled_intent


func _cancel_candidate_build(_build_epoch: int) -> void:
	_presentation_candidate_cancelled_builds += 1
	_presentation_candidate_building = false
	if not _presentation_candidate_enabled_intent:
		presentation_candidate_status = "manual_polygon"
	elif _presentation_candidate_refresh_pending:
		presentation_candidate_status = "refresh_pending"
	else:
		presentation_candidate_status = "cancelled_stale_build"


func _discard_presentation_candidate() -> void:
	if _presentation_candidate == null:
		return
	_presentation_candidate.shutdown()
	if _presentation_candidate.get_parent() == self:
		remove_child(_presentation_candidate)
	_presentation_candidate.queue_free()
	_presentation_candidate = null


func _capture_candidate_static_map(live_root: Node2D) -> Image:
	if live_root == null or polygon_map == null or not polygon_map.is_ready:
		return null
	var map_size_value: Vector2 = polygon_map.image_size()
	var map_size := Vector2i(maxi(1, int(map_size_value.x)), maxi(1, int(map_size_value.y)))
	var capture := SubViewport.new()
	capture.size = map_size * CANDIDATE_CACHE_SCALE
	capture.transparent_bg = true
	capture.disable_3d = true
	capture.render_target_update_mode = SubViewport.UPDATE_ONCE
	var duplicate_root := live_root.duplicate() as Node2D
	if duplicate_root == null:
		capture.queue_free()
		return null
	duplicate_root.visible = true
	duplicate_root.position = Vector2.ZERO
	duplicate_root.scale = Vector2(CANDIDATE_CACHE_SCALE, CANDIDATE_CACHE_SCALE)
	duplicate_root.rotation = 0.0
	capture.add_child(duplicate_root)
	get_tree().root.add_child(capture)
	await get_tree().process_frame
	RenderingServer.force_draw(false, 0.0)
	await RenderingServer.frame_post_draw
	var rendered := capture.get_texture().get_image()
	var copy: Image = rendered.duplicate() if rendered != null and not rendered.is_empty() else null
	capture.queue_free()
	await get_tree().process_frame
	return copy
