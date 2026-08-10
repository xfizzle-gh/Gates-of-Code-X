extends "res://scripts/main.gd"

# Correctness layer for the write-back checkpoint. The full stack UI remains in #52.
const FrontendCommandRunnerScript = preload("res://scripts/presentation/command_runner.gd")
const OperationalResolutionPresenterScript = preload("res://scripts/presentation/operational_resolution_presenter.gd")

var battalion_stacks_by_province: Dictionary = {}
var battalions_by_id: Dictionary = {}
var all_front_by_origin: Dictionary = {}
var selected_battalion_id := ""
var command_runner: Node
var operational_presenter
var _busy_status := ""
var _last_command_gen_handled := 0
## Test/observability: increments only on successful live snapshot commit after a command.
var snapshot_commit_count := 0
## Player-shell state. New Campaign replaces authoritative state, so it always
## requires a second confirming press.
var new_campaign_confirm_pending := false
## P5: Import Result stays unavailable until Verify Result accepts this save.
var last_verified_save_path := ""
var last_verification_ok := false
var last_verification_detail := ""
var _command_sequence := 0
var _session_token := ""


func _ready() -> void:
	_ensure_command_runner()
	_ensure_operational_presenter()
	super._ready()


func _ensure_command_runner() -> void:
	if command_runner != null and is_instance_valid(command_runner):
		return
	command_runner = FrontendCommandRunnerScript.new()
	command_runner.name = "FrontendCommandRunner"
	add_child(command_runner)
	if not command_runner.command_finished.is_connected(_on_command_finished):
		command_runner.command_finished.connect(_on_command_finished)


func _ensure_operational_presenter() -> void:
	if operational_presenter != null:
		return
	operational_presenter = OperationalResolutionPresenterScript.new()
	if not InputMap.has_action("skip_operational_presentation"):
		InputMap.add_action("skip_operational_presentation")
		var event := InputEventKey.new()
		event.physical_keycode = KEY_SPACE
		InputMap.action_add_event("skip_operational_presentation", event)


func inject_command_runner(runner: Node) -> void:
	## Test hook: replace the default runner with a deterministic fake.
	if command_runner != null and is_instance_valid(command_runner):
		if command_runner.command_finished.is_connected(_on_command_finished):
			command_runner.command_finished.disconnect(_on_command_finished)
		command_runner.queue_free()
	command_runner = runner
	if runner.get_parent() != self:
		add_child(runner)
	if not command_runner.command_finished.is_connected(_on_command_finished):
		command_runner.command_finished.connect(_on_command_finished)


func is_command_busy() -> bool:
	return command_runner != null and command_runner.is_busy()


func command_busy_label() -> String:
	if not is_command_busy():
		return ""
	var op := String(command_runner.current_op())
	if op.is_empty():
		op = "command"
	return "Backend busy: %s..." % op


func _load_snapshot(path: String) -> void:
	## Initial / explicit load. Clears then rebuilds. Command completion uses
	## transactional _try_build_snapshot_state + _commit_snapshot_state instead.
	var built: Dictionary = _try_build_snapshot_state(path)
	if not bool(built.get("ok", false)):
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
		snapshot = {}
		load_error = String(built.get("error", "snapshot load failed"))
		return
	_commit_snapshot_state(built, "", "", false)
	_ensure_operational_presenter()
	operational_presenter.begin_session(snapshot, _operational_graph_index())


