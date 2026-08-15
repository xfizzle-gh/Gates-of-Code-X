extends "res://scripts/tools/map_ux_lod_profiler_v2.gd"

## Repeatability correction for #212 Phase D.
## Burns process-first renderer/font/resource work before any recorded LOD bracket.
## The existing 15% p50/p95 rejection gate remains unchanged.

const LOD_STABILIZATION_PASSES := 2
var _lod_process_stabilized := false


func _measure_lod_bracket(scale: float, state: Dictionary, reference: Dictionary) -> Dictionary:
	if not _lod_process_stabilized:
		for pass_index in range(LOD_STABILIZATION_PASSES):
			var warm: Dictionary = await _measure_lod_one(1.0, {}, false, reference)
			if not bool(warm.get("ok", false)):
				return {
					"ok": false,
					"error": "LOD process stabilization failed",
					"pass": pass_index,
					"detail": warm,
				}
		_lod_process_stabilized = true
	return await super._measure_lod_bracket(scale, state, reference)
