extends SceneTree

const PresenterScript = preload("res://scripts/presentation/operational_resolution_presenter.gd")

var passed := 0
var failed := 0


func _initialize() -> void:
	print("operational_resolution_presenter_test: start")
	_run_all()
	if failed > 0:
		push_error("operational_resolution_presenter_test: FAILED %s" % failed)
		quit(1)
		return
	print("operational_resolution_presenter_test: passed=%s failed=0" % passed)
	print("operational_resolution_presenter_test: PASS")
	quit(0)


func _run_all() -> void:
	_test_routed_parallel_interpolation_and_exact_endpoints()
	_test_skip_finishes_all_tracks()
	_test_direct_contact_kind_labels_and_exact_location()
	_test_ambush_uses_triggered_1150_only()
	_test_replay_is_state_neutral_and_session_only()
	_test_retreat_and_trapped_outcomes_are_authoritative()
	_test_battle_outcome_is_transient()
	_test_older_snapshot_without_s10_fields_loads()


func _graph_index() -> Dictionary:
	return {
		"nodes": {
			"n-a": {"node_id": "n-a", "pixel": [0, 0]},
			"n-b": {"node_id": "n-b", "pixel": [100, 100]},
			"n-c": {"node_id": "n-c", "pixel": [200, 0]},
		},
		"edges": {
			"e-ab": {"edge_id": "e-ab", "a": "n-a", "b": "n-b"},
			"e-bc": {"edge_id": "e-bc", "a": "n-b", "b": "n-c"},
		},
	}


func _movement(
	formation_id: String,
	start_pixel: Array,
	end_pixel: Array,
	start_node: String,
	end_node: String,
	path_nodes: Array,
	path_edges: Array
) -> Dictionary:
	return {
		"formation_id": formation_id,
		"start_position": {
			"mode": "at_node",
			"node_id": start_node,
			"edge_id": null,
			"progress_milli": 0,
			"facing_node_id": null,
		},
		"end_position": {
			"mode": "at_node",
			"node_id": end_node,
			"edge_id": null,
			"progress_milli": 0,
			"facing_node_id": null,
		},
		"start_pixel": start_pixel,
		"end_pixel": end_pixel,
		"path_node_ids": path_nodes,
		"path_edge_ids": path_edges,
	}


func _payload(movements: Array, battle_finalization: Variant = null) -> Dictionary:
	var presentation := {"movements": movements}
	if battle_finalization is Dictionary:
		presentation["battle_finalization"] = battle_finalization
	return {
		"ok": true,
		"results": [
			{
				"op": "advance_operational_tick",
				"ok": true,
				"data": {"operational_presentation": presentation},
			}
		],
	}


func _snapshot(pending: Variant = null) -> Dictionary:
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 13,
		"strategic_formations": [
			{"id": "sf-a", "display_name": "Alpha", "stance": "operational", "display_pixel": [0, 0]},
			{"id": "sf-b", "display_name": "Bravo", "stance": "entrenched", "display_pixel": [0, 20]},
			{"id": "sf-r", "display_name": "Prepared Guards", "stance": "ambush", "display_pixel": [100, 100]},
			{"id": "sf-ally", "display_name": "Allied Guards", "stance": "forced_march", "display_pixel": [100, 100]},
			{"id": "sf-refit", "display_name": "Refit Group", "stance": "refit_resupply", "display_pixel": [100, 100]},
		],
		"pending_battle": pending,
	}


func _pending(kind: String, pixel := [333, 444]) -> Dictionary:
	var edge_kind := kind in ["edge_cross", "edge_catchup"]
	return {
		"id": "battle-1",
		"encounter_kind": kind,
		"encounter_node_id": null if edge_kind else "n-b",
		"encounter_edge_id": "e-ab" if edge_kind else null,
		"encounter_progress_milli": 500 if edge_kind else null,
		"encounter_pixel": pixel,
		"attacker_faction": "nato",
		"defender_faction": "rusa",
		"attacking_participants": [
			{
				"battalion_id": "bn-a",
				"strategic_formation_id": "sf-a",
				"formation_display_name": "Alpha",
				"faction": "nato",
				"contact_initiator": true,
				"ambush_eligible": false,
				"ambush_triggered": false,
				"ambush_strength_multiplier_milli": 1000,
				"ambush_readiness_consumed": false,
			}
		],
		"defending_participants": [
			{
				"battalion_id": "bn-r",
				"strategic_formation_id": "sf-r",
				"formation_display_name": "Prepared Guards",
				"faction": "rusa",
				"contact_initiator": false,
				"ambush_eligible": true,
				"ambush_triggered": true,
				"ambush_strength_multiplier_milli": 1150,
				"ambush_readiness_consumed": true,
			},
			{
				"battalion_id": "bn-r-2",
				"strategic_formation_id": "sf-r",
				"formation_display_name": "Prepared Guards",
				"faction": "rusa",
				"contact_initiator": false,
				"ambush_eligible": true,
				"ambush_triggered": true,
				"ambush_strength_multiplier_milli": 1150,
				"ambush_readiness_consumed": true,
			},
			{
				"battalion_id": "bn-ally",
				"strategic_formation_id": "sf-ally",
				"formation_display_name": "Allied Guards",
				"faction": "rusa",
				"contact_initiator": false,
				"ambush_eligible": false,
				"ambush_triggered": false,
				"ambush_strength_multiplier_milli": 1000,
				"ambush_readiness_consumed": false,
			},
			{
				"battalion_id": "bn-refit",
				"strategic_formation_id": "sf-refit",
				"formation_display_name": "Refit Group",
				"faction": "rusa",
				"contact_initiator": false,
				"ambush_eligible": false,
				"ambush_triggered": false,
				"ambush_strength_multiplier_milli": 1000,
				"ambush_readiness_consumed": false,
			},
		],
	}


