extends "res://scripts/main_map_contract.gd"

const STACK_HEADER_H := 52.0
const STACK_TAB_H := 44.0
const UNIT_CARD_H := 64.0
const PORTRAIT_SIZE := 44.0
const COLLAPSED_BAR_H := 36.0

var stack_tab_rects: Dictionary = {}  # strategic_formation_id -> Rect2
var battalion_row_rects: Dictionary = {}  # battalion_id -> Rect2
var unit_card_rects: Dictionary = {}
var portrait_cache: Dictionary = {}
var hovered_unit_tooltip := ""
var stack_panel_expanded := true
var unit_scroll_offset := 0
var selected_strategic_formation_id := ""
var _collapse_button_rect := Rect2()
var _scroll_up_rect := Rect2()
var _scroll_down_rect := Rect2()


func _draw_management_panel() -> void:
	if has_method("is_pending_battle_modal_active") and is_pending_battle_modal_active() \
	and operational_presenter != null and not operational_presenter.is_active():
		_draw_pending_battle_modal()
		return
	# Full opaque side panel — no ghosted legacy province UI underneath.
	var viewport := get_viewport_rect().size
	var panel_x := viewport.x - PANEL_WIDTH
	draw_rect(Rect2(panel_x, 0, PANEL_WIDTH, viewport.y), Color(0.035, 0.047, 0.062, 1.0))
	draw_line(Vector2(panel_x, 0), Vector2(panel_x, viewport.y), Color(0.28, 0.34, 0.42, 0.85), 1.0)

	var x := panel_x + 18.0
	var y := 28.0
	var campaign: Dictionary = snapshot.get("campaign", {})
	var control: Dictionary = snapshot.get("control", {})
	var writeback := bool(control.get("enabled", false))
	var has_battle := snapshot.get("pending_battle") != null

	y = _panel_heading("CAMPAIGN COMMAND", x, y)
	y = _panel_line(
		"Faction: %s   Current: %s" % [
			String(campaign.get("selected_faction", "")).to_upper(),
			String(campaign.get("current_faction", "")).to_upper(),
		],
		x,
		y
	)
	var faction: Dictionary = factions_by_id.get(String(campaign.get("selected_faction", "")), {})
	y = _panel_line(
		"Resources %s   Inc/Maint %s/%s" % [
			_fmt_int(faction.get("resources", 0)),
			_fmt_int(faction.get("income_last_round", 0)),
			_fmt_int(faction.get("maintenance_last_round", 0)),
		],
		x,
		y
	)
	y += 8.0
	y = _panel_heading("ACTIONS", x, y)
	y = _draw_button("fit", "Fit front (F)", x, y, true, Color("243140"))
	y = _draw_button("refresh", "Refresh", x, y, writeback)
	y = _draw_button("end_turn", "End turn (E)", x, y, writeback and not has_battle)
	y = _draw_button("run_ai", "Run AI + advance", x, y, writeback and not has_battle)
	y = _draw_button("auto_resolve", "Auto-resolve battle (A)", x, y, writeback and has_battle, Color("4a2f18"))
	y = _draw_button("handoff", "Handoff to GoH (H)", x, y, writeback and has_battle, Color("5a2418"))
	if operational_presenter != null and operational_presenter.can_replay_last_contact():
		y = _draw_button("replay_contact", "Replay last contact", x, y, true, Color("243140"))
	if operational_presenter != null and operational_presenter.is_active():
		y = _draw_button("skip_presentation", "Skip presentation (Space)", x, y, true, Color("243140"))
	if not writeback:
		y = _panel_line("Write-back off — re-export frontend.", x, y, Color("ff8e72"), 12)
	y += 10.0

	_draw_stack_section(panel_x, y, viewport.y - y - 12.0)

	# Targets / objectives under the stack section when collapsed enough room.
	var stack_bottom := _stack_section_bottom(y, viewport.y - y - 12.0)
	if stack_bottom + 80.0 < viewport.y:
		_draw_targets_and_objectives(x, stack_bottom + 12.0)


