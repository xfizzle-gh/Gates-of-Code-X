extends "res://scripts/main_composed_presentation.gd"

## #212 E2 final reload/camera-safety boundary.
##
## E1 already restores authoritative polygons synchronously before rebuilding a
## raster cache. E2 must do the same for every derived overlay. This final thin
## subclass keeps the larger compositor reviewable while making reload behavior
## fail closed, preserving the player's layer-toggle choices across remounts,
## and keeping atlas screen positions synchronized with live pan/zoom.

var _preserved_composed_toggles: Dictionary = {}
var _composed_camera_signature := ""
var _composed_atlas_camera_updates := 0


func _process(delta: float) -> void:
	super._process(delta)
	if not composed_presentation_active or _composed_atlas == null:
		_composed_camera_signature = ""
		return
	var next_signature := _current_composed_camera_signature()
	if _composed_camera_signature.is_empty():
		_composed_camera_signature = next_signature
		return
	if next_signature == _composed_camera_signature:
		return
	_composed_camera_signature = next_signature
	_composed_atlas_camera_updates += 1
	# Atlas entries cache the shared clamped screen center so they stay aligned
	# with live warning rings/reservations. Recompute that center whenever the
	# normal camera transform changes. No caller/test must manually rebuild it.
	_rebuild_composed_atlas_entries()


func _load_snapshot(path: String) -> void:
	_composed_camera_signature = ""
	if not _composed_toggles.is_empty():
		_preserved_composed_toggles = _composed_toggles.duplicate(true)
	super._load_snapshot(path)
	if composed_presentation_requested and (_composed_atlas != null or _composed_canvas != null):
		composed_presentation_active = false
		composed_presentation_status = "refresh_pending"
		if _composed_atlas != null:
			_composed_atlas.visible = false
		if _composed_canvas != null:
			_composed_canvas.visible = false
		queue_redraw()


func _ensure_composed_surface() -> void:
	var preserved := _preserved_composed_toggles.duplicate(true)
	if preserved.is_empty() and not _composed_toggles.is_empty():
		preserved = _composed_toggles.duplicate(true)
	super._ensure_composed_surface()
	if not composed_presentation_active:
		return
	_composed_camera_signature = _current_composed_camera_signature()
	if preserved.is_empty():
		return
	_composed_toggles = preserved
	_preserved_composed_toggles = preserved.duplicate(true)
	if _composed_layer_control != null:
		_composed_layer_control.configure(_composed_toggles)
	_composed_lod = ""
	_sync_composed_lod()
	_composed_atlas_dirty = true
	_composed_minimap_dirty = true
	if _composed_atlas != null:
		_composed_atlas.visible = bool(_composed_state.get("formation_symbols", true))
	queue_redraw()


func composed_presentation_debug_state() -> Dictionary:
	var state := super.composed_presentation_debug_state()
	state["atlas_camera_updates"] = _composed_atlas_camera_updates
	state["camera_signature"] = _composed_camera_signature
	return state


func _current_composed_camera_signature() -> String:
	var viewport := get_viewport_rect().size
	return "%0.6f|%0.3f|%0.3f|%0.1f|%0.1f" % [
		view_scale,
		view_offset.x,
		view_offset.y,
		viewport.x,
		viewport.y,
	]
