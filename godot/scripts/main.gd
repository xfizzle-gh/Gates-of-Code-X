extends Node2D

const DEFAULT_SNAPSHOT := "res://campaign_snapshot.json"
const PANEL_WIDTH := 400.0
const MAP_MARGIN := Vector2(48, 48)
const BUTTON_HEIGHT := 30.0
const BASE_HIT_RADIUS := 18.0
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}

var snapshot: Dictionary = {}
var provinces_by_id: Dictionary = {}
var battalions_by_province: Dictionary = {}
var formations_by_id: Dictionary = {}
var factions_by_id: Dictionary = {}
var front_by_origin: Dictionary = {}
## Graph-native movement authority (#206): strategic_formation_id -> Array of
## legal route rows exported by the backend, each carrying the full authenticated
## node/edge path. Province polygon adjacency never derives a player order.
var orders_by_formation: Dictionary = {}
## province_id -> Array of strategic_formation_ids that have a legal order there.
var order_formations_by_province: Dictionary = {}
var selected_strategic_formation_id := ""
var legal_targets: Dictionary = {}
var focus_province_ids: Dictionary = {}
var load_error := ""
var status_message := ""
var last_handoff_name := ""
var last_handoff_save_path := ""
var last_handoff_battle_id := ""
var snapshot_source_path := ""
var view_scale := 1.0
var view_offset := Vector2.ZERO
var dragging := false
var last_mouse_position := Vector2.ZERO
var selected_province_id := ""
var button_rects: Dictionary = {}
var fitted_once := false


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	snapshot_source_path = DEFAULT_SNAPSHOT
	for arg in args:
		var text := String(arg)
		if text.begins_with("--snapshot="):
			snapshot_source_path = text.substr(String("--snapshot=").length()).strip_edges()
			continue
		if text.begins_with("--"):
			continue
		if text.is_empty():
			continue
		# Positional snapshot path (non-flag) wins only when --snapshot= was not set.
		if snapshot_source_path == DEFAULT_SNAPSHOT:
			snapshot_source_path = text
			break
	_load_snapshot(snapshot_source_path)
	_fit_to_focus(true)
	queue_redraw()


func _load_snapshot(path: String) -> void:
	provinces_by_id.clear()
	battalions_by_province.clear()
	formations_by_id.clear()
	factions_by_id.clear()
	front_by_origin.clear()
	orders_by_formation.clear()
	order_formations_by_province.clear()
	legal_targets.clear()
	focus_province_ids.clear()
	button_rects.clear()
	load_error = ""

	if not FileAccess.file_exists(path):
		load_error = "Campaign snapshot not found: %s" % path
		return
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		load_error = "Unable to open campaign snapshot: %s" % path
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		load_error = "Campaign snapshot is not valid JSON."
		return
	snapshot = parsed
	if snapshot.get("schema", "") != "gates-of-codex.frontend":
		load_error = "Unsupported campaign snapshot schema."
		snapshot = {}
		return
	for province: Dictionary in snapshot.get("provinces", []):
		provinces_by_id[String(province.get("id", ""))] = province
	for battalion: Dictionary in snapshot.get("battalions", []):
		battalions_by_province[String(battalion.get("province_id", ""))] = battalion
	for formation: Dictionary in snapshot.get("formations", []):
		formations_by_id[String(formation.get("id", ""))] = formation
	for faction: Dictionary in snapshot.get("factions", []):
		factions_by_id[String(faction.get("id", ""))] = faction
	for option: Dictionary in snapshot.get("front_options", []):
		var origin := String(option.get("origin", ""))
		if not front_by_origin.has(origin):
			front_by_origin[origin] = []
		(front_by_origin[origin] as Array).append(option)
	var indexed := index_operational_orders(snapshot)
	orders_by_formation = indexed.get("by_formation", {})
	order_formations_by_province = indexed.get("by_province", {})
	_select_default_province()
	_rebuild_legal_targets()
	_rebuild_focus_set()


