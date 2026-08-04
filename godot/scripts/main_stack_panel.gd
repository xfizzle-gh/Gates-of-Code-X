extends "res://scripts/main_map_contract.gd"

const STACK_PANEL_TOP := 48.0
const STACK_PANEL_HEIGHT := 470.0
const STACK_TAB_HEIGHT := 46.0
const UNIT_CARD_HEIGHT := 66.0
const PORTRAIT_SIZE := 48.0

var stack_tab_rects: Dictionary = {}
var unit_card_rects: Dictionary = {}
var portrait_cache: Dictionary = {}
var hovered_unit_tooltip := ""


func _draw_management_panel() -> void:
	super._draw_management_panel()
	_draw_stack_panel()


func _input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		var next_tooltip := _unit_tooltip_at(event.position)
		if next_tooltip != hovered_unit_tooltip:
			hovered_unit_tooltip = next_tooltip
			queue_redraw()
	elif event is InputEventMouseButton \
	and event.button_index == MOUSE_BUTTON_LEFT \
	and event.pressed:
		for battalion_id: String in stack_tab_rects:
			var rect: Rect2 = stack_tab_rects[battalion_id]
			if rect.has_point(event.position):
				selected_battalion_id = battalion_id
				_rebuild_legal_targets()
				status_message = "Selected %s as acting battalion." % _selected_presentation().get("display_name", battalion_id)
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
	super._input(event)


func _draw_stack_panel() -> void:
	stack_tab_rects.clear()
	unit_card_rects.clear()
	var viewport := get_viewport_rect().size
	var left := viewport.x - PANEL_WIDTH
	var panel_rect := Rect2(left, STACK_PANEL_TOP, PANEL_WIDTH, STACK_PANEL_HEIGHT)
	draw_rect(panel_rect, Color(0.035, 0.047, 0.062, 0.985))
	draw_line(
		Vector2(left, STACK_PANEL_TOP),
		Vector2(left, STACK_PANEL_TOP + STACK_PANEL_HEIGHT),
		Color(0.28, 0.34, 0.42, 0.8),
		1.0
	)

	var stack: Dictionary = snapshot.get("stack_presentations", {}).get(selected_province_id, {})
	var battalion_ids: Array = stack.get("battalion_ids", [])
	if battalion_ids.is_empty():
		_draw_panel_text(
			"No battalion selected",
			Vector2(left + 18, STACK_PANEL_TOP + 28),
			16,
			Color(0.72, 0.77, 0.83, 1.0)
		)
		return
	if selected_battalion_id.is_empty() or not battalion_ids.has(selected_battalion_id):
		selected_battalion_id = String(battalion_ids[0])
		_rebuild_legal_targets()

	_draw_stack_summary(left, stack)
	var tab_y := STACK_PANEL_TOP + 58.0
	var tab_width := (PANEL_WIDTH - 28.0) / maxf(float(battalion_ids.size()), 1.0)
	for index in range(battalion_ids.size()):
		var battalion_id := String(battalion_ids[index])
		var rect := Rect2(
			left + 14.0 + tab_width * index,
			tab_y,
			tab_width - 4.0,
			STACK_TAB_HEIGHT
		)
		stack_tab_rects[battalion_id] = rect
		_draw_battalion_tab(rect, battalion_id)

	var presentation := _selected_presentation()
	if presentation.is_empty():
		return
	var header_y := tab_y + STACK_TAB_HEIGHT + 18.0
	_draw_selected_header(left, header_y, presentation)
	var card_y := header_y + 86.0
	var cards: Array = presentation.get("cards", [])
	for index in range(cards.size()):
		if card_y + UNIT_CARD_HEIGHT > STACK_PANEL_TOP + STACK_PANEL_HEIGHT - 42.0:
			_draw_panel_text(
				"+%s more unit groups" % (cards.size() - index),
				Vector2(left + 18, card_y + 18),
				12,
				Color(0.68, 0.73, 0.79, 1.0)
			)
			break
		var card: Dictionary = cards[index]
		var rect := Rect2(left + 14.0, card_y, PANEL_WIDTH - 28.0, UNIT_CARD_HEIGHT - 4.0)
		unit_card_rects[index] = {"rect": rect, "tooltip": String(card.get("tooltip", ""))}
		_draw_unit_card(rect, card)
		card_y += UNIT_CARD_HEIGHT

	if not hovered_unit_tooltip.is_empty():
		var tooltip_rect := Rect2(
			left + 12.0,
			STACK_PANEL_TOP + STACK_PANEL_HEIGHT - 66.0,
			PANEL_WIDTH - 24.0,
			58.0
		)
		draw_rect(tooltip_rect, Color(0.02, 0.026, 0.035, 0.98))
		draw_rect(tooltip_rect, Color(0.45, 0.55, 0.68, 0.8), false, 1.0)
		_draw_wrapped_text(hovered_unit_tooltip, tooltip_rect.grow(-8.0), 11, Color(0.92, 0.94, 0.97, 1.0))


