class_name StrategicMapLodPolicy
extends RefCounted

## #212 Phase D presentation-only LOD policy prototype.
##
## This object is pure/event-driven: it has no Node and no _process loop. User
## toggles are hard disables; LOD may additionally suppress lower-value layers.

const FULL_THEATRE_MAX_SCALE := 1.65
const MID_ZOOM_MAX_SCALE := 2.6
const LAYER_KEYS := [
	"formation_symbols",
	"names",
	"infrastructure_sites",
	"operational_routes",
	"supply",
	"objectives",
	"fog_intelligence",
	"debug_overlays",
]


func default_toggles() -> Dictionary:
	return {
		"formation_symbols": true,
		"names": true,
		"infrastructure_sites": true,
		"operational_routes": true,
		"supply": true,
		"objectives": true,
		"fog_intelligence": true,
		"debug_overlays": false,
	}


func lod_name(view_scale: float) -> String:
	if view_scale <= FULL_THEATRE_MAX_SCALE:
		return "full_theatre"
	if view_scale <= MID_ZOOM_MAX_SCALE:
		return "operational"
	return "detailed"


func state_for_scale(view_scale: float, toggles: Dictionary = {}) -> Dictionary:
	var user := default_toggles()
	for key_value in LAYER_KEYS:
		var key := String(key_value)
		if toggles.has(key):
			user[key] = bool(toggles[key])
	var state := user.duplicate(true)
	var lod := lod_name(view_scale)
	if lod == "full_theatre":
		state["names"] = false
		state["infrastructure_sites"] = false
		state["operational_routes"] = false
		state["debug_overlays"] = false
	elif lod == "operational":
		state["names"] = false
		state["debug_overlays"] = false
	# Detailed zoom honors every user toggle exactly.
	state["lod"] = lod
	state["view_scale"] = view_scale
	return state


func measurable_layer_keys() -> Array:
	# These have independent current production/fixture surfaces that the Phase D
	# profiler can actually suppress and measure without inventing authority.
	return [
		"formation_symbols",
		"names",
		"infrastructure_sites",
		"operational_routes",
		"debug_overlays",
	]


func contract_only_layer_keys() -> Array:
	# Current #212 fixture does not expose these as independent presentation
	# surfaces. They remain part of the control contract, but the profiler marks
	# them unmeasured rather than fabricating fake work.
	return ["supply", "objectives", "fog_intelligence"]