func _select_default_province() -> void:
	if not selected_province_id.is_empty() and provinces_by_id.has(selected_province_id):
		return
	var pending: Variant = snapshot.get("pending_battle")
	if pending is Dictionary:
		selected_province_id = String((pending as Dictionary).get("origin_province_id", ""))
		if not selected_province_id.is_empty():
			return
	var campaign: Dictionary = snapshot.get("campaign", {})
	var current := String(campaign.get("current_faction", ""))
	# Prefer a formation that has an authoritative graph order: on a graph-native
	# campaign that is the only surface that can actually issue movement.
	for option: Dictionary in snapshot.get("operational_orders", []):
		if String(option.get("faction", "")) != current:
			continue
		var origin_province := String(option.get("origin_province_id", ""))
		if origin_province.is_empty():
			continue
		selected_province_id = origin_province
		selected_strategic_formation_id = String(option.get("formation_id", ""))
		return
	for option: Dictionary in snapshot.get("front_options", []):
		var origin := String(option.get("origin", ""))
		var battalion: Dictionary = battalions_by_province.get(origin, {})
		if String(battalion.get("faction", "")) == current:
			selected_province_id = origin
			return
	for battalion: Dictionary in snapshot.get("battalions", []):
		if String(battalion.get("faction", "")) == current:
			selected_province_id = String(battalion.get("province_id", ""))
			return
	if not provinces_by_id.is_empty():
		selected_province_id = String(provinces_by_id.keys()[0])


func index_operational_orders(source: Dictionary) -> Dictionary:
	## Index the backend's legal graph orders. Every row already passed the same
	## gates the authoritative commit runs, so nothing here re-derives legality.
	var by_formation: Dictionary = {}
	var by_province: Dictionary = {}
	for option: Dictionary in source.get("operational_orders", []):
		var formation_id := String(option.get("formation_id", ""))
		if formation_id.is_empty():
			continue
		if not by_formation.has(formation_id):
			by_formation[formation_id] = []
		(by_formation[formation_id] as Array).append(option)
		var origin := String(option.get("origin_province_id", ""))
		if origin.is_empty():
			continue
		if not by_province.has(origin):
			by_province[origin] = []
		var holders: Array = by_province[origin]
		if not holders.has(formation_id):
			holders.append(formation_id)
	return {"by_formation": by_formation, "by_province": by_province}


func formation_ids_at_province(province_id: String) -> Array:
	var stack: Dictionary = snapshot.get("stack_presentations", {}).get(province_id, {})
	return (stack.get("strategic_formation_ids", []) as Array).duplicate()


func _ensure_order_formation_selection() -> void:
	## Keep the ordering formation consistent with the selected province, but
	## never override a formation the player explicitly selected there — a force
	## with no legal graph order must be able to report exactly that.
	if not selected_strategic_formation_id.is_empty() \
	and formation_ids_at_province(selected_province_id).has(selected_strategic_formation_id):
		return
	var holders: Array = order_formations_by_province.get(selected_province_id, [])
	if not holders.is_empty():
		selected_strategic_formation_id = String(holders[0])
		return
	var present := formation_ids_at_province(selected_province_id)
	selected_strategic_formation_id = String(present[0]) if not present.is_empty() else ""


func _rebuild_legal_targets() -> void:
	legal_targets.clear()
	_ensure_order_formation_selection()
	for option: Dictionary in orders_by_formation.get(selected_strategic_formation_id, []):
		legal_targets[String(option.get("target_province_id", ""))] = option


func _rebuild_focus_set() -> void:
	focus_province_ids.clear()
	if not selected_province_id.is_empty():
		focus_province_ids[selected_province_id] = true
	for target_id in legal_targets.keys():
		focus_province_ids[String(target_id)] = true
	var pending: Variant = snapshot.get("pending_battle")
	if pending is Dictionary:
		var battle := pending as Dictionary
		focus_province_ids[String(battle.get("origin_province_id", ""))] = true
		focus_province_ids[String(battle.get("target_province_id", ""))] = true


func _draw() -> void:
	if not load_error.is_empty():
		draw_string(ThemeDB.fallback_font, Vector2(32, 54), load_error, HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color("f08080"))
		return
	if snapshot.is_empty():
		return

	_draw_pending_battle_link()
	for edge: Array in snapshot.get("edges", []):
		if edge.size() != 2:
			continue
		var left: Dictionary = provinces_by_id.get(String(edge[0]), {})
		var right: Dictionary = provinces_by_id.get(String(edge[1]), {})
		if left.is_empty() or right.is_empty():
			continue
		var alpha := 0.45 if focus_province_ids.has(String(edge[0])) or focus_province_ids.has(String(edge[1])) else 0.18
		draw_line(_map_to_screen(left), _map_to_screen(right), Color(0.4, 0.46, 0.52, alpha), 1.2)

	for province: Dictionary in snapshot.get("provinces", []):
		_draw_province(province)

	var campaign: Dictionary = snapshot.get("campaign", {})
	var title := "%s  |  Turn %s  |  %s" % [
		campaign.get("name", "Gates of CodeX"),
		campaign.get("turn_number", 1),
		String(campaign.get("current_faction", "")).to_upper(),
	]
	draw_string(ThemeDB.fallback_font, Vector2(24, 34), title, HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color.WHITE)
	var hint := "F fit front  |  click unit then green/orange neighbor  |  wheel zoom  |  drag pan"
	if not status_message.is_empty():
		hint = status_message
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, get_viewport_rect().size.y - 22),
		hint,
		HORIZONTAL_ALIGNMENT_LEFT,
		get_viewport_rect().size.x - PANEL_WIDTH - 48,
		14,
		Color(0.78, 0.82, 0.86, 0.95)
	)
	_draw_management_panel()


