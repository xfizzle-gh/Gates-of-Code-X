extends Node2D

const DEFAULT_SNAPSHOT := "res://campaign_snapshot.json"
const PANEL_WIDTH := 390.0
const MAP_MARGIN := Vector2(70, 70)
const FACTION_COLORS := {
    "nato": Color("4f8fd8"),
    "ukr": Color("e2c84a"),
    "rusa": Color("c95b5b"),
    "prc": Color("d08a3f"),
    "neutral": Color("707780"),
}

var snapshot: Dictionary = {}
var provinces_by_id: Dictionary = {}
var battalions_by_province: Dictionary = {}
var formations_by_id: Dictionary = {}
var factions_by_id: Dictionary = {}
var load_error := ""
var view_scale := 1.0
var view_offset := Vector2.ZERO
var dragging := false
var last_mouse_position := Vector2.ZERO
var selected_province_id := ""


func _ready() -> void:
    var args := OS.get_cmdline_user_args()
    var snapshot_path := args[0] if not args.is_empty() else DEFAULT_SNAPSHOT
    _load_snapshot(snapshot_path)
    queue_redraw()


func _load_snapshot(path: String) -> void:
    if not FileAccess.file_exists(path):
        load_error = "Campaign snapshot not found: %s" % path
        return
    var file := FileAccess.open(path, FileAccess.READ)
    if file == null:
        load_error = "Unable to open campaign snapshot: %s" % path
        return
    var parsed: Variant = JSON.parse_string(file.get_as_text())
    if not parsed is Dictionary:
        load_error = "Campaign snapshot is not valid JSON."
        return
    snapshot = parsed
    if snapshot.get("schema", "") != "gates-of-codex.frontend":
        load_error = "Unsupported campaign snapshot schema."
        snapshot = {}
        return
    for province: Dictionary in snapshot.get("provinces", []):
        provinces_by_id[province.get("id", "")] = province
    for battalion: Dictionary in snapshot.get("battalions", []):
        battalions_by_province[battalion.get("province_id", "")] = battalion
    for formation: Dictionary in snapshot.get("formations", []):
        formations_by_id[formation.get("id", "")] = formation
    for faction: Dictionary in snapshot.get("factions", []):
        factions_by_id[faction.get("id", "")] = faction
    var battalions: Array = snapshot.get("battalions", [])
    if not battalions.is_empty():
        selected_province_id = String((battalions[0] as Dictionary).get("province_id", ""))
    elif not provinces_by_id.is_empty():
        selected_province_id = String(provinces_by_id.keys()[0])


func _draw() -> void:
    if not load_error.is_empty():
        draw_string(ThemeDB.fallback_font, Vector2(32, 54), load_error, HORIZONTAL_ALIGNMENT_LEFT, -1, 22, Color("f08080"))
        return
    if snapshot.is_empty():
        return

    for edge: Array in snapshot.get("edges", []):
        if edge.size() != 2:
            continue
        var left: Dictionary = provinces_by_id.get(edge[0], {})
        var right: Dictionary = provinces_by_id.get(edge[1], {})
        if left.is_empty() or right.is_empty():
            continue
        draw_line(_map_to_screen(left), _map_to_screen(right), Color(0.35, 0.4, 0.45, 0.34), 1.0)

    for province: Dictionary in snapshot.get("provinces", []):
        _draw_province(province)

    var campaign: Dictionary = snapshot.get("campaign", {})
    var title := "%s  |  Turn %s  |  %s" % [
        campaign.get("name", "Gates of CodeX"),
        campaign.get("turn_number", 1),
        String(campaign.get("current_faction", "")).to_upper(),
    ]
    draw_string(ThemeDB.fallback_font, Vector2(24, 34), title, HORIZONTAL_ALIGNMENT_LEFT, -1, 20, Color.WHITE)
    draw_string(
        ThemeDB.fallback_font,
        Vector2(24, get_viewport_rect().size.y - 22),
        "Click a province. Drag to pan. Wheel to zoom. White: supplied. Red: isolated. Orange: encircled.",
        HORIZONTAL_ALIGNMENT_LEFT,
        get_viewport_rect().size.x - PANEL_WIDTH - 48,
        14,
        Color(0.75, 0.79, 0.83, 0.9)
    )
    _draw_management_panel()


