extends Node

## Deterministic fake backend runner for write-back integration tests.
## Mimics FrontendCommandRunner API without spawning real processes.

signal command_finished(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
)

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

var start_count := 0
var started_commands: Array = []
var started_candidates: Array = []
var finish_count := 0
var default_delay_sec := 0.25
## Queue of scripted results: {exit_code, output_text, delay_sec?, launch_path?}
var scripted_results: Array = []
var _generation_counter := 0
var _shutting_down := false
var _pending_timer: SceneTreeTimer


func _exit_tree() -> void:
	_shutting_down = true
	_pending_timer = null


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
	if _shutting_down or not is_inside_tree():
		return {"ok": false, "reason": "shutting_down", "generation": 0}
	if commands.is_empty():
		return {"ok": false, "reason": "empty_commands", "generation": 0}
	var identity := JSON.stringify({"commands": commands})
	if is_busy():
		if identity == current_identity():
			return {"ok": false, "reason": "duplicate_in_flight", "generation": generation()}
		return {"ok": false, "reason": "busy", "generation": generation()}

	_generation_counter += 1
	var gen := _generation_counter
	var op := "command"
	if not commands.is_empty() and commands[0] is Dictionary:
		op = String((commands[0] as Dictionary).get("op", "command"))
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
	start_count += 1
	started_commands.append(commands.duplicate(true))
	started_candidates.append(candidates.duplicate(true))

	var scripted: Dictionary = {}
	if not scripted_results.is_empty():
		scripted = scripted_results.pop_front()
	var delay := float(scripted.get("delay_sec", default_delay_sec))
	var tree := get_tree()
	if tree == null:
		return {"ok": false, "reason": "no_tree", "generation": gen}
	_pending_timer = tree.create_timer(delay)
	_pending_timer.timeout.connect(
		func() -> void:
			_finish_scripted(gen, scripted, commands, snapshot_path)
	)
	return {"ok": true, "reason": "started", "generation": gen}


func _finish_scripted(
	gen: int,
	scripted: Dictionary,
	commands: Array,
	snapshot_path: String
) -> void:
	if _shutting_down or not is_inside_tree():
		return
	if gen != int(in_flight.get("generation", -1)):
		return
	if not bool(in_flight.get("active", false)):
		return
	var exit_code := int(scripted.get("exit_code", 0))
	var output_text := String(scripted.get("output_text", "{\"ok\":true,\"results\":[]}"))
	var launch_path := String(scripted.get("launch_path", "fake-backend"))
	var success := exit_code == 0
	in_flight["active"] = false
	in_flight["launch_path"] = launch_path
	in_flight["result"] = {
		"success": success,
		"exit_code": exit_code,
		"output_text": output_text,
		"launch_path": launch_path,
	}
	finish_count += 1
	command_finished.emit(gen, success, exit_code, output_text, commands, snapshot_path)


func force_finish_stale(gen: int, exit_code: int, output_text: String, commands: Array, snapshot_path: String) -> void:
	## Emit a completion for an arbitrary generation without clearing current busy if gens differ.
	command_finished.emit(gen, exit_code == 0, exit_code, output_text, commands, snapshot_path)