func pending_battle_modal_model() -> Dictionary:
	var pending_variant: Variant = snapshot.get("pending_battle", null)
	if not pending_variant is Dictionary:
		return {}
	_ensure_operational_presenter()
	var contact: Dictionary = operational_presenter.contact_model()
	var attacker_names: Array = []
	var defender_names: Array = []
	var formations: Dictionary = contact.get("formations", {})
	for formation_id: String in contact.get("participant_formation_ids", []):
		var row: Dictionary = formations.get(formation_id, {})
		var names: Array = attacker_names if String(row.get("side", "")) == "attacker" else defender_names
		names.append(String(row.get("display_name", formation_id)))
	var ambush_lines: Array = []
	for ambush_variant: Variant in contact.get("ambush", []):
		if not ambush_variant is Dictionary:
			continue
		var ambush := ambush_variant as Dictionary
		ambush_lines.append("%s: Ambush %s" % [ambush.get("display_name", "Formation"), ambush.get("effect_label", "+15%")])
	var location := String(contact.get("location_detail", "")).strip_edges()
	if location.is_empty():
		var pending := pending_variant as Dictionary
		var location_value: Variant = pending.get("encounter_node_id", null)
		if location_value == null or String(location_value).strip_edges().is_empty():
			location_value = pending.get("encounter_edge_id", "")
		location = "" if location_value == null else String(location_value).strip_edges()
	return {
		"battle_id": String((pending_variant as Dictionary).get("id", "")),
		"contact_label": String(contact.get("label", "Pending Battle")),
		"location": location,
		"attacker_names": attacker_names,
		"defender_names": defender_names,
		"ambush_lines": ambush_lines,
	}


func _draw_pending_battle_modal() -> void:
	button_rects.clear()
	stack_tab_rects.clear()
	battalion_row_rects.clear()
	unit_card_rects.clear()
	var viewport := get_viewport_rect().size
	draw_rect(Rect2(Vector2.ZERO, viewport), Color(0.01, 0.015, 0.025, 0.76))
	var width := minf(880.0, viewport.x - 64.0)
	var height := minf(480.0, viewport.y - 64.0)
	var rect := Rect2((viewport - Vector2(width, height)) * 0.5, Vector2(width, height))
	draw_rect(rect, Color(0.035, 0.047, 0.062, 0.99))
	draw_rect(rect, Color("ffb14e"), false, 2.0)
	var model := pending_battle_modal_model()
	var left := rect.position.x + 30.0
	var right := rect.position.x + rect.size.x * 0.5 + 14.0
	var top := rect.position.y + 38.0
	_draw_panel_text("OPERATIONAL RESOLUTION PAUSED", Vector2(left, top), 22, Color("ffd27a"))
	_draw_panel_text(String(model.get("contact_label", "Pending Battle")), Vector2(left, top + 38.0), 19, Color.WHITE)
	var location := String(model.get("location", ""))
	if not location.is_empty():
		_draw_panel_text("Contact location: %s" % location, Vector2(left, top + 63.0), 13, Color("9fd7ff"))
	_draw_panel_text("ATTACKER", Vector2(left, top + 110.0), 14, Color("7fe7ff"))
	_draw_panel_text("DEFENDER", Vector2(right, top + 110.0), 14, Color("ff8e72"))
	var y_left := top + 137.0
	for name: String in model.get("attacker_names", []):
		_draw_panel_text(name, Vector2(left, y_left), 15, Color.WHITE)
		y_left += 22.0
	var y_right := top + 137.0
	for name: String in model.get("defender_names", []):
		_draw_panel_text(name, Vector2(right, y_right), 15, Color.WHITE)
		y_right += 22.0
	var ambush_y := top + 210.0
	for line: String in model.get("ambush_lines", []):
		_draw_panel_text(line, Vector2(left, ambush_y), 15, Color("ffd27a"))
		ambush_y += 22.0
	_draw_panel_text(
		"Campaign state is paused until this battle is resolved or handed off.",
		Vector2(left, top + 273.0),
		13,
		Color(0.78, 0.82, 0.86, 1.0)
	)
	var writeback := bool(snapshot.get("control", {}).get("enabled", false))
	var button_y := top + 304.0
	button_y = _draw_button("auto_resolve", "Auto-resolve battle (A)", left, button_y, writeback, Color("4a2f18"))
	button_y = _draw_button("handoff", "Handoff to GoH (H)", left, button_y, writeback, Color("5a2418"))
	button_y = _draw_button(
		"import_battle",
		"Import verified GoH result (I)",
		left,
		button_y,
		writeback \
			and bool(snapshot.get("pending_battle", {}).get("started", false)) \
			and String(snapshot.get("pending_battle", {}).get("id", "")) == last_handoff_battle_id \
			and not last_handoff_save_path.is_empty(),
		Color("264a34")
	)
	button_y = _draw_button(
		"replay_contact",
		"Replay last contact",
		right,
		top + 304.0,
		operational_presenter.can_replay_last_contact(),
		Color("243140")
	)
	_draw_button(
		"skip_presentation",
		"Skip presentation (Space)",
		right,
		button_y,
		operational_presenter.is_active(),
		Color("243140")
	)


