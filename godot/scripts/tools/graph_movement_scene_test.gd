extends SceneTree

## #206/#218 production movement surface regression.
## Drives the active order-control layer so the existing headless Godot CI gate
## proves selection and movement remain separate and graph-native.

const MainScript = preload("res://scripts/main_order_controls.gd")
const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")

var passed := 0
var failed := 0


func _initialize() -> void:
	print("graph_movement_scene_test: start")
	if not _require_production_main():
		push_error("graph_movement_scene_test: FAILED production MainScript")
		quit(1)
		return
	_run_all()
	if failed > 0:
		push_error("graph_movement_scene_test: FAILED %s" % failed)
		quit(1)
		return
	print("graph_movement_scene_test: passed=%s failed=0" % passed)
	print("graph_movement_scene_test: PASS")
	quit(0)


func _require_production_main() -> bool:
	if MainScript == null:
		push_error("production MainScript failed to preload")
		return false
	if not (MainScript as Script).can_instantiate():
		push_error("production MainScript cannot instantiate")
		return false
	var instance = MainScript.new()
	if instance == null:
		push_error("production MainScript instantiation returned null")
		return false
	var ok := instance.has_method("_order_from_map") and instance.has_method("_select_from_map")
	instance.free()
	if not ok:
		push_error("production MainScript is missing required order-control methods")
		return false
	return true


func _run_all() -> void:
	_test_left_selection_never_dispatches()
	_test_right_click_dispatches_graph_native_order()
	_test_panel_button_dispatches_the_same_order()
	_test_legacy_province_move_op_is_gone_from_the_scene_source()
	_test_unrouted_target_cannot_dispatch()
	_test_locked_order_offers_no_targets()
	_test_draft_order_cancels_by_formation_id()
	_test_pending_battle_modal_precedes_map_mouse_split()
	_test_accept_feedback_stays_bound_to_dispatched_formation()
	_test_authoritative_route_rejects_tampered_edges()
	_test_focus_set_ignores_unrelated_formation_orders()
	_test_theatre_lod_keeps_legal_targets_and_order_payload()


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
	scene.snapshot = _graph_snapshot(dir, commands_path)
	scene.provinces_by_id = {
		"prov-a": scene.snapshot["provinces"][0],
		"prov-b": scene.snapshot["provinces"][1],
		"prov-c": scene.snapshot["provinces"][2],
		"prov-x": scene.snapshot["provinces"][3],
	}
	var indexed: Dictionary = scene.index_operational_orders(scene.snapshot)
	scene.orders_by_formation = indexed.get("by_formation", {})
	scene.order_formations_by_province = indexed.get("by_province", {})
	scene.selected_province_id = "prov-a"
	scene.selected_strategic_formation_id = "sf-a"
	scene._rebuild_legal_targets()
	scene._ensure_operational_presenter()
	return {"scene": scene, "runner": runner, "commands_path": commands_path}


func _queued_commands(commands_path: String) -> Array:
	if not FileAccess.file_exists(commands_path):
		return []
	var parsed: Variant = JSON.parse_string(
		FileAccess.open(commands_path, FileAccess.READ).get_as_text()
	)
	if not parsed is Dictionary:
		return []
	return (parsed as Dictionary).get("commands", [])


func _test_left_selection_never_dispatches() -> void:
	var ctx := _scene("p8_left_select")
	var scene = ctx["scene"]
	scene._select_from_map("prov-c")
	_check_eq(scene.selected_province_id, "prov-c", "left selection changes province")
	_check_eq(scene.order_dispatch_count, 0, "left selection never increments order dispatch")
	_check(not FileAccess.file_exists(ctx["commands_path"]), "left selection writes no backend commands")
	_free(ctx)


func _test_right_click_dispatches_graph_native_order() -> void:
	var ctx := _scene("p8_graph_right_click")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	_check(scene.legal_targets.has("prov-c"), "routed destination is a legal target")
	scene._order_from_map("prov-c")
	_check_eq(scene.order_dispatch_count, 1, "right-click intent dispatches exactly once")
	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 2, "right-click queues draft + commit")
	if rows.size() != 2:
		_free(ctx)
		return
	var draft: Dictionary = rows[0]
	var commit: Dictionary = rows[1]
	_check_eq(String(draft.get("op", "")), "issue_move_order", "first op is issue_move_order")
	_check_eq(String(commit.get("op", "")), "commit_move_orders", "second op is commit_move_orders")
	_check_eq(String(draft.get("formation", "")), "sf-a", "order names the strategic formation")
	_check_eq(draft.get("path_node_ids", []), ["node-a", "node-b", "node-c"], "order carries exact node path")
	_check_eq(draft.get("path_edge_ids", []), ["edge-ab", "edge-bc"], "order carries exact edge path")
	_check(not draft.has("battalion") and not draft.has("province"), "graph order carries no legacy adjacency payload")
	_check(
		not String(draft.get("command_id", "")).is_empty()
		and not String(commit.get("command_id", "")).is_empty()
		and String(draft.get("command_id", "")) != String(commit.get("command_id", "")),
		"queued commands carry distinct exactly-once identities"
	)
	_check_eq(String(commit.get("faction", "")), "nato", "commit is scoped to ordering faction")
	_check_eq(String(commit.get("locked_stance", "")), "operational", "commit preserves locked stance")
	_free(ctx)


