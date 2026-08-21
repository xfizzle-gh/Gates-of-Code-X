extends RefCounted
## Presentation-only #75 campaign calendar, objectives, and result model.
## Python remains authority. This script never invents victory or calendar state.


const VICTORY_GRADES := ["decisive_victory", "victory"]
const GRADE_LABELS := {
	"decisive_victory": "Decisive Victory",
	"victory": "Victory",
	"negotiated_advantage": "Negotiated Advantage",
	"stalemate": "Stalemate",
	"defeat": "Defeat",
	"decisive_defeat": "Decisive Defeat",
}


static func campaign_block(snapshot: Dictionary) -> Dictionary:
	var campaign: Variant = snapshot.get("campaign", {})
	return campaign if campaign is Dictionary else {}


static func calendar_label(campaign: Dictionary) -> String:
	var calendar: Variant = campaign.get("calendar", {})
	if calendar is Dictionary:
		var label := String((calendar as Dictionary).get("label", "")).strip_edges()
		if not label.is_empty():
			return label
	var turn := int(campaign.get("turn_number", 1))
	var year := 2028 + int((turn - 1) / 52)
	var week := ((turn - 1) % 52) + 1
	return "%s-W%02d" % [year, week]


static func turn_line(campaign: Dictionary) -> String:
	var cap := int(campaign.get("turn_cap", 0))
	var turn := int(campaign.get("turn_number", 1))
	if cap > 0 and not bool(campaign.get("continue_playing", false)):
		return "Turn %s / %s   %s" % [turn, cap, calendar_label(campaign)]
	return "Turn %s   %s" % [turn, calendar_label(campaign)]


static func momentum_label(campaign: Dictionary) -> String:
	var momentum: Variant = campaign.get("momentum", {})
	var score := 0
	if momentum is Dictionary:
		score = int((momentum as Dictionary).get("score", 0))
	else:
		score = int(campaign.get("momentum", 0))
	return "Momentum %s" % score


static func objective_progress_line(objective: Dictionary) -> String:
	var required := int(objective.get("required", objective.get("threshold", 0)))
	var progress := int(objective.get("progress", 0))
	var prefix := "DONE" if bool(objective.get("completed", false)) else "%s/%s" % [progress, required]
	var layer := String(objective.get("layer", "")).strip_edges()
	var name := String(objective.get("display_name", objective.get("id", "Objective")))
	if layer == "national_contribution":
		return "%s  [National] %s" % [prefix, name]
	if layer == "coalition_war_aim":
		return "%s  [War aim] %s" % [prefix, name]
	return "%s  %s" % [prefix, name]


static func result_model(snapshot: Dictionary) -> Dictionary:
	var campaign := campaign_block(snapshot)
	var outcome: Variant = campaign.get("outcome", {})
	if not outcome is Dictionary:
		return {"visible": false}
	var row := outcome as Dictionary
	var status := String(row.get("status", "active"))
	var continue_playing := bool(campaign.get("continue_playing", row.get("continue_playing", false)))
	var concluded := bool(campaign.get("concluded", row.get("concluded", false)))
	var grade := String(row.get("grade", "")).strip_edges()
	var complete := status == "complete" or not grade.is_empty()
	if not complete:
		return {"visible": false, "continue_playing": continue_playing, "concluded": concluded}
	var faction_result := String(row.get("selected_faction_result", ""))
	# Python is authority. A defeated selected player must never be classified
	# as Victory or offered Continue Playing, even if a winner-side grade leaked.
	var victory := (grade in VICTORY_GRADES or faction_result == "victory") and faction_result != "defeat"
	return {
		"visible": not continue_playing or concluded,
		"banner": concluded or not continue_playing,
		"title": "CAMPAIGN RESULT",
		"grade": grade,
		"grade_label": String(GRADE_LABELS.get(grade, grade if not grade.is_empty() else "Complete")),
		"reason": String(row.get("reason", "")),
		"momentum": momentum_label(campaign),
		"coalition_result": String(row.get("coalition_result", "")),
		"national_result": String(row.get("national_result", "")),
		"show_continue": victory and not continue_playing and not concluded,
		"show_conclude": not concluded,
		"continue_playing": continue_playing,
		"concluded": concluded,
	}


static func rewrite_launch_args(args: Array, length_preset: String, fog_of_war: String) -> Array:
	var rewritten: Array = []
	var skip_next := false
	for item in args:
		if skip_next:
			skip_next = false
			continue
		var token := String(item)
		if token == "--length-preset" or token == "--fog-of-war":
			skip_next = true
			continue
		rewritten.append(token)
	if not length_preset.strip_edges().is_empty():
		rewritten.append("--length-preset")
		rewritten.append(length_preset)
	if not fog_of_war.strip_edges().is_empty():
		rewritten.append("--fog-of-war")
		rewritten.append(fog_of_war)
	return rewritten
