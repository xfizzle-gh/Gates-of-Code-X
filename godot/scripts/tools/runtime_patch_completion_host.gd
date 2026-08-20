extends "res://scripts/main_perf_measured.gd"

var full_snapshot_loads := 0


func _ready() -> void:
	pass


func _try_build_snapshot_state(path: String) -> Dictionary:
	full_snapshot_loads += 1
	return super._try_build_snapshot_state(path)


func _load_snapshot(path: String) -> void:
	full_snapshot_loads += 1
	super._load_snapshot(path)
