extends "res://scripts/tools/map_candidate_native_acceptance.gd"

## #212 E3 compatibility + non-vacuous operational authority entrypoint.
##
## Snapshot loading happens in the base harness before the expensive hybrid and
## composed presentation gates are activated. This entrypoint additionally drives
## one real indexed operational formation/order before every authority comparison,
## so selected-province/legal-target parity can never pass as empty == empty.

const OPERATIONAL_ACCEPTANCE_SNAPSHOT := "res://campaign_snapshot.json"


func _initialize() -> void:
	# Direct owner runs without an explicit --snapshot must use the current
	# production-published campaign snapshot. CI passes its freshly generated
	# Earth3 bootstrap snapshot explicitly. Either path must satisfy the same
	# fail-closed non-empty operational formation/order contract.
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


func _strategic_formation(snapshot: Dictionary, formation_id: String) -> Dictionary:
	var formations_value: Variant = snapshot.get("strategic_formations", [])
	if not formations_value is Array:
		return {}
	for formation_value: Variant in formations_value as Array:
		if not formation_value is Dictionary:
			continue
		var formation: Dictionary = formation_value as Dictionary
		if String(formation.get("id", "")) == formation_id:
			return formation
	return {}


func _order_route_is_authenticated(scene: Node, row: Dictionary) -> bool:
	var graph = scene.get("operational_graph")
	if graph == null or not bool(graph.is_ready):
		return false
	var nodes_value: Variant = graph.index.get("nodes", {})
	var edges_value: Variant = graph.index.get("edges", {})
	var path_nodes_value: Variant = row.get("path_node_ids", [])
	var path_edges_value: Variant = row.get("path_edge_ids", [])
	if not nodes_value is Dictionary or not edges_value is Dictionary:
		return false
	if not path_nodes_value is Array or not path_edges_value is Array:
		return false
	var path_nodes: Array = path_nodes_value as Array
	var path_edges: Array = path_edges_value as Array
	if path_nodes.size() < 2 or path_nodes.size() != path_edges.size() + 1:
		return false
	var nodes: Dictionary = nodes_value as Dictionary
	var edges: Dictionary = edges_value as Dictionary
	for index in range(path_edges.size()):
		var left_id := String(path_nodes[index])
		var right_id := String(path_nodes[index + 1])
		var edge_id := String(path_edges[index])
		if not nodes.has(left_id) or not nodes.has(right_id) or not edges.has(edge_id):
			return false
		var edge_value: Variant = edges.get(edge_id, null)
		if not edge_value is Dictionary:
			return false
		var edge: Dictionary = edge_value as Dictionary
		var a := String(edge.get("a", ""))
		var b := String(edge.get("b", ""))
		if not ((a == left_id and b == right_id) or (a == right_id and b == left_id)):
			return false
	return true


func _drive_real_operational_order(scene: Node) -> Dictionary:
	var by_province_value: Variant = scene.get("order_formations_by_province")
	var by_formation_value: Variant = scene.get("orders_by_formation")
	var snapshot_value: Variant = scene.get("snapshot")
	var provinces_value: Variant = scene.get("provinces_by_id")
	if not by_province_value is Dictionary or not by_formation_value is Dictionary or not snapshot_value is Dictionary:
		return {"ok": false, "error": "operational-order indexes unavailable"}
	if not provinces_value is Dictionary:
		return {"ok": false, "error": "province index unavailable"}
	var by_province := by_province_value as Dictionary
	var by_formation := by_formation_value as Dictionary
	if by_province.is_empty() or by_formation.is_empty():
		return {"ok": false, "error": "snapshot contains no indexed operational orders"}
	var snapshot := snapshot_value as Dictionary
	var provinces := provinces_value as Dictionary
	var campaign_value: Variant = snapshot.get("campaign", {})
	if not campaign_value is Dictionary:
		return {"ok": false, "error": "campaign metadata unavailable"}
	var current_faction := String((campaign_value as Dictionary).get("current_faction", ""))
	var origins: Array = by_province.keys()
	origins.sort()
	for origin_value in origins:
		var origin := String(origin_value)
		if origin.is_empty() or not provinces.has(origin):
			continue
		var holders_value: Variant = by_province.get(origin, [])
		if not holders_value is Array:
			continue
		var holders: Array = (holders_value as Array).duplicate()
		holders.sort()
		for formation_value in holders:
			var formation_id := String(formation_value)
			var formation: Dictionary = _strategic_formation(snapshot, formation_id)
			if formation.is_empty() or String(formation.get("province_id", "")) != origin:
				continue
			var formation_faction := String(formation.get("faction", ""))
			if not current_faction.is_empty() and formation_faction != current_faction:
				continue
			var rows_value: Variant = by_formation.get(formation_id, [])
			if not rows_value is Array or (rows_value as Array).is_empty():
				continue
			var rows: Array = rows_value as Array
			var expected_ids: Array = []
			var all_rows_authenticated := true
			for row_value in rows:
				if not row_value is Dictionary:
					all_rows_authenticated = false
					break
				var row: Dictionary = row_value as Dictionary
				if String(row.get("formation_id", "")) != formation_id or String(row.get("origin_province_id", "")) != origin:
					all_rows_authenticated = false
					break
				var row_faction := String(row.get("faction", ""))
				if not row_faction.is_empty() and row_faction != formation_faction:
					all_rows_authenticated = false
					break
				var target := String(row.get("target_province_id", ""))
				if target.is_empty() or not provinces.has(target) or not _order_route_is_authenticated(scene, row):
					all_rows_authenticated = false
					break
				if not expected_ids.has(target):
					expected_ids.append(target)
			if not all_rows_authenticated or expected_ids.is_empty():
				continue
			expected_ids.sort()
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
			if legal_ids != expected_ids:
				continue
			return {
				"ok": true,
				"origin_province_id": origin,
				"formation_id": formation_id,
				"expected_legal_target_ids": expected_ids,
			}
	return {"ok": false, "error": "no authenticated operational formation produced a non-empty exact legal-target set"}
