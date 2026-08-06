extends SceneTree

## Deterministic GDScript tests for FrontendCommandRunner async write-back.
## Godot.exe --headless --path godot -s res://scripts/tools/command_runner_test.gd

const FrontendCommandRunnerScript = preload("res://scripts/presentation/command_runner.gd")

var _failed := 0
var _passed := 0
var _runner: Node
var _finished_events: Array = []
var _host: Node


func _initialize() -> void:
	print("command_runner_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	_host = Node.new()
	_host.name = "Host"
	root.add_child(_host)
	_make_runner()

	_test_identity_and_op()
	await _test_duplicate_rejection()
	await _test_busy_blocks_second_command()
	await _test_success_completion_once()
	await _test_failure_clears_busy()
	_test_stale_callback_ignored()
	await _test_exit_during_command_safe()

	print("command_runner_test: passed=%s failed=%s" % [_passed, _failed])
	if _failed > 0:
		push_error("command_runner_test FAIL")
		quit(1)
		return
	print("command_runner_test: PASS")
	quit(0)


func _make_runner() -> void:
	_runner = FrontendCommandRunnerScript.new()
	_runner.name = "Runner"
	_host.add_child(_runner)
	_runner.command_finished.connect(_on_finished)


func _on_finished(
	gen: int,
	success: bool,
	exit_code: int,
	output_text: String,
	commands: Array,
	snapshot_path: String
) -> void:
	_finished_events.append({
		"gen": gen,
		"success": success,
		"exit_code": exit_code,
		"output_text": output_text,
		"commands": commands,
		"snapshot_path": snapshot_path,
	})


func _ok(name: String) -> void:
	_passed += 1
	print("  ok ", name)


func _fail(name: String, detail: String) -> void:
	_failed += 1
	push_error("  FAIL %s: %s" % [name, detail])
	print("  FAIL ", name, ": ", detail)


func _assert_true(name: String, cond: bool, detail := "") -> void:
	if cond:
		_ok(name)
	else:
		_fail(name, detail if not detail.is_empty() else "false")


func _assert_eq(name: String, got: Variant, expected: Variant) -> void:
	if got == expected:
		_ok(name)
	else:
		_fail(name, "got=%s expected=%s" % [got, expected])


func _test_identity_and_op() -> void:
	var cmds := [{"op": "end_turn"}]
	var id1: String = FrontendCommandRunnerScript.command_identity(cmds)
	var id2: String = FrontendCommandRunnerScript.command_identity([{"op": "end_turn"}])
	var id_move: String = FrontendCommandRunnerScript.command_identity([{"op": "move", "province": "A"}])
	_assert_eq("identity stable", id1, id2)
	_assert_true("identity differs by op", id1 != id_move)
	_assert_eq("primary op", FrontendCommandRunnerScript.primary_op(cmds), "end_turn")


func _fake_executable() -> Dictionary:
	return {
		"exe": OS.get_executable_path(),
		"args": PackedStringArray(["--version"]),
	}


func _test_duplicate_rejection() -> void:
	_finished_events.clear()
	var fake: Dictionary = _fake_executable()
	var cmds := [{"op": "end_turn"}]
	var first: Dictionary = _runner.try_start(cmds, fake.exe, fake.args, "res://x.json")
	_assert_true("first start ok", bool(first.get("ok")), str(first))
	_assert_true("busy after start", _runner.is_busy())
	var dup: Dictionary = _runner.try_start(cmds, fake.exe, fake.args, "res://x.json")
	_assert_eq("duplicate rejected", String(dup.get("reason")), "duplicate_in_flight")
	_assert_true("still single generation", int(first.get("generation")) == _runner.generation())
	await _wait_until_idle(5.0)


func _test_busy_blocks_second_command() -> void:
	_finished_events.clear()
	var fake: Dictionary = _fake_executable()
	var a: Dictionary = _runner.try_start([{"op": "end_turn"}], fake.exe, fake.args, "res://a.json")
	_assert_true("start A", bool(a.get("ok")), str(a))
	var b: Dictionary = _runner.try_start([{"op": "move", "province": "X"}], fake.exe, fake.args, "res://b.json")
	_assert_eq("different command while busy", String(b.get("reason")), "busy")
	await _wait_until_idle(5.0)


func _test_success_completion_once() -> void:
	_finished_events.clear()
	var fake: Dictionary = _fake_executable()
	var start: Dictionary = _runner.try_start([{"op": "refresh"}], fake.exe, fake.args, "res://snap.json")
	_assert_true("refresh start", bool(start.get("ok")), str(start))
	var gen: int = int(start.get("generation"))
	await _wait_until_idle(5.0)
	_assert_true("not busy after success", not _runner.is_busy())
	_assert_eq("one finished event", _finished_events.size(), 1)
	if not _finished_events.is_empty():
		_assert_eq("finished gen", int(_finished_events[0].get("gen")), gen)
		_assert_eq("success flag", bool(_finished_events[0].get("success")), true)


func _test_failure_clears_busy() -> void:
	_finished_events.clear()
	var start: Dictionary = _runner.try_start(
		[{"op": "end_turn"}],
		"Z:/definitely/missing/backend-binary-xyz",
		PackedStringArray(["--help"]),
		"res://snap.json"
	)
	if bool(start.get("ok")):
		await _wait_until_idle(5.0)
		_assert_true("not busy after failure", not _runner.is_busy())
		_assert_true("got failure event", _finished_events.size() >= 1)
		if not _finished_events.is_empty():
			_assert_eq("failure success=false", bool(_finished_events[-1].get("success")), false)
	else:
		_assert_true("failed to start invalid exe path is acceptable", true)


func _test_stale_callback_ignored() -> void:
	_finished_events.clear()
	_runner.in_flight = {
		"active": true,
		"generation": 99,
		"op": "end_turn",
		"command_identity": "x",
		"started_usec": Time.get_ticks_usec(),
		"commands": [{"op": "end_turn"}],
		"snapshot_path": "res://s.json",
		"result": {},
		"error_text": "",
	}
	_runner._on_worker_finished(1, 0, "stale", [{"op": "end_turn"}], "res://s.json")
	_assert_eq("stale did not finish", _finished_events.size(), 0)
	_assert_true("still marked active until real clear", bool(_runner.in_flight.get("active")))
	_finished_events.clear()
	_runner.in_flight = {
		"active": true,
		"generation": 99,
		"op": "end_turn",
		"command_identity": "x",
		"started_usec": Time.get_ticks_usec(),
		"commands": [{"op": "end_turn"}],
		"snapshot_path": "res://s.json",
		"result": {},
		"error_text": "",
	}
	_runner._on_worker_finished(99, 0, "ok", [{"op": "end_turn"}], "res://s.json")
	_assert_eq("matching gen finishes once", _finished_events.size(), 1)
	_assert_true("cleared after match", not _runner.is_busy())


func _test_exit_during_command_safe() -> void:
	_finished_events.clear()
	var fake: Dictionary = _fake_executable()
	var start: Dictionary = _runner.try_start([{"op": "end_turn"}], fake.exe, fake.args, "res://s.json")
	_assert_true(
		"start before free",
		bool(start.get("ok")) or String(start.get("reason")) in ["busy", "duplicate_in_flight"],
		str(start)
	)
	_host.queue_free()
	await create_timer(0.25).timeout
	_assert_true("exit during command did not crash", true)
	_host = Node.new()
	root.add_child(_host)
	_make_runner()


func _wait_until_idle(timeout_sec: float) -> void:
	var left := timeout_sec
	while left > 0.0:
		if _runner != null and is_instance_valid(_runner) and not _runner.is_busy():
			await create_timer(0.05).timeout
			return
		await create_timer(0.05).timeout
		left -= 0.05
	_fail("wait_until_idle timeout", "still busy after %ss" % timeout_sec)