func _draw_pending_battle_link() -> void:
	var pending: Variant = snapshot.get("pending_battle")
	if not pending is Dictionary:
		return
	var battle := pending as Dictionary
	var origin: Dictionary = provinces_by_id.get(String(battle.get("origin_province_id", "")), {})
	var target: Dictionary = provinces_by_id.get(String(battle.get("target_province_id", "")), {})
	if origin.is_empty() or target.is_empty():
		return
	draw_line(_map_to_screen(origin), _map_to_screen(target), Color("ff9f43"), 3.0)


func _draw_province(province: Dictionary) -> void:
	var position := _map_to_screen(province)
	var owner := String(province.get("owner", "neutral"))
	var color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])
	var province_id := String(province.get("id", ""))
	var battalion: Dictionary = battalions_by_province.get(province_id, {})
	var occupied := not battalion.is_empty()
	var selected := province_id == selected_province_id
	var target_option: Dictionary = legal_targets.get(province_id, {})
	var in_focus := focus_province_ids.has(province_id)
	if not in_focus and not occupied:
		color.a = 0.42
	# Soft ownership blob (MapChart-style stand-in until color-ID texture pipeline).
	var blob := color
	blob.a = 0.22 if occupied else 0.12
	if in_focus:
		blob.a += 0.08
	draw_circle(position, 14.0 if occupied else 9.0, blob)
	draw_circle(position, 3.0 if occupied else 2.2, color)
	if selected:
		draw_arc(position, 18.0, 0.0, TAU, 36, Color("7fe7ff"), 2.4)
	if not target_option.is_empty():
		# Contact is decided by the authoritative tick, not by the order. Colour
		# the ring from what the observer already sees on the map.
		var contested := _province_holds_hostile_formation(province_id)
		var ring := Color("ff9f43") if contested else Color("7dffa3")
		draw_arc(position, 16.0, 0.0, TAU, 32, ring, 2.6)
	if occupied:
		_draw_battalion_counter(position, battalion, color, selected)
	var infrastructure: Dictionary = province.get("infrastructure", {})
	if int(infrastructure.get("supply_hub", 0)) > 0:
		draw_rect(Rect2(position + Vector2(-12, 10), Vector2(5, 5)), Color("63d69f"))
	if int(infrastructure.get("command_post", 0)) > 0:
		draw_rect(Rect2(position + Vector2(-4, 10), Vector2(5, 5)), Color("b892ff"))
	var label := String(province.get("display_name", province_id))
	var named := not label.to_lower().begins_with("province")
	var show_label := occupied or selected or not target_option.is_empty()
	if not show_label and view_scale >= 2.4 and named:
		show_label = true
	if show_label:
		draw_string(
			ThemeDB.fallback_font,
			position + Vector2(12, -8),
			label,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			12 if selected or not target_option.is_empty() or occupied else 11,
			Color(0.92, 0.94, 0.96, 0.95 if in_focus or occupied else 0.55)
		)


func _draw_battalion_counter(position: Vector2, battalion: Dictionary, color: Color, selected: bool) -> void:
	# HOI-style army counter: faction diamond + type glyph + strength.
	var size := Vector2(34, 22)
	var rect := Rect2(position - size * 0.5 + Vector2(0, -2), size)
	var fill := color.darkened(0.25)
	fill.a = 0.95
	draw_rect(rect, fill)
	draw_rect(rect, Color.WHITE if selected else Color(0.1, 0.1, 0.12, 0.95), false, 1.5)
	var supplied: bool = battalion.get("is_in_supply", true)
	if not supplied:
		draw_rect(Rect2(rect.position, Vector2(4, rect.size.y)), Color("ff6b5f"))
	if int(battalion.get("encircled_turns", 0)) > 0:
		draw_rect(Rect2(rect.position + Vector2(rect.size.x - 4, 0), Vector2(4, rect.size.y)), Color("ffb14e"))
	var type_code := _battalion_type_glyph(String(battalion.get("battalion_type", "")))
	var strength := int(battalion.get("unit_count", 0))
	var label := "%s %s" % [type_code, strength]
	draw_string(
		ThemeDB.fallback_font,
		rect.position + Vector2(6, 15),
		label,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		12,
		Color.WHITE
	)


