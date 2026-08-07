extends SceneTree

## One-shot: inject unoccupied supply/CP/air markers and screenshot a zoomed frame.
## Godot.exe --path godot --audio-driver Dummy -s res://scripts/tools/earth3_infra_screenshot.gd -- \
##   --out=../docs/godot-presentation/screenshots/earth3/pr_c_infra_zoom_1080p.png

const SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const FIXTURE := "res://fixtures/presentation/e3_operational.json"
const MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"

var _out := ""
var _width := 1920
var _height := 1080


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var t := String(arg)
		if t.begins_with("--out="):
			_out = t.substr(6).strip_edges()
		elif t.begins_with("--width="):
			_width = maxi(int(t.substr(8)), 640)
		elif t.begins_with("--height="):
			_height = maxi(int(t.substr(9)), 480)
	if _out.is_empty():
		push_error("earth3_infra_screenshot: --out= required")
		quit(1)
		return
	call_deferred("_run")


func _run() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
	var packed := load("res://main.tscn")
	var scene: Node = packed.instantiate()
	root.add_child(scene)
	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = SNAPSHOT
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", SNAPSHOT)
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = MANIFEST
	if scene.has_method("_load_presentation_fixture"):
		scene.call("_load_presentation_fixture", FIXTURE)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	for _i in 12:
		await process_frame
		if root.has_method("force_draw"):
			root.call("force_draw")

	var picks: Dictionary = {}
	if scene.has_method("ensure_unoccupied_infrastructure_markers_for_test"):
		picks = scene.call("ensure_unoccupied_infrastructure_markers_for_test")
	var am = scene.call("_active_map") if scene.has_method("_active_map") else null
	var focus_id := String(picks.get("command_post", picks.get("supply_hub", "")))
	var focus := Vector2(2100, 1700)
	if am != null and not focus_id.is_empty() and am.has_method("anchor_pixel"):
		focus = am.anchor_pixel(focus_id)
	# Use screenshot-style focus if available.
	if scene.get("view_scale") != null:
		scene.view_scale = 4.0
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	if scene.get("view_scale") != null:
		scene.view_scale = 4.0
	if scene.get("view_offset") != null and am != null:
		var img: Vector2 = am.image_size() if am.has_method("image_size") else Vector2(4306, 3449)
		# Pan so focus sits near viewport center (empirical for Earth3 home framing).
		scene.view_offset = Vector2((img.x * 0.5 - focus.x) * 0.55, (img.y * 0.45 - focus.y) * 0.55)
	if scene.get("selected_province_id") != null:
		scene.selected_province_id = ""
	if scene.get("hovered_province_id") != null:
		scene.hovered_province_id = focus_id
	if scene.has_method("_invalidate_overlay_cache"):
		scene.call("_invalidate_overlay_cache")
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()
	for _j in 20:
		await process_frame
		if root.has_method("force_draw"):
			root.call("force_draw")

	var img_out: Image = root.get_texture().get_image()
	var abs_out := _out
	if abs_out.begins_with("res://") or abs_out.begins_with("user://"):
		abs_out = ProjectSettings.globalize_path(abs_out)
	var base := abs_out.get_base_dir()
	if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	img_out.save_png(abs_out)
	print("earth3_infra_screenshot ok ", abs_out, " picks=", picks)
	quit(0)
