extends SceneTree

## #218 interaction/presentation regression for the production top-level map layer.

const MainScript = preload("res://scripts/main_order_controls.gd")
const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")
const OperationalGraphViewScript = preload("res://scripts/presentation/operational_graph_view.gd")

const EARTH3_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const P3_GRAPH_RES := "res://assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"
const P3_GRAPH_REPO := "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"
const EM_CANDIDATE_GRAPH := "res://assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
const NATIVE_NODE_A := "op-node-e3_0442-anchor"
const NATIVE_NODE_B := "op-node-e3_0456-anchor"
const NATIVE_NODE_C := "op-node-e3_0455-anchor"
const NATIVE_EDGE_AB := "op-edge-corridor-op-node-e3_0442-anchor__op-node-e3_0456-anchor"
const NATIVE_EDGE_BC := "op-edge-corridor-op-node-e3_0455-anchor__op-node-e3_0456-anchor"

var passed := 0
var failed := 0


func _initialize() -> void:
	print("map_order_controls_test: start")
	if not _require_production_main():
		push_error("map_order_controls_test: FAILED production MainScript")
		quit(1)
		return
	_test_left_select_never_dispatches()
	_test_right_click_dispatches_exactly_once()
	_test_right_click_without_selection_or_route_dispatches_nothing()
	_test_persisted_route_uses_exact_node_and_edge_ids()
	_test_fast_patch_replaces_and_cancels_route_once()
	_test_contact_blocked_order_is_labeled_interrupted()
	_test_source_locks_mouse_split()
	_test_production_p3_graph_loads_and_renders_native_route()
	_test_production_repo_relative_graph_path_loads()
	_test_missing_and_malformed_graph_paths_fail_closed()
	_test_unapproved_candidate_graph_is_not_fallback()
	_test_production_node_edge_mismatch_refuses_render()
	if failed > 0:
		push_error("map_order_controls_test: FAILED %s" % failed)
		quit(1)
		return
	print("map_order_controls_test: passed=%s failed=0" % passed)
	print("map_order_controls_test: PASS")
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


func _native_order() -> Dictionary:
	return {
		"formation_id": "sf_pol_vilnius",
		"status": "committed",
		"path_node_ids": [NATIVE_NODE_A, NATIVE_NODE_B, NATIVE_NODE_C],
		"path_edge_ids": [NATIVE_EDGE_AB, NATIVE_EDGE_BC],
	}


func _production_snapshot(graph_contract: Dictionary) -> Dictionary:
	var order := _native_order()
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 16,
		"campaign": {
			"current_faction": "nato",
			"selected_faction": "nato",
			"map_id": "earth3_europe_mediterranean",
			"map_metadata": graph_contract.get("map_metadata", {
				"operational_graph": P3_GRAPH_REPO,
			}),
		},
		"strategic_map": graph_contract.get("strategic_map", {
			"map_id": "earth3_europe_mediterranean",
			"operational_graph_path": P3_GRAPH_RES,
			"fallback": "none",
		}),
		"provinces": [
			{"id": "e3_0442", "display_name": "Vilnius", "owner": "nato", "x": 0, "y": 0},
			{"id": "e3_0456", "display_name": "Hop", "owner": "neutral", "x": 20, "y": 0},
			{"id": "e3_0455", "display_name": "Dest", "owner": "neutral", "x": 40, "y": 0},
		],
		"strategic_formations": [{
			"id": "sf_pol_vilnius",
			"display_name": "Vilnius Forward Brigade",
			"faction": "nato",
			"province_id": "e3_0442",
			"move_order": order,
		}],
	}


func _production_scene(name: String, graph_contract: Dictionary = {}) -> Dictionary:
	var scene = MainScript.new()
	var runner = FakeRunnerScript.new()
	scene.command_runner = runner
	scene.snapshot = _production_snapshot(graph_contract)
	scene.map_manifest_source_path = EARTH3_MANIFEST
	scene.selected_province_id = "e3_0442"
	scene.selected_strategic_formation_id = "sf_pol_vilnius"
	scene._open_operational_graph()
	return {"scene": scene, "runner": runner, "name": name}


func _assert_production_graph_ready(scene) -> void:
	_check(scene.operational_graph != null, "production scene owns an operational graph view")
	_check(scene.operational_graph.is_ready, "production graph loader marked the authenticated P3 graph ready")
	_check_eq(scene.operational_graph.path, P3_GRAPH_RES, "production loader opened the exact P3 resource")
	var nodes: Dictionary = scene.operational_graph.index.get("nodes", {})
	var edges: Dictionary = scene.operational_graph.index.get("edges", {})
	_check(nodes.has(NATIVE_NODE_A), "P3 graph contains Vilnius origin node")
	_check(nodes.has(NATIVE_NODE_B), "P3 graph contains native hop node")
	_check(nodes.has(NATIVE_NODE_C), "P3 graph contains native destination node")
	_check(edges.has(NATIVE_EDGE_AB), "P3 graph contains native first corridor")
	_check(edges.has(NATIVE_EDGE_BC), "P3 graph contains native second corridor")
	_check(not nodes.has("node-a"), "production loader did not inject the artificial #218 index")


