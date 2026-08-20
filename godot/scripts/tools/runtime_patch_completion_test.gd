extends SceneTree

const HostScript = preload("res://scripts/tools/runtime_patch_completion_host.gd")

var _failed := 0
var _passed := 0


func _initialize() -> void:
	print("runtime_patch_completion_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	_test_successful_move_batch()
	_test_blocked_move_batch()
	_test_auto_resolve()
	print("runtime_patch_completion_test: passed=%s failed=%s" % [_passed, _failed])
	if _failed > 0:
		push_error("runtime_patch_completion_test FAIL")
		quit(1)
		return
	print("runtime_patch_completion_test: PASS")
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


func _base_snapshot() -> Dictionary:
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 13,
		"campaign": {
			"turn_number": 1,
			"current_faction": "nato",
			"selected_faction": "nato",
		},
		"provinces": [
			{"id": "a", "x": 0, "y": 0},
			{"id": "b", "x": 100, "y": 0},
		],
		"formations": [],
		"factions": [{"id": "nato"}, {"id": "rusa"}],
		"battalions": [
			{"id": "bn-n", "strategic_formation_id": "sf-n", "province_id": "a", "faction": "nato"},
			{"id": "bn-r", "strategic_formation_id": "sf-r", "province_id": "b", "faction": "rusa"},
		],
		"battalion_stacks": {"a": ["bn-n"], "b": ["bn-r"]},
		"stack_presentations": {
			"a": {"strategic_formation_ids": ["sf-n"]},
			"b": {"strategic_formation_ids": ["sf-r"]},
		},
		"strategic_formations": [
			{
				"id": "sf-n",
				"faction": "nato",
				"province_id": "a",
				"position": {"mode": "at_node", "node_id": "n-a"},
				"move_order": null,
			},
			{
				"id": "sf-r",
				"faction": "rusa",
				"province_id": "b",
				"position": {"mode": "at_node", "node_id": "n-b"},
				"move_order": null,
			},
		],
		"front_options": [],
		"operational_orders": [
			{
				"formation_id": "sf-n",
				"origin_province_id": "a",
				"target_province_id": "b",
				"path_node_ids": ["n-a", "n-b"],
				"path_edge_ids": ["e-ab"],
			}
		],
		"pending_battle": null,
		"objectives": [],
		"commanders": [],
		"control": {"enabled": true},
	}


func _committed_order() -> Dictionary:
	return {
		"status": "committed",
		"committed_turn": 1,
		"locked_stance": "operational",
		"path_node_ids": ["n-a", "n-b"],
		"path_edge_ids": ["e-ab"],
	}


func _blocked_order() -> Dictionary:
	return {
		"status": "blocked",
		"committed_turn": null,
		"locked_stance": "refit_resupply",
		"path_node_ids": ["n-a", "n-b"],
		"path_edge_ids": ["e-ab"],
	}


func _patch_for_order(order: Variant, pending = null) -> Dictionary:
	var snap := _base_snapshot()
	var forces: Array = snap["strategic_formations"]
	(forces[0] as Dictionary)["move_order"] = order
	return {
		"schema": "gates-of-codex.frontend-runtime-patch",
		"schema_version": 1,
		"merge": {
			"application": {},
			"campaign": {"turn_number": 1, "current_faction": "nato", "selected_faction": "nato"},
			"provinces": snap["provinces"],
			"formations": [],
		},
		"replace": {
			"factions": snap["factions"],
			"objectives": [],
			"strategic_formations": forces,
			"commanders": [],
			"battalions": snap["battalions"],
			"battalion_stacks": snap["battalion_stacks"],
			"stack_presentations": {
				"a": {"strategic_formation_ids": ["sf-n"]},
				"b": {"strategic_formation_ids": ["sf-r"]},
			},
			"battalion_presentations": {},
			"strategic_formation_presentations": {},
			"pending_battle": pending,
			"front_options": [],
			"operational_orders": snap["operational_orders"],
			"control": {"enabled": true},
			"fog_of_war": {"enabled": false},
			"last_known_contacts": [],
		},
	}


func _payload(op: String, patch: Dictionary, extra_data: Dictionary = {}) -> String:
	var data := extra_data.duplicate(true)
	data["operational_presentation"] = {
		"movements": [],
		"battle_finalization": extra_data.get("battle_finalization", {}),
	}
	return JSON.stringify({
		"ok": true,
		"results": [{"op": op, "ok": true, "data": data}],
		"frontend_patch": patch,
		"timings": {"total_ms": 1.0, "runtime_patch_fast_path": true},
	})


func _make_scene(snapshot: Dictionary) -> Node:
	var scene: Node = HostScript.new()
	root.add_child(scene)
	scene.snapshot = snapshot.duplicate(true)
	scene.selected_province_id = "a"
	scene.selected_strategic_formation_id = "sf-n"
	scene.view_scale = 2.5
	scene.view_offset = Vector2(11, 17)
	scene.fitted_once = true
	scene.snapshot_source_path = "user://runtime_patch_completion_unused.json"
	return scene