func _try_build_snapshot_state(path: String) -> Dictionary:
	## Parse + validate into temporary dictionaries. Never mutates live state.
	if path.is_empty() or not FileAccess.file_exists(path):
		return {"ok": false, "error": "Campaign snapshot not found: %s" % path}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {"ok": false, "error": "Unable to open campaign snapshot: %s" % path}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return {"ok": false, "error": "Campaign snapshot is not valid JSON."}
	var candidate: Dictionary = (parsed as Dictionary).duplicate(true)
	if String(candidate.get("schema", "")) != "gates-of-codex.frontend":
		return {"ok": false, "error": "Unsupported campaign snapshot schema."}

	var tmp_provinces: Dictionary = {}
	var tmp_battalions_by_province: Dictionary = {}
	var tmp_stacks: Dictionary = {}
	var tmp_battalions_by_id: Dictionary = {}
	var tmp_formations: Dictionary = {}
	var tmp_factions: Dictionary = {}
	var tmp_front: Dictionary = {}
	var tmp_all_front: Dictionary = {}

	for province: Dictionary in candidate.get("provinces", []):
		tmp_provinces[String(province.get("id", ""))] = province
	for battalion: Dictionary in candidate.get("battalions", []):
		var battalion_id := String(battalion.get("id", ""))
		var province_id := String(battalion.get("province_id", ""))
		tmp_battalions_by_id[battalion_id] = battalion
		if not tmp_stacks.has(province_id):
			tmp_stacks[province_id] = []
		(tmp_stacks[province_id] as Array).append(battalion)
	for province_id in tmp_stacks.keys():
		var stack: Array = tmp_stacks[province_id]
		stack.sort_custom(Callable(self, "_battalion_id_less_than"))
		if not stack.is_empty():
			tmp_battalions_by_province[province_id] = stack[0]
	for formation: Dictionary in candidate.get("formations", []):
		tmp_formations[String(formation.get("id", ""))] = formation
	for faction: Dictionary in candidate.get("factions", []):
		tmp_factions[String(faction.get("id", ""))] = faction
	for option: Dictionary in candidate.get("front_options", []):
		var origin := String(option.get("origin", ""))
		if not tmp_all_front.has(origin):
			tmp_all_front[origin] = []
		(tmp_all_front[origin] as Array).append(option)
	for origin in tmp_all_front.keys():
		tmp_front[origin] = (tmp_all_front[origin] as Array).duplicate()

	var stack_err := _validate_battalion_stack_contract_on(
		candidate, tmp_stacks
	)
	if not stack_err.is_empty():
		return {"ok": false, "error": stack_err}

	return {
		"ok": true,
		"error": "",
		"path": path,
		"snapshot": candidate,
		"provinces_by_id": tmp_provinces,
		"battalions_by_province": tmp_battalions_by_province,
		"battalion_stacks_by_province": tmp_stacks,
		"battalions_by_id": tmp_battalions_by_id,
		"formations_by_id": tmp_formations,
		"factions_by_id": tmp_factions,
		"front_by_origin": tmp_front,
		"all_front_by_origin": tmp_all_front,
	}


func _commit_snapshot_state(
	built: Dictionary,
	previous_selected: String,
	previous_battalion: String,
	count_as_command_commit: bool
) -> void:
	## Atomically replace live presentation state from a validated candidate.
	snapshot = built.get("snapshot", {})
	provinces_by_id = built.get("provinces_by_id", {})
	battalions_by_province = built.get("battalions_by_province", {})
	battalion_stacks_by_province = built.get("battalion_stacks_by_province", {})
	battalions_by_id = built.get("battalions_by_id", {})
	formations_by_id = built.get("formations_by_id", {})
	factions_by_id = built.get("factions_by_id", {})
	front_by_origin = built.get("front_by_origin", {})
	all_front_by_origin = built.get("all_front_by_origin", {})
	legal_targets.clear()
	focus_province_ids.clear()
	button_rects.clear()
	load_error = ""
	if not String(built.get("path", "")).is_empty():
		snapshot_source_path = String(built.get("path", ""))

	if not previous_selected.is_empty() and provinces_by_id.has(previous_selected):
		selected_province_id = previous_selected
		selected_battalion_id = previous_battalion
	else:
		_select_default_province()
	_rebuild_legal_targets()
	_rebuild_focus_set()
	if count_as_command_commit:
		snapshot_commit_count += 1


func _battalion_id_less_than(left: Dictionary, right: Dictionary) -> bool:
	return String(left.get("id", "")) < String(right.get("id", ""))


func _validate_battalion_stack_contract_on(snap: Dictionary, stacks: Dictionary) -> String:
	var declared: Variant = snap.get("battalion_stacks", {})
	if not declared is Dictionary:
		return ""
	for province_id_variant in (declared as Dictionary).keys():
		var province_id := String(province_id_variant)
		var expected: Array = (declared as Dictionary).get(province_id_variant, [])
		var actual_ids: Array = []
		for battalion: Dictionary in stacks.get(province_id, []):
			actual_ids.append(String(battalion.get("id", "")))
		if expected != actual_ids:
			return "Battalion stack contract mismatch for %s." % province_id
	return ""


