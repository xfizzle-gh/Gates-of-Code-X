extends SceneTree

## Time Godot snapshot replacement + first visible frame. Read-only.

var _snapshot_path := ""
var _out_path := "user://command-reload-latency.json"


func _initialize() -> void:
	for arg in OS.get_cmdline_user_args():
		var text := String(arg)
		if text.begins_with("--snapshot="):
			_snapshot_path = text.substr(11).strip_edges()
		elif text.begins_with("--out="):
			_out_path = text.substr(6).strip_edges()
	call_deferred("_run")


func _run() -> void:
	if _snapshot_path.is_empty() or not FileAccess.file_exists(_snapshot_path):
		_write({"ok": false, "error": "missing snapshot"})
		quit(1)
		return
	var t_all := Time.get_ticks_usec()
	var t0 := Time.get_ticks_usec()
	var file := FileAccess.open(_snapshot_path, FileAccess.READ)
	var text := file.get_as_text() if file != null else ""
	var read_ms := (Time.get_ticks_usec() - t0) / 1000.0
	t0 = Time.get_ticks_usec()
	var parsed: Variant = JSON.parse_string(text)
	var parse_ms := (Time.get_ticks_usec() - t0) / 1000.0
	var packed := load("res://scripts/main_writeback.gd")
	if packed == null:
		_write({"ok": false, "error": "failed to load main_writeback.gd"})
		quit(1)
		return
	var scene: Node = (packed as GDScript).new()
	root.add_child(scene)
	t0 = Time.get_ticks_usec()
	if scene.has_method("_try_build_snapshot_state"):
		var built: Dictionary = scene.call("_try_build_snapshot_state", _snapshot_path)
		var build_ms := (Time.get_ticks_usec() - t0) / 1000.0
		if not bool(built.get("ok", false)):
			_write({"ok": false, "error": built.get("error", "build failed"), "read_ms": read_ms, "parse_ms": parse_ms})
			quit(1)
			return
		t0 = Time.get_ticks_usec()
		if scene.has_method("_commit_snapshot_state"):
			scene.call("_commit_snapshot_state", built, "", "", false)
		if scene.has_method("_rebuild_legal_targets"):
			scene.call("_rebuild_legal_targets")
		if scene.has_method("_rebuild_focus_set"):
			scene.call("_rebuild_focus_set")
		var commit_ms := (Time.get_ticks_usec() - t0) / 1000.0
		t0 = Time.get_ticks_usec()
		if scene.has_method("queue_redraw"):
			scene.queue_redraw()
		RenderingServer.force_draw(false, 0.0)
		await process_frame
		var draw_ms := (Time.get_ticks_usec() - t0) / 1000.0
		var pending = scene.snapshot.get("pending_battle") if scene.get("snapshot") != null else null
		var modal := false
		if scene.has_method("is_pending_battle_modal_active"):
			modal = bool(scene.call("is_pending_battle_modal_active"))
		_write({
			"ok": true,
			"read_ms": read_ms,
			"parse_ms": parse_ms,
			"build_ms": build_ms,
			"commit_ms": commit_ms,
			"first_visible_ms": draw_ms,
			"total_ms": (Time.get_ticks_usec() - t_all) / 1000.0,
			"pending_battle": pending != null,
			"modal_active": modal,
			"bytes": text.length(),
		})
		quit(0)
		return
	_write({"ok": false, "error": "no _try_build_snapshot_state"})
	quit(1)


func _write(payload: Dictionary) -> void:
	var text := JSON.stringify(payload, "\t") + "\n"
	if _out_path.begins_with("user://") or _out_path.begins_with("res://"):
		var handle := FileAccess.open(_out_path, FileAccess.WRITE)
		if handle != null:
			handle.store_string(text)
		return
	DirAccess.make_dir_recursive_absolute(_out_path.get_base_dir())
	var disk := FileAccess.open(_out_path, FileAccess.WRITE)
	if disk != null:
		disk.store_string(text)
