extends "res://scripts/main_writeback.gd"

const ColorIdMapScript = preload("res://scripts/color_id_map.gd")
const DEFAULT_MAP_MANIFEST := "res://assets/maps/europe/interim_goe/map_manifest.json"
const EM_FROM_GOE_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const HOME_MAP_MARGIN := Vector2(18, 18)
const HOME_FIT_FILL := 1.06
# Reserve space so title/diagnostic rows never cover the theatre.
const HEADER_SAFE_TOP := 64.0
const FOOTER_SAFE_BOTTOM := 28.0
const OVERLAY_EDGE_PAD := 18.0

var color_id_map = ColorIdMapScript.new()
var map_manifest_source_path := DEFAULT_MAP_MANIFEST
var hovered_province_id := ""
var show_coalition_fronts := false
var show_crossing_overlay := false
var _screenshot_path := ""
var _screenshot_frames_left := -1


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	var filtered: PackedStringArray = PackedStringArray()
	for arg in args:
		var text := String(arg)
		if text.begins_with("--screenshot="):
			_screenshot_path = text.substr(String("--screenshot=").length()).strip_edges()
			continue
		if text == "--crossings" or text == "--screenshot-crossings":
			show_crossing_overlay = true
			continue
		filtered.append(text)
	if filtered.size() > 1:
		map_manifest_source_path = String(filtered[1])
	super._ready()
	if filtered.size() <= 1:
		map_manifest_source_path = _resolve_map_manifest_path()
	_open_color_id_map()
	if not _screenshot_path.is_empty():
		_fit_complete_theatre()
		_screenshot_frames_left = 18
		set_process(true)
		queue_redraw()


func _process(_delta: float) -> void:
	if _screenshot_frames_left < 0:
		return
	_screenshot_frames_left -= 1
	queue_redraw()
	if _screenshot_frames_left > 0:
		return
	_screenshot_frames_left = -1
	set_process(false)
	call_deferred("_capture_screenshot_and_quit")


func _capture_screenshot_and_quit() -> void:
	if _screenshot_path.is_empty():
		return
	var image := get_viewport().get_texture().get_image()
	if image != null and not image.is_empty():
		image.save_png(_screenshot_path)
		status_message = "Saved screenshot err=0 path=%s ready=%s" % [
			_screenshot_path,
			str(color_id_map.is_ready),
		]
	get_tree().quit()


func _resolve_map_manifest_path() -> String:
	var contract: Dictionary = snapshot.get("strategic_map", {})
	var exported := String(contract.get("manifest_path", "")).strip_edges()
	if not exported.is_empty() and FileAccess.file_exists(exported):
		return exported
	var map_id := String(contract.get("map_id", ""))
	if map_id == "europe_mediterranean_from_goe" and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
		return EM_FROM_GOE_MANIFEST
	var campaign: Dictionary = snapshot.get("campaign", {})
	var meta: Dictionary = campaign.get("map_metadata", {})
	var configured := String(meta.get("strategic_map_id", ""))
	if configured == "europe_mediterranean_from_goe" and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
		return EM_FROM_GOE_MANIFEST
	if FileAccess.file_exists(DEFAULT_MAP_MANIFEST):
		return DEFAULT_MAP_MANIFEST
	return DEFAULT_MAP_MANIFEST


func _load_snapshot(path: String) -> void:
	super._load_snapshot(path)
	if color_id_map != null and color_id_map.is_ready:
		color_id_map.refresh_snapshot(snapshot, FACTION_COLORS)
		color_id_map.refresh_highlights(selected_province_id, legal_targets)


func _rebuild_legal_targets() -> void:
	super._rebuild_legal_targets()
	if color_id_map != null and color_id_map.is_ready:
		color_id_map.refresh_highlights(selected_province_id, legal_targets)


