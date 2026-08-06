extends SceneTree

## Screenshot capture for presentation evidence.
## Godot.exe --path godot -s res://scripts/tools/map_screenshot.gd -- --out=... --fixture=... --width=1920 --height=1080

var _out_path := "user://map_shot.png"
var _fixture_path := "res://fixtures/presentation/empty_map.json"
var _width := 1920
var _height := 1080
var _debug := false
var _frames_left := 12
var _scene: Node = null


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
		elif text.begins_with("--fixture="):
			_fixture_path = text.substr(10).strip_edges()
		elif text.begins_with("--width="):
			_width = int(text.substr(8))
		elif text.begins_with("--height="):
			_height = int(text.substr(9))
		elif text == "--debug":
			_debug = true

	DisplayServer.window_set_size(Vector2i(_width, _height))
	var packed := load("res://main.tscn")
	if packed == null:
		push_error("Unable to load main.tscn")
		quit(1)
		return
	_scene = packed.instantiate()
	root.add_child(_scene)
	if _scene.has_method("_load_presentation_fixture"):
		_scene.call("_load_presentation_fixture", _fixture_path)
	if _debug and _scene.get("map_debug") != null:
		_scene.map_debug.enabled = true
	if _scene.has_method("_fit_complete_theatre"):
		_scene.call("_fit_complete_theatre")
	if _scene.has_method("queue_redraw"):
		_scene.queue_redraw()


func _process(_delta: float) -> void:
	_frames_left -= 1
	if _scene != null and _scene.has_method("queue_redraw"):
		_scene.queue_redraw()
	if _frames_left > 0:
		return
	var image := root.get_viewport().get_texture().get_image()
	if image == null or image.is_empty():
		push_error("Viewport image empty")
		quit(2)
		return
	var err := image.save_png(_out_path)
	print("screenshot err=%s path=%s size=%sx%s" % [err, _out_path, image.get_width(), image.get_height()])
	quit(0 if err == OK else 3)
