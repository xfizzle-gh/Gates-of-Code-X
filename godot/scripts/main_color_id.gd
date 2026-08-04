extends "res://scripts/main_writeback.gd"

const ColorIdMapScript = preload("res://scripts/color_id_map.gd")
const DEFAULT_MAP_MANIFEST := "res://assets/maps/europe/interim_goe/map_manifest.json"
const EM_MAP_MANIFEST := "res://assets/maps/europe_mediterranean/prototype/map_manifest.json"

var color_id_map = ColorIdMapScript.new()
var map_manifest_source_path := DEFAULT_MAP_MANIFEST
var hovered_province_id := ""


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() > 1:
		map_manifest_source_path = String(args[1])
	super._ready()
	if args.size() <= 1:
		map_manifest_source_path = _resolve_map_manifest_path()
	_open_color_id_map()


func _resolve_map_manifest_path() -> String:
	var contract: Dictionary = snapshot.get("strategic_map", {})
	var exported := String(contract.get("manifest_path", "")).strip_edges()
	if not exported.is_empty() and FileAccess.file_exists(exported):
		return exported
	var map_id := String(contract.get("map_id", ""))
	if map_id == "europe_mediterranean_prototype" and FileAccess.file_exists(EM_MAP_MANIFEST):
		return EM_MAP_MANIFEST
	if map_id in ["goe_europe", "interim_goe_europe"] and FileAccess.file_exists(DEFAULT_MAP_MANIFEST):
		return DEFAULT_MAP_MANIFEST
	var campaign: Dictionary = snapshot.get("campaign", {})
	var meta: Dictionary = campaign.get("map_metadata", {})
	var configured := String(meta.get("strategic_map_id", ""))
	if configured == "europe_mediterranean_prototype" and FileAccess.file_exists(EM_MAP_MANIFEST):
		return EM_MAP_MANIFEST
	if configured in ["goe_europe", "interim_goe_europe"] and FileAccess.file_exists(DEFAULT_MAP_MANIFEST):
		return DEFAULT_MAP_MANIFEST
	# Prefer EM prototype when present and campaign is EM; else Europe fallback.
	if map_id == "europe_mediterranean_prototype" or configured == "europe_mediterranean_prototype":
		if FileAccess.file_exists(EM_MAP_MANIFEST):
			return EM_MAP_MANIFEST
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
	if color_id_map.open(map_manifest_source_path, snapshot, FACTION_COLORS):
		color_id_map.refresh_highlights(selected_province_id, legal_targets)
		status_message = "Color-ID province renderer active."
		fitted_once = false
		_fit_to_focus(true)
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
	if color_id_map.owner_texture != null:
		draw_texture_rect(color_id_map.owner_texture, texture_rect, false)
	if color_id_map.border_texture != null:
		draw_texture_rect(color_id_map.border_texture, texture_rect, false)
	_draw_coalition_fronts()
	if color_id_map.highlight_texture != null:
		draw_texture_rect(color_id_map.highlight_texture, texture_rect, false)
	_draw_color_id_pending_battle()
	_draw_color_id_overlays()

	var campaign: Dictionary = snapshot.get("campaign", {})
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	var map_id := String(map_contract.get("map_id", campaign.get("map_id", "")))
	var title := "%s  |  Turn %s  |  %s" % [
		campaign.get("name", "Gates of CodeX"),
		campaign.get("turn_number", 1),
		String(campaign.get("current_faction", "")).to_upper(),
	]
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, 34),
		title,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		22,
		Color.WHITE
	)
	var province_count := int(snapshot.get("provinces", []).size())
	var manifest_path := String(map_contract.get("manifest_path", map_manifest_source_path))
	var short_manifest := manifest_path
	if short_manifest.find("assets/maps/") >= 0:
		short_manifest = short_manifest.substr(short_manifest.find("assets/maps/"))
	var diag := "Map: %s  |  Provinces: %s  |  Manifest: %s" % [map_id, province_count, short_manifest]
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, 56),
		diag,
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 48,
		14,
		Color("9fd7ff")
	)
	var hint := "F fit front  |  click province shape  |  wheel zoom  |  drag pan"
	if not status_message.is_empty():
		hint = status_message
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, viewport.y - 22),
		hint,
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 48,
		14,
		Color(0.78, 0.82, 0.86, 0.95)
	)
	_draw_management_panel()


