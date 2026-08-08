extends SceneTree

const MainScript = preload("res://scripts/main_stack_panel.gd")
const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")
const MapMarkersScript = preload("res://scripts/presentation/map_markers.gd")

var passed := 0
var failed := 0


func _initialize() -> void:
	print("operational_presentation_scene_test: start")
	_run_all()
	if failed > 0:
		push_error("operational_presentation_scene_test: FAILED %s" % failed)
		quit(1)
		return
	print("operational_presentation_scene_test: passed=%s failed=0" % passed)
	print("operational_presentation_scene_test: PASS")
	quit(0)


func _run_all() -> void:
	var main_script: GDScript = MainScript
	if main_script == null or not main_script.can_instantiate():
		failed += 1
		push_error("  FAIL active main scene script cannot instantiate")
		return
	var scene = MainScript.new()
	var runner = FakeRunnerScript.new()
	if not scene.has_method("_ensure_operational_presenter"):
		failed += 1
		push_error("  FAIL active scene has no S10 presenter integration")
		scene.free()
		runner.free()
		return
	scene.command_runner = runner
	scene.snapshot = _pending_snapshot()
	scene.last_handoff_save_path = "completed.sav"
	scene.last_handoff_battle_id = "unrelated-battle"
	scene._ensure_operational_presenter()
	scene.operational_presenter.begin_session(scene.snapshot, _graph_index())

	_check(scene.is_pending_battle_modal_active(), "pending battle opens modal gate")
	_check(scene.is_map_interaction_blocked(), "modal blocks map interaction")
	_check(not Array(scene.enabled_action_button_ids()).has("import_battle"), "unrelated handoff cannot expose import")
	scene.last_handoff_battle_id = "battle-1"
	var initial_actions: Array = Array(scene.enabled_action_button_ids())
	_check(initial_actions.has("auto_resolve"), "modal keeps existing proceed action")
	_check(initial_actions.has("handoff"), "modal keeps existing handoff action")
	_check(initial_actions.has("import_battle"), "handed-off modal exposes verified import action")
	_check(not initial_actions.has("end_turn"), "modal blocks end turn")
	_check(not initial_actions.has("run_ai"), "modal blocks AI resolution")
	_check(not initial_actions.has("refresh"), "modal blocks refresh interaction")
	_check(not initial_actions.has("replay_contact"), "fresh session has no replay")
	var modal: Dictionary = scene.pending_battle_modal_model()
	_check_eq(modal.get("contact_label", ""), "Edge Crossing Contact", "modal uses direct contact-kind label")
	_check_eq(modal.get("attacker_names", []), ["Alpha"], "modal names attacking formation")
	_check_eq(modal.get("defender_names", []), ["Red"], "modal names defending formation")
	_check_eq(modal.get("ambush_lines", []), ["Red: Ambush +15%"], "modal shows only triggered Ambush metadata")

	var before_bytes := JSON.stringify(scene.snapshot)
	var movement := {
		"formation_id": "sf-a",
		"start_position": {"mode": "at_node", "node_id": "n-a", "edge_id": null, "progress_milli": 0, "facing_node_id": null},
		"end_position": {"mode": "on_edge", "node_id": null, "edge_id": "e-ab", "progress_milli": 500, "facing_node_id": "n-b"},
		"start_pixel": [0, 0],
		"end_pixel": [50, 50],
		"path_node_ids": ["n-a", "n-b"],
		"path_edge_ids": ["e-ab"],
	}
	var payload := {
		"ok": true,
		"results": [{"op": "advance_operational_tick", "ok": true, "data": {"operational_presentation": {"movements": [movement]}}}],
	}
	scene.operational_presenter.begin_transition({}, scene.snapshot, payload, _graph_index())
	var actions: Array = Array(scene.enabled_action_button_ids())
	_check(actions.has("replay_contact"), "modal enables session replay")
	_check(actions.has("skip_presentation"), "active presentation exposes Skip")

	# This is the actual strategic-map counter style resolver used by the draw path.
	# It consumes ordinary snapshot battalion/strategic-formation rows, not the
	# presentation_formations screenshot shortcut.
	var moving_baseline: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene,
		Vector2(50, 50),
		Color("4f8fd8"),
		"T",
		4,
		false,
		true
	)
	var moving_overlay: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene,
		Vector2(25, 25),
		Color("4f8fd8"),
		"T",
		4,
		true,
		true
	)
	var stationary_participant: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene,
		Vector2(50, 50),
		Color("c95b5b"),
		"I",
		3,
		false,
		true
	)
	var moving_visible_count := int(bool(moving_baseline.get("visible", true))) \
		+ int(bool(moving_overlay.get("visible", true)))
	_check_eq(moving_visible_count, 1, "moving formation has exactly one visible counter")
	_check(not bool(moving_baseline.get("visible", true)), "authoritative endpoint baseline is suppressed")
	_check(bool(stationary_participant.get("visible", false)), "stationary participant remains visible")
	_check(bool(stationary_participant.get("emphasized", false)), "stationary participant is emphasized")
	_check_eq(stationary_participant.get("formation_id", ""), "sf-r", "stationary emphasis resolves real formation row")

	scene._handle_button("replay_contact")
	_check_eq(runner.start_count, 0, "replay issues no command")
	_check_eq(JSON.stringify(scene.snapshot), before_bytes, "replay leaves snapshot bytes unchanged")
	scene._handle_button("end_turn")
	_check_eq(runner.start_count, 0, "modal rejects operational command")
	scene._issue_move("b")
	_check_eq(runner.start_count, 0, "modal rejects map order")
	scene._handle_button("skip_presentation")
	_check(not scene.operational_presenter.is_active(), "Skip completes active presentation")
	_check_eq(JSON.stringify(scene.snapshot), before_bytes, "Skip leaves snapshot bytes unchanged")

	scene.free()
	runner.free()