func _stack_section_bottom(section_top: float, available_h: float) -> float:
	if not stack_panel_expanded:
		return section_top + COLLAPSED_BAR_H
	return section_top + minf(available_h, 420.0)


func _draw_stack_section(panel_x: float, top: float, available_h: float) -> void:
	stack_tab_rects.clear()
	battalion_row_rects.clear()
	unit_card_rects.clear()
	var left := panel_x
	var width := PANEL_WIDTH
	var stack: Dictionary = snapshot.get("stack_presentations", {}).get(selected_province_id, {})
	var battalion_ids: Array = stack.get("battalion_ids", [])
	var force_ids: Array = stack.get("strategic_formation_ids", [])
	var province: Dictionary = provinces_by_id.get(selected_province_id, {})
	var province_name := String(province.get("display_name", selected_province_id))
	var force_presentations: Dictionary = snapshot.get("strategic_formation_presentations", {})

	# Collapse bar always visible.
	var bar := Rect2(left + 10.0, top, width - 20.0, COLLAPSED_BAR_H)
	draw_rect(bar, Color(0.07, 0.10, 0.14, 1.0))
	draw_rect(bar, Color(0.30, 0.38, 0.48, 0.9), false, 1.0)
	_collapse_button_rect = Rect2(bar.end.x - 70.0, bar.position.y + 6.0, 60.0, 24.0)
	draw_rect(_collapse_button_rect, Color(0.14, 0.20, 0.28, 1.0))
	_draw_panel_text(
		"Hide" if stack_panel_expanded else "Show",
		_collapse_button_rect.position + Vector2(14, 16),
		11,
		Color(0.90, 0.94, 0.98, 1.0)
	)
	# Always show all three hierarchy counts in the header.
	var header_summary := "%s | %s | %s | %s" % [
		province_name,
		_count_words(int(stack.get("formation_count", force_ids.size())), "formation", "formations"),
		_count_words(int(stack.get("battalion_count", battalion_ids.size())), "battalion", "battalions"),
		_count_words(int(stack.get("unit_count", 0)), "tactical unit", "tactical units"),
	]
	if battalion_ids.is_empty() and force_ids.is_empty():
		header_summary = "%s | No forces in province" % province_name
	_draw_panel_text(
		header_summary,
		bar.position + Vector2(10, 22),
		11,
		Color(0.94, 0.96, 0.99, 1.0)
	)

	if not stack_panel_expanded:
		return

	var body_top := top + COLLAPSED_BAR_H + 8.0
	var body_h := minf(available_h - COLLAPSED_BAR_H - 8.0, 400.0)
	var body := Rect2(left + 10.0, body_top, width - 20.0, body_h)
	draw_rect(body, Color(0.045, 0.06, 0.08, 1.0))
	draw_rect(body, Color(0.24, 0.30, 0.38, 0.75), false, 1.0)

	if force_ids.is_empty() and battalion_ids.is_empty():
		_draw_panel_text(
			"Select a province with forces.",
			body.position + Vector2(12, 28),
			13,
			Color(0.72, 0.77, 0.83, 1.0)
		)
		return

	# Fallback if older snapshot lacks strategic_formation_ids.
	if force_ids.is_empty():
		force_ids = _force_ids_from_battalions(battalion_ids)

	_ensure_selection(force_ids, battalion_ids)

	_draw_panel_text(
		"Cond %s%%   Sup %s%%   Reinf %s   Repair %s" % [
			_fmt_int(stack.get("condition", 0)),
			_fmt_int(stack.get("supply", 0)),
			_fmt_int(stack.get("reinforcement_cost", 0)),
			_fmt_int(stack.get("repair_cost", 0)),
		],
		body.position + Vector2(12, 20),
		11,
		Color(0.65, 0.77, 0.88, 1.0)
	)

	# Top-level tabs = StrategicFormations (not battalions).
	var tab_y := body.position.y + 36.0
	var tab_w := (body.size.x - 8.0) / maxf(float(force_ids.size()), 1.0)
	for index in range(force_ids.size()):
		var force_id := String(force_ids[index])
		var rect := Rect2(body.position.x + 4.0 + tab_w * index, tab_y, tab_w - 4.0, STACK_TAB_H)
		stack_tab_rects[force_id] = rect
		_draw_formation_tab(rect, force_id)

	var force_row: Dictionary = force_presentations.get(selected_strategic_formation_id, {})
	if force_row.is_empty() and force_ids.size() > 0:
		force_row = force_presentations.get(String(force_ids[0]), {})

	var header_y := tab_y + STACK_TAB_H + 12.0
	_draw_formation_header(body.position.x, header_y, force_row)

	# Battalion list inside selected strategic formation.
	var member_ids: Array = force_row.get("battalion_ids", [])
	var bn_y := header_y + 70.0
	_draw_panel_text("BATTALIONS IN FORMATION", Vector2(body.position.x + 12, bn_y), 10, Color(0.55, 0.72, 0.86, 1.0))
	bn_y += 8.0
	for battalion_id_variant in member_ids:
		var battalion_id := String(battalion_id_variant)
		var row_rect := Rect2(body.position.x + 10.0, bn_y, body.size.x - 20.0, 26.0)
		battalion_row_rects[battalion_id] = row_rect
		var selected_bn := battalion_id == selected_battalion_id
		draw_rect(row_rect, Color(0.12, 0.26, 0.32, 1.0) if selected_bn else Color(0.06, 0.08, 0.11, 1.0))
		draw_rect(row_rect, Color(0.30, 0.92, 0.76, 0.9) if selected_bn else Color(0.25, 0.32, 0.40, 0.7), false, 1.0)
		var bn_pres: Dictionary = snapshot.get("battalion_presentations", {}).get(battalion_id, {})
		var bn_label := String(bn_pres.get("battalion_label", battalion_id))
		var bn_type := String(bn_pres.get("type_label", "Battalion"))
		_draw_panel_text(
			"%s  ·  %s%s" % [bn_label, bn_type, "  (selected)" if selected_bn else ""],
			row_rect.position + Vector2(8, 17),
			11,
			Color.WHITE if selected_bn else Color(0.85, 0.88, 0.92, 1.0)
		)
		bn_y += 30.0

	var presentation := _selected_presentation()
	if presentation.is_empty():
		return

	# Scrollable tactical unit cards for selected battalion.
	var cards: Array = presentation.get("cards", [])
	var cards_top := bn_y + 10.0
	var cards_bottom := body.position.y + body.size.y - 28.0
	var visible_h := cards_bottom - cards_top
	var max_visible := maxi(int(floor(visible_h / UNIT_CARD_H)), 1)
	var max_scroll := maxi(cards.size() - max_visible, 0)
	unit_scroll_offset = clampi(unit_scroll_offset, 0, max_scroll)

	_draw_panel_text(
		"TACTICAL UNITS IN SELECTED BATTALION",
		Vector2(body.position.x + 12, cards_top - 2),
		10,
		Color(0.55, 0.72, 0.86, 1.0)
	)
	cards_top += 14.0

	_scroll_up_rect = Rect2(body.end.x - 54.0, cards_top - 2.0, 22.0, 18.0)
	_scroll_down_rect = Rect2(body.end.x - 28.0, cards_top - 2.0, 22.0, 18.0)
	if max_scroll > 0:
		_draw_scroll_button(_scroll_up_rect, "^", unit_scroll_offset > 0)
		_draw_scroll_button(_scroll_down_rect, "v", unit_scroll_offset < max_scroll)

	if cards.is_empty():
		var debug_on := bool(snapshot.get("campaign", {}).get("map_metadata", {}).get("debug_show_placeholder_units", false))
		if debug_on:
			_draw_panel_text(
				"[debug] No non-placeholder tactical units in this battalion.",
				Vector2(body.position.x + 12, cards_top + 20),
				11,
				Color(0.95, 0.75, 0.40, 1.0)
			)
		else:
			_draw_panel_text(
				"No tactical unit cards (roster empty or placeholders hidden).",
				Vector2(body.position.x + 12, cards_top + 20),
				11,
				Color(0.70, 0.76, 0.82, 1.0)
			)
		return

	var card_y := cards_top
	var end_index := mini(unit_scroll_offset + max_visible, cards.size())
	for index in range(unit_scroll_offset, end_index):
		var card: Dictionary = cards[index]
		var rect := Rect2(body.position.x + 8.0, card_y, body.size.x - 16.0, UNIT_CARD_H - 4.0)
		unit_card_rects[index] = {"rect": rect, "tooltip": String(card.get("tooltip", ""))}
		_draw_unit_card(rect, card)
		card_y += UNIT_CARD_H

	if end_index < cards.size():
		_draw_panel_text(
			"+%s more unit groups  (scroll)" % (cards.size() - end_index),
			Vector2(body.position.x + 12, cards_bottom - 4),
			10,
			Color(0.68, 0.73, 0.79, 1.0)
		)


