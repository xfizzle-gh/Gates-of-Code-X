extends "res://scripts/tools/map_raster_shadow_phase_b_audit.gd"

## The dynamic-scenario audit proves hover/select/counter/site/route/contact
## presentation and map-space alignment. Non-empty legal-target identity is
## proven separately by map_raster_shadow_legal_target_audit.gd using a real
## production player-shell snapshot with backend-authored operational_orders.
##
## Pending-battle/contact presentation comes from the fixture itself, so that
## scenario must not mutate selected_province_id and then fail the generic
## selection-parity control against its own deliberate mutation.

func _apply_scenario(scene: Node, scenario: String, i: int, total: int) -> void:
	if scenario != "pending_battle_contact":
		super._apply_scenario(scene, scenario, i, total)
		return
	var t := float(i) / float(maxi(total - 1, 1))
	if scene.get("hovered_province_id") != null:
		scene.hovered_province_id = "e3_2783"
	if scene.get("view_offset") != null:
		scene.view_offset = Vector2(110.0 * sin(t * TAU), 65.0 * sin(t * TAU * 0.5))


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