func _battalion_type_glyph(battalion_type: String) -> String:
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
		return "✈"
	if "inf" in key:
		return "I"
	return "X"


func _draw_management_panel() -> void:
	button_rects.clear()
	var viewport := get_viewport_rect().size
	var panel_x := viewport.x - PANEL_WIDTH
	draw_rect(Rect2(panel_x, 0, PANEL_WIDTH, viewport.y), Color(0.04, 0.055, 0.07, 0.98))
	draw_line(Vector2(panel_x, 0), Vector2(panel_x, viewport.y), Color(0.25, 0.31, 0.37, 0.9), 2.0)
	var x := panel_x + 18.0
	var y := 28.0
	y = _panel_heading("CAMPAIGN COMMAND", x, y)

	var campaign: Dictionary = snapshot.get("campaign", {})
	var selected_faction := String(campaign.get("selected_faction", ""))
	var faction: Dictionary = factions_by_id.get(selected_faction, {})
	y = _panel_line("Faction: %s   Current: %s" % [selected_faction.to_upper(), String(campaign.get("current_faction", "")).to_upper()], x, y)
	y = _panel_line("Resources %s   Inc/Maint %s/%s" % [
		faction.get("resources", 0),
		faction.get("income_last_round", 0),
		faction.get("maintenance_last_round", 0),
	], x, y)
	var names: Dictionary = snapshot.get("province_names", {})
	if names.is_empty():
		var meta: Dictionary = campaign.get("map_metadata", {})
		names = meta.get("province_names", {})
	if not names.is_empty():
		y = _panel_line("Names %s/%s human-readable (%s%%)" % [
			names.get("human_readable", 0),
			names.get("total", 0),
			names.get("human_readable_pct", 0),
		], x, y, Color("9fd7ff"), 12)
	y += 6.0

	y = _panel_heading("ACTIONS", x, y)
	var control: Dictionary = snapshot.get("control", {})
	var writeback := bool(control.get("enabled", false))
	var has_battle := snapshot.get("pending_battle") != null
	y = _draw_button("fit", "Fit front (F)", x, y, true, Color("243140"))
	y = _draw_button("refresh", "Refresh", x, y, writeback)
	y = _draw_button("end_turn", "End turn (E)", x, y, writeback and not has_battle)
	y = _draw_button("run_ai", "Run AI + advance", x, y, writeback and not has_battle)
	y = _draw_button("auto_resolve", "Auto-resolve battle (A)", x, y, writeback and has_battle, Color("4a2f18"))
	y = _draw_button("handoff", "Handoff to GoH (H)", x, y, writeback and has_battle, Color("5a2418"))
	if not last_handoff_name.is_empty():
		y = _panel_line("Load Conquest: %s" % last_handoff_name, x, y, Color("ffd27a"), 12)
	if not writeback:
		y = _panel_line("Write-back off — re-export frontend.", x, y, Color("f08080"), 12)
	y += 6.0

	y = _panel_heading("SELECTED", x, y)
	var province: Dictionary = provinces_by_id.get(selected_province_id, {})
	if province.is_empty():
		y = _panel_line("Click a province on the map.", x, y)
	else:
		y = _panel_line(String(province.get("display_name", selected_province_id)), x, y, Color.WHITE, 16)
		if String(province.get("display_name", "")) != selected_province_id:
			y = _panel_line("ID %s" % selected_province_id, x, y, Color("9aa7b2"), 12)
		y = _panel_line("Owner %s   Yield %s   Fort %s" % [
			String(province.get("owner", "neutral")).to_upper(),
			province.get("resource_yield", 0),
			province.get("fortification", 0),
		], x, y)
		var battalion: Dictionary = battalions_by_province.get(selected_province_id, {})
		if not battalion.is_empty():
			var formation: Dictionary = formations_by_id.get(String(battalion.get("formation_id", "")), {})
			y = _panel_line(String(formation.get("display_name", battalion.get("formation_id", "Formation"))), x, y, Color("9fd7ff"))
			y = _panel_line("Str %s/%s  Cond %s  Sup %s  Mv/Cbt %s/%s" % [
				battalion.get("unit_count", 0),
				battalion.get("authorized_unit_count", 0),
				battalion.get("condition", 0),
				battalion.get("supply", 0),
				battalion.get("movement_remaining", 0),
				battalion.get("combat_actions_remaining", 0),
			], x, y)
		var options: Array = province.get("construction_options", [])
		var construct_count := 0
		for option: Dictionary in options:
			if not option.get("available", false) or not writeback or construct_count >= 3:
				continue
			var key := "construct:%s" % String(option.get("building", ""))
			var line := "+ %s L%s (%s)" % [
				String(option.get("building", "")).replace("_", " ").capitalize(),
				option.get("next_level", 0),
				option.get("cost", 0),
			]
			y = _draw_button(key, line, x, y, true, Color("1f3d2c"))
			construct_count += 1
		var targets: Array = orders_by_formation.get(selected_strategic_formation_id, [])
		if not targets.is_empty():
			y += 4.0
			y = _panel_line("MOVEMENT ORDERS (click map or button)", x, y, Color("ffd27a"), 12)
			var shown := 0
			for option: Dictionary in targets:
				var tid := String(option.get("target_province_id", ""))
				var label := "MOVE  %s" % option.get("target_province_name", tid)
				y = _draw_button("move:%s" % tid, label, x, y, writeback, Color("2a3d28"))
				shown += 1
				if shown >= 6:
					break
	y += 8.0

	var pending: Variant = snapshot.get("pending_battle")
	if pending is Dictionary:
		y = _panel_heading("PENDING BATTLE", x, y)
		var battle := pending as Dictionary
		y = _panel_line(String(battle.get("id", "")), x, y, Color("ffb14e"), 12)
		var origin_name := _province_name(String(battle.get("origin_province_id", "")))
		var target_name := _province_name(String(battle.get("target_province_id", "")))
		y = _panel_line("%s  ->  %s" % [origin_name, target_name], x, y, Color.WHITE, 13)
		y = _panel_line("%s attacks %s" % [
			String(battle.get("attacker_faction", "")).to_upper(),
			String(battle.get("defender_faction", "")).to_upper(),
		], x, y, Color("d4dbe2"), 12)

	y = _panel_heading("OBJECTIVES", x, y)
	var shown_obj := 0
	for objective: Dictionary in snapshot.get("objectives", []):
		if objective.get("coalition", "") != _selected_coalition(selected_faction):
			continue
		var completed: bool = objective.get("completed", false)
		var prefix := "DONE" if completed else "%s/%s" % [objective.get("progress", 0), objective.get("required", 0)]
		y = _panel_line("%s  %s" % [prefix, objective.get("display_name", "Objective")], x, y, Color("8ee2ad") if completed else Color("d4dbe2"), 12)
		shown_obj += 1
		if shown_obj >= 4:
			break


