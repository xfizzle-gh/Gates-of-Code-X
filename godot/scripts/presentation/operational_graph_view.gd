class_name OperationalGraphView
extends RefCounted

## Read-only Godot view of operational_graph.json for presentation adapters.
## Does not own simulation authority.

var path := ""
var error := ""
var is_ready := false
var raw: Dictionary = {}
## Indexed view consumed by BattleLocation:
## { "nodes": {node_id: {pixel:[x,y], ...}}, "edges": {edge_id: {a,b,...}} }
var index: Dictionary = {"nodes": {}, "edges": {}}


func clear() -> void:
	path = ""
	error = ""
	is_ready = false
	raw = {}
	index = {"nodes": {}, "edges": {}}


func open(graph_path: String) -> bool:
	clear()
	path = graph_path
	if graph_path.is_empty() or not FileAccess.file_exists(graph_path):
		error = "operational graph not found: %s" % graph_path
		return false
	var file := FileAccess.open(graph_path, FileAccess.READ)
	if file == null:
		error = "unable to open operational graph: %s" % graph_path
		return false
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		error = "operational graph is not a JSON object"
		return false
	raw = parsed
	var nodes_out: Dictionary = {}
	for row_variant in raw.get("nodes", []):
		if not row_variant is Dictionary:
			continue
		var row := row_variant as Dictionary
		var node_id := String(row.get("node_id", "")).strip_edges()
		if node_id.is_empty():
			continue
		nodes_out[node_id] = row
	var edges_out: Dictionary = {}
	for row_variant in raw.get("edges", []):
		if not row_variant is Dictionary:
			continue
		var erow := row_variant as Dictionary
		var edge_id := String(erow.get("edge_id", "")).strip_edges()
		if edge_id.is_empty():
			continue
		edges_out[edge_id] = erow
	index = {"nodes": nodes_out, "edges": edges_out}
	is_ready = true
	error = ""
	return true


func resolve_default_path(map_manifest_path: String) -> String:
	## Prefer operational/operational_graph.json beside the strategic map manifest.
	if map_manifest_path.is_empty():
		return "res://assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
	var base := map_manifest_path.get_base_dir()
	var candidate := base.path_join("operational/operational_graph.json").simplify_path()
	if FileAccess.file_exists(candidate):
		return candidate
	var fallback := "res://assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
	if FileAccess.file_exists(fallback):
		return fallback
	return candidate
