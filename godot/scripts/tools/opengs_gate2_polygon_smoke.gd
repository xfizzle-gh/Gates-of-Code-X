extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _arg(name: String, default_value: String = "") -> String:
	var prefix := "--%s=" % name
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with(prefix):
			return arg.substr(prefix.length())
	return default_value

func _load_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed = JSON.parse_string(file.get_as_text())
	return parsed if parsed is Dictionary else {}

func _run() -> void:
	var manifest_path := _arg("manifest")
	if manifest_path.is_empty():
		push_error("missing --manifest=<path>")
		quit(2)
		return
	var manifest := _load_json(manifest_path)
	if manifest.is_empty():
		push_error("Gate 2 manifest invalid: %s" % manifest_path)
		quit(3)
		return
	var dataset_path := manifest_path.get_base_dir().path_join(
		String(manifest.get("polygon_dataset", {}).get("path", "polygon_dataset.json"))
	)
	var dataset := _load_json(dataset_path)
	if dataset.is_empty():
		push_error("Gate 2 dataset invalid: %s" % dataset_path)
		quit(4)
		return
	var PolygonMap = load("res://scripts/polygon_map.gd")
	var pm = PolygonMap.new()
	var ok = pm.open(manifest_path, {"provinces": []}, {
		"neutral": Color("707780"),
	})
	if not ok:
		push_error("Gate 2 PolygonMap open failed: %s" % pm.error)
		quit(5)
		return
	var expected := int(manifest.get("province_count", -1))
	if pm.province_count != expected or expected <= 0:
		push_error("Gate 2 province count mismatch: %d / %d" % [pm.province_count, expected])
		quit(6)
		return
	var land_row: Dictionary = {}
	var water_row: Dictionary = {}
	for value: Variant in dataset.get("provinces", []):
		if not value is Dictionary:
			continue
		var row: Dictionary = value
		var pid := String(row.get("id", ""))
		if not pid.begins_with("og2_") or pid.begins_with("e3_"):
			push_error("Gate 2 ID namespace failure: %s" % pid)
			quit(7)
			return
		if bool(row.get("is_water", false)):
			if water_row.is_empty():
				water_row = row
		elif land_row.is_empty():
			land_row = row
	if land_row.is_empty() or water_row.is_empty():
		push_error("Gate 2 smoke requires both land and water fixtures")
		quit(8)
		return
	var land_anchor: Array = land_row.get("centroid", [])
	var land_hit: String = String(pm.province_at_image_pos(Vector2(float(land_anchor[0]), float(land_anchor[1]))))
	if land_hit != String(land_row.get("id", "")):
		push_error("Gate 2 land hit-test mismatch: %s" % land_hit)
		quit(9)
		return
	var water_anchor: Array = water_row.get("centroid", [])
	var water_hit: String = String(pm.province_at_image_pos(Vector2(float(water_anchor[0]), float(water_anchor[1]))))
	if not water_hit.is_empty():
		push_error("Gate 2 water must be non-selectable: %s" % water_hit)
		quit(10)
		return
	print("gate2_open_ok=true count=", pm.province_count, " land_hit=", land_hit, " water_hit_empty=true")
	quit(0)