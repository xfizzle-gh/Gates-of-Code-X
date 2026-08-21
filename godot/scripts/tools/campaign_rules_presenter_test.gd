extends SceneTree

const Presenter := preload("res://scripts/presentation/campaign_rules_presenter.gd")

var passed := 0
var failed := 0


func _initialize() -> void:
	print("campaign_rules_presenter_test: start")
	_run_all()
	if failed > 0:
		push_error("campaign_rules_presenter_test: FAILED %s" % failed)
		quit(1)
		return
	print("campaign_rules_presenter_test: passed=%s failed=0" % passed)
	print("campaign_rules_presenter_test: PASS")
	quit(0)


func _run_all() -> void:
	_test_calendar_and_momentum_labels()
	_test_objective_uses_required_not_threshold()
	_test_result_shows_continue_and_conclude_on_victory()
	_test_result_hides_continue_on_defeat()
	_test_opposing_contract_is_not_player_victory()
	_test_contradictory_winner_grade_does_not_show_continue()
	_test_rewrite_launch_args_sets_preset_and_fog()


func _ok(name: String) -> void:
	passed += 1
	print("  ok ", name)


func _fail(name: String, detail: String) -> void:
	failed += 1
	push_error("  FAIL %s: %s" % [name, detail])
	print("  FAIL ", name, ": ", detail)


func _assert_eq(name: String, got: Variant, expected: Variant) -> void:
	if got == expected:
		_ok(name)
	else:
		_fail(name, "got=%s expected=%s" % [got, expected])


func _assert_true(name: String, cond: bool, detail := "") -> void:
	if cond:
		_ok(name)
	else:
		_fail(name, detail if not detail.is_empty() else "false")


func _test_calendar_and_momentum_labels() -> void:
	var campaign := {
		"turn_number": 53,
		"turn_cap": 104,
		"length_preset": "medium",
		"calendar": {"label": "2029-W01", "year": 2029, "week": 1},
		"momentum": {"score": 12},
		"continue_playing": false,
	}
	_assert_eq("calendar label", Presenter.calendar_label(campaign), "2029-W01")
	_assert_eq("turn line", Presenter.turn_line(campaign), "Turn 53 / 104   2029-W01")
	_assert_eq("momentum", Presenter.momentum_label(campaign), "Momentum 12")


func _test_objective_uses_required_not_threshold() -> void:
	var line := Presenter.objective_progress_line({
		"display_name": "Secure Donbas",
		"progress": 1,
		"required": 2,
		"threshold": 99,
		"layer": "coalition_war_aim",
		"completed": false,
	})
	_assert_eq("war aim line", line, "1/2  [War aim] Secure Donbas")
	var done := Presenter.objective_progress_line({
		"display_name": "Defend Kyiv",
		"progress": 1,
		"required": 1,
		"layer": "national_contribution",
		"completed": true,
	})
	_assert_eq("national line", done, "DONE  [National] Defend Kyiv")


func _test_result_shows_continue_and_conclude_on_victory() -> void:
	var model := Presenter.result_model({
		"campaign": {
			"continue_playing": false,
			"concluded": false,
			"momentum": {"score": 60},
			"outcome": {
				"status": "complete",
				"grade": "victory",
				"reason": "campaign victory",
				"selected_faction_result": "victory",
			},
		}
	})
	_assert_true("result visible", bool(model.get("visible", false)))
	_assert_true("show continue", bool(model.get("show_continue", false)))
	_assert_true("show conclude", bool(model.get("show_conclude", false)))
	_assert_eq("grade label", String(model.get("grade_label", "")), "Victory")


func _test_result_hides_continue_on_defeat() -> void:
	var model := Presenter.result_model({
		"campaign": {
			"continue_playing": false,
			"concluded": false,
			"outcome": {
				"status": "complete",
				"grade": "defeat",
				"selected_faction_result": "defeat",
			},
		}
	})
	_assert_true("defeat visible", bool(model.get("visible", false)))
	_assert_true("no continue after defeat", not bool(model.get("show_continue", true)))
	_assert_true("conclude still available", bool(model.get("show_conclude", false)))


func _test_opposing_contract_is_not_player_victory() -> void:
	var model := Presenter.result_model({
		"campaign": {
			"continue_playing": false,
			"concluded": false,
			"momentum": {"score": 2},
			"outcome": {
				"status": "complete",
				"grade": "defeat",
				"selected_faction_result": "defeat",
				"winner_coalition": "eastern-coalition",
				"loser_coalition": "western-coalition",
				"coalition_result": "incomplete",
				"national_result": "incomplete",
				"reason": "opposing coalition completed its accepted victory contract",
			},
		}
	})
	_assert_true("opposing contract visible", bool(model.get("visible", false)))
	_assert_true("opposing contract hides continue", not bool(model.get("show_continue", true)))
	_assert_eq("opposing contract grade label", String(model.get("grade_label", "")), "Defeat")
	_assert_eq("opposing contract grade", String(model.get("grade", "")), "defeat")
	_assert_eq("opposing contract coalition", String(model.get("coalition_result", "")), "incomplete")
	_assert_eq("opposing contract national", String(model.get("national_result", "")), "incomplete")


func _test_contradictory_winner_grade_does_not_show_continue() -> void:
	var model := Presenter.result_model({
		"campaign": {
			"continue_playing": false,
			"concluded": false,
			"outcome": {
				"status": "complete",
				"grade": "victory",
				"selected_faction_result": "defeat",
				"coalition_result": "victory",
				"national_result": "victory",
			},
		}
	})
	_assert_true("leaked winner grade stays visible", bool(model.get("visible", false)))
	_assert_true("leaked winner grade hides continue", not bool(model.get("show_continue", true)))


func _test_rewrite_launch_args_sets_preset_and_fog() -> void:
	var rewritten: Array = Presenter.rewrite_launch_args(
		["play", "--new", "--fog-of-war", "off", "--length-preset", "medium"],
		"short",
		"on"
	)
	_assert_true("keeps play", rewritten.has("play"))
	_assert_true("keeps new", rewritten.has("--new"))
	var fog_at := rewritten.find("--fog-of-war")
	_assert_true("fog flag present", fog_at >= 0)
	_assert_eq("fog value", String(rewritten[fog_at + 1]), "on")
	var preset_at := rewritten.find("--length-preset")
	_assert_true("preset flag present", preset_at >= 0)
	_assert_eq("preset value", String(rewritten[preset_at + 1]), "short")