func _draw_targets_and_objectives(x: float, y: float) -> float:
	y = _panel_heading("TARGETS", x, y)
	var writeback := bool(snapshot.get("control", {}).get("enabled", false))
	var options: Array = front_by_origin.get(selected_province_id, [])
	if options.is_empty():
		y = _panel_line("No legal moves for selected battalion.", x, y, Color(0.7, 0.75, 0.8), 12)
	else:
		var shown := 0
		for option: Dictionary in options:
			if shown >= 4:
				y = _panel_line("+ more targets in list…", x, y, Color(0.65, 0.7, 0.75), 11)
				break
			var tid := String(option.get("target", ""))
			var label := "%s  %s" % [
				String(option.get("kind", "move")).to_upper(),
				String(option.get("target_name", tid)),
			]
			y = _draw_button(
				"move:%s" % tid,
				label,
				x,
				y,
				writeback,
				Color("2a3d28") if String(option.get("kind", "")) == "move" else Color("4a2f18")
			)
			shown += 1
	y += 6.0
	y = _panel_heading("OBJECTIVES", x, y)
	for objective: Dictionary in snapshot.get("objectives", []):
		y = _panel_line(
			"%s/%s  %s" % [
				_fmt_int(objective.get("progress", 0)),
				_fmt_int(objective.get("threshold", 0)),
				String(objective.get("display_name", objective.get("id", ""))),
			],
			x,
			y,
			Color(0.78, 0.82, 0.86, 1.0),
			12
		)
	return y