func _pending_snapshot() -> Dictionary:
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 13,
		"control": {
			"enabled": true,
			"campaign_path": "campaign.json",
			"snapshot_path": "snapshot.json",
			"commands_path": "commands.json",
		},
		"campaign": {"current_faction": "nato", "selected_faction": "nato"},
		"battalions": [
			{
				"id": "bn-a",
				"strategic_formation_id": "sf-a",
				"province_id": "a",
				"faction": "nato",
				"battalion_type": "tank",
				"unit_count": 4,
				"display_pixel": [50, 50],
			},
			{
				"id": "bn-r",
				"strategic_formation_id": "sf-r",
				"province_id": "b",
				"faction": "rusa",
				"battalion_type": "infantry",
				"unit_count": 3,
				"display_pixel": [50, 50],
			},
		],
		"strategic_formations": [
			{"id": "sf-a", "display_name": "Alpha", "faction": "nato", "display_pixel": [50, 50]},
			{"id": "sf-r", "display_name": "Red", "faction": "rusa", "display_pixel": [50, 50]},
		],
		"pending_battle": {
			"id": "battle-1",
			"started": true,
			"encounter_kind": "edge_cross",
			"encounter_node_id": "",
			"encounter_edge_id": "e-ab",
			"encounter_progress_milli": 500,
			"encounter_pixel": [50, 50],
			"attacker_faction": "nato",
			"defender_faction": "rusa",
			"attacking_participants": [
				{"battalion_id": "bn-a", "strategic_formation_id": "sf-a", "formation_display_name": "Alpha", "faction": "nato", "contact_initiator": true, "ambush_triggered": false, "ambush_strength_multiplier_milli": 1000}
			],
			"defending_participants": [
				{"battalion_id": "bn-r", "strategic_formation_id": "sf-r", "formation_display_name": "Red", "faction": "rusa", "contact_initiator": false, "ambush_triggered": true, "ambush_strength_multiplier_milli": 1150}
			],
		},
	}


func _graph_index() -> Dictionary:
	return {
		"nodes": {
			"n-a": {"pixel": [0, 0]},
			"n-b": {"pixel": [100, 100]},
		},
		"edges": {
			"e-ab": {"edge_id": "e-ab", "a": "n-a", "b": "n-b"},
		},
	}


func _check(condition: bool, label: String) -> void:
	if condition:
		passed += 1
		print("  ok %s" % label)
		return
	failed += 1
	push_error("  FAIL %s" % label)


func _check_eq(actual: Variant, expected: Variant, label: String) -> void:
	_check(actual == expected, "%s expected=%s actual=%s" % [label, expected, actual])
