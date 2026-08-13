extends "res://scripts/main_startup_measured.gd"

## P8/#218 interaction contract.
## Left click is selection-only. Right click is the only map gesture that can
## submit movement intent. Persisted Python move orders remain the sole route
## authority; this layer only presents their exact node/edge paths.

const QUEUED_ROUTE_COLOR := Color(0.25, 0.86, 1.0, 0.96)
const ACTIVE_ROUTE_COLOR := Color(1.0, 0.68, 0.18, 0.98)
const BLOCKED_ROUTE_COLOR := Color(1.0, 0.32, 0.28, 0.98)
const COMPLETE_ROUTE_COLOR := Color(0.45, 0.86, 0.55, 0.9)
const ROUTE_WIDTH := 3.2

var order_dispatch_count := 0


func _unhandled_input(event: InputEvent) -> void:
	# Pending-battle modal input owns the entire viewport. Do not let the map
	# split intercept clicks that happen to land left of the side-panel boundary.
	if has_method("is_pending_battle_modal_active") and is_pending_battle_modal_active():
		super._unhandled_input(event)
		return
	if event is InputEventMouseButton:
		var mouse_button := event as InputEventMouseButton
		var map_width := get_viewport_rect().size.x - PANEL_WIDTH
		if mouse_button.button_index == MOUSE_BUTTON_LEFT:
			if mouse_button.pressed:
				if mouse_button.position.x >= map_width:
					super._unhandled_input(event)
					return
				var province_id := _province_at(mouse_button.position)
				if province_id.is_empty():
					_clear_map_selection()
					dragging = true
					last_mouse_position = mouse_button.position
				else:
					_select_from_map(province_id)
					dragging = false
			else:
				dragging = false
			return
		if mouse_button.button_index == MOUSE_BUTTON_RIGHT and mouse_button.pressed:
			if mouse_button.position.x < map_width:
				_order_from_map(_province_at(mouse_button.position))
			return
	super._unhandled_input(event)


func _clear_map_selection() -> void:
	selected_province_id = ""
	selected_battalion_id = ""
	selected_strategic_formation_id = ""
	legal_targets.clear()
	focus_province_ids.clear()
	status_message = "Selection cleared."
	queue_redraw()


func _select_from_map(province_id: String) -> void:
	## Selection-only by contract. This function must never call _issue_move.
	if province_id.is_empty() or not provinces_by_id.has(province_id):
		_clear_map_selection()
		return
	selected_province_id = province_id
	_rebuild_legal_targets()
	_rebuild_focus_set()
	var formation := _selected_strategic_formation()
	if formation.is_empty():
		status_message = "Selected %s." % _province_name(province_id)
	else:
		status_message = "Selected %s: %s." % [
			_province_name(province_id),
			String(formation.get("display_name", selected_strategic_formation_id)),
		]
	queue_redraw()


func _order_from_map(target_province_id: String) -> void:
	if has_method("is_command_busy") and is_command_busy():
		status_message = "Order not submitted: backend is busy."
		queue_redraw()
		return
	if selected_strategic_formation_id.is_empty():
		status_message = "Order not submitted: select a friendly formation first."
		queue_redraw()
		return
	var formation := _selected_strategic_formation()
	if formation.is_empty():
		status_message = "Order not submitted: selected formation is unavailable."
		queue_redraw()
		return
	var campaign: Dictionary = snapshot.get("campaign", {})
	var current_faction := String(campaign.get("current_faction", campaign.get("selected_faction", "")))
	if String(formation.get("faction", "")) != current_faction:
		status_message = "Order not submitted: selected formation is not friendly."
		queue_redraw()
		return
	if target_province_id.is_empty():
		status_message = "Order not submitted: no operational destination under cursor."
		queue_redraw()
		return
	if not legal_targets.has(target_province_id):
		status_message = "Illegal destination: %s has no authoritative route for %s." % [
			_province_name(target_province_id),
			String(formation.get("display_name", selected_strategic_formation_id)),
		]
		queue_redraw()
		return
	order_dispatch_count += 1
	status_message = "Submitting order: %s -> %s..." % [
		String(formation.get("display_name", selected_strategic_formation_id)),
		_province_name(target_province_id),
	]
	queue_redraw()
	_issue_move(target_province_id)