func _open_color_id_map() -> void:
	var previous_ready: bool = color_id_map != null and bool(color_id_map.is_ready)
	if color_id_map.open(map_manifest_source_path, snapshot, FACTION_COLORS):
		color_id_map.refresh_highlights(selected_province_id, legal_targets)
		status_message = "Color-ID province renderer active (%s)." % map_manifest_source_path.get_file()
		fitted_once = false
		_fit_complete_theatre()
	else:
		# Keep a previously successful open; only fall back if nothing is ready.
		if previous_ready:
			status_message = "%s Kept previous color-ID map." % color_id_map.error
		else:
			status_message = "%s Marker fallback remains non-authoritative." % color_id_map.error
	queue_redraw()


func _draw() -> void:
	if not color_id_map.is_ready:
		super._draw()
		return
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	draw_rect(Rect2(0, 0, map_width, viewport.y), Color(0.025, 0.035, 0.047, 1.0))
	var texture_rect := _map_texture_rect()
	if color_id_map.background_texture != null:
		draw_texture_rect(color_id_map.background_texture, texture_rect, false)
	if color_id_map.owner_texture != null:
		draw_texture_rect(color_id_map.owner_texture, texture_rect, false)
	if color_id_map.border_texture != null:
		draw_texture_rect(color_id_map.border_texture, texture_rect, false)
	if show_coalition_fronts:
		_draw_coalition_fronts()
	if show_crossing_overlay:
		_draw_crossing_overlay()
	if color_id_map.highlight_texture != null:
		draw_texture_rect(color_id_map.highlight_texture, texture_rect, false)
	_draw_color_id_pending_battle()
	_draw_color_id_overlays()

	var campaign: Dictionary = snapshot.get("campaign", {})
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	# Opaque header band so map never shows through title/status.
	draw_rect(Rect2(0, 0, map_width, HEADER_SAFE_TOP), Color(0.025, 0.035, 0.047, 0.96))
	var title := "%s  |  Turn %s  |  %s" % [
		campaign.get("name", "Gates of CodeX"),
		campaign.get("turn_number", 1),
		String(campaign.get("current_faction", "")).to_upper(),
	]
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, 28),
		title,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		20,
		Color.WHITE
	)
	var front_mode := "fronts:on" if show_coalition_fronts else "fronts:off"
	var cross_mode := "crossings:on" if show_crossing_overlay else "crossings:off"
	var diag := "Map: %s  |  Provinces: %s  |  %s  |  %s  |  %s" % [
		String(map_contract.get("map_id", campaign.get("map_id", ""))),
		int(snapshot.get("provinces", []).size()),
		color_id_map.background_status(),
		front_mode,
		cross_mode,
	]
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, 50),
		diag,
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 48,
		13,
		Color("9fd7ff")
	)
	draw_rect(
		Rect2(0, viewport.y - FOOTER_SAFE_BOTTOM, map_width, FOOTER_SAFE_BOTTOM),
		Color(0.025, 0.035, 0.047, 0.92)
	)
	var hint := "Home full  |  F front  |  G fronts  |  C crossings  |  click  |  wheel"
	if not status_message.is_empty():
		hint = status_message
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, viewport.y - 10),
		hint,
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 48,
		13,
		Color(0.78, 0.82, 0.86, 0.95)
	)
	_draw_management_panel()


func _draw_coalition_fronts() -> void:
	# Debug-only: orange lines are ownership-adjacency front segments, not province borders.
	for edge: Array in snapshot.get("edges", []):
		if edge.size() != 2:
			continue
		var left_id := String(edge[0])
		var right_id := String(edge[1])
		var left: Dictionary = provinces_by_id.get(left_id, {})
		var right: Dictionary = provinces_by_id.get(right_id, {})
		if left.is_empty() or right.is_empty():
			continue
		if String(left.get("owner", "neutral")) == String(right.get("owner", "neutral")):
			continue
		draw_line(
			_image_to_screen(color_id_map.anchor_pixel(left_id)),
			_image_to_screen(color_id_map.anchor_pixel(right_id)),
			Color(1.0, 0.76, 0.31, 0.35),
			1.0
		)


