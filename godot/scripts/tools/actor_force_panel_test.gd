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
	_assert_eq("research formation", String(research.get("formation", "")), "sf-fra")
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
				"command_actor_id": "fra",
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
	var src := FileAccess.get_file_as_string("res://scripts/main_stack_panel.gd")
	var draw_at := src.find("func _draw_stack_section(")
	var header_at := src.find("_draw_formation_header(", draw_at)
	var fm_at := src.find("_draw_force_management(", header_at)
	var bn_at := src.find("BATTALIONS IN FORMATION", header_at)
	_assert_true("formation header before FM", header_at > draw_at)
	_assert_true("FM starts before battalion list when open", fm_at > header_at and fm_at < bn_at)
	_assert_true("battalion list still present for closed FM", bn_at > 0)
	_assert_true("repair stays in force management", src.find("Repair / replenish") > 0)
	var skip := src.substr(header_at, fm_at - header_at + 180)
	_assert_true("FM-open skip does not clear formation id", skip.find("selected_strategic_formation_id = \"\"") < 0)
	_assert_true("FM-open skip does not clear battalion id", skip.find("selected_battalion_id = \"\"") < 0)
	var client: Node = stack_script.new()
	root.add_child(client)
	client.selected_strategic_formation_id = "sf_deu_berlin"
	client.selected_battalion_id = "bn_sf_deu_berlin"
	client.force_management_open = true
	_assert_eq("formation id preserved", client.selected_strategic_formation_id, "sf_deu_berlin")
	_assert_eq("battalion id preserved", client.selected_battalion_id, "bn_sf_deu_berlin")
	client.force_management_open = false
	_assert_eq("formation id unchanged after close", client.selected_strategic_formation_id, "sf_deu_berlin")
	_assert_eq("battalion id unchanged after close", client.selected_battalion_id, "bn_sf_deu_berlin")
	client.queue_free()


func _assert_true(label: String, value: bool, detail := "") -> void:
	if value:
		_passed += 1
		print("PASS %s" % label)
	else:
		_failed += 1
		print("FAIL %s %s" % [label, detail])


func _assert_eq(label: String, actual: Variant, expected: Variant) -> void:
	_assert_true(label, actual == expected, "got %s expected %s" % [actual, expected])