func _validate_battalion_stack_contract() -> bool:
	var err := _validate_battalion_stack_contract_on(snapshot, battalion_stacks_by_province)
	if not err.is_empty():
		load_error = err
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


func _command_mutates_state(button_id: String) -> bool:
	if button_id in ["fit", "replay_contact", "skip_presentation"]:
		return false
	if button_id == "verify_result":
		# Read-only verification: never mutates campaign or snapshot.
		return false
	if button_id.begins_with("move:") or button_id.begins_with("construct:"):
		return true
	return button_id in [
		"refresh",
		"end_turn",
		"run_ai",
		"auto_resolve",
		"handoff",
		"import_battle",
		"new_campaign",
		"continue_campaign",
	]


func next_command_id(op: String) -> String:
	## Stable per-session identity used by the backend exactly-once ledger.
	if _session_token.is_empty():
		_session_token = "%d-%d" % [
			int(Time.get_unix_time_from_system()),
			int(Time.get_ticks_usec()),
		]
	_command_sequence += 1
	return "%s:%s:%d" % [_session_token, op, _command_sequence]


func _stamp_command_ids(commands: Array) -> Array:
	## Every mutation carries an identity so a replay cannot apply twice.
	var stamped: Array = []
	for item in commands:
		if not item is Dictionary:
			continue
		var entry: Dictionary = (item as Dictionary).duplicate(true)
		var existing := String(entry.get("command_id", "")).strip_edges()
		if existing.is_empty():
			entry["command_id"] = next_command_id(String(entry.get("op", "command")))
		stamped.append(entry)
	return stamped


func can_import_verified_result() -> bool:
	## P5: import is unavailable until Verify Result accepted this exact save.
	return last_verification_ok \
		and not last_handoff_save_path.is_empty() \
		and last_verified_save_path == last_handoff_save_path


func handoff_status_label() -> String:
	if last_handoff_save_path.is_empty():
		return ""
	if can_import_verified_result():
		return "Result verified - ready to import."
	if not last_verification_detail.is_empty():
		return "Verification failed: %s" % last_verification_detail
	return "Awaiting Verify Result."


func _capture_verification(payload: Dictionary) -> void:
	var results: Array = payload.get("results", [])
	for item in results:
		if not item is Dictionary:
			continue
		var row: Dictionary = item as Dictionary
		if String(row.get("op", "")) != "verify_result":
			continue
		var data: Dictionary = row.get("data", {})
		last_verified_save_path = String(data.get("save_path", ""))
		last_verification_ok = bool(data.get("verified", false))
		var errors: Array = data.get("errors", [])
		last_verification_detail = "" if last_verification_ok else ", ".join(errors.slice(0, 3))


func player_launch_block() -> Dictionary:
	var control: Dictionary = snapshot.get("control", {})
	var play: Variant = control.get("play", {})
	if play is Dictionary:
		return (play as Dictionary).duplicate(true)
	return {}


func can_start_new_campaign() -> bool:
	var play := player_launch_block()
	return bool(play.get("enabled", false)) \
		and not (play.get("new_args", []) as Array).is_empty() \
		and not is_command_busy()


func can_continue_campaign() -> bool:
	var play := player_launch_block()
	return bool(play.get("enabled", false)) \
		and not (play.get("continue_args", []) as Array).is_empty() \
		and not is_command_busy()


func _run_player_launch(op: String, args_key: String) -> void:
	_ensure_command_runner()
	var play := player_launch_block()
	if not bool(play.get("enabled", false)):
		status_message = "Player launch unavailable — re-export the frontend with a campaign path."
		queue_redraw()
		return
	var raw_args: Array = play.get(args_key, [])
	if raw_args.is_empty():
		status_message = "Player launch arguments missing for %s." % op
		queue_redraw()
		return
	if is_command_busy():
		status_message = "Busy — wait for %s to finish." % command_runner.current_op()
		queue_redraw()
		return
	var launch_args: Array = []
	for value in raw_args:
		launch_args.append(String(value))
	var control: Dictionary = snapshot.get("control", {})
	var snapshot_path := String(control.get("snapshot_path", ""))
	var candidates := _backend_launch_candidates(control, launch_args)
	# The launcher rewrites the authoritative campaign and republishes the
	# snapshot; the runner reports the same way an apply-frontend batch does.
	var marker: Array = [{"op": op, "command_id": next_command_id(op)}]
	var start: Dictionary = command_runner.try_start_candidates(
		marker,
		candidates,
		snapshot_path if not snapshot_path.is_empty() else snapshot_source_path
	)
	if not bool(start.get("ok", false)):
		status_message = "Unable to start player launch: %s" % String(start.get("reason", "rejected"))
		queue_redraw()
		return
	_busy_status = "Running %s..." % op
	status_message = _busy_status
	set_process(true)
	queue_redraw()


