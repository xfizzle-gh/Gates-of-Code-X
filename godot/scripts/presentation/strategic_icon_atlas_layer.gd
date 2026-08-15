class_name StrategicIconAtlasLayer
extends Node2D

## #212 Phase C debug-only strategic-symbol atlas prototype.
##
## All glyphs below are original repository-owned procedural pixel patterns. No
## reference-mod artwork is embedded or traced. Numeric strength remains text and
## is deliberately not baked into the atlas.

const CELL_SIZE := 32
const GRID_COLUMNS := 6
const SYMBOL_PIXEL := 3
const SYMBOL_ORIGIN := Vector2i(5, 5)
const COUNTER_SIZE := Vector2(34, 22)

const ICON_KEYS := [
	"infantry",
	"motorized",
	"mechanized",
	"armor",
	"airborne",
	"artillery",
	"air_defense",
	"engineers",
	"recon",
	"logistics_support",
	"hq_command",
	"supply",
	"objective",
	"battle_contact",
	"stance_warning",
	"readiness_warning",
	"supply_warning",
	"actor_flag_badge",
]

const PATTERNS := {
	"infantry": ["1000001","0100010","0010100","0001000","0010100","0100010","1000001"],
	"motorized": ["0011100","0100010","1000001","1001001","1000001","0100010","0011100"],
	"mechanized": ["1111111","1000001","1011101","1010101","1011101","1000001","1111111"],
	"armor": ["0001000","0011100","0111110","1111111","0111110","0011100","0001000"],
	"airborne": ["1000001","1100011","0110110","0011100","0001000","0011100","0100010"],
	"artillery": ["0001000","0001000","0001000","1111111","0001000","0011100","0111110"],
	"air_defense": ["0001000","0011100","0101010","1001001","0001000","0010100","0100010"],
	"engineers": ["1000001","1000001","1111111","1000001","1111111","1000001","1000001"],
	"recon": ["0001000","0011100","0110110","1100011","0110110","0011100","0001000"],
	"logistics_support": ["1111111","1000001","1011101","1011101","1011101","1000001","1111111"],
	"hq_command": ["1000000","1111100","1000100","1111100","1000000","1000000","1000000"],
	"supply": ["1111111","1000001","1011101","1011101","1011101","1000001","1111111"],
	"objective": ["0001000","0101010","0011100","1111111","0011100","0101010","0001000"],
	"battle_contact": ["1000001","0100010","0010100","0001000","0010100","0100010","1000001"],
	"stance_warning": ["0001000","0011100","0011100","0111110","0111110","1111111","0001000"],
	"readiness_warning": ["0011100","0100010","1000001","0001000","0001000","0000000","0001000"],
	"supply_warning": ["1111111","1000001","1011101","1001001","1011101","1000001","1111111"],
	"actor_flag_badge": ["1111110","1000010","1111110","1000000","1000000","1000000","1000000"],
}

var map_space: Variant = null
var entries: Array = []
var atlas_texture: ImageTexture = null
var show_strength_text := true
var _source_rect_by_key: Dictionary = {}


func configure(map_space_value: Variant, entry_rows: Array, strength_text := true) -> void:
	map_space = map_space_value
	entries = entry_rows.duplicate(true)
	show_strength_text = strength_text
	if atlas_texture == null:
		atlas_texture = ImageTexture.create_from_image(_build_atlas_image())
	queue_redraw()


func set_entries(entry_rows: Array) -> void:
	entries = entry_rows.duplicate(true)
	queue_redraw()


func set_strength_text_enabled(enabled: bool) -> void:
	show_strength_text = enabled
	queue_redraw()


func vocabulary() -> Array:
	return ICON_KEYS.duplicate()


func atlas_size() -> Vector2i:
	var rows := int(ceili(float(ICON_KEYS.size()) / float(GRID_COLUMNS)))
	return Vector2i(GRID_COLUMNS * CELL_SIZE, rows * CELL_SIZE)


func _draw() -> void:
	if atlas_texture == null:
		return
	for entry_value in entries:
		if not entry_value is Dictionary:
			continue
		var entry := entry_value as Dictionary
		var pixel_value: Variant = entry.get("pixel", [])
		if not pixel_value is Array or (pixel_value as Array).size() < 2:
			continue
		var image_pixel := Vector2(float(pixel_value[0]), float(pixel_value[1]))
		var center := image_pixel
		if map_space != null and map_space.has_method("image_to_screen"):
			center = map_space.call("image_to_screen", image_pixel)
		var key := String(entry.get("icon_key", "infantry"))
		var source: Rect2 = _source_rect_by_key.get(key, _source_rect_by_key.get("infantry", Rect2()))
		var color_value: Variant = entry.get("color", Color.WHITE)
		var faction_color := color_value as Color if color_value is Color else Color.WHITE
		var dest := Rect2(center - COUNTER_SIZE * 0.5 + Vector2(0, -2), COUNTER_SIZE)
		draw_texture_rect_region(atlas_texture, dest, source, faction_color, false, true)
		if show_strength_text:
			var strength := int(entry.get("strength", 0))
			draw_string(
				ThemeDB.fallback_font,
				dest.position + Vector2(19, 15),
				str(strength),
				HORIZONTAL_ALIGNMENT_LEFT,
				-1,
				10,
				Color.WHITE
			)


func _build_atlas_image() -> Image:
	_source_rect_by_key.clear()
	var size := atlas_size()
	var image := Image.create(size.x, size.y, false, Image.FORMAT_RGBA8)
	image.fill(Color(0, 0, 0, 0))
	for index in range(ICON_KEYS.size()):
		var key := String(ICON_KEYS[index])
		var col := index % GRID_COLUMNS
		var row := index / GRID_COLUMNS
		var origin := Vector2i(col * CELL_SIZE, row * CELL_SIZE)
		var source := Rect2(origin, Vector2i(CELL_SIZE, CELL_SIZE))
		_source_rect_by_key[key] = source
		# A compact counter plate is part of every atlas cell. The faction color is
		# applied as one draw-time modulate, so every instance reuses this texture.
		image.fill_rect(Rect2i(origin + Vector2i(1, 5), Vector2i(30, 22)), Color(0.92, 0.92, 0.92, 1.0))
		image.fill_rect(Rect2i(origin + Vector2i(2, 6), Vector2i(28, 20)), Color(0.72, 0.72, 0.72, 1.0))
		var pattern_value: Variant = PATTERNS.get(key, PATTERNS["infantry"])
		if pattern_value is Array:
			var pattern := pattern_value as Array
			for py in range(pattern.size()):
				var line := String(pattern[py])
				for px in range(line.length()):
					if line[px] != "1":
						continue
					var block_origin := origin + SYMBOL_ORIGIN + Vector2i(px * SYMBOL_PIXEL, py * SYMBOL_PIXEL)
					image.fill_rect(Rect2i(block_origin, Vector2i(SYMBOL_PIXEL, SYMBOL_PIXEL)), Color(0.08, 0.08, 0.09, 1.0))
	return image
