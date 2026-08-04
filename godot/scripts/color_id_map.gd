class_name ColorIdMap
extends RefCounted

var manifest: Dictionary = {}
var manifest_path := ""
var texture_path := ""
var background_path := ""
var background_status_text := "background: placeholder/none"
var id_image: Image
var land_silhouette_image: Image
var background_texture: ImageTexture
var owner_texture: ImageTexture
var border_texture: ImageTexture
var highlight_texture: ImageTexture
var debug_id_texture: ImageTexture
var province_by_color: Dictionary = {}
var row_by_province: Dictionary = {}
var anchor_bounds := Rect2()
var error := ""
var is_ready := false
var has_background := false
var debug_color_id_view := false
var debug_calibration_view := false
var control_points: Array = []
var calibration: Dictionary = {}
const OWNER_TINT_ALPHA := 0.32
const OWNER_TINT_ALPHA_NO_BG := 0.90
const DEFAULT_CONTROL_POINTS := [
	{"name": "london", "lat": 51.5074, "lon": -0.1278},
	{"name": "gibraltar", "lat": 36.1408, "lon": -5.3536},
	{"name": "rome", "lat": 41.9028, "lon": 12.4964},
	{"name": "istanbul", "lat": 41.0082, "lon": 28.9784},
	{"name": "moscow", "lat": 55.7558, "lon": 37.6173},
	{"name": "cairo", "lat": 30.0444, "lon": 31.2357},
	{"name": "northern_norway", "lat": 71.0, "lon": 25.0},
	{"name": "western_iceland", "lat": 64.8, "lon": -23.0},
]


func open(path: String, snapshot: Dictionary, faction_colors: Dictionary) -> bool:
	manifest_path = path
	error = ""
	is_ready = false
	has_background = false
	background_texture = null
	debug_id_texture = null
	land_silhouette_image = null
	province_by_color.clear()
	row_by_province.clear()
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
		province_by_color[key] = province_id
		row_by_province[province_id] = row
	if province_by_color.size() != int(manifest.get("province_count", province_by_color.size())):
		error = "Strategic map province table count does not match the manifest."
		return false
	_load_land_silhouette(path)
	_load_background(path)
	_rebuild_control_points()
	_rebuild_debug_id_texture()
	_compute_anchor_bounds()
	_rebuild_border_texture()
	refresh_snapshot(snapshot, faction_colors)
	is_ready = true
	return true


func _load_land_silhouette(manifest_file_path: String) -> void:
	var candidate := _resolve_relative_path(manifest_file_path, "land_silhouette.png")
	if not FileAccess.file_exists(candidate):
		candidate = _resolve_relative_path(manifest_file_path, "background_placeholder.png")
	if not FileAccess.file_exists(candidate):
		return
	var image := Image.load_from_file(candidate)
	if image == null or image.is_empty():
		return
	if image.get_width() != id_image.get_width() or image.get_height() != id_image.get_height():
		image.resize(id_image.get_width(), id_image.get_height(), Image.INTERPOLATE_BILINEAR)
	land_silhouette_image = image


func _load_background(manifest_file_path: String) -> void:
	background_path = ""
	has_background = false
	background_status_text = "background: placeholder"
	calibration = {}
	control_points = []

	var candidates: Array[String] = []
	# 1) Local external config next to manifest (gitignored).
	var local_cfg := _resolve_relative_path(manifest_file_path, "background_config.json")
	var cfg: Dictionary = {}
	if FileAccess.file_exists(local_cfg):
		var cfg_file := FileAccess.open(local_cfg, FileAccess.READ)
		if cfg_file != null:
			var parsed_cfg: Variant = JSON.parse_string(cfg_file.get_as_text())
			if parsed_cfg is Dictionary:
				cfg = parsed_cfg as Dictionary
				calibration = cfg.duplicate(true)
				var external := String(cfg.get("background_texture", "")).strip_edges()
				if not external.is_empty():
					candidates.append(external)
	# 2) Manifest optional path (must not be pack art committed to repo).
	var bg: Dictionary = manifest.get("visual_background", {})
	var rel := String(bg.get("path", "")).strip_edges()
	if not rel.is_empty() and not rel.ends_with("background_pack_reference.png"):
		candidates.append(_resolve_relative_path(manifest_file_path, rel))
	# 3) Project-owned placeholder fixture.
	candidates.append(_resolve_relative_path(manifest_file_path, "background_placeholder.png"))
	if land_silhouette_image != null:
		# Final guaranteed fallback built from silhouette image already loaded.
		pass

	for candidate in candidates:
		if candidate.is_empty() or not FileAccess.file_exists(candidate):
			continue
		var image := Image.load_from_file(candidate)
		if image == null or image.is_empty():
			continue
		image = _calibrate_background_image(image, cfg)
		background_texture = ImageTexture.create_from_image(image)
		background_path = candidate
		has_background = true
		var status := String(cfg.get("background_status", bg.get("asset_status", "local_or_placeholder")))
		if candidate.ends_with("background_placeholder.png"):
			status = "project_placeholder"
			background_status_text = "background: project_placeholder"
		else:
			background_status_text = "background: local_reference (%s)" % status
		return

	# Absolute last resort: solid dark frame from silhouette if present.
	if land_silhouette_image != null:
		background_texture = ImageTexture.create_from_image(land_silhouette_image)
		has_background = true
		background_status_text = "background: silhouette_fallback"
		return
	background_status_text = "background: none"