func _province_holds_hostile_formation(province_id: String) -> bool:
	var campaign: Dictionary = snapshot.get("campaign", {})
	var current := String(campaign.get("current_faction", ""))
	for force: Dictionary in snapshot.get("strategic_formations", []):
		if String(force.get("province_id", "")) != province_id:
			continue
		if String(force.get("faction", "")) != current:
			return true
	return false


func _province_name(province_id: String) -> String:
	var province: Dictionary = provinces_by_id.get(province_id, {})
	if province.is_empty():
		return province_id
	return String(province.get("display_name", province_id))


func _draw_button(id: String, label: String, x: float, y: float, enabled: bool, fill := Color("1a2a38")) -> float:
	var rect := Rect2(x, y - 16.0, PANEL_WIDTH - 36.0, BUTTON_HEIGHT)
	var bg := fill if enabled else Color("1a1f24")
	var fg := Color.WHITE if enabled else Color("6b737a")
	draw_rect(rect, bg)
	draw_rect(rect, Color(0.4, 0.5, 0.58, 0.95 if enabled else 0.3), false, 1.0)
	draw_string(ThemeDB.fallback_font, Vector2(x + 10.0, y + 3.0), label, HORIZONTAL_ALIGNMENT_LEFT, PANEL_WIDTH - 56, 13, fg)
	if enabled:
		button_rects[id] = rect
	return y + BUTTON_HEIGHT + 7.0


func _selected_coalition(faction_id: String) -> String:
	for alliance: Dictionary in snapshot.get("alliances", []):
		if faction_id in alliance.get("factions", []):
			return String(alliance.get("id", ""))
	return ""


func _panel_heading(text: String, x: float, y: float) -> float:
	draw_string(ThemeDB.fallback_font, Vector2(x, y), text, HORIZONTAL_ALIGNMENT_LEFT, PANEL_WIDTH - 40, 14, Color("78bce8"))
	return y + 22.0


