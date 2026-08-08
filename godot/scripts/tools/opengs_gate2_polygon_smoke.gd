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

func _flat_ring(value: Variant) -> PackedVector2Array:
	var result := PackedVector2Array()
	if not value is Array:
		return result
	var raw: Array = value
	for i in range(0, raw.size(), 2):
		if i + 1 >= raw.size():
			break
		result.append(Vector2(float(raw[i]), float(raw[i + 1])))
	return result

func _point_in_ring(pos: Vector2, ring: PackedVector2Array) -> bool:
	var n := ring.size()
	if n < 3:
		return false
	var inside := false
	var j := n - 1
	for i in n:
		var yi := ring[i].y
		var yj := ring[j].y
		var xi := ring[i].x
		var xj := ring[j].x
		var intersect := ((yi > pos.y) != (yj > pos.y)) and (
			pos.x < (xj - xi) * (pos.y - yi) / ((yj - yi) if absf(yj - yi) > 1e-12 else 1e-12) + xi
		)
		if intersect:
			inside = not inside
		j = i
	return inside

func _component_probe(component: Dictionary) -> Vector2:
	var outer := _flat_ring(component.get("outer", []))
	if outer.is_empty():
		return Vector2.ZERO
	var sum := Vector2.ZERO
	for point: Vector2 in outer:
		sum += point
	return sum / float(outer.size())

func _run() -> void:
	var manifest_path := _arg("manifest")
	var require_multipart := _arg("require-multipart", "false") == "true"
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
	var ok = pm.open(manifest_path, {"provinces": []}, {"neutral": Color("707780")})
	if not ok:
		push_error("Gate 2 PolygonMap open failed: %s" % pm.error)
		quit(5)
		return
	var expected := int(manifest.get("province_count", -1))
	if pm.province_count != expected or expected <= 0:
		push_error("Gate 2 province count mismatch: %d / %d" % [pm.province_count, expected])
		quit(6)
		return

	var water_rows: Array[Dictionary] = []
	var land_rows: Array[Dictionary] = []
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
			water_rows.append(row)
		else:
			land_rows.append(row)
	if land_rows.is_empty() or water_rows.is_empty():
		push_error("Gate 2 smoke requires both land and water fixtures")
		quit(8)
		return

	for row in land_rows:
		var anchor: Array = row.get("centroid", [])
		var hit: String = String(pm.province_at_image_pos(Vector2(float(anchor[0]), float(anchor[1]))))
		if hit != String(row.get("id", "")):
			push_error("Gate 2 land hit-test mismatch: %s / %s" % [hit, row.get("id", "")])
			quit(9)
			return
	for row in water_rows:
		var anchor: Array = row.get("centroid", [])
		var hit: String = String(pm.province_at_image_pos(Vector2(float(anchor[0]), float(anchor[1]))))
		if not hit.is_empty():
			push_error("Gate 2 water must be non-selectable: %s -> %s" % [row.get("id", ""), hit])
			quit(10)
			return

	var hole_count := 0
	var multipart_checked := false
	for row in land_rows:
		var components: Array = row.get("components", [])
		if components.size() > 1:
			for ci in range(1, components.size()):
				var secondary: Dictionary = components[ci]
				var probe := _component_probe(secondary)
				var hit: String = String(pm.province_at_image_pos(probe))
				if hit != String(row.get("id", "")):
					push_error("Gate 2 secondary component hit-test mismatch: %s / %s" % [hit, row.get("id", "")])
					quit(11)
					return
				multipart_checked = true
		for component_value: Variant in components:
			if not component_value is Dictionary:
				continue
			var component: Dictionary = component_value
			for hole_value: Variant in component.get("holes", []):
				var hole := _flat_ring(hole_value)
				var matched_water := false
				for water in water_rows:
					var anchor: Array = water.get("centroid", [])
					var probe := Vector2(float(anchor[0]), float(anchor[1]))
					if _point_in_ring(probe, hole):
						matched_water = true
						if not String(pm.province_at_image_pos(probe)).is_empty():
							push_error("Gate 2 hole anchor selected surrounding land: %s" % water.get("id", ""))
							quit(12)
							return
				if not matched_water:
					push_error("Gate 2 land hole has no non-selectable water anchor")
					quit(13)
					return
				hole_count += 1
	if require_multipart and not multipart_checked:
		push_error("Gate 2 multipart runtime fixture did not exercise a secondary component")
		quit(14)
		return
	print(
		"gate2_open_ok=true count=", pm.province_count,
		" land_checks=", land_rows.size(),
		" water_checks=", water_rows.size(),
		" hole_checks=", hole_count,
		" multipart_checked=", multipart_checked
	)
	quit(0)