func _draw_formation_tab(rect: Rect2, force_id: String) -> void:
	var presentation: Dictionary = snapshot.get("strategic_formation_presentations", {}).get(force_id, {})
	var selected := force_id == selected_strategic_formation_id
	var can_act := bool(presentation.get("can_act", false))
	var fill := Color(0.12, 0.28, 0.34, 1.0) if selected else Color(0.065, 0.085, 0.11, 1.0)
	draw_rect(rect, fill)
	draw_rect(
		rect,
		Color(0.30, 0.92, 0.76, 0.95) if selected else Color(0.27, 0.33, 0.41, 0.85),
		false,
		2.0 if selected else 1.0
	)
	_draw_panel_text(
		String(presentation.get("actor_marker", "?")),
		rect.position + Vector2(7, 14),
		10,
		Color(0.95, 0.84, 0.42, 1.0)
	)
	# StrategicFormation.display_name (tab_label may include compact disambiguator).
	var name := String(presentation.get("tab_label", presentation.get("display_name", force_id)))
	_draw_panel_text(name.left(20), rect.position + Vector2(7, 30), 11, Color.WHITE)
	if can_act:
		draw_circle(rect.position + Vector2(rect.size.x - 8, 9), 3.5, Color(0.30, 1.0, 0.56, 1.0))


