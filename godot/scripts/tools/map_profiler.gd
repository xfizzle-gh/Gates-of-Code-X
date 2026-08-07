extends SceneTree

## Headless strategic-map presentation profiler (clean-checkout reproducible).
## Usage:
##   Godot.exe --headless --path godot -s res://scripts/tools/map_profiler.gd -- \
##     --snapshot=res://fixtures/snapshots/em_theatre_profile.json \
##     --out=../docs/godot-presentation/after_profile.json

const ColorIdMapScript = preload("res://scripts/color_id_map.gd")
const PolygonMapScript = preload("res://scripts/polygon_map.gd")
const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/em_theatre_profile.json"
const DEFAULT_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}


func _initialize() -> void:
	var out_path := ""
	var snapshot_path := DEFAULT_SNAPSHOT
	var manifest_path := DEFAULT_MANIFEST
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			out_path = text.substr(String("--out=").length()).strip_edges()
		elif text.begins_with("--snapshot="):
			snapshot_path = text.substr(String("--snapshot=").length()).strip_edges()
		elif text.begins_with("--manifest="):
			manifest_path = text.substr(String("--manifest=").length()).strip_edges()
	var metrics := _run_profile(snapshot_path, manifest_path)
	var encoded := JSON.stringify(metrics, "\t")
	print(encoded)
	if not out_path.is_empty():
		var base := out_path.get_base_dir()
		if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
			DirAccess.make_dir_recursive_absolute(base)
		var file := FileAccess.open(out_path, FileAccess.WRITE)
		if file != null:
			file.store_string(encoded)
			file.close()
	quit(0 if bool(metrics.get("ok", false)) else 1)


func _manifest_is_polygon(path: String) -> bool:
	if not FileAccess.file_exists(path):
		return false
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return false
	return f.get_as_text().find("polygon_mesh") >= 0


