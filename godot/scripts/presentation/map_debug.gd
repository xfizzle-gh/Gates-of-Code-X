class_name MapDebug
extends RefCounted

## Developer-only strategic map debug overlay. Disabled for ordinary player presentation.

var enabled := false
var show_province_ids := true
var show_anchors := true
var show_bounds := true
var show_fps := true
var show_coords := true
var show_operational_graph := true
var show_control_sites := true
var show_counters_bounds := true
var show_invalidation := true

var fps_value := 0.0
var frame_ms := 0.0
var redraw_count := 0
var invalidation_count := 0
var last_hover_id := ""
var last_selected_id := ""
var last_map_pixel := Vector2i.ZERO
var last_screen_pos := Vector2.ZERO
var last_event := "none"
var last_perf: Dictionary = {}
var counter_bounds: Array = []
var label_bounds: Array = []
var _fps_frames := 0
var _fps_accum := 0.0


func toggle() -> void:
	enabled = not enabled


func note_redraw() -> void:
	if enabled:
		redraw_count += 1


func note_invalidation(event := "invalidate") -> void:
	if enabled:
		invalidation_count += 1
		last_event = event


func capture_perf(stats: Dictionary) -> void:
	last_perf = stats.duplicate()
	if not String(stats.get("last_event", "")).is_empty():
		last_event = String(stats.get("last_event", last_event))


func tick_fps(delta: float) -> void:
	if not enabled:
		return
	_fps_frames += 1
	_fps_accum += delta
	if _fps_accum >= 0.5:
		fps_value = float(_fps_frames) / _fps_accum
		frame_ms = (1000.0 * _fps_accum) / float(maxi(_fps_frames, 1))
		_fps_frames = 0
		_fps_accum = 0.0