func _draw_formation_header(left: float, y: float, force_row: Dictionary) -> void:
	_draw_panel_text("STRATEGIC FORMATION", Vector2(left + 12, y + 4), 10, Color(0.55, 0.72, 0.86, 1.0))
	_draw_panel_text(
		String(force_row.get("display_name", "Formation")),
		Vector2(left + 12, y + 22),
		15,
		Color(0.98, 0.99, 1.0, 1.0)
	)
	var echelon := String(force_row.get("echelon", "battalion")).replace("_", " ")
	_draw_panel_text(
		"Echelon: %s  ·  Commander: %s  ·  %s" % [
			echelon.capitalize(),
			force_row.get("commander_label", "Unassigned Commander"),
			force_row.get("actor_marker", "?"),
		],
		Vector2(left + 12, y + 42),
		11,
		Color(0.64, 0.78, 0.90, 1.0)
	)
	_draw_panel_text(
		"%s  ·  %s tactical units in formation" % [
			_count_words(int(force_row.get("battalion_count", 0)), "battalion", "battalions"),
			_fmt_int(force_row.get("unit_count", 0)),
		],
		Vector2(left + 12, y + 58),
		11,
		Color(0.83, 0.86, 0.90, 1.0)
	)


func _ensure_selection(force_ids: Array, battalion_ids: Array) -> void:
	if force_ids.is_empty():
		return
	if selected_strategic_formation_id.is_empty() or not force_ids.has(selected_strategic_formation_id):
		selected_strategic_formation_id = String(force_ids[0])
	var force_row: Dictionary = snapshot.get("strategic_formation_presentations", {}).get(
		selected_strategic_formation_id, {}
	)
	var members: Array = force_row.get("battalion_ids", [])
	if members.is_empty():
		members = battalion_ids
	if selected_battalion_id.is_empty() or not members.has(selected_battalion_id):
		# Prefer a battalion that can act.
		selected_battalion_id = ""
		for battalion_id_variant in members:
			var battalion_id := String(battalion_id_variant)
			var row: Dictionary = snapshot.get("battalion_presentations", {}).get(battalion_id, {})
			if bool(row.get("can_act", false)):
				selected_battalion_id = battalion_id
				break
		if selected_battalion_id.is_empty() and members.size() > 0:
			selected_battalion_id = String(members[0])
		_rebuild_legal_targets()


func _force_ids_from_battalions(battalion_ids: Array) -> Array:
	var out: Array = []
	var seen: Dictionary = {}
	var forces: Dictionary = snapshot.get("strategic_formation_presentations", {})
	for force_id_variant in forces.keys():
		var force_id := String(force_id_variant)
		var row: Dictionary = forces[force_id]
		if String(row.get("province_id", "")) != selected_province_id:
			continue
		if seen.has(force_id):
			continue
		seen[force_id] = true
		out.append(force_id)
	if out.is_empty():
		# Last-resort: one synthetic tab per battalion (legacy snapshots).
		for battalion_id_variant in battalion_ids:
			out.append(String(battalion_id_variant))
	return out


func _count_words(count: int, singular: String, plural: String) -> String:
	return "%s %s" % [count, singular if count == 1 else plural]