func _test_routed_parallel_interpolation_and_exact_endpoints() -> void:
	var presenter = PresenterScript.new()
	var movements := [
		_movement("sf-a", [0, 0], [200, 0], "n-a", "n-c", ["n-a", "n-b", "n-c"], ["e-ab", "e-bc"]),
		_movement("sf-b", [0, 20], [200, 20], "n-a", "n-c", ["n-a", "n-b", "n-c"], ["e-ab", "e-bc"]),
	]
	presenter.begin_transition(_snapshot(), _snapshot(), _payload(movements), _graph_index())
	_check(presenter.is_active(), "parallel transition active")
	_check_vec(presenter.display_pixel("sf-a", Vector2(200, 0)), Vector2(0, 0), "starts at backend start")
	_check_vec(presenter.display_pixel("sf-b", Vector2(200, 20)), Vector2(0, 20), "parallel starts together")
	presenter.advance(0.225)
	# Routed midpoint must pass through n-b, not direct-map Vector2(100, 0).
	_check_vec(presenter.display_pixel("sf-a", Vector2(200, 0)), Vector2(100, 100), "follows backend path midpoint")
	_check_vec(presenter.display_pixel("sf-b", Vector2(200, 20)), Vector2(100, 100), "unrelated formation not serialized")
	presenter.advance(0.225)
	_check(not presenter.is_active(), "transition complete")
	_check_vec(presenter.display_pixel("sf-a", Vector2.ZERO), Vector2(200, 0), "snaps exact endpoint a")
	_check_vec(presenter.display_pixel("sf-b", Vector2.ZERO), Vector2(200, 20), "snaps exact endpoint b")


func _test_skip_finishes_all_tracks() -> void:
	var presenter = PresenterScript.new()
	var movements := [
		_movement("sf-a", [0, 0], [100, 100], "n-a", "n-b", ["n-a", "n-b"], ["e-ab"]),
		_movement("sf-b", [0, 20], [100, 100], "n-a", "n-b", ["n-a", "n-b"], ["e-ab"]),
	]
	presenter.begin_transition(_snapshot(), _snapshot(), _payload(movements), _graph_index())
	presenter.advance(0.05)
	presenter.skip()
	_check(not presenter.is_active(), "skip clears active presentation")
	_check_vec(presenter.display_pixel("sf-a", Vector2.ZERO), Vector2(100, 100), "skip exact endpoint a")
	_check_vec(presenter.display_pixel("sf-b", Vector2.ZERO), Vector2(100, 100), "skip exact endpoint b")


func _test_direct_contact_kind_labels_and_exact_location() -> void:
	var expected := {
		"node_contact": "Node Contact",
		"node_simultaneous": "Simultaneous Node Contact",
		"edge_cross": "Edge Crossing Contact",
		"edge_catchup": "Edge Catch-up Contact",
	}
	for kind: String in expected:
		var presenter = PresenterScript.new()
		var next := _snapshot(_pending(kind))
		presenter.begin_transition(_snapshot(), next, _payload([]), _graph_index())
		var contact: Dictionary = presenter.contact_model()
		_check_eq(contact.get("kind", ""), kind, "%s reads backend kind" % kind)
		_check_eq(contact.get("label", ""), expected[kind], "%s visible label" % kind)
		_check_vec(contact.get("encounter_pixel", Vector2.ZERO), Vector2(333, 444), "%s exact encounter pixel" % kind)


func _test_ambush_uses_triggered_1150_only() -> void:
	var presenter = PresenterScript.new()
	presenter.begin_transition(_snapshot(), _snapshot(_pending("node_contact")), _payload([]), _graph_index())
	var contact: Dictionary = presenter.contact_model()
	var ambush: Array = contact.get("ambush", [])
	_check_eq(ambush.size(), 1, "one strategic formation receives Ambush presentation")
	_check_eq(ambush[0].get("formation_id", ""), "sf-r", "Ambush remains on triggered formation")
	_check_eq(ambush[0].get("multiplier_milli", 0), 1150, "reads exact 1150")
	_check_eq(ambush[0].get("effect_label", ""), "+15%", "shows fixed 1150 label")
	var participant_ids: Array = contact.get("participant_formation_ids", [])
	_check(participant_ids.has("sf-a"), "ordinary initiator participates without Ambush")
	_check(participant_ids.has("sf-ally"), "Forced March participant not mislabeled")
	_check(participant_ids.has("sf-refit"), "Refit participant not mislabeled")


