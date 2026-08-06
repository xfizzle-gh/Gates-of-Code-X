extends SceneTree

## Integration tests for main_writeback async apply path with a fake runner.
## Godot.exe --headless --path godot -s res://scripts/tools/writeback_integration_test.gd

const MainWritebackScript = preload("res://scripts/main_writeback.gd")
const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")
const RealRunnerScript = preload("res://scripts/presentation/command_runner.gd")

var _failed := 0
var _passed := 0
var _client: Node
var _fake: Node
var _dir := ""
var _snapshot_path := ""
var _commands_path := ""
var _campaign_path := ""
var _success_snapshot_path := ""


func _initialize() -> void:
	print("writeback_integration_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	_dir = OS.get_user_data_dir().path_join("writeback_integration_test")
	DirAccess.make_dir_recursive_absolute(_dir)
	_snapshot_path = _dir.path_join("snapshot.json")
	_commands_path = _dir.path_join("commands.json")
	_campaign_path = _dir.path_join("campaign.json")
	_success_snapshot_path = _dir.path_join("snapshot_success.json")
	_write_json(_campaign_path, {"id": "test-campaign"})
	_write_base_snapshot(_snapshot_path)
	_write_success_snapshot(_success_snapshot_path)

	await _setup_client()
	await _test_duplicate_end_turn()
	await _test_duplicate_move()
	await _test_different_command_rejected_while_busy()
	await _test_mutating_buttons_disabled_while_busy()
	await _test_pan_zoom_and_process_during_slow_command()
	await _test_success_reloads_once_and_restores_selection()
	await _test_backend_failure_preserves_snapshot()
	await _test_exit0_missing_snapshot_preserves()
	await _test_exit0_malformed_json_preserves()
	await _test_exit0_wrong_schema_preserves()
	await _test_exit0_payload_ok_false_preserves()
	await _test_controls_restored_after_failure()
	await _test_stale_completion_ignored()
	await _test_free_during_slow_command_safe()
	await _test_launch_fallback_second_succeeds()

	print("writeback_integration_test: passed=%s failed=%s" % [_passed, _failed])
	if _failed > 0:
		push_error("writeback_integration_test FAIL")
		quit(1)
		return
	print("writeback_integration_test: PASS")
	quit(0)


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


func _write_json(path: String, data: Variant) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(data, "\t"))
	f.close()


func _base_snapshot_dict(snapshot_path: String) -> Dictionary:
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 6,
		"campaign": {"current_faction": "nato", "turn": 1},
		"alliances": [],
		"objectives": [],
		"provinces": [
			{"id": "Warszawa", "display_name": "Warsaw", "x": 100.0, "y": 100.0, "owner": "nato", "yield": 2, "fort": 0},
			{"id": "Lodz", "display_name": "Lodz", "x": 140.0, "y": 110.0, "owner": "nato", "yield": 1, "fort": 0},
			{"id": "Radom", "display_name": "Radom", "x": 120.0, "y": 140.0, "owner": "rusa", "yield": 1, "fort": 0},
		],
		"battalions": [
			{
				"id": "alpha-battalion",
				"province_id": "Warszawa",
				"faction": "nato",
				"formation_id": "f1",
				"strength": 10,
				"authorized_strength": 10,
				"condition": 100,
				"supply": 100,
				"move": 1,
				"combat": 1,
			},
			{
				"id": "bravo-battalion",
				"province_id": "Warszawa",
				"faction": "nato",
				"formation_id": "f1",
				"strength": 8,
				"authorized_strength": 10,
				"condition": 90,
				"supply": 90,
				"move": 1,
				"combat": 1,
			},
		],
		"battalion_stacks": {
			"Warszawa": ["alpha-battalion", "bravo-battalion"],
		},
		"formations": [{"id": "f1", "display_name": "1st Brigade"}],
		"factions": [{"id": "nato", "display_name": "NATO"}, {"id": "rusa", "display_name": "RUSA"}],
		"front_options": [
			{"origin": "Warszawa", "target": "Lodz", "kind": "move", "battalion_id": "alpha-battalion"},
			{"origin": "Warszawa", "target": "Radom", "kind": "move", "battalion_id": "bravo-battalion"},
		],
		"control": {
			"enabled": true,
			"commands_path": _commands_path,
			"campaign_path": _campaign_path,
			"snapshot_path": snapshot_path,
			"python_executable": "",
			"python_module": "gates_of_codex",
		},
	}


