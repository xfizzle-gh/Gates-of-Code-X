extends SceneTree

## #218 interaction/presentation regression for the production top-level map layer.

const MainScript = preload("res://scripts/main_order_controls.gd")
const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")

var passed := 0
var failed := 0


func _initialize() -> void:
	print("map_order_controls_test: start")
	_test_left_select_never_dispatches()
	_test_right_click_dispatches_exactly_once()
	_test_right_click_without_selection_or_route_dispatches_nothing()
	_test_persisted_route_uses_exact_node_and_edge_ids()
	_test_fast_patch_replaces_and_cancels_route_once()
	_test_contact_blocked_order_is_labeled_interrupted()
	_test_source_locks_mouse_split()
	if failed > 0:
		push_error("map_order_controls_test: FAILED %s" % failed)
		quit(1)
		return
	print("map_order_controls_test: passed=%s failed=0" % passed)
	print("map_order_controls_test: PASS")
	quit(0)


func _work_dir(name: String) -> String:
	var dir := OS.get_user_data_dir().path_join(name)
	DirAccess.make_dir_recursive_absolute(dir)
	return dir


func _scene(name: String) -> Dictionary:
	var scene = MainScript.new()
	var runner = FakeRunnerScript.new()
	scene.command_runner = runner
	var dir := _work_dir(name)
	var commands_path := dir.path_join("frontend_commands.json")
	if FileAccess.file_exists(commands_path):
		DirAccess.remove_absolute(commands_path)
	scene.snapshot = _snapshot(dir, commands_path)
	scene.provinces_by_id = {
		"prov-a": scene.snapshot["provinces"][0],
		"prov-b": scene.snapshot["provinces"][1],
		"prov-c": scene.snapshot["provinces"][2],
	}
	var indexed: Dictionary = scene.index_operational_orders(scene.snapshot)
	scene.orders_by_formation = indexed.get("by_formation", {})
	scene.order_formations_by_province = indexed.get("by_province", {})
	scene.selected_province_id = "prov-a"
	scene.selected_strategic_formation_id = "sf-a"
	scene._rebuild_legal_targets()
	scene.operational_graph.is_ready = true
	scene.operational_graph.index = {
		"nodes": {
			"node-a": {"node_id": "node-a", "pixel": [10, 20]},
			"node-b": {"node_id": "node-b", "pixel": [30, 20]},
			"node-c": {"node_id": "node-c", "pixel": [50, 25]},
		},
		"edges": {
			"edge-ab": {"edge_id": "edge-ab", "a": "node-a", "b": "node-b"},
			"edge-bc": {"edge_id": "edge-bc", "a": "node-b", "b": "node-c"},
		},
	}
	return {"scene": scene, "runner": runner, "commands_path": commands_path}


func _queued_commands(path: String) -> Array:
	if not FileAccess.file_exists(path):
		return []
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		return []
	return (parsed as Dictionary).get("commands", [])


func _test_left_select_never_dispatches() -> void:
	var ctx := _scene("p8_218_left")
	var scene = ctx["scene"]
	scene._select_from_map("prov-c")
	_check_eq(scene.selected_province_id, "prov-c", "left-click selection changes selected province")
	_check_eq(scene.order_dispatch_count, 0, "selection path never increments order dispatch")
	_check(not FileAccess.file_exists(ctx["commands_path"]), "selection path writes no command file")
	_free(ctx)


func _test_right_click_dispatches_exactly_once() -> void:
	var ctx := _scene("p8_218_right")
	var scene = ctx["scene"]
	scene._order_from_map("prov-c")
	_check_eq(scene.order_dispatch_count, 1, "valid right-click order intent dispatches once")
	var rows := _queued_commands(ctx["commands_path"])
	_check_eq(rows.size(), 2, "right-click queues one draft+commit batch")
	if rows.size() == 2:
		_check_eq(String((rows[0] as Dictionary).get("op", "")), "issue_move_order", "right-click uses graph move op")
		_check_eq((rows[0] as Dictionary).get("path_node_ids", []), ["node-a", "node-b", "node-c"], "right-click preserves exact nodes")
		_check_eq((rows[0] as Dictionary).get("path_edge_ids", []), ["edge-ab", "edge-bc"], "right-click preserves exact edges")
	_free(ctx)


func _test_right_click_without_selection_or_route_dispatches_nothing() -> void:
	var ctx := _scene("p8_218_invalid")
	var scene = ctx["scene"]
	scene.selected_strategic_formation_id = ""
	scene._order_from_map("prov-c")
	_check_eq(scene.order_dispatch_count, 0, "right-click without selection dispatches nothing")
	_check(not FileAccess.file_exists(ctx["commands_path"]), "no-selection right-click writes no commands")
	scene.selected_province_id = "prov-a"
	scene.selected_strategic_formation_id = "sf-a"
	scene._rebuild_legal_targets()
	scene._order_from_map("prov-bad")
	_check_eq(scene.order_dispatch_count, 0, "illegal destination dispatches nothing")
	_check(String(scene.status_message).begins_with("Illegal destination:"), "illegal destination gives an explicit reason")
	_free(ctx)


