extends SceneTree

## True runtime viewport capture of main.tscn.
## Requires a real rendering backend (windowed or xvfb). Do not use pure --headless dummy renderer.
## Waits for processed + rendered frames via force_draw + timers, then
## saves root.get_texture().get_image() — the actual CanvasItem output.
##
## Godot.exe --path godot --audio-driver Dummy -s res://scripts/tools/map_screenshot.gd -- \
##   --out=shot.png --width=1920 --height=1080 \
##   --snapshot=res://fixtures/snapshots/em_theatre_profile.json \
##   --fixture=res://fixtures/presentation/routes_and_battles.json

const DEFAULT_SNAPSHOT := "res://fixtures/snapshots/em_theatre_profile.json"
const DEFAULT_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const DEFAULT_FIXTURE := "res://fixtures/presentation/empty_map.json"
const RENDER_FRAMES := 16

var _out_path := ""
var _fixture_path := DEFAULT_FIXTURE
var _snapshot_path := DEFAULT_SNAPSHOT
var _width := 1920
var _height := 1080
var _debug := false
var _select_first := false
var _hover_second := false


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--fixture="):
			_fixture_path = text.substr(10).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--width="):
			_width = maxi(int(text.substr(8)), 640)
		elif text.begins_with("--height="):
			_height = maxi(int(text.substr(9)), 480)
		elif text == "--debug":
			_debug = true
		elif text == "--select-first":
			_select_first = true
		elif text == "--hover-second":
			_hover_second = true

	if _out_path.is_empty():
		push_error("map_screenshot: --out= is required")
		quit(1)
		return
	if not FileAccess.file_exists(_snapshot_path):
		push_error("map_screenshot: snapshot missing: %s" % _snapshot_path)
		quit(1)
		return
	call_deferred("_run_capture")


func _run_capture() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	var packed := load("res://main.tscn")
	if packed == null:
		push_error("map_screenshot: failed to load main.tscn")
		quit(1)
		return
	var scene: Node = packed.instantiate()
	if scene == null:
		push_error("map_screenshot: failed to instantiate main.tscn")
		quit(1)
		return
	root.add_child(scene)

	# Explicit snapshot/fixture only.
	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = _snapshot_path
	if scene.has_method("_load_snapshot"):
		scene.call("_load_snapshot", _snapshot_path)
	if not str(scene.get("load_error") if scene.get("load_error") != null else "").is_empty():
		push_error("map_screenshot: snapshot load_error=%s" % scene.load_error)
		quit(2)
		return
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = DEFAULT_MANIFEST
	if scene.has_method("_load_presentation_fixture"):
		scene.call("_load_presentation_fixture", _fixture_path)
	if scene.has_method("_open_color_id_map"):
		scene.call("_open_color_id_map")
	if _debug and scene.get("map_debug") != null:
		scene.map_debug.enabled = true
		if scene.has_method("set_process"):
			scene.set_process(true)
	_apply_selection_hover(scene)
	if scene.has_method("_fit_complete_theatre"):
		scene.call("_fit_complete_theatre")
	if scene.get("_layers_dirty") != null:
		scene._layers_dirty = true
	if scene.has_method("_sync_presentation_layers"):
		scene.call("_sync_presentation_layers")
	if scene.has_method("queue_redraw"):
		scene.queue_redraw()

	if scene.get("color_id_map") == null or not bool(scene.color_id_map.is_ready):
		var err := ""
		if scene.get("color_id_map") != null:
			err = str(scene.color_id_map.error)
		push_error("map_screenshot: color_id_map not ready: %s" % err)
		quit(2)
		return
	var bg := scene.find_child("MapBackgroundLayer", true, false)
	var identity := scene.find_child("MapIdentityLayer", true, false)
	if bg == null or identity == null:
		push_error("map_screenshot: missing MapBackgroundLayer/MapIdentityLayer")
		quit(2)
		return
	if int(bg.texture_filter) != int(CanvasItem.TEXTURE_FILTER_LINEAR):
		push_error("map_screenshot: background filter must be LINEAR (got %s)" % bg.texture_filter)
		quit(2)
		return
	if int(identity.texture_filter) != int(CanvasItem.TEXTURE_FILTER_NEAREST):
		push_error("map_screenshot: identity filter must be NEAREST (got %s)" % identity.texture_filter)
		quit(2)
		return

	print("map_screenshot: rendering frames via live CanvasItems")
	for i in range(RENDER_FRAMES):
		if scene.get("_layers_dirty") != null:
			scene._layers_dirty = true
		if scene.has_method("_sync_presentation_layers"):
			scene.call("_sync_presentation_layers")
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await create_timer(0.04).timeout

	var image: Image = null
	if root is Viewport:
		var tex: ViewportTexture = (root as Viewport).get_texture()
		if tex != null:
			image = tex.get_image()
	if image == null or image.is_empty():
		push_error("map_screenshot: viewport image empty after %s rendered frames" % RENDER_FRAMES)
		quit(3)
		return

	var base := _out_path.get_base_dir()
	if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	var err := image.save_png(_out_path)
	if err != OK:
		push_error("map_screenshot: save_png failed err=%s path=%s" % [err, _out_path])
		quit(4)
		return
	if not FileAccess.file_exists(_out_path):
		push_error("map_screenshot: output missing after save: %s" % _out_path)
		quit(4)
		return
	# Reject pure-clear frames (draw path did not run).
	var sample := image.get_pixel(image.get_width() / 2, image.get_height() / 2)
	if sample.r + sample.g + sample.b < 0.05:
		push_error("map_screenshot: center pixel nearly black — draw path likely skipped")
		quit(5)
		return
	print(
		"screenshot ok path=%s size=%sx%s frames=%s center=(%s,%s,%s) filters=bg:%s id:%s" % [
			_out_path,
			image.get_width(),
			image.get_height(),
			RENDER_FRAMES,
			snappedf(sample.r, 0.01),
			snappedf(sample.g, 0.01),
			snappedf(sample.b, 0.01),
			bg.texture_filter,
			identity.texture_filter,
		]
	)
	quit(0)


func _apply_selection_hover(scene: Node) -> void:
	if scene.get("color_id_map") == null or not bool(scene.color_id_map.is_ready):
		return
	var ids: Array = []
	for pid: Variant in scene.color_id_map.row_by_province.keys():
		ids.append(String(pid))
		if ids.size() >= 3:
			break
	if ids.is_empty():
		return
	if _select_first:
		scene.selected_province_id = String(ids[0])
		if scene.has_method("_rebuild_legal_targets"):
			scene.call("_rebuild_legal_targets")
		if scene.has_method("_rebuild_focus_set"):
			scene.call("_rebuild_focus_set")
	if _hover_second and ids.size() > 1:
		scene.hovered_province_id = String(ids[1])
