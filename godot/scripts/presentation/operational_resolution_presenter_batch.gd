extends "res://scripts/presentation/operational_resolution_presenter.gd"

## Batch-aware presentation adapter for #207.
##
## The base presenter historically returned the first successful result carrying
## ``operational_presentation``. A player-round batch begins with ``end_turn``
## and later resolves AI/round movement, so taking the first result can discard
## the actual movement tracks. Aggregate every successful result in order while
## keeping the final battle-finalization payload, if any.


func _extract_operational_presentation(payload: Dictionary) -> Dictionary:
	if payload.has("movements") or payload.has("battle_finalization"):
		return payload.duplicate(true)
	var movements: Array = []
	var battle_finalization: Dictionary = {}
	for result_variant: Variant in payload.get("results", []):
		if not result_variant is Dictionary:
			continue
		var result := result_variant as Dictionary
		if not bool(result.get("ok", false)):
			continue
		var data: Dictionary = result.get("data", {})
		var presentation_variant: Variant = data.get("operational_presentation", {})
		if not presentation_variant is Dictionary:
			continue
		var presentation := presentation_variant as Dictionary
		for movement_variant: Variant in presentation.get("movements", []):
			if movement_variant is Dictionary:
				movements.append((movement_variant as Dictionary).duplicate(true))
		var finalization_variant: Variant = presentation.get("battle_finalization", {})
		if finalization_variant is Dictionary and not (finalization_variant as Dictionary).is_empty():
			battle_finalization = (finalization_variant as Dictionary).duplicate(true)
	var merged := {"movements": movements}
	if not battle_finalization.is_empty():
		merged["battle_finalization"] = battle_finalization
	return merged
