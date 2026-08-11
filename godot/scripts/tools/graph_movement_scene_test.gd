extends SceneTree

## #206 — the production Godot movement surface must be graph-native.
##
## These assertions drive the *real* click path on the *active* main scene
## script. A control that merely appears in an enabled-button list is not a
## proof of anything: the only evidence that a click reached the backend is the
## queued command file, so every dispatch check below reads that file back and
## inspects the ops and payload the backend would actually receive.

const MainScript = preload("res://scripts/main_stack_panel.gd")
const FakeRunnerScript = preload("res://scripts/tools/fake_command_runner.gd")

var passed := 0
var failed := 0


func _initialize() -> void:
	print("graph_movement_scene_test: start")
	_run_all()
	if failed > 0:
		push_error("graph_movement_scene_test: FAILED %s" % failed)
		quit(1)
		return
	print("graph_movement_scene_test: passed=%s failed=0" % passed)
	print("graph_movement_scene_test: PASS")
	quit(0)


func _run_all() -> void:
	_test_map_click_dispatches_graph_native_order()
	_test_panel_button_dispatches_the_same_order()
	_test_legacy_province_move_op_is_gone_from_the_scene_source()
	_test_unrouted_target_cannot_dispatch()
	_test_locked_order_offers_no_targets()
	_test_draft_order_cancels_by_formation_id()


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


func _test_map_click_dispatches_graph_native_order() -> void:
	var ctx := _scene("p6_graph_map_click")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]

	_check(
		scene.legal_targets.has("prov-c"),
		"a routed destination province is a legal map target"
	)
	# The exact production map-click branch: _unhandled_input calls _issue_move
	# for a province present in legal_targets.
	scene._issue_move("prov-c")

	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 2, "map click queues draft + commit (status: %s)" % String(scene.status_message))
	if rows.size() != 2:
		_free(ctx)
		return
	var draft: Dictionary = rows[0]
	var commit: Dictionary = rows[1]
	_check_eq(String(draft.get("op", "")), "issue_move_order", "first op is issue_move_order")
	_check_eq(String(commit.get("op", "")), "commit_move_orders", "second op is commit_move_orders")
	_check_eq(String(draft.get("formation", "")), "sf-a", "order names the strategic formation")
	_check_eq(
		draft.get("path_node_ids", []),
		["node-a", "node-b", "node-c"],
		"order carries the full authenticated node path"
	)
	_check_eq(
		draft.get("path_edge_ids", []),
		["edge-ab", "edge-bc"],
		"order carries the full authenticated edge path"
	)
	_check(
		not draft.has("battalion") and not draft.has("province"),
		"graph order carries no battalion or province adjacency payload"
	)
	_check(
		not String(draft.get("command_id", "")).is_empty()
		and not String(commit.get("command_id", "")).is_empty()
		and String(draft.get("command_id", "")) != String(commit.get("command_id", "")),
		"every queued command carries a distinct exactly-once identity"
	)
	_check_eq(String(commit.get("faction", "")), "nato", "commit is scoped to the ordering faction")
	_check_eq(
		String(commit.get("locked_stance", "")),
		"operational",
		"commit locks the stance the option was validated under"
	)
	_free(ctx)


func _test_panel_button_dispatches_the_same_order() -> void:
	var ctx := _scene("p6_graph_panel_button")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]

	_check(
		Array(scene.enabled_action_button_ids()).has("move:prov-c"),
		"movement order button is offered for the selected formation"
	)
	scene._handle_button("move:prov-c")

	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 2, "panel button queues draft + commit (status: %s)" % String(scene.status_message))
	if rows.size() == 2:
		_check_eq(
			String((rows[0] as Dictionary).get("op", "")),
			"issue_move_order",
			"panel button dispatches issue_move_order"
		)
		_check_eq(
			(rows[0] as Dictionary).get("path_edge_ids", []),
			["edge-ab", "edge-bc"],
			"panel button carries the same authenticated edge path"
		)
	_free(ctx)


func _test_legacy_province_move_op_is_gone_from_the_scene_source() -> void:
	## A residual legacy dispatch would silently reintroduce #206 for any code
	## path this test does not click, so assert on the production source itself.
	for path in [
		"res://scripts/main.gd",
		"res://scripts/main_writeback.gd",
		"res://scripts/main_stack_panel.gd",
	]:
		var source := FileAccess.get_file_as_string(path)
		_check(
			source.find('"op": "move"') < 0,
			"%s no longer emits the legacy province move op" % path
		)


