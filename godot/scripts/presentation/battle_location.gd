class_name BattleLocation
extends RefCounted

## Map-agnostic pending-battle location resolution for Godot presentation.
## Reusable by ColorIdMap and future Earth3 polygon renderers.
##
## Priority (authoritative S6 fields first):
## 1. encounter_pixel [x, y] when valid two-number coordinate
## 2. encounter_edge_id + encounter_progress_milli via operational graph (a→b integer lerp)
## 3. encounter_node_id via operational node pixel
## 4. legacy origin/target midpoint only when no operational location exists
##
## Progress is fixed-point milli 0..1000. Interpolation matches Python:
##   x = ax + (bx - ax) * progress // 1000

const PROGRESS_MILLI_MAX := 1000
const EDGE_KINDS := ["edge_cross", "edge_catchup"]
const NODE_KINDS := ["node_contact", "node_simultaneous"]


static func resolve_pending_battle_location(
	battle: Dictionary,
	graph_index: Dictionary = {},
	legacy_origin_pixel := Vector2.INF,
	legacy_target_pixel := Vector2.INF
) -> Dictionary:
	## Returns:
	##   ok: bool
	##   map_pixel: Vector2 in map/image space (not screen)
	##   mode: "encounter_pixel" | "edge_progress" | "node" | "legacy_midpoint" | "none"
	##   draw_origin_target_line: bool
	##   encounter_kind: String
	##   detail: String
	var kind := String(battle.get("encounter_kind", "")).strip_edges()
	var result := {
		"ok": false,
		"map_pixel": Vector2.ZERO,
		"mode": "none",
		"draw_origin_target_line": false,
		"encounter_kind": kind,
		"detail": "",
	}

	var pixel_variant: Variant = battle.get("encounter_pixel", null)
	var pixel := _parse_pixel(pixel_variant)
	if pixel != Vector2.INF:
		result["ok"] = true
		result["map_pixel"] = pixel
		result["mode"] = "encounter_pixel"
		result["draw_origin_target_line"] = false
		result["detail"] = "encounter_pixel"
		return result

	var edge_id := String(battle.get("encounter_edge_id", "")).strip_edges()
	if not edge_id.is_empty() and battle.has("encounter_progress_milli"):
		var progress_raw: Variant = battle.get("encounter_progress_milli")
		if _is_int_like(progress_raw):
			var progress := clampi(int(progress_raw), 0, PROGRESS_MILLI_MAX)
			var edge_pixel := _edge_pixel(graph_index, edge_id, progress)
			if edge_pixel != Vector2.INF:
				result["ok"] = true
				result["map_pixel"] = edge_pixel
				result["mode"] = "edge_progress"
				# Authoritative edge encounters must not draw misleading origin-target line.
				result["draw_origin_target_line"] = false
				result["detail"] = "%s@%s" % [edge_id, progress]
				return result

	var node_id := String(battle.get("encounter_node_id", "")).strip_edges()
	if not node_id.is_empty():
		var node_pixel := _node_pixel(graph_index, node_id)
		if node_pixel != Vector2.INF:
			result["ok"] = true
			result["map_pixel"] = node_pixel
			result["mode"] = "node"
			result["draw_origin_target_line"] = false
			result["detail"] = node_id
			return result

	# Legacy midpoint only when no operational location exists.
	if legacy_origin_pixel != Vector2.INF and legacy_target_pixel != Vector2.INF:
		result["ok"] = true
		result["map_pixel"] = (legacy_origin_pixel + legacy_target_pixel) * 0.5
		result["mode"] = "legacy_midpoint"
		result["draw_origin_target_line"] = true
		result["detail"] = "legacy_origin_target"
		return result

	result["detail"] = "unresolved"
	return result


static func edge_lerp_pixel(a_pixel: Vector2, b_pixel: Vector2, progress_milli: int) -> Vector2:
	## Integer lerp a→b at progress 0..1000 (matches Python encounter_pixel_for_edge).
	var progress := clampi(progress_milli, 0, PROGRESS_MILLI_MAX)
	var ax := int(round(a_pixel.x))
	var ay := int(round(a_pixel.y))
	var bx := int(round(b_pixel.x))
	var by := int(round(b_pixel.y))
	var x := ax + (bx - ax) * progress / PROGRESS_MILLI_MAX
	var y := ay + (by - ay) * progress / PROGRESS_MILLI_MAX
	return Vector2(x, y)


static func is_edge_encounter_kind(kind: String) -> bool:
	return kind in EDGE_KINDS


static func is_node_encounter_kind(kind: String) -> bool:
	return kind in NODE_KINDS


static func _parse_pixel(value: Variant) -> Vector2:
	if value == null:
		return Vector2.INF
	if value is Array:
		var arr := value as Array
		if arr.size() < 2:
			return Vector2.INF
		if not _is_number(arr[0]) or not _is_number(arr[1]):
			return Vector2.INF
		return Vector2(float(arr[0]), float(arr[1]))
	return Vector2.INF


static func _is_number(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT]


static func _is_int_like(value: Variant) -> bool:
	return typeof(value) == TYPE_INT or (typeof(value) == TYPE_FLOAT and is_equal_approx(float(value), round(float(value))))


static func _node_pixel(graph_index: Dictionary, node_id: String) -> Vector2:
	var nodes: Dictionary = graph_index.get("nodes", {})
	if not nodes.has(node_id):
		return Vector2.INF
	var row: Dictionary = nodes[node_id]
	return _parse_pixel(row.get("pixel", null))


static func _edge_pixel(graph_index: Dictionary, edge_id: String, progress_milli: int) -> Vector2:
	var edges: Dictionary = graph_index.get("edges", {})
	if not edges.has(edge_id):
		return Vector2.INF
	var edge: Dictionary = edges[edge_id]
	var a_id := String(edge.get("a", ""))
	var b_id := String(edge.get("b", ""))
	var a_px := _node_pixel(graph_index, a_id)
	var b_px := _node_pixel(graph_index, b_id)
	if a_px == Vector2.INF or b_px == Vector2.INF:
		return Vector2.INF
	# Always interpolate graph a → b (canonical). Reversed edge IDs must reverse a/b in the graph,
	# not by flipping progress in presentation.
	return edge_lerp_pixel(a_px, b_px, progress_milli)
