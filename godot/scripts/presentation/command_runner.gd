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
	## Attempt to start a backend command. Never blocks.
	## Returns {ok:bool, reason:String, generation:int}
	if _shutting_down or not is_inside_tree():
		return {"ok": false, "reason": "shutting_down", "generation": 0}
	if commands.is_empty():
		return {"ok": false, "reason": "empty_commands", "generation": 0}
	var identity := command_identity(commands)
	if is_busy():
		if identity == current_identity():
			return {"ok": false, "reason": "duplicate_in_flight", "generation": generation()}
		return {"ok": false, "reason": "busy", "generation": generation()}
	if executable.is_empty():
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
	}

	var payload := {
		"generation": gen,
		"executable": executable,
		"args": Array(args),
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
		}
		return {"ok": false, "reason": "thread_start_failed", "generation": gen}
	return {"ok": true, "reason": "started", "generation": gen}


func _worker_run(payload: Dictionary) -> void:
	## WORKER THREAD — no Node access beyond call_deferred.
	var executable := String(payload.get("executable", ""))
	var args_variant: Variant = payload.get("args", [])
	var args: PackedStringArray = PackedStringArray()
	if args_variant is Array:
		for item in args_variant:
			args.append(String(item))
	var output: Array = []
	var exit_code := OS.execute(executable, args, output, true, false)
	var text := "\n".join(output)
	# Marshal back to main thread only.
	call_deferred(
		"_on_worker_finished",
		int(payload.get("generation", 0)),
		exit_code,
		text,
		payload.get("commands", []),
		String(payload.get("snapshot_path", ""))
	)


func _on_worker_finished(
	gen: int,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
) -> void:
	if _shutting_down or not is_inside_tree():
		return
	if gen != int(in_flight.get("generation", -1)):
		# Stale completion from a superseded generation.
		return
	if not bool(in_flight.get("active", false)):
		return

	var success := exit_code == 0
	in_flight["active"] = false
	in_flight["result"] = {
		"success": success,
		"exit_code": exit_code,
		"output_text": output_text,
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
