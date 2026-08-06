class_name MapSpace
extends RefCounted

## Central map-space <-> screen-space transforms for the strategic theatre.
## Image pixels are the canonical map space for color-ID theatres.
## Do not hardcode texture dimensions; always read size from the active map.

var image_size := Vector2.ONE
var content_rect := Rect2()
var view_scale := 1.0
var view_offset := Vector2.ZERO


func configure(p_image_size: Vector2, p_content_rect: Rect2, p_view_scale: float, p_view_offset: Vector2) -> void:
	image_size = p_image_size if p_image_size.x > 0.0 and p_image_size.y > 0.0 else Vector2.ONE
	content_rect = p_content_rect
	view_scale = p_view_scale
	view_offset = p_view_offset


func texture_rect() -> Rect2:
	var fit_scale := minf(content_rect.size.x / image_size.x, content_rect.size.y / image_size.y)
	var rendered_size := image_size * fit_scale * view_scale
	var origin := content_rect.position + (content_rect.size - rendered_size) * 0.5 + view_offset
	return Rect2(origin, rendered_size)


func image_to_screen(pixel: Vector2) -> Vector2:
	var rect := texture_rect()
	return rect.position + (pixel / image_size) * rect.size


func screen_to_image(screen: Vector2) -> Vector2:
	var rect := texture_rect()
	if rect.size.x <= 0.0 or rect.size.y <= 0.0:
		return Vector2.ZERO
	var normalized := (screen - rect.position) / rect.size
	return normalized * image_size


func screen_to_pixel(screen: Vector2) -> Vector2i:
	var img := screen_to_image(screen)
	return Vector2i(floori(img.x), floori(img.y))


func clamp_to_rect(point: Vector2, bounds: Rect2, pad: float) -> Vector2:
	return Vector2(
		clampf(point.x, bounds.position.x + pad, bounds.position.x + bounds.size.x - pad),
		clampf(point.y, bounds.position.y + pad, bounds.position.y + bounds.size.y - pad)
	)
