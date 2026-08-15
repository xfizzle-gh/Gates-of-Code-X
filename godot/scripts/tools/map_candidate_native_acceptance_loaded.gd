extends "res://scripts/tools/map_candidate_native_acceptance.gd"

## #212 E3 compatibility + non-vacuous operational authority entrypoint.
##
## Snapshot loading happens in the base harness before the expensive hybrid and
## composed presentation gates are activated. This entrypoint additionally drives
## one real indexed operational formation/order before every authority comparison,
## so selected-province/legal-target parity can never pass as empty == empty.

const OPERATIONAL_ACCEPTANCE_SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"


func _initialize() -> void:
	# Owner runs without an explicit -SnapshotPath must use the committed snapshot
	# that actually contains operational orders. A caller-supplied --snapshot still
	# overrides this in the base parser and must itself satisfy the same fail-closed
	# non-empty order contract.
	_snapshot_path = OPERATIONAL_ACCEPTANCE_SNAPSHOT
	super._initialize()


func _build_scene(candidate_enabled: bool) -> Node:
	# This entrypoint legitimately receives harness-only --out/--screens-dir/size
	# flags. The legacy map CLI parser can interpret unknown user flags as its
	# optional positional manifest argument during scene _ready(). Re-pin and open
	# the exact Earth3 acceptance authority after ready and after snapshot loading,
	# before any parity sample or candidate activation is allowed to proceed.
	_clear_env()
	var packed := load("res://main.tscn") as PackedScene
	if packed == null:
		_fail("failed to load main.tscn")
		return null
	var scene := packed.instantiate()
	if scene == null:
		_fail("failed to instantiate main.tscn")
		return null
	root.add_child(scene)
	for _i in range(12):
		RenderingServer.force_draw(false, 0.0)
		await process_frame

	scene.call("_load_snapshot", _snapshot_path)
	scene.set("map_manifest_source_path", MANIFEST)
	scene.call("_open_color_id_map")
	for _i in range(3):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	if not bool(scene.get("map_backend_is_polygon")):
		_fail("scene did not load PolygonMap authority")
		return null
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready) or int(pmap.province_count) != 3514:
		_fail("scene PolygonMap authority not ready/3514")
		return null
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")

	if candidate_enabled:
		OS.set_environment(HYBRID_ENV, "hybrid")
		OS.set_environment(COMPOSED_ENV, "1")
		scene.set("composed_presentation_requested", true)
		scene.set("composed_presentation_status", "waiting_for_hybrid_candidate")
		scene.call("set_presentation_candidate_enabled", true)
		for _i in range(WAIT_FRAMES):
			var hybrid: Dictionary = scene.call("presentation_candidate_debug_state")
			var composed: Dictionary = scene.call("composed_presentation_debug_state")
			if bool(hybrid.get("active", false)) and bool(composed.get("active", false)):
				return scene
			RenderingServer.force_draw(false, 0.0)
			await process_frame
		_fail("candidate/composition failed to activate after requested snapshot load")
		return null
	var default_hybrid: Dictionary = scene.call("presentation_candidate_debug_state")
	var default_composed: Dictionary = scene.call("composed_presentation_debug_state")
	if bool(default_hybrid.get("active", false)) or bool(default_composed.get("active", false)):
		_fail("polygon control unexpectedly activated candidate")
		return null
	return scene


func _authority_state(scene: Node) -> Dictionary:
	var operational := _drive_real_operational_order(scene)
	if not bool(operational.get("ok", false)):
		return {
			"ok": false,
			"province_count": 0,
			"operational_order_error": operational.get("error", "unable to drive operational order"),
		}
	var state := super._authority_state(scene)
	var selected_province := String(state.get("selected_province_id", ""))
	var selected_formation := String(scene.get("selected_strategic_formation_id") if scene.get("selected_strategic_formation_id") != null else "")
	var legal_ids: Array = state.get("legal_target_ids", [])
	var expected_ids: Array = operational.get("expected_legal_target_ids", [])
	var selection_ok := (
		not selected_province.is_empty()
		and not selected_formation.is_empty()
		and selected_province == String(operational.get("origin_province_id", ""))
		and selected_formation == String(operational.get("formation_id", ""))
		and not legal_ids.is_empty()
		and not expected_ids.is_empty()
		and legal_ids == expected_ids
	)
	state["selected_strategic_formation_id"] = selected_formation
	state["operational_order_origin_province_id"] = String(operational.get("origin_province_id", ""))
	state["operational_order_target_ids"] = expected_ids
	state["operational_order_selection_ok"] = selection_ok
	state["ok"] = bool(state.get("ok", false)) and selection_ok
	return state


