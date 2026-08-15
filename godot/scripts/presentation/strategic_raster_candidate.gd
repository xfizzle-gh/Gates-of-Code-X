class_name StrategicRasterCandidate
extends Node2D

## #212 E1 production-candidate presentation compositor.
##
## This node is presentation-only. The live Earth3 PolygonMap and its polygon
## root remain loaded as the sole authority for stable IDs, picking, ownership,
## legal targets, and operational coordinates. The candidate only shadows the
## expensive static polygon presentation when explicitly enabled by its owner.
##
## Wide view uses one 1x derived texture to avoid the B2 all-63-tile residency
## failure. Closer views switch to lazy 2x / 1024px tiles with short hysteresis.

const CACHE_SCALE := 2
const LAZY_TILE_SIZE := 1024
const LAZY_RETAIN_FRAMES := 2
const PREFETCH_MARGIN_PX := 96.0
const FULL_THEATRE_MAX_SCALE := 1.65

var _live_root: Node2D = null
var _cache_image: Image = null
var _wide_sprite: Sprite2D = null
var _tiles: Array = []
var _frame_index := 0
var _enabled := false
var _mode := "disabled"
var _created_total := 0
var _evicted_total := 0
var _peak_resident_tiles := 0
var _peak_resident_rgba8_bytes := 0


func configure(live_root: Node2D, cache_image: Image) -> bool:
	if live_root == null or cache_image == null or cache_image.is_empty():
		return false
	_live_root = live_root
	_cache_image = cache_image
	name = "Issue212HybridRasterCandidate"
	z_index = -15
	_build_wide_sprite()
	_build_tile_descriptors()
	_sync_transform()
	return _wide_sprite != null and not _tiles.is_empty()


func set_candidate_enabled(enabled: bool) -> void:
	_enabled = enabled
	visible = enabled
	if _live_root != null:
		_live_root.visible = not enabled
	if not enabled:
		_mode = "disabled"
		if _wide_sprite != null:
			_wide_sprite.visible = false
		_evict_all_tiles()


func is_candidate_enabled() -> bool:
	return _enabled


func sync(view_scale: float, viewport_size: Vector2) -> Dictionary:
	if not _enabled or _live_root == null:
		return debug_state()
	_sync_transform()
	_frame_index += 1
	if view_scale <= FULL_THEATRE_MAX_SCALE:
		_mode = "wide_1x"
		if _wide_sprite != null:
			_wide_sprite.visible = true
		_evict_all_tiles()
	else:
		_mode = "lazy_2x_1024"
		if _wide_sprite != null:
			_wide_sprite.visible = false
		_sync_lazy_tiles(viewport_size)
	return debug_state()


func debug_state() -> Dictionary:
	var resident := 0
	var resident_bytes := 0
	for entry_value in _tiles:
		var entry: Dictionary = entry_value
		if entry.get("sprite") as Sprite2D != null:
			resident += 1
			resident_bytes += int(entry.get("rgba8_bytes", 0))
	return {
		"enabled": _enabled,
		"mode": _mode,
		"cache_scale": CACHE_SCALE,
		"lazy_tile_size": LAZY_TILE_SIZE,
		"total_tiles": _tiles.size(),
		"resident_tiles": resident,
		"resident_rgba8_bytes": resident_bytes,
		"wide_rgba8_bytes": _wide_rgba8_bytes(),
		"created_total": _created_total,
		"evicted_total": _evicted_total,
		"peak_resident_tiles": _peak_resident_tiles,
		"peak_resident_rgba8_bytes": _peak_resident_rgba8_bytes,
		"polygon_root_loaded": _live_root != null,
		"polygon_root_visible": _live_root.visible if _live_root != null else false,
	}


func shutdown() -> void:
	set_candidate_enabled(false)
	_cache_image = null
	_tiles.clear()
	_live_root = null