func _test_persisted_route_uses_exact_node_and_edge_ids() -> void:
	var ctx := _scene("p8_218_route")
	var scene = ctx["scene"]
	var order := {
		"formation_id": "sf-a",
		"status": "committed",
		"path_node_ids": ["node-a", "node-b", "node-c"],
		"path_edge_ids": ["edge-ab", "edge-bc"],
	}
	(scene.snapshot["strategic_formations"][0] as Dictionary)["move_order"] = order
	var points: PackedVector2Array = scene._authoritative_route_map_pixels(order)
	_check_eq(points.size(), 3, "persisted queued route resolves every authoritative node")
	if points.size() == 3:
		_check_eq(points[0], Vector2(10, 20), "route begins at exact node-a pixel")
		_check_eq(points[2], Vector2(50, 25), "route ends at exact node-c pixel")
	var tampered := order.duplicate(true)
	tampered["path_edge_ids"] = ["edge-bc", "edge-ab"]
	_check_eq(scene._authoritative_route_map_pixels(tampered).size(), 0, "edge/node mismatch fails closed instead of drawing an inferred route")
	_free(ctx)


func _test_fast_patch_replaces_and_cancels_route_once() -> void:
	var ctx := _scene("p8_218_patch")
	var scene = ctx["scene"]
	var accepted := {
		"formation_id": "sf-a",
		"status": "draft",
		"path_node_ids": ["node-a", "node-b", "node-c"],
		"path_edge_ids": ["edge-ab", "edge-bc"],
	}
	var issue_payload := {
		"results": [{"op": "issue_move_order", "data": {"move_order": accepted}}],
	}
	_check(scene._apply_move_order_result_patch("issue_move_order", [{"formation": "sf-a"}], issue_payload), "accepted order patches live route")
	_check((scene.snapshot["strategic_formations"][0] as Dictionary).get("move_order") is Dictionary, "accepted route is visible immediately")
	_check(String(scene.status_message).begins_with("Order accepted and queued:"), "accepted order has persistent status feedback")
	var cancel_payload := {
		"results": [{"op": "cancel_move_order", "data": {"move_order": null}}],
	}
	_check(scene._apply_move_order_result_patch("cancel_move_order", [{"formation": "sf-a"}], cancel_payload), "cancel patches live route")
	_check((scene.snapshot["strategic_formations"][0] as Dictionary).get("move_order") == null, "cancel removes visible route immediately")
	_check_eq(scene.status_message, "Order cancelled.", "cancel has explicit status feedback")
	_free(ctx)


func _test_contact_blocked_order_is_labeled_interrupted() -> void:
	var ctx := _scene("p8_218_contact")
	var scene = ctx["scene"]
	var order := {"status": "blocked"}
	scene.snapshot["pending_battle"] = {"attacker_formation_id": "sf-a"}
	_check_eq(scene._order_phase(order), "INTERRUPTED BY CONTACT", "contact-blocked route reports interruption")
	_free(ctx)


func _test_source_locks_mouse_split() -> void:
	var source := FileAccess.get_file_as_string("res://scripts/main_order_controls.gd")
	_check(source.find("MOUSE_BUTTON_LEFT") >= 0, "production layer explicitly handles left click")
	_check(source.find("MOUSE_BUTTON_RIGHT") >= 0, "production layer explicitly handles right click")
	var select_start := source.find("func _select_from_map")
	var order_start := source.find("func _order_from_map")
	_check(select_start >= 0 and order_start > select_start, "selection and order paths are separate functions")
	if select_start >= 0 and order_start > select_start:
		var selection_source := source.substr(select_start, order_start - select_start)
		_check(selection_source.find("_issue_move(") < 0, "left-click selection function cannot issue movement")


func _snapshot(dir: String, commands_path: String) -> Dictionary:
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 16,
		"control": {
			"enabled": true,
			"campaign_path": dir.path_join("campaign.json"),
			"snapshot_path": dir.path_join("campaign_snapshot.json"),
			"commands_path": commands_path,
		},
		"campaign": {"current_faction": "nato", "selected_faction": "nato"},
		"provinces": [
			{"id": "prov-a", "display_name": "Alpha", "owner": "nato", "x": 0, "y": 0},
			{"id": "prov-b", "display_name": "Bravo", "owner": "neutral", "x": 20, "y": 0},
			{"id": "prov-c", "display_name": "Charlie", "owner": "neutral", "x": 40, "y": 0},
		],
		"stack_presentations": {"prov-a": {"strategic_formation_ids": ["sf-a"]}},
		"strategic_formations": [{
			"id": "sf-a",
			"display_name": "Alpha Brigade",
			"faction": "nato",
			"province_id": "prov-a",
			"move_order": null,
		}],
		"operational_orders": [{
			"formation_id": "sf-a",
			"formation_display_name": "Alpha Brigade",
			"faction": "nato",
			"origin_node_id": "node-a",
			"origin_province_id": "prov-a",
			"origin_province_name": "Alpha",
			"target_node_id": "node-c",
			"target_province_id": "prov-c",
			"target_province_name": "Charlie",
			"path_node_ids": ["node-a", "node-b", "node-c"],
			"path_edge_ids": ["edge-ab", "edge-bc"],
			"locked_stance": "operational",
		}],
		"front_options": [],
	}


func _free(ctx: Dictionary) -> void:
	(ctx["scene"] as Object).free()
	var runner = ctx["runner"]
	if is_instance_valid(runner) and runner.get_parent() == null:
		runner.free()


func _check(value: bool, label: String) -> void:
	if value:
		passed += 1
		return
	failed += 1
	push_error("FAIL: %s" % label)


func _check_eq(actual: Variant, expected: Variant, label: String) -> void:
	_check(actual == expected, "%s expected=%s actual=%s" % [label, str(expected), str(actual)])
