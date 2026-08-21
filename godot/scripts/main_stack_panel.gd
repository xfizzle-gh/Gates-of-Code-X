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
var _collapse_button_rect := Rect2()
var _scroll_up_rect := Rect2()
var _scroll_down_rect := Rect2()


func _player_launch_model() -> Dictionary:
	return player_launch_block()


func _scenario_label(application: Dictionary, campaign: Dictionary) -> String:
	## Never invent a name: report exactly what the authoritative campaign says.
	var display := String(application.get("scenario_display_name", "")).strip_edges()
	if not display.is_empty():
		return display
	var scenario_id := String(application.get("scenario_id", "")).strip_edges()
	if not scenario_id.is_empty():
		return scenario_id
	return String(campaign.get("map_id", "unknown"))


func _save_path_label(application: Dictionary, control: Dictionary) -> String:
	var path := String(application.get("campaign_path", "")).strip_edges()
	if path.is_empty():
		path = String(control.get("campaign_path", "")).strip_edges()
	if path.is_empty():
		return "(unsaved)"
	var normalized := path.replace("\\", "/")
	var name := normalized.get_file()
	var parent := normalized.get_base_dir().get_file()
	if parent.is_empty():
		return name
	return "%s/%s" % [parent, name]


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

	var application: Dictionary = snapshot.get("application", {})
	y = _panel_heading("CAMPAIGN COMMAND", x, y)
	y = _panel_line(
		"%s %s" % [
			String(application.get("name", "Gates of CodeX")),
			String(application.get("version", "")),
		],
		x,
		y,
		Color(0.55, 0.72, 0.86, 1.0),
		12
	)
	y = _panel_line(
		"Commit: %s" % String(application.get("source_commit", "")),
		x,
		y,
		Color(0.55, 0.72, 0.86, 1.0),
		10
	)
	y = _panel_line(
		"Scenario: %s" % _scenario_label(application, campaign),
		x,
		y,
		Color(0.78, 0.88, 0.96, 1.0),
		12
	)
	y = _panel_line(
		"%s   Save: %s" % [
			CampaignRulesPresenter.turn_line(campaign),
			_save_path_label(application, control),
		],
		x,
		y,
		Color(0.66, 0.78, 0.88, 1.0),
		12
	)
	y = _panel_line(
		"%s   Preset %s" % [
			CampaignRulesPresenter.momentum_label(campaign),
			String(campaign.get("length_preset", "medium")).capitalize(),
		],
		x,
		y,
		Color(0.86, 0.78, 0.52, 1.0),
		12
	)
	y = _panel_line(
		"Faction: %s   Current: %s" % [
			String(campaign.get("selected_faction", "")).to_upper(),
			String(campaign.get("current_faction", "")).to_upper(),
		],
		x,
		y
	)
	var actor: Dictionary = acting_actor_block() if has_method("acting_actor_block") else {}
	if not actor.is_empty():
		y = _panel_line(
			"Actor %s   Treasury %s" % [
				String(actor.get("short_name", actor.get("display_name", actor.get("actor_id", "")))),
				_fmt_int(actor.get("resources", 0)),
			],
			x,
			y,
			Color(0.95, 0.84, 0.42, 1.0)
		)
		y = _panel_line(
			"Inc/Maint %s/%s   Research %s" % [
				_fmt_int(actor.get("income_last_round", 0)),
				_fmt_int(actor.get("maintenance_last_round", 0)),
				_fmt_int(actor.get("researched_count", 0)),
			],
			x,
			y
		)
	else:
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
	y = _panel_heading("CAMPAIGN", x, y)
	var play: Dictionary = _player_launch_model()
	var play_enabled := bool(play.get("enabled", false))
	var confirm_new := new_campaign_confirm_pending
	y = _draw_button(
		"new_campaign",
		"Confirm New Campaign" if confirm_new else "New Campaign",
		x,
		y,
		play_enabled and not (play.get("new_args", []) as Array).is_empty(),
		Color("5a2418") if confirm_new else Color("243140")
	)
	if confirm_new:
		y = _panel_line("Length and Fog apply to the next New Campaign only.", x, y, Color(0.78, 0.82, 0.86, 1.0), 11)
		for preset in ["short", "medium", "long"]:
			var selected_preset := _selected_length_preset(campaign)
			y = _draw_button(
				"length_preset:%s" % preset,
				"%s%s" % [preset.capitalize(), "  [selected]" if selected_preset == preset else ""],
				x,
				y,
				play_enabled,
				Color("2a4a28") if selected_preset == preset else Color("243140")
			)
		var selected_fog := _selected_fog_of_war(campaign)
		y = _draw_button(
			"fog_of_war:on",
			"Fog of War On%s" % ("  [selected]" if selected_fog == "on" else ""),
			x,
			y,
			play_enabled,
			Color("2a4a28") if selected_fog == "on" else Color("243140")
		)
		y = _draw_button(
			"fog_of_war:off",
			"Fog of War Off%s" % ("  [selected]" if selected_fog == "off" else ""),
			x,
			y,
			play_enabled,
			Color("2a4a28") if selected_fog == "off" else Color("243140")
		)
	y = _draw_button(
		"continue_campaign",
		"Continue Campaign",
		x,
		y,
		play_enabled and not (play.get("continue_args", []) as Array).is_empty(),
		Color("243140")
	)
	var maintenance: Dictionary = control.get("maintenance", {})
	y = _draw_button(
		"restore_backup",
		"Confirm Restore Latest Backup" if restore_confirm_pending else "Restore Latest Backup",
		x,
		y,
		writeback and bool(maintenance.get("restore_available", false)),
		Color("5a3f18") if restore_confirm_pending else Color("243140")
	)
	y = _draw_button(
		"reset_test_campaign",
		"Confirm Reset Test Campaign" if reset_confirm_pending else "Reset Test Campaign",
		x,
		y,
		writeback and bool(maintenance.get("reset_available", false)),
		Color("5a2418") if reset_confirm_pending else Color("243140")
	)
	if not play_enabled:
		y = _panel_line("Launcher unavailable — start via 'gates-of-codex play'.", x, y, Color("ff8e72"), 11)
	y += 8.0
	y = _panel_heading("ACTIONS", x, y)
	y = _draw_button("fit", "Fit front (F)", x, y, true, Color("243140"))
	y = _draw_button("refresh", "Refresh", x, y, writeback)
	var result := CampaignRulesPresenter.result_model(snapshot)
	if bool(result.get("banner", false)):
		y = _panel_heading(String(result.get("title", "CAMPAIGN RESULT")), x, y)
		y = _panel_line(String(result.get("grade_label", "")), x, y, Color(0.95, 0.84, 0.42, 1.0), 13)
		if not String(result.get("reason", "")).is_empty():
			y = _panel_line(String(result.get("reason", "")), x, y, Color(0.86, 0.88, 0.9, 1.0), 11)
		y = _panel_line(String(result.get("momentum", "")), x, y, Color(0.86, 0.78, 0.52, 1.0), 12)
		if bool(result.get("show_continue", false)):
			y = _draw_button("continue_playing", "Continue Playing", x, y, writeback, Color("24402c"))
		if bool(result.get("show_conclude", false)):
			y = _draw_button("conclude_campaign", "Conclude Campaign", x, y, writeback, Color("5a2418"))
		if bool(result.get("concluded", false)):
			y = _panel_line("Campaign concluded.", x, y, Color(0.78, 0.82, 0.86, 1.0), 11)
		elif bool(result.get("continue_playing", false)):
			y = _panel_line("Victory recorded — continuing.", x, y, Color("8ee2ad"), 11)
	var end_turn_enabled := writeback and not has_battle
	if bool(result.get("visible", false)) and not bool(result.get("continue_playing", false)):
		end_turn_enabled = false
	y = _draw_button("end_turn", "End turn (E)", x, y, end_turn_enabled)
	y = _draw_button("run_ai", "Run AI + advance", x, y, writeback and not has_battle)
	if force_management_open:
		y = _draw_button("close_force_panel", "Close Force Management", x, y, writeback, Color("2a3d28"))
	else:
		y = _draw_button("manage_forces", "Manage Forces", x, y, writeback and not has_battle, Color("243140"))
	y = _draw_button("auto_resolve", "Auto-resolve battle (A)", x, y, writeback and has_battle, Color("4a2f18"))
	y = _draw_button("handoff", "Launch Battle in GoH (H)", x, y, writeback and has_battle, Color("5a2418"))
	if not last_handoff_save_path.is_empty():
		y = _draw_button("verify_result", "Verify Result", x, y, writeback, Color("243140"))
		y = _draw_button(
			"import_battle",
			"Import Result",
			x,
			y,
			writeback and can_import_verified_result(),
			Color("24402c")
		)
		var handoff_status := handoff_status_label()
		if not handoff_status.is_empty():
			y = _panel_line(
				handoff_status,
				x,
				y,
				Color("9fe7a8") if can_import_verified_result() else Color("ffd27a"),
				11
			)
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
	_draw_end_turn_economy_report()