func draw(
	canvas: CanvasItem,
	map_space: MapSpace,
	color_id_map,
	selected_id: String,
	hovered_id: String,
	presentation_fixture: Dictionary,
	overlay_bounds: Rect2
) -> void:
	if not enabled:
		return
	note_redraw()
	last_selected_id = selected_id
	last_hover_id = hovered_id

	if show_anchors and color_id_map != null and color_id_map.is_ready:
		for province_id: Variant in color_id_map.row_by_province.keys():
			var pid := String(province_id)
			var anchor := map_space.image_to_screen(color_id_map.anchor_pixel(pid))
			canvas.draw_circle(anchor, 1.6, Color(0.9, 0.95, 1.0, 0.35))
			if show_province_ids and (pid == selected_id or pid == hovered_id):
				canvas.draw_string(
					ThemeDB.fallback_font,
					anchor + Vector2(6, -6),
					pid,
					HORIZONTAL_ALIGNMENT_LEFT,
					-1,
					10,
					Color(0.75, 0.95, 1.0, 0.95)
				)

	if show_bounds:
		canvas.draw_rect(map_space.texture_rect(), Color(0.3, 0.85, 1.0, 0.35), false, 1.0)
		canvas.draw_rect(overlay_bounds, Color(1.0, 0.7, 0.2, 0.35), false, 1.0)

	if show_counters_bounds:
		for rect_variant in counter_bounds:
			if rect_variant is Rect2:
				canvas.draw_rect(rect_variant as Rect2, Color(0.4, 1.0, 0.5, 0.5), false, 1.0)
		for rect_variant in label_bounds:
			if rect_variant is Rect2:
				canvas.draw_rect(rect_variant as Rect2, Color(1.0, 0.5, 0.9, 0.45), false, 1.0)

	if show_operational_graph:
		_draw_fixture_graph(canvas, map_space, presentation_fixture)

	if show_control_sites:
		for site: Variant in presentation_fixture.get("control_sites", []):
			if not site is Dictionary:
				continue
			var row := site as Dictionary
			var pos := MapMarkers.battle_marker_position(row, map_space)
			if pos == Vector2.ZERO and row.has("pixel"):
				var px: Variant = row.get("pixel")
				if px is Array and (px as Array).size() >= 2:
					pos = map_space.image_to_screen(Vector2(float(px[0]), float(px[1])))
			if pos == Vector2.ZERO:
				continue
			MapMarkers.draw_control_site_marker(canvas, pos, bool(row.get("owned", false)))
			if int(row.get("presentation_capture_progress_fp", -1)) >= 0:
				MapMarkers.draw_capture_progress(
					canvas,
					pos + Vector2(16, 0),
					int(row.get("presentation_capture_progress_fp", 0)),
					int(row.get("presentation_capture_max_fp", 1000))
				)

	if show_fps or show_coords or show_invalidation:
		var lines: PackedStringArray = PackedStringArray()
		if show_fps:
			lines.append("FPS %s  frame %sms" % [snappedf(fps_value, 0.1), snappedf(frame_ms, 0.01)])
		if show_invalidation:
			lines.append("redraws %s  invalidations %s" % [redraw_count, invalidation_count])
			lines.append("last_event %s" % last_event)
			var stats: Dictionary = last_perf
			if stats.is_empty() and color_id_map != null and color_id_map.has_method("get_perf_stats"):
				stats = color_id_map.get_perf_stats()
			if not stats.is_empty():
				lines.append(
					"owner full/partial %s/%s  hl %s  px %s" % [
						stats.get("full_owner_rebuilds", 0),
						stats.get("partial_owner_rebuilds", 0),
						stats.get("highlight_rebuilds", 0),
						stats.get("pixels_touched_last", 0),
					]
				)
				lines.append(
					"rebuilds pending %s  displayed %s  owner_ms %s  hl_ms %s" % [
						stats.get("static_rebuilds_this_frame", 0),
						stats.get("static_rebuilds_displayed", 0),
						stats.get("owner_rebuild_ms_last", 0),
						stats.get("highlight_rebuild_ms_last", 0),
					]
				)
			lines.append("counters %s  labels %s" % [counter_bounds.size(), label_bounds.size()])
		if show_coords:
			lines.append("hover %s  selected %s" % [hovered_id, selected_id])
			lines.append("screen %s  map_px %s" % [last_screen_pos, last_map_pixel])
		var y := overlay_bounds.position.y + 14.0
		for line in lines:
			canvas.draw_string(
				ThemeDB.fallback_font,
				Vector2(overlay_bounds.position.x + 8.0, y),
				line,
				HORIZONTAL_ALIGNMENT_LEFT,
				-1,
				12,
				Color(0.85, 1.0, 0.75, 0.95)
			)
			y += 14.0


func _draw_fixture_graph(canvas: CanvasItem, map_space: MapSpace, fixture: Dictionary) -> void:
	for edge: Variant in fixture.get("operational_edges", []):
		if not edge is Dictionary:
			continue
		var row := edge as Dictionary
		var a: Variant = row.get("a_pixel", null)
		var b: Variant = row.get("b_pixel", null)
		if not (a is Array and b is Array):
			continue
		if (a as Array).size() < 2 or (b as Array).size() < 2:
			continue
		var pa := map_space.image_to_screen(Vector2(float(a[0]), float(a[1])))
		var pb := map_space.image_to_screen(Vector2(float(b[0]), float(b[1])))
		canvas.draw_line(pa, pb, Color(0.4, 0.75, 1.0, 0.35), 1.0)
	for node: Variant in fixture.get("operational_nodes", []):
		if not node is Dictionary:
			continue
		var nrow := node as Dictionary
		var px: Variant = nrow.get("pixel", null)
		if not (px is Array and (px as Array).size() >= 2):
			continue
		var p := map_space.image_to_screen(Vector2(float(px[0]), float(px[1])))
		canvas.draw_circle(p, 2.5, Color(0.55, 0.85, 1.0, 0.8))