func _test_replay_is_state_neutral_and_session_only() -> void:
	var presenter = PresenterScript.new()
	var pending := _pending("edge_cross")
	var next := _snapshot(pending)
	var movement := _movement("sf-a", [0, 0], [333, 444], "n-a", "n-b", ["n-a", "n-b"], ["e-ab"])
	var before_bytes := JSON.stringify(next)
	presenter.begin_transition(_snapshot(), next, _payload([movement]), _graph_index())
	presenter.skip()
	_check(presenter.can_replay_last_contact(), "contact becomes replayable")
	_check(presenter.replay_last_contact(), "replay starts without backend")
	_check_eq(JSON.stringify(next), before_bytes, "replay leaves snapshot bytes unchanged")
	presenter.begin_session(next, _graph_index())
	_check(not presenter.can_replay_last_contact(), "fresh session clears replay")
	_check(not presenter.replay_last_contact(), "fresh session replay unavailable")


func _test_retreat_and_trapped_outcomes_are_authoritative() -> void:
	var presenter = PresenterScript.new()
	var retreat := {
		"winner": "rusa",
		"retreat_outcomes": [
			{
				"formation_id": "sf-a",
				"destination_node_id": "n-a",
				"destination_province_id": "a",
				"destination_pixel": [0, 0],
				"reason": "",
			}
		],
	}
	presenter.begin_transition(_snapshot(_pending("node_contact")), _snapshot(), _payload([], retreat), _graph_index())
	var outcome: Dictionary = presenter.transient_outcome()
	_check_eq(outcome.get("winner", ""), "rusa", "retreat winner authoritative")
	_check_eq(outcome.get("retreat_outcomes", [])[0].get("destination_node_id", ""), "n-a", "retreat node authoritative")
	_check_vec(outcome.get("retreat_outcomes", [])[0].get("destination_pixel", Vector2.INF), Vector2(0, 0), "retreat pixel authoritative")

	var trapped := {
		"winner": "rusa",
		"retreat_outcomes": [
			{
				"formation_id": "sf-a",
				"destination_node_id": null,
				"destination_province_id": null,
				"destination_pixel": null,
				"reason": "trapped_no_legal_retreat",
			}
		],
	}
	presenter.begin_transition(_snapshot(_pending("node_contact")), _snapshot(), _payload([], trapped), _graph_index())
	outcome = presenter.transient_outcome()
	var trapped_row: Dictionary = outcome.get("retreat_outcomes", [])[0]
	_check_eq(trapped_row.get("reason", ""), "trapped_no_legal_retreat", "trapped reason exact")
	_check(not trapped_row.has("destination_pixel") or trapped_row.get("destination_pixel") == null, "trapped invents no destination")


func _test_battle_outcome_is_transient() -> void:
	var presenter = PresenterScript.new()
	var finalization := {
		"winner": "rusa",
		"retreat_outcomes": [{"formation_id": "sf-a", "reason": "trapped_no_legal_retreat"}],
	}
	presenter.begin_transition(_snapshot(_pending("node_contact")), _snapshot(), _payload([], finalization), _graph_index())
	_check(not presenter.transient_outcome().is_empty(), "battle outcome begins visible")
	presenter.advance(3.0)
	_check(presenter.transient_outcome().is_empty(), "battle outcome expires without another command")


func _test_older_snapshot_without_s10_fields_loads() -> void:
	var presenter = PresenterScript.new()
	var legacy := {
		"schema": "gates-of-codex.frontend",
		"schema_version": 12,
		"strategic_formations": [],
		"pending_battle": {
			"id": "legacy",
			"encounter_kind": "node_contact",
			"encounter_node_id": "n-b",
			"encounter_pixel": [],
		},
	}
	presenter.begin_session(legacy, _graph_index())
	_check(not presenter.can_replay_last_contact(), "legacy snapshot has no replay")
	_check_eq(presenter.contact_model().get("kind", ""), "node_contact", "legacy pending battle still presents")
	_check_eq(presenter.contact_model().get("participant_formation_ids", []).size(), 0, "missing rows remain optional")


func _check(condition: bool, label: String) -> void:
	if condition:
		passed += 1
		print("  ok %s" % label)
		return
	failed += 1
	push_error("  FAIL %s" % label)


func _check_eq(actual: Variant, expected: Variant, label: String) -> void:
	_check(actual == expected, "%s expected=%s actual=%s" % [label, expected, actual])


func _check_vec(actual: Variant, expected: Vector2, label: String) -> void:
	var value := actual as Vector2 if actual is Vector2 else Vector2.INF
	_check(value.distance_to(expected) < 0.01, "%s expected=%s actual=%s" % [label, expected, value])
