extends SceneTree

## Owner-readiness command probe for the exact packaged Godot -> retained backend path.
## The process may take time to start; command_elapsed_ms begins immediately before
## FrontendCommandRunner dispatch, matching an already-running player UI click.

const FrontendCommandRunnerScript = preload("res://scripts/presentation/command_runner.gd")


func _initialize() -> void:
	call_deferred("_run")


func _arg_value(arguments: PackedStringArray, name: String) -> String:
	var prefix := "--%s=" % name
	for argument in arguments:
		var text := String(argument)
		if text.begins_with(prefix):
			return text.substr(prefix.length())
	return ""


func _write_result(path: String, payload: Dictionary) -> void:
	if path.is_empty():
		print(JSON.stringify(payload))
		return
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("Unable to write owner-readiness command probe result: %s" % path)
		return
	file.store_string(JSON.stringify(payload) + "\n")
	file.close()


func _fail(output_path: String, reason: String, detail := "") -> void:
	_write_result(output_path, {
		"ok": false,
		"reason": reason,
		"detail": detail,
		"persistent_backend_used": false,
	})
	push_error("owner_readiness_command_probe: %s %s" % [reason, detail])
	quit(1)


func _run() -> void:
	var arguments := OS.get_cmdline_user_args()
	var campaign := _arg_value(arguments, "campaign")
	var snapshot := _arg_value(arguments, "snapshot")
	var commands_path := _arg_value(arguments, "commands")
	var backend := _arg_value(arguments, "backend")
	var expected_commit := _arg_value(arguments, "expected-source-commit")
	var output_path := _arg_value(arguments, "out")
	if campaign.is_empty() or snapshot.is_empty() or commands_path.is_empty() or backend.is_empty():
		_fail(output_path, "missing_argument")
		return
	if expected_commit.length() != 40:
		_fail(output_path, "invalid_expected_source_commit", expected_commit)
		return
	if not FileAccess.file_exists(commands_path):
		_fail(output_path, "commands_missing", commands_path)
		return

	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(commands_path))
	if not parsed is Dictionary:
		_fail(output_path, "commands_invalid_json")
		return
	var commands_variant: Variant = (parsed as Dictionary).get("commands", [])
	if not commands_variant is Array or (commands_variant as Array).is_empty():
		_fail(output_path, "commands_empty")
		return
	var commands: Array = (commands_variant as Array).duplicate(true)

	var host := Node.new()
	root.add_child(host)
	var runner = FrontendCommandRunnerScript.new()
	host.add_child(runner)
	var candidate := {
		"executable": backend,
		"args": [
			"-m", "gates_of_codex", "apply-frontend", campaign,
			"--snapshot", snapshot,
			"--commands", commands_path,
			"--expected-source-commit", expected_commit,
		],
	}
	var started_usec := Time.get_ticks_usec()
	var start_result: Dictionary = runner.try_start_candidates(
		commands,
		[candidate],
		snapshot
	)
	if not bool(start_result.get("ok", false)):
		_fail(output_path, "runner_start_failed", JSON.stringify(start_result))
		return

	var deadline_usec := started_usec + 620000000
	while runner.is_busy() and Time.get_ticks_usec() < deadline_usec:
		await process_frame
	if runner.is_busy():
		_fail(output_path, "runner_timeout")
		return
	var elapsed_ms := float(Time.get_ticks_usec() - started_usec) / 1000.0
	var result: Dictionary = runner.in_flight.get("result", {})
	var output_text := String(result.get("output_text", ""))
	var launch_path := runner.last_launch_path()
	var backend_report: Variant = JSON.parse_string(output_text)
	var backend_ok := backend_report is Dictionary and bool((backend_report as Dictionary).get("ok", false))
	var persistent_used := launch_path.begins_with("persistent-backend://")
	var ok := bool(result.get("success", false)) and backend_ok and persistent_used
	_write_result(output_path, {
		"ok": ok,
		"command_elapsed_ms": round(elapsed_ms * 1000.0) / 1000.0,
		"persistent_backend_used": persistent_used,
		"launch_path": launch_path,
		"exit_code": int(result.get("exit_code", -1)),
		"backend_report": backend_report if backend_report is Dictionary else {},
		"raw_output": output_text if not backend_ok else "",
	})
	if not ok:
		push_error(
			"owner_readiness_command_probe failed: persistent=%s launch=%s output=%s"
			% [persistent_used, launch_path, output_text.left(800)]
		)
		quit(1)
		return
	quit(0)