func _strategic_formation_by_id(formation_id: String) -> Dictionary:
	if formation_id.is_empty():
		return {}
	for item: Variant in snapshot.get("strategic_formations", []):
		if not item is Dictionary:
			continue
		var row := item as Dictionary
		if String(row.get("id", "")) == formation_id:
			return row
	return {}


func _selected_strategic_formation() -> Dictionary:
	return _strategic_formation_by_id(selected_strategic_formation_id)


func _command_formation_id(commands: Array) -> String:
	if commands.is_empty() or not commands[0] is Dictionary:
		return ""
	var command := commands[0] as Dictionary
	var formation_id := String(command.get("formation", ""))
	if formation_id.is_empty():
		formation_id = String(command.get("formation_id", ""))
	if formation_id.is_empty():
		formation_id = String(command.get("strategic_formation_id", ""))
	return formation_id


func _apply_move_order_result_patch(op: String, commands: Array, payload: Dictionary) -> bool:
	var applied := super._apply_move_order_result_patch(op, commands, payload)
	if not applied:
		return false
	if op == "issue_move_order":
		# Selection may change while the backend works. Bind acceptance feedback to
		# the command that actually completed, not to whichever force is selected now.
		var formation_id := _command_formation_id(commands)
		var formation := _strategic_formation_by_id(formation_id)
		var fallback_id := formation_id if not formation_id.is_empty() else selected_strategic_formation_id
		status_message = "Order accepted and queued: %s." % String(
			formation.get("display_name", fallback_id)
		)
	elif op == "cancel_move_order":
		status_message = "Order cancelled."
	queue_redraw()
	return true


func _fail_command(op: String, detail: String) -> void:
	super._fail_command(op, detail)
	if op == "issue_move_order":
		status_message = "Order rejected: %s" % detail.substr(0, 220)
	elif op == "cancel_move_order":
		status_message = "Order cancel rejected: %s" % detail.substr(0, 220)
	queue_redraw()


func _draw() -> void:
	super._draw()
	_draw_selected_order_route()


func _authoritative_route_map_pixels(order: Dictionary) -> PackedVector2Array:
	## Resolve only the exact persisted node/edge IDs. A malformed or incomplete
	## path draws nothing instead of deriving a client-side substitute.
	var points := PackedVector2Array()
	if operational_graph == null or not operational_graph.is_ready:
		return points
	var path_nodes: Array = order.get("path_node_ids", [])
	var path_edges: Array = order.get("path_edge_ids", [])
	if path_nodes.size() < 2 or path_nodes.size() != path_edges.size() + 1:
		return points
	var graph_nodes: Dictionary = operational_graph.index.get("nodes", {})
	var graph_edges: Dictionary = operational_graph.index.get("edges", {})
	for idx in range(path_edges.size()):
		var left_id := String(path_nodes[idx])
		var right_id := String(path_nodes[idx + 1])
		var edge_id := String(path_edges[idx])
		if not graph_nodes.has(left_id) or not graph_nodes.has(right_id) or not graph_edges.has(edge_id):
			return PackedVector2Array()
		var edge: Dictionary = graph_edges[edge_id]
		var a := String(edge.get("a", ""))
		var b := String(edge.get("b", ""))
		if not ((a == left_id and b == right_id) or (a == right_id and b == left_id)):
			return PackedVector2Array()
	for node_variant: Variant in path_nodes:
		var node_id := String(node_variant)
		var node: Dictionary = graph_nodes.get(node_id, {})
		var pixel: Variant = node.get("pixel", null)
		if not (pixel is Array and (pixel as Array).size() >= 2):
			return PackedVector2Array()
		points.append(Vector2(float(pixel[0]), float(pixel[1])))
	return points


