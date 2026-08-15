extends "res://scripts/main_presentation_candidate.gd"

## #212 E2 composed production-candidate presentation.
##
## This layer is still opt-in. It requires both:
##   GOCX_PRESENTATION_CANDIDATE=hybrid
##   GOCX_PRESENTATION_COMPOSED=1
##
## E1 owns the static hybrid raster. E2 composes Phase C atlas symbols and Phase D
## LOD/layer-control/minimap behavior on top while keeping PolygonMap authority.
## Default launches execute the inherited renderer without mounting any E2 node.

const COMPOSED_ENV := "GOCX_PRESENTATION_COMPOSED"
const StrategicIconAtlasLayerScript = preload("res://scripts/presentation/strategic_icon_atlas_layer.gd")
const StrategicMapLodPolicyScript = preload("res://scripts/presentation/strategic_map_lod_policy.gd")
const StrategicMapLayerControlScript = preload("res://scripts/presentation/strategic_map_layer_control.gd")
const StrategicMinimapPrototypeScript = preload("res://scripts/presentation/strategic_minimap_prototype.gd")

var composed_presentation_requested := false
var composed_presentation_active := false
var composed_presentation_status := "default_renderer"

var _composed_policy: StrategicMapLodPolicy = null
var _composed_toggles: Dictionary = {}
var _composed_state: Dictionary = {}
var _composed_lod := ""
var _composed_atlas: StrategicIconAtlasLayer = null
var _composed_canvas: CanvasLayer = null
var _composed_layer_control: StrategicMapLayerControl = null
var _composed_minimap: StrategicMinimapPrototype = null
var _composed_atlas_dirty := true
var _composed_minimap_dirty := true


func _ready() -> void:
	composed_presentation_requested = OS.get_environment(COMPOSED_ENV).strip_edges() == "1"
	super._ready()
	if composed_presentation_requested:
		composed_presentation_status = "waiting_for_hybrid_candidate"
		call_deferred("_ensure_composed_surface")


func _process(delta: float) -> void:
	super._process(delta)
	if not composed_presentation_requested:
		return
	if not presentation_candidate_active:
		composed_presentation_active = false
		if _composed_atlas != null:
			_composed_atlas.visible = false
		if _composed_canvas != null:
			_composed_canvas.visible = false
		return
	if not composed_presentation_active:
		_ensure_composed_surface()
	if not composed_presentation_active:
		return
	_sync_composed_lod()
	if _composed_atlas_dirty:
		_rebuild_composed_atlas_entries()
	if _composed_minimap_dirty:
		_refresh_composed_minimap()


func _load_snapshot(path: String) -> void:
	super._load_snapshot(path)
	_composed_atlas_dirty = true
	_composed_minimap_dirty = true


func _rebuild_legal_targets() -> void:
	super._rebuild_legal_targets()
	_composed_minimap_dirty = true


func set_composed_layer_toggle(layer_key: String, enabled: bool) -> bool:
	if _composed_policy == null or not StrategicMapLodPolicy.LAYER_KEYS.has(layer_key):
		return false
	_composed_toggles[layer_key] = enabled
	if _composed_layer_control != null:
		_composed_layer_control.configure(_composed_toggles)
	_composed_lod = ""
	_sync_composed_lod()
	queue_redraw()
	return true


func composed_presentation_debug_state() -> Dictionary:
	var atlas_entries := 0
	var atlas_strength := false
	if _composed_atlas != null:
		atlas_entries = _composed_atlas.entries.size()
		atlas_strength = _composed_atlas.show_strength_text
	return {
		"requested": composed_presentation_requested,
		"active": composed_presentation_active,
		"status": composed_presentation_status,
		"environment_gate": COMPOSED_ENV,
		"lod": _composed_lod,
		"state": _composed_state.duplicate(true),
		"toggles": _composed_toggles.duplicate(true),
		"atlas_mounted": _composed_atlas != null,
		"atlas_visible": _composed_atlas.visible if _composed_atlas != null else false,
		"atlas_entry_count": atlas_entries,
		"atlas_strength_text": atlas_strength,
		"atlas_vocabulary_count": _composed_atlas.vocabulary().size() if _composed_atlas != null else 0,
		"layer_control_mounted": _composed_layer_control != null,
		"minimap_mounted": _composed_minimap != null,
		"minimap_texture_size": _composed_minimap.texture_size() if _composed_minimap != null else Vector2i.ZERO,
		"minimap_has_live_map_descendant": _composed_minimap.has_live_map_descendant() if _composed_minimap != null else false,
		"route_enabled": bool(_composed_state.get("operational_routes", true)),
		"authority_backend_polygon": map_backend_is_polygon,
	}


