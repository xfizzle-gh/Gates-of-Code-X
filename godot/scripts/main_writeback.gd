extends "res://scripts/main.gd"

# Correctness layer for the write-back checkpoint. The full stack UI remains in #52.
var battalion_stacks_by_province: Dictionary = {}
var battalions_by_id: Dictionary = {}
var all_front_by_origin: Dictionary = {}
var selected_battalion_id := ""


func _load_snapshot(path: String) -> void:
	provinces_by_id.clear()
	battalions_by_province.clear()
	battalion_stacks_by_province.clear()
	battalions_by_id.clear()
	formations_by_id.clear()
	factions_by_id.clear()
	front_by_origin.clear()
	all_front_by_origin.clear()
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
		var battalion_id := String(battalion.get("id", ""))
		var province_id := String(battalion.get("province_id", ""))
		battalions_by_id[battalion_id] = battalion
		if not battalion_stacks_by_province.has(province_id):
			battalion_stacks_by_province[province_id] = []
		(battalion_stacks_by_province[province_id] as Array).append(battalion)
	for province_id in battalion_stacks_by_province.keys():
		var stack: Array = battalion_stacks_by_province[province_id]
		stack.sort_custom(Callable(self, "_battalion_id_less_than"))
		if not stack.is_empty():
			# Compatibility representative used by the existing compact panel.
			battalions_by_province[province_id] = stack[0]
	for formation: Dictionary in snapshot.get("formations", []):
		formations_by_id[String(formation.get("id", ""))] = formation
	for faction: Dictionary in snapshot.get("factions", []):
		factions_by_id[String(faction.get("id", ""))] = faction
	for option: Dictionary in snapshot.get("front_options", []):
		var origin := String(option.get("origin", ""))
		if not all_front_by_origin.has(origin):
			all_front_by_origin[origin] = []
		(all_front_by_origin[origin] as Array).append(option)
	for origin in all_front_by_origin.keys():
		front_by_origin[origin] = (all_front_by_origin[origin] as Array).duplicate()

	if not _validate_battalion_stack_contract():
		return
	_select_default_province()
	_rebuild_legal_targets()
	_rebuild_focus_set()


func _battalion_id_less_than(left: Dictionary, right: Dictionary) -> bool:
	return String(left.get("id", "")) < String(right.get("id", ""))


func _validate_battalion_stack_contract() -> bool:
	var declared: Variant = snapshot.get("battalion_stacks", {})
	if not declared is Dictionary:
		return true
	for province_id_variant in (declared as Dictionary).keys():
		var province_id := String(province_id_variant)
		var expected: Array = (declared as Dictionary).get(province_id_variant, [])
		var actual_ids: Array = []
		for battalion: Dictionary in battalion_stacks_by_province.get(province_id, []):
			actual_ids.append(String(battalion.get("id", "")))
		if expected != actual_ids:
			load_error = "Battalion stack contract mismatch for %s." % province_id
			return false
	return true


func _rebuild_legal_targets() -> void:
	legal_targets.clear()
	for origin in all_front_by_origin.keys():
		front_by_origin[origin] = (all_front_by_origin[origin] as Array).duplicate()

	var stack: Array = battalion_stacks_by_province.get(selected_province_id, [])
	if stack.is_empty():
		selected_battalion_id = ""
		return
	var options: Array = all_front_by_origin.get(selected_province_id, [])
	if not _battalion_has_option(selected_battalion_id, options):
		selected_battalion_id = ""
		for battalion: Dictionary in stack:
			var candidate_id := String(battalion.get("id", ""))
			if _battalion_has_option(candidate_id, options):
				selected_battalion_id = candidate_id
				break
	if selected_battalion_id.is_empty():
		selected_battalion_id = String((stack[0] as Dictionary).get("id", ""))

	var representative: Dictionary = battalions_by_id.get(selected_battalion_id, {})
	if not representative.is_empty():
		battalions_by_province[selected_province_id] = representative

	var selected_options: Array = []
	for option: Dictionary in options:
		if String(option.get("battalion_id", "")) != selected_battalion_id:
			continue
		selected_options.append(option)
		legal_targets[String(option.get("target", ""))] = option
	front_by_origin[selected_province_id] = selected_options


func _battalion_has_option(battalion_id: String, options: Array) -> bool:
	if battalion_id.is_empty():
		return false
	for option: Dictionary in options:
		if String(option.get("battalion_id", "")) == battalion_id:
			return true
	return false


func _draw_province(province: Dictionary) -> void:
	super._draw_province(province)
	var province_id := String(province.get("id", ""))
	var stack: Array = battalion_stacks_by_province.get(province_id, [])
	if stack.size() <= 1:
		return
	var badge_position := _map_to_screen(province) + Vector2(19, -14)
	draw_circle(badge_position, 8.5, Color(0.04, 0.055, 0.07, 0.98))
	draw_circle(badge_position, 8.5, Color.WHITE, false, 1.0)
	draw_string(
		ThemeDB.fallback_font,
		badge_position + Vector2(-3.5, 4.0),
		str(stack.size()),
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		11,
		Color.WHITE
	)


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

	var apply_args := [
		"apply-frontend",
		campaign_path,
		"--snapshot",
		snapshot_path,
		"--commands",
		commands_path,
	]
	var output: Array = []
	var python_executable := String(control.get("python_executable", "")).strip_edges()
	var python_module := String(control.get("python_module", "gates_of_codex")).strip_edges()
	var exit_code := -1
	if not python_executable.is_empty():
		if not FileAccess.file_exists(python_executable):
			status_message = "Configured backend executable no longer exists: %s" % python_executable
			queue_redraw()
			return
		var python_args := ["-m", python_module]
		python_args.append_array(apply_args)
		exit_code = OS.execute(python_executable, python_args, output, true, false)
	else:
		# Backward-compatible fallback for older snapshots only.
		exit_code = OS.execute("gates-of-codex", apply_args, output, true, false)
		if exit_code == -1:
			output.clear()
			var fallback_args := ["-m", "gates_of_codex"]
			fallback_args.append_array(apply_args)
			exit_code = OS.execute("python", fallback_args, output, true, false)

	var joined := "\n".join(output)
	if exit_code != 0:
		if joined.strip_edges().is_empty():
			joined = "backend process could not be launched"
		status_message = "Apply failed: %s" % joined.substr(0, 200)
		queue_redraw()
		return
	_parse_apply_output(joined)
	var previous_selected := selected_province_id
	var previous_battalion := selected_battalion_id
	_load_snapshot(snapshot_path if not snapshot_path.is_empty() else snapshot_source_path)
	if provinces_by_id.has(previous_selected):
		selected_province_id = previous_selected
		selected_battalion_id = previous_battalion
		_rebuild_legal_targets()
		_rebuild_focus_set()
	var op := String((commands[0] as Dictionary).get("op", "command"))
	if status_message.is_empty():
		status_message = "Applied %s." % op
	if snapshot.get("pending_battle") != null and op != "handoff":
		status_message += " Pending battle ready — Auto-resolve or Handoff."
	_fit_to_focus(false)
	queue_redraw()
