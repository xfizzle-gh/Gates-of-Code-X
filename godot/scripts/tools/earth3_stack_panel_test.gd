extends SceneTree

## #52 Earth3 follow-up: existing stack panel on the live polygon main scene,
## driven by a hand-built fixture. Presentation/selection only.

const ProductionMain = preload("res://scripts/main_composed_presentation_refresh_safe.gd")
const OPERATIONAL_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const COMPACT_SNAPSHOT := "res://fixtures/snapshots/earth3_stack_panel.json"
const STACK_FIXTURE := "res://fixtures/presentation/earth3_stack_panel.json"
const STACK_PROVINCE := "e3_2108"
const ARMOR_BN := "bat-nato-1"
const MECH_BN := "bat-nato-2"
const ARMOR_TARGET := "e3_0823"
const MECH_TARGET := "e3_0845"

var passed := 0
var failed := 0


func _initialize() -> void:
	print("earth3_stack_panel_test: start")
	_run_all()
	if failed > 0:
		push_error("earth3_stack_panel_test: FAILED %s" % failed)
		quit(1)
		return
	print("earth3_stack_panel_test: passed=%s failed=0" % passed)
	print("earth3_stack_panel_test: PASS")
	quit(0)


func _run_all() -> void:
	if not _require_production_main():
		return
	_test_compact_snapshot_selects_disjoint_legal_targets()
	_test_live_slim_earth3_needs_local_fixture()
	_test_fixture_overlay_on_live_slim_earth3()


func _require_production_main() -> bool:
	if ProductionMain == null or not (ProductionMain as Script).can_instantiate():
		_fail("production Earth3 main script cannot instantiate")
		return false
	var scene = ProductionMain.new()
	var ok := scene.has_method("apply_stack_panel_fixture") \
		and scene.has_method("select_acting_battalion") \
		and scene.has_method("acting_battalion_legal_target_ids") \
		and scene.has_method("_try_build_snapshot_state")
	scene.free()
	if not ok:
		_fail("production Earth3 main is missing stack-panel fixture methods")
		return false
	_ok("production Earth3 main inherits stack-panel fixture API")
	return true


func _test_compact_snapshot_selects_disjoint_legal_targets() -> void:
	var scene = _load_snapshot_scene(COMPACT_SNAPSHOT)
	if scene == null:
		return
	_assert_stack_ready(scene, "compact snapshot")
	scene.selected_province_id = STACK_PROVINCE
	scene.select_acting_battalion(ARMOR_BN)
	var armor_targets := _target_list(scene)
	_check_eq(scene.selected_battalion_id, ARMOR_BN, "compact armor selection")
	_check(armor_targets.has(ARMOR_TARGET), "compact armor legal target is e3_0823")
	_check(not armor_targets.has(MECH_TARGET), "compact armor legal target is not e3_0845")
	_check_eq(
		_front_battalion_ids(scene),
		[ARMOR_BN],
		"compact front_by_origin follows armor battalion"
	)
	scene.select_acting_battalion(MECH_BN)
	var mech_targets := _target_list(scene)
	_check_eq(scene.selected_battalion_id, MECH_BN, "compact mechanized selection")
	_check(mech_targets.has(MECH_TARGET), "compact mechanized legal target is e3_0845")
	_check(not mech_targets.has(ARMOR_TARGET), "compact mechanized legal target is not e3_0823")
	_check_eq(
		_front_battalion_ids(scene),
		[MECH_BN],
		"compact front_by_origin follows mechanized battalion"
	)
	_check(armor_targets != mech_targets, "compact battalion switch changes legal-target identity")
	_check(
		int((scene.battalion_stacks_by_province.get(STACK_PROVINCE, []) as Array).size()) == 2,
		"compact snapshot exposes a two-battalion stack counter"
	)
	scene.free()


func _test_live_slim_earth3_needs_local_fixture() -> void:
	var scene = _load_snapshot_scene(OPERATIONAL_SNAPSHOT)
	if scene == null:
		return
	var presentations: Variant = scene.snapshot.get("stack_presentations", {})
	var empty_presentations := not (presentations is Dictionary) or (presentations as Dictionary).is_empty()
	_check(empty_presentations, "live Earth3 operational snapshot has no stack_presentations")
	_check(
		not scene.snapshot.has("battalion_presentations")
		or (scene.snapshot.get("battalion_presentations", {}) as Dictionary).is_empty(),
		"live Earth3 operational snapshot has no battalion_presentations"
	)
	var stack: Array = scene.battalion_stacks_by_province.get(STACK_PROVINCE, [])
	_check_eq(stack.size(), 1, "live slim Earth3 has a single battalion on e3_2108")
	scene.free()