func _handle_button(button_id: String) -> void:
	_ensure_operational_presenter()
	if button_id != "new_campaign":
		new_campaign_confirm_pending = false
	if button_id == "new_campaign":
		if not can_start_new_campaign():
			status_message = "New Campaign unavailable right now."
			queue_redraw()
			return
		if not new_campaign_confirm_pending:
			new_campaign_confirm_pending = true
			status_message = "New Campaign replaces the current campaign — press again to confirm."
			queue_redraw()
			return
		new_campaign_confirm_pending = false
		_run_player_launch("new_campaign", "new_args")
		return
	if button_id == "continue_campaign":
		if not can_continue_campaign():
			status_message = "Continue Campaign unavailable right now."
			queue_redraw()
			return
		_run_player_launch("continue_campaign", "continue_args")
		return
	if button_id == "replay_contact":
		if operational_presenter.replay_last_contact():
			status_message = "Replaying last contact - presentation only."
		else:
			status_message = "No contact is available to replay in this session."
		queue_redraw()
		return
	if button_id == "skip_presentation":
		operational_presenter.skip()
		status_message = "Operational presentation skipped to authoritative endpoints."
		queue_redraw()
		return
	if button_id == "verify_result":
		if last_handoff_save_path.is_empty():
			status_message = "Nothing to verify - hand a battle off to Gates of Hell first."
			queue_redraw()
			return
		_queue_and_apply([{
			"op": "verify_result",
			"save_path": last_handoff_save_path,
		}])
		return
	if button_id == "import_battle":
		if not can_import_verified_result():
			status_message = "Verify Result must accept this save before it can be imported."
			queue_redraw()
			return
		_queue_and_apply([{
			"op": "import_battle",
			"save_path": last_handoff_save_path,
		}])
		return
	if is_pending_battle_modal_active() and button_id not in ["auto_resolve", "handoff", "import_battle"]:
		status_message = "Operational resolution paused - resolve or hand off the pending battle."
		queue_redraw()
		return
	if operational_presenter.is_active() and _command_mutates_state(button_id):
		status_message = "Operational presentation active - Skip or wait for completion."
		queue_redraw()
		return
	if is_command_busy() and _command_mutates_state(button_id):
		status_message = "Busy - wait for %s to finish." % command_runner.current_op()
		queue_redraw()
		return
	super._handle_button(button_id)


func _issue_move(target_province_id: String) -> void:
	if is_map_interaction_blocked():
		status_message = "Operational resolution paused - map orders are blocked."
		queue_redraw()
		return
	if is_command_busy():
		status_message = "Busy - move ignored until %s finishes." % command_runner.current_op()
		queue_redraw()
		return
	super._issue_move(target_province_id)


func _draw_button(id: String, label: String, x: float, y: float, enabled: bool, fill := Color("1a2a38")) -> float:
	var allow := enabled
	if is_pending_battle_modal_active() and id not in ["auto_resolve", "handoff", "import_battle", "replay_contact", "skip_presentation", "new_campaign", "continue_campaign"]:
		allow = false
	if operational_presenter != null and operational_presenter.is_active() and _command_mutates_state(id):
		allow = false
	if is_command_busy() and _command_mutates_state(id):
		allow = false
	return super._draw_button(id, label, x, y, allow, fill)