func _test_production_p3_graph_loads_and_renders_native_route() -> void:
	var ctx := _production_scene("p8_218_production_p3")
	var scene = ctx["scene"]
	_assert_production_graph_ready(scene)
	var points: PackedVector2Array = scene._authoritative_route_map_pixels(_native_order())
	_check_eq(points.size(), 3, "committed native order resolves every authoritative P3 node")
	if points.size() == 3:
		_check_eq(points[0], Vector2(2498, 1585), "route begins at exact Vilnius P3 pixel")
		_check_eq(points[2], Vector2(2571, 1639), "route ends at exact destination P3 pixel")
	var primitives: Dictionary = scene._route_presentation_primitives(points, scene.QUEUED_ROUTE_COLOR)
	_check(primitives["lines"].size() >= 2, "production route layer emits the path line segments")
	_check(primitives["chevrons"].size() >= 1, "production route layer emits directional chevron(s)")
	_check(primitives.get("destination") != null, "production route layer emits a destination indicator")
	_free(ctx)


func _test_production_repo_relative_graph_path_loads() -> void:
	var ctx := _production_scene("p8_218_repo_relative", {
		"strategic_map": {
			"map_id": "earth3_europe_mediterranean",
			"fallback": "none",
		},
		"map_metadata": {
			"operational_graph": P3_GRAPH_REPO,
		},
	})
	_assert_production_graph_ready(ctx["scene"])
	_free(ctx)


func _test_missing_and_malformed_graph_paths_fail_closed() -> void:
	var missing := _production_scene("p8_218_missing_graph", {
		"strategic_map": {
			"map_id": "earth3_europe_mediterranean",
			"fallback": "none",
		},
		"map_metadata": {},
	})
	_check(not missing["scene"].operational_graph.is_ready, "missing graph path leaves the view unready")
	_check_eq(missing["scene"]._authoritative_route_map_pixels(_native_order()).size(), 0, "missing graph draws nothing")
	_free(missing)
	var malformed := _production_scene("p8_218_malformed_graph", {
		"strategic_map": {
			"map_id": "earth3_europe_mediterranean",
			"operational_graph_path": "res://godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
			"fallback": "none",
		},
		"map_metadata": {
			"operational_graph": "../p3_authority/not-a-graph.json",
		},
	})
	_check(not malformed["scene"].operational_graph.is_ready, "malformed graph path leaves the view unready")
	_check_eq(malformed["scene"]._authoritative_route_map_pixels(_native_order()).size(), 0, "malformed graph draws nothing")
	_free(malformed)


func _test_unapproved_candidate_graph_is_not_fallback() -> void:
	var view = OperationalGraphViewScript.new()
	_check(FileAccess.file_exists(EM_CANDIDATE_GRAPH), "adversarial EM candidate graph exists on disk")
	var resolved := view.resolve_path(EARTH3_MANIFEST, {
		"strategic_map": {"map_id": "earth3_europe_mediterranean", "fallback": "none"},
		"campaign": {"map_metadata": {}},
	})
	_check_eq(resolved, "", "Earth3 without an approved graph path does not fall back")
	_check(resolved != EM_CANDIDATE_GRAPH, "Earth3 does not select the EM candidate graph")
	_check(resolved.find("operational/operational_graph.json") < 0, "Earth3 does not select a sibling candidate graph")
	var existing_wrong := view.resolve_path(EARTH3_MANIFEST, {
		"strategic_map": {
			"map_id": "earth3_europe_mediterranean",
			"operational_graph_path": EM_CANDIDATE_GRAPH,
			"fallback": "none",
		},
		"campaign": {
			"map_id": "earth3_europe_mediterranean",
			"map_metadata": {
				"operational_graph": EM_CANDIDATE_GRAPH,
			},
		},
	})
	_check_eq(existing_wrong, "", "Earth3 rejects a wrong-but-existing EM graph")
	var ctx := _production_scene("p8_218_candidate_blocked", {
		"strategic_map": {
			"map_id": "earth3_europe_mediterranean",
			"operational_graph_path": EM_CANDIDATE_GRAPH,
			"fallback": "none",
		},
		"map_metadata": {
			"operational_graph": EM_CANDIDATE_GRAPH,
		},
	})
	_check(not ctx["scene"].operational_graph.is_ready, "unapproved Earth3 candidate path fails closed")
	_check(ctx["scene"].operational_graph.path != EM_CANDIDATE_GRAPH, "failed Earth3 load does not swap in the EM graph")
	_check_eq(ctx["scene"]._authoritative_route_map_pixels(_native_order()).size(), 0, "wrong-but-existing EM graph draws nothing")
	_free(ctx)


func _test_production_node_edge_mismatch_refuses_render() -> void:
	var ctx := _production_scene("p8_218_mismatch")
	var scene = ctx["scene"]
	_assert_production_graph_ready(scene)
	var tampered := _native_order()
	tampered["path_edge_ids"] = [NATIVE_EDGE_BC, NATIVE_EDGE_AB]
	_check_eq(scene._authoritative_route_map_pixels(tampered).size(), 0, "P3 node/edge mismatch refuses to render")
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