func _build_wide_sprite() -> void:
	var wide := _cache_image.duplicate()
	wide.resize(
		maxi(1, int(round(float(_cache_image.get_width()) / float(CACHE_SCALE)))),
		maxi(1, int(round(float(_cache_image.get_height()) / float(CACHE_SCALE)))),
		Image.INTERPOLATE_LANCZOS
	)
	_wide_sprite = Sprite2D.new()
	_wide_sprite.name = "WideTheatre1x"
	_wide_sprite.centered = false
	_wide_sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	_wide_sprite.texture = ImageTexture.create_from_image(wide)
	_wide_sprite.visible = false
	add_child(_wide_sprite)


func _build_tile_descriptors() -> void:
	_tiles.clear()
	for y in range(0, _cache_image.get_height(), LAZY_TILE_SIZE):
		for x in range(0, _cache_image.get_width(), LAZY_TILE_SIZE):
			var w := mini(LAZY_TILE_SIZE, _cache_image.get_width() - x)
			var h := mini(LAZY_TILE_SIZE, _cache_image.get_height() - y)
			_tiles.append({
				"cache_rect": Rect2i(x, y, w, h),
				"map_rect": Rect2(
					Vector2(x, y) / float(CACHE_SCALE),
					Vector2(w, h) / float(CACHE_SCALE)
				),
				"sprite": null,
				"last_visible_frame": -100000,
				"rgba8_bytes": w * h * 4,
			})


func _sync_transform() -> void:
	if _live_root == null:
		return
	position = _live_root.position
	scale = _live_root.scale
	rotation = _live_root.rotation


func _sync_lazy_tiles(viewport_size: Vector2) -> void:
	var viewport_rect := Rect2(Vector2.ZERO, viewport_size).grow(PREFETCH_MARGIN_PX)
	var resident := 0
	var resident_bytes := 0
	for index in range(_tiles.size()):
		var entry: Dictionary = _tiles[index]
		var local_rect: Rect2 = entry.get("map_rect", Rect2())
		var screen_rect := Rect2(
			position + local_rect.position * scale,
			local_rect.size * scale
		)
		var wanted := screen_rect.intersects(viewport_rect)
		var sprite := entry.get("sprite") as Sprite2D
		if wanted:
			entry["last_visible_frame"] = _frame_index
			if sprite == null:
				sprite = _materialize_tile(entry)
				entry["sprite"] = sprite
				if sprite != null:
					_created_total += 1
		elif sprite != null and _frame_index - int(entry.get("last_visible_frame", -100000)) > LAZY_RETAIN_FRAMES:
			sprite.queue_free()
			entry["sprite"] = null
			_evicted_total += 1
			sprite = null
		if sprite != null:
			sprite.visible = true
			resident += 1
			resident_bytes += int(entry.get("rgba8_bytes", 0))
		_tiles[index] = entry
	_peak_resident_tiles = maxi(_peak_resident_tiles, resident)
	_peak_resident_rgba8_bytes = maxi(_peak_resident_rgba8_bytes, resident_bytes)


func _materialize_tile(entry: Dictionary) -> Sprite2D:
	var cache_rect: Rect2i = entry.get("cache_rect", Rect2i())
	if cache_rect.size.x <= 0 or cache_rect.size.y <= 0:
		return null
	var region := _cache_image.get_region(cache_rect)
	if region == null or region.is_empty():
		return null
	var sprite := Sprite2D.new()
	sprite.centered = false
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	sprite.texture = ImageTexture.create_from_image(region)
	sprite.position = Vector2(cache_rect.position) / float(CACHE_SCALE)
	sprite.scale = Vector2.ONE / float(CACHE_SCALE)
	add_child(sprite)
	return sprite


func _evict_all_tiles() -> void:
	for index in range(_tiles.size()):
		var entry: Dictionary = _tiles[index]
		var sprite := entry.get("sprite") as Sprite2D
		if sprite != null:
			sprite.queue_free()
			entry["sprite"] = null
			_evicted_total += 1
		_tiles[index] = entry


func _wide_rgba8_bytes() -> int:
	if _cache_image == null or _cache_image.is_empty():
		return 0
	return int(
		ceili(float(_cache_image.get_width()) / float(CACHE_SCALE))
		* ceili(float(_cache_image.get_height()) / float(CACHE_SCALE))
		* 4.0
	)
