extends "res://scripts/main_stack_panel.gd"

## Post-P5 responsiveness layer (#207).
##
## 1. Player End Turn submits one backend operation. Python owns the canonical
##    human -> AI -> human cycle and stops cleanly if a pending battle appears.
##    The file-backed bridge therefore pays for one load/save/snapshot cycle.
## 2. The polygon/color-ID overlay never scans/draws ambient province names.
##    Selected, hovered, occupied and legal-target labels remain.
##
## This script does not alter operational graph authority or campaign rules.


func _handle_button(button_id: String) -> void:
	if button_id == "end_turn":
		status_message = "Ending turn + resolving AI round..."
		_queue_and_apply([{"op": "end_player_round"}])
		return
	super._handle_button(button_id)


func _draw_button(id: String, label: String, x: float, y: float, enabled: bool, fill := Color("1a2a38")) -> float:
	if id == "end_turn":
		label = "End turn + AI cycle (E)"
	elif id == "run_ai":
		label = "Run current AI only"
	elif id == "verify_result" and _pending_battle_handoff_ready():
		# A fresh Godot process no longer has the transient handoff command
		# payload, but the authoritative pending battle persists started=true and
		# exported_save_path. The backend can resolve that exact save itself, so
		# the rendered control must match enabled_action_button_ids().
		enabled = enabled or bool(snapshot.get("control", {}).get("enabled", false))
	return super._draw_button(id, label, x, y, enabled, fill)


