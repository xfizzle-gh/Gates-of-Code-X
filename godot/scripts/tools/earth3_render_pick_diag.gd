extends SceneTree

## Headless/windowed Earth3 pick diagnostic.
## Samples map-local points (or --pick-at=x,y screen) and writes JSON matching
## docs/earth3-crop/hydrography_audit/owner_circle_render_trace.json fields.
##
## Godot.exe --path godot --audio-driver Dummy -s res://scripts/tools/earth3_render_pick_diag.gd -- \
##   --out=../docs/earth3-crop/hydrography_audit/owner_circle_render_trace_godot.json \
##   --snapshot=res://fixtures/snapshots/earth3_theatre.json

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/earth3_theatre.json"
const RENDER_FRAMES := 12

var _out_path := ""
var _snapshot_path := DEFAULT_SNAPSHOT
var _width := 1920
var _height := 1080
var _pick_screen := Vector2(-1, -1)
var _pick_image := Vector2(-1, -1)


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
		elif text.begins_with("--pick-at="):
			var parts := text.substr(String("--pick-at=").length()).split(",")
			if parts.size() >= 2:
				_pick_screen = Vector2(float(parts[0]), float(parts[1]))
		elif text.begins_with("--pick-image="):
			var parts2 := text.substr(String("--pick-image=").length()).split(",")
			if parts2.size() >= 2:
				_pick_image = Vector2(float(parts2[0]), float(parts2[1]))
	if _out_path.is_empty():
		push_error("earth3_render_pick_diag: --out= required")
		quit(1)
		return
	call_deferred("_run")


func _run() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
	var packed := load("res://main.tscn")
	if packed == null:
		push_error("failed to load main.tscn")
		quit(1)
		return
	var scene: Node = packed.instantiate()
	root.add_child(scene)
	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = _snapshot_path
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", _snapshot_path)
	# Force Earth3 polygon manifest (do not fall back to GoE EM).
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	for _i in RENDER_FRAMES:
		await process_frame
		if root != null and root.has_method("force_draw"):
			root.call("force_draw")
	if scene.has_method("_sync_map_space"):
		scene.call("_sync_map_space")

	var samples: Array = []
	# Default owner NE sample points in map-local image space
	var defaults: Array = [
		{"label": "NE01_northern_outline", "image": Vector2(4220, 660)},
		{"label": "NE04_WhiteSea_SE_large_hole", "image": Vector2(3618, 685)},
		{"label": "NE06_Galich_area", "image": Vector2(3376, 1273)},
		{"label": "NE07_east_volga", "image": Vector2(3597, 1356)},
		{"label": "NE08_kama_volga", "image": Vector2(3890, 1546)},
	]
	if _pick_image.x >= 0.0:
		defaults = [{"label": "pick_image", "image": _pick_image}]
	elif _pick_screen.x >= 0.0:
		defaults = [{"label": "pick_screen", "screen": _pick_screen}]

	for item in defaults:
		samples.append(_sample(scene, item))

	var am_meta := {}
	if scene.has_method("_active_map"):
		var am0 = scene.call("_active_map")
		if am0 != null:
			am_meta = {
				"class": String(am0.get_class()) if am0.has_method("get_class") else typeof(am0),
				"image_size": [am0.image_size().x, am0.image_size().y] if am0.has_method("image_size") else [],
				"province_count": am0.get("province_count") if am0.get("province_count") != null else null,
				"has_province_at_image_pos": am0.has_method("province_at_image_pos"),
			}
	var payload := {
		"schema": "gates-of-codex.earth3-owner-circle-render-trace-godot",
		"schema_version": 1,
		"viewport": [_width, _height],
		"snapshot": _snapshot_path,
		"active_map": am_meta,
		"samples": samples,
		"note": "Live Godot land hit-test via province_at_image_pos. Empty hit expected over ocean/gap (water not selectable). Gap-fill IDs from Python owner_circle_render_trace.json.",
		"authoritative_gap_and_archive_trace": "docs/earth3-crop/hydrography_audit/owner_circle_render_trace.json",
	}
	var abs_out := _out_path
	if abs_out.begins_with("res://") or abs_out.begins_with("user://"):
		abs_out = ProjectSettings.globalize_path(abs_out)
	var f := FileAccess.open(abs_out, FileAccess.WRITE)
	if f == null:
		push_error("cannot write %s" % abs_out)
		quit(2)
		return
	f.store_string(JSON.stringify(payload, "\t"))
	f.close()
	print("earth3_render_pick_diag wrote ", abs_out)
	quit(0)


