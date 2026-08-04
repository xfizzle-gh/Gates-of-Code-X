extends "res://scripts/main_color_id.gd"


func _ready() -> void:
	super._ready()
	var args := OS.get_cmdline_user_args()
	if args.size() > 1:
		return
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	var exported_manifest := String(map_contract.get("manifest_path", "")).strip_edges()
	if exported_manifest.is_empty() or exported_manifest == map_manifest_source_path:
		return
	# Never replace a working color-ID open with a missing absolute export path
	# (stale snapshot paths previously forced the node-graph fallback).
	if not FileAccess.file_exists(exported_manifest):
		status_message = "Strategic map export path missing; kept %s" % map_manifest_source_path
		queue_redraw()
		return
	map_manifest_source_path = exported_manifest
	_open_color_id_map()
