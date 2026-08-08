class_name OperationalResolutionPresenter
extends RefCounted

## Session-only presentation of backend-authoritative operational results.
## This object never issues commands and never mutates a campaign snapshot.

const BattleLocationScript = preload("res://scripts/presentation/battle_location.gd")
const DEFAULT_DURATION_SECONDS := 0.45
const OUTCOME_DURATION_SECONDS := 2.5
const CONTACT_KIND_LABELS := {
	"node_contact": "Node Contact",
	"node_simultaneous": "Simultaneous Node Contact",
	"edge_cross": "Edge Crossing Contact",
	"edge_catchup": "Edge Catch-up Contact",
}

var duration_seconds := DEFAULT_DURATION_SECONDS
var _elapsed_seconds := 0.0
var _outcome_elapsed_seconds := 0.0
var _active := false
var _tracks: Dictionary = {}
var _contact: Dictionary = {}
var _last_contact: Dictionary = {}
var _outcome: Dictionary = {}
var _graph_index: Dictionary = {}


func begin_session(snapshot: Dictionary, graph_index: Dictionary = {}) -> void:
	reset_session()
	_graph_index = graph_index.duplicate(true)
	_contact = _contact_from_snapshot(snapshot, _graph_index)


func reset_session() -> void:
	_elapsed_seconds = 0.0
	_outcome_elapsed_seconds = 0.0
	_active = false
	_tracks.clear()
	_contact.clear()
	_last_contact.clear()
	_outcome.clear()
	_graph_index.clear()


func begin_transition(
	previous_snapshot: Dictionary,
	next_snapshot: Dictionary,
	backend_payload: Dictionary,
	graph_index: Dictionary = {}
) -> void:
	_elapsed_seconds = 0.0
	_outcome_elapsed_seconds = 0.0
	_tracks.clear()
	_outcome.clear()
	_graph_index = graph_index.duplicate(true)
	var presentation := _extract_operational_presentation(backend_payload)
	for row_variant: Variant in presentation.get("movements", []):
		if not row_variant is Dictionary:
			continue
		var track := _build_track(row_variant as Dictionary, _graph_index)
		var formation_id := String(track.get("formation_id", ""))
		if not formation_id.is_empty():
			_tracks[formation_id] = track

	var previous_contact := _contact_from_snapshot(previous_snapshot, _graph_index)
	var next_contact := _contact_from_snapshot(next_snapshot, _graph_index)
	var new_primary_contact := _is_new_primary_contact(previous_contact, next_contact)
	_contact = next_contact
	_outcome = _normalize_outcome(presentation.get("battle_finalization", {}))
	_active = _has_animated_track() or new_primary_contact
	if new_primary_contact:
		_last_contact = {
			"tracks": _tracks.duplicate(true),
			"contact": _contact.duplicate(true),
		}


func advance(delta: float) -> void:
	var safe_delta := maxf(delta, 0.0)
	if _active:
		_elapsed_seconds = minf(
			_elapsed_seconds + safe_delta,
			maxf(duration_seconds, 0.001)
		)
		if _elapsed_seconds >= maxf(duration_seconds, 0.001):
			_active = false
	if not _outcome.is_empty():
		_outcome_elapsed_seconds += safe_delta
		if _outcome_elapsed_seconds >= OUTCOME_DURATION_SECONDS:
			_outcome.clear()


func skip() -> void:
	_elapsed_seconds = maxf(duration_seconds, 0.001)
	_active = false


func is_active() -> bool:
	return _active


func active_formation_ids() -> Array:
	var ids: Array = _tracks.keys()
	ids.sort()
	return ids


func track_model() -> Dictionary:
	return _tracks.duplicate(true)


func display_pixel(formation_id: String, authoritative_pixel: Vector2) -> Vector2:
	if not _tracks.has(formation_id):
		return authoritative_pixel
	var track: Dictionary = _tracks[formation_id]
	if bool(track.get("snap_only", false)):
		return track.get("end_pixel", authoritative_pixel)
	return _sample_track(track, _progress())


func contact_model() -> Dictionary:
	return _contact.duplicate(true)


func transient_outcome() -> Dictionary:
	return _outcome.duplicate(true)


func can_replay_last_contact() -> bool:
	return not _last_contact.is_empty()


func replay_last_contact() -> bool:
	if _last_contact.is_empty():
		return false
	_tracks = (_last_contact.get("tracks", {}) as Dictionary).duplicate(true)
	_contact = (_last_contact.get("contact", {}) as Dictionary).duplicate(true)
	_outcome.clear()
	_outcome_elapsed_seconds = 0.0
	_elapsed_seconds = 0.0
	_active = true
	return true


static func contact_kind_label(kind: String) -> String:
	return String(CONTACT_KIND_LABELS.get(kind, kind.replace("_", " ").capitalize()))


func _progress() -> float:
	if not _active:
		return 1.0
	return clampf(_elapsed_seconds / maxf(duration_seconds, 0.001), 0.0, 1.0)