func _calibrate_background_image(source: Image, cfg: Dictionary) -> Image:
	"""Fit background into gameplay frame without independent X/Y distortion.

	If source already matches id map size and no offset/scale override, keep it.
	Otherwise letterbox/contain into the id-map frame.
	"""
	var target_w := id_image.get_width()
	var target_h := id_image.get_height()
	var scale_mul := float(cfg.get("scale", 1.0))
	var offset: Array = cfg.get("offset_px", [0.0, 0.0])
	var ox := float(offset[0]) if offset.size() > 0 else 0.0
	var oy := float(offset[1]) if offset.size() > 1 else 0.0
	var identity := is_equal_approx(scale_mul, 1.0) and is_zero_approx(ox) and is_zero_approx(oy)
	if source.get_width() == target_w and source.get_height() == target_h and identity:
		var ready := source.duplicate()
		ready.convert(Image.FORMAT_RGBA8)
		return ready

	var fit := String(cfg.get("fit", "contain"))
	var sx := float(target_w) / float(source.get_width())
	var sy := float(target_h) / float(source.get_height())
	var base := minf(sx, sy) if fit != "cover" else maxf(sx, sy)
	base *= scale_mul
	var draw_w := maxi(1, int(round(float(source.get_width()) * base)))
	var draw_h := maxi(1, int(round(float(source.get_height()) * base)))
	var resized := source.duplicate()
	resized.convert(Image.FORMAT_RGBA8)
	resized.resize(draw_w, draw_h, Image.INTERPOLATE_BILINEAR)

	var output := Image.create(target_w, target_h, false, Image.FORMAT_RGBA8)
	output.fill(Color(0.045, 0.055, 0.07, 1.0))
	var origin_x := int(round((float(target_w - draw_w) * 0.5) + ox))
	var origin_y := int(round((float(target_h - draw_h) * 0.5) + oy))
	output.blit_rect(resized, Rect2i(0, 0, resized.get_width(), resized.get_height()), Vector2i(origin_x, origin_y))
	return output


func _rebuild_control_points() -> void:
	control_points.clear()
	var bounds: Array = calibration.get("target_bounds_lon_lat", [-25.0, 50.0, 25.0, 72.0])
	if bounds.size() != 4:
		bounds = [-25.0, 50.0, 25.0, 72.0]
	var lon_min := float(bounds[0])
	var lon_max := float(bounds[1])
	var lat_min := float(bounds[2])
	var lat_max := float(bounds[3])
	var width := float(id_image.get_width())
	var height := float(id_image.get_height())
	var source_points: Array = calibration.get("control_points", DEFAULT_CONTROL_POINTS)
	for raw: Variant in source_points:
		if not raw is Dictionary:
			continue
		var row := raw as Dictionary
		var lat := float(row.get("lat", 0.0))
		var lon := float(row.get("lon", 0.0))
		var target_arr: Array = row.get("target_px", [])
		var result_arr: Array = row.get("resulting_px", [])
		var source_arr: Array = row.get("source_px", [])
		var target := Vector2.ZERO
		if target_arr.size() >= 2:
			target = Vector2(float(target_arr[0]), float(target_arr[1]))
		else:
			var lon_span := maxf(lon_max - lon_min, 0.0001)
			var lat_span := maxf(lat_max - lat_min, 0.0001)
			target = Vector2(
				(lon - lon_min) / lon_span * (width - 1.0),
				(lat_max - lat) / lat_span * (height - 1.0)
			)
		var resulting := target
		if result_arr.size() >= 2:
			resulting = Vector2(float(result_arr[0]), float(result_arr[1]))
		var err := float(row.get("error_px", target.distance_to(resulting)))
		control_points.append({
			"name": String(row.get("name", "?")),
			"lat": lat,
			"lon": lon,
			"source_px": Vector2(
				float(source_arr[0]) if source_arr.size() > 0 else 0.0,
				float(source_arr[1]) if source_arr.size() > 1 else 0.0
			),
			"target_px": target,
			"resulting_px": resulting,
			"error_px": err,
			"gameplay_px": target,
		})


func _rebuild_debug_id_texture() -> void:
	if id_image == null:
		return
	var output := Image.create(id_image.get_width(), id_image.get_height(), false, Image.FORMAT_RGBA8)
	for y in range(id_image.get_height()):
		for x in range(id_image.get_width()):
			var color := id_image.get_pixel(x, y)
			var province_id: String = province_by_color.get(_rgb_key(color), "")
			if province_id.is_empty():
				output.set_pixel(x, y, Color(0.04, 0.05, 0.06, 1.0))
			else:
				output.set_pixel(x, y, Color(color.r, color.g, color.b, 1.0))
	debug_id_texture = ImageTexture.create_from_image(output)