func _test_panel_button_dispatches_the_same_order() -> void:
	var ctx := _scene("p8_graph_panel_button")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	_check(Array(scene.enabled_action_button_ids()).has("move:prov-c"), "movement button is offered")
	scene._handle_button("move:prov-c")
	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 2, "panel button queues draft + commit")
	if rows.size() == 2:
		_check_eq(String((rows[0] as Dictionary).get("op", "")), "issue_move_order", "panel dispatches issue_move_order")
		_check_eq((rows[0] as Dictionary).get("path_edge_ids", []), ["edge-ab", "edge-bc"], "panel carries exact edge path")
	_free(ctx)


func _test_legacy_province_move_op_is_gone_from_the_scene_source() -> void:
	for path in [
		"res://scripts/main.gd",
		"res://scripts/main_writeback.gd",
		"res://scripts/main_stack_panel.gd",
		"res://scripts/main_order_controls.gd",
	]:
		var source := FileAccess.get_file_as_string(path)
		_check(source.find('"op": "move"') < 0, "%s emits no legacy province move op" % path)


func _test_unrouted_target_cannot_dispatch() -> void:
	var ctx := _scene("p8_graph_unrouted")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	scene._order_from_map("prov-x")
	_check(not FileAccess.file_exists(commands_path), "unrouted province dispatches nothing")
	_check(String(scene.status_message).begins_with("Illegal destination:"), "unrouted province gives visible reason")
	_check(not Array(scene.enabled_action_button_ids()).has("move:prov-x"), "unrouted province is not an offered button")
	_free(ctx)


func _test_locked_order_offers_no_targets() -> void:
	var ctx := _scene("p8_graph_locked")
	var scene = ctx["scene"]
	scene.snapshot["operational_orders"] = []
	var indexed: Dictionary = scene.index_operational_orders(scene.snapshot)
	scene.orders_by_formation = indexed.get("by_formation", {})
	scene.order_formations_by_province = indexed.get("by_province", {})
	scene._rebuild_legal_targets()
	_check(scene.legal_targets.is_empty(), "locked formation exposes no legal targets")
	_check(not Array(scene.enabled_action_button_ids()).has("move:prov-c"), "locked formation exposes no movement button")
	_free(ctx)


func _test_draft_order_cancels_by_formation_id() -> void:
	var ctx := _scene("p8_graph_cancel")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	_check(not Array(scene.enabled_action_button_ids()).has("cancel_move_order"), "cancel unavailable without draft")
	var forces: Array = scene.snapshot["strategic_formations"]
	(forces[0] as Dictionary)["move_order"] = {
		"order_id": "ord-1",
		"formation_id": "sf-a",
		"status": "draft",
		"path_node_ids": ["node-a", "node-b"],
		"path_edge_ids": ["edge-ab"],
	}
	_check(Array(scene.enabled_action_button_ids()).has("cancel_move_order"), "draft exposes cancel")
	scene._handle_button("cancel_move_order")
	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 1, "cancel queues exactly one command")
	if rows.size() == 1:
		var row: Dictionary = rows[0]
		_check_eq(String(row.get("op", "")), "cancel_move_order", "cancel dispatches cancel_move_order")
		_check_eq(String(row.get("formation", "")), "sf-a", "cancel names strategic formation")
	(forces[0] as Dictionary)["move_order"] = {
		"order_id": "ord-1",
		"formation_id": "sf-a",
		"status": "committed",
		"path_node_ids": ["node-a", "node-b"],
		"path_edge_ids": ["edge-ab"],
	}
	_check(not Array(scene.enabled_action_button_ids()).has("cancel_move_order"), "committed order cannot be cancelled")
	_free(ctx)