func _same_authority(reference: Dictionary, candidate: Dictionary) -> bool:
	return super._same_authority(reference, candidate) \
		and bool(candidate.get("operational_order_selection_ok", false)) \
		and candidate.get("selected_strategic_formation_id", "") == reference.get("selected_strategic_formation_id", "") \
		and candidate.get("operational_order_origin_province_id", "") == reference.get("operational_order_origin_province_id", "") \
		and candidate.get("operational_order_target_ids", []) == reference.get("operational_order_target_ids", [])


func _drive_real_operational_order(scene: Node) -> Dictionary:
	var by_province_value: Variant = scene.get("order_formations_by_province")
	var by_formation_value: Variant = scene.get("orders_by_formation")
	var snapshot_value: Variant = scene.get("snapshot")
	if not by_province_value is Dictionary or not by_formation_value is Dictionary or not snapshot_value is Dictionary:
		return {"ok": false, "error": "operational-order indexes unavailable"}
	var by_province := by_province_value as Dictionary
	var by_formation := by_formation_value as Dictionary
	if by_province.is_empty() or by_formation.is_empty():
		return {"ok": false, "error": "snapshot contains no indexed operational orders"}
	var snapshot := snapshot_value as Dictionary
	var current_faction := String((snapshot.get("campaign", {}) as Dictionary).get("current_faction", ""))
	var origins: Array = by_province.keys()
	origins.sort()
	for origin_value in origins:
		var origin := String(origin_value)
		var holders_value: Variant = by_province.get(origin, [])
		if not holders_value is Array:
			continue
		var holders: Array = (holders_value as Array).duplicate()
		holders.sort()
		for formation_value in holders:
			var formation_id := String(formation_value)
			var rows_value: Variant = by_formation.get(formation_id, [])
			if not rows_value is Array or (rows_value as Array).is_empty():
				continue
			var rows := rows_value as Array
			var faction_match := current_faction.is_empty()
			for row_value in rows:
				if not row_value is Dictionary:
					continue
				var row_faction := String((row_value as Dictionary).get("faction", ""))
				if row_faction.is_empty() or row_faction == current_faction:
					faction_match = true
					break
			if not faction_match:
				continue
			scene.set("selected_province_id", origin)
			scene.set("selected_strategic_formation_id", formation_id)
			scene.call("_rebuild_legal_targets")
			var actual_formation := String(scene.get("selected_strategic_formation_id") if scene.get("selected_strategic_formation_id") != null else "")
			if actual_formation != formation_id:
				continue
			var legal_value: Variant = scene.get("legal_targets")
			if not legal_value is Dictionary or (legal_value as Dictionary).is_empty():
				continue
			var legal_ids: Array = (legal_value as Dictionary).keys()
			legal_ids.sort()
			var expected_ids: Array = []
			for row_value in rows:
				if not row_value is Dictionary:
					continue
				var target := String((row_value as Dictionary).get("target_province_id", ""))
				if not target.is_empty() and not expected_ids.has(target):
					expected_ids.append(target)
			expected_ids.sort()
			if expected_ids.is_empty() or legal_ids != expected_ids:
				continue
			return {
				"ok": true,
				"origin_province_id": origin,
				"formation_id": formation_id,
				"expected_legal_target_ids": expected_ids,
			}
	return {"ok": false, "error": "no real operational formation produced a non-empty exact legal-target set"}