func _panel_line(text: String, x: float, y: float, color := Color("d4dbe2"), size := 13) -> float:
	draw_string(ThemeDB.fallback_font, Vector2(x, y), text, HORIZONTAL_ALIGNMENT_LEFT, PANEL_WIDTH - 40, size, color)
	return y + float(size + 6)


func _map_to_screen(province: Dictionary) -> Vector2:
	var bounds: Dictionary = snapshot.get("bounds", {})
	var min_x: float = float(bounds.get("min_x", 0.0))
	var max_x: float = float(bounds.get("max_x", 1.0))
	var min_y: float = float(bounds.get("min_y", 0.0))
	var max_y: float = float(bounds.get("max_y", 1.0))
	var span_x: float = maxf(max_x - min_x, 1.0)
	var span_y: float = maxf(max_y - min_y, 1.0)
	var viewport_size := get_viewport_rect().size
	var map_size := Vector2(viewport_size.x - PANEL_WIDTH, viewport_size.y)
	var available := map_size - MAP_MARGIN * 2.0
	var normalized := Vector2(
		(float(province.get("x", 0.0)) - min_x) / span_x,
		(float(province.get("y", 0.0)) - min_y) / span_y
	)
	var base := MAP_MARGIN + normalized * available
	var center := map_size * 0.5
	return (base - center) * view_scale + center + view_offset


func _province_at(screen_position: Vector2) -> String:
	var best_id := ""
	var best_distance: float = BASE_HIT_RADIUS * maxf(view_scale, 1.0)
	for province: Dictionary in snapshot.get("provinces", []):
		var distance: float = screen_position.distance_to(_map_to_screen(province))
		var bonus: float = 0.0
		var pid := String(province.get("id", ""))
		if pid == selected_province_id or legal_targets.has(pid) or battalions_by_province.has(pid):
			bonus = 8.0
		if distance < best_distance + bonus:
			best_distance = distance
			best_id = pid
	return best_id


func _button_at(screen_position: Vector2) -> String:
	for id in button_rects.keys():
		var rect: Rect2 = button_rects[id]
		if rect.has_point(screen_position):
			return String(id)
	return ""


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		var key := event as InputEventKey
		if key.keycode == KEY_F:
			_fit_to_focus(true)
			return
		if key.keycode == KEY_E:
			_handle_button("end_turn")
			return
		if key.keycode == KEY_A:
			_handle_button("auto_resolve")
			return
		if key.keycode == KEY_H:
			_handle_button("handoff")
			return
		if key.keycode == KEY_R:
			_handle_button("refresh")
			return
	if event is InputEventMouseButton:
		var mouse_button := event as InputEventMouseButton
		var map_width := get_viewport_rect().size.x - PANEL_WIDTH
		if mouse_button.button_index == MOUSE_BUTTON_LEFT:
			if mouse_button.pressed:
				if mouse_button.position.x >= map_width:
					var button_id := _button_at(mouse_button.position)
					if not button_id.is_empty():
						_handle_button(button_id)
					dragging = false
					return
				var province_id := _province_at(mouse_button.position)
				if not province_id.is_empty():
					if legal_targets.has(province_id):
						_issue_move(province_id)
					else:
						selected_province_id = province_id
						_rebuild_legal_targets()
						_rebuild_focus_set()
						status_message = ""
						queue_redraw()
					dragging = false
				else:
					dragging = true
					last_mouse_position = mouse_button.position
			else:
				dragging = false
		elif mouse_button.pressed and mouse_button.position.x < map_width and mouse_button.button_index == MOUSE_BUTTON_WHEEL_UP:
			_zoom_at(mouse_button.position, 1.14)
		elif mouse_button.pressed and mouse_button.position.x < map_width and mouse_button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			_zoom_at(mouse_button.position, 1.0 / 1.14)
	elif event is InputEventMouseMotion and dragging:
		var motion := event as InputEventMouseMotion
		view_offset += motion.position - last_mouse_position
		last_mouse_position = motion.position
		queue_redraw()