func _draw_crossing_overlay() -> void:
	# Debug topology: land / strait / ferry / sea-lane edges from manifest edge_types.
	var drawn: Dictionary = {}
	for province_id: Variant in color_id_map.row_by_province.keys():
		var pid := String(province_id)
		var row: Dictionary = color_id_map.row_by_province.get(pid, {})
		var edge_types: Dictionary = row.get("edge_types", {})
		if edge_types.is_empty():
			continue
		var origin := _image_to_screen(color_id_map.anchor_pixel(pid))
		for neighbor_id: Variant in edge_types.keys():
			var nid := String(neighbor_id)
			if not color_id_map.row_by_province.has(nid):
				continue
			var key := pid + "|" + nid if pid < nid else nid + "|" + pid
			if drawn.has(key):
				continue
			drawn[key] = true
			var etype := String(edge_types.get(nid, "land"))
			var target := _image_to_screen(color_id_map.anchor_pixel(nid))
			var color := Color(0.55, 0.58, 0.62, 0.22)
			var width := 1.0
			var label := ""
			if etype == "land":
				color = Color(0.45, 0.48, 0.52, 0.18)
				width = 1.0
			elif etype == "strait":
				color = Color(0.25, 0.85, 1.0, 0.75)
				width = 2.2
				label = "strait"
			elif etype == "ferry" or etype == "ferry_or_sea_lane":
				color = Color(0.35, 1.0, 0.55, 0.78)
				width = 2.0
				label = "ferry" if etype == "ferry" else "ferry/lane"
			elif etype == "sea_lane":
				color = Color(0.95, 0.75, 0.25, 0.80)
				width = 2.0
				label = "sea"
			else:
				color = Color(1.0, 0.4, 0.9, 0.7)
				width = 1.5
				label = etype
			# Land edges stay very faint; non-land get strong strokes + midpoint labels.
			if etype == "land":
				draw_line(origin, target, color, width)
			else:
				draw_line(origin, target, color, width)
				var mid := (origin + target) * 0.5
				if not label.is_empty():
					draw_string(
						ThemeDB.fallback_font,
						mid + Vector2(4, -4),
						label,
						HORIZONTAL_ALIGNMENT_LEFT,
						-1,
						11,
						color
					)


func _draw_color_id_pending_battle() -> void:
	var pending: Variant = snapshot.get("pending_battle")
	if not pending is Dictionary:
		return
	var battle := pending as Dictionary
	var origin_id := String(battle.get("origin_province_id", ""))
	var target_id := String(battle.get("target_province_id", ""))
	if not color_id_map.row_by_province.has(origin_id) or not color_id_map.row_by_province.has(target_id):
		return
	draw_line(
		_image_to_screen(color_id_map.anchor_pixel(origin_id)),
		_image_to_screen(color_id_map.anchor_pixel(target_id)),
		Color("ff9f43"),
		3.0
	)


