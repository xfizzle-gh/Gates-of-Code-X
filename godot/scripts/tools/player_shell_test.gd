extends SceneTree

## P4 player-shell headless contract test.
##
## Imports a generated production snapshot into the real player scene script and
## proves the shell exposes the required player-facing surface: Earth3 resolves
## as a first-class production map, New/Continue Campaign are visible actions,
## scenario/faction/turn/version/save-path are readable, and controls that cause
## authoritative mutation guard themselves while a mutation is in flight.
##
## godot --headless --path godot -s res://scripts/tools/player_shell_test.gd -- \
##   --snapshot=<generated production snapshot>

const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")
const MainScene = preload("res://main.tscn")

const EARTH3_MAP_ID := "earth3_europe_mediterranean"
const LEGACY_MAP_IDS := [
	"goe_europe_alpha_graph_v1",
	"goe_europe",
	"interim_goe_europe",
	"europe_mediterranean_from_goe",
]

var _failed := 0
var _passed := 0
var _client: Node


func _initialize() -> void:
	print("player_shell_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	var path := _snapshot_path()
	if path.is_empty():
		push_error("player_shell_test requires --snapshot=<generated snapshot>")
		quit(2)
		return

	_client = MainScene.instantiate()
	_client.name = "PlayerShellClient"
	root.add_child(_client)
	await create_timer(0.05).timeout

	_client.snapshot_source_path = path
	_client._load_snapshot(path)
	_assert_true(
		"snapshot_loads",
		String(_client.load_error).is_empty(),
		String(_client.load_error)
	)
	var snapshot: Dictionary = _client.snapshot
	_assert_true("snapshot_not_empty", not snapshot.is_empty(), "snapshot is empty")

	_verify_production_map(snapshot)
	_verify_player_identity(snapshot)
	_verify_player_actions(snapshot)
	await _verify_mutation_guard()

	_client.queue_free()
	await create_timer(0.05).timeout

	print("player_shell_test: passed=%s failed=%s" % [_passed, _failed])
	if _failed > 0:
		push_error("player_shell_test FAIL")
		quit(1)
		return
	print("player_shell_test: PASS")
	quit(0)


func _snapshot_path() -> String:
	for raw in OS.get_cmdline_user_args():
		var text := String(raw)
		if text.begins_with("--snapshot="):
			return text.substr(String("--snapshot=").length()).strip_edges()
	return ""


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


func _verify_production_map(snapshot: Dictionary) -> void:
	var campaign: Dictionary = snapshot.get("campaign", {})
	var strategic_map: Dictionary = snapshot.get("strategic_map", {})
	_assert_true(
		"campaign_map_is_earth3",
		String(campaign.get("map_id", "")) == EARTH3_MAP_ID,
		String(campaign.get("map_id", ""))
	)
	_assert_true(
		"strategic_map_is_earth3",
		String(strategic_map.get("map_id", "")) == EARTH3_MAP_ID,
		String(strategic_map.get("map_id", ""))
	)
	_assert_true(
		"no_production_fallback",
		String(strategic_map.get("fallback", "")) == "none",
		String(strategic_map.get("fallback", ""))
	)
	var available: Array = strategic_map.get("available_map_ids", [])
	_assert_true(
		"earth3_is_the_only_production_map",
		available.size() == 1 and String(available[0]) == EARTH3_MAP_ID,
		str(available)
	)
	var legacy_offered := false
	for legacy in LEGACY_MAP_IDS:
		if available.has(legacy) or String(strategic_map.get("map_id", "")) == legacy:
			legacy_offered = true
	_assert_true("no_legacy_goe_map_in_production", not legacy_offered, str(available))


func _verify_player_identity(snapshot: Dictionary) -> void:
	var application: Dictionary = snapshot.get("application", {})
	var campaign: Dictionary = snapshot.get("campaign", {})
	_assert_true(
		"application_version_present",
		not String(application.get("version", "")).strip_edges().is_empty()
	)
	var commit := String(application.get("source_commit", ""))
	var commit_pattern := RegEx.new()
	commit_pattern.compile("^[0-9a-f]{40}$")
	_assert_true(
		"exact_source_commit_present",
		commit_pattern.search(commit) != null,
		commit
	)
	var scenario_id := String(application.get("scenario_id", ""))
	_assert_true(
		"scenario_is_2028_core_or_earth3_fixture",
		scenario_id == "ww3_2028_core" or scenario_id == "earth3_v1",
		scenario_id
	)
	_assert_true(
		"scenario_status_present",
		not String(application.get("scenario_status", "")).strip_edges().is_empty(),
		String(application.get("scenario_status", ""))
	)
	_assert_true(
		"save_path_present",
		not String(application.get("campaign_path", "")).strip_edges().is_empty()
	)
	_assert_true(
		"selected_faction_present",
		not String(campaign.get("selected_faction", "")).strip_edges().is_empty()
	)
	_assert_true("strategic_turn_present", int(campaign.get("turn_number", -1)) >= 0)


func _verify_player_actions(snapshot: Dictionary) -> void:
	var play: Dictionary = _client.player_launch_block()
	_assert_true("player_launch_enabled", bool(play.get("enabled", false)))
	_assert_true(
		"new_campaign_arguments_present",
		not (play.get("new_args", []) as Array).is_empty()
	)
	_assert_true(
		"continue_campaign_arguments_present",
		not (play.get("continue_args", []) as Array).is_empty()
	)
	_assert_true("new_campaign_available", _client.can_start_new_campaign())
	_assert_true("continue_campaign_available", _client.can_continue_campaign())

	# A production snapshot can begin with an operational presentation in flight.
	# State-mutating maintenance controls must stay hidden until that lifecycle is
	# complete, so finish it before checking the idle player controls.
	if _client.operational_presenter != null and _client.operational_presenter.is_active():
		_client._handle_button("skip_presentation")
	var ids: PackedStringArray = _client.enabled_action_button_ids()
	_assert_true("new_campaign_button_exposed", ids.has("new_campaign"), str(ids))
	_assert_true("continue_campaign_button_exposed", ids.has("continue_campaign"), str(ids))
	_assert_true("reset_campaign_button_exposed", ids.has("reset_test_campaign"), str(ids))
	var maintenance: Dictionary = snapshot.get("control", {}).get("maintenance", {})
	_assert_true(
		"restore_matches_authenticated_backup_availability",
		ids.has("restore_backup") == bool(maintenance.get("restore_available", false)),
		str(maintenance)
	)

	# New Campaign replaces authoritative state and must confirm before running.
	_client._handle_button("new_campaign")
	_assert_true(
		"new_campaign_requires_confirmation",
		bool(_client.new_campaign_confirm_pending)
	)
	_client._handle_button("fit")
	_assert_true(
		"new_campaign_confirmation_cleared",
		not bool(_client.new_campaign_confirm_pending)
	)

	var control: Dictionary = snapshot.get("control", {})
	var supported: Array = control.get("supported_ops", [])
	var missing: Array = []
	for required in [
		"move",
		"issue_move_order",
		"cancel_move_order",
		"commit_move_orders",
		"end_turn",
		"run_ai",
		"auto_resolve",
	]:
		if not supported.has(required):
			missing.append(required)
	_assert_true("operational_ops_supported", missing.is_empty(), str(missing))


func _verify_mutation_guard() -> void:
	var runner = FakeRunnerScript.new()
	runner.scripted_results = [{"exit_code": 0, "output_text": "{\"ok\":true,\"results\":[]}", "delay_sec": 30.0}]
	_client.inject_command_runner(runner)
	await create_timer(0.05).timeout

	var started: Dictionary = runner.try_start_candidates(
		[{"op": "end_turn"}],
		[{"executable": "fake-backend", "args": []}],
		String(_client.snapshot_source_path)
	)
	_assert_true("in_flight_command_started", bool(started.get("ok", false)), str(started))
	_assert_true("client_reports_busy", _client.is_command_busy())

	var ids: PackedStringArray = _client.enabled_action_button_ids()
	var still_enabled: Array = []
	for guarded in ["end_turn", "run_ai", "refresh", "new_campaign", "continue_campaign", "restore_backup", "reset_test_campaign"]:
		if ids.has(guarded):
			still_enabled.append(guarded)
	_assert_true(
		"mutating_controls_guarded_while_in_flight",
		still_enabled.is_empty(),
		str(still_enabled)
	)
	_assert_true("new_campaign_blocked_while_in_flight", not _client.can_start_new_campaign())
	_assert_true("continue_campaign_blocked_while_in_flight", not _client.can_continue_campaign())

	runner.in_flight["active"] = false
	_assert_true("controls_restored_after_completion", not _client.is_command_busy())
	var restored: PackedStringArray = _client.enabled_action_button_ids()
	_assert_true(
		"new_campaign_restored",
		restored.has("new_campaign"),
		str(restored)
	)
