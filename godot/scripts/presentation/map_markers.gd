class_name MapMarkers
extends RefCounted

## Godot-only presentation primitives for the strategic map.
## Inputs are generic view-model dictionaries. Presentation-only mock fields must be
## prefixed with `presentation_` and never treated as simulation authority.

const COUNTER_SIZE := Vector2(34, 22)


static func draw_selected_province_ring(canvas: CanvasItem, center: Vector2, radius := 18.0) -> void:
	canvas.draw_arc(center, radius, 0.0, TAU, 36, Color("7fe7ff"), 2.4)


static func draw_hovered_province_ring(canvas: CanvasItem, center: Vector2, radius := 15.0) -> void:
	canvas.draw_arc(center, radius, 0.0, TAU, 28, Color(1.0, 1.0, 1.0, 0.55), 1.6)


static func draw_formation_counter(
	canvas: CanvasItem,
	center: Vector2,
	faction_color: Color,
	type_glyph: String,
	strength: int,
	selected: bool,
	in_supply := true,
	encircled := false
) -> Rect2:
	var rect := Rect2(center - COUNTER_SIZE * 0.5 + Vector2(0, -2), COUNTER_SIZE)
	var fill := faction_color.darkened(0.25)
	fill.a = 0.95
	canvas.draw_rect(rect, fill)
	canvas.draw_rect(rect, Color.WHITE if selected else Color(0.1, 0.1, 0.12, 0.95), false, 1.5)
	if not in_supply:
		canvas.draw_rect(Rect2(rect.position, Vector2(4, rect.size.y)), Color("ff6b5f"))
	if encircled:
		canvas.draw_rect(Rect2(rect.position + Vector2(rect.size.x - 4, 0), Vector2(4, rect.size.y)), Color("ffb14e"))
	var label := "%s %s" % [type_glyph, strength]
	canvas.draw_string(
		ThemeDB.fallback_font,
		rect.position + Vector2(6, 15),
		label,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		12,
		Color.WHITE
	)
	return rect


static func draw_stack_badge(canvas: CanvasItem, anchor: Vector2, count: int) -> Rect2:
	var badge_rect := Rect2(anchor - Vector2(11, 9), Vector2(30, 18))
	canvas.draw_rect(badge_rect, Color(0.04, 0.06, 0.09, 0.96))
	canvas.draw_rect(badge_rect, Color.WHITE, false, 1.2)
	canvas.draw_string(
		ThemeDB.fallback_font,
		anchor + Vector2(-7, 4),
		"x%s" % count,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		11,
		Color.WHITE
	)
	return badge_rect


static func draw_route_line(canvas: CanvasItem, points: PackedVector2Array, color := Color("7fe7ff"), width := 2.0) -> void:
	if points.size() < 2:
		return
	for i in range(points.size() - 1):
		canvas.draw_line(points[i], points[i + 1], color, width)
		canvas.draw_circle(points[i], 2.5, color)
	canvas.draw_circle(points[points.size() - 1], 3.0, color)


static func draw_node_contact_marker(canvas: CanvasItem, center: Vector2) -> void:
	canvas.draw_circle(center, 7.0, Color(1.0, 0.55, 0.2, 0.85))
	canvas.draw_arc(center, 10.0, 0.0, TAU, 24, Color(1.0, 0.75, 0.35, 0.9), 2.0)


static func draw_edge_contact_marker(canvas: CanvasItem, center: Vector2) -> void:
	var a := center + Vector2(-8, -5)
	var b := center + Vector2(8, 5)
	var c := center + Vector2(-8, 5)
	var d := center + Vector2(8, -5)
	canvas.draw_line(a, b, Color(1.0, 0.45, 0.2, 0.95), 2.4)
	canvas.draw_line(c, d, Color(1.0, 0.45, 0.2, 0.95), 2.4)
	canvas.draw_circle(center, 3.0, Color(1.0, 0.85, 0.4, 0.95))