func _test_fixture_overlay_on_live_slim_earth3() -> void:
	var scene = _load_snapshot_scene(OPERATIONAL_SNAPSHOT)
	if scene == null:
		return
	var fixture := _load_json(STACK_FIXTURE)
	if fixture.is_empty():
		_fail("stack panel fixture missing")
		scene.free()
		return
	_check(scene.apply_stack_panel_fixture(fixture), "overlay apply reports work")
	_assert_stack_ready(scene, "live slim + fixture")
	_check_eq(scene.selected_province_id, STACK_PROVINCE, "fixture selects the stacked Earth3 province")
	scene.select_acting_battalion(ARMOR_BN)
	var armor_targets := _target_list(scene)
	scene.select_acting_battalion(MECH_BN)
	var mech_targets := _target_list(scene)
	_check_eq(scene.selected_battalion_id, MECH_BN, "overlay mechanized selection")
	_check(armor_targets.has(ARMOR_TARGET) and not armor_targets.has(MECH_TARGET), "overlay armor identity")
	_check(mech_targets.has(MECH_TARGET) and not mech_targets.has(ARMOR_TARGET), "overlay mechanized identity")
	_check(armor_targets != mech_targets, "overlay battalion switch changes legal-target identity")
	var armor_cards: Array = (scene.snapshot.get("battalion_presentations", {}) as Dictionary).get(ARMOR_BN, {}).get("cards", [])
	var mech_cards: Array = (scene.snapshot.get("battalion_presentations", {}) as Dictionary).get(MECH_BN, {}).get("cards", [])
	_check(armor_cards.size() >= 2 and mech_cards.size() >= 2, "overlay supplies unit cards for both battalions")
	_check(
		String((armor_cards[0] as Dictionary).get("short_name", "")) != String((mech_cards[0] as Dictionary).get("short_name", "")),
		"overlay unit cards are battalion-specific"
	)
	scene.free()


func _assert_stack_ready(scene, label: String) -> void:
	var stack: Dictionary = scene.snapshot.get("stack_presentations", {}).get(STACK_PROVINCE, {})
	var members: Array = stack.get("battalion_ids", [])
	_check(members.has(ARMOR_BN) and members.has(MECH_BN), "%s stack lists both battalions" % label)
	_check_eq(int(stack.get("battalion_count", 0)), 2, "%s stack count" % label)
	var force: Dictionary = scene.snapshot.get("strategic_formation_presentations", {}).get("sf-nato-vanguard", {})
	_check_eq(int(force.get("battalion_count", 0)), 2, "%s formation membership" % label)
	var presentations: Dictionary = scene.snapshot.get("battalion_presentations", {})
	_check(presentations.has(ARMOR_BN) and presentations.has(MECH_BN), "%s battalion presentations present" % label)


func _load_snapshot_scene(path: String):
	var scene = ProductionMain.new()
	var built: Dictionary = scene._try_build_snapshot_state(path)
	if not bool(built.get("ok", false)):
		_fail("snapshot load failed for %s: %s" % [path, built.get("error", "")])
		scene.free()
		return null
	scene._commit_snapshot_state(built, "", "", false)
	return scene


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		return parsed as Dictionary
	return {}


func _target_list(scene) -> Array:
	var ids: Array = []
	for target_id in scene.acting_battalion_legal_target_ids():
		ids.append(String(target_id))
	ids.sort()
	return ids


func _front_battalion_ids(scene) -> Array:
	var ids: Array = []
	for option_variant in scene.front_by_origin.get(scene.selected_province_id, []):
		if option_variant is Dictionary:
			ids.append(String((option_variant as Dictionary).get("battalion_id", "")))
	ids.sort()
	return ids


func _ok(name: String) -> void:
	passed += 1
	print("  ok ", name)


func _fail(name: String) -> void:
	failed += 1
	push_error("  FAIL %s" % name)
	print("  FAIL ", name)


func _check(cond: bool, name: String) -> void:
	if cond:
		_ok(name)
	else:
		_fail(name)


func _check_eq(got: Variant, expected: Variant, name: String) -> void:
	if got == expected:
		_ok(name)
	else:
		_fail("%s: got=%s expected=%s" % [name, got, expected])