func _has_animated_track() -> bool:
	for track_variant: Variant in _tracks.values():
		if track_variant is Dictionary and not bool((track_variant as Dictionary).get("snap_only", false)):
			return true
	return false


func _is_new_primary_contact(previous_contact: Dictionary, next_contact: Dictionary) -> bool:
	if next_contact.is_empty():
		return false
	if previous_contact.is_empty():
		return true
	var previous_id := String(previous_contact.get("battle_id", "")).strip_edges()
	var next_id := String(next_contact.get("battle_id", "")).strip_edges()
	if previous_id.is_empty() and next_id.is_empty():
		# Older compatible snapshots may omit the identity. A transition from one
		# pending contact to another is then treated as the same contact so that a
		# handoff/status refresh cannot overwrite the session replay record.
		return false
	return previous_id != next_id


func _extract_operational_presentation(payload: Dictionary) -> Dictionary:
	if payload.has("movements") or payload.has("battle_finalization"):
		return payload.duplicate(true)
	for result_variant: Variant in payload.get("results", []):
		if not result_variant is Dictionary:
			continue
		var result := result_variant as Dictionary
		if not bool(result.get("ok", false)):
			continue
		var data: Dictionary = result.get("data", {})
		var presentation: Variant = data.get("operational_presentation", {})
		if presentation is Dictionary:
			return (presentation as Dictionary).duplicate(true)
	return {}


func _build_track(row: Dictionary, graph_index: Dictionary) -> Dictionary:
	var formation_id := String(row.get("formation_id", "")).strip_edges()
	var start_pixel := _strict_pixel(row.get("start_pixel", null))
	var end_pixel := _strict_pixel(row.get("end_pixel", null))
	if formation_id.is_empty() or start_pixel == Vector2.INF or end_pixel == Vector2.INF:
		return {}
	var points := _route_points(row, graph_index, start_pixel, end_pixel)
	var snap_only := points.size() < 2
	if snap_only:
		points = [end_pixel]
	return {
		"formation_id": formation_id,
		"start_pixel": start_pixel,
		"end_pixel": end_pixel,
		"points": points,
		"snap_only": snap_only,
	}


func _route_points(
	row: Dictionary,
	graph_index: Dictionary,
	start_pixel: Vector2,
	end_pixel: Vector2
) -> Array:
	var path_nodes: Array = row.get("path_node_ids", [])
	var path_edges: Array = row.get("path_edge_ids", [])
	if not _path_contract_valid(path_nodes, path_edges, graph_index):
		return []
	var start_position: Dictionary = row.get("start_position", {})
	var end_position: Dictionary = row.get("end_position", {})
	var start_index := _path_start_index(start_position, path_nodes, path_edges)
	var end_index := _path_end_index(end_position, path_nodes, path_edges)
	if start_index < 0 or end_index < start_index:
		return []
	var points: Array = [start_pixel]
	var first_node_after_start := start_index + 1
	if String(start_position.get("mode", "")) == "on_edge":
		first_node_after_start = start_index + 1
	var last_intermediate := end_index - 1
	if String(end_position.get("mode", "")) == "on_edge":
		last_intermediate = end_index
	for index in range(first_node_after_start, last_intermediate + 1):
		if index < 0 or index >= path_nodes.size():
			return []
		var pixel := _node_pixel(graph_index, String(path_nodes[index]))
		if pixel == Vector2.INF:
			return []
		if (points[-1] as Vector2).distance_to(pixel) > 0.001:
			points.append(pixel)
	if (points[-1] as Vector2).distance_to(end_pixel) > 0.001:
		points.append(end_pixel)
	elif points.size() == 1:
		points.append(end_pixel)
	return points


func _path_start_index(position: Dictionary, path_nodes: Array, path_edges: Array) -> int:
	var mode := String(position.get("mode", ""))
	if mode == "at_node":
		return path_nodes.find(String(position.get("node_id", "")))
	if mode == "on_edge":
		return path_edges.find(String(position.get("edge_id", "")))
	return -1


func _path_end_index(position: Dictionary, path_nodes: Array, path_edges: Array) -> int:
	var mode := String(position.get("mode", ""))
	if mode == "at_node":
		return path_nodes.find(String(position.get("node_id", "")))
	if mode == "on_edge":
		return path_edges.find(String(position.get("edge_id", "")))
	return -1


func _path_contract_valid(path_nodes: Array, path_edges: Array, graph_index: Dictionary) -> bool:
	if path_nodes.size() < 2 or path_edges.size() != path_nodes.size() - 1:
		return false
	var edges: Dictionary = graph_index.get("edges", {})
	for index in range(path_edges.size()):
		var edge_id := String(path_edges[index])
		if not edges.has(edge_id):
			return false
		var edge: Dictionary = edges[edge_id]
		var a := String(edge.get("a", ""))
		var b := String(edge.get("b", ""))
		var left := String(path_nodes[index])
		var right := String(path_nodes[index + 1])
		if not ((a == left and b == right) or (a == right and b == left)):
			return false
	return true