func _write_base_snapshot(path: String) -> void:
	_write_json(path, _base_snapshot_dict(path))


func _write_success_snapshot(path: String) -> void:
	var snap := _base_snapshot_dict(path)
	# Mutate so we can detect reload: bravo moves conceptually; turn advances.
	snap["campaign"]["turn"] = 2
	snap["battalions"][1]["province_id"] = "Lodz"
	snap["battalion_stacks"] = {
		"Warszawa": ["alpha-battalion"],
		"Lodz": ["bravo-battalion"],
	}
	snap["control"]["snapshot_path"] = path
	_write_json(path, snap)


func _setup_client() -> void:
	if _client != null and is_instance_valid(_client):
		_client.queue_free()
		await create_timer(0.05).timeout
	_client = MainWritebackScript.new()
	_client.name = "WritebackClient"
	root.add_child(_client)
	await create_timer(0.05).timeout
	_client._load_snapshot(_snapshot_path)
	_client.selected_province_id = "Warszawa"
	_client.selected_battalion_id = "alpha-battalion"
	_client._rebuild_legal_targets()
	_client._rebuild_focus_set()
	_client.snapshot_commit_count = 0
	_fake = FakeRunnerScript.new()
	_fake.name = "FakeRunner"
	_client.inject_command_runner(_fake)
	_assert_true("client ready", not _client.provinces_by_id.is_empty())


func _wait_until(pred: Callable, timeout_sec := 3.0) -> bool:
	var left := timeout_sec
	while left > 0.0:
		if pred.call():
			return true
		await create_timer(0.05).timeout
		left -= 0.05
	return false


func _test_duplicate_end_turn() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.35},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	_client._queue_and_apply([{"op": "end_turn"}])
	_assert_eq("duplicate end_turn one submit", _fake.start_count, 1)
	_assert_true("busy after end_turn", _client.is_command_busy())
	await _wait_until(func() -> bool: return not _client.is_command_busy())


func _test_duplicate_move() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.35},
	]
	var move_cmd := [{"op": "move", "battalion_id": "alpha-battalion", "to": "Lodz"}]
	_client._queue_and_apply(move_cmd)
	_client._queue_and_apply(move_cmd)
	_assert_eq("duplicate move one submit", _fake.start_count, 1)
	await _wait_until(func() -> bool: return not _client.is_command_busy())


func _test_different_command_rejected_while_busy() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.4},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	_client._queue_and_apply([{"op": "refresh"}])
	_assert_eq("different command not submitted", _fake.start_count, 1)
	_assert_true("status mentions busy", String(_client.status_message).to_lower().contains("busy"))
	await _wait_until(func() -> bool: return not _client.is_command_busy())


func _test_mutating_buttons_disabled_while_busy() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.4},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	var busy_ids: PackedStringArray = _client.enabled_action_button_ids()
	_assert_true("end_turn disabled while busy", not busy_ids.has("end_turn"))
	_assert_true("refresh disabled while busy", not busy_ids.has("refresh"))
	_assert_true("fit still enabled while busy", busy_ids.has("fit"))
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	var idle_ids: PackedStringArray = _client.enabled_action_button_ids()
	_assert_true("end_turn restored after idle", idle_ids.has("end_turn"))


func _test_pan_zoom_and_process_during_slow_command() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.5},
	]
	var scale0: float = _client.view_scale
	var off0: Vector2 = _client.view_offset
	_client._queue_and_apply([{"op": "end_turn"}])
	_assert_true("busy for pan/zoom test", _client.is_command_busy())
	_client.view_offset += Vector2(12, -7)
	_client._zoom_at(Vector2(200, 200), 1.14)
	_assert_true("pan applied while busy", _client.view_offset != off0)
	_assert_true("zoom applied while busy", not is_equal_approx(_client.view_scale, scale0))
	var frames := 0
	var left := 0.45
	while left > 0.0 and _client.is_command_busy():
		frames += 1
		await create_timer(0.05).timeout
		left -= 0.05
	_assert_true("processed frames during slow command", frames >= 3)
	await _wait_until(func() -> bool: return not _client.is_command_busy())


