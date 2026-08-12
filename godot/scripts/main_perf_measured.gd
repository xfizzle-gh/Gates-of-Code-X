extends "res://scripts/main_perf.gd"

## P8/#207 native timing layer.
##
## Mutating commands continue through the existing transactional full-snapshot
## replacement path. verify_result is read-only, so it consumes the backend
## verdict directly and deliberately skips reparsing the unchanged full snapshot.


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


func _append_backend_timing(payload: Dictionary) -> void:
	var suffix := _timing_suffix(payload)
	if suffix.is_empty():
		return
	if status_message.is_empty():
		status_message = suffix
	else:
		status_message += " " + suffix
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

	if op != "verify_result":
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
		return

	# verify_result is read-only. The parent implementation would transactionally
	# reload the unchanged 14 MB-class snapshot before exposing the verdict. That
	# work cannot affect authority and only adds latency, so consume the backend
	# result directly while retaining the same generation/error gates.
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
	_capture_verification(backend_payload)
	_clear_busy_ui()
	_append_backend_timing(backend_payload)
	queue_redraw()