func _draw_stack_summary(left: float, stack: Dictionary) -> void:
	_draw_panel_text(
		"STACK · %s BATTALIONS · %s/%s UNITS" % [
			stack.get("battalion_count", 0),
			stack.get("unit_count", 0),
			stack.get("authorized_unit_count", 0),
		],
		Vector2(left + 16, STACK_PANEL_TOP + 22),
		14,
		Color(0.94, 0.96, 0.99, 1.0)
	)
	_draw_panel_text(
		"COND %s   SUP %s   REINF %s   REPAIR %s" % [
			stack.get("condition", 0),
			stack.get("supply", 0),
			stack.get("reinforcement_cost", 0),
			stack.get("repair_cost", 0),
		],
		Vector2(left + 16, STACK_PANEL_TOP + 43),
		11,
		Color(0.65, 0.77, 0.88, 1.0)
	)


func _draw_battalion_tab(rect: Rect2, battalion_id: String) -> void:
	var presentation: Dictionary = snapshot.get("battalion_presentations", {}).get(battalion_id, {})
	var selected := battalion_id == selected_battalion_id
	var can_act := bool(presentation.get("can_act", false))
	var fill := Color(0.12, 0.18, 0.24, 1.0) if selected else Color(0.065, 0.085, 0.11, 1.0)
	if selected:
		fill = Color(0.12, 0.28, 0.34, 1.0)
	draw_rect(rect, fill)
	draw_rect(
		rect,
		Color(0.30, 0.92, 0.76, 0.95) if selected else Color(0.27, 0.33, 0.41, 0.85),
		false,
		2.0 if selected else 1.0
	)
	_draw_panel_text(
		String(presentation.get("actor_marker", "?")),
		rect.position + Vector2(7, 16),
		10,
		Color(0.95, 0.84, 0.42, 1.0)
	)
	_draw_panel_text(
		String(presentation.get("display_name", battalion_id)).left(17),
		rect.position + Vector2(7, 33),
		11,
		Color.WHITE
	)
	if can_act:
		draw_circle(rect.position + Vector2(rect.size.x - 8, 9), 3.5, Color(0.30, 1.0, 0.56, 1.0))


func _draw_selected_header(left: float, y: float, presentation: Dictionary) -> void:
	_draw_panel_text(
		String(presentation.get("display_name", "Battalion")),
		Vector2(left + 16, y + 18),
		18,
		Color(0.98, 0.99, 1.0, 1.0)
	)
	_draw_panel_text(
		"%s · %s · %s" % [
			presentation.get("actor_marker", "?"),
			presentation.get("formation_name", "Unknown formation"),
			presentation.get("type_label", "Battalion"),
		],
		Vector2(left + 16, y + 39),
		11,
		Color(0.64, 0.78, 0.90, 1.0)
	)
	_draw_panel_text(
		"%s/%s units   C%s   S%s   XP%s   M%s   A%s" % [
			presentation.get("unit_count", 0),
			presentation.get("authorized_unit_count", 0),
			presentation.get("condition", 0),
			presentation.get("supply", 0),
			presentation.get("experience", 0),
			presentation.get("movement_remaining", 0),
			presentation.get("combat_actions_remaining", 0),
		],
		Vector2(left + 16, y + 60),
		11,
		Color(0.83, 0.86, 0.90, 1.0)
	)
	_draw_panel_text(
		"Reinforce %s · Repair %s · %s legal targets" % [
			presentation.get("reinforcement_cost", 0),
			presentation.get("repair_cost", 0),
			presentation.get("legal_option_count", 0),
		],
		Vector2(left + 16, y + 78),
		10,
		Color(0.68, 0.74, 0.81, 1.0)
	)