func _draw_province(province: Dictionary) -> void:
    var position := _map_to_screen(province)
    var owner: String = province.get("owner", "neutral")
    var color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])
    var province_id: String = province.get("id", "")
    var battalion: Dictionary = battalions_by_province.get(province_id, {})
    var occupied := not battalion.is_empty()
    var selected := province_id == selected_province_id
    draw_circle(position, 5.0 if occupied else 3.2, color)
    if selected:
        draw_arc(position, 13.0, 0.0, TAU, 32, Color("7fe7ff"), 2.0)
    if occupied:
        var supplied: bool = battalion.get("is_in_supply", true)
        var encircled_turns: int = int(battalion.get("encircled_turns", 0))
        var ring_color := Color.WHITE if supplied else Color("ff6b5f")
        draw_arc(position, 8.0, 0.0, TAU, 24, ring_color, 1.5)
        if encircled_turns > 0:
            draw_arc(position, 10.5, 0.0, TAU, 24, Color("ffb14e"), 1.5)
    var infrastructure: Dictionary = province.get("infrastructure", {})
    if int(infrastructure.get("supply_hub", 0)) > 0:
        draw_rect(Rect2(position + Vector2(-9, 7), Vector2(4, 4)), Color("63d69f"))
    if int(infrastructure.get("command_post", 0)) > 0:
        draw_rect(Rect2(position + Vector2(-2, 7), Vector2(4, 4)), Color("b892ff"))
    if view_scale >= 1.7 or occupied or selected:
        draw_string(
            ThemeDB.fallback_font,
            position + Vector2(7, -5),
            String(province.get("display_name", province_id)),
            HORIZONTAL_ALIGNMENT_LEFT,
            -1,
            11,
            Color(0.9, 0.92, 0.94, 0.9)
        )


func _draw_management_panel() -> void:
    var viewport := get_viewport_rect().size
    var panel_x := viewport.x - PANEL_WIDTH
    draw_rect(Rect2(panel_x, 0, PANEL_WIDTH, viewport.y), Color(0.045, 0.06, 0.075, 0.98))
    draw_line(Vector2(panel_x, 0), Vector2(panel_x, viewport.y), Color(0.25, 0.31, 0.37, 0.9), 2.0)
    var x := panel_x + 20.0
    var y := 32.0
    y = _panel_heading("CAMPAIGN COMMAND", x, y)

    var campaign: Dictionary = snapshot.get("campaign", {})
    var selected_faction := String(campaign.get("selected_faction", ""))
    var faction: Dictionary = factions_by_id.get(selected_faction, {})
    y = _panel_line("Faction: %s" % selected_faction.to_upper(), x, y)
    y = _panel_line("Resources: %s" % faction.get("resources", 0), x, y)
    y = _panel_line("Income / maintenance: %s / %s" % [faction.get("income_last_round", 0), faction.get("maintenance_last_round", 0)], x, y)
    var outcome: Dictionary = campaign.get("outcome", {})
    y = _panel_line("Campaign: %s" % String(outcome.get("status", "active")).to_upper(), x, y)
    if outcome.get("status", "active") == "complete":
        y = _panel_line("Result: %s" % String(outcome.get("selected_faction_result", "")).to_upper(), x, y, Color("ffd27a"))
    y += 10.0

    y = _panel_heading("SELECTED PROVINCE", x, y)
    var province: Dictionary = provinces_by_id.get(selected_province_id, {})
    if province.is_empty():
        y = _panel_line("Click a province on the map.", x, y)
    else:
        y = _panel_line(String(province.get("display_name", selected_province_id)), x, y, Color.WHITE, 16)
        y = _panel_line("Owner: %s" % String(province.get("owner", "neutral")).to_upper(), x, y)
        y = _panel_line("Yield: %s   Fortification: %s" % [province.get("resource_yield", 0), province.get("fortification", 0)], x, y)
        var infrastructure: Dictionary = province.get("infrastructure", {})
        y = _panel_line("Supply hub %s | Recruit %s | Command %s" % [
            infrastructure.get("supply_hub", 0),
            infrastructure.get("recruitment_center", 0),
            infrastructure.get("command_post", 0),
        ], x, y)
        var battalion: Dictionary = battalions_by_province.get(selected_province_id, {})
        if not battalion.is_empty():
            var formation: Dictionary = formations_by_id.get(battalion.get("formation_id", ""), {})
            y = _panel_line(String(formation.get("display_name", battalion.get("formation_id", "Formation"))), x, y, Color("9fd7ff"))
            y = _panel_line("Strength %s/%s | Condition %s | Supply %s" % [
                battalion.get("unit_count", 0),
                battalion.get("authorized_unit_count", 0),
                battalion.get("condition", 0),
                battalion.get("supply", 0),
            ], x, y)
        var options: Array = province.get("construction_options", [])
        for option: Dictionary in options:
            var marker := "+" if option.get("available", false) else "-"
            y = _panel_line("%s %s L%s  cost %s" % [
                marker,
                String(option.get("building", "")).replace("_", " ").capitalize(),
                option.get("next_level", 0),
                option.get("cost", 0),
            ], x, y, Color("8ee2ad") if option.get("available", false) else Color("7f8a94"), 12)
    y += 10.0

    y = _panel_heading("OPERATIONAL OBJECTIVES", x, y)
    var shown := 0
    for objective: Dictionary in snapshot.get("objectives", []):
        if objective.get("coalition", "") != _selected_coalition(selected_faction):
            continue
        var completed: bool = objective.get("completed", false)
        var prefix := "DONE" if completed else "%s/%s" % [objective.get("progress", 0), objective.get("required", 0)]
        y = _panel_line("%s  %s" % [prefix, objective.get("display_name", "Objective")], x, y, Color("8ee2ad") if completed else Color("d4dbe2"), 12)
        shown += 1
        if shown >= 4:
            break


