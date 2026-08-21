extends "res://scripts/main_perf.gd"

## P8/#207 native timing layer.
##
## Most mutating commands continue through the existing transactional
## full-snapshot replacement path. Three narrow fast paths avoid known redundant
## presentation work:
##
## * verify_result is read-only and consumes the backend verdict directly.
## * query_supply is read-only and caches bounded supply/readiness for the panel.
## * issue/cancel move-order commands still persist authoritatively in Python,
##   but update only the returned move_order field in the live Godot snapshot.
## * end_player_round still persists authoritatively in Python, but consumes a
##   bounded runtime patch instead of reparsing/replacing the static Earth3 map
##   payload. The patch is validated into a detached candidate before commit.

const LIGHTWEIGHT_ORDER_OPS := ["issue_move_order", "cancel_move_order"]
const RUNTIME_PATCH_OPS := ["end_player_round", "auto_resolve"]
const RUNTIME_PATCH_SCHEMA := "gates-of-codex.frontend-runtime-patch"
const RUNTIME_PATCH_SCHEMA_VERSION := 1


func _timing_suffix(payload: Dictionary) -> String:
	var timings: Variant = payload.get("timings", {})
	if not timings is Dictionary:
		return ""
	var row := timings as Dictionary
	if not row.has("total_ms"):
		return ""
	return "[backend %.2fs: load %.2f, mutate %.2f, save %.2f, snapshot %.2f]" % [
		float(row.get("total_ms", 0.0)) / 1000.0,
		float(row.get("load_ms", 0.0)) / 1000.0,
		float(row.get("mutate_ms", 0.0)) / 1000.0,
		float(row.get("save_ms", 0.0)) / 1000.0,
		float(row.get("snapshot_ms", 0.0)) / 1000.0,
	]


func _save_timing_suffix(payload: Dictionary) -> String:
	var timings: Variant = payload.get("timings", {})
	if not timings is Dictionary:
		return ""
	var row := timings as Dictionary
	if not row.has("save_validate_ms"):
		return ""
	return "[save: strat %.2f pos %.2f ord %.2f site %.2f supply %.2f s11 %.2f obs %.2f val %.2f enc %.2f write %.2f]" % [
		float(row.get("save_strategic_ms", 0.0)) / 1000.0,
		float(row.get("save_positions_ms", 0.0)) / 1000.0,
		float(row.get("save_orders_ms", 0.0)) / 1000.0,
		float(row.get("save_site_control_ms", 0.0)) / 1000.0,
		float(row.get("save_supply_ms", 0.0)) / 1000.0,
		float(row.get("save_s11_schema_ms", 0.0)) / 1000.0,
		float(row.get("save_observer_refresh_ms", 0.0)) / 1000.0,
		float(row.get("save_validate_ms", 0.0)) / 1000.0,
		float(row.get("save_encode_ms", 0.0)) / 1000.0,
		float(row.get("save_write_ms", 0.0)) / 1000.0,
	]


func _round_timing_suffix(payload: Dictionary) -> String:
	var data := _result_data(payload, "end_player_round")
	var perf: Variant = data.get("perf_turn_cycle", {})
	if not perf is Dictionary:
		return ""
	var row := perf as Dictionary
	if not row.has("ai_take_turn_total_ms"):
		return ""
	return "[round: engine %.2fs, AI %.2fs, advance %.2fs, actors %.2fs]" % [
		float(row.get("engine_init_ms", 0.0)) / 1000.0,
		float(row.get("ai_take_turn_total_ms", 0.0)) / 1000.0,
		float(row.get("advance_turn_total_ms", 0.0)) / 1000.0,
		float(row.get("actor_runtime_total_ms", 0.0)) / 1000.0,
	]


func _append_backend_timing(payload: Dictionary) -> void:
	var pieces: Array[String] = []
	var suffix := _timing_suffix(payload)
	if not suffix.is_empty():
		pieces.append(suffix)
	var save_suffix := _save_timing_suffix(payload)
	if not save_suffix.is_empty():
		pieces.append(save_suffix)
	var round_suffix := _round_timing_suffix(payload)
	if not round_suffix.is_empty():
		pieces.append(round_suffix)
	if pieces.is_empty():
		return
	var text := " ".join(pieces)
	# Native acceptance screenshots can lose the transient status line to normal
	# map help/hover UI. Always emit the same timing payload to Godot's log so a
	# completed command has durable performance evidence even if the HUD changes.
	print("GOC_PERF " + text)
	if status_message.is_empty():
		status_message = text
	else:
		status_message += " " + text
	queue_redraw()


func _is_lightweight_order_op(op: String) -> bool:
	return op in LIGHTWEIGHT_ORDER_OPS


func _is_runtime_patch_op(op: String) -> bool:
	return op in RUNTIME_PATCH_OPS


