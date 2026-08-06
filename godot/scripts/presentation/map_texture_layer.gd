extends Node2D

## Dedicated CanvasItem texture layer with a fixed texture_filter.
## Godot 4 applies filtering per CanvasItem, not per draw_texture_rect call.

var clear_rect := Rect2()
var clear_color := Color(0, 0, 0, 0)
var _items: Array = []


func set_draw_items(items: Array) -> void:
	_items = items


func set_clear(rect: Rect2, color: Color) -> void:
	clear_rect = rect
	clear_color = color


func refresh() -> void:
	queue_redraw()


func _draw() -> void:
	if clear_rect.size.x > 0.0 and clear_rect.size.y > 0.0:
		draw_rect(clear_rect, clear_color)
	for item_variant in _items:
		if not item_variant is Dictionary:
			continue
		var item := item_variant as Dictionary
		var texture: Texture2D = item.get("texture", null)
		if texture == null:
			continue
		var rect: Rect2 = item.get("rect", Rect2())
		if rect.size.x <= 0.0 or rect.size.y <= 0.0:
			continue
		draw_texture_rect(texture, rect, false)