func _force(scene: Node, formation_id: String) -> Dictionary:
	for row_variant: Variant in scene.snapshot.get("strategic_formations", []):
		if row_variant is Dictionary and String((row_variant as Dictionary).get("id", "")) == formation_id:
			return row_variant as Dictionary
	return {}


func _test_successful_move_batch() -> void:
	var scene := _make_scene(_base_snapshot())
	var commands := [
		{"op": "issue_move_order", "formation": "sf-n"},
		{"op": "commit_move_orders", "faction": "nato", "locked_stance": "operational"},
	]
	var order := _committed_order()
	scene._on_command_finished(
		1,
		true,
		0,
		_payload("issue_move_order", _patch_for_order(order)),
		commands,
		""
	)
	var got: Variant = _force(scene, "sf-n").get("move_order")
	_assert_true("success uses runtime patch path", scene.full_snapshot_loads == 0, str(scene.full_snapshot_loads))
	_assert_true("success order is dict", got is Dictionary)
	if got is Dictionary:
		_assert_eq("success status", String(got.get("status", "")), "committed")
		_assert_eq("success committed_turn", int(got.get("committed_turn", -1)), 1)
		_assert_eq("success locked_stance", String(got.get("locked_stance", "")), "operational")
		_assert_eq("success nodes", got.get("path_node_ids"), ["n-a", "n-b"])
		_assert_eq("success edges", got.get("path_edge_ids"), ["e-ab"])
		_assert_true("success not draft", String(got.get("status", "")) != "draft")
	else:
		_fail("success not draft", "missing move_order")
	var targets: Variant = scene.legal_targets
	_assert_true(
		"success legal targets rebuilt",
		targets is Dictionary and (targets as Dictionary).has("b"),
		str(targets)
	)
	_assert_eq("success view_scale", scene.view_scale, 2.5)
	_assert_eq("success view_offset", scene.view_offset, Vector2(11, 17))
	scene.queue_free()


func _test_blocked_move_batch() -> void:
	var scene := _make_scene(_base_snapshot())
	var commands := [
		{"op": "issue_move_order", "formation": "sf-n"},
		{"op": "commit_move_orders", "faction": "nato", "locked_stance": "refit_resupply"},
	]
	var order := _blocked_order()
	scene._on_command_finished(
		1,
		true,
		0,
		_payload("issue_move_order", _patch_for_order(order)),
		commands,
		""
	)
	var got: Variant = _force(scene, "sf-n").get("move_order")
	_assert_true("blocked uses runtime patch path", scene.full_snapshot_loads == 0)
	_assert_true("blocked order is dict", got is Dictionary)
	if got is Dictionary:
		_assert_eq("blocked status", String(got.get("status", "")), "blocked")
		_assert_true("blocked is not draft", String(got.get("status", "")) != "draft")
		_assert_eq("blocked stance", String(got.get("locked_stance", "")), "refit_resupply")
	_assert_eq("blocked view_scale", scene.view_scale, 2.5)
	_assert_eq("blocked view_offset", scene.view_offset, Vector2(11, 17))
	scene.queue_free()


func _test_auto_resolve() -> void:
	var before := _base_snapshot()
	before["pending_battle"] = {
		"id": "battle-1",
		"started": false,
		"attacker_faction": "nato",
		"defender_faction": "rusa",
	}
	var scene := _make_scene(before)
	_assert_true("auto-resolve starts with modal", scene.is_pending_battle_modal_active())
	var retreat := {
		"winner": "nato",
		"retreat_outcomes": [
			{"formation_id": "sf-r", "destination_pixel": [80, 10]}
		],
	}
	var patch := _patch_for_order(null, null)
	(patch["replace"]["strategic_formations"][1] as Dictionary)["province_id"] = "b"
	scene._on_command_finished(
		1,
		true,
		0,
		_payload("auto_resolve", patch, {"winner": "nato", "battle_finalization": retreat}),
		[{"op": "auto_resolve"}],
		""
	)
	_assert_true("auto-resolve uses runtime patch path", scene.full_snapshot_loads == 0)
	_assert_true("pending_battle cleared", scene.snapshot.get("pending_battle") == null)
	_assert_true("modal gone", not scene.is_pending_battle_modal_active())
	_assert_true("map unblocked", not scene.is_map_interaction_blocked())
	var outcome: Variant = scene.operational_presenter.get("_outcome")
	_assert_true("finalization reached presenter", outcome is Dictionary and String((outcome as Dictionary).get("winner", "")) == "nato")
	_assert_true(
		"retreat accepted",
		outcome is Dictionary and (outcome as Dictionary).get("retreat_outcomes", []).size() == 1
	)
	_assert_true("indexes rebuilt", scene.orders_by_formation.has("sf-n"))
	_assert_eq("auto-resolve view_scale", scene.view_scale, 2.5)
	_assert_eq("auto-resolve view_offset", scene.view_offset, Vector2(11, 17))
	scene.queue_free()
