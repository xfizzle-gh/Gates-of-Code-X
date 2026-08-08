from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return updated


def patch_map_markers() -> None:
    path = ROOT / "godot/scripts/presentation/map_markers.gd"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''const COUNTER_SIZE := Vector2(34, 22)
const S10_COUNTER_MATCH_EPSILON := 2.0
const S10_FACTION_COLORS := {
	"nato": Color("4f8fd8"),
	"ukr": Color("e2c84a"),
	"rusa": Color("c95b5b"),
	"prc": Color("d08a3f"),
	"neutral": Color("707780"),
}
''',
        '''const COUNTER_SIZE := Vector2(34, 22)
''',
        "remove heuristic constants",
    )
    text = replace_once(
        text,
        '''	selected: bool,
	in_supply: Variant = null,
	encircled: Variant = null
) -> Rect2:''',
        '''	selected: bool,
	in_supply: Variant = null,
	encircled: Variant = null,
	formation_id := ""
) -> Rect2:''',
        "add exact counter identity argument",
    )
    text = replace_once(
        text,
        '''		strength,
		presentation_overlay
	)''',
        '''		strength,
		presentation_overlay,
		formation_id
	)''',
        "forward exact counter identity",
    )
    replacement = '''static func resolve_formation_counter_style(
	canvas: CanvasItem,
	_center: Vector2,
	_faction_color: Color,
	_type_glyph: String,
	_strength: int,
	presentation_overlay := false,
	_center_is_image_pixel := false,
	formation_id := ""
) -> Dictionary:
	## The ordinary map draw path supplies the exact representative formation ID.
	## S10 never guesses identity from color, glyph, strength, or position.
	var normal := {"visible": true, "emphasized": false, "formation_id": formation_id}
	if presentation_overlay or formation_id.is_empty():
		return normal
	var presenter: Variant = _object_property(canvas, "operational_presenter", null)
	if presenter == null or not presenter.has_method("is_active") or not presenter.is_active():
		return normal
	var tracks: Dictionary = presenter.track_model()
	if tracks.has(formation_id):
		return {"visible": false, "emphasized": false, "formation_id": formation_id}
	var contact: Dictionary = presenter.contact_model()
	var participants: Array = contact.get("participant_formation_ids", [])
	if participants.has(formation_id):
		# Stationary participants are drawn explicitly by formation ID in the S10
		# overlay, including multiple formations colocated in one stack.
		return {"visible": false, "emphasized": false, "formation_id": formation_id}
	return normal


static func _object_property(object: Object, property_name: String, default_value: Variant) -> Variant:
	for row_variant: Variant in object.get_property_list():
		if row_variant is Dictionary and String((row_variant as Dictionary).get("name", "")) == property_name:
			return object.get(property_name)
	return default_value