func _ensure_composed_surface() -> void:
	if composed_presentation_active or not composed_presentation_requested:
		return
	if not presentation_candidate_requested:
		composed_presentation_status = "refused_without_hybrid_request"
		return
	if not presentation_candidate_active or _presentation_candidate_cache == null or _presentation_candidate_cache.is_empty():
		composed_presentation_status = "waiting_for_hybrid_candidate"
		return
	if not map_backend_is_polygon or polygon_map == null or not polygon_map.is_ready:
		composed_presentation_status = "refused_non_polygon_authority"
		return

	# E1 snapshot refresh deliberately deactivates the raster while rebuilding.
	# When it comes back, dispose the old hidden E2 nodes before remounting against
	# the fresh cache. This makes repeated campaign snapshot loads idempotent.
	_discard_composed_surface()
	_composed_policy = StrategicMapLodPolicyScript.new() as StrategicMapLodPolicy
	if _composed_policy == null:
		composed_presentation_status = "policy_create_failed"
		return
	_composed_toggles = _composed_policy.default_toggles()
	_composed_state = _composed_policy.state_for_scale(view_scale, _composed_toggles)
	_composed_lod = String(_composed_state.get("lod", ""))

	_composed_atlas = StrategicIconAtlasLayerScript.new() as StrategicIconAtlasLayer
	if _composed_atlas == null:
		composed_presentation_status = "atlas_create_failed"
		return
	_composed_atlas.name = "Issue212ComposedAtlas"
	_composed_atlas.z_index = 12
	_composed_atlas.configure(map_space, [], _composed_lod != "full_theatre")
	add_child(_composed_atlas)

	_composed_canvas = CanvasLayer.new()
	_composed_canvas.name = "Issue212ComposedCanvas"
	_composed_canvas.layer = 40
	add_child(_composed_canvas)

	_composed_layer_control = StrategicMapLayerControlScript.new() as StrategicMapLayerControl
	_composed_layer_control.name = "Issue212MapLayerControl"
	_composed_layer_control.position = Vector2(16, HEADER_SAFE_TOP + 16)
	_composed_layer_control.configure(_composed_toggles)
	_composed_layer_control.layer_toggled.connect(_on_composed_layer_toggled)
	_composed_canvas.add_child(_composed_layer_control)

	_composed_minimap = StrategicMinimapPrototypeScript.new() as StrategicMinimapPrototype
	_composed_minimap.name = "Issue212CachedMinimap"
	_composed_minimap.position = Vector2(16, 410)
	_composed_canvas.add_child(_composed_minimap)

	composed_presentation_active = true
	composed_presentation_status = "active"
	_composed_atlas_dirty = true
	_composed_minimap_dirty = true
	_sync_composed_lod()
	_rebuild_composed_atlas_entries()
	_refresh_composed_minimap()
	queue_redraw()
	print("ISSUE212_COMPOSED_PRESENTATION active lod=%s atlas_entries=%s" % [
		_composed_lod,
		_composed_atlas.entries.size(),
	])


func _discard_composed_surface() -> void:
	if _composed_atlas != null:
		if _composed_atlas.get_parent() == self:
			remove_child(_composed_atlas)
		_composed_atlas.queue_free()
		_composed_atlas = null
	if _composed_canvas != null:
		if _composed_canvas.get_parent() == self:
			remove_child(_composed_canvas)
		_composed_canvas.queue_free()
		_composed_canvas = null
	_composed_layer_control = null
	_composed_minimap = null
	_composed_policy = null
	composed_presentation_active = false