func _test_success_reloads_once_and_restores_selection() -> void:
	await _setup_client()
	# Point control snapshot_path at success file so commit loads it.
	_client.snapshot["control"]["snapshot_path"] = _success_snapshot_path
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.2},
	]
	_client.selected_province_id = "Warszawa"
	_client.selected_battalion_id = "alpha-battalion"
	var before: int = int(_client.snapshot_commit_count)
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("success commit once", int(_client.snapshot_commit_count), before + 1)
	_assert_eq("selection province restored", _client.selected_province_id, "Warszawa")
	_assert_eq("selection battalion restored", _client.selected_battalion_id, "alpha-battalion")
	_assert_eq("turn advanced from success snapshot", int(_client.snapshot.get("campaign", {}).get("turn", 0)), 2)


func _capture_live_fingerprint() -> Dictionary:
	return {
		"turn": int(_client.snapshot.get("campaign", {}).get("turn", -1)),
		"prov_count": _client.provinces_by_id.size(),
		"stack_w": (_client.battalion_stacks_by_province.get("Warszawa", []) as Array).size(),
		"selected": _client.selected_province_id,
		"battalion": _client.selected_battalion_id,
		"scale": _client.view_scale,
		"offset": _client.view_offset,
	}


func _assert_fingerprint_unchanged(name: String, before: Dictionary) -> void:
	var after := _capture_live_fingerprint()
	_assert_eq(name + " turn", after.turn, before.turn)
	_assert_eq(name + " prov", after.prov_count, before.prov_count)
	_assert_eq(name + " stack", after.stack_w, before.stack_w)
	_assert_eq(name + " selected", after.selected, before.selected)
	_assert_eq(name + " battalion", after.battalion, before.battalion)
	_assert_eq(name + " scale", after.scale, before.scale)
	_assert_eq(name + " offset", after.offset, before.offset)


func _test_backend_failure_preserves_snapshot() -> void:
	await _setup_client()
	var before: Dictionary = _capture_live_fingerprint()
	var commits: int = int(_client.snapshot_commit_count)
	_fake.scripted_results = [
		{"exit_code": 2, "output_text": "backend exploded", "delay_sec": 0.15},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("failure no commit", int(_client.snapshot_commit_count), commits)
	_assert_fingerprint_unchanged("failure", before)
	_assert_true("failure status", String(_client.status_message).contains("failed") or String(_client.status_message).contains("Apply failed"))


func _test_exit0_missing_snapshot_preserves() -> void:
	await _setup_client()
	var missing := _dir.path_join("does_not_exist.json")
	_client.snapshot["control"]["snapshot_path"] = missing
	var before: Dictionary = _capture_live_fingerprint()
	var commits: int = int(_client.snapshot_commit_count)
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.15},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("missing snap no commit", int(_client.snapshot_commit_count), commits)
	_assert_fingerprint_unchanged("missing", before)


func _test_exit0_malformed_json_preserves() -> void:
	await _setup_client()
	var bad := _dir.path_join("bad.json")
	var f := FileAccess.open(bad, FileAccess.WRITE)
	f.store_string("{not-json")
	f.close()
	_client.snapshot["control"]["snapshot_path"] = bad
	var before: Dictionary = _capture_live_fingerprint()
	var commits: int = int(_client.snapshot_commit_count)
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.15},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("malformed no commit", int(_client.snapshot_commit_count), commits)
	_assert_fingerprint_unchanged("malformed", before)


func _test_exit0_wrong_schema_preserves() -> void:
	await _setup_client()
	var bad := _dir.path_join("wrong_schema.json")
	_write_json(bad, {"schema": "not-frontend", "provinces": []})
	_client.snapshot["control"]["snapshot_path"] = bad
	var before: Dictionary = _capture_live_fingerprint()
	var commits: int = int(_client.snapshot_commit_count)
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.15},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("wrong schema no commit", int(_client.snapshot_commit_count), commits)
	_assert_fingerprint_unchanged("schema", before)


