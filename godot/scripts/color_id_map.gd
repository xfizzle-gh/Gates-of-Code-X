class_name ColorIdMap
extends RefCounted

## Authoritative color-ID province layer plus cached visual ownership/border/highlight textures.
## Hit-testing always samples the unfiltered ID image (nearest). Visual textures are rebuilt
## only when ownership or selection inputs change, using precomputed province pixel runs.

var manifest: Dictionary = {}
var manifest_path := ""
var texture_path := ""
var id_image: Image
var background_texture: ImageTexture
var owner_texture: ImageTexture
var border_texture: ImageTexture
var highlight_texture: ImageTexture
var province_by_color: Dictionary = {}
var row_by_province: Dictionary = {}
var anchor_bounds := Rect2()
var error := ""
var is_ready := false
var has_background := false
var background_status_text := "background: none"
const OWNER_TINT_ALPHA := 0.34
const OWNER_TINT_ALPHA_NO_BG := 0.90

# Cached geometry / invalidation
var _width := 0
var _height := 0
var _pixel_count := 0
var _province_ids: PackedStringArray = PackedStringArray()
var _province_index_by_id: Dictionary = {}
var _pixel_province_index: PackedInt32Array = PackedInt32Array()
var _province_pixel_runs: Array = [] # Array[PackedInt32Array] linear indices per province
var _owner_image: Image
var _highlight_image: Image
var _last_ownership: Dictionary = {}
var _last_selected_id := ""
var _last_target_ids: Dictionary = {}
var _highlighted_province_ids: Array = []
var _owner_dirty := true
var _highlight_dirty := true

# Perf counters (presentation diagnostics only)
var stat_full_owner_rebuilds := 0
var stat_partial_owner_rebuilds := 0
var stat_highlight_rebuilds := 0
var stat_pixels_touched_last := 0
var stat_owner_rebuild_usec_last := 0
var stat_highlight_rebuild_usec_last := 0
var stat_static_rebuilds_this_frame := 0
var stat_static_rebuilds_displayed := 0
var stat_last_event := "none"


func open(path: String, snapshot: Dictionary, faction_colors: Dictionary) -> bool:
	manifest_path = path
	error = ""
	is_ready = false
	has_background = false
	background_texture = null
	owner_texture = null
	border_texture = null
	highlight_texture = null
	province_by_color.clear()
	row_by_province.clear()
	_province_ids = PackedStringArray()
	_province_index_by_id.clear()
	_pixel_province_index = PackedInt32Array()
	_province_pixel_runs.clear()
	_owner_image = null
	_highlight_image = null
	_last_ownership.clear()
	_last_selected_id = ""
	_last_target_ids.clear()
	_highlighted_province_ids.clear()
	_owner_dirty = true
	_highlight_dirty = true
	if not FileAccess.file_exists(path):
		error = "Strategic map manifest not found: %s" % path
		return false
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		error = "Unable to open strategic map manifest: %s" % path
		return false
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		error = "Strategic map manifest is not valid JSON."
		return false
	manifest = parsed as Dictionary
	if String(manifest.get("schema", "")) != "gates-of-codex.strategic-map":
		error = "Unsupported strategic map manifest schema."
		return false
	var texture: Dictionary = manifest.get("id_texture", {})
	if String(texture.get("sampling", "")) != "nearest":
		error = "Strategic ID map must use nearest-neighbor sampling."
		return false
	texture_path = _resolve_relative_path(path, String(texture.get("path", "")))
	if not FileAccess.file_exists(texture_path):
		error = "Strategic ID texture not found: %s" % texture_path
		return false
	id_image = Image.load_from_file(texture_path)
	if id_image == null or id_image.is_empty():
		error = "Unable to load strategic ID texture: %s" % texture_path
		return false
	id_image.convert(Image.FORMAT_RGB8)
	if int(texture.get("width", id_image.get_width())) != id_image.get_width() \
	or int(texture.get("height", id_image.get_height())) != id_image.get_height():
		error = "Strategic ID texture dimensions do not match the manifest."
		return false
	_width = id_image.get_width()
	_height = id_image.get_height()
	_pixel_count = _width * _height
	for raw_row: Variant in manifest.get("province_table", []):
		if not raw_row is Dictionary:
			continue
		var row := raw_row as Dictionary
		var province_id := String(row.get("province_id", ""))
		var rgb: Array = row.get("rgb", [])
		if province_id.is_empty() or rgb.size() != 3:
			error = "Strategic map province table contains an invalid row."
			return false
		var key := _rgb_key_from_channels(int(rgb[0]), int(rgb[1]), int(rgb[2]))
		if province_by_color.has(key) or row_by_province.has(province_id):
			error = "Strategic map province table contains duplicate RGB or province IDs."
			return false
		var index := _province_ids.size()
		_province_ids.append(province_id)
		_province_index_by_id[province_id] = index
		province_by_color[key] = province_id
		row_by_province[province_id] = row
		_province_pixel_runs.append(PackedInt32Array())
	if province_by_color.size() != int(manifest.get("province_count", province_by_color.size())):
		error = "Strategic map province table count does not match the manifest."
		return false
	_build_pixel_index_and_runs()
	_load_background(path)
	_compute_anchor_bounds()
	_rebuild_border_texture()
	refresh_snapshot(snapshot, faction_colors)
	is_ready = true
	return true