func _is_live_move_batch(commands: Array) -> bool:
	if commands.size() != 2:
		return false
	if not commands[0] is Dictionary or not commands[1] is Dictionary:
		return false
	return (
		String((commands[0] as Dictionary).get("op", "")) == "issue_move_order"
		and String((commands[1] as Dictionary).get("op", "")) == "commit_move_orders"
	)


func _apply_move_order_result_patch(
	op: String,
	commands: Array,
	payload: Dictionary
) -> bool:
	if commands.is_empty() or not commands[0] is Dictionary:
		return false
	var command := commands[0] as Dictionary
	var formation_id := String(command.get("formation", ""))
	if formation_id.is_empty():
		formation_id = String(command.get("formation_id", ""))
	if formation_id.is_empty():
		formation_id = String(command.get("strategic_formation_id", ""))
	if formation_id.is_empty():
		return false

	var data := _result_data(payload, op)
	if not data.has("move_order"):
		return false

	var rows: Array = snapshot.get("strategic_formations", [])
	var found := false
	for idx in range(rows.size()):
		var candidate: Variant = rows[idx]
		if not candidate is Dictionary:
			continue
		var force := (candidate as Dictionary).duplicate(true)
		if String(force.get("id", "")) != formation_id:
			continue
		force["move_order"] = data.get("move_order", null)
		rows[idx] = force
		found = true
		break
	if not found:
		return false

	snapshot["strategic_formations"] = rows
	_rebuild_legal_targets()
	_rebuild_focus_set()
	return true


func _copy_variant(value: Variant) -> Variant:
	if value is Dictionary:
		return (value as Dictionary).duplicate(true)
	if value is Array:
		return (value as Array).duplicate(true)
	return value


func _merge_dictionary_patch(base_value: Variant, patch_value: Variant) -> Dictionary:
	var merged: Dictionary = {}
	if base_value is Dictionary:
		merged = (base_value as Dictionary).duplicate(true)
	if not patch_value is Dictionary:
		return merged
	for key: Variant in (patch_value as Dictionary).keys():
		merged[key] = _copy_variant((patch_value as Dictionary).get(key))
	return merged


func _merge_rows_by_id(base_value: Variant, patch_value: Variant) -> Array:
	var rows: Array = []
	if base_value is Array:
		rows = (base_value as Array).duplicate(true)
	if not patch_value is Array:
		return rows
	var index_by_id: Dictionary = {}
	for idx in range(rows.size()):
		var candidate: Variant = rows[idx]
		if not candidate is Dictionary:
			continue
		var identity := String((candidate as Dictionary).get("id", ""))
		if not identity.is_empty():
			index_by_id[identity] = idx
	for item: Variant in patch_value as Array:
		if not item is Dictionary:
			continue
		var patch_row := item as Dictionary
		var identity := String(patch_row.get("id", ""))
		if identity.is_empty():
			continue
		if index_by_id.has(identity):
			var idx := int(index_by_id[identity])
			var merged := (rows[idx] as Dictionary).duplicate(true)
			for key: Variant in patch_row.keys():
				merged[key] = _copy_variant(patch_row.get(key))
			rows[idx] = merged
		else:
			index_by_id[identity] = rows.size()
			rows.append(patch_row.duplicate(true))
	return rows


func _build_runtime_patch_state(patch: Dictionary) -> Dictionary:
	## Build the same temporary index shape as _try_build_snapshot_state, but from
	## an in-memory candidate. Live presentation state is untouched until the
	## candidate passes schema + stack validation and _commit_snapshot_state runs.
	if String(patch.get("schema", "")) != RUNTIME_PATCH_SCHEMA:
		return {"ok": false, "error": "Unsupported runtime patch schema."}
	if int(patch.get("schema_version", 0)) != RUNTIME_PATCH_SCHEMA_VERSION:
		return {"ok": false, "error": "Unsupported runtime patch version."}

	var candidate := snapshot.duplicate(true)
	if String(candidate.get("schema", "")) != "gates-of-codex.frontend":
		return {"ok": false, "error": "Live snapshot schema is not patchable."}

	var merge_value: Variant = patch.get("merge", {})
	if not merge_value is Dictionary:
		return {"ok": false, "error": "Runtime patch merge block is malformed."}
	var merge := merge_value as Dictionary
	candidate["application"] = _merge_dictionary_patch(
		candidate.get("application", {}), merge.get("application", {})
	)
	candidate["campaign"] = _merge_dictionary_patch(
		candidate.get("campaign", {}), merge.get("campaign", {})
	)
	candidate["provinces"] = _merge_rows_by_id(
		candidate.get("provinces", []), merge.get("provinces", [])
	)
	candidate["formations"] = _merge_rows_by_id(
		candidate.get("formations", []), merge.get("formations", [])
	)

	var replace_value: Variant = patch.get("replace", {})
	if not replace_value is Dictionary:
		return {"ok": false, "error": "Runtime patch replace block is malformed."}
	for key: Variant in (replace_value as Dictionary).keys():
		candidate[key] = _copy_variant((replace_value as Dictionary).get(key))

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
	for province_id: Variant in tmp_stacks.keys():
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
	for origin: Variant in tmp_all_front.keys():
		tmp_front[origin] = (tmp_all_front[origin] as Array).duplicate()

	var stack_err := _validate_battalion_stack_contract_on(candidate, tmp_stacks)
	if not stack_err.is_empty():
		return {"ok": false, "error": stack_err}

	var indexed_orders := index_operational_orders(candidate)
	return {
		"ok": true,
		"error": "",
		"path": snapshot_source_path,
		"snapshot": candidate,
		"orders_by_formation": indexed_orders.get("by_formation", {}),
		"order_formations_by_province": indexed_orders.get("by_province", {}),
		"provinces_by_id": tmp_provinces,
		"battalions_by_province": tmp_battalions_by_province,
		"battalion_stacks_by_province": tmp_stacks,
		"battalions_by_id": tmp_battalions_by_id,
		"formations_by_id": tmp_formations,
		"factions_by_id": tmp_factions,
		"front_by_origin": tmp_front,
		"all_front_by_origin": tmp_all_front,
	}