func _sync_composed_lod() -> void:
	if not composed_presentation_active or _composed_policy == null:
		return
	var next_state := _composed_policy.state_for_scale(view_scale, _composed_toggles)
	var next_lod := String(next_state.get("lod", ""))
	if next_lod == _composed_lod and next_state == _composed_state:
		return
	_composed_lod = next_lod
	_composed_state = next_state
	if _composed_atlas != null:
		_composed_atlas.visible = bool(_composed_state.get("formation_symbols", true))
		_composed_atlas.set_strength_text_enabled(_composed_lod != "full_theatre")
	queue_redraw()


func _rebuild_composed_atlas_entries() -> void:
	_composed_atlas_dirty = false
	if _composed_atlas == null:
		return
	var rows: Array = []
	var province_ids: Array = battalions_by_province.keys()
	province_ids.sort()
	var active_map = _active_map()
	if active_map == null or not active_map.is_ready:
		_composed_atlas.set_entries(rows)
		return
	var bounds := _overlay_clamp_rect()
	for pid_value in province_ids:
		var pid := String(pid_value)
		var battalion_value: Variant = battalions_by_province.get(pid, {})
		if not battalion_value is Dictionary:
			continue
		var battalion := battalion_value as Dictionary
		if battalion.is_empty() or not active_map.row_by_province.has(pid):
			continue
		var map_pixel: Vector2 = active_map.anchor_pixel(pid)
		var display_pixel: Variant = battalion.get("display_pixel", null)
		if display_pixel is Array and (display_pixel as Array).size() >= 2:
			map_pixel = Vector2(float(display_pixel[0]), float(display_pixel[1]))
		var province: Dictionary = provinces_by_id.get(pid, {})
		var faction := String(battalion.get("faction", province.get("owner", "neutral")))
		rows.append({
			"province_id": pid,
			"pixel": [map_pixel.x, map_pixel.y],
			"screen_position": _composed_counter_screen_position(pid, battalion, active_map, bounds),
			"icon_key": _composed_icon_key(String(battalion.get("battalion_type", ""))),
			"color": FACTION_COLORS.get(faction, FACTION_COLORS["neutral"]),
			"strength": int(battalion.get("unit_count", 0)),
		})
	_composed_atlas.set_entries(rows)
	_composed_atlas.visible = bool(_composed_state.get("formation_symbols", true))
	_composed_atlas.set_strength_text_enabled(_composed_lod != "full_theatre")


func _composed_counter_screen_position(pid: String, battalion: Dictionary, active_map, bounds: Rect2) -> Vector2:
	var counter_pixel: Vector2 = active_map.anchor_pixel(pid)
	var display_pixel: Variant = battalion.get("display_pixel", null)
	if display_pixel is Array and (display_pixel as Array).size() >= 2:
		counter_pixel = Vector2(float(display_pixel[0]), float(display_pixel[1]))
	return _clamp_point_in_rect(_image_to_screen(counter_pixel), bounds, OVERLAY_EDGE_PAD)


func _composed_icon_key(battalion_type: String) -> String:
	var kind := battalion_type.to_lower()
	if "airborne" in kind or "para" in kind:
		return "airborne"
	if "mechan" in kind:
		return "mechanized"
	if "motor" in kind:
		return "motorized"
	if "armor" in kind or "armour" in kind or "tank" in kind:
		return "armor"
	if "artillery" in kind or "arty" in kind:
		return "artillery"
	if "air_defense" in kind or "air defense" in kind or kind == "aa":
		return "air_defense"
	if "engineer" in kind:
		return "engineers"
	if "recon" in kind or "scout" in kind:
		return "recon"
	if "logistic" in kind or "support" in kind or "supply" in kind:
		return "logistics_support"
	if kind == "hq" or "command" in kind or "headquarter" in kind:
		return "hq_command"
	return "infantry"


func _refresh_composed_minimap() -> void:
	_composed_minimap_dirty = false
	if _composed_minimap == null or _presentation_candidate_cache == null or _presentation_candidate_cache.is_empty():
		return
	var active_map = _active_map()
	if active_map == null or not active_map.is_ready:
		return
	var selected_pixel := Vector2(-1, -1)
	if not selected_province_id.is_empty() and active_map.row_by_province.has(selected_province_id):
		selected_pixel = active_map.anchor_pixel(selected_province_id)
	_composed_minimap.configure(
		_presentation_candidate_cache,
		active_map.image_size(),
		selected_pixel,
		_composed_front_pixels()
	)