func _build_pixel_index_and_runs() -> void:
	_pixel_province_index.resize(_pixel_count)
	var run_builders: Array = []
	run_builders.resize(_province_ids.size())
	for i in range(_province_ids.size()):
		run_builders[i] = []
	var idx := 0
	for y in range(_height):
		for x in range(_width):
			var province_id: String = province_by_color.get(_rgb_key(id_image.get_pixel(x, y)), "")
			if province_id.is_empty():
				_pixel_province_index[idx] = -1
			else:
				var pindex: int = int(_province_index_by_id.get(province_id, -1))
				_pixel_province_index[idx] = pindex
				if pindex >= 0:
					(run_builders[pindex] as Array).append(idx)
			idx += 1
	for i in range(_province_ids.size()):
		_province_pixel_runs[i] = PackedInt32Array(run_builders[i])


func _load_background(manifest_file_path: String) -> void:
	has_background = false
	background_texture = null
	background_status_text = "background: none"
	var bg: Dictionary = manifest.get("visual_background", {})
	var rel := String(bg.get("path", "background_procedural.png")).strip_edges()
	var candidate := _resolve_relative_path(manifest_file_path, rel)
	if not FileAccess.file_exists(candidate):
		return
	var image := Image.load_from_file(candidate)
	if image == null or image.is_empty():
		return
	if image.get_width() != _width or image.get_height() != _height:
		image.resize(_width, _height, Image.INTERPOLATE_BILINEAR)
	image.convert(Image.FORMAT_RGBA8)
	background_texture = ImageTexture.create_from_image(image)
	# Filtering is applied by dedicated CanvasItem layers (linear background node).
	has_background = true
	var status := String(bg.get("asset_status", "project_procedural"))
	if status in ["project_procedural", "project_owned_procedural"] or rel.ends_with("background_procedural.png"):
		background_status_text = "background: project_procedural"
	else:
		background_status_text = "background: %s" % status


func background_status() -> String:
	return background_status_text


func refresh_snapshot(snapshot: Dictionary, faction_colors: Dictionary) -> void:
	if id_image == null or id_image.is_empty() or _pixel_count == 0:
		return
	var ownership: Dictionary = {}
	for province: Dictionary in snapshot.get("provinces", []):
		ownership[String(province.get("id", ""))] = String(province.get("owner", "neutral"))
	var changed: Array = []
	if _owner_image == null or _last_ownership.is_empty():
		_rebuild_owner_full(ownership, faction_colors)
		_last_ownership = ownership.duplicate()
		_owner_dirty = false
		stat_static_rebuilds_this_frame += 1
		return
	for province_id: Variant in row_by_province.keys():
		var pid := String(province_id)
		var next_owner := String(ownership.get(pid, "neutral"))
		var prev_owner := String(_last_ownership.get(pid, ""))
		if next_owner != prev_owner:
			changed.append(pid)
	# Provinces removed from snapshot ownership map
	for province_id: Variant in _last_ownership.keys():
		var pid := String(province_id)
		if not ownership.has(pid) and row_by_province.has(pid):
			if pid not in changed:
				changed.append(pid)
	if changed.is_empty():
		_owner_dirty = false
		return
	_rebuild_owner_partial(changed, ownership, faction_colors)
	_last_ownership = ownership.duplicate()
	_owner_dirty = false
	stat_static_rebuilds_this_frame += 1