func _consume_fast_command_result(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	op: String
) -> void:
	if not is_inside_tree():
		return
	if generation <= _last_command_gen_handled:
		return
	_last_command_gen_handled = generation
	_busy_status = ""

	if not success or exit_code != 0:
		var detail := output_text.strip_edges()
		if detail.is_empty():
			detail = "backend exit %s" % exit_code
		_fail_command(op, detail)
		return

	var payload_fail := _payload_failure_detail(output_text)
	if not payload_fail.is_empty():
		_fail_command(op, payload_fail)
		return

	var backend_payload := _backend_payload(output_text)
	_parse_apply_output(output_text)

	if op == "verify_result":
		_capture_verification(backend_payload)
	elif op == "query_supply":
		_capture_supply_query(backend_payload)
	elif _is_lightweight_order_op(op):
		if not _apply_move_order_result_patch(op, commands, backend_payload):
			_fail_command(op, "backend succeeded but move-order presentation patch was incomplete")
			return

	_clear_busy_ui()
	_append_backend_timing(backend_payload)
	queue_redraw()


func _consume_runtime_patch_result(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	op: String
) -> void:
	if not is_inside_tree():
		return
	if generation <= _last_command_gen_handled:
		return
	_last_command_gen_handled = generation
	_busy_status = ""

	if not success or exit_code != 0:
		var detail := output_text.strip_edges()
		if detail.is_empty():
			detail = "backend exit %s" % exit_code
		_fail_command(op, detail)
		return
	var payload_fail := _payload_failure_detail(output_text)
	if not payload_fail.is_empty():
		_fail_command(op, payload_fail)
		return

	var backend_payload := _backend_payload(output_text)
	var patch_value: Variant = backend_payload.get("frontend_patch", null)
	if not patch_value is Dictionary:
		_fail_command(op, "backend succeeded without a runtime frontend patch")
		return

	var previous_selected := selected_province_id
	var previous_battalion := selected_battalion_id
	var previous_scale := view_scale
	var previous_offset := view_offset
	var previous_snapshot := snapshot.duplicate(true)
	var built := _build_runtime_patch_state(patch_value as Dictionary)
	if not bool(built.get("ok", false)):
		_fail_command(op, String(built.get("error", "invalid runtime patch")))
		view_scale = previous_scale
		view_offset = previous_offset
		return

	_parse_apply_output(output_text)
	_capture_verification(backend_payload)
	_capture_end_turn_economy_report(backend_payload)
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
		if op == "end_player_round" and economy_report_open:
			status_message = "Round economy: income %s, maintenance %s, treasury %s." % [
				int(economy_report.get("income", 0)),
				int(economy_report.get("maintenance", 0)),
				int(economy_report.get("treasury", 0)),
			]
		else:
			status_message = "Applied %s." % op
	if snapshot.get("pending_battle") != null:
		status_message += " Pending battle ready - Auto-resolve or Handoff."
	_fit_to_focus(false)
	_clear_busy_ui()
	_append_backend_timing(backend_payload)
	queue_redraw()


func _on_command_finished(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
) -> void:
	var op := "command"
	if not commands.is_empty() and commands[0] is Dictionary:
		op = String((commands[0] as Dictionary).get("op", "command"))

	if _is_live_move_batch(commands) or _is_runtime_patch_op(op):
		_consume_runtime_patch_result(
			generation,
			success,
			exit_code,
			output_text,
			commands,
			op
		)
		return
	if op == "verify_result" or op == "query_supply" or _is_lightweight_order_op(op):
		_consume_fast_command_result(
			generation,
			success,
			exit_code,
			output_text,
			commands,
			op
		)
		return

	super._on_command_finished(
		generation,
		success,
		exit_code,
		output_text,
		commands,
		snapshot_path
	)
	if success and exit_code == 0:
		_append_backend_timing(_backend_payload(output_text))