func _draw_color_id_overlays() -> void:
	# Pass 1: facilities + counters (always). Pass 2: priority label declutter.
	# Counters/labels are clamped inside the map viewport (header/footer safe).
	var label_candidates: Array = []
	var reserved: Array = []  # Rect2 obstacles (counters first)
	var overlay_bounds := _overlay_clamp_rect()

	for province: Dictionary in snapshot.get("provinces", []):
		var province_id := String(province.get("id", ""))
		if not color_id_map.row_by_province.has(province_id):
			continue
		var anchor := _image_to_screen(color_id_map.anchor_pixel(province_id))
		var position := _clamp_point_in_rect(anchor, overlay_bounds, OVERLAY_EDGE_PAD)
		var shifted := position.distance_to(anchor) > 0.5
		var battalion: Dictionary = battalions_by_province.get(province_id, {})
		var occupied := not battalion.is_empty()
		var selected := province_id == selected_province_id
		var target := legal_targets.has(province_id)
		var owner := String(province.get("owner", "neutral"))
		var faction_color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])

		if shifted and (occupied or selected or target):
			draw_line(anchor, position, Color(0.85, 0.9, 0.95, 0.55), 1.0)
			draw_circle(anchor, 2.0, Color(0.85, 0.9, 0.95, 0.7))

		var infrastructure: Dictionary = province.get("infrastructure", {})
		if int(infrastructure.get("supply_hub", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-13, 12), Vector2(6, 6)), Color("63d69f"))
		if int(infrastructure.get("command_post", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-4, 12), Vector2(6, 6)), Color("b892ff"))
		if int(infrastructure.get("air_base", 0)) > 0:
			draw_circle(position + Vector2(8, 15), 3.2, Color("7fe7ff"))

		if occupied:
			if not bool(battalion.get("is_in_supply", true)):
				draw_arc(position, 22.0, 0.0, TAU, 30, Color("ff6b5f"), 2.4)
			if int(battalion.get("encircled_turns", 0)) > 0:
				draw_arc(position, 25.0, 0.0, TAU, 30, Color("ffb14e"), 2.4)
			_draw_battalion_counter(position, battalion, faction_color, selected)
			reserved.append(Rect2(position + Vector2(-18, -14), Vector2(36, 28)))
			var stack: Array = battalion_stacks_by_province.get(province_id, [])
			if stack.size() > 1:
				var badge := _clamp_point_in_rect(position + Vector2(19, -14), overlay_bounds, 10.0)
				draw_circle(badge, 8.5, Color(0.04, 0.055, 0.07, 0.98))
				draw_circle(badge, 8.5, Color.WHITE, false, 1.0)
				draw_string(
					ThemeDB.fallback_font,
					badge + Vector2(-3.5, 4.0),
					str(stack.size()),
					HORIZONTAL_ALIGNMENT_LEFT,
					-1,
					11,
					Color.WHITE
				)
				reserved.append(Rect2(badge + Vector2(-9, -9), Vector2(18, 18)))

		var label := _province_label(province, province_id)
		var named := bool(province.get("name_is_human_readable", _is_named_province(label)))
		var hovered := province_id == hovered_province_id
		var priority := 0
		if selected:
			priority = 100
		elif hovered:
			priority = 90
		elif target:
			priority = 80
		elif occupied:
			priority = 70
		elif named and view_scale >= 2.4:
			priority = 40
		# Full-theatre Home: suppress ambient names (declutter).
		if priority <= 0:
			continue
		var font_size := 12 if priority >= 70 else 11
		var text_w := float(ThemeDB.fallback_font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x)
		var raw_text_pos := position + Vector2(13, -9)
		var text_pos := _clamp_point_in_rect(raw_text_pos, overlay_bounds, OVERLAY_EDGE_PAD)
		# Keep label fully inside bounds.
		text_pos.x = minf(text_pos.x, overlay_bounds.position.x + overlay_bounds.size.x - text_w - 4.0)
		text_pos.y = clampf(text_pos.y, overlay_bounds.position.y + font_size, overlay_bounds.position.y + overlay_bounds.size.y - 4.0)
		var text_rect := Rect2(text_pos + Vector2(0, -font_size), Vector2(text_w + 4.0, float(font_size) + 4.0))
		label_candidates.append({
			"priority": priority,
			"label": label,
			"pos": text_pos,
			"rect": text_rect,
			"font_size": font_size,
			"color": Color(0.95, 0.96, 0.98, 0.98 if priority >= 70 else 0.78),
			"must_show": priority >= 90,
		})

	label_candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return int(a.get("priority", 0)) > int(b.get("priority", 0))
	)
	for candidate: Dictionary in label_candidates:
		var rect: Rect2 = candidate.get("rect", Rect2())
		var blocked := false
		if not bool(candidate.get("must_show", false)):
			for prior: Variant in reserved:
				if rect.intersects(prior as Rect2):
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
			candidate.get("color", Color.WHITE)
		)
		reserved.append(rect)


