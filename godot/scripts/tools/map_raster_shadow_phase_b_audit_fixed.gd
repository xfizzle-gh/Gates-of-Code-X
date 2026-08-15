extends "res://scripts/tools/map_raster_shadow_phase_b_audit.gd"

## The dynamic-scenario audit proves hover/select/counter/site/route/contact
## presentation and map-space alignment. Non-empty legal-target identity is
## proven separately by map_raster_shadow_legal_target_audit.gd using a real
## committed snapshot with backend-authored operational_orders.

func _scenario_surface(scene: Node, scenario: String) -> Dictionary:
	if scenario == "hover_select":
		var selected := String(scene.get("selected_province_id") if scene.get("selected_province_id") != null else "")
		var hovered := String(scene.get("hovered_province_id") if scene.get("hovered_province_id") != null else "")
		var legal_value: Variant = scene.get("legal_targets")
		var legal_count := (legal_value as Dictionary).size() if legal_value is Dictionary else 0
		return {
			"ok": not selected.is_empty() and not hovered.is_empty(),
			"selected": selected,
			"hovered": hovered,
			"legal_target_count_diagnostic": legal_count,
		}
	return super._scenario_surface(scene, scenario)