static func draw_stack_badge'''
    text = regex_once(
        text,
        r"static func resolve_formation_counter_style\([\s\S]*?static func draw_stack_badge",
        replacement,
        "replace heuristic resolver with exact-ID resolver",
    )
    path.write_text(text, encoding="utf-8")


def patch_main_color_id() -> None:
    path = ROOT / "godot/scripts/main_color_id.gd"
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''					bool(battalion.get("is_in_supply", true)),
					int(battalion.get("encircled_turns", 0)) > 0
				)''',
        '''					bool(battalion.get("is_in_supply", true)),
					int(battalion.get("encircled_turns", 0)) > 0,
					String(battalion.get("strategic_formation_id", ""))
				)''',
        "pass exact representative formation ID",
    )
    text = replace_once(
        text,
        '''			if emphasized:
				draw_arc(screen, 25.0, 0.0, TAU, 32, Color("ffd27a"), 2.5)
		if not contact.is_empty():''',
        '''			if emphasized:
				draw_arc(screen, 25.0, 0.0, TAU, 32, Color("ffd27a"), 2.5)
		for model_variant: Variant in _s10_stationary_participant_models(contact, tracks):
			if not model_variant is Dictionary:
				continue
			var model := model_variant as Dictionary
			var image_pixel: Vector2 = model.get("image_pixel", Vector2.INF)
			if image_pixel == Vector2.INF:
				continue
			var screen := _image_to_screen(image_pixel) + model.get("screen_offset", Vector2.ZERO)
			var faction_color: Color = FACTION_COLORS.get(
				String(model.get("faction", "neutral")),
				FACTION_COLORS["neutral"]
			)
			MapMarkersScript.draw_formation_counter(
				self,
				screen,
				faction_color,
				String(model.get("glyph", "X")),
				int(model.get("unit_count", 0)),
				true
			)
			draw_arc(screen, 25.0, 0.0, TAU, 32, Color("ffd27a"), 2.5)
		if not contact.is_empty():''',
        "draw every stationary participant explicitly",
    )
    helper = '''func _s10_stationary_participant_models(contact: Dictionary, tracks: Dictionary) -> Array:
	## Build one explicit overlay counter per stationary participant using exact
	## strategic formation IDs. Colocated participants receive stable offsets so
	## every formation remains visible; nonparticipants stay in the ordinary layer.
	var grouped: Dictionary = {}
	var participant_ids: Array = contact.get("participant_formation_ids", []).duplicate()
	participant_ids.sort()
	for formation_id_variant: Variant in participant_ids:
		var formation_id := String(formation_id_variant)
		if formation_id.is_empty() or tracks.has(formation_id):
			continue
		var row := _s10_formation_row(formation_id)
		var image_pixel := _s10_pixel(row.get("display_pixel", null))
		if image_pixel == Vector2.INF:
			var encounter: Variant = contact.get("encounter_pixel", Vector2.INF)
			if encounter is Vector2:
				image_pixel = encounter as Vector2
		if image_pixel == Vector2.INF:
			continue
		var summary := _s10_formation_summary(formation_id)
		var key := "%.3f|%.3f" % [image_pixel.x, image_pixel.y]
		if not grouped.has(key):
			grouped[key] = []
		(grouped[key] as Array).append({
			"formation_id": formation_id,
			"faction": String(row.get("faction", "neutral")),
			"image_pixel": image_pixel,
			"glyph": String(summary.get("glyph", "X")),
			"unit_count": int(summary.get("unit_count", 0)),
		})
	var result: Array = []
	var group_keys: Array = grouped.keys()
	group_keys.sort()
	for key_variant: Variant in group_keys:
		var group: Array = grouped[key_variant]
		group.sort_custom(func(left: Dictionary, right: Dictionary) -> bool:
			return String(left.get("formation_id", "")) < String(right.get("formation_id", ""))
		)
		var midpoint := float(group.size() - 1) * 0.5
		for index in range(group.size()):
			var model := (group[index] as Dictionary).duplicate(true)
			model["screen_offset"] = Vector2((float(index) - midpoint) * 40.0, 0.0)
			result.append(model)
	return result


'''
    text = replace_once(
        text,
        '''func _s10_pixel(value: Variant) -> Vector2:
''',
        helper + '''func _s10_pixel(value: Variant) -> Vector2:
''',
        "add stationary participant model builder",
    )
    path.write_text(text, encoding="utf-8")


