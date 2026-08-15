extends Node

## Non-blocking frontend apply-frontend runner.
## Worker thread may perform process launch plus file/socket I/O; all Node/UI work
## stays on the main thread.

signal command_finished(
	generation: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
)

const _SESSION_FILE_NAME := ".goc-backend-session.json"
const _SESSION_SCHEMA := "gates-of-codex.persistent-backend"
const _SESSION_SCHEMA_VERSION := 2
const _PING_TIMEOUT_MSEC := 750
const _APPLY_TIMEOUT_MSEC := 600000

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
	## candidates: Array of {executable:String, args:Array|PackedStringArray}.
	## Authenticated frozen apply-frontend candidates first try the already-running
	## persistent backend directly over its localhost session. Only a failure
	## before apply dispatch may fall back to process launch.
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
		var normalized_item := {"executable": exe, "args": arg_list}
		if (item as Dictionary).has("persistent_ping_timeout_msec"):
			normalized_item["persistent_ping_timeout_msec"] = int(
				(item as Dictionary).get("persistent_ping_timeout_msec", _PING_TIMEOUT_MSEC)
			)
		if (item as Dictionary).has("persistent_apply_timeout_msec"):
			normalized_item["persistent_apply_timeout_msec"] = int(
				(item as Dictionary).get("persistent_apply_timeout_msec", _APPLY_TIMEOUT_MSEC)
			)
		normalized.append(normalized_item)
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


static func _is_commit_sha(value: String) -> bool:
	var candidate := value.strip_edges().to_lower()
	if candidate.length() != 40:
		return false
	for index in candidate.length():
		if "0123456789abcdef".find(candidate.substr(index, 1)) < 0:
			return false
	return true


static func _path_key(value: String) -> String:
	var key := value.strip_edges().replace("\\", "/")
	while key.ends_with("/") and key.length() > 1:
		key = key.left(key.length() - 1)
	if OS.get_name() == "Windows":
		key = key.to_lower()
	return key


static func _persistent_apply_spec(candidate: Dictionary) -> Dictionary:
	## The direct path is intentionally limited to the frozen invocation that
	## already carries exact package provenance. Source/dev candidates retain the
	## ordinary process path.
	var raw_args: Variant = candidate.get("args", [])
	if not raw_args is Array:
		return {}
	var args: Array = raw_args as Array
	var apply_index := args.find("apply-frontend")
	if apply_index < 0 or apply_index + 1 >= args.size():
		return {}
	var commit_index := args.find("--expected-source-commit")
	if commit_index < 0 or commit_index + 1 >= args.size():
		return {}
	var expected_commit := String(args[commit_index + 1]).strip_edges().to_lower()
	if not _is_commit_sha(expected_commit):
		return {}
	var campaign_path := String(args[apply_index + 1]).strip_edges()
	if campaign_path.is_empty():
		return {}
	var snapshot_path := ""
	var commands_path := ""
	var index := apply_index + 2
	while index < args.size():
		var token := String(args[index])
		if token == "--snapshot" and index + 1 < args.size():
			snapshot_path = String(args[index + 1]).strip_edges()
			index += 2
			continue
		if token == "--commands" and index + 1 < args.size():
			commands_path = String(args[index + 1]).strip_edges()
			index += 2
			continue
		index += 1
	if snapshot_path.is_empty() or commands_path.is_empty():
		return {}
	return {
		"campaign_path": campaign_path,
		"snapshot_path": snapshot_path,
		"commands_path": commands_path,
		"expected_commit": expected_commit,
		"session_path": campaign_path.get_base_dir().path_join(_SESSION_FILE_NAME),
	}