func _handle_button(button_id: String) -> void:
	if button_id == "fit":
		_fit_to_focus(true)
		return
	if button_id == "refresh":
		_queue_and_apply([{"op": "refresh"}])
		return
	if button_id == "end_turn":
		_queue_and_apply([{"op": "end_turn"}])
		return
	if button_id == "run_ai":
		var campaign: Dictionary = snapshot.get("campaign", {})
		_queue_and_apply([{
			"op": "run_ai",
			"faction": String(campaign.get("current_faction", "")),
			"advance_turn": true,
		}])
		return
	if button_id == "auto_resolve":
		_queue_and_apply([{"op": "auto_resolve"}])
		return
	if button_id == "handoff":
		_queue_and_apply([{"op": "handoff", "work_root": "live", "backup_root": "backups"}])
		return
	if button_id == "cancel_move_order":
		_cancel_graph_move_order()
		return
	if button_id.begins_with("move:"):
		_issue_move(button_id.trim_prefix("move:"))
		return
	if button_id.begins_with("construct:"):
		var building := button_id.trim_prefix("construct:")
		var campaign2: Dictionary = snapshot.get("campaign", {})
		_queue_and_apply([{
			"op": "construct",
			"province": selected_province_id,
			"building": building,
			"faction": String(campaign2.get("selected_faction", campaign2.get("current_faction", ""))),
		}])


func _issue_move(target_province_id: String) -> void:
	var option: Dictionary = legal_targets.get(target_province_id, {})
	if option.is_empty():
		return
	_issue_graph_move_order(option)


func _issue_graph_move_order(option: Dictionary) -> void:
	## Graph-native order dispatch (#206). The command carries the strategic
	## formation ID and the authenticated node/edge path; it never names a
	## battalion or a polygon neighbour.
	var formation_id := String(option.get("formation_id", ""))
	var path_node_ids: Array = option.get("path_node_ids", [])
	var path_edge_ids: Array = option.get("path_edge_ids", [])
	if formation_id.is_empty() or path_node_ids.size() < 2 or path_edge_ids.is_empty():
		# Never fall back to province adjacency: refuse instead of guessing.
		status_message = "Order refused: snapshot option carries no graph path authority."
		queue_redraw()
		return
	# Draft then commit as one authoritative batch. Neither op self-commits, so a
	# rejected commit discards the draft with the rest of the batch.
	_queue_and_apply([
		{
			"op": "issue_move_order",
			"formation": formation_id,
			"path_node_ids": path_node_ids.duplicate(),
			"path_edge_ids": path_edge_ids.duplicate(),
		},
		{
			"op": "commit_move_orders",
			"faction": String(option.get("faction", "")),
			"locked_stance": String(option.get("locked_stance", "operational")),
		},
	])


func _cancel_graph_move_order() -> void:
	if selected_strategic_formation_id.is_empty():
		status_message = "Select a strategic formation before cancelling its order."
		queue_redraw()
		return
	_queue_and_apply([{
		"op": "cancel_move_order",
		"formation": selected_strategic_formation_id,
	}])


func _queue_and_apply(commands: Array) -> void:
	var control: Dictionary = snapshot.get("control", {})
	if not bool(control.get("enabled", false)):
		status_message = "Write-back disabled. Re-export frontend with campaign path."
		queue_redraw()
		return
	var commands_path := String(control.get("commands_path", ""))
	var campaign_path := String(control.get("campaign_path", ""))
	var snapshot_path := String(control.get("snapshot_path", ""))
	if commands_path.is_empty() or campaign_path.is_empty() or snapshot_path.is_empty():
		status_message = "Control paths missing from snapshot."
		queue_redraw()
		return
	var payload := {"commands": commands}
	var file := FileAccess.open(commands_path, FileAccess.WRITE)
	if file == null:
		status_message = "Unable to write commands: %s" % commands_path
		queue_redraw()
		return
	file.store_string(JSON.stringify(payload, "\t"))
	file.close()

	var args := [
		"apply-frontend",
		campaign_path,
		"--snapshot",
		snapshot_path,
		"--commands",
		commands_path,
	]
	var output: Array = []
	var exit_code := OS.execute("gates-of-codex", args, output, true, false)
	if exit_code == -1:
		output.clear()
		var python_args := ["-m", "gates_of_codex"]
		python_args.append_array(args)
		exit_code = OS.execute("python", python_args, output, true, false)
	var joined := "\n".join(output)
	if exit_code != 0:
		status_message = "Apply failed: %s" % joined.substr(0, 200)
		queue_redraw()
		return
	_parse_apply_output(joined)
	var previous_selected := selected_province_id
	_load_snapshot(snapshot_path if not snapshot_path.is_empty() else snapshot_source_path)
	if provinces_by_id.has(previous_selected):
		selected_province_id = previous_selected
		_rebuild_legal_targets()
		_rebuild_focus_set()
	var op := String((commands[0] as Dictionary).get("op", "command"))
	if status_message.is_empty():
		status_message = "Applied %s." % op
	if snapshot.get("pending_battle") != null and op != "handoff":
		status_message += " Pending battle ready — Auto-resolve or Handoff."
	_fit_to_focus(false)
	queue_redraw()