func _route_screen_points(order: Dictionary) -> PackedVector2Array:
	var map_points := _authoritative_route_map_pixels(order)
	var screen_points := PackedVector2Array()
	for point: Vector2 in map_points:
		screen_points.append(_image_to_screen(point))
	return screen_points


func _order_phase(order: Dictionary) -> String:
	var status := String(order.get("status", "")).to_lower()
	if status == "draft" or status == "committed":
		return "QUEUED"
	if status == "active":
		return "EXECUTING"
	if status == "blocked":
		return "INTERRUPTED BY CONTACT" if _selected_order_has_contact() else "BLOCKED"
	if status == "completed":
		return "COMPLETED"
	if status == "cancelled":
		return "CANCELLED"
	return status.to_upper()


func _selected_order_has_contact() -> bool:
	var pending: Variant = snapshot.get("pending_battle", null)
	if not pending is Dictionary:
		return false
	var battle := pending as Dictionary
	for key in ["attacker_formation_id", "defender_formation_id"]:
		if String(battle.get(key, "")) == selected_strategic_formation_id:
			return true
	for side in ["attacking_participants", "defending_participants"]:
		for participant: Variant in battle.get(side, []):
			if participant is Dictionary and String((participant as Dictionary).get("formation_id", "")) == selected_strategic_formation_id:
				return true
	return false


func _route_color(order: Dictionary) -> Color:
	match String(order.get("status", "")).to_lower():
		"active":
			return ACTIVE_ROUTE_COLOR
		"blocked":
			return BLOCKED_ROUTE_COLOR
		"completed":
			return COMPLETE_ROUTE_COLOR
		_:
			return QUEUED_ROUTE_COLOR


func _draw_selected_order_route() -> void:
	var formation := _selected_strategic_formation()
	if formation.is_empty():
		return
	var order_value: Variant = formation.get("move_order", null)
	if not order_value is Dictionary:
		return
	var order := order_value as Dictionary
	var phase := _order_phase(order)
	if phase in ["COMPLETED", "CANCELLED"]:
		_draw_terminal_order_badge(formation, phase, _route_color(order))
		return
	var points := _route_screen_points(order)
	if points.size() < 2:
		return
	var color := _route_color(order)
	for idx in range(points.size() - 1):
		var a := points[idx]
		var b := points[idx + 1]
		draw_line(a, b, Color(color.r, color.g, color.b, 0.28), ROUTE_WIDTH + 4.0, true)
		draw_line(a, b, color, ROUTE_WIDTH, true)
		_draw_route_chevron(a, b, color)
	var destination := points[points.size() - 1]
	draw_circle(destination, 10.0, Color(color.r, color.g, color.b, 0.2))
	draw_arc(destination, 10.0, 0.0, TAU, 28, color, 2.5, true)
	var owner_label := "%s  %s" % [
		String(formation.get("display_name", selected_strategic_formation_id)),
		phase,
	]
	draw_string(
		ThemeDB.fallback_font,
		points[0] + Vector2(12, -13),
		owner_label,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		12,
		color
	)


func _draw_route_chevron(a: Vector2, b: Vector2, color: Color) -> void:
	var delta := b - a
	if delta.length() < 12.0:
		return
	var direction := delta.normalized()
	var normal := Vector2(-direction.y, direction.x)
	var center := a.lerp(b, 0.58)
	var tip := center + direction * 7.0
	var back := center - direction * 5.0
	var triangle := PackedVector2Array([
		tip,
		back + normal * 4.5,
		back - normal * 4.5,
	])
	draw_colored_polygon(triangle, color)


func _draw_terminal_order_badge(formation: Dictionary, phase: String, color: Color) -> void:
	var province_id := String(formation.get("province_id", ""))
	var province: Dictionary = provinces_by_id.get(province_id, {})
	if province.is_empty():
		return
	var position := _map_to_screen(province) + Vector2(16, 22)
	draw_string(
		ThemeDB.fallback_font,
		position,
		"%s  %s" % [String(formation.get("display_name", selected_strategic_formation_id)), phase],
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		11,
		color
	)