func _draw_end_turn_economy_report() -> void:
	## Compact event-driven overlay. Drawn only from the last End Turn payload.
	if not economy_report_open:
		return
	if economy_report.is_empty() or not bool(economy_report.get("settled", false)):
		return
	var viewport := get_viewport_rect().size
	var extra := 0.0 if String(economy_report.get("other_actors_summary", "")).is_empty() else 20.0
	var card := Rect2(24.0, 24.0, 360.0, 178.0 + extra)
	if card.position.x + card.size.x > viewport.x - PANEL_WIDTH - 16.0:
		card.size.x = maxf(240.0, viewport.x - PANEL_WIDTH - 40.0)
	draw_rect(card, Color(0.04, 0.07, 0.10, 0.94))
	draw_rect(card, Color(0.95, 0.84, 0.42, 0.85), false, 1.5)
	var x := card.position.x + 14.0
	var y := card.position.y + 22.0
	_draw_panel_text("ROUND ECONOMY", Vector2(x, y), 11, Color(0.55, 0.72, 0.86, 1.0))
	y += 20.0
	_draw_panel_text(
		String(economy_report.get("display_name", economy_report.get("actor_id", "Actor"))),
		Vector2(x, y),
		13,
		Color(0.95, 0.84, 0.42, 1.0)
	)
	y += 20.0
	_draw_panel_text(
		"Income %s   Maintenance %s" % [
			_fmt_int(economy_report.get("income", 0)),
			_fmt_int(economy_report.get("maintenance", 0)),
		],
		Vector2(x, y),
		13,
		Color(0.90, 0.94, 0.98, 1.0)
	)
	y += 18.0
	var net := int(economy_report.get("net", 0))
	_draw_panel_text(
		"Net %s   Treasury %s" % [_fmt_signed(net), _fmt_int(economy_report.get("treasury", 0))],
		Vector2(x, y),
		13,
		Color(0.63, 0.90, 0.72, 1.0) if net >= 0 else Color(0.95, 0.62, 0.48, 1.0)
	)
	y += 20.0
	var summary := String(economy_report.get("other_actors_summary", "")).strip_edges()
	if not summary.is_empty():
		_draw_panel_text(summary, Vector2(x, y), 12, Color(0.70, 0.76, 0.82, 1.0))
		y += 20.0
	var dismiss := Rect2(card.position.x + 12.0, card.position.y + card.size.y - 36.0, card.size.x - 24.0, 24.0)
	draw_rect(dismiss, Color(0.10, 0.16, 0.20, 1.0))
	draw_rect(dismiss, Color(0.30, 0.92, 0.76, 0.8), false, 1.0)
	_draw_panel_text("Dismiss report", dismiss.position + Vector2(8, 16), 11, Color.WHITE)
	button_rects["dismiss_economy_report"] = dismiss