func _draw_unit_card(rect: Rect2, card: Dictionary) -> void:
	draw_rect(rect, Color(0.075, 0.095, 0.12, 0.98))
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
			portrait_rect.position + Vector2(6, 26),
			11,
			Color(0.88, 0.92, 0.96, 1.0)
		)
	var text_x := rect.position.x + PORTRAIT_SIZE + 14.0
	_draw_panel_text("TACTICAL UNIT", Vector2(text_x, rect.position.y + 12), 9, Color(0.55, 0.70, 0.82, 1.0))
	_draw_panel_text(
		String(card.get("short_name", card.get("display_name", "Unknown unit"))),
		Vector2(text_x, rect.position.y + 28),
		12,
		Color(0.97, 0.98, 1.0, 1.0)
	)
	var qty := int(card.get("quantity", 0))
	var auth := int(card.get("authorized_quantity", 0))
	var qty_label := str(qty) if auth <= 0 else "%s/%s" % [qty, auth]
	_draw_panel_text(
		"%s fielded   C%s%%  S%s%%  XP%s" % [
			qty_label,
			_fmt_int(card.get("condition", 0)),
			_fmt_int(card.get("supply", 0)),
			_fmt_int(card.get("experience", 0)),
		],
		Vector2(text_x, rect.position.y + 46),
		10,
		Color(0.72, 0.81, 0.88, 1.0)
	)


func _draw_scroll_button(rect: Rect2, label: String, enabled: bool) -> void:
	draw_rect(rect, Color(0.12, 0.16, 0.22, 1.0) if enabled else Color(0.07, 0.09, 0.12, 1.0))
	draw_rect(rect, Color(0.35, 0.42, 0.52, 0.9), false, 1.0)
	_draw_panel_text(label, rect.position + Vector2(7, 13), 11, Color.WHITE if enabled else Color(0.4, 0.45, 0.5, 1.0))