func enabled_action_button_ids() -> PackedStringArray:
	## Hit-test mirror of management-panel action buttons (no CanvasItem draw required).
	var ids := PackedStringArray()
	var writeback := bool(snapshot.get("control", {}).get("enabled", false))
	var has_battle := snapshot.get("pending_battle") != null
	var pending: Dictionary = snapshot.get("pending_battle", {}) if has_battle else {}
	var can_import := writeback \
		and bool(pending.get("started", false)) \
		and String(pending.get("id", "")) == last_handoff_battle_id \
		and not last_handoff_save_path.is_empty()
	_ensure_operational_presenter()
	var play := player_launch_block()
	var play_enabled := bool(play.get("enabled", false))
	var candidates: Array = [
		["new_campaign", play_enabled and not (play.get("new_args", []) as Array).is_empty()],
		["continue_campaign", play_enabled and not (play.get("continue_args", []) as Array).is_empty()],
	]
	if has_battle:
		candidates.append_array([
			["auto_resolve", writeback],
			["handoff", writeback],
			["verify_result", writeback and not last_handoff_save_path.is_empty()],
			["import_battle", can_import and can_import_verified_result()],
			["replay_contact", operational_presenter.can_replay_last_contact()],
			["skip_presentation", operational_presenter.is_active()],
		])
	else:
		candidates.append_array([
			["fit", true],
			["refresh", writeback],
			["end_turn", writeback],
			["run_ai", writeback],
			["skip_presentation", operational_presenter.is_active()],
		])
	for entry in candidates:
		var button_id := String(entry[0])
		var allow := bool(entry[1])
		if is_command_busy() and _command_mutates_state(button_id):
			allow = false
		if allow:
			ids.append(button_id)
	return ids


func is_pending_battle_modal_active() -> bool:
	return snapshot.get("pending_battle", null) is Dictionary


func is_map_interaction_blocked() -> bool:
	return is_pending_battle_modal_active()


func _operational_graph_index() -> Dictionary:
	var graph: Variant = get("operational_graph")
	if graph == null:
		return {}
	var index_value: Variant = graph.get("index")
	if index_value is Dictionary:
		return (index_value as Dictionary).duplicate(true)
	return {}


func _backend_launch_candidates(control: Dictionary, apply_args: Array) -> Array:
	## Authority order:
	## a) control.python_executable + control.python_module
	## b) installed gates-of-codex
	## c) python -m gates_of_codex
	var candidates: Array = []
	var python_executable := String(control.get("python_executable", "")).strip_edges()
	var python_module := String(control.get("python_module", "gates_of_codex")).strip_edges()
	if python_module.is_empty():
		python_module = "gates_of_codex"
	if not python_executable.is_empty() and FileAccess.file_exists(python_executable):
		var a_args: Array = ["-m", python_module]
		a_args.append_array(apply_args)
		candidates.append({"executable": python_executable, "args": a_args})
	candidates.append({"executable": "gates-of-codex", "args": apply_args.duplicate()})
	var c_args: Array = ["-m", "gates_of_codex"]
	c_args.append_array(apply_args)
	candidates.append({"executable": "python", "args": c_args})
	return candidates


func _queue_and_apply(commands: Array) -> void:
	_ensure_command_runner()
	_ensure_operational_presenter()
	var requested_op := FrontendCommandRunnerScript.primary_op(commands)
	if is_pending_battle_modal_active() and requested_op not in ["auto_resolve", "handoff", "import_battle"]:
		status_message = "Operational resolution paused - pending battle is modal."
		queue_redraw()
		return
	if operational_presenter.is_active() and requested_op not in ["handoff", "import_battle"]:
		status_message = "Operational presentation active - Skip or wait for completion."
		queue_redraw()
		return
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

	var identity := FrontendCommandRunnerScript.command_identity(commands)
	if is_command_busy():
		if identity == command_runner.current_identity():
			status_message = "Duplicate %s ignored - already in flight." % command_runner.current_op()
		else:
			status_message = "Busy with %s - new command rejected." % command_runner.current_op()
		queue_redraw()
		return

	# Identity is stamped only on the queued payload. In-flight duplicate
	# suppression above still compares the raw command shape, while the backend
	# ledger uses these ids to guarantee a replayed queue applies exactly once.
	var payload := {"commands": _stamp_command_ids(commands)}
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
	var candidates := _backend_launch_candidates(control, apply_args)
	var start: Dictionary = command_runner.try_start_candidates(
		commands,
		candidates,
		snapshot_path if not snapshot_path.is_empty() else snapshot_source_path
	)
	if not bool(start.get("ok", false)):
		var reason := String(start.get("reason", "rejected"))
		if reason == "duplicate_in_flight":
			status_message = "Duplicate %s ignored - already in flight." % FrontendCommandRunnerScript.primary_op(commands)
		elif reason == "busy":
			status_message = "Busy - command rejected."
		else:
			status_message = "Unable to start backend: %s" % reason
		queue_redraw()
		return

	_busy_status = "Running %s..." % FrontendCommandRunnerScript.primary_op(commands)
	status_message = _busy_status
	set_process(true)
	queue_redraw()


