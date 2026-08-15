extends "res://scripts/main_composed_presentation.gd"

## #212 E2 final reload-safety boundary.
##
## E1 already restores authoritative polygons synchronously before rebuilding a
## raster cache. E2 must do the same for every derived overlay. This final thin
## subclass keeps the larger compositor reviewable while making reload behavior
## fail closed and preserving the player's layer-toggle choices across remounts.

var _preserved_composed_toggles: Dictionary = {}


func _load_snapshot(path: String) -> void:
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
	if not composed_presentation_active or preserved.is_empty():
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