func _parse_apply_output(text: String) -> void:
	status_message = ""
	if text.strip_edges().is_empty():
		return
	var parsed: Variant = JSON.parse_string(text)
	if not parsed is Dictionary:
		return
	var payload := parsed as Dictionary
	for result: Dictionary in payload.get("results", []):
		if String(result.get("op", "")) == "handoff" and bool(result.get("ok", false)):
			var data: Dictionary = result.get("data", {})
			last_handoff_name = String(data.get("visible_campaign_name", ""))
			last_handoff_save_path = String(data.get("installed_save_path", ""))
			last_handoff_battle_id = String(data.get("battle_id", ""))
			status_message = "Handoff ready. Load Conquest: %s" % last_handoff_name
			return
	if not bool(payload.get("ok", true)):
		var first: Dictionary = (payload.get("results", [{}]) as Array)[0] if not (payload.get("results", []) as Array).is_empty() else {}
		status_message = "Failed: %s" % String(first.get("detail", "unknown"))


func _fit_to_focus(force: bool) -> void:
	if snapshot.is_empty() or provinces_by_id.is_empty():
		return
	if fitted_once and not force:
		return
	var ids: Array = focus_province_ids.keys()
	if ids.is_empty():
		ids = provinces_by_id.keys()
	var min_x := 1e9
	var max_x := -1e9
	var min_y := 1e9
	var max_y := -1e9
	var count := 0
	for id in ids:
		var province: Dictionary = provinces_by_id.get(String(id), {})
		if province.is_empty():
			continue
		var px: float = float(province.get("x", 0.0))
		var py: float = float(province.get("y", 0.0))
		min_x = minf(min_x, px)
		max_x = maxf(max_x, px)
		min_y = minf(min_y, py)
		max_y = maxf(max_y, py)
		count += 1
	if count == 0:
		return
	if is_equal_approx(min_x, max_x):
		min_x -= 40.0
		max_x += 40.0
	if is_equal_approx(min_y, max_y):
		min_y -= 40.0
		max_y += 40.0
	var bounds: Dictionary = snapshot.get("bounds", {})
	var world_min_x: float = float(bounds.get("min_x", 0.0))
	var world_max_x: float = float(bounds.get("max_x", 1.0))
	var world_min_y: float = float(bounds.get("min_y", 0.0))
	var world_max_y: float = float(bounds.get("max_y", 1.0))
	var world_span := Vector2(maxf(world_max_x - world_min_x, 1.0), maxf(world_max_y - world_min_y, 1.0))
	var focus_span := Vector2(maxf(max_x - min_x, 1.0), maxf(max_y - min_y, 1.0))
	var pad := 1.35
	var scale_x: float = world_span.x / (focus_span.x * pad)
	var scale_y: float = world_span.y / (focus_span.y * pad)
	view_scale = clampf(minf(scale_x, scale_y), 1.0, 6.5)
	var focus_center := Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var world_center := Vector2((world_min_x + world_max_x) * 0.5, (world_min_y + world_max_y) * 0.5)
	var viewport_size := get_viewport_rect().size
	var map_size := Vector2(viewport_size.x - PANEL_WIDTH, viewport_size.y)
	var available := map_size - MAP_MARGIN * 2.0
	var normalized_focus := Vector2(
		(focus_center.x - world_min_x) / world_span.x,
		(focus_center.y - world_min_y) / world_span.y
	)
	var normalized_world := Vector2(0.5, 0.5)
	var base_focus := MAP_MARGIN + normalized_focus * available
	var base_world := MAP_MARGIN + normalized_world * available
	var center := map_size * 0.5
	# Place focus center at map center under current scale.
	var focus_screen_unscaled := base_focus
	view_offset = center - ((focus_screen_unscaled - center) * view_scale + center)
	# Nudge slightly if math drifts from world center reference.
	var _unused := base_world
	fitted_once = true
	status_message = "Fitted to front (%s nodes)." % count
	queue_redraw()


func _zoom_at(mouse_position: Vector2, factor: float) -> void:
	var old_scale := view_scale
	view_scale = clampf(view_scale * factor, 0.55, 10.0)
	if is_equal_approx(old_scale, view_scale):
		return
	var map_center := Vector2((get_viewport_rect().size.x - PANEL_WIDTH) * 0.5, get_viewport_rect().size.y * 0.5)
	var relative := mouse_position - map_center - view_offset
	view_offset -= relative * (view_scale / old_scale - 1.0)
	queue_redraw()