func _fmt_signed(value: Variant) -> String:
	var amount := int(value)
	if amount > 0:
		return "+%s" % _fmt_int(amount)
	return _fmt_int(amount)


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
	button_y = _draw_button("handoff", "Launch Battle in GoH (H)", left, button_y, writeback, Color("5a2418"))
	button_y = _draw_button(
		"verify_result",
		"Verify Result",
		left,
		button_y,
		writeback and not last_handoff_save_path.is_empty(),
		Color("243140")
	)
	var modal_handoff_status := handoff_status_label()
	if not modal_handoff_status.is_empty():
		_draw_panel_text(
			modal_handoff_status,
			Vector2(left, button_y + 4.0),
			12,
			Color("9fe7a8") if can_import_verified_result() else Color("ffd27a")
		)
		button_y += 20.0
	button_y = _draw_button(
		"import_battle",
		"Import verified GoH result (I)",
		left,
		button_y,
		writeback \
			and bool(snapshot.get("pending_battle", {}).get("started", false)) \
			and String(snapshot.get("pending_battle", {}).get("id", "")) == last_handoff_battle_id \
			and can_import_verified_result(),
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
	var stack_supply := _stack_supply_summary(force_ids)
	_draw_panel_text(
		"Supply %s   Readiness %s%%" % [
			String(stack_supply.get("label", "Unknown")),
			_fmt_int(stack.get("supply", 0)),
		],
		body.position + Vector2(12, 36),
		11,
		stack_supply.get("color", Color(0.65, 0.77, 0.88, 1.0))
	)

	# Top-level tabs = StrategicFormations (not battalions).
	var tab_y := body.position.y + 52.0
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
	var bn_y := header_y + 102.0
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

	if force_management_open:
		_draw_force_management(body.position.x, bn_y + 8.0, body.size.x, body.position.y + body.size.y)
		return

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


func _draw_force_management(left: float, top: float, width: float, bottom: float) -> void:
	var panel: Dictionary = force_panel
	var writeback := bool(snapshot.get("control", {}).get("enabled", false))
	var y := top
	_draw_panel_text("FORCE MANAGEMENT", Vector2(left + 12, y + 4), 10, Color(0.55, 0.72, 0.86, 1.0))
	y += 18.0
	if panel.is_empty():
		_draw_panel_text(
			"Querying actor treasury and authorized options...",
			Vector2(left + 12, y + 8),
			12,
			Color(0.78, 0.84, 0.90, 1.0)
		)
		return
	_draw_panel_text(
		"%s treasury %s" % [
			String(panel.get("display_name", panel.get("actor_id", "Actor"))),
			_fmt_int(panel.get("resources", 0)),
		],
		Vector2(left + 12, y),
		12,
		Color(0.95, 0.84, 0.42, 1.0)
	)
	y += 16.0
	var blocked: Array = panel.get("blocked_reasons", [])
	if not blocked.is_empty():
		_draw_panel_text(
			String(blocked[0]),
			Vector2(left + 12, y),
			11,
			Color(0.95, 0.62, 0.48, 1.0)
		)
		y += 16.0
	var tabs := ["research", "recruit", "assign", "repair"]
	var tab_w := (width - 16.0) / float(tabs.size())
	var tab_y := y
	for index in range(tabs.size()):
		var tab := String(tabs[index])
		var selected := tab == force_panel_tab
		var rect := Rect2(left + 8.0 + tab_w * index, tab_y, tab_w - 4.0, 26.0)
		draw_rect(rect, Color(0.07, 0.22, 0.18, 1.0) if selected else Color(0.08, 0.11, 0.14, 1.0))
		draw_rect(rect, Color(0.30, 0.92, 0.76, 0.9) if selected else Color(0.27, 0.33, 0.41, 0.75), false, 1.0)
		_draw_panel_text(tab.capitalize(), rect.position + Vector2(6, 17), 11, Color.WHITE)
		button_rects["force_tab:%s" % tab] = rect
	y = tab_y + 36.0
	if force_panel_tab == "research":
		y = _draw_force_research_rows(left, y, width, bottom, writeback, panel)
	elif force_panel_tab == "recruit":
		y = _draw_force_recruit_rows(left, y, width, bottom, writeback, panel)
	elif force_panel_tab == "assign":
		y = _draw_force_assign_rows(left, y, width, bottom, writeback, panel)
	else:
		_draw_force_repair_block(left, y, writeback, panel)


func _draw_force_research_rows(
	left: float,
	y: float,
	_width: float,
	bottom: float,
	writeback: bool,
	panel: Dictionary
) -> float:
	var rows: Array = panel.get("available_research", [])
	if rows.is_empty():
		return _panel_line("No research available for this actor.", left + 8.0, y, Color(0.70, 0.76, 0.82, 1.0), 11)
	var visible := _force_visible_count(y, bottom, rows.size())
	var end_index := mini(force_panel_scroll + visible, rows.size())
	for index in range(force_panel_scroll, end_index):
		var row: Dictionary = rows[index]
		var key := String(row.get("key", ""))
		var cost := int(row.get("cost", 0))
		var can_buy := writeback and int(panel.get("resources", 0)) >= cost and not key.is_empty()
		y = _draw_button(
			"research:%s" % key,
			"Research %s  (%s)" % [String(row.get("display_name", key)), _fmt_int(cost)],
			left + 8.0,
			y,
			can_buy,
			Color("2a3d28") if can_buy else Color("243140")
		)
		if y + 8.0 >= bottom:
			break
	if end_index < rows.size():
		y = _panel_line("+%s more — scroll" % (rows.size() - end_index), left + 8.0, y, Color(0.68, 0.73, 0.79, 1.0), 10)
	return y


func _draw_force_recruit_rows(
	left: float,
	y: float,
	_width: float,
	bottom: float,
	writeback: bool,
	panel: Dictionary
) -> float:
	if not bool(panel.get("can_manage_formation", false)):
		return _panel_line("Select one of this actor's formations to recruit.", left + 8.0, y, Color(0.95, 0.62, 0.48, 1.0), 11)
	var rows: Array = []
	for offer_variant in panel.get("recruitment_offers", []):
		if offer_variant is Dictionary and bool((offer_variant as Dictionary).get("unlocked", false)):
			rows.append(offer_variant)
	if rows.is_empty():
		return _panel_line("No unlocked units on this actor's roster.", left + 8.0, y, Color(0.70, 0.76, 0.82, 1.0), 11)
	var visible := _force_visible_count(y, bottom, rows.size())
	var end_index := mini(force_panel_scroll + visible, rows.size())
	for index in range(force_panel_scroll, end_index):
		var row: Dictionary = rows[index]
		var unit_name := String(row.get("unit_name", ""))
		var cost := int(row.get("purchase_cost", 0))
		var can_buy := writeback and int(panel.get("resources", 0)) >= cost and not unit_name.is_empty()
		y = _draw_button(
			"recruit:%s" % unit_name,
			"Buy %s  (%s)" % [unit_name, _fmt_int(cost)],
			left + 8.0,
			y,
			can_buy,
			Color("2a3d28") if can_buy else Color("243140")
		)
		if y + 8.0 >= bottom:
			break
	if end_index < rows.size():
		y = _panel_line("+%s more — scroll" % (rows.size() - end_index), left + 8.0, y, Color(0.68, 0.73, 0.79, 1.0), 10)
	return y


func _draw_force_assign_rows(
	left: float,
	y: float,
	_width: float,
	bottom: float,
	writeback: bool,
	panel: Dictionary
) -> float:
	if not bool(panel.get("can_manage_formation", false)):
		return _panel_line("Select one of this actor's formations to assign.", left + 8.0, y, Color(0.95, 0.62, 0.48, 1.0), 11)
	var rows: Array = panel.get("reinforcement_pool", [])
	if rows.is_empty():
		return _panel_line("No purchased reinforcements waiting to assign.", left + 8.0, y, Color(0.70, 0.76, 0.82, 1.0), 11)
	var visible := _force_visible_count(y, bottom, rows.size())
	var end_index := mini(force_panel_scroll + visible, rows.size())
	for index in range(force_panel_scroll, end_index):
		var row: Dictionary = rows[index]
		var unit_name := String(row.get("unit_name", ""))
		var qty := int(row.get("quantity", 0))
		var can_assign := writeback and qty > 0 and not selected_battalion_id.is_empty() and not unit_name.is_empty()
		y = _draw_button(
			"assign:%s" % unit_name,
			"Assign %s  x%s" % [unit_name, _fmt_int(qty)],
			left + 8.0,
			y,
			can_assign,
			Color("2a3d28") if can_assign else Color("243140")
		)
		if y + 8.0 >= bottom:
			break
	if end_index < rows.size():
		y = _panel_line("+%s more — scroll" % (rows.size() - end_index), left + 8.0, y, Color(0.68, 0.73, 0.79, 1.0), 10)
	return y


func _draw_force_repair_block(left: float, y: float, writeback: bool, panel: Dictionary) -> void:
	var repair: Dictionary = panel.get("repair", {})
	y = _panel_line(
		"Condition %s%%   Supply %s   Ready %s pt" % [
			_fmt_int(repair.get("condition", 0)),
			_fmt_int(repair.get("supply", 0)),
			_fmt_int(repair.get("points_needed", 0)),
		],
		left + 8.0,
		y,
		Color(0.78, 0.86, 0.92, 1.0),
		11
	)
	y = _panel_line(
		"Repair %s/pt   Afford %s   Cost %s" % [
			_fmt_int(repair.get("cost_per_point", 0)),
			_fmt_int(repair.get("affordable_points", 0)),
			_fmt_int(repair.get("total_cost", 0)),
		],
		left + 8.0,
		y,
		Color(0.78, 0.86, 0.92, 1.0),
		11
	)
	var reasons: Array = repair.get("blocked_reasons", [])
	if not reasons.is_empty():
		y = _panel_line(String(reasons[0]), left + 8.0, y, Color(0.95, 0.62, 0.48, 1.0), 11)
	_draw_button(
		"repair_formation",
		"Repair / replenish",
		left + 8.0,
		y,
		writeback and bool(repair.get("can_repair", false)),
		Color("2a3d28")
	)


func _force_visible_count(y: float, bottom: float, total: int) -> int:
	var room := maxf(bottom - y, 36.0)
	var visible := maxi(int(floor(room / 36.0)), 1)
	if force_panel_scroll > maxi(total - visible, 0):
		force_panel_scroll = maxi(total - visible, 0)
	return visible


func _draw_targets_and_objectives(x: float, y: float) -> float:
	## Graph-native movement surface (#206). Targets are the backend's validated
	## strategic-formation orders; province polygon adjacency is not consulted.
	y = _panel_heading("MOVEMENT ORDERS", x, y)
	var writeback := bool(snapshot.get("control", {}).get("enabled", false))
	var options: Array = orders_by_formation.get(selected_strategic_formation_id, [])
	var order: Dictionary = selected_formation_move_order()
	var order_status := String(order.get("status", ""))
	if not order_status.is_empty():
		y = _panel_line(
			"Standing order: %s -> %s" % [
				order_status.to_upper(),
				_province_name(_order_destination_province(order)),
			],
			x,
			y,
			Color(0.95, 0.84, 0.42, 1.0),
			12
		)
	if options.is_empty():
		if order_status in ["committed", "active"]:
			y = _panel_line(
				"Order locked until it resolves — no new order this turn.",
				x, y, Color(0.7, 0.75, 0.8), 12
			)
		elif selected_strategic_formation_id.is_empty():
			y = _panel_line("Select a strategic formation.", x, y, Color(0.7, 0.75, 0.8), 12)
		else:
			y = _panel_line(
				"No legal graph moves for this formation.",
				x, y, Color(0.7, 0.75, 0.8), 12
			)
	else:
		var shown := 0
		for option: Dictionary in options:
			if shown >= 4:
				y = _panel_line(
					"+%s more reachable — click the map to order." % (options.size() - shown),
					x, y, Color(0.65, 0.7, 0.75), 11
				)
				break
			var tid := String(option.get("target_province_id", ""))
			y = _draw_button(
				"move:%s" % tid,
				"MOVE  %s" % String(option.get("target_province_name", tid)),
				x,
				y,
				writeback,
				Color("2a3d28")
			)
			shown += 1
	if order_status == "draft":
		y = _draw_button("cancel_move_order", "Cancel movement order", x, y, writeback, Color("3d2a28"))
	y += 6.0
	y = _panel_heading("OBJECTIVES", x, y)
	for objective: Dictionary in snapshot.get("objectives", []):
		y = _panel_line(
			CampaignRulesPresenter.objective_progress_line(objective),
			x,
			y,
			Color("8ee2ad") if bool(objective.get("completed", false)) else Color(0.78, 0.82, 0.86, 1.0),
			12
		)
	return y


func _order_destination_province(order: Dictionary) -> String:
	var nodes: Array = order.get("path_node_ids", [])
	if nodes.is_empty():
		return ""
	var destination_node := String(nodes[nodes.size() - 1])
	for option: Dictionary in snapshot.get("operational_orders", []):
		if String(option.get("target_node_id", "")) == destination_node:
			return String(option.get("target_province_id", ""))
	# A locked order has no live option naming its destination, so read the
	# province straight off the graph node instead of guessing from the id.
	var nodes_index: Dictionary = _operational_graph_index().get("nodes", {})
	var node_row: Dictionary = nodes_index.get(destination_node, {})
	return String(node_row.get("province_id", destination_node))


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
	var tab_supply := _formation_supply_presentation(force_id)
	draw_circle(
		rect.position + Vector2(rect.size.x - 8, rect.size.y - 9),
		3.5,
		tab_supply.get("color", Color(0.55, 0.62, 0.70, 1.0))
	)


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
	var supply_row := _formation_supply_presentation(String(force_row.get("id", selected_strategic_formation_id)))
	_draw_panel_text(
		"Supply: %s%s" % [
			String(supply_row.get("label", "Unknown")),
			_supply_source_suffix(supply_row),
		],
		Vector2(left + 12, y + 74),
		11,
		supply_row.get("color", Color(0.83, 0.86, 0.90, 1.0))
	)
	_draw_panel_text(
		"Readiness: %s%%  ·  %s" % [
			_fmt_int(supply_row.get("readiness", 0)),
			String(supply_row.get("repair_label", "repair unknown")),
		],
		Vector2(left + 12, y + 90),
		11,
		Color(0.83, 0.86, 0.90, 1.0)
	)


func _supply_source_suffix(row: Dictionary) -> String:
	var hub := String(row.get("source_hub_id", "")).strip_edges()
	if hub.is_empty():
		return ""
	return " · %s" % hub


func _stack_supply_summary(force_ids: Array) -> Dictionary:
	var worst = {
		"state": "connected",
		"label": "Connected",
		"color": _supply_state_color("connected"),
	}
	var worst_rank := -1
	for force_id_variant in force_ids:
		var row = _formation_supply_presentation(String(force_id_variant))
		var state := String(row.get("state", "disconnected"))
		var value := 1
		if state == "connected":
			value = 0
		elif state == "grace":
			value = 2
		elif state == "cut_off":
			value = 3
		if value > worst_rank:
			worst_rank = value
			worst = row
	return worst


func _formation_supply_presentation(force_id: String) -> Dictionary:
	if force_id.is_empty():
		return {
			"state": "unknown",
			"label": "Unknown",
			"color": Color(0.70, 0.76, 0.82, 1.0),
			"readiness": 0,
			"repair_label": "repair unknown",
			"source_hub_id": "",
		}
	if supply_query_cache.has(force_id):
		var cached = supply_query_cache[force_id]
		if cached is Dictionary:
			return _supply_presentation_from_query(cached)
	return _supply_presentation_from_snapshot(force_id)


func _supply_presentation_from_query(row: Dictionary) -> Dictionary:
	var state := String(row.get("supply_state", "disconnected"))
	var readiness = row.get("readiness", {})
	if not readiness is Dictionary:
		readiness = {}
	var can_repair := bool(readiness.get("can_repair", false))
	var repair_label := "repair blocked"
	if can_repair:
		repair_label = "repair ready"
	return {
		"state": state,
		"label": _supply_state_label(state),
		"color": _supply_state_color(state),
		"readiness": int(readiness.get("supply", 0)),
		"repair_label": repair_label,
		"source_hub_id": String(row.get("source_hub_id", "")),
		"effect": String(row.get("effect", "")),
	}


func _supply_presentation_from_snapshot(force_id: String) -> Dictionary:
	var force = _s10_formation_row(force_id)
	var supplied := bool(force.get("supplied", true))
	var cut_off := bool(force.get("cut_off", false))
	var source := String(force.get("source_hub_id", "")).strip_edges()
	var state := "disconnected"
	if cut_off:
		state = "cut_off"
	elif supplied:
		state = "connected"
	var repair_label := "repair blocked"
	if supplied and not cut_off:
		repair_label = "repair ready"
	return {
		"state": state,
		"label": _supply_state_label(state),
		"color": _supply_state_color(state),
		"readiness": int(force.get("supply_summary", 0)),
		"repair_label": repair_label,
		"source_hub_id": source,
		"effect": "",
	}


func _supply_state_label(state: String) -> String:
	if state == "connected":
		return "Connected"
	if state == "grace":
		return "Grace"
	if state == "cut_off":
		return "Cut-off"
	if state == "initial_disconnected" or state == "disconnected":
		return "Disconnected"
	return "Unknown"


func _supply_state_color(state: String) -> Color:
	if state == "connected":
		return Color(0.45, 0.86, 0.62, 1.0)
	if state == "grace":
		return Color(0.95, 0.84, 0.42, 1.0)
	if state == "cut_off":
		return Color(0.98, 0.46, 0.38, 1.0)
	return Color(0.95, 0.78, 0.48, 1.0)


func _maybe_request_supply_query() -> void:
	## Event-driven: only the selected stack, never from _process or a province scan.
	if selected_strategic_formation_id.is_empty():
		return
	if supply_query_cache.has(selected_strategic_formation_id):
		return
	if is_command_busy():
		return
	var control: Dictionary = snapshot.get("control", {})
	if not bool(control.get("enabled", false)):
		return
	var supported: Array = control.get("supported_ops", [])
	if not supported.has("query_supply"):
		return
	_queue_and_apply([{
		"op": "query_supply",
		"strategic_formation_id": selected_strategic_formation_id,
		"province_id": selected_province_id,
	}])


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
		if (event as InputEventKey).keycode == KEY_ESCAPE and economy_report_open:
			_handle_button("dismiss_economy_report")
			get_viewport().set_input_as_handled()
			return
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
					_maybe_request_supply_query()
					status_message = "Selected formation %s (acting battalion %s)." % [
						force_row.get("display_name", force_id),
						_selected_presentation().get("battalion_label", selected_battalion_id),
					]
					if force_management_open:
						force_panel_scroll = 0
						request_force_panel()
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
					if force_management_open:
						force_panel_scroll = 0
						request_force_panel()
					queue_redraw()
					get_viewport().set_input_as_handled()
					return
		elif mouse.button_index == MOUSE_BUTTON_WHEEL_UP and stack_panel_expanded:
			if Rect2(get_viewport_rect().size.x - PANEL_WIDTH, 0, PANEL_WIDTH, get_viewport_rect().size.y).has_point(mouse.position):
				if force_management_open:
					force_panel_scroll = maxi(force_panel_scroll - 1, 0)
				else:
					unit_scroll_offset = maxi(unit_scroll_offset - 1, 0)
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
		elif mouse.button_index == MOUSE_BUTTON_WHEEL_DOWN and stack_panel_expanded:
			if Rect2(get_viewport_rect().size.x - PANEL_WIDTH, 0, PANEL_WIDTH, get_viewport_rect().size.y).has_point(mouse.position):
				if force_management_open:
					force_panel_scroll += 1
				else:
					unit_scroll_offset += 1
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
	super._unhandled_input(event)