func _selected_coalition(faction_id: String) -> String:
    for alliance: Dictionary in snapshot.get("alliances", []):
        if faction_id in alliance.get("factions", []):
            return String(alliance.get("id", ""))
    return ""


func _panel_heading(text: String, x: float, y: float) -> float:
    draw_string(ThemeDB.fallback_font, Vector2(x, y), text, HORIZONTAL_ALIGNMENT_LEFT, PANEL_WIDTH - 40, 14, Color("78bce8"))
    return y + 24.0


func _panel_line(text: String, x: float, y: float, color := Color("d4dbe2"), size := 13) -> float:
    draw_string(ThemeDB.fallback_font, Vector2(x, y), text, HORIZONTAL_ALIGNMENT_LEFT, PANEL_WIDTH - 40, size, color)
    return y + float(size + 7)


func _map_to_screen(province: Dictionary) -> Vector2:
    var bounds: Dictionary = snapshot.get("bounds", {})
    var min_x := float(bounds.get("min_x", 0.0))
    var max_x := float(bounds.get("max_x", 1.0))
    var min_y := float(bounds.get("min_y", 0.0))
    var max_y := float(bounds.get("max_y", 1.0))
    var span_x := max(max_x - min_x, 1.0)
    var span_y := max(max_y - min_y, 1.0)
    var viewport_size := get_viewport_rect().size
    var map_size := Vector2(viewport_size.x - PANEL_WIDTH, viewport_size.y)
    var available := map_size - MAP_MARGIN * 2.0
    var normalized := Vector2(
        (float(province.get("x", 0.0)) - min_x) / span_x,
        (float(province.get("y", 0.0)) - min_y) / span_y
    )
    var base := MAP_MARGIN + normalized * available
    var center := map_size * 0.5
    return (base - center) * view_scale + center + view_offset


func _province_at(screen_position: Vector2) -> String:
    var best_id := ""
    var best_distance := 15.0
    for province: Dictionary in snapshot.get("provinces", []):
        var distance := screen_position.distance_to(_map_to_screen(province))
        if distance < best_distance:
            best_distance = distance
            best_id = String(province.get("id", ""))
    return best_id


func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton:
        var mouse_button := event as InputEventMouseButton
        var map_width := get_viewport_rect().size.x - PANEL_WIDTH
        if mouse_button.button_index == MOUSE_BUTTON_LEFT:
            if mouse_button.pressed and mouse_button.position.x < map_width:
                var province_id := _province_at(mouse_button.position)
                if not province_id.is_empty():
                    selected_province_id = province_id
                    dragging = false
                    queue_redraw()
                else:
                    dragging = true
                    last_mouse_position = mouse_button.position
            else:
                dragging = false
        elif mouse_button.pressed and mouse_button.position.x < map_width and mouse_button.button_index == MOUSE_BUTTON_WHEEL_UP:
            _zoom_at(mouse_button.position, 1.12)
        elif mouse_button.pressed and mouse_button.position.x < map_width and mouse_button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
            _zoom_at(mouse_button.position, 1.0 / 1.12)
    elif event is InputEventMouseMotion and dragging:
        var motion := event as InputEventMouseMotion
        view_offset += motion.position - last_mouse_position
        last_mouse_position = motion.position
        queue_redraw()


func _zoom_at(mouse_position: Vector2, factor: float) -> void:
    var old_scale := view_scale
    view_scale = clamp(view_scale * factor, 0.55, 8.0)
    if is_equal_approx(old_scale, view_scale):
        return
    var map_center := Vector2((get_viewport_rect().size.x - PANEL_WIDTH) * 0.5, get_viewport_rect().size.y * 0.5)
    var relative := mouse_position - map_center - view_offset
    view_offset -= relative * (view_scale / old_scale - 1.0)
    queue_redraw()
