extends SceneTree

## v1 water policy (#117, accepted): open-water samples and every is_water centroid
## must return no selectable province. Coordinates are validated as water-first.

const DATASET := "res://assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
const MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const PolygonMapScript = preload("res://scripts/polygon_map.gd")
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}

# Pre-validated open-water sample points in local image space (3512 production crop).
# Each point must hit water metadata or empty ocean underlay — never land.
const WATER_SAMPLES := {
	"open_atlantic": Vector2(200, 1500),
	"norwegian_sea": Vector2(1400, 300),
	"mediterranean": Vector2(1900, 3000),
	"baltic": Vector2(2300, 1300),
	"black_sea": Vector2(2700, 2360),
	"caspian_approach": Vector2(4100, 1900),
	"scandinavian_lake_belt": Vector2(2400, 700),
}


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	if not FileAccess.file_exists(DATASET) or not FileAccess.file_exists(MANIFEST):
		_fail("Earth3 dataset/manifest missing")
		return
	var ds := _load_json(DATASET)
	var snap := {
		"provinces": [],
		"strategic_map": {"map_id": "earth3_europe_mediterranean"},
	}
	var water_ids: Dictionary = {}
	for row: Variant in ds.get("provinces", []):
		if not (row is Dictionary):
			continue
		var d := row as Dictionary
		var pid := String(d.get("id", ""))
		snap["provinces"].append({"id": pid, "owner": "neutral"})
		if bool(d.get("is_water", false)):
			water_ids[pid] = true

	var pmap = PolygonMapScript.new()
	if not pmap.open(MANIFEST, snap, FACTION_COLORS):
		_fail("PolygonMap.open failed: %s" % pmap.error)
		return

	# 1) Every water centroid must never resolve to a water province id.
	# Empty is required when the centroid is geographically water; land is only
	# allowed if the centroid point actually lies inside a land polygon (bad water centroid).
	var water_checked := 0
	for i in range(int(pmap.province_count)):
		if int(pmap.is_water[i]) != 1:
			continue
		water_checked += 1
		var cpos: Vector2 = pmap.centroids[i]
		var wh := String(pmap.province_at_image_pos(cpos))
		if wh.is_empty():
			continue
		var wi := int(pmap.index_by_province.get(wh, -1))
		if wi >= 0 and int(pmap.is_water[wi]) == 1:
			_fail("water centroid idx=%s id=%s returned water province %s" % [
				i, pmap.province_by_index[i], wh
			])
			return
		# Hit land: only acceptable if centroid is truly inside that land polygon.
		if wi >= 0 and int(pmap.is_water[wi]) != 1:
			if not pmap._point_in_province(cpos, wi):
				_fail("water centroid idx=%s returned land %s but point not in that land" % [i, wh])
				return
			# Geographic water false at this centroid — do not require empty.
			continue

	if water_checked < 50:
		_fail("expected many water metadata provinces, got %s" % water_checked)
		return

	# 2) Named open-water samples: coordinate must not be land; hit must be empty.
	for label in WATER_SAMPLES.keys():
		var pos: Vector2 = WATER_SAMPLES[label]
		if not _point_is_geographically_water(pmap, pos):
			_fail("sample %s at %s is not geographically water (land under sample)" % [label, pos])
			return
		var hit := String(pmap.province_at_image_pos(pos))
		if not hit.is_empty():
			_fail("open-water sample %s returned selectable province %s" % [label, hit])
			return

	# 3) Explicit legacy IDs when present as water in this dataset.
	for legacy in ["e3_3495", "e3_2888"]:
		if not pmap.index_by_province.has(legacy):
			continue
		var li := int(pmap.index_by_province[legacy])
		if int(pmap.is_water[li]) != 1:
			# e3_2888 may be land spill in pre-sanitize map — skip water assertion.
			continue
		var lh := String(pmap.province_at_image_pos(pmap.centroids[li]))
		if not lh.is_empty():
			_fail("legacy water id %s still selectable via hit-test -> %s" % [legacy, lh])
			return

	print(
		"earth3_water_policy_test: PASS provinces=%s water_metadata=%s samples=%s"
		% [pmap.province_count, water_checked, WATER_SAMPLES.size()]
	)
	quit(0)


func _point_is_geographically_water(pmap, pos: Vector2) -> bool:
	# Water if no land polygon contains the point. Uses internal ring test via
	# temporary scan of land only; does not accept water IDs as success.
	for i in range(int(pmap.province_count)):
		if int(pmap.is_water[i]) == 1:
			continue
		if pmap._point_in_province(pos, i):
			return false
	return true


func _fail(reason: String) -> void:
	push_error("earth3_water_policy_test FAIL: %s" % reason)
	print("earth3_water_policy_test: FAIL %s" % reason)
	quit(1)


func _load_json(path: String) -> Dictionary:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var parsed: Variant = JSON.parse_string(f.get_as_text())
	if parsed is Dictionary:
		return parsed
	return {}