func _province_at(screen_position: Vector2) -> String:
	if not color_id_map.is_ready:
		return super._province_at(screen_position)
	var rect := _map_texture_rect()
	if not rect.has_point(screen_position):
		return ""
	var normalized := (screen_position - rect.position) / rect.size
	var size := color_id_map.image_size()
	var pixel := Vector2i(
		clampi(floori(normalized.x * size.x), 0, int(size.x) - 1),
		clampi(floori(normalized.y * size.y), 0, int(size.y) - 1)
	)
	return color_id_map.province_at_pixel(pixel)


func _map_to_screen(province: Dictionary) -> Vector2:
	if color_id_map != null and color_id_map.is_ready:
		return _image_to_screen(color_id_map.anchor_pixel(String(province.get("id", ""))))
	return super._map_to_screen(province)


func _image_to_screen(pixel: Vector2) -> Vector2:
	var rect := _map_texture_rect()
	return rect.position + (pixel / color_id_map.image_size()) * rect.size


func _map_content_rect() -> Rect2:
	# Usable map panel excluding header/footer chrome and side panel.
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	return Rect2(
		Vector2(HOME_MAP_MARGIN.x, HEADER_SAFE_TOP + HOME_MAP_MARGIN.y),
		Vector2(
			map_width - HOME_MAP_MARGIN.x * 2.0,
			viewport.y - HEADER_SAFE_TOP - FOOTER_SAFE_BOTTOM - HOME_MAP_MARGIN.y * 2.0
		)
	)


func _map_texture_rect() -> Rect2:
	var content := _map_content_rect()
	var image_size := color_id_map.image_size()
	var fit_scale := minf(content.size.x / image_size.x, content.size.y / image_size.y)
	var rendered_size := image_size * fit_scale * view_scale
	var origin := content.position + (content.size - rendered_size) * 0.5 + view_offset
	return Rect2(origin, rendered_size)


func _overlay_clamp_rect() -> Rect2:
	# Keep counters/labels fully inside the visible map panel (under header).
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	return Rect2(
		Vector2(4.0, HEADER_SAFE_TOP + 4.0),
		Vector2(map_width - 8.0, viewport.y - HEADER_SAFE_TOP - FOOTER_SAFE_BOTTOM - 8.0)
	)


func _clamp_point_in_rect(point: Vector2, bounds: Rect2, pad: float) -> Vector2:
	return Vector2(
		clampf(point.x, bounds.position.x + pad, bounds.position.x + bounds.size.x - pad),
		clampf(point.y, bounds.position.y + pad, bounds.position.y + bounds.size.y - pad)
	)


func _province_label(province: Dictionary, province_id: String) -> String:
	var label := String(province.get("display_name", province_id)).strip_edges()
	if label.is_empty():
		return province_id
	# Prefer manifest source name when campaign still has a generic label.
	if not _is_named_province(label) and color_id_map != null and color_id_map.row_by_province.has(province_id):
		var row: Dictionary = color_id_map.row_by_province[province_id]
		var source_label := String(row.get("display_name", "")).strip_edges()
		if _is_named_province(source_label):
			return source_label
	return label


func _is_named_province(label: String) -> bool:
	var lower := label.to_lower().strip_edges()
	if lower.is_empty():
		return false
	if lower.begins_with("province"):
		return false
	return true


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		var key := event as InputEventKey
		if key.keycode == KEY_G:
			show_coalition_fronts = not show_coalition_fronts
			status_message = (
				"Coalition front lines ON (ownership-adjacency debug). Press G to hide."
				if show_coalition_fronts
				else "Coalition front lines OFF."
			)
			queue_redraw()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_C:
			show_crossing_overlay = not show_crossing_overlay
			status_message = (
				"Crossing overlay ON (land faint / strait cyan / ferry green / sea gold). Press C to hide."
				if show_crossing_overlay
				else "Crossing overlay OFF."
			)
			queue_redraw()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_HOME:
			_fit_complete_theatre()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_F:
			_fit_to_focus(true)
			get_viewport().set_input_as_handled()
			return
	if event is InputEventMouseMotion and color_id_map != null and color_id_map.is_ready:
		var motion := event as InputEventMouseMotion
		var map_width := get_viewport_rect().size.x - PANEL_WIDTH
		var next_hover := ""
		if motion.position.x < map_width:
			next_hover = _province_at(motion.position)
		if next_hover != hovered_province_id:
			hovered_province_id = next_hover
			queue_redraw()
	super._unhandled_input(event)


