extends Node

## Non-blocking frontend apply-frontend runner.
## Worker thread may only call OS.execute; all Node/UI work stays on the main thread.

signal command_finished(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
)

## Authoritative in-flight state (main thread only).
var in_flight: Dictionary = {
	"active": false,
	"generation": 0,
	"op": "",
	"command_identity": "",
	"started_usec": 0,
	"commands": [],
	"snapshot_path": "",
	"result": {},
	"error_text": "",
	"launch_path": "",
}

var _thread: Thread
var _shutting_down := false
var _generation_counter := 0


func _exit_tree() -> void:
	_shutting_down = true
	_join_worker()


func is_busy() -> bool:
	return bool(in_flight.get("active", false))


func current_op() -> String:
	return String(in_flight.get("op", ""))


func current_identity() -> String:
	return String(in_flight.get("command_identity", ""))


func generation() -> int:
	return int(in_flight.get("generation", 0))


func last_launch_path() -> String:
	return String(in_flight.get("launch_path", ""))


static func command_identity(commands: Array) -> String:
	## Stable identity for duplicate suppression (deterministic JSON).
	return JSON.stringify({"commands": commands})


static func primary_op(commands: Array) -> String:
	if commands.is_empty() or not commands[0] is Dictionary:
		return "command"
	return String((commands[0] as Dictionary).get("op", "command"))


func try_start(
	commands: Array,
	executable: String,
	args: PackedStringArray,
	snapshot_path: String
) -> Dictionary:
	return try_start_candidates(
		commands,
		[{"executable": executable, "args": Array(args)}],
		snapshot_path
	)


func try_start_candidates(
	commands: Array,
	candidates: Array,
	snapshot_path: String
) -> Dictionary:
	## candidates: Array of {executable:String, args:Array|PackedStringArray}
	## Tries each candidate in order. exit_code == -1 means "could not launch" → next.
	if _shutting_down or not is_inside_tree():
		return {"ok": false, "reason": "shutting_down", "generation": 0}
	if commands.is_empty():
		return {"ok": false, "reason": "empty_commands", "generation": 0}
	var identity := command_identity(commands)
	if is_busy():
		if identity == current_identity():
			return {"ok": false, "reason": "duplicate_in_flight", "generation": generation()}
		return {"ok": false, "reason": "busy", "generation": generation()}
	if candidates.is_empty():
		return {"ok": false, "reason": "missing_executable", "generation": 0}

	_join_worker()
	_generation_counter += 1
	var gen := _generation_counter
	var op := primary_op(commands)
	in_flight = {
		"active": true,
		"generation": gen,
		"op": op,
		"command_identity": identity,
		"started_usec": Time.get_ticks_usec(),
		"commands": commands.duplicate(true),
		"snapshot_path": snapshot_path,
		"result": {},
		"error_text": "",
		"launch_path": "",
	}

	var normalized: Array = []
	for item in candidates:
		if not item is Dictionary:
			continue
		var exe := String((item as Dictionary).get("executable", "")).strip_edges()
		if exe.is_empty():
			continue
		var raw_args: Variant = (item as Dictionary).get("args", [])
		var arg_list: Array = []
		if raw_args is PackedStringArray:
			for a in raw_args:
				arg_list.append(String(a))
		elif raw_args is Array:
			for a in raw_args:
				arg_list.append(String(a))
		normalized.append({"executable": exe, "args": arg_list})
	if normalized.is_empty():
		in_flight["active"] = false
		return {"ok": false, "reason": "missing_executable", "generation": gen}

	var payload := {
		"generation": gen,
		"candidates": normalized,
		"commands": commands.duplicate(true),
		"snapshot_path": snapshot_path,
	}
	_thread = Thread.new()
	var err := _thread.start(Callable(self, "_worker_run").bind(payload))
	if err != OK:
		in_flight = {
			"active": false,
			"generation": gen,
			"op": op,
			"command_identity": identity,
			"started_usec": 0,
			"commands": [],
			"snapshot_path": snapshot_path,
			"result": {},
			"error_text": "failed to start worker thread",
			"launch_path": "",
		}
		return {"ok": false, "reason": "thread_start_failed", "generation": gen}
	return {"ok": true, "reason": "started", "generation": gen}


static func could_not_launch(exit_code: int, output_text: String = "") -> bool:
	## True when the OS could not start the candidate (try next fallback).
	## Windows: -1. Linux/macOS shell: 127 "command not found".
	if exit_code == -1 or exit_code == 127:
		return true
	var lower := output_text.to_lower()
	if lower.contains("not found") and (exit_code == 1 or exit_code == 127):
		return true
	if lower.contains("is not recognized"):
		return true
	return false


func _worker_run(payload: Dictionary) -> void:
	## WORKER THREAD — no Node access beyond call_deferred.
	var candidates: Array = payload.get("candidates", [])
	var exit_code := -1
	var text := ""
	var launch_path := ""
	var idx := 0
	while idx < candidates.size():
		var candidate: Variant = candidates[idx]
		idx += 1
		if not candidate is Dictionary:
			continue
		var executable := String((candidate as Dictionary).get("executable", ""))
		var args_variant: Variant = (candidate as Dictionary).get("args", [])
		var args := PackedStringArray()
		if args_variant is Array:
			for item in args_variant:
				args.append(String(item))
		var output: Array = []
		exit_code = OS.execute(executable, args, output, true, false)
		text = "\n".join(output)
		launch_path = executable
		# Only advance when the process itself could not start.
		if not could_not_launch(exit_code, text):
			break
	call_deferred(
		"_on_worker_finished",
		int(payload.get("generation", 0)),
		exit_code,
		text,
		payload.get("commands", []),
		String(payload.get("snapshot_path", "")),
		launch_path
	)


func _on_worker_finished(
	gen: int,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String,
	launch_path: String = ""
) -> void:
	if _shutting_down or not is_inside_tree():
		return
	if gen != int(in_flight.get("generation", -1)):
		return
	if not bool(in_flight.get("active", false)):
		return

	var success := exit_code == 0
	in_flight["active"] = false
	in_flight["launch_path"] = launch_path
	in_flight["result"] = {
		"success": success,
		"exit_code": exit_code,
		"output_text": output_text,
		"launch_path": launch_path,
	}
	in_flight["error_text"] = "" if success else output_text
	_join_worker()
	command_finished.emit(gen, success, exit_code, output_text, commands, snapshot_path)


func _join_worker() -> void:
	if _thread == null:
		return
	if _thread.is_started():
		_thread.wait_to_finish()
	_thread = null
