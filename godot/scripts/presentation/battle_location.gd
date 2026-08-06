class_name BattleLocation
extends RefCounted

## Map-agnostic pending-battle location resolution for Godot presentation.
## Reusable by ColorIdMap and future Earth3 polygon renderers.
##
## Priority (authoritative S6 fields first):
## 1. encounter_pixel [x, y] when exactly two strict ints
## 2. encounter_edge_id + encounter_progress_milli (strict int 0..1000) via graph a→b
## 3. encounter_node_id via operational node pixel
## 4. legacy origin/target midpoint only when no operational location exists
##
## Edge interpolation matches Python floor division:
##   x = ax + (bx - ax) * progress // 1000

const PROGRESS_MILLI_MAX := 1000
const EDGE_KINDS := ["edge_cross", "edge_catchup"]
const NODE_KINDS := ["node_contact", "node_simultaneous"]


static func floor_div(numerator: int, denominator: int) -> int:
	## Signed floor division toward -infinity. denominator must be > 0.
	## Matches Python `//` for positive denominators.
	if denominator <= 0:
		push_error("BattleLocation.floor_div: denominator must be > 0")
		return 0
	if numerator >= 0:
		return numerator / denominator
	# ceil_div(|n|, d) then negate → floor(n/d)
	return -(((-numerator) + denominator - 1) / denominator)


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

	# 1) encounter_pixel — strict contract or continue fallback chain.
	if battle.has("encounter_pixel"):
		var pixel_variant: Variant = battle.get("encounter_pixel")
		# Empty list / null is "absent" and continues the chain.
		if not _is_absent_pixel(pixel_variant):
			var pixel := _parse_strict_pixel(pixel_variant)
			if pixel == Vector2.INF:
				# Malformed authoritative field: skip to next fallback.
				pass
			else:
				result["ok"] = true
				result["map_pixel"] = pixel
				result["mode"] = "encounter_pixel"
				result["draw_origin_target_line"] = false
				result["detail"] = "encounter_pixel"
				return result

	# 2) edge_id + progress_milli — strict int in range, no clamping of malformed values.
	var edge_id := String(battle.get("encounter_edge_id", "")).strip_edges()
	if not edge_id.is_empty() and battle.has("encounter_progress_milli"):
		var progress := _parse_strict_progress_milli(battle.get("encounter_progress_milli"))
		if progress >= 0:
			var edge_pixel := _edge_pixel(graph_index, edge_id, progress)
			if edge_pixel != Vector2.INF:
				result["ok"] = true
				result["map_pixel"] = edge_pixel
				result["mode"] = "edge_progress"
				result["draw_origin_target_line"] = false
				result["detail"] = "%s@%s" % [edge_id, progress]
				return result

	# 3) encounter_node_id
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

	# 4) Legacy midpoint only when no operational location exists.
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
	## Integer floor-lerp a→b at progress 0..1000 (matches Python encounter_pixel_for_edge).
	var progress := progress_milli
	if progress < 0 or progress > PROGRESS_MILLI_MAX:
		# Caller must only pass already-validated progress; defensive no-op pixel.
		return Vector2.INF
	var ax := int(a_pixel.x)
	var ay := int(a_pixel.y)
	var bx := int(b_pixel.x)
	var by := int(b_pixel.y)
	var x := ax + floor_div((bx - ax) * progress, PROGRESS_MILLI_MAX)
	var y := ay + floor_div((by - ay) * progress, PROGRESS_MILLI_MAX)
	return Vector2(x, y)


static func is_edge_encounter_kind(kind: String) -> bool:
	return kind in EDGE_KINDS


static func is_node_encounter_kind(kind: String) -> bool:
	return kind in NODE_KINDS


static func _is_absent_pixel(value: Variant) -> bool:
	if value == null:
		return true
	if value is Array and (value as Array).is_empty():
		return true
	return false


static func _parse_strict_pixel(value: Variant) -> Vector2:
	## Exactly two strict integers. Reject bool/float/string/null/wrong arity.
	if not value is Array:
		return Vector2.INF
	var arr := value as Array
	if arr.size() != 2:
		return Vector2.INF
	if not _is_strict_int(arr[0]) or not _is_strict_int(arr[1]):
		return Vector2.INF
	return Vector2(int(arr[0]), int(arr[1]))


static func _parse_strict_progress_milli(value: Variant) -> int:
	## Strict int in 0..1000 inclusive. Returns -1 if malformed (do not clamp).
	if not _is_strict_int(value):
		return -1
	var progress := int(value)
	if progress < 0 or progress > PROGRESS_MILLI_MAX:
		return -1
	return progress


static func _is_strict_int(value: Variant) -> bool:
	# TYPE_BOOL is distinct from TYPE_INT in Godot 4.
	return typeof(value) == TYPE_INT


static func _node_pixel(graph_index: Dictionary, node_id: String) -> Vector2:
	var nodes: Dictionary = graph_index.get("nodes", {})
	if not nodes.has(node_id):
		return Vector2.INF
	var row: Dictionary = nodes[node_id]
	# Node pixels from authored graph are trusted as int pairs when present.
	var px: Variant = row.get("pixel", null)
	if px is Array and (px as Array).size() == 2:
		var arr := px as Array
		if _is_number_like(arr[0]) and _is_number_like(arr[1]):
			return Vector2(int(round(float(arr[0]))), int(round(float(arr[1]))))
	return Vector2.INF


static func _is_number_like(value: Variant) -> bool:
	return typeof(value) in [TYPE_INT, TYPE_FLOAT]


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
	# Always interpolate graph a → b (canonical).
	return edge_lerp_pixel(a_px, b_px, progress_milli)