func _draw_color_id_overlays() -> void:
	## Bounded overlay pass. The former high-zoom branch scanned all ~3.5k
	## provinces and considered every human-readable name for collision/layout.
	## That is both visually noisy and unnecessarily expensive. Ordinary map
	## identity comes from the polygon layer; text is reserved for actionable
	## context only.
	var am = _active_map()
	if am == null or not am.is_ready:
		return
	_ensure_snapshot_overlay_indexes()
	var overlay_bounds := _overlay_clamp_rect()
	var active_ids := _build_overlay_active_ids()
	var active_keys: Array = active_ids.keys()
	active_keys.sort()
	var reserved: Array = []
	var label_candidates: Array = []

	for key: Variant in active_keys:
		var province_id := String(key)
		if not am.row_by_province.has(province_id):
			continue
		var province: Dictionary = _snap_by_id.get(
			province_id,
			{"id": province_id, "owner": "neutral", "infrastructure": {}}
		)
		var battalion: Dictionary = battalions_by_province.get(province_id, {})
		var occupied := not battalion.is_empty()
		var selected := province_id == selected_province_id
		var target := legal_targets.has(province_id)
		var hovered := province_id == hovered_province_id
		var infrastructure: Dictionary = province.get("infrastructure", {})
		var anchor := _image_to_screen(am.anchor_pixel(province_id))
		var position := _clamp_point_in_rect(anchor, overlay_bounds, OVERLAY_EDGE_PAD)
		var shifted := position.distance_to(anchor) > 0.5
		var owner := String(province.get("owner", "neutral"))
		var faction_color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])

		if selected:
			MapMarkersScript.draw_selected_province_ring(self, position)
		elif hovered:
			MapMarkersScript.draw_hovered_province_ring(self, position)

		if shifted and (occupied or selected or target or hovered):
			draw_line(anchor, position, Color(0.85, 0.9, 0.95, 0.55), 1.0)
			draw_circle(anchor, 2.0, Color(0.85, 0.9, 0.95, 0.7))

		if int(infrastructure.get("supply_hub", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-13, 12), Vector2(6, 6)), Color("63d69f"))
		if int(infrastructure.get("command_post", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-4, 12), Vector2(6, 6)), Color("b892ff"))
		if int(infrastructure.get("air_base", 0)) > 0:
			draw_circle(position + Vector2(8, 15), 3.2, Color("7fe7ff"))

		if occupied:
			var show_counter := view_scale >= 0.95 or selected or hovered or target
			if show_counter:
				var counter_pos := position
				var display_pixel: Variant = battalion.get("display_pixel", null)
				if display_pixel is Array and (display_pixel as Array).size() >= 2:
					counter_pos = _clamp_point_in_rect(
						_image_to_screen(Vector2(
							float((display_pixel as Array)[0]),
							float((display_pixel as Array)[1])
						)),
						overlay_bounds,
						OVERLAY_EDGE_PAD
					)
				if not bool(battalion.get("is_in_supply", true)):
					draw_arc(counter_pos, 22.0, 0.0, TAU, 30, Color("ff6b5f"), 2.4)
				if int(battalion.get("encircled_turns", 0)) > 0:
					draw_arc(counter_pos, 25.0, 0.0, TAU, 30, Color("ffb14e"), 2.4)
				var counter_rect := MapMarkersScript.draw_formation_counter(
					self,
					counter_pos,
					faction_color,
					MapMarkersScript.battalion_type_glyph(String(battalion.get("battalion_type", ""))),
					int(battalion.get("unit_count", 0)),
					selected,
					bool(battalion.get("is_in_supply", true)),
					int(battalion.get("encircled_turns", 0)) > 0,
					String(battalion.get("strategic_formation_id", ""))
				)
				reserved.append(counter_rect)
				var stack: Array = battalion_stacks_by_province.get(province_id, [])
				if stack.size() > 1 and view_scale >= 1.15:
					var badge := _clamp_point_in_rect(counter_pos + Vector2(19, -14), overlay_bounds, 12.0)
					reserved.append(MapMarkersScript.draw_stack_badge(self, badge, stack.size()))

		# Labels are action context, not wallpaper. No ambient high-zoom names.
		var priority := 0
		if selected:
			priority = 100
		elif target:
			priority = 80
		elif occupied:
			priority = 70
		elif hovered:
			priority = 60
		if priority <= 0:
			continue
		var label := _province_label(province, province_id)
		var font_size := 12 if priority >= 70 else 11
		var text_w := float(ThemeDB.fallback_font.get_string_size(
			label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size
		).x)
		var text_pos := _clamp_point_in_rect(
			position + Vector2(13, -9), overlay_bounds, OVERLAY_EDGE_PAD
		)
		text_pos.x = minf(
			text_pos.x,
			overlay_bounds.position.x + overlay_bounds.size.x - text_w - 4.0
		)
		text_pos.y = clampf(
			text_pos.y,
			overlay_bounds.position.y + font_size,
			overlay_bounds.position.y + overlay_bounds.size.y - 4.0
		)
		var text_rect := Rect2(
			text_pos + Vector2(0, -font_size),
			Vector2(text_w + 4.0, float(font_size) + 4.0)
		)
		label_candidates.append({
			"priority": priority,
			"label": label,
			"pos": text_pos,
			"rect": text_rect,
			"font_size": font_size,
			"color": Color(0.95, 0.96, 0.98, 0.98),
			"must_show": selected,
			"province_id": province_id,
		})

	label_candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		var ap := int(a.get("priority", 0))
		var bp := int(b.get("priority", 0))
		if ap != bp:
			return ap > bp
		return String(a.get("province_id", "")) < String(b.get("province_id", ""))
	)
	var accepted: Array = []
	var accepted_bounds: Array = []
	var occupied_rects: Array = reserved.duplicate()
	for candidate: Dictionary in label_candidates:
		var rect: Rect2 = candidate.get("rect", Rect2())
		var blocked := false
		if not bool(candidate.get("must_show", false)):
			for prior: Variant in occupied_rects:
				if rect.intersects(prior as Rect2):
					blocked = true
					break
		if blocked:
			continue
		accepted.append(candidate)
		accepted_bounds.append(rect)
		occupied_rects.append(rect)

	_cached_label_candidates = accepted
	_cached_label_bounds = accepted_bounds
	_cached_reserved_rects = reserved.duplicate()
	for candidate: Dictionary in accepted:
		draw_string(
			ThemeDB.fallback_font,
			candidate.get("pos", Vector2.ZERO),
			String(candidate.get("label", "")),
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			int(candidate.get("font_size", 11)),
			candidate.get("color", Color.WHITE)
		)