func _rebuild_owner_full(ownership: Dictionary, faction_colors: Dictionary) -> void:
	var t0 := Time.get_ticks_usec()
	var tint_alpha := OWNER_TINT_ALPHA if has_background else OWNER_TINT_ALPHA_NO_BG
	_owner_image = Image.create(_width, _height, false, Image.FORMAT_RGBA8)
	var empty_color := Color(0, 0, 0, 0) if has_background else Color(0.07, 0.085, 0.10, 1.0)
	_owner_image.fill(empty_color)
	stat_pixels_touched_last = 0
	for pindex in range(_province_ids.size()):
		var province_id := String(_province_ids[pindex])
		var owner := String(ownership.get(province_id, "neutral"))
		var fill: Color = faction_colors.get(owner, faction_colors.get("neutral", Color("707780")))
		fill.a = tint_alpha
		var runs: PackedInt32Array = _province_pixel_runs[pindex]
		for linear in runs:
			var x := int(linear) % _width
			var y := int(linear) / _width
			_owner_image.set_pixel(x, y, fill)
		stat_pixels_touched_last += runs.size()
	if owner_texture == null:
		owner_texture = ImageTexture.create_from_image(_owner_image)
	else:
		owner_texture.update(_owner_image)
	stat_full_owner_rebuilds += 1
	stat_owner_rebuild_usec_last = Time.get_ticks_usec() - t0
	stat_last_event = "owner_full"


func _rebuild_owner_partial(changed_ids: Array, ownership: Dictionary, faction_colors: Dictionary) -> void:
	var t0 := Time.get_ticks_usec()
	var tint_alpha := OWNER_TINT_ALPHA if has_background else OWNER_TINT_ALPHA_NO_BG
	stat_pixels_touched_last = 0
	for province_id_variant in changed_ids:
		var province_id := String(province_id_variant)
		var pindex: int = int(_province_index_by_id.get(province_id, -1))
		if pindex < 0:
			continue
		var owner := String(ownership.get(province_id, "neutral"))
		var fill: Color = faction_colors.get(owner, faction_colors.get("neutral", Color("707780")))
		fill.a = tint_alpha
		var runs: PackedInt32Array = _province_pixel_runs[pindex]
		for linear in runs:
			var x := int(linear) % _width
			var y := int(linear) / _width
			_owner_image.set_pixel(x, y, fill)
		stat_pixels_touched_last += runs.size()
	if owner_texture == null:
		owner_texture = ImageTexture.create_from_image(_owner_image)
	else:
		owner_texture.update(_owner_image)
	stat_partial_owner_rebuilds += 1
	stat_owner_rebuild_usec_last = Time.get_ticks_usec() - t0
	stat_last_event = "owner_partial"


func refresh_highlights(selected_province_id: String, legal_targets: Dictionary) -> void:
	if id_image == null or id_image.is_empty() or _pixel_count == 0:
		return
	var target_ids: Dictionary = {}
	for key: Variant in legal_targets.keys():
		target_ids[String(key)] = legal_targets[key]
	if _highlight_image != null \
	and selected_province_id == _last_selected_id \
	and _target_dicts_equal(target_ids, _last_target_ids):
		_highlight_dirty = false
		return
	var t0 := Time.get_ticks_usec()
	if _highlight_image == null:
		_highlight_image = Image.create(_width, _height, false, Image.FORMAT_RGBA8)
		_highlight_image.fill(Color.TRANSPARENT)
	else:
		# Clear only previously painted provinces.
		for province_id_variant in _highlighted_province_ids:
			_fill_province_pixels(String(province_id_variant), Color.TRANSPARENT)
	_highlighted_province_ids.clear()
	stat_pixels_touched_last = 0
	if not selected_province_id.is_empty() and row_by_province.has(selected_province_id):
		_fill_province_pixels(selected_province_id, Color(0.20, 0.84, 1.0, 0.42))
		_highlighted_province_ids.append(selected_province_id)
	for target_id_variant in target_ids.keys():
		var target_id := String(target_id_variant)
		if target_id.is_empty() or target_id == selected_province_id:
			continue
		if not row_by_province.has(target_id):
			continue
		var option: Dictionary = target_ids.get(target_id, {})
		var kind := String(option.get("kind", "move"))
		var color := Color(1.0, 0.48, 0.16, 0.40) if kind in ["battle", "capture"] else Color(0.25, 1.0, 0.50, 0.34)
		_fill_province_pixels(target_id, color)
		_highlighted_province_ids.append(target_id)
	if highlight_texture == null:
		highlight_texture = ImageTexture.create_from_image(_highlight_image)
	else:
		highlight_texture.update(_highlight_image)
	_last_selected_id = selected_province_id
	_last_target_ids = target_ids.duplicate()
	_highlight_dirty = false
	stat_highlight_rebuilds += 1
	stat_highlight_rebuild_usec_last = Time.get_ticks_usec() - t0
	stat_static_rebuilds_this_frame += 1
	stat_last_event = "highlight"


