extends SceneTree

## Headless contract for the #149 Godot force-management panel.
## Godot --headless --path godot -s res://scripts/tools/actor_force_panel_test.gd

const MainWritebackScript = preload("res://scripts/main_writeback.gd")
const MainStackPanelScript = preload("res://scripts/main_stack_panel.gd")

var _failed := 0
var _passed := 0


func _initialize() -> void:
	print("actor_force_panel_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	_test_command_contract()
	_test_stack_panel_preload()
	print("actor_force_panel_test: %s passed, %s failed" % [_passed, _failed])
	quit(1 if _failed > 0 else 0)


func _test_command_contract() -> void:
	var client: Node = MainWritebackScript.new()
	root.add_child(client)
	client.snapshot = {
		"schema": "gates-of-codex.frontend",
		"acting_actor": {
			"actor_id": "fra",
			"display_name": "France",
			"short_name": "FRA",
			"resources": 1240,
			"income_last_round": 80,
			"maintenance_last_round": 20,
			"researched_count": 3,
			"content_installed": true,
		},
		"control": {"enabled": true, "supported_ops": ["research", "recruit", "assign", "repair", "actor_force_panel"]},
	}
	client.selected_strategic_formation_id = "sf-fra"
	client.selected_battalion_id = "bn-fra"
	var actor: Dictionary = client.acting_actor_block()
	_assert_eq("acting actor id", String(actor.get("actor_id", "")), "fra")
	_assert_eq("acting actor treasury", int(actor.get("resources", 0)), 1240)
	var research: Dictionary = client._research_command("actor:fra:unit:fixture_fra")
	_assert_eq("research op", String(research.get("op", "")), "research")
	_assert_eq("research actor", String(research.get("actor", "")), "fra")
	_assert_eq("research key", String(research.get("key", "")), "actor:fra:unit:fixture_fra")
	var recruit: Dictionary = client._recruit_command("fixture_fra")
	_assert_eq("recruit op", String(recruit.get("op", "")), "recruit")
	_assert_eq("recruit formation", String(recruit.get("formation", "")), "sf-fra")
	var assign_cmd: Dictionary = client._assign_command("fixture_fra")
	_assert_eq("assign battalion", String(assign_cmd.get("battalion", "")), "bn-fra")
	var repair: Dictionary = client._repair_command()
	_assert_eq("repair op", String(repair.get("op", "")), "repair")
	_assert_true("research mutates", client._command_mutates_state("research:actor:fra:unit:fixture_fra"))
	_assert_true("recruit mutates", client._command_mutates_state("recruit:fixture_fra"))
	_assert_true("assign mutates", client._command_mutates_state("assign:fixture_fra"))
	_assert_true("repair mutates", client._command_mutates_state("repair_formation"))
	_assert_true("query does not mutate", not client._command_mutates_state("manage_forces"))
	client._capture_force_panel({
		"ok": true,
		"results": [{
			"op": "actor_force_panel",
			"ok": true,
			"data": {
				"actor_id": "fra",
				"can_manage_formation": true,
				"recruitment_offers": [{"unit_name": "fixture_fra", "unlocked": true, "actor_id": "fra"}],
			},
		}],
	})
	_assert_true("panel captured", client.force_management_open)
	_assert_eq("panel actor", String(client.force_panel.get("actor_id", "")), "fra")
	_assert_true(
		"no foreign offer",
		(client.force_panel.get("recruitment_offers", []) as Array).size() == 1
	)
	client.queue_free()


func _test_stack_panel_preload() -> void:
	var stack_script: GDScript = MainStackPanelScript
	_assert_true("stack panel script loaded", stack_script != null)
	_assert_true(
		"stack panel instantiable",
		stack_script != null and stack_script.can_instantiate()
	)


func _assert_true(label: String, value: bool, detail := "") -> void:
	if value:
		_passed += 1
		print("PASS %s" % label)
	else:
		_failed += 1
		print("FAIL %s %s" % [label, detail])


func _assert_eq(label: String, actual: Variant, expected: Variant) -> void:
	_assert_true(label, actual == expected, "got %s expected %s" % [actual, expected])