func _fit_complete_theatre() -> void:
	if color_id_map == null or not color_id_map.is_ready:
		view_scale = HOME_FIT_FILL
		view_offset = Vector2.ZERO
		fitted_once = true
		status_message = "Fitted full theatre."
		queue_redraw()
		return
	# Fill more of the map panel while keeping aspect ratio; panel stays clear.
	view_scale = HOME_FIT_FILL
	view_offset = Vector2.ZERO
	fitted_once = true
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	status_message = "Fitted complete theatre (%s provinces). Home=full  F=front." % [
		int(snapshot.get("provinces", []).size())
	]
	if not String(map_contract.get("map_id", "")).is_empty():
		status_message = "Fitted complete theatre map %s (%s provinces)." % [
			String(map_contract.get("map_id", "")),
			int(snapshot.get("provinces", []).size()),
		]
	queue_redraw()


func _fit_to_focus(force: bool) -> void:
	if color_id_map == null or not color_id_map.is_ready:
		super._fit_to_focus(force)
		return
	if fitted_once and not force:
		return
	var ids: Dictionary = {}
	for id: Variant in focus_province_ids.keys():
		ids[String(id)] = true
	var campaign: Dictionary = snapshot.get("campaign", {})
	var current := String(campaign.get("current_faction", ""))
	for battalion: Dictionary in snapshot.get("battalions", []):
		if String(battalion.get("faction", "")) == current:
			ids[String(battalion.get("province_id", ""))] = true
	for option: Dictionary in snapshot.get("front_options", []):
		ids[String(option.get("origin", ""))] = true
		ids[String(option.get("target", ""))] = true
	var pending: Variant = snapshot.get("pending_battle")
	if pending is Dictionary:
		var battle := pending as Dictionary
		ids[String(battle.get("origin_province_id", ""))] = true
		ids[String(battle.get("target_province_id", ""))] = true

	var min_x := INF
	var min_y := INF
	var max_x := -INF
	var max_y := -INF
	var count := 0
	for id: Variant in ids.keys():
		var province_id := String(id)
		if province_id.is_empty() or not color_id_map.row_by_province.has(province_id):
			continue
		var anchor := color_id_map.anchor_pixel(province_id)
		min_x = minf(min_x, anchor.x)
		max_x = maxf(max_x, anchor.x)
		min_y = minf(min_y, anchor.y)
		max_y = maxf(max_y, anchor.y)
		count += 1
	if count < 4:
		_fit_complete_theatre()
		status_message = "Fit Front had <4 nodes; fell back to complete theatre."
		return
	var image_size := color_id_map.image_size()
	var span := Vector2(maxf(max_x - min_x, 48.0), maxf(max_y - min_y, 48.0))
	var padding := 1.45
	view_scale = clampf(minf(image_size.x / (span.x * padding), image_size.y / (span.y * padding)), 1.0, 4.5)
	view_offset = Vector2.ZERO
	var focus_center := Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var map_center := Vector2(
		(get_viewport_rect().size.x - PANEL_WIDTH) * 0.5,
		get_viewport_rect().size.y * 0.5
	)
	view_offset = map_center - _image_to_screen(focus_center)
	fitted_once = true
	status_message = "Fitted operational front (%s provinces). Home=full theatre." % count
	queue_redraw()