func _process(_delta: float) -> void:
	if is_command_busy():
		queue_redraw()
		return
	if not _busy_status.is_empty():
		_busy_status = ""


func _payload_failure_detail(output_text: String) -> String:
	## Returns non-empty detail when backend payload reports ok:false.
	var text := output_text.strip_edges()
	if text.is_empty():
		return ""
	var parsed: Variant = JSON.parse_string(text)
	if not parsed is Dictionary:
		return ""
	var payload := parsed as Dictionary
	if bool(payload.get("ok", true)):
		return ""
	var results: Array = payload.get("results", [])
	var first: Dictionary = results[0] if not results.is_empty() and results[0] is Dictionary else {}
	var detail := String(first.get("detail", ""))
	if detail.is_empty():
		detail = "backend reported ok:false"
	return detail


func _backend_payload(output_text: String) -> Dictionary:
	var text := output_text.strip_edges()
	if text.is_empty():
		return {}
	var parsed: Variant = JSON.parse_string(text)
	if parsed is Dictionary:
		return (parsed as Dictionary).duplicate(true)
	return {}


func _clear_busy_ui() -> void:
	_busy_status = ""
	queue_redraw()


func _fail_command(op: String, detail: String) -> void:
	## Preserve complete prior snapshot + selection + view; clear busy; restore controls.
	status_message = "Apply failed (%s): %s" % [op, detail.substr(0, 240)]
	_clear_busy_ui()


func _on_command_finished(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
) -> void:
	if not is_inside_tree():
		return
	if generation <= _last_command_gen_handled:
		return
	_last_command_gen_handled = generation
	_busy_status = ""

	var op := FrontendCommandRunnerScript.primary_op(commands)

	# 1) Nonzero exit (or could-not-launch after all fallbacks).
	if not success or exit_code != 0:
		var detail := output_text.strip_edges()
		if detail.is_empty():
			detail = "backend exit %s" % exit_code
		_fail_command(op, detail)
		return

	# 2) Payload ok:false even with exit 0.
	var payload_fail := _payload_failure_detail(output_text)
	if not payload_fail.is_empty():
		_fail_command(op, payload_fail)
		return

	# 3) Transactional snapshot replacement — never clear live state first.
	var previous_selected := selected_province_id
	var previous_battalion := selected_battalion_id
	var previous_scale := view_scale
	var previous_offset := view_offset
	var previous_snapshot := snapshot.duplicate(true)
	var backend_payload := _backend_payload(output_text)
	var load_path := snapshot_path if not snapshot_path.is_empty() else snapshot_source_path
	var built: Dictionary = _try_build_snapshot_state(load_path)
	if not bool(built.get("ok", false)):
		_fail_command(op, String(built.get("error", "invalid replacement snapshot")))
		# Explicitly keep view state.
		view_scale = previous_scale
		view_offset = previous_offset
		return

	# Apply output side-effects only after candidate is valid.
	_parse_apply_output(output_text)
	_capture_verification(backend_payload)
	_commit_snapshot_state(built, previous_selected, previous_battalion, true)
	_ensure_operational_presenter()
	operational_presenter.begin_transition(
		previous_snapshot,
		snapshot,
		backend_payload,
		_operational_graph_index()
	)
	view_scale = previous_scale
	view_offset = previous_offset
	if status_message.is_empty():
		status_message = "Applied %s." % op
	if snapshot.get("pending_battle") != null and op != "handoff":
		status_message += " Pending battle ready - Auto-resolve or Handoff."
	_fit_to_focus(false)
	queue_redraw()