func _composed_front_pixels() -> Array:
	var points: Array = []
	var pending: Variant = snapshot.get("pending_battle", null)
	if pending is Dictionary:
		var encounter: Variant = (pending as Dictionary).get("encounter_pixel", null)
		if encounter is Array and (encounter as Array).size() >= 2:
			points.append(Vector2(float(encounter[0]), float(encounter[1])))
		elif encounter is Vector2:
			points.append(encounter as Vector2)
	for key in ["contacts", "battles"]:
		for row_value in presentation_fixture.get(key, []):
			if not row_value is Dictionary:
				continue
			var pixel_value: Variant = (row_value as Dictionary).get("pixel", null)
			if pixel_value is Array and (pixel_value as Array).size() >= 2:
				points.append(Vector2(float(pixel_value[0]), float(pixel_value[1])))
	return points


func _on_composed_layer_toggled(layer_key: String, enabled: bool) -> void:
	_composed_toggles[layer_key] = enabled
	_composed_lod = ""
	_sync_composed_lod()
	queue_redraw()


func _draw() -> void:
	if not composed_presentation_active:
		super._draw()
		return
	var suppress_debug: bool = not bool(_composed_state.get("debug_overlays", false))
	var old_debug: bool = bool(map_debug.enabled)
	var old_fronts: bool = bool(show_coalition_fronts)
	var old_crossings: bool = bool(show_crossing_overlay)
	if suppress_debug:
		map_debug.enabled = false
		show_coalition_fronts = false
		show_crossing_overlay = false
	super._draw()
	map_debug.enabled = old_debug
	show_coalition_fronts = old_fronts
	show_crossing_overlay = old_crossings