func _run_profile(snapshot_path: String, manifest_path: String) -> Dictionary:
	if not FileAccess.file_exists(snapshot_path):
		return {
			"ok": false,
			"error": "snapshot not found: %s" % snapshot_path,
			"snapshot_path": snapshot_path,
		}
	var snapshot := _load_json(snapshot_path)
	if snapshot.is_empty():
		return {"ok": false, "error": "snapshot invalid JSON", "snapshot_path": snapshot_path}

	var use_polygon := _manifest_is_polygon(manifest_path)
	var map_backend = PolygonMapScript.new() if use_polygon else ColorIdMapScript.new()
	var t0 := Time.get_ticks_usec()
	var opened: bool = map_backend.open(manifest_path, snapshot, FACTION_COLORS)
	var open_ms := (Time.get_ticks_usec() - t0) / 1000.0
	if not opened:
		return {
			"ok": false,
			"error": map_backend.error,
			"map_open_ms": open_ms,
			"snapshot_path": snapshot_path,
			"manifest_path": manifest_path,
			"renderer": "polygon_mesh" if use_polygon else "color_id",
		}

	var selected := _pick_selected(snapshot)
	var legal := _pick_legal_targets(snapshot, selected)

	t0 = Time.get_ticks_usec()
	for _i in range(20):
		map_backend.refresh_snapshot(snapshot, FACTION_COLORS)
	var refresh_snapshot_noop_ms := (Time.get_ticks_usec() - t0) / 1000.0 / 20.0

	var mutated := snapshot.duplicate(true)
	var provinces: Array = mutated.get("provinces", [])
	var flipped_id := ""
	if not provinces.is_empty():
		var row: Dictionary = provinces[0]
		flipped_id = String(row.get("id", ""))
		var owner := String(row.get("owner", "neutral"))
		row["owner"] = "nato" if owner != "nato" else "rusa"
		provinces[0] = row
		mutated["provinces"] = provinces
	t0 = Time.get_ticks_usec()
	map_backend.refresh_snapshot(mutated, FACTION_COLORS)
	var refresh_snapshot_partial_ms := (Time.get_ticks_usec() - t0) / 1000.0
	map_backend.refresh_snapshot(snapshot, FACTION_COLORS)

	t0 = Time.get_ticks_usec()
	for _i in range(20):
		map_backend.refresh_highlights(selected, legal)
	var refresh_highlights_noop_ms := (Time.get_ticks_usec() - t0) / 1000.0 / 20.0

	var alt_selected := selected
	for province: Dictionary in snapshot.get("provinces", []):
		var pid := String(province.get("id", ""))
		if pid != selected and not pid.is_empty():
			alt_selected = pid
			break
	t0 = Time.get_ticks_usec()
	for _i in range(20):
		var use_id := selected if (_i % 2) == 0 else alt_selected
		map_backend.refresh_highlights(use_id, legal)
	var refresh_highlights_ms := (Time.get_ticks_usec() - t0) / 1000.0 / 20.0

	t0 = Time.get_ticks_usec()
	var pick_pos := Vector2i(400, 450)
	if use_polygon and map_backend.centroids.size() > 10:
		var c: Vector2 = map_backend.centroids[10]
		pick_pos = Vector2i(int(c.x), int(c.y))
	for _i in range(50):
		if use_polygon:
			map_backend.province_at_image_pos(Vector2(pick_pos))
		else:
			map_backend.province_at_pixel(pick_pos)
	var pick_ms := (Time.get_ticks_usec() - t0) / 1000.0 / 50.0

	var ownership_stats: Dictionary = {}
	if map_backend.has_method("get_perf_stats"):
		ownership_stats = map_backend.get_perf_stats()

	var image_size: Vector2 = map_backend.image_size()
	var province_count := 0
	if use_polygon:
		province_count = int(map_backend.province_count)
	else:
		province_count = int(map_backend.row_by_province.size())

	return {
		"ok": true,
		"label": "godot-strategic-map-profile",
		"timestamp_unix": Time.get_unix_time_from_system(),
		"snapshot_path": snapshot_path,
		"manifest_path": manifest_path,
		"renderer": "polygon_mesh" if use_polygon else "color_id",
		"map_open_ms": snappedf(open_ms, 0.01),
		"refresh_snapshot_ms_avg": snappedf(refresh_snapshot_partial_ms, 0.01),
		"refresh_snapshot_noop_ms_avg": snappedf(refresh_snapshot_noop_ms, 0.001),
		"refresh_snapshot_partial_ms": snappedf(refresh_snapshot_partial_ms, 0.01),
		"refresh_highlights_ms_avg": snappedf(refresh_highlights_ms, 0.01),
		"refresh_highlights_noop_ms_avg": snappedf(refresh_highlights_noop_ms, 0.001),
		"province_pick_ms_avg": snappedf(pick_ms, 0.001),
		"flipped_province_id": flipped_id,
		"image_width": int(image_size.x),
		"image_height": int(image_size.y),
		"province_count": province_count,
		"mesh_count": int(map_backend.mesh_count) if use_polygon else 0,
		"snapshot_provinces": int(snapshot.get("provinces", []).size()),
		"snapshot_battalions": int(snapshot.get("battalions", []).size()),
		"has_background": bool(map_backend.get("has_background")) if not use_polygon else false,
		"geometry_immutable": bool(ownership_stats.get("geometry_immutable", use_polygon)),
		"perf_stats": ownership_stats,
		"notes": [
			"Headless CPU timings for map layer rebuilds (not full interactive FPS).",
			"Polygon backend: ownership refresh updates lookup texture only (geometry immutable).",
			"refresh_snapshot_ms_avg is partial single-province ownership change.",
		],
	}


func _load_json(path: String) -> Dictionary:
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if parsed is Dictionary:
		return parsed
	return {}


func _pick_selected(snapshot: Dictionary) -> String:
	var pending: Variant = snapshot.get("pending_battle")
	if pending is Dictionary:
		var origin := String((pending as Dictionary).get("origin_province_id", ""))
		if not origin.is_empty():
			return origin
	for battalion: Dictionary in snapshot.get("battalions", []):
		var pid := String(battalion.get("province_id", ""))
		if not pid.is_empty():
			return pid
	for province: Dictionary in snapshot.get("provinces", []):
		var pid2 := String(province.get("id", ""))
		if not pid2.is_empty():
			return pid2
	return ""


func _pick_legal_targets(snapshot: Dictionary, selected: String) -> Dictionary:
	var legal := {}
	for option: Dictionary in snapshot.get("front_options", []):
		if String(option.get("origin", "")) == selected:
			legal[String(option.get("target", ""))] = option
	return legal