func _test_pending_battle_modal_precedes_map_mouse_split() -> void:
	var source := FileAccess.get_file_as_string("res://scripts/main_order_controls.gd")
	var guard := source.find('is_pending_battle_modal_active") and is_pending_battle_modal_active()')
	var mouse_split := source.find("if event is InputEventMouseButton")
	_check(guard >= 0 and mouse_split > guard, "pending-battle modal keeps mouse precedence over map controls")


func _test_accept_feedback_stays_bound_to_dispatched_formation() -> void:
	var ctx := _scene("p8_accept_owner")
	var scene = ctx["scene"]
	# Simulate changing selection while the backend finishes the sf-a command.
	scene.selected_province_id = "prov-c"
	scene.selected_strategic_formation_id = ""
	var accepted := {
		"formation_id": "sf-a",
		"status": "draft",
		"path_node_ids": ["node-a", "node-b", "node-c"],
		"path_edge_ids": ["edge-ab", "edge-bc"],
	}
	var payload := {"results": [{"op": "issue_move_order", "data": {"move_order": accepted}}]}
	_check(
		scene._apply_move_order_result_patch("issue_move_order", [{"formation": "sf-a"}], payload),
		"accepted command patches live route"
	)
	_check_eq(scene.status_message, "Order accepted and queued: Alpha Brigade.", "accept feedback names dispatched formation")
	_free(ctx)


func _test_authoritative_route_rejects_tampered_edges() -> void:
	var ctx := _scene("p8_route_integrity")
	var scene = ctx["scene"]
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
	var exact := {
		"path_node_ids": ["node-a", "node-b", "node-c"],
		"path_edge_ids": ["edge-ab", "edge-bc"],
	}
	_check_eq(scene._authoritative_route_map_pixels(exact).size(), 3, "exact persisted route resolves")
	var tampered := exact.duplicate(true)
	tampered["path_edge_ids"] = ["edge-bc", "edge-ab"]
	_check_eq(scene._authoritative_route_map_pixels(tampered).size(), 0, "tampered edge sequence fails closed")
	_free(ctx)


func _test_focus_set_ignores_unrelated_formation_orders() -> void:
	var ctx := _scene("p8_focus_selected_only")
	var scene = ctx["scene"]
	var extra := {
		"formation_id": "sf-other",
		"origin_province_id": "prov-x",
		"target_province_id": "prov-b",
		"path_node_ids": ["node-x", "node-b"],
		"path_edge_ids": ["edge-xb"],
	}
	(scene.snapshot.get("operational_orders", []) as Array).append(extra)
	var indexed: Dictionary = scene.index_operational_orders(scene.snapshot)
	scene.orders_by_formation = indexed.get("by_formation", {})
	scene.selected_strategic_formation_id = "sf-a"
	scene._rebuild_legal_targets()
	scene._rebuild_focus_set()
	_check(scene.focus_province_ids.has("prov-a"), "selected origin stays in focus")
	_check(scene.focus_province_ids.has("prov-c"), "selected formation target stays in focus")
	_check(not scene.focus_province_ids.has("prov-x"), "unrelated formation origin is not theatre-wide focus")
	_free(ctx)


func _test_theatre_lod_keeps_legal_targets_and_order_payload() -> void:
	var ctx := _scene("p8_theatre_target_lod")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	scene.view_scale = 1.15
	var before_ids: Array = scene.legal_targets.keys()
	before_ids.sort()
	_check(scene.legal_targets.has("prov-c"), "theatre LOD keeps every legal destination")
	_check(scene.legal_targets.size() >= 2, "selected formation still has multiple legal targets")
	if scene.has_method("_build_overlay_active_ids"):
		var active: Dictionary = scene.call("_build_overlay_active_ids")
		_check(not active.has("prov-c"), "theatre overlay does not expand every legal destination")
		_check(active.has("prov-a"), "selected origin remains overlay-active")
	if scene.has_method("_highlight_targets_for_draw"):
		var drawn: Dictionary = scene.call("_highlight_targets_for_draw")
		_check(not drawn.has("prov-c"), "theatre highlight set omits unemphasized destinations")
	scene.hovered_province_id = "prov-c"
	if scene.has_method("_highlight_targets_for_draw"):
		var hovered: Dictionary = scene.call("_highlight_targets_for_draw")
		_check(hovered.has("prov-c"), "hovered legal destination receives full highlight")
	scene.hovered_province_id = ""
	scene.view_scale = 2.0
	if scene.has_method("_highlight_targets_for_draw"):
		var detailed: Dictionary = scene.call("_highlight_targets_for_draw")
		_check(detailed.has("prov-c"), "closer zoom restores detailed legal-target presentation")
	scene.view_scale = 1.15
	var option: Dictionary = scene.legal_targets.get("prov-c", {})
	_check_eq(option.get("path_node_ids", []), ["node-a", "node-b", "node-c"], "LOD does not rewrite path_node_ids")
	_check_eq(option.get("path_edge_ids", []), ["edge-ab", "edge-bc"], "LOD does not rewrite path_edge_ids")
	scene._order_from_map("prov-c")
	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 2, "theatre click still queues draft + commit")
	if rows.size() == 2:
		var draft: Dictionary = rows[0]
		_check_eq(draft.get("path_node_ids", []), ["node-a", "node-b", "node-c"], "clicked order keeps exact nodes")
		_check_eq(draft.get("path_edge_ids", []), ["edge-ab", "edge-bc"], "clicked order keeps exact edges")
	var after_ids: Array = scene.legal_targets.keys()
	after_ids.sort()
	_check_eq(after_ids, before_ids, "legal_targets IDs are unchanged after theatre click")
	_free(ctx)


