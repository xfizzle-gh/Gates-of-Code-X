extends Node2D

const DEFAULT_SNAPSHOT := "res://campaign_snapshot.json"
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
var load_error := ""
var view_scale := 1.0
var view_offset := Vector2.ZERO
var dragging := false
var last_mouse_position := Vector2.ZERO


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


func _draw() -> void:
    if not load_error.is_empty():
        draw_string(
            ThemeDB.fallback_font,
            Vector2(32, 54),
            load_error,
            HORIZONTAL_ALIGNMENT_LEFT,
            -1,
            22,
            Color("f08080")
        )
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
        draw_line(_map_to_screen(left), _map_to_screen(right), Color(0.35, 0.4, 0.45, 0.38), 1.0)

    for province: Dictionary in snapshot.get("provinces", []):
        var position := _map_to_screen(province)
        var owner: String = province.get("owner", "neutral")
        var color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])
        var province_id: String = province.get("id", "")
        var battalion: Dictionary = battalions_by_province.get(province_id, {})
        var occupied := not battalion.is_empty()
        draw_circle(position, 4.5 if occupied else 3.0, color)
        if occupied:
            var supplied: bool = battalion.get("is_in_supply", true)
            var encircled_turns: int = int(battalion.get("encircled_turns", 0))
            var ring_color := Color.WHITE if supplied else Color("ff6b5f")
            draw_arc(position, 8.0, 0.0, TAU, 24, ring_color, 1.5)
            if encircled_turns > 0:
                draw_arc(position, 11.0, 0.0, TAU, 24, Color("ffb14e"), 1.5)
        if view_scale >= 1.7 or occupied:
            draw_string(
                ThemeDB.fallback_font,
                position + Vector2(7, -5),
                String(province.get("display_name", province_id)),
                HORIZONTAL_ALIGNMENT_LEFT,
                -1,
                11,
                Color(0.9, 0.92, 0.94, 0.9)
            )

    var campaign: Dictionary = snapshot.get("campaign", {})
    var title := "%s  |  Turn %s  |  %s" % [
        campaign.get("name", "Gates of CodeX"),
        campaign.get("turn_number", 1),
        String(campaign.get("current_faction", "")).to_upper(),
    ]
    draw_string(
        ThemeDB.fallback_font,
        Vector2(24, 34),
        title,
        HORIZONTAL_ALIGNMENT_LEFT,
        -1,
        20,
        Color.WHITE
    )
    draw_string(
        ThemeDB.fallback_font,
        Vector2(24, get_viewport_rect().size.y - 22),
        "White: supplied. Red: isolated. Orange: encircled. Drag to pan; wheel to zoom.",
        HORIZONTAL_ALIGNMENT_LEFT,
        -1,
        14,
        Color(0.75, 0.79, 0.83, 0.9)
    )


func _map_to_screen(province: Dictionary) -> Vector2:
    var bounds: Dictionary = snapshot.get("bounds", {})
    var min_x := float(bounds.get("min_x", 0.0))
    var max_x := float(bounds.get("max_x", 1.0))
    var min_y := float(bounds.get("min_y", 0.0))
    var max_y := float(bounds.get("max_y", 1.0))
    var span_x := max(max_x - min_x, 1.0)
    var span_y := max(max_y - min_y, 1.0)
    var viewport_size := get_viewport_rect().size
    var margin := Vector2(70, 70)
    var available := viewport_size - margin * 2.0
    var normalized := Vector2(
        (float(province.get("x", 0.0)) - min_x) / span_x,
        (float(province.get("y", 0.0)) - min_y) / span_y
    )
    var base := margin + normalized * available
    var center := viewport_size * 0.5
    return (base - center) * view_scale + center + view_offset


func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseButton:
        var mouse_button := event as InputEventMouseButton
        if mouse_button.button_index == MOUSE_BUTTON_LEFT:
            dragging = mouse_button.pressed
            last_mouse_position = mouse_button.position
        elif mouse_button.pressed and mouse_button.button_index == MOUSE_BUTTON_WHEEL_UP:
            _zoom_at(mouse_button.position, 1.12)
        elif mouse_button.pressed and mouse_button.button_index == MOUSE_BUTTON_WHEEL_DOWN:
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
    var viewport_center := get_viewport_rect().size * 0.5
    var relative := mouse_position - viewport_center - view_offset
    view_offset -= relative * (view_scale / old_scale - 1.0)
    queue_redraw()
