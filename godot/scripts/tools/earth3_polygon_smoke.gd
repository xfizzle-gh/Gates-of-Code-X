extends SceneTree
func _initialize():
	call_deferred("_run")
func _run():
	var PolygonMap = load("res://scripts/polygon_map.gd")
	var pm = PolygonMap.new()
	var f = FileAccess.open("res://fixtures/snapshots/earth3_theatre.json", FileAccess.READ)
	var snap = JSON.parse_string(f.get_as_text())
	var ok = pm.open("res://assets/maps/earth3_europe_mediterranean/map_manifest.json", snap, {
		"nato": Color("4f8fd8"), "ukr": Color("e2c84a"), "rusa": Color("c95b5b"), "prc": Color("d08a3f"), "neutral": Color("707780")
	})
	print("open_ok=", ok, " err=", pm.error, " count=", pm.province_count, " load_ms=", pm.load_ms, " meshes=", pm.mesh_count)
	if ok:
		var hit = pm.province_at_image_pos(pm.centroids[10])
		print("hit_test=", hit, " expected=", pm.province_by_index[10])
	quit(0 if ok else 1)