func _fill_province_pixels(province_id: String, color: Color) -> void:
	var pindex: int = int(_province_index_by_id.get(province_id, -1))
	if pindex < 0 or _highlight_image == null:
		return
	var runs: PackedInt32Array = _province_pixel_runs[pindex]
	for linear in runs:
		var x := int(linear) % _width
		var y := int(linear) / _width
		_highlight_image.set_pixel(x, y, color)
	stat_pixels_touched_last += runs.size()


func _target_dicts_equal(left: Dictionary, right: Dictionary) -> bool:
	if left.size() != right.size():
		return false
	for key: Variant in left.keys():
		if not right.has(key):
			return false
		var lopt: Dictionary = left[key]
		var ropt: Dictionary = right[key]
		if String(lopt.get("kind", "")) != String(ropt.get("kind", "")):
			return false
		# Graph orders carry no kind; the edge identity is what changes.
		if String(lopt.get("edge_id", "")) != String(ropt.get("edge_id", "")):
			return false
	return true


func province_at_pixel(pixel: Vector2i) -> String:
	if id_image == null or pixel.x < 0 or pixel.y < 0 \
	or pixel.x >= _width or pixel.y >= _height:
		return ""
	if _pixel_province_index.size() == _pixel_count:
		var pindex := int(_pixel_province_index[pixel.y * _width + pixel.x])
		if pindex < 0 or pindex >= _province_ids.size():
			return ""
		return String(_province_ids[pindex])
	return String(province_by_color.get(_rgb_key(id_image.get_pixelv(pixel)), ""))


func anchor_pixel(province_id: String) -> Vector2:
	var row: Dictionary = row_by_province.get(province_id, {})
	var anchor: Array = row.get("marker_anchor", [])
	if anchor.size() != 2:
		return Vector2(_width * 0.5, _height * 0.5)
	var ax := float(anchor[0])
	var ay_bottom := float(anchor[1])
	# Cropped theatre stores anchors in image pixel space (bottom-left Y).
	if ax >= 0.0 and ay_bottom >= 0.0 and ax < float(_width) and ay_bottom < float(_height):
		return Vector2(ax, float(_height - 1) - ay_bottom)
	if anchor_bounds.size.x <= 0.0 or anchor_bounds.size.y <= 0.0:
		return Vector2(_width * 0.5, _height * 0.5)
	var normalized := Vector2(
		(ax - anchor_bounds.position.x) / anchor_bounds.size.x,
		1.0 - ((ay_bottom - anchor_bounds.position.y) / anchor_bounds.size.y)
	)
	return Vector2(
		normalized.x * float(_width),
		normalized.y * float(_height)
	)


func image_size() -> Vector2:
	if id_image == null:
		return Vector2.ONE
	return Vector2(_width, _height)


