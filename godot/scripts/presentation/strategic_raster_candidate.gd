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
## failure. Closer stationary views progressively hydrate visible 2x / 1024px
## tiles. While the camera is moving, the already-resident 1x theatre texture is
## used instead so pan/zoom never performs synchronous GPU texture creation.

const CACHE_SCALE := 2
const LAZY_TILE_SIZE := 1024
const LAZY_RETAIN_FRAMES := 2
const PREFETCH_MARGIN_PX := 96.0
const FULL_THEATRE_MAX_SCALE := 1.65
const DETAIL_SETTLE_FRAMES := 3
const MAX_TILE_CREATES_PER_FRAME := 3
const MAX_TILE_EVICTIONS_PER_FRAME := 1
const TRANSFORM_EPSILON_SQUARED := 0.0001
const ROTATION_EPSILON := 0.0001

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
var _have_transform_sample := false
var _last_position := Vector2.ZERO
var _last_scale := Vector2.ONE
var _last_rotation := 0.0
var _stable_transform_frames := 0


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
	_have_transform_sample = false
	_stable_transform_frames = 0
	if enabled:
		# The wide texture is already resident. Showing it immediately prevents a
		# blank frame while the first process tick classifies camera motion.
		if _wide_sprite != null:
			_wide_sprite.visible = true
		_set_tile_visibility(false)
	else:
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
	var camera_moved := _sample_transform_motion()
	if view_scale <= FULL_THEATRE_MAX_SCALE:
		_mode = "wide_1x"
		if _wide_sprite != null:
			_wide_sprite.visible = true
		_set_tile_visibility(false)
		_evict_tiles_bounded(MAX_TILE_EVICTIONS_PER_FRAME)
	elif camera_moved or _stable_transform_frames < DETAIL_SETTLE_FRAMES:
		# Never slice/upload 2x textures on a pan/zoom frame. The previous path did
		# exactly that, creating and evicting large ImageTextures while the camera
		# moved. Native acceptance exposed the resulting long hitch and VRAM churn.
		_mode = "moving_wide_1x"
		if _wide_sprite != null:
			_wide_sprite.visible = true
		_set_tile_visibility(false)
		_evict_tiles_bounded(MAX_TILE_EVICTIONS_PER_FRAME)
	else:
		var detail_ready := _sync_lazy_tiles(viewport_size)
		if detail_ready:
			_mode = "lazy_2x_1024"
			if _wide_sprite != null:
				_wide_sprite.visible = false
		else:
			# Keep the complete low-resolution image visible while at most a small,
			# bounded number of detail textures are uploaded each frame. This avoids
			# moving the pan hitch to the first stationary frame.
			_mode = "detail_warmup_1x"
			if _wide_sprite != null:
				_wide_sprite.visible = true
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
		"stable_transform_frames": _stable_transform_frames,
		"detail_settle_frames": DETAIL_SETTLE_FRAMES,
		"max_tile_creates_per_frame": MAX_TILE_CREATES_PER_FRAME,
		"max_tile_evictions_per_frame": MAX_TILE_EVICTIONS_PER_FRAME,
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
				"wanted": false,
				"last_visible_frame": -100000,
				"rgba8_bytes": w * h * 4,
			})


func _sync_transform() -> void:
	if _live_root == null:
		return
	position = _live_root.position
	scale = _live_root.scale
	rotation = _live_root.rotation


func _sample_transform_motion() -> bool:
	if not _have_transform_sample:
		_have_transform_sample = true
		_last_position = position
		_last_scale = scale
		_last_rotation = rotation
		_stable_transform_frames = 0
		return true
	var changed := position.distance_squared_to(_last_position) > TRANSFORM_EPSILON_SQUARED \
		or scale.distance_squared_to(_last_scale) > TRANSFORM_EPSILON_SQUARED \
		or absf(rotation - _last_rotation) > ROTATION_EPSILON
	_last_position = position
	_last_scale = scale
	_last_rotation = rotation
	if changed:
		_stable_transform_frames = 0
	else:
		_stable_transform_frames += 1
	return changed


func _sync_lazy_tiles(viewport_size: Vector2) -> bool:
	var viewport_rect := Rect2(Vector2.ZERO, viewport_size).grow(PREFETCH_MARGIN_PX)
	var resident := 0
	var resident_bytes := 0
	var creates_remaining := MAX_TILE_CREATES_PER_FRAME
	var evictions_remaining := MAX_TILE_EVICTIONS_PER_FRAME
	var all_wanted_ready := true
	for index in range(_tiles.size()):
		var entry: Dictionary = _tiles[index]
		var local_rect: Rect2 = entry.get("map_rect", Rect2())
		var screen_rect := Rect2(
			position + local_rect.position * scale,
			local_rect.size * scale
		)
		var wanted := screen_rect.intersects(viewport_rect)
		entry["wanted"] = wanted
		var sprite := entry.get("sprite") as Sprite2D
		if wanted:
			entry["last_visible_frame"] = _frame_index
			if sprite == null and creates_remaining > 0:
				creates_remaining -= 1
				sprite = _materialize_tile(entry)
				entry["sprite"] = sprite
				if sprite != null:
					_created_total += 1
			if sprite == null:
				all_wanted_ready = false
		elif sprite != null \
		and evictions_remaining > 0 \
		and _frame_index - int(entry.get("last_visible_frame", -100000)) > LAZY_RETAIN_FRAMES:
			sprite.queue_free()
			entry["sprite"] = null
			_evicted_total += 1
			evictions_remaining -= 1
			sprite = null
		if sprite != null:
			resident += 1
			resident_bytes += int(entry.get("rgba8_bytes", 0))
		_tiles[index] = entry
	if all_wanted_ready:
		_set_wanted_tile_visibility()
	else:
		_set_tile_visibility(false)
	_peak_resident_tiles = maxi(_peak_resident_tiles, resident)
	_peak_resident_rgba8_bytes = maxi(_peak_resident_rgba8_bytes, resident_bytes)
	return all_wanted_ready


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
	sprite.visible = false
	add_child(sprite)
	return sprite


func _set_tile_visibility(tiles_visible: bool) -> void:
	for entry_value in _tiles:
		var entry: Dictionary = entry_value
		var sprite := entry.get("sprite") as Sprite2D
		if sprite != null:
			sprite.visible = tiles_visible


func _set_wanted_tile_visibility() -> void:
	for entry_value in _tiles:
		var entry: Dictionary = entry_value
		var sprite := entry.get("sprite") as Sprite2D
		if sprite != null:
			sprite.visible = bool(entry.get("wanted", false))


func _evict_tiles_bounded(limit: int) -> void:
	if limit <= 0:
		return
	var remaining := limit
	for index in range(_tiles.size()):
		if remaining <= 0:
			break
		var entry: Dictionary = _tiles[index]
		var sprite := entry.get("sprite") as Sprite2D
		if sprite == null:
			continue
		sprite.visible = false
		sprite.queue_free()
		entry["sprite"] = null
		entry["wanted"] = false
		_evicted_total += 1
		remaining -= 1
		_tiles[index] = entry


func _evict_all_tiles() -> void:
	for index in range(_tiles.size()):
		var entry: Dictionary = _tiles[index]
		var sprite := entry.get("sprite") as Sprite2D
		if sprite != null:
			sprite.queue_free()
			entry["sprite"] = null
			entry["wanted"] = false
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