func _draw_province(province: Dictionary) -> void:
	# Custom province draw: clearer stack badge (no ambiguous black circle).
	var position := _map_to_screen(province)
	var owner := String(province.get("owner", "neutral"))
	var color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])
	var province_id := String(province.get("id", ""))
	var battalion: Dictionary = battalions_by_province.get(province_id, {})
	var occupied := not battalion.is_empty()
	var selected := province_id == selected_province_id
	var target_option: Dictionary = legal_targets.get(province_id, {})
	var stack: Array = battalion_stacks_by_province.get(province_id, [])

	if color_id_map != null and color_id_map.is_ready:
		# Color-ID path: only overlays (map fill already drawn).
		pass
	else:
		draw_circle(position, 10.0 if selected else 7.0, color)

	if not target_option.is_empty():
		var kind := String(target_option.get("kind", "move"))
		draw_arc(position, 16.0, 0.0, TAU, 28, Color("3dff8a") if kind == "move" else Color("ff9f43"), 2.0)

	if occupied:
		_draw_battalion_counter(position, battalion, color, selected)
		if stack.size() > 1:
			var badge := position + Vector2(18, -16)
			var badge_rect := Rect2(badge - Vector2(10, 9), Vector2(28, 18))
			draw_rect(badge_rect, Color(0.04, 0.06, 0.09, 0.96))
			draw_rect(badge_rect, Color.WHITE, false, 1.2)
			draw_string(
				ThemeDB.fallback_font,
				badge + Vector2(-6, 4),
				"x%s" % stack.size(),
				HORIZONTAL_ALIGNMENT_LEFT,
				-1,
				11,
				Color.WHITE
			)

	var label := String(province.get("display_name", province_id))
	var show_label := occupied or selected or not target_option.is_empty()
	if show_label:
		draw_string(
			ThemeDB.fallback_font,
			position + Vector2(14, -8),
			label,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			12 if selected or occupied else 11,
			Color(0.95, 0.96, 0.98, 0.95)
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


func _fmt_int(value: Variant) -> String:
	return str(int(round(float(value))))


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


func _unhandled_input(event: InputEvent) -> void:
	if has_method("is_pending_battle_modal_active") and is_pending_battle_modal_active():
		if event is InputEventKey and event.pressed and not event.echo:
			var key := event as InputEventKey
			if key.keycode == KEY_SPACE:
				_handle_button("skip_presentation")
			elif key.keycode == KEY_A:
				_handle_button("auto_resolve")
			elif key.keycode == KEY_H:
				_handle_button("handoff")
			elif key.keycode == KEY_I:
				_handle_button("import_battle")
			get_viewport().set_input_as_handled()
			return
		if event is InputEventMouseButton and event.pressed:
			var modal_mouse := event as InputEventMouseButton
			if modal_mouse.button_index == MOUSE_BUTTON_LEFT:
				for button_id: String in button_rects:
					if (button_rects[button_id] as Rect2).has_point(modal_mouse.position):
						_handle_button(button_id)
						break
		get_viewport().set_input_as_handled()
		return
	if event is InputEventKey and event.pressed and not event.echo:
		if (event as InputEventKey).keycode == KEY_SPACE and operational_presenter != null and operational_presenter.is_active():
			_handle_button("skip_presentation")
			get_viewport().set_input_as_handled()
			return
	if event is InputEventMouseMotion:
		var next_tooltip := _unit_tooltip_at(event.position)
		if next_tooltip != hovered_unit_tooltip:
			hovered_unit_tooltip = next_tooltip
			queue_redraw()
	elif event is InputEventMouseButton and event.pressed:
		var mouse := event as InputEventMouseButton
		if mouse.button_index == MOUSE_BUTTON_LEFT:
			if _collapse_button_rect.has_point(mouse.position):
				stack_panel_expanded = not stack_panel_expanded
				status_message = "Stack panel %s." % ("expanded" if stack_panel_expanded else "collapsed")
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
			if _scroll_up_rect.has_point(mouse.position):
				unit_scroll_offset = maxi(unit_scroll_offset - 1, 0)
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
			if _scroll_down_rect.has_point(mouse.position):
				unit_scroll_offset += 1
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
			for force_id: String in stack_tab_rects:
				var rect: Rect2 = stack_tab_rects[force_id]
				if rect.has_point(mouse.position):
					selected_strategic_formation_id = force_id
					unit_scroll_offset = 0
					var force_row: Dictionary = snapshot.get("strategic_formation_presentations", {}).get(force_id, {})
					var members: Array = force_row.get("battalion_ids", [])
					selected_battalion_id = ""
					for battalion_id_variant in members:
						var battalion_id := String(battalion_id_variant)
						var row: Dictionary = snapshot.get("battalion_presentations", {}).get(battalion_id, {})
						if bool(row.get("can_act", false)):
							selected_battalion_id = battalion_id
							break
					if selected_battalion_id.is_empty() and members.size() > 0:
						selected_battalion_id = String(members[0])
					_rebuild_legal_targets()
					status_message = "Selected formation %s (acting battalion %s)." % [
						force_row.get("display_name", force_id),
						_selected_presentation().get("battalion_label", selected_battalion_id),
					]
					queue_redraw()
					get_viewport().set_input_as_handled()
					return
			for battalion_id: String in battalion_row_rects:
				var bn_rect: Rect2 = battalion_row_rects[battalion_id]
				if bn_rect.has_point(mouse.position):
					selected_battalion_id = battalion_id
					unit_scroll_offset = 0
					_rebuild_legal_targets()
					status_message = "Selected acting battalion %s." % _selected_presentation().get(
						"battalion_label", battalion_id
					)
					queue_redraw()
					get_viewport().set_input_as_handled()
					return
		elif mouse.button_index == MOUSE_BUTTON_WHEEL_UP and stack_panel_expanded:
			if Rect2(get_viewport_rect().size.x - PANEL_WIDTH, 0, PANEL_WIDTH, get_viewport_rect().size.y).has_point(mouse.position):
				unit_scroll_offset = maxi(unit_scroll_offset - 1, 0)
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
		elif mouse.button_index == MOUSE_BUTTON_WHEEL_DOWN and stack_panel_expanded:
			if Rect2(get_viewport_rect().size.x - PANEL_WIDTH, 0, PANEL_WIDTH, get_viewport_rect().size.y).has_point(mouse.position):
				unit_scroll_offset += 1
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
	super._unhandled_input(event)
