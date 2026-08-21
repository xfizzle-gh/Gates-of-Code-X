extends SceneTree

const HostScript = preload("res://scripts/tools/runtime_patch_completion_host.gd")

var _failed := 0
var _passed := 0


func _initialize() -> void:
	print("snapshot_field_audit_test: start")
	call_deferred("_run_all")


func _run_all() -> void:
	_test_slimmed_snapshot_loads_consumed_fields()
	print("snapshot_field_audit_test: passed=%s failed=%s" % [_passed, _failed])
	if _failed > 0:
		push_error("snapshot_field_audit_test FAIL")
		quit(1)
		return
	print("snapshot_field_audit_test: PASS")
	quit(0)


func _ok(name: String) -> void:
	_passed += 1
	print("  ok ", name)


func _fail(name: String, detail: String) -> void:
	_failed += 1
	push_error("  FAIL %s: %s" % [name, detail])
	print("  FAIL ", name, ": ", detail)


func _assert_true(name: String, cond: bool, detail := "") -> void:
	if cond:
		_ok(name)
	else:
		_fail(name, detail if not detail.is_empty() else "false")


func _slimmed_snapshot() -> Dictionary:
	return {
		"schema": "gates-of-codex.frontend",
		"schema_version": 17,
		"application": {"name": "Gates of CodeX", "turn_number": 1},
		"campaign": {
			"name": "audit",
			"turn_number": 1,
			"current_faction": "nato",
			"selected_faction": "nato",
			"map_id": "earth3_europe_mediterranean",
			"map_metadata": {
				"strategic_map_id": "earth3_europe_mediterranean",
				"operational_graph": "godot/assets/maps/earth3_europe_mediterranean/operational/operational_graph.json",
				"province_names": {"human_readable": 1, "total": 2, "human_readable_pct": 50},
			},
		},
		"strategic_map": {"map_id": "earth3_europe_mediterranean", "fallback": "none"},
		"bounds": {"min_x": 0, "max_x": 100, "min_y": 0, "max_y": 100},
		"province_names": {"human_readable": 1, "total": 2, "human_readable_pct": 50},
		"alliances": [{"id": "west", "factions": ["nato"]}],
		"objectives": [],
		"provinces": [
			{
				"id": "a",
				"display_name": "Alpha",
				"name_is_human_readable": true,
				"owner": "nato",
				"x": 0,
				"y": 0,
				"resource_yield": 1,
				"fortification": 0,
				"infrastructure": {"supply_hub": 1},
				"construction_options": [
					{"building": "supply_hub", "next_level": 2, "cost": 10, "available": true}
				],
				"site_upgrade": {"upgrade_id": "forward_depot", "status": "none", "available": true, "cost": 400},
				"occupied_by": "bn-n",
				"occupied_by_battalions": ["bn-n"],
			},
			{
				"id": "b",
				"display_name": "Bravo",
				"name_is_human_readable": true,
				"owner": "rusa",
				"x": 100,
				"y": 0,
				"resource_yield": 0,
				"fortification": 0,
				"infrastructure": {},
				"construction_options": [],
				"site_upgrade": {"upgrade_id": "forward_depot", "status": "none", "available": false, "cost": 400},
				"occupied_by": "bn-r",
				"occupied_by_battalions": ["bn-r"],
			},
		],
		"edges": [["a", "b"]],
		"formations": [{"id": "f-n", "display_name": "Alpha Brigade"}],
		"factions": [{"id": "nato", "resources": 4}, {"id": "rusa", "resources": 0}],
		"battalions": [
			{"id": "bn-n", "formation_id": "f-n", "strategic_formation_id": "sf-n", "province_id": "a", "faction": "nato", "unit_count": 1, "authorized_unit_count": 1, "condition": 100, "supply": 100, "is_in_supply": true, "battalion_type": "infantry"},
			{"id": "bn-r", "formation_id": "f-r", "strategic_formation_id": "sf-r", "province_id": "b", "faction": "rusa", "unit_count": 1, "authorized_unit_count": 1, "condition": 100, "supply": 100, "is_in_supply": true, "battalion_type": "infantry"},
		],
		"battalion_stacks": {"a": ["bn-n"], "b": ["bn-r"]},
		"stack_presentations": {
			"a": {"strategic_formation_ids": ["sf-n"]},
			"b": {"strategic_formation_ids": ["sf-r"]},
		},
		"battalion_presentations": {},
		"strategic_formation_presentations": {},
		"strategic_formations": [
			{"id": "sf-n", "faction": "nato", "province_id": "a", "display_name": "Alpha"},
			{"id": "sf-r", "faction": "rusa", "province_id": "b", "display_name": "Red"},
		],
		"pending_battle": null,
		"front_options": [],
		"operational_orders": [],
		"control": {"enabled": false},
		"fog_of_war": {"enabled": false},
		"last_known_contacts": [],
	}


func _test_slimmed_snapshot_loads_consumed_fields() -> void:
	var path := "user://snapshot_field_audit.json"
	var payload := _slimmed_snapshot()
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_fail("write slim snapshot", "unable to open %s" % path)
		return
	file.store_string(JSON.stringify(payload))
	file.close()

	var scene: Node = HostScript.new()
	root.add_child(scene)
	scene.snapshot_source_path = path
	scene._load_snapshot(path)

	_assert_true("slim snapshot loaded", scene.load_error.is_empty(), scene.load_error)
	_assert_true("schema accepted", String(scene.snapshot.get("schema", "")) == "gates-of-codex.frontend")
	_assert_true("research omitted", not scene.snapshot.has("research"))
	_assert_true("commanders omitted", not scene.snapshot.has("commanders"))
	var province: Dictionary = scene.provinces_by_id.get("a", {})
	_assert_true("province indexed", not province.is_empty())
	_assert_true("metadata omitted", not province.has("metadata"))
	_assert_true("terrain omitted", not province.has("terrain"))
	var options: Array = province.get("construction_options", [])
	_assert_true("construction_options kept", options.size() == 1)
	var site_upgrade: Dictionary = province.get("site_upgrade", {})
	_assert_true("site_upgrade kept", String(site_upgrade.get("upgrade_id", "")) == "forward_depot")
	if not options.is_empty():
		var option: Dictionary = options[0]
		_assert_true("construction building kept", String(option.get("building", "")) == "supply_hub")
		_assert_true("blocked_reasons omitted", not option.has("blocked_reasons"))
	var names: Dictionary = scene.snapshot.get("province_names", {})
	_assert_true("province_names kept", int(names.get("total", 0)) == 2)
	var meta: Dictionary = scene.snapshot.get("campaign", {}).get("map_metadata", {})
	_assert_true("map_metadata.strategic_map_id kept", String(meta.get("strategic_map_id", "")) == "earth3_europe_mediterranean")
	_assert_true("alliances kept", (scene.snapshot.get("alliances", []) as Array).size() == 1)
	scene.queue_free()