func _draw_unit_card(rect: Rect2, card: Dictionary) -> void:
	var role := String(card.get("source", {}).get("role", "unknown"))
	var fill := Color(0.075, 0.095, 0.12, 0.98)
	if role == "legacy_reserve":
		fill = Color(0.12, 0.105, 0.075, 0.98)
	draw_rect(rect, fill)
	draw_rect(rect, Color(0.26, 0.32, 0.39, 0.9), false, 1.0)
	var portrait_rect := Rect2(rect.position + Vector2(7, 7), Vector2(PORTRAIT_SIZE, PORTRAIT_SIZE))
	var portrait := _portrait_texture(String(card.get("portrait_key", "")))
	if portrait != null:
		draw_texture_rect(portrait, portrait_rect, false)
	else:
		draw_rect(portrait_rect, Color(0.12, 0.16, 0.20, 1.0))
		draw_rect(portrait_rect, Color(0.38, 0.46, 0.56, 0.9), false, 1.0)
		_draw_panel_text(
			String(card.get("portrait_fallback", "UNIT")),
			portrait_rect.position + Vector2(6, 28),
			11,
			Color(0.88, 0.92, 0.96, 1.0)
		)
	var text_x := rect.position.x + PORTRAIT_SIZE + 14.0
	_draw_panel_text(
		String(card.get("short_name", card.get("display_name", "Unknown unit"))),
		Vector2(text_x, rect.position.y + 18),
		12,
		Color(0.97, 0.98, 1.0, 1.0)
	)
	_draw_panel_text(
		"%s/%s   C%s   S%s   XP%s" % [
			card.get("quantity", 0),
			card.get("authorized_quantity", 0),
			card.get("condition", 0),
			card.get("supply", 0),
			card.get("experience", 0),
		],
		Vector2(text_x, rect.position.y + 38),
		10,
		Color(0.72, 0.81, 0.88, 1.0)
	)
	var source: Dictionary = card.get("source", {})
	_draw_panel_text(
		"%s · %s · R%s" % [
			source.get("marker", "?"),
			card.get("category_icon", "UNIT"),
			card.get("replacement_cost", 0),
		],
		Vector2(text_x, rect.position.y + 55),
		9,
		Color(0.90, 0.72, 0.40, 1.0) if role == "legacy_reserve" else Color(0.62, 0.70, 0.78, 1.0)
	)


func _portrait_texture(key: String) -> Texture2D:
	if key.is_empty():
		return null
	if portrait_cache.has(key):
		return portrait_cache[key]
	var path := "res://assets/unit_portraits/%s.png" % key
	var texture: Texture2D = null
	if ResourceLoader.exists(path):
		texture = load(path) as Texture2D
	portrait_cache[key] = texture
	return texture


func _unit_tooltip_at(position: Vector2) -> String:
	for row: Dictionary in unit_card_rects.values():
		var rect: Rect2 = row.get("rect", Rect2())
		if rect.has_point(position):
			return String(row.get("tooltip", ""))
	return ""


func _selected_presentation() -> Dictionary:
	return snapshot.get("battalion_presentations", {}).get(selected_battalion_id, {})


func _draw_panel_text(text: String, position: Vector2, font_size: int, color: Color) -> void:
	draw_string(
		ThemeDB.fallback_font,
		position,
		text,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		font_size,
		color
	)


func _draw_wrapped_text(text: String, rect: Rect2, font_size: int, color: Color) -> void:
	var lines := text.split("\n")
	var y := rect.position.y + font_size
	for line: String in lines:
		draw_string(
			ThemeDB.fallback_font,
			Vector2(rect.position.x, y),
			line,
			HORIZONTAL_ALIGNMENT_LEFT,
			rect.size.x,
			font_size,
			color
		)
		y += font_size + 3
		if y > rect.end.y:
			break
