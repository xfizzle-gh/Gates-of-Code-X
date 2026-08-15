extends "res://scripts/tools/map_icon_atlas_profiler.gd"

## Independent-repeatability correction for #212 Phase C.
## Burn process-first renderer/font/resource work before any recorded counter
## bracket. The existing 15% local p50/p95 rejection contract is unchanged.

const COUNTER_STABILIZATION_PASSES := 2
var _counter_process_stabilized := false


func _measure_counter_bracket(mode: String, count: int, scenario: String, reference: Dictionary) -> Dictionary:
	if not _counter_process_stabilized:
		for pass_index in range(COUNTER_STABILIZATION_PASSES):
			var warm: Dictionary = await _measure_counter_one("baseline", 64, "idle_full_theatre", reference)
			if not bool(warm.get("ok", false)):
				return {
					"ok": false,
					"error": "counter process stabilization failed",
					"pass": pass_index,
					"detail": warm,
				}
		_counter_process_stabilized = true
	return await super._measure_counter_bracket(mode, count, scenario, reference)