def patch_scene_test() -> None:
    path = ROOT / "godot/scripts/tools/operational_presentation_scene_test.gd"
    text = path.read_text(encoding="utf-8")
    start = text.index('\t# This is the actual strategic-map counter style resolver used by the draw path.')
    end = text.index('\n\tscene._handle_button("replay_contact")', start)
    replacement = '''	# The production draw call must pass the representative battalion's exact
	# strategic formation ID into the style resolver.
	var map_source := FileAccess.get_file_as_string("res://scripts/main_color_id.gd")
	_check(
		map_source.find('String(battalion.get("strategic_formation_id", ""))') >= 0,
		"ordinary counter draw path passes exact strategic formation ID"
	)
	var moving_baseline: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene, Vector2(50, 50), Color("4f8fd8"), "T", 4, false, true, "sf-a"
	)
	var identical_nonparticipant: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene, Vector2(50, 50), Color("4f8fd8"), "T", 4, false, true, "sf-a-twin"
	)
	var stationary_first: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene, Vector2(50, 50), Color("c95b5b"), "I", 3, false, true, "sf-r"
	)
	var stationary_second: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene, Vector2(50, 50), Color("c95b5b"), "I", 3, false, true, "sf-r-2"
	)
	var moving_overlay: Dictionary = MapMarkersScript.resolve_formation_counter_style(
		scene, Vector2(25, 25), Color("4f8fd8"), "T", 4, true, true, "sf-a"
	)
	var moving_visible_count := int(bool(moving_baseline.get("visible", true))) \
		+ int(bool(moving_overlay.get("visible", true)))
	_check_eq(moving_visible_count, 1, "moving formation has exactly one visible counter")
	_check(not bool(moving_baseline.get("visible", true)), "moving endpoint suppressed by exact formation ID")
	_check(bool(identical_nonparticipant.get("visible", false)), "identical colocated nonparticipant remains visible")
	_check(not bool(identical_nonparticipant.get("emphasized", true)), "identical colocated nonparticipant is not emphasized")
	_check(not bool(stationary_first.get("visible", true)), "first stationary participant baseline is replaced")
	_check(not bool(stationary_second.get("visible", true)), "second stationary participant baseline is replaced")
	var stationary_models: Array = scene._s10_stationary_participant_models(
		scene.operational_presenter.contact_model(),
		scene.operational_presenter.track_model()
	)
	_check_eq(stationary_models.size(), 2, "every stationary participant receives an explicit overlay counter")
	var stationary_ids: Array = []
	var stationary_offsets: Array = []
	for model_variant: Variant in stationary_models:
		var model := model_variant as Dictionary
		stationary_ids.append(String(model.get("formation_id", "")))
		stationary_offsets.append(model.get("screen_offset", Vector2.ZERO))
	stationary_ids.sort()
	_check_eq(stationary_ids, ["sf-r", "sf-r-2"], "stationary overlay models use exact participant IDs")
	_check(stationary_offsets[0] != stationary_offsets[1], "colocated stationary participants receive distinct visible offsets")
'''
    text = text[:start] + replacement + text[end:]
    text = replace_once(
        text,
        '''			{
				"id": "bn-r",
				"strategic_formation_id": "sf-r",
				"province_id": "b",
				"faction": "rusa",
				"battalion_type": "infantry",
				"unit_count": 3,
				"display_pixel": [50, 50],
			},
''',
        '''			{
				"id": "bn-a-twin",
				"strategic_formation_id": "sf-a-twin",
				"province_id": "a",
				"faction": "nato",
				"battalion_type": "tank",
				"unit_count": 4,
				"display_pixel": [50, 50],
			},
			{
				"id": "bn-r",
				"strategic_formation_id": "sf-r",
				"province_id": "b",
				"faction": "rusa",
				"battalion_type": "infantry",
				"unit_count": 3,
				"display_pixel": [50, 50],
			},
			{
				"id": "bn-r-2",
				"strategic_formation_id": "sf-r-2",
				"province_id": "b",
				"faction": "rusa",
				"battalion_type": "infantry",
				"unit_count": 3,
				"display_pixel": [50, 50],
			},
''',
        "add identity collision and stationary stack battalions",
    )
    text = replace_once(
        text,
        '''			{"id": "sf-a", "display_name": "Alpha", "faction": "nato", "display_pixel": [50, 50]},
			{"id": "sf-r", "display_name": "Red", "faction": "rusa", "display_pixel": [50, 50]},
''',
        '''			{"id": "sf-a", "display_name": "Alpha", "faction": "nato", "display_pixel": [50, 50]},
			{"id": "sf-a-twin", "display_name": "Alpha Twin", "faction": "nato", "display_pixel": [50, 50]},
			{"id": "sf-r", "display_name": "Red", "faction": "rusa", "display_pixel": [50, 50]},
			{"id": "sf-r-2", "display_name": "Red Two", "faction": "rusa", "display_pixel": [50, 50]},
''',
        "add strategic formation identity rows",
    )
    text = replace_once(
        text,
        '''			"defending_participants": [
				{"battalion_id": "bn-r", "strategic_formation_id": "sf-r", "formation_display_name": "Red", "faction": "rusa", "contact_initiator": false, "ambush_triggered": true, "ambush_strength_multiplier_milli": 1150}
			],
''',
        '''			"defending_participants": [
				{"battalion_id": "bn-r", "strategic_formation_id": "sf-r", "formation_display_name": "Red", "faction": "rusa", "contact_initiator": false, "ambush_triggered": true, "ambush_strength_multiplier_milli": 1150},
				{"battalion_id": "bn-r-2", "strategic_formation_id": "sf-r-2", "formation_display_name": "Red Two", "faction": "rusa", "contact_initiator": false, "ambush_triggered": false, "ambush_strength_multiplier_milli": 1000}
			],
''',
        "add second stationary participant",
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_map_markers()
    patch_main_color_id()
    patch_scene_test()
    print("S10 exact counter identity patch applied")


if __name__ == "__main__":
    main()