func _test_exit0_payload_ok_false_preserves() -> void:
	await _setup_client()
	_client.snapshot["control"]["snapshot_path"] = _success_snapshot_path
	var before: Dictionary = _capture_live_fingerprint()
	var commits: int = int(_client.snapshot_commit_count)
	_fake.scripted_results = [
		{
			"exit_code": 0,
			"output_text": "{\"ok\":false,\"results\":[{\"op\":\"end_turn\",\"ok\":false,\"detail\":\"order rejected\"}]}",
			"delay_sec": 0.15,
		},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("ok:false no commit", int(_client.snapshot_commit_count), commits)
	_assert_fingerprint_unchanged("okfalse", before)
	_assert_true("ok:false status readable", String(_client.status_message).contains("order rejected") or String(_client.status_message).contains("ok:false") or String(_client.status_message).contains("Apply failed"))


func _test_controls_restored_after_failure() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 1, "output_text": "nope", "delay_sec": 0.15},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	var ids: PackedStringArray = _client.enabled_action_button_ids()
	_assert_true("not busy after failure", not _client.is_command_busy())
	_assert_true("end_turn enabled after failure", ids.has("end_turn"))
	_assert_true("refresh enabled after failure", ids.has("refresh"))


func _test_stale_completion_ignored() -> void:
	await _setup_client()
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.35},
	]
	_client.snapshot["control"]["snapshot_path"] = _success_snapshot_path
	var commits: int = int(_client.snapshot_commit_count)
	_client._queue_and_apply([{"op": "end_turn"}])
	var live_gen: int = int(_fake.generation())
	# Stale older generation must not commit.
	_fake.force_finish_stale(
		live_gen - 1,
		0,
		"{\"ok\":true,\"results\":[]}",
		[{"op": "end_turn"}],
		_success_snapshot_path
	)
	await create_timer(0.05).timeout
	_assert_eq("stale did not commit", int(_client.snapshot_commit_count), commits)
	await _wait_until(func() -> bool: return not _client.is_command_busy())
	_assert_eq("live completion committed once", int(_client.snapshot_commit_count), commits + 1)


func _test_free_during_slow_command_safe() -> void:
	await _setup_client()
	_fake.default_delay_sec = 0.8
	_fake.scripted_results = [
		{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 0.8},
	]
	_client._queue_and_apply([{"op": "end_turn"}])
	_assert_true("busy before free", _client.is_command_busy())
	_client.queue_free()
	await create_timer(0.25).timeout
	_assert_true("free during slow command did not crash", true)
	_client = null
	_fake = null
	# Recreate for subsequent tests.
	await _setup_client()


func _test_launch_fallback_second_succeeds() -> void:
	## Real runner: first candidate cannot launch (-1), second succeeds once.
	if _client != null and is_instance_valid(_client):
		_client.queue_free()
		await create_timer(0.05).timeout
	_client = MainWritebackScript.new()
	root.add_child(_client)
	await create_timer(0.05).timeout
	_client._load_snapshot(_snapshot_path)
	var runner: Node = RealRunnerScript.new()
	_client.inject_command_runner(runner)
	var finished: Array = []
	runner.command_finished.connect(
		func(gen, success, exit_code, output_text, commands, snapshot_path) -> void:
			finished.append({
				"gen": gen,
				"success": success,
				"exit_code": exit_code,
				"output": output_text,
			})
	)
	var candidates := [
		{
			"executable": "Z:/definitely/missing/backend-fallback-a",
			"args": ["--help"],
		},
		{
			"executable": OS.get_executable_path(),
			"args": ["--version"],
		},
	]
	var start: Dictionary = runner.try_start_candidates(
		[{"op": "refresh"}],
		candidates,
		_snapshot_path
	)
	_assert_true("fallback start ok", bool(start.get("ok")), str(start))
	var ok_wait := await _wait_until(func() -> bool: return finished.size() >= 1, 8.0)
	_assert_true("fallback finished once", ok_wait and finished.size() == 1)
	if not finished.is_empty():
		_assert_eq("fallback success", bool(finished[0].get("success")), true)
		_assert_eq("fallback exit 0", int(finished[0].get("exit_code")), 0)
	_assert_true("not busy after fallback", not runner.is_busy())