func refresh_snapshot(snapshot: Dictionary, faction_colors: Dictionary) -> void:
	if id_image == null or id_image.is_empty():
		return
	var ownership: Dictionary = {}
	for province: Dictionary in snapshot.get("provinces", []):
		ownership[String(province.get("id", ""))] = String(province.get("owner", "neutral"))
	var output := Image.create(id_image.get_width(), id_image.get_height(), false, Image.FORMAT_RGBA8)
	var tint_alpha := OWNER_TINT_ALPHA if has_background else OWNER_TINT_ALPHA_NO_BG
	for y in range(id_image.get_height()):
		for x in range(id_image.get_width()):
			var province_id: String = province_by_color.get(_rgb_key(id_image.get_pixel(x, y)), "")
			if province_id.is_empty():
				if has_background:
					output.set_pixel(x, y, Color(0.0, 0.0, 0.0, 0.0))
				else:
					output.set_pixel(x, y, Color(0.07, 0.085, 0.10, 1.0))
				continue
			var owner := String(ownership.get(province_id, "neutral"))
			var fill: Color = faction_colors.get(owner, faction_colors.get("neutral", Color("707780")))
			fill.a = tint_alpha
			output.set_pixel(x, y, fill)
	owner_texture = ImageTexture.create_from_image(output)


func refresh_highlights(selected_province_id: String, legal_targets: Dictionary) -> void:
	if id_image == null or id_image.is_empty():
		return
	var output := Image.create(id_image.get_width(), id_image.get_height(), false, Image.FORMAT_RGBA8)
	output.fill(Color.TRANSPARENT)
	for y in range(id_image.get_height()):
		for x in range(id_image.get_width()):
			var province_id: String = province_by_color.get(_rgb_key(id_image.get_pixel(x, y)), "")
			if province_id == selected_province_id:
				output.set_pixel(x, y, Color(0.20, 0.84, 1.0, 0.42))
			elif legal_targets.has(province_id):
				var option: Dictionary = legal_targets.get(province_id, {})
				var kind := String(option.get("kind", "move"))
				var color := Color(1.0, 0.48, 0.16, 0.40) if kind in ["battle", "capture"] else Color(0.25, 1.0, 0.50, 0.34)
				output.set_pixel(x, y, color)
	highlight_texture = ImageTexture.create_from_image(output)


func province_at_pixel(pixel: Vector2i) -> String:
	if id_image == null or pixel.x < 0 or pixel.y < 0 \
	or pixel.x >= id_image.get_width() or pixel.y >= id_image.get_height():
		return ""
	return String(province_by_color.get(_rgb_key(id_image.get_pixelv(pixel)), ""))


func anchor_pixel(province_id: String) -> Vector2:
	var row: Dictionary = row_by_province.get(province_id, {})
	var anchor: Array = row.get("marker_anchor", [])
	if anchor.size() != 2:
		return Vector2(id_image.get_width() * 0.5, id_image.get_height() * 0.5)
	var ax := float(anchor[0])
	var ay_bottom := float(anchor[1])
	if ax >= 0.0 and ay_bottom >= 0.0 and ax < float(id_image.get_width()) and ay_bottom < float(id_image.get_height()):
		return Vector2(ax, float(id_image.get_height() - 1) - ay_bottom)
	if anchor_bounds.size.x <= 0.0 or anchor_bounds.size.y <= 0.0:
		return Vector2(id_image.get_width() * 0.5, id_image.get_height() * 0.5)
	var normalized := Vector2(
		(ax - anchor_bounds.position.x) / anchor_bounds.size.x,
		1.0 - ((ay_bottom - anchor_bounds.position.y) / anchor_bounds.size.y)
	)
	return Vector2(
		normalized.x * float(id_image.get_width()),
		normalized.y * float(id_image.get_height())
	)


func image_size() -> Vector2:
	if id_image == null:
		return Vector2.ONE
	return Vector2(id_image.get_width(), id_image.get_height())


func background_status() -> String:
	return background_status_text


func _rebuild_border_texture() -> void:
	var output := Image.create(id_image.get_width(), id_image.get_height(), false, Image.FORMAT_RGBA8)
	output.fill(Color.TRANSPARENT)
	for y in range(id_image.get_height()):
		for x in range(id_image.get_width()):
			var current := province_at_pixel(Vector2i(x, y))
			if current.is_empty():
				continue
			var is_border := false
			for offset in [Vector2i.LEFT, Vector2i.RIGHT, Vector2i.UP, Vector2i.DOWN]:
				var other := province_at_pixel(Vector2i(x, y) + offset)
				if other != current:
					is_border = true
					break
			if is_border:
				output.set_pixel(x, y, Color(0.05, 0.07, 0.09, 0.55 if has_background else 0.82))
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
