extends SceneTree

var passed := 0
var failed := 0


func _initialize() -> void:
	print("map_overmap_camera_contract_test: start")
	var main_source := FileAccess.get_file_as_string("res://scripts/main.gd")
	var overlay_source := FileAccess.get_file_as_string("res://scripts/main_color_id.gd")
	var panel_source := FileAccess.get_file_as_string("res://scripts/main_stack_panel.gd")
	var writeback_source := FileAccess.get_file_as_string("res://scripts/main_writeback.gd")
	_check(main_source.find("func mark_camera_moving") >= 0, "main exposes mark_camera_moving")
	_check(main_source.find("func camera_is_moving") >= 0, "main exposes camera_is_moving")
	_check(overlay_source.find("snappedf(view_offset.x, 0.5)") < 0, "overlay cache no longer keys on pan offset")
	_check(
		overlay_source.find("scan_all := rebuild and view_scale >= 2.4 and not camera_moving") >= 0,
		"full-theatre scan is suppressed while the camera moves"
	)
	_check(
		overlay_source.find("if not _layers_dirty and viewport_key == _last_layer_viewport:") >= 0,
		"polygon camera motion does not rebuild the background layer"
	)
	_check(panel_source.find("PENDING BATTLE") >= 0, "pending modal title is PENDING BATTLE")
	_check(panel_source.find("AUTO-RESOLVE (A)") >= 0, "AUTO-RESOLVE is the primary action")
	_check(writeback_source.find("\"auto_resolve\"]") >= 0 or writeback_source.find(", \"auto_resolve\"") >= 0, "auto-resolve is admitted during presentation")
	if failed > 0:
		push_error("map_overmap_camera_contract_test: FAILED %s" % failed)
		quit(1)
		return
	if passed < 1:
		push_error("map_overmap_camera_contract_test: no assertions ran")
		quit(1)
		return
	print("map_overmap_camera_contract_test: passed=%s failed=0" % passed)
	print("map_overmap_camera_contract_test: PASS")
	quit(0)


func _check(condition: bool, label: String) -> void:
	if condition:
		passed += 1
		return
	failed += 1
	push_error("  FAIL %s" % label)
