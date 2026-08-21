extends SceneTree

## Headless contract for the End Turn treasury earn/spend overlay.
## Godot --headless --path godot -s res://scripts/tools/end_turn_economy_report_test.gd

const MainWritebackScript = preload("res://scripts/main_writeback.gd")
const MainStackPanelScript = preload("res://scripts/main_stack_panel.gd")

var _failed := 0
var _passed := 0


func _initialize() -> void:
	print("end_turn_economy_report_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	_test_command_contract()
	_test_stack_panel_preload()
	print("end_turn_economy_report_test: %s passed, %s failed" % [_passed, _failed])
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
			"resources": 1280,
			"income_last_round": 80,
			"maintenance_last_round": 20,
			"content_installed": true,
		},
		"control": {"enabled": true, "supported_ops": ["end_player_round"]},
	}
	_assert_true("dismiss is presentation only", not client._command_mutates_state("dismiss_economy_report"))
	client._capture_end_turn_economy_report({
		"ok": true,
		"results": [{
			"op": "end_player_round",
			"ok": true,
			"data": {
				"economy_report": {
					"schema": "gates-of-codex.end-turn-economy-report",
					"schema_version": 1,
					"settled": true,
					"source": "settle_actor_round_economy",
					"actor_id": "fra",
					"display_name": "France",
					"income": 80,
					"maintenance": 20,
					"net": 60,
					"treasury": 1280,
					"other_actors_acted": true,
					"other_actors_summary": "Other actors acted.",
				},
			},
		}],
	})
	_assert_true("report captured", client.economy_report_open)
	_assert_eq("report actor", String(client.economy_report.get("actor_id", "")), "fra")
	_assert_eq("report income", int(client.economy_report.get("income", 0)), 80)
	_assert_eq("report maintenance", int(client.economy_report.get("maintenance", 0)), 20)
	_assert_eq("report net", int(client.economy_report.get("net", 0)), 60)
	_assert_eq("report treasury", int(client.economy_report.get("treasury", 0)), 1280)
	_assert_eq("other actors line", String(client.economy_report.get("other_actors_summary", "")), "Other actors acted.")
	_assert_eq("acting actor only", String(client.economy_report.get("actor_id", "")), "fra")
	client.dismiss_end_turn_economy_report()
	_assert_true("dismissed", not client.economy_report_open)
	client._capture_end_turn_economy_report({
		"ok": true,
		"results": [{
			"op": "end_player_round",
			"ok": true,
			"data": {
				"economy_report": {
					"settled": false,
					"source": "",
					"actor_id": "fra",
				},
			},
		}],
	})
	_assert_true("unsettled does not open overlay", not client.economy_report_open)
	client.queue_free()


func _test_stack_panel_preload() -> void:
	_assert_true("stack panel instantiable", MainStackPanelScript.can_instantiate())


func _assert_true(label: String, value: bool, detail := "") -> void:
	if value:
		_passed += 1
		print("PASS %s" % label)
	else:
		_failed += 1
		print("FAIL %s %s" % [label, detail])


func _assert_eq(label: String, actual: Variant, expected: Variant) -> void:
	_assert_true(label, actual == expected, "got %s expected %s" % [actual, expected])