func _draw_coalition_fronts() -> void:
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
			Color(1.0, 0.76, 0.31, 0.42),
			1.4
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
	for province: Dictionary in snapshot.get("provinces", []):
		var province_id := String(province.get("id", ""))
		if not color_id_map.row_by_province.has(province_id):
			continue
		var position := _image_to_screen(color_id_map.anchor_pixel(province_id))
		var battalion: Dictionary = battalions_by_province.get(province_id, {})
		var occupied := not battalion.is_empty()
		var selected := province_id == selected_province_id
		var target := legal_targets.has(province_id)
		var owner := String(province.get("owner", "neutral"))
		var faction_color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])

		var infrastructure: Dictionary = province.get("infrastructure", {})
		if int(infrastructure.get("supply_hub", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-13, 12), Vector2(6, 6)), Color("63d69f"))
		if int(infrastructure.get("command_post", 0)) > 0 or int(infrastructure.get("air_base", 0)) > 0:
			draw_circle(position + Vector2(8, 15), 3.2, Color("7fe7ff"))
		if int(infrastructure.get("port", 0)) > 0:
			draw_rect(Rect2(position + Vector2(10, 8), Vector2(6, 4)), Color("4f8fd8"))

		if occupied:
			if not bool(battalion.get("is_in_supply", true)):
				draw_arc(position, 22.0, 0.0, TAU, 30, Color("ff6b5f"), 2.4)
			if int(battalion.get("encircled_turns", 0)) > 0:
				draw_arc(position, 25.0, 0.0, TAU, 30, Color("ffb14e"), 2.4)
			_draw_battalion_counter(position, battalion, faction_color, selected)
			var stack: Array = battalion_stacks_by_province.get(province_id, [])
			if stack.size() > 1:
				var badge := position + Vector2(19, -14)
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

		var label := _province_label(province, province_id)
		var named := bool(province.get("name_is_human_readable", _is_named_province(label)))
		var hovered := province_id == hovered_province_id
		var show_label := occupied or selected or target or hovered
		if not show_label and view_scale >= 2.4 and named:
			show_label = true
		if show_label:
			draw_string(
				ThemeDB.fallback_font,
				position + Vector2(13, -9),
				label,
				HORIZONTAL_ALIGNMENT_LEFT,
				-1,
				12 if selected or target or occupied or hovered else 11,
				Color(0.95, 0.96, 0.98, 0.98 if occupied or selected or target or hovered else 0.78)
			)


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


func _map_texture_rect() -> Rect2:
	var viewport := get_viewport_rect().size
	var map_size := Vector2(viewport.x - PANEL_WIDTH, viewport.y)
	var available := map_size - MAP_MARGIN * 2.0
	var image_size := color_id_map.image_size()
	var fit_scale := minf(available.x / image_size.x, available.y / image_size.y)
	var rendered_size := image_size * fit_scale * view_scale
	return Rect2(map_size * 0.5 - rendered_size * 0.5 + view_offset, rendered_size)


func _province_label(province: Dictionary, province_id: String) -> String:
	var label := String(province.get("display_name", province_id)).strip_edges()
	if label.is_empty():
		return province_id
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


func _fit_to_focus(force: bool) -> void:
	if color_id_map == null or not color_id_map.is_ready:
		super._fit_to_focus(force)
		return
	if fitted_once and not force:
		return
	# Fit the full theatre map by default for EM prototype readability.
	view_scale = 1.0
	view_offset = Vector2.ZERO
	fitted_once = true
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	status_message = "Fitted map %s (%s provinces)." % [
		String(map_contract.get("map_id", "")),
		int(snapshot.get("provinces", []).size()),
	]
	queue_redraw()