func _free(ctx: Dictionary) -> void:
	(ctx["scene"] as Object).free()
	var runner = ctx["runner"]
	if is_instance_valid(runner) and runner.get_parent() == null:
		runner.free()


func _graph_snapshot(dir: String, commands_path: String) -> Dictionary:
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
		"bounds": {"min_x": 0, "max_x": 100, "min_y": 0, "max_y": 100},
		"provinces": [
			{"id": "prov-a", "display_name": "Alpha", "owner": "nato", "x": 0, "y": 0},
			{"id": "prov-b", "display_name": "Bravo", "owner": "neutral", "x": 20, "y": 0},
			{"id": "prov-c", "display_name": "Charlie", "owner": "neutral", "x": 40, "y": 0},
			{"id": "prov-x", "display_name": "Xray", "owner": "neutral", "x": 0, "y": 40},
		],
		"edges": [["prov-a", "prov-b"], ["prov-b", "prov-c"], ["prov-a", "prov-x"]],
		"battalions": [{
			"id": "bn-a",
			"strategic_formation_id": "sf-a",
			"province_id": "prov-a",
			"faction": "nato",
			"battalion_type": "tank",
			"unit_count": 4,
		}],
		"battalion_stacks": {"prov-a": ["bn-a"]},
		"stack_presentations": {
			"prov-a": {
				"province_id": "prov-a",
				"battalion_ids": ["bn-a"],
				"strategic_formation_ids": ["sf-a"],
			},
		},
		"strategic_formations": [{
			"id": "sf-a",
			"display_name": "Alpha Brigade",
			"faction": "nato",
			"province_id": "prov-a",
			"move_order": null,
		}],
		"strategic_formation_presentations": {
			"sf-a": {
				"id": "sf-a",
				"display_name": "Alpha Brigade",
				"battalion_ids": ["bn-a"],
				"can_act": true,
			},
		},
		"battalion_presentations": {"bn-a": {"battalion_label": "1st", "can_act": true}},
		"front_options": [],
		"operational_orders": [
			{
				"formation_id": "sf-a",
				"formation_display_name": "Alpha Brigade",
				"faction": "nato",
				"origin_node_id": "node-a",
				"origin_province_id": "prov-a",
				"origin_province_name": "Alpha",
				"target_node_id": "node-b",
				"target_province_id": "prov-b",
				"target_province_name": "Bravo",
				"edge_id": "edge-ab",
				"first_edge_id": "edge-ab",
				"hop_count": 1,
				"route_cost_milli": 1000,
				"path_node_ids": ["node-a", "node-b"],
				"path_edge_ids": ["edge-ab"],
				"locked_stance": "operational",
			},
			{
				"formation_id": "sf-a",
				"formation_display_name": "Alpha Brigade",
				"faction": "nato",
				"origin_node_id": "node-a",
				"origin_province_id": "prov-a",
				"origin_province_name": "Alpha",
				"target_node_id": "node-c",
				"target_province_id": "prov-c",
				"target_province_name": "Charlie",
				"edge_id": "edge-bc",
				"first_edge_id": "edge-ab",
				"hop_count": 2,
				"route_cost_milli": 2000,
				"path_node_ids": ["node-a", "node-b", "node-c"],
				"path_edge_ids": ["edge-ab", "edge-bc"],
				"locked_stance": "operational",
			},
		],
		"objectives": [],
		"alliances": [],
		"factions": [{"id": "nato", "resources": 0}],
		"pending_battle": null,
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