func _draw_color_id_overlays() -> void:
	if not composed_presentation_active:
		super._draw_color_id_overlays()
		return
	_ensure_snapshot_overlay_indexes()
	var active_map = _active_map()
	if active_map == null or not active_map.is_ready:
		return
	var bounds := _overlay_clamp_rect()
	var active_ids: Dictionary = _build_overlay_active_ids()
	var ids: Array = active_ids.keys()
	ids.sort()
	var reserved: Array = []
	var labels: Array = []
	var show_formations := bool(_composed_state.get("formation_symbols", true))
	var show_names := bool(_composed_state.get("names", true))
	var show_infra := bool(_composed_state.get("infrastructure_sites", true))
	var show_supply := bool(_composed_state.get("supply", true))

	for pid_value in ids:
		var pid := String(pid_value)
		if not active_map.row_by_province.has(pid):
			continue
		var province: Dictionary = _snap_by_id.get(pid, provinces_by_id.get(pid, {}))
		var battalion_value: Variant = battalions_by_province.get(pid, {})
		var battalion: Dictionary = battalion_value if battalion_value is Dictionary else {}
		var occupied := not battalion.is_empty()
		var selected := pid == selected_province_id
		var hovered := pid == hovered_province_id
		var target := legal_targets.has(pid)
		var anchor := _image_to_screen(active_map.anchor_pixel(pid))
		var position := _clamp_point_in_rect(anchor, bounds, OVERLAY_EDGE_PAD)

		if selected:
			MapMarkersScript.draw_selected_province_ring(self, position)
		elif hovered:
			MapMarkersScript.draw_hovered_province_ring(self, position)
		if position.distance_to(anchor) > 0.5 and (occupied or selected or hovered or target):
			draw_line(anchor, position, Color(0.85, 0.9, 0.95, 0.55), 1.0)
			draw_circle(anchor, 2.0, Color(0.85, 0.9, 0.95, 0.7))

		var infra: Dictionary = province.get("infrastructure", {})
		if show_infra:
			if int(infra.get("supply_hub", 0)) > 0:
				draw_rect(Rect2(position + Vector2(-13, 12), Vector2(6, 6)), Color("63d69f"))
			if int(infra.get("command_post", 0)) > 0:
				draw_rect(Rect2(position + Vector2(-4, 12), Vector2(6, 6)), Color("b892ff"))
			if int(infra.get("air_base", 0)) > 0:
				draw_circle(position + Vector2(8, 15), 3.2, Color("7fe7ff"))

		if occupied and show_formations:
			var counter_pos := _composed_counter_screen_position(pid, battalion, active_map, bounds)
			reserved.append(Rect2(counter_pos - Vector2(17, 13), Vector2(34, 26)))
			if show_supply and not bool(battalion.get("is_in_supply", true)):
				draw_arc(counter_pos, 22.0, 0.0, TAU, 30, Color("ff6b5f"), 2.4)
			if int(battalion.get("encircled_turns", 0)) > 0:
				draw_arc(counter_pos, 25.0, 0.0, TAU, 30, Color("ffb14e"), 2.4)
			var stack_value: Variant = battalion_stacks_by_province.get(pid, [])
			var stack: Array = stack_value if stack_value is Array else []
			if stack.size() > 1 and _composed_lod != "full_theatre":
				var badge := _clamp_point_in_rect(counter_pos + Vector2(19, -14), bounds, 12.0)
				reserved.append(MapMarkersScript.draw_stack_badge(self, badge, stack.size()))

		var critical := selected or hovered or target
		var allow_ambient := show_names and (_composed_lod != "full_theatre")
		if not critical and not allow_ambient:
			continue
		var label := _province_label(province, pid)
		var named := bool(province.get("name_is_human_readable", _is_named_province(label)))
		var priority := 0
		if selected:
			priority = 100
		elif hovered:
			priority = 90
		elif target:
			priority = 80
		elif occupied:
			priority = 70
		elif named and _composed_lod == "detailed":
			priority = 40
		if priority <= 0:
			continue
		var font_size := 12 if priority >= 70 else 11
		var text_w := float(ThemeDB.fallback_font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x)
		var text_pos := _clamp_point_in_rect(position + Vector2(13, -9), bounds, OVERLAY_EDGE_PAD)
		text_pos.x = minf(text_pos.x, bounds.end.x - text_w - 4.0)
		text_pos.y = clampf(text_pos.y, bounds.position.y + font_size, bounds.end.y - 4.0)
		labels.append({
			"priority": priority,
			"label": label,
			"pos": text_pos,
			"rect": Rect2(text_pos + Vector2(0, -font_size), Vector2(text_w + 4.0, float(font_size) + 4.0)),
			"font_size": font_size,
			"must_show": selected,
		})

	labels.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return int(a.get("priority", 0)) > int(b.get("priority", 0))
	)
	var occupied_rects := reserved.duplicate()
	var accepted_bounds: Array = []
	for candidate_value in labels:
		var candidate: Dictionary = candidate_value
		var rect: Rect2 = candidate.get("rect", Rect2())
		var blocked := false
		if not bool(candidate.get("must_show", false)):
			for prior_value in occupied_rects:
				if rect.intersects(prior_value as Rect2):
					blocked = true
					break
		if blocked:
			continue
		draw_string(
			ThemeDB.fallback_font,
			candidate.get("pos", Vector2.ZERO),
			String(candidate.get("label", "")),
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			int(candidate.get("font_size", 11)),
			Color(0.95, 0.96, 0.98, 0.98 if int(candidate.get("priority", 0)) >= 70 else 0.78)
		)
		occupied_rects.append(rect)
		accepted_bounds.append(rect)
	_cached_reserved_rects = reserved
	_cached_label_bounds = accepted_bounds


func _draw_selected_order_route() -> void:
	if composed_presentation_active and not bool(_composed_state.get("operational_routes", true)):
		return
	super._draw_selected_order_route()


func _draw_presentation_fixture_markers() -> void:
	if not composed_presentation_active or bool(_composed_state.get("operational_routes", true)):
		super._draw_presentation_fixture_markers()
		return
	var saved_routes: Variant = presentation_fixture.get("routes", null)
	presentation_fixture["routes"] = []
	super._draw_presentation_fixture_markers()
	if saved_routes == null:
		presentation_fixture.erase("routes")
	else:
		presentation_fixture["routes"] = saved_routes
