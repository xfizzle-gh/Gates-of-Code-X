class_name StrategicMinimapPrototype
extends Control

## #212 Phase D cached minimap prototype. The minimap owns one downsampled image
## texture plus lightweight overlay marks. It never instantiates a second Earth3
## scene or PolygonMap and has no per-frame process loop.

const TARGET_WIDTH := 250

var _texture: ImageTexture = null
var _map_image_size := Vector2.ONE
var _selected_pixel := Vector2(-1, -1)
var _front_pixels: Array = []
var _texture_size := Vector2i.ZERO


func configure(source_image: Image, map_image_size: Vector2, selected_pixel: Vector2, front_pixels: Array) -> void:
	if source_image == null or source_image.is_empty():
		return
	var image := source_image.duplicate()
	var target_height := maxi(1, int(round(float(TARGET_WIDTH) * float(image.get_height()) / float(maxi(image.get_width(), 1)))))
	image.resize(TARGET_WIDTH, target_height, Image.INTERPOLATE_LANCZOS)
	_texture = ImageTexture.create_from_image(image)
	_texture_size = Vector2i(TARGET_WIDTH, target_height)
	_map_image_size = Vector2(maxf(map_image_size.x, 1.0), maxf(map_image_size.y, 1.0))
	_selected_pixel = selected_pixel
	_front_pixels = front_pixels.duplicate(true)
	custom_minimum_size = Vector2(_texture_size)
	size = Vector2(_texture_size)
	queue_redraw()


func texture_size() -> Vector2i:
	return _texture_size


func has_live_map_descendant() -> bool:
	for child in get_children():
		if String(child.name).contains("Earth3") or String(child.name).contains("PolygonMap"):
			return true
	return false


func _draw() -> void:
	if _texture == null:
		return
	var rect := Rect2(Vector2.ZERO, Vector2(_texture_size))
	draw_rect(rect.grow(3), Color(0.02, 0.03, 0.05, 0.92))
	draw_texture_rect(_texture, rect, false)
	draw_rect(rect, Color(0.85, 0.88, 0.92, 0.9), false, 1.0)
	for point_value in _front_pixels:
		var point := _variant_to_vec2(point_value)
		if point.x < 0.0:
			continue
		draw_circle(_to_minimap(point), 2.0, Color("ffb14e"))
	if _selected_pixel.x >= 0.0 and _selected_pixel.y >= 0.0:
		var selected := _to_minimap(_selected_pixel)
		draw_circle(selected, 4.0, Color("7fe7ff"))
		draw_arc(selected, 7.0, 0.0, TAU, 20, Color.WHITE, 1.2)


func _to_minimap(image_pixel: Vector2) -> Vector2:
	return Vector2(
		image_pixel.x / _map_image_size.x * float(_texture_size.x),
		image_pixel.y / _map_image_size.y * float(_texture_size.y)
	)


func _variant_to_vec2(value: Variant) -> Vector2:
	if value is Vector2:
		return value as Vector2
	if value is Array and (value as Array).size() >= 2:
		return Vector2(float(value[0]), float(value[1]))
	return Vector2(-1, -1)