static func draw_crossed_swords_battle_marker(canvas: CanvasItem, center: Vector2, scale := 1.0) -> void:
	var s := 10.0 * scale
	var color := Color("ff9f43")
	canvas.draw_line(center + Vector2(-s, -s), center + Vector2(s, s), color, 2.6)
	canvas.draw_line(center + Vector2(-s, s), center + Vector2(s, -s), color, 2.6)
	canvas.draw_circle(center, 3.5 * scale, Color(0.05, 0.05, 0.07, 0.9))
	canvas.draw_circle(center, 2.2 * scale, color)


static func draw_control_site_marker(canvas: CanvasItem, center: Vector2, owned := false) -> void:
	var fill := Color("63d69f") if owned else Color("b8c0c8")
	var points := PackedVector2Array([
		center + Vector2(0, -7),
		center + Vector2(7, 0),
		center + Vector2(0, 7),
		center + Vector2(-7, 0),
	])
	canvas.draw_colored_polygon(points, fill)
	canvas.draw_polyline(points + PackedVector2Array([points[0]]), Color(0.05, 0.06, 0.08, 0.95), 1.2, true)


static func draw_capture_progress(canvas: CanvasItem, center: Vector2, progress_fp: int, max_fp := 1000) -> void:
	# Fixed-point progress 0..max_fp — no simulation float authority.
	var t := clampf(float(progress_fp) / float(maxi(max_fp, 1)), 0.0, 1.0)
	var radius := 12.0
	canvas.draw_arc(center, radius, 0.0, TAU, 32, Color(0.1, 0.12, 0.14, 0.85), 3.0)
	if t > 0.0:
		canvas.draw_arc(center, radius, -PI * 0.5, -PI * 0.5 + TAU * t, 32, Color("ffb14e"), 3.0)
	canvas.draw_string(
		ThemeDB.fallback_font,
		center + Vector2(-10, 4),
		"%s%%" % int(round(t * 100.0)),
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		10,
		Color.WHITE
	)


static func battle_marker_position(marker: Dictionary, map_space: MapSpace) -> Vector2:
	## Resolve a battle/contact marker from generic presentation inputs:
	## - pixel: [x, y] image pixels
	## - node_pixel / presentation_node_pixel
	## - edge: presentation_edge_a_pixel + presentation_edge_b_pixel + progress_fp (0..1000)
	if marker.has("pixel"):
		var px: Variant = marker.get("pixel")
		if px is Array and (px as Array).size() >= 2:
			return map_space.image_to_screen(Vector2(float(px[0]), float(px[1])))
	if marker.has("presentation_pixel"):
		var pp: Variant = marker.get("presentation_pixel")
		if pp is Array and (pp as Array).size() >= 2:
			return map_space.image_to_screen(Vector2(float(pp[0]), float(pp[1])))
	if marker.has("node_pixel"):
		var np: Variant = marker.get("node_pixel")
		if np is Array and (np as Array).size() >= 2:
			return map_space.image_to_screen(Vector2(float(np[0]), float(np[1])))
	var a: Variant = marker.get("presentation_edge_a_pixel", marker.get("edge_a_pixel", null))
	var b: Variant = marker.get("presentation_edge_b_pixel", marker.get("edge_b_pixel", null))
	if a is Array and b is Array and (a as Array).size() >= 2 and (b as Array).size() >= 2:
		var progress_fp := int(marker.get("presentation_progress_fp", marker.get("progress_fp", 500)))
		progress_fp = clampi(progress_fp, 0, 1000)
		var t := float(progress_fp) / 1000.0
		var pa := Vector2(float(a[0]), float(a[1]))
		var pb := Vector2(float(b[0]), float(b[1]))
		return map_space.image_to_screen(pa.lerp(pb, t))
	return Vector2.ZERO


static func battalion_type_glyph(battalion_type: String) -> String:
	var key := battalion_type.to_lower()
	if "armor" in key or "tank" in key:
		return "T"
	if "mech" in key:
		return "M"
	if "motor" in key:
		return "m"
	if "art" in key:
		return "A"
	if "air" in key:
		return "A"
	if "inf" in key:
		return "I"
	return "X"
