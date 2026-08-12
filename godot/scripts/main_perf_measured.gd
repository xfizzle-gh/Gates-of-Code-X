extends "res://scripts/main_perf.gd"

## P8/#207 native timing layer.
##
## Most mutating commands continue through the existing transactional
## full-snapshot replacement path. Two narrow fast paths avoid known redundant
## presentation work:
##
## * verify_result is read-only and consumes the backend verdict directly.
## * issue/cancel move-order commands still persist authoritatively in Python,
##   but update only the returned move_order field in the live Godot snapshot.
##   The multi-megabyte frontend snapshot is rebuilt by the next full mutation.

const LIGHTWEIGHT_ORDER_OPS := ["issue_move_order", "cancel_move_order"]


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


func _round_timing_suffix(payload: Dictionary) -> String:
	var data := _result_data(payload, "end_player_round")
	var perf: Variant = data.get("perf_turn_cycle", {})
	if not perf is Dictionary:
		return ""
	var row := perf as Dictionary
	if not row.has("ai_take_turn_total_ms"):
		return ""
	return "[round: AI %.2fs, advance %.2fs, actors %.2fs]" % [
		float(row.get("ai_take_turn_total_ms", 0.0)) / 1000.0,
		float(row.get("advance_turn_total_ms", 0.0)) / 1000.0,
		float(row.get("actor_runtime_total_ms", 0.0)) / 1000.0,
	]


func _append_backend_timing(payload: Dictionary) -> void:
	var pieces: Array[String] = []
	var suffix := _timing_suffix(payload)
	if not suffix.is_empty():
		pieces.append(suffix)
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
	elif _is_lightweight_order_op(op):
		if not _apply_move_order_result_patch(op, commands, backend_payload):
			_fail_command(op, "backend succeeded but move-order presentation patch was incomplete")
			return

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

	if op == "verify_result" or _is_lightweight_order_op(op):
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