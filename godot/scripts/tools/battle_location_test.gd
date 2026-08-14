extends SceneTree

## Direct GDScript runtime tests for BattleLocation (not a Python mirror).
## Godot.exe --headless --path godot -s res://scripts/tools/battle_location_test.gd

const BattleLocationScript = preload("res://scripts/presentation/battle_location.gd")
const OperationalGraphViewScript = preload("res://scripts/presentation/operational_graph_view.gd")
const GRAPH_PATH := "res://assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
const EDGE_ID := "op-edge-corridor-op-node-Baden-anchor__op-node-Franken-anchor"

var _failed := 0
var _passed := 0


func _initialize() -> void:
	print("battle_location_test: start")
	_test_floor_div()
	_test_baden_franken_250()
	_test_negative_delta_lerp()
	_test_progress_endpoints()
	_test_resolve_priority_and_contract()
	_test_graph_fallback_safety()
	print("battle_location_test: passed=%s failed=%s" % [_passed, _failed])
	if _failed > 0:
		push_error("battle_location_test FAIL")
		quit(1)
		return
	print("battle_location_test: PASS")
	quit(0)


func _ok(name: String) -> void:
	_passed += 1
	print("  ok ", name)


func _fail(name: String, detail: String) -> void:
	_failed += 1
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
		_fail(name, detail if not detail.is_empty() else "condition false")


func _test_floor_div() -> void:
	_assert_eq("floor_div positive", BattleLocationScript.floor_div(6000, 1000), 6)
	_assert_eq("floor_div negative exact", BattleLocationScript.floor_div(-8000, 1000), -8)
	_assert_eq("floor_div negative floor", BattleLocationScript.floor_div(-7250, 1000), -8)
	_assert_eq("floor_div toward -inf", BattleLocationScript.floor_div(-1, 1000), -1)
	_assert_eq("floor_div zero", BattleLocationScript.floor_div(0, 1000), 0)


func _test_baden_franken_250() -> void:
	var a := Vector2(319, 512)
	var b := Vector2(343, 483)
	var got := BattleLocationScript.edge_lerp_pixel(a, b, 250)
	_assert_eq("Baden→Franken@250", got, Vector2(325, 504))


func _test_negative_delta_lerp() -> void:
	# Synthetic negative X and Y deltas.
	var a := Vector2(100, 100)
	var b := Vector2(50, 20)
	_assert_eq("neg-delta@0", BattleLocationScript.edge_lerp_pixel(a, b, 0), Vector2(100, 100))
	_assert_eq("neg-delta@250", BattleLocationScript.edge_lerp_pixel(a, b, 250), Vector2(87, 80))
	_assert_eq("neg-delta@500", BattleLocationScript.edge_lerp_pixel(a, b, 500), Vector2(75, 60))
	_assert_eq("neg-delta@1000", BattleLocationScript.edge_lerp_pixel(a, b, 1000), Vector2(50, 20))


func _test_progress_endpoints() -> void:
	var a := Vector2(319, 512)
	var b := Vector2(343, 483)
	_assert_eq("progress0", BattleLocationScript.edge_lerp_pixel(a, b, 0), a)
	_assert_eq("progress500", BattleLocationScript.edge_lerp_pixel(a, b, 500), Vector2(331, 497))
	_assert_eq("progress1000", BattleLocationScript.edge_lerp_pixel(a, b, 1000), b)


func _load_graph_index() -> Dictionary:
	var view = OperationalGraphViewScript.new()
	_assert_true("graph open", view.open(GRAPH_PATH), view.error)
	return view.index