func _sample_track(track: Dictionary, progress: float) -> Vector2:
	var points: Array = track.get("points", [])
	if points.is_empty():
		return track.get("end_pixel", Vector2.ZERO)
	if points.size() == 1:
		return points[0]
	var total := 0.0
	var lengths: Array = []
	for index in range(points.size() - 1):
		var length := (points[index] as Vector2).distance_to(points[index + 1] as Vector2)
		lengths.append(length)
		total += length
	if total <= 0.001:
		return track.get("end_pixel", points[-1])
	var remaining := total * clampf(progress, 0.0, 1.0)
	for index in range(lengths.size()):
		var segment := float(lengths[index])
		if remaining <= segment or index == lengths.size() - 1:
			var amount := 1.0 if segment <= 0.001 else clampf(remaining / segment, 0.0, 1.0)
			return (points[index] as Vector2).lerp(points[index + 1] as Vector2, amount)
		remaining -= segment
	return track.get("end_pixel", points[-1])


func _contact_from_snapshot(snapshot: Dictionary, graph_index: Dictionary) -> Dictionary:
	var pending_variant: Variant = snapshot.get("pending_battle", null)
	if not pending_variant is Dictionary:
		return {}
	var pending := pending_variant as Dictionary
	var kind := String(pending.get("encounter_kind", "")).strip_edges()
	var resolved := BattleLocationScript.resolve_pending_battle_location(
		pending,
		graph_index
	)
	var formations: Dictionary = {}
	var sides := {
		"attacker": pending.get("attacking_participants", []),
		"defender": pending.get("defending_participants", []),
	}
	for side: String in sides:
		for row_variant: Variant in sides[side]:
			if not row_variant is Dictionary:
				continue
			var row := row_variant as Dictionary
			var formation_id := String(row.get("strategic_formation_id", "")).strip_edges()
			if formation_id.is_empty() or formations.has(formation_id):
				continue
			formations[formation_id] = {
				"formation_id": formation_id,
				"display_name": String(row.get("formation_display_name", formation_id)),
				"faction": String(row.get("faction", "")),
				"side": side,
				"contact_initiator": bool(row.get("contact_initiator", false)),
				"ambush_triggered": bool(row.get("ambush_triggered", false)),
				"ambush_strength_multiplier_milli": int(row.get("ambush_strength_multiplier_milli", 1000)),
			}
	var participant_ids: Array = formations.keys()
	participant_ids.sort()
	var ambush: Array = []
	for formation_id: String in participant_ids:
		var formation: Dictionary = formations[formation_id]
		if not bool(formation.get("ambush_triggered", false)):
			continue
		var multiplier := int(formation.get("ambush_strength_multiplier_milli", 1000))
		ambush.append({
			"formation_id": formation_id,
			"display_name": formation.get("display_name", formation_id),
			"multiplier_milli": multiplier,
			"effect_label": "+15%" if multiplier == 1150 else str(multiplier),
		})
	var encounter_pixel := Vector2.INF
	var location_mode := "none"
	var location_detail := ""
	if bool(resolved.get("ok", false)):
		encounter_pixel = resolved.get("map_pixel", Vector2.INF)
		location_mode = String(resolved.get("mode", "none"))
		location_detail = String(resolved.get("detail", ""))
	return {
		"battle_id": String(pending.get("id", "")),
		"kind": kind,
		"label": contact_kind_label(kind),
		"encounter_pixel": encounter_pixel,
		"location_mode": location_mode,
		"location_detail": location_detail,
		"participant_formation_ids": participant_ids,
		"formations": formations,
		"ambush": ambush,
	}


func _normalize_outcome(value: Variant) -> Dictionary:
	if not value is Dictionary:
		return {}
	var outcome := (value as Dictionary).duplicate(true)
	var rows: Array = []
	for row_variant: Variant in outcome.get("retreat_outcomes", []):
		if not row_variant is Dictionary:
			continue
		var row := (row_variant as Dictionary).duplicate(true)
		var pixel := _strict_pixel(row.get("destination_pixel", null))
		if pixel != Vector2.INF:
			row["destination_pixel"] = pixel
		rows.append(row)
	outcome["retreat_outcomes"] = rows
	return outcome


func _strict_pixel(value: Variant) -> Vector2:
	if not value is Array:
		return Vector2.INF
	var array := value as Array
	if array.size() != 2:
		return Vector2.INF
	if typeof(array[0]) not in [TYPE_INT, TYPE_FLOAT] or typeof(array[1]) not in [TYPE_INT, TYPE_FLOAT]:
		return Vector2.INF
	return Vector2(float(array[0]), float(array[1]))


func _node_pixel(graph_index: Dictionary, node_id: String) -> Vector2:
	var nodes: Dictionary = graph_index.get("nodes", {})
	if not nodes.has(node_id):
		return Vector2.INF
	return _strict_pixel((nodes[node_id] as Dictionary).get("pixel", null))