func _sample(scene: Node, item: Dictionary) -> Dictionary:
	var map_space = scene.get("map_space")
	var screen := Vector2(-1, -1)
	var map_local := Vector2(-1, -1)
	if item.has("screen"):
		screen = item["screen"]
		if map_space != null and map_space.has_method("screen_to_image"):
			map_local = map_space.screen_to_image(screen)
	elif item.has("image"):
		map_local = item["image"]
		if map_space != null and map_space.has_method("image_to_screen"):
			screen = map_space.image_to_screen(map_local)
		elif map_space != null and map_space.has_method("texture_rect"):
			var tr: Rect2 = map_space.texture_rect()
			var img_sz: Vector2 = map_space.image_size_v if map_space.get("image_size_v") != null else Vector2(4306, 3449)
			if img_sz.x > 0.0 and img_sz.y > 0.0:
				screen = Vector2(
					tr.position.x + map_local.x / img_sz.x * tr.size.x,
					tr.position.y + map_local.y / img_sz.y * tr.size.y
				)

	var origin := Vector2(7076.0, 142.0)
	var am = null
	if scene.has_method("_active_map"):
		am = scene.call("_active_map")
	var hit := ""
	# Prefer image-space hit on PolygonMap (avoids broken screen mapping).
	if am != null and am.has_method("province_at_image_pos") and map_local.x >= 0.0:
		hit = String(am.call("province_at_image_pos", map_local))
	elif scene.has_method("_province_at") and screen.x >= 0.0:
		hit = String(scene.call("_province_at", screen))
	var backend := "unknown"
	var is_water_hit := false
	var source_id = null
	var row := {}
	if am != null:
		if am.get("row_by_province") != null and hit != "":
			var rbp: Dictionary = am.row_by_province
			if rbp.has(hit):
				row = rbp[hit]
				source_id = row.get("source_id", null)
				is_water_hit = bool(row.get("is_water", false))
		if String(am.get("error") if am.get("error") != null else "") != "":
			backend = "error"
		else:
			backend = "polygon" if bool(scene.get("map_backend_is_polygon")) else "color_id"

	var vp_color := []
	var vp_img: Image = root.get_texture().get_image() if root != null and root.get_texture() != null else null
	if vp_img != null and screen.x >= 0.0:
		var sx := clampi(int(screen.x), 0, vp_img.get_width() - 1)
		var sy := clampi(int(screen.y), 0, vp_img.get_height() - 1)
		var c: Color = vp_img.get_pixel(sx, sy)
		vp_color = [c.r, c.g, c.b, c.a]

	var pixel_class := "continuous_water_background"
	if hit != "" and not is_water_hit:
		pixel_class = "land_mesh"
	elif hit != "" and is_water_hit:
		pixel_class = "water_metadata_selectable_unexpected"
	elif vp_color.size() >= 3 and float(vp_color[2]) > float(vp_color[0]) + 0.02:
		pixel_class = "continuous_water_background"

	return {
		"label": String(item.get("label", "")),
		"viewport_pixel": [screen.x, screen.y],
		"viewport_rgba": vp_color,
		"map_local_xy": [map_local.x, map_local.y],
		"source_map_xy": [map_local.x + origin.x, map_local.y + origin.y],
		"province_hit_test": hit,
		"province_is_water": is_water_hit,
		"source_id": source_id,
		"land_fill_mesh_membership": hit != "" and not is_water_hit,
		"ocean_gap_fill_id": null,
		"gap_fill_note": "ocean_gap_fills not loaded by PolygonMap; see Python owner_circle_render_trace.json",
		"pixel_classification": pixel_class,
		"backend": backend,
		"view_scale": scene.get("view_scale") if scene.get("view_scale") != null else null,
	}