func _test_resolve_priority_and_contract() -> void:
	var index := _load_graph_index()

	# encounter_pixel authority
	var r := BattleLocationScript.resolve_pending_battle_location({
		"encounter_kind": "edge_cross",
		"encounter_pixel": [111, 222],
		"encounter_edge_id": EDGE_ID,
		"encounter_progress_milli": 0,
		"encounter_node_id": "op-node-Baden-anchor",
	}, index)
	_assert_eq("pixel authority mode", r.get("mode"), "encounter_pixel")
	_assert_eq("pixel authority value", r.get("map_pixel"), Vector2(111, 222))
	_assert_eq("pixel no line", r.get("draw_origin_target_line"), false)

	# Strict pixel rejects
	for bad in [[1], [1, 2, 3], [1.5, 2], ["1", "2"], [true, false], null]:
		var br := BattleLocationScript.resolve_pending_battle_location({
			"encounter_pixel": bad,
			"encounter_edge_id": EDGE_ID,
			"encounter_progress_milli": 250,
		}, index)
		# Malformed pixel continues to edge fallback when edge is valid.
		if bad == null or (bad is Array and (bad as Array).is_empty()):
			continue
		_assert_true(
			"malformed pixel falls through (%s)" % str(bad),
			str(br.get("mode")) != "encounter_pixel",
			"mode=%s" % br.get("mode")
		)

	# Empty pixel list is absent → edge
	r = BattleLocationScript.resolve_pending_battle_location({
		"encounter_kind": "edge_cross",
		"encounter_pixel": [],
		"encounter_edge_id": EDGE_ID,
		"encounter_progress_milli": 250,
	}, index)
	_assert_eq("empty pixel → edge mode", r.get("mode"), "edge_progress")
	_assert_eq("empty pixel → edge@250", r.get("map_pixel"), Vector2(325, 504))

	# Edge progress 0/250/500/1000
	for item in [[0, Vector2(319, 512)], [250, Vector2(325, 504)], [500, Vector2(331, 497)], [1000, Vector2(343, 483)]]:
		var p: int = item[0]
		var exp: Vector2 = item[1]
		r = BattleLocationScript.resolve_pending_battle_location({
			"encounter_kind": "edge_catchup",
			"encounter_pixel": [],
			"encounter_edge_id": EDGE_ID,
			"encounter_progress_milli": p,
		}, index)
		_assert_eq("edge@%s" % p, r.get("map_pixel"), exp)
		_assert_eq("edge@%s no line" % p, r.get("draw_origin_target_line"), false)

	# Malformed progress rejects (no clamp) → fall through
	for bad_p in [null, 1.5, "500", true, -1, 1001]:
		r = BattleLocationScript.resolve_pending_battle_location({
			"encounter_kind": "edge_cross",
			"encounter_pixel": [],
			"encounter_edge_id": EDGE_ID,
			"encounter_progress_milli": bad_p,
			"encounter_node_id": "op-node-Baden-anchor",
		}, index)
		_assert_eq("bad progress %s → node" % str(bad_p), r.get("mode"), "node")

	# Reversed endpoints: progress always a→b from graph
	r = BattleLocationScript.resolve_pending_battle_location({
		"encounter_kind": "edge_cross",
		"encounter_edge_id": EDGE_ID,
		"encounter_progress_milli": 250,
		"encounter_pixel": [],
	}, index)
	_assert_eq("graph a→b @250", r.get("map_pixel"), Vector2(325, 504))
	var reversed_pixel := BattleLocationScript.edge_lerp_pixel(Vector2(343, 483), Vector2(319, 512), 250)
	_assert_true("not reversed lerp", r.get("map_pixel") != reversed_pixel)

	# node_contact / node_simultaneous
	r = BattleLocationScript.resolve_pending_battle_location({
		"encounter_kind": "node_contact",
		"encounter_node_id": "op-node-Baden-anchor",
		"encounter_pixel": [],
	}, index)
	_assert_eq("node_contact", r.get("map_pixel"), Vector2(319, 512))
	_assert_eq("node_contact mode", r.get("mode"), "node")

	r = BattleLocationScript.resolve_pending_battle_location({
		"encounter_kind": "node_simultaneous",
		"encounter_node_id": "op-node-Hannover-anchor",
		"encounter_pixel": [],
	}, index)
	_assert_eq("node_simultaneous mode", r.get("mode"), "node")
	_assert_true("node_simultaneous ok", bool(r.get("ok")))

	# Legacy midpoint
	r = BattleLocationScript.resolve_pending_battle_location({
		"encounter_kind": "",
		"encounter_pixel": [],
		"encounter_edge_id": "",
		"encounter_node_id": "",
	}, index, Vector2(0, 0), Vector2(10, 20))
	_assert_eq("legacy mode", r.get("mode"), "legacy_midpoint")
	_assert_eq("legacy pixel", r.get("map_pixel"), Vector2(5, 10))
	_assert_eq("legacy line", r.get("draw_origin_target_line"), true)

	# Fully unresolved
	r = BattleLocationScript.resolve_pending_battle_location({}, {})
	_assert_eq("unresolved", r.get("ok"), false)


func _test_graph_fallback_safety() -> void:
	var view = OperationalGraphViewScript.new()
	# Unknown / Earth3-like manifest must NOT silently load EM graph.
	var unknown := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
	var path := view.resolve_path(unknown, {})
	_assert_eq("unknown manifest no silent EM graph", path, "")

	# Known EM manifest may use EM graph.
	var em := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
	path = view.resolve_path(em, {})
	_assert_true("EM manifest resolves graph", path.ends_with("operational_graph.json"), path)

	# Explicit snapshot path still wins for non-Earth3 maps.
	var custom := "res://assets/maps/not-a-real-map/map_manifest.json"
	path = view.resolve_path(custom, {
		"strategic_map": {
			"operational_graph_path": GRAPH_PATH,
		}
	})
	_assert_eq("explicit snapshot graph path", path, GRAPH_PATH)

	# An existing unapproved graph must not load for Earth3.
	_assert_true("EM candidate exists", FileAccess.file_exists(GRAPH_PATH), GRAPH_PATH)
	path = view.resolve_path(unknown, {
		"strategic_map": {
			"map_id": "earth3_europe_mediterranean",
			"operational_graph_path": GRAPH_PATH,
		},
		"campaign": {
			"map_id": "earth3_europe_mediterranean",
			"map_metadata": {
				"operational_graph": GRAPH_PATH,
			}
		}
	})
	_assert_eq("Earth3 rejects existing EM candidate", path, "")

	var p3_repo := "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"
	var p3_res := "res://assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"
	path = view.resolve_path(unknown, {
		"campaign": {
			"map_metadata": {
				"operational_graph": p3_repo,
			}
		}
	})
	_assert_eq("repo-root godot/ prefix maps to res://assets", path, p3_res)
	_assert_true("mapped P3 path exists", FileAccess.file_exists(path), path)
	path = view.resolve_path(unknown, {
		"strategic_map": {
			"operational_graph_path": "res://godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json",
		}
	})
	_assert_eq("wrong res://godot/ conversion fails closed", path, "")