func get_perf_stats() -> Dictionary:
	return {
		"full_owner_rebuilds": stat_full_owner_rebuilds,
		"partial_owner_rebuilds": stat_partial_owner_rebuilds,
		"highlight_rebuilds": stat_highlight_rebuilds,
		"pixels_touched_last": stat_pixels_touched_last,
		"owner_rebuild_ms_last": snappedf(stat_owner_rebuild_usec_last / 1000.0, 0.001),
		"highlight_rebuild_ms_last": snappedf(stat_highlight_rebuild_usec_last / 1000.0, 0.001),
		"static_rebuilds_this_frame": stat_static_rebuilds_this_frame,
		"static_rebuilds_displayed": stat_static_rebuilds_displayed,
		"last_event": stat_last_event,
		"cached_province_runs": _province_pixel_runs.size(),
		"pixel_index_size": _pixel_province_index.size(),
	}


func begin_frame_stats() -> void:
	# Prefer end_frame_stats() after the debug overlay reads counters.
	stat_static_rebuilds_this_frame = 0


func end_frame_stats() -> void:
	# Snapshot then clear so the next invalidation window accumulates cleanly.
	stat_static_rebuilds_displayed = stat_static_rebuilds_this_frame
	stat_static_rebuilds_this_frame = 0


func _rebuild_border_texture() -> void:
	# Borders only between two different PLAYABLE provinces.
	var output := Image.create(_width, _height, false, Image.FORMAT_RGBA8)
	output.fill(Color.TRANSPARENT)
	var border_color := Color(0.40, 0.43, 0.46, 0.55 if has_background else 0.65)
	# Slightly stronger edge for readability when upscaled with nearest sampling.
	var border_soft := Color(0.55, 0.58, 0.62, 0.28 if has_background else 0.35)
	for y in range(_height):
		for x in range(_width):
			var linear := y * _width + x
			var current_idx := int(_pixel_province_index[linear])
			if current_idx < 0:
				continue
			var edge := false
			if x + 1 < _width:
				var right_idx := int(_pixel_province_index[linear + 1])
				if right_idx >= 0 and right_idx != current_idx:
					edge = true
			if not edge and y + 1 < _height:
				var down_idx := int(_pixel_province_index[linear + _width])
				if down_idx >= 0 and down_idx != current_idx:
					edge = true
			if edge:
				output.set_pixel(x, y, border_color)
				# 1px soft halo toward interior for less harsh upscale stair-steps.
				if x > 0 and int(_pixel_province_index[linear - 1]) == current_idx:
					var existing := output.get_pixel(x - 1, y)
					if existing.a <= 0.0:
						output.set_pixel(x - 1, y, border_soft)
				if y > 0 and int(_pixel_province_index[linear - _width]) == current_idx:
					var existing_up := output.get_pixel(x, y - 1)
					if existing_up.a <= 0.0:
						output.set_pixel(x, y - 1, border_soft)
	border_texture = ImageTexture.create_from_image(output)


func _compute_anchor_bounds() -> void:
	var min_x := INF
	var min_y := INF
	var max_x := -INF
	var max_y := -INF
	for row: Dictionary in row_by_province.values():
		var anchor: Array = row.get("marker_anchor", [])
		if anchor.size() != 2:
			continue
		min_x = minf(min_x, float(anchor[0]))
		max_x = maxf(max_x, float(anchor[0]))
		min_y = minf(min_y, float(anchor[1]))
		max_y = maxf(max_y, float(anchor[1]))
	if is_inf(min_x) or is_inf(min_y):
		anchor_bounds = Rect2(Vector2.ZERO, Vector2.ONE)
	else:
		anchor_bounds = Rect2(
			Vector2(min_x, min_y),
			Vector2(maxf(max_x - min_x, 1.0), maxf(max_y - min_y, 1.0))
		)


func _resolve_relative_path(base_path: String, relative_path: String) -> String:
	if relative_path.begins_with("res://") or relative_path.begins_with("user://") or relative_path.is_absolute_path():
		return relative_path
	return base_path.get_base_dir().path_join(relative_path).simplify_path()


func _rgb_key(color: Color) -> int:
	return _rgb_key_from_channels(
		clampi(roundi(color.r * 255.0), 0, 255),
		clampi(roundi(color.g * 255.0), 0, 255),
		clampi(roundi(color.b * 255.0), 0, 255)
	)


func _rgb_key_from_channels(red: int, green: int, blue: int) -> int:
	return (red << 16) | (green << 8) | blue
