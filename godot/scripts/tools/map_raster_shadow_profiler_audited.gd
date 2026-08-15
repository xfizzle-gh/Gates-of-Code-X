extends "res://scripts/tools/map_raster_shadow_profiler.gd"

## Independent-audit correction layer for #212 Phase B.
##
## Keeps the original matrix implementation intact, but closes three proof gaps:
## - burn process-first renderer/resource warmup before the first recorded bracket;
## - require a real non-empty legal graph target set from authoritative orders;
## - require refreshed raster pixels to match the expected authoritative owner color.

const STABILIZATION_PASSES := 2
const OWNER_COLOR_TOLERANCE := 0.012

var _process_stabilized := false


func _measure_bracket(mode_name: String, tile_size: int, scenario: String, reference: Dictionary) -> Dictionary:
	if not _process_stabilized:
		for pass_index in range(STABILIZATION_PASSES):
			var warm := await super._measure_one("polygon", 0, "idle_full_theatre", reference)
			if not bool(warm.get("ok", false)):
				return {
					"ok": false,
					"error": "process stabilization failed",
					"pass": pass_index,
					"detail": warm,
				}
		_process_stabilized = true
	return await super._measure_bracket(mode_name, tile_size, scenario, reference)


func _prepare_nonempty_legal_targets(scene: Node) -> bool:
	if scene.has_method("_rebuild_legal_targets"):
		scene.call("_rebuild_legal_targets")
	var current: Variant = scene.get("legal_targets")
	if current is Dictionary and not (current as Dictionary).is_empty():
		return true

	var orders_value: Variant = scene.get("orders_by_formation")
	if not orders_value is Dictionary:
		return false
	var orders := orders_value as Dictionary
	var formation_ids: Array = orders.keys()
	formation_ids.sort()
	for formation_value in formation_ids:
		var formation_id := String(formation_value)
		var rows_value: Variant = orders.get(formation_id, [])
		if not rows_value is Array or (rows_value as Array).is_empty():
			continue
		var rows := rows_value as Array
		var first_value: Variant = rows[0]
		if not first_value is Dictionary:
			continue
		var first := first_value as Dictionary
		var origin := String(first.get("origin_province_id", ""))
		if origin.is_empty():
			continue
		if scene.get("selected_strategic_formation_id") != null:
			scene.selected_strategic_formation_id = formation_id
		if scene.get("selected_province_id") != null:
			scene.selected_province_id = origin
		if scene.has_method("_rebuild_legal_targets"):
			scene.call("_rebuild_legal_targets")
		current = scene.get("legal_targets")
		if current is Dictionary and not (current as Dictionary).is_empty():
			return true
	return false


func _authority_parity(scene: Node, active_map) -> Dictionary:
	if not _prepare_nonempty_legal_targets(scene):
		return {
			"ok": false,
			"error": "no authoritative non-empty legal-target state",
			"legal_target_ids": [],
		}
	var parity := super._authority_parity(scene, active_map)
	var legal_ids: Array = parity.get("legal_target_ids", [])
	parity["selected_strategic_formation_id"] = String(
		scene.get("selected_strategic_formation_id") if scene.get("selected_strategic_formation_id") != null else ""
	)
	parity["nonempty_legal_targets"] = not legal_ids.is_empty()
	parity["ok"] = bool(parity.get("ok", false)) \
		and bool(parity.get("nonempty_legal_targets", false)) \
		and not String(parity.get("selected_strategic_formation_id", "")).is_empty()
	return parity


func _same_parity(reference: Dictionary, candidate: Dictionary) -> bool:
	return super._same_parity(reference, candidate) \
		and bool(reference.get("nonempty_legal_targets", false)) \
		and bool(candidate.get("nonempty_legal_targets", false)) \
		and candidate.get("selected_strategic_formation_id", "") == reference.get("selected_strategic_formation_id", "")


func _owner_refresh_check() -> Dictionary:
	var built := await _build_scene()
	if not bool(built.get("ok", false)):
		return built
	var scene: Node = built.get("scene")
	var active_map = _active_map(scene)
	var error := _authority_error(scene, active_map)
	if not error.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": error}

	var target := -1
	for i in range(active_map.is_water.size()):
		if int(active_map.is_water[i]) == 0:
			target = i
			break
	if target < 0:
		await _dispose_scene(scene)
		return {"ok": false, "error": "no land province"}

	var before := await _capture_static_map(scene, active_map)
	var snapshot_copy: Dictionary = scene.snapshot.duplicate(true)
	var provinces: Array = snapshot_copy.get("provinces", [])
	var pid := String(active_map.province_by_index[target])
	var old_owner := ""
	var new_owner := ""
	for j in range(provinces.size()):
		var row_value: Variant = provinces[j]
		if not row_value is Dictionary:
			continue
		var row := row_value as Dictionary
		if String(row.get("id", "")) == pid:
			old_owner = String(row.get("owner", "neutral"))
			new_owner = "rusa" if old_owner != "rusa" else "nato"
			row["owner"] = new_owner
			provinces[j] = row
			break
	if new_owner.is_empty():
		await _dispose_scene(scene)
		return {"ok": false, "error": "province missing from snapshot", "province_id": pid}

	snapshot_copy["provinces"] = provinces
	scene.snapshot = snapshot_copy
	active_map.refresh_snapshot(scene.snapshot, FACTION_COLORS)
	await _pump_frames(scene, 4)
	var after := await _capture_static_map(scene, active_map)
	var pos := Vector2i(
		clampi(int(round(active_map.centroids[target].x * CACHE_SCALE)), 0, before.get_width() - 1),
		clampi(int(round(active_map.centroids[target].y * CACHE_SCALE)), 0, before.get_height() - 1)
	)
	var prior_color := before.get_pixelv(pos)
	var actual_color := after.get_pixelv(pos)
	var expected_color: Color = FACTION_COLORS.get(new_owner, FACTION_COLORS["neutral"])
	var color_error := maxf(
		maxf(absf(actual_color.r - expected_color.r), absf(actual_color.g - expected_color.g)),
		absf(actual_color.b - expected_color.b)
	)
	var owner_ok := String(active_map.owners[target]) == new_owner
	var exact_owner_color_match := color_error <= OWNER_COLOR_TOLERANCE
	var changed := prior_color.distance_to(actual_color) > 0.01
	await _dispose_scene(scene)
	return {
		"ok": owner_ok and exact_owner_color_match and changed,
		"province_id": pid,
		"old_owner": old_owner,
		"new_owner": new_owner,
		"polygon_owner_state_applied": owner_ok,
		"expected_owner_color": _color_row(expected_color),
		"cached_owner_color": _color_row(actual_color),
		"owner_color_max_channel_error": snappedf(color_error, 0.0001),
		"owner_color_tolerance": OWNER_COLOR_TOLERANCE,
		"exact_owner_color_match": exact_owner_color_match,
		"cached_pixel_changed": changed,
	}


func _color_row(color: Color) -> Array:
	return [
		snappedf(color.r, 0.0001),
		snappedf(color.g, 0.0001),
		snappedf(color.b, 0.0001),
		snappedf(color.a, 0.0001),
	]