func _test_unrouted_target_cannot_dispatch() -> void:
	var ctx := _scene("p6_graph_unrouted")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	# prov-x is polygon-adjacent in the snapshot's province edges but carries no
	# authenticated route, so it must never reach the backend.
	scene._issue_move("prov-x")
	_check(
		not FileAccess.file_exists(commands_path),
		"a province without an authenticated route dispatches nothing"
	)
	_check(
		not Array(scene.enabled_action_button_ids()).has("move:prov-x"),
		"a province without an authenticated route is not an offered button"
	)
	_free(ctx)


func _test_locked_order_offers_no_targets() -> void:
	var ctx := _scene("p6_graph_locked")
	var scene = ctx["scene"]
	# The backend drops locked formations from operational_orders; the scene must
	# report that instead of inventing a target.
	scene.snapshot["operational_orders"] = []
	var indexed: Dictionary = scene.index_operational_orders(scene.snapshot)
	scene.orders_by_formation = indexed.get("by_formation", {})
	scene.order_formations_by_province = indexed.get("by_province", {})
	scene._rebuild_legal_targets()
	_check(scene.legal_targets.is_empty(), "locked formation exposes no legal targets")
	_check(
		not Array(scene.enabled_action_button_ids()).has("move:prov-c"),
		"locked formation exposes no movement button"
	)
	_free(ctx)


func _test_draft_order_cancels_by_formation_id() -> void:
	var ctx := _scene("p6_graph_cancel")
	var scene = ctx["scene"]
	var commands_path: String = ctx["commands_path"]
	_check(
		not Array(scene.enabled_action_button_ids()).has("cancel_move_order"),
		"cancel stays unavailable while the formation holds no draft"
	)
	var forces: Array = scene.snapshot["strategic_formations"]
	(forces[0] as Dictionary)["move_order"] = {
		"order_id": "ord-1",
		"formation_id": "sf-a",
		"status": "draft",
		"path_node_ids": ["node-a", "node-b"],
		"path_edge_ids": ["edge-ab"],
	}
	_check(
		Array(scene.enabled_action_button_ids()).has("cancel_move_order"),
		"a draft order exposes cancel"
	)
	scene._handle_button("cancel_move_order")
	var rows := _queued_commands(commands_path)
	_check_eq(rows.size(), 1, "cancel queues exactly one command (status: %s)" % String(scene.status_message))
	if rows.size() == 1:
		var row: Dictionary = rows[0]
		_check_eq(String(row.get("op", "")), "cancel_move_order", "cancel dispatches cancel_move_order")
		_check_eq(String(row.get("formation", "")), "sf-a", "cancel names the strategic formation")

	(forces[0] as Dictionary)["move_order"] = {
		"order_id": "ord-1",
		"formation_id": "sf-a",
		"status": "committed",
		"path_node_ids": ["node-a", "node-b"],
		"path_edge_ids": ["edge-ab"],
	}
	_check(
		not Array(scene.enabled_action_button_ids()).has("cancel_move_order"),
		"a committed order is locked and cannot be cancelled from the UI"
	)
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
		# Polygon adjacency deliberately includes prov-a <-> prov-x, which the
		# authenticated graph does not: it must never become a player target.
		"edges": [["prov-a", "prov-b"], ["prov-b", "prov-c"], ["prov-a", "prov-x"]],
		"battalions": [
			{
				"id": "bn-a",
				"strategic_formation_id": "sf-a",
				"province_id": "prov-a",
				"faction": "nato",
				"battalion_type": "tank",
				"unit_count": 4,
			},
		],
		"battalion_stacks": {"prov-a": ["bn-a"]},
		"stack_presentations": {
			"prov-a": {
				"province_id": "prov-a",
				"battalion_ids": ["bn-a"],
				"strategic_formation_ids": ["sf-a"],
			},
		},
		"strategic_formations": [
			{
				"id": "sf-a",
				"display_name": "Alpha Brigade",
				"faction": "nato",
				"province_id": "prov-a",
				"move_order": null,
			},
		],
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
