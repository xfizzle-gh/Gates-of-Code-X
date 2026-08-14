class_name OperationalGraphView
extends RefCounted

## Read-only Godot view of operational_graph.json for presentation adapters.
## Does not own simulation authority.

const EM_FROM_GOE_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const INTERIM_GOE_MANIFEST := "res://assets/maps/europe/interim_goe/map_manifest.json"
const EM_OPERATIONAL_GRAPH := "res://assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
const EARTH3_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const EARTH3_MAP_ID := "earth3_europe_mediterranean"
const P3_GRAPH_RES := "res://assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"

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


func presentation_res_path(raw_path: String) -> String:
	## Map an explicit repo-root or Godot path to res:// without searching.
	## Only `res://...`, `godot/assets/...`, and `assets/...` are accepted.
	var normalized := raw_path.replace("\\", "/").strip_edges()
	if normalized.begins_with("./"):
		normalized = normalized.substr(2)
	if normalized.begins_with("res://"):
		return normalized.simplify_path()
	if normalized.begins_with("godot/"):
		normalized = normalized.substr(6)
	if normalized.begins_with("assets/"):
		return ("res://" + normalized).simplify_path()
	return ""


func _existing_presentation_path(raw_path: String) -> String:
	var trimmed := raw_path.strip_edges()
	if trimmed.is_empty():
		return ""
	if FileAccess.file_exists(trimmed):
		return trimmed
	var converted := presentation_res_path(trimmed)
	if converted.is_empty() or converted == trimmed:
		return ""
	if FileAccess.file_exists(converted):
		return converted
	return ""


func resolve_path(map_manifest_path: String, snapshot: Dictionary = {}) -> String:
	## Resolve operational graph without silently using EM data for unknown maps.
	## Earth3 production accepts only the authenticated P3 presentation graph.
	## Other maps keep:
	## 1) explicit snapshot.strategic_map.operational_graph_path
	## 2) campaign.map_metadata.operational_graph (absolute or relative to manifest)
	## 3) manifest-local operational/operational_graph.json when present
	## 4) known EM/interim manifests only → committed EM operational graph
	## else: empty (unresolved)
	var contract: Dictionary = snapshot.get("strategic_map", {})
	var campaign: Dictionary = snapshot.get("campaign", {})
	var meta: Dictionary = campaign.get("map_metadata", {})
	if _is_earth3_context(map_manifest_path, snapshot):
		var approved := _approved_earth3_graph_path(String(contract.get("operational_graph_path", "")))
		if approved.is_empty():
			approved = _approved_earth3_graph_path(String(meta.get("operational_graph", "")))
		return approved

	var exported := _existing_presentation_path(String(contract.get("operational_graph_path", "")))
	if not exported.is_empty():
		return exported

	var meta_graph := String(meta.get("operational_graph", "")).strip_edges()
	if not meta_graph.is_empty():
		var existing := _existing_presentation_path(meta_graph)
		if not existing.is_empty():
			return existing
		if not map_manifest_path.is_empty():
			var rel := map_manifest_path.get_base_dir().path_join(meta_graph).simplify_path()
			if FileAccess.file_exists(rel):
				return rel

	if not map_manifest_path.is_empty():
		var local := map_manifest_path.get_base_dir().path_join("operational/operational_graph.json").simplify_path()
		if FileAccess.file_exists(local):
			return local

	if _is_known_em_or_interim_manifest(map_manifest_path):
		if FileAccess.file_exists(EM_OPERATIONAL_GRAPH):
			return EM_OPERATIONAL_GRAPH

	return ""


func resolve_default_path(map_manifest_path: String) -> String:
	## Backward-compatible wrapper without snapshot context.
	return resolve_path(map_manifest_path, {})


func _is_earth3_context(map_manifest_path: String, snapshot: Dictionary) -> bool:
	var contract: Dictionary = snapshot.get("strategic_map", {})
	var campaign: Dictionary = snapshot.get("campaign", {})
	var meta: Dictionary = campaign.get("map_metadata", {})
	for map_id in [
		String(contract.get("map_id", "")),
		String(campaign.get("map_id", "")),
		String(meta.get("strategic_map_id", "")),
	]:
		if map_id == EARTH3_MAP_ID:
			return true
	var manifest := map_manifest_path.replace("\\", "/").simplify_path()
	if manifest == EARTH3_MANIFEST or manifest.ends_with("/earth3_europe_mediterranean/map_manifest.json"):
		return true
	return false


func _approved_earth3_graph_path(raw_path: String) -> String:
	var converted := presentation_res_path(raw_path)
	if converted != P3_GRAPH_RES:
		return ""
	if FileAccess.file_exists(P3_GRAPH_RES):
		return P3_GRAPH_RES
	return ""


func _is_known_em_or_interim_manifest(map_manifest_path: String) -> bool:
	var path := map_manifest_path.replace("\\", "/").simplify_path()
	if path.is_empty():
		return false
	if path == EM_FROM_GOE_MANIFEST or path.ends_with("/europe_mediterranean/from_goe/map_manifest.json"):
		return true
	if path == INTERIM_GOE_MANIFEST or path.ends_with("/europe/interim_goe/map_manifest.json"):
		return true
	return false