static func _load_authenticated_session(spec: Dictionary) -> Dictionary:
	if spec.is_empty():
		return {}
	var session_path := String(spec.get("session_path", ""))
	if session_path.is_empty() or not FileAccess.file_exists(session_path):
		return {}
	var file := FileAccess.open(session_path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	file.close()
	if not parsed is Dictionary:
		return {}
	var session := parsed as Dictionary
	if String(session.get("schema", "")) != _SESSION_SCHEMA:
		return {}
	if int(session.get("schema_version", 0)) != _SESSION_SCHEMA_VERSION:
		return {}
	if String(session.get("source_commit", "")).strip_edges().to_lower() != String(spec.get("expected_commit", "")):
		return {}
	if _path_key(String(session.get("campaign_path", ""))) != _path_key(String(spec.get("campaign_path", ""))):
		return {}
	var port := int(session.get("port", 0))
	var token := String(session.get("token", ""))
	if port <= 0 or port > 65535 or token.is_empty() or int(session.get("pid", 0)) <= 0:
		return {}
	return session.duplicate(true)


static func _tcp_json_request(
	session: Dictionary,
	payload: Dictionary,
	timeout_msec: int
) -> Dictionary:
	var peer := StreamPeerTCP.new()
	var port := int(session.get("port", 0))
	var connect_error := peer.connect_to_host("127.0.0.1", port)
	if connect_error != OK:
		return {"ok": false, "dispatched": false, "reason": "connect_failed"}
	var deadline := Time.get_ticks_msec() + maxi(1, timeout_msec)
	while Time.get_ticks_msec() < deadline:
		peer.poll()
		var status := peer.get_status()
		if status == StreamPeerTCP.STATUS_CONNECTED:
			break
		if status == StreamPeerTCP.STATUS_ERROR or status == StreamPeerTCP.STATUS_NONE:
			return {"ok": false, "dispatched": false, "reason": "connect_failed"}
		OS.delay_msec(1)
	if peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		peer.disconnect_from_host()
		return {"ok": false, "dispatched": false, "reason": "connect_timeout"}

	var message := payload.duplicate(true)
	message["token"] = String(session.get("token", ""))
	message["source_commit"] = String(session.get("source_commit", "")).strip_edges().to_lower()
	var send_error := peer.put_data((JSON.stringify(message) + "\n").to_utf8_buffer())
	if send_error != OK:
		peer.disconnect_from_host()
		return {"ok": false, "dispatched": false, "reason": "send_failed"}

	var received := PackedByteArray()
	while Time.get_ticks_msec() < deadline:
		peer.poll()
		var available := peer.get_available_bytes()
		if available > 0:
			var chunk: Array = peer.get_partial_data(available)
			if chunk.size() < 2 or int(chunk[0]) != OK:
				peer.disconnect_from_host()
				return {"ok": false, "dispatched": true, "reason": "receive_failed"}
			received.append_array(chunk[1] as PackedByteArray)
			var text := received.get_string_from_utf8()
			var newline := text.find("\n")
			if newline >= 0:
				peer.disconnect_from_host()
				var response: Variant = JSON.parse_string(text.substr(0, newline))
				if response is Dictionary:
					return {"ok": true, "dispatched": true, "response": response}
				return {"ok": false, "dispatched": true, "reason": "invalid_json"}
		var status := peer.get_status()
		if status == StreamPeerTCP.STATUS_ERROR or status == StreamPeerTCP.STATUS_NONE:
			peer.disconnect_from_host()
			return {"ok": false, "dispatched": true, "reason": "connection_lost"}
		OS.delay_msec(1)
	peer.disconnect_from_host()
	return {"ok": false, "dispatched": true, "reason": "response_timeout"}


static func _ambiguous_daemon_payload() -> String:
	return JSON.stringify({
		"ok": false,
		"campaign_path": "",
		"snapshot_path": "",
		"commands_applied": 0,
		"results": [{
			"op": "persistent_backend",
			"ok": false,
			"detail": "Persistent backend response was lost after dispatch; command outcome is ambiguous. Reload campaign state before retrying.",
			"data": {},
		}],
	})


static func _try_persistent_backend(candidate: Dictionary) -> Dictionary:
	var spec := _persistent_apply_spec(candidate)
	if spec.is_empty():
		return {"handled": false}
	var session := _load_authenticated_session(spec)
	if session.is_empty():
		return {"handled": false}
	var ping_timeout := int(candidate.get("persistent_ping_timeout_msec", _PING_TIMEOUT_MSEC))
	var apply_timeout := int(candidate.get("persistent_apply_timeout_msec", _APPLY_TIMEOUT_MSEC))
	var ping := _tcp_json_request(session, {"action": "ping"}, ping_timeout)
	if not bool(ping.get("ok", false)):
		return {"handled": false}
	var ping_response: Dictionary = ping.get("response", {})
	if not bool(ping_response.get("ok", false)):
		return {"handled": false}

	var applied := _tcp_json_request(session, {
		"action": "apply",
		"campaign_path": String(spec.get("campaign_path", "")),
		"snapshot_path": String(spec.get("snapshot_path", "")),
		"commands_path": String(spec.get("commands_path", "")),
	}, apply_timeout)
	var launch_path := "persistent-backend://127.0.0.1:%d" % int(session.get("port", 0))
	if not bool(applied.get("ok", false)):
		if bool(applied.get("dispatched", false)):
			# Never replay automatically after apply bytes were accepted. The daemon
			# may have committed and only lost its response.
			return {
				"handled": true,
				"exit_code": 0,
				"output_text": _ambiguous_daemon_payload(),
				"launch_path": launch_path,
			}
		return {"handled": false}

	var response: Dictionary = applied.get("response", {})
	if not bool(response.get("handled", false)):
		# The daemon explicitly declined before applying this operation. Match the
		# existing Python client: invalidate its lease and use the approved one-shot
		# executable path for unsupported operations.
		_tcp_json_request(session, {"action": "invalidate"}, ping_timeout)
		return {"handled": false}
	return {
		"handled": true,
		"exit_code": int(response.get("exit_code", 1)),
		"output_text": String(response.get("stdout", "")),
		"launch_path": launch_path,
	}


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
		var direct := _try_persistent_backend(candidate as Dictionary)
		if bool(direct.get("handled", false)):
			exit_code = int(direct.get("exit_code", 1))
			text = String(direct.get("output_text", ""))
			launch_path = String(direct.get("launch_path", "persistent-backend"))
			break

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