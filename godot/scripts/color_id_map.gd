class_name ColorIdMap
extends RefCounted

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


func open(path: String, snapshot: Dictionary, faction_colors: Dictionary) -> bool:
	manifest_path = path
	error = ""
	is_ready = false
	has_background = false
	background_texture = null
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
	_load_background(path)
	_compute_anchor_bounds()
	_rebuild_border_texture()
	refresh_snapshot(snapshot, faction_colors)
	is_ready = true
	return true


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
	if image.get_width() != id_image.get_width() or image.get_height() != id_image.get_height():
		image.resize(id_image.get_width(), id_image.get_height(), Image.INTERPOLATE_BILINEAR)
	image.convert(Image.FORMAT_RGBA8)
	background_texture = ImageTexture.create_from_image(image)
	has_background = true
	var status := String(bg.get("asset_status", "project_procedural"))
	if status in ["project_procedural", "project_owned_procedural"] or rel.ends_with("background_procedural.png"):
		background_status_text = "background: project_procedural"
	else:
		background_status_text = "background: %s" % status


func background_status() -> String:
	return background_status_text


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
					output.set_pixel(x, y, Color(0, 0, 0, 0))
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
	# Cropped theatre stores anchors in image pixel space (bottom-left Y).
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
				# Subtle gray edge; selected/front overlays carry emphasis.
				output.set_pixel(x, y, Color(0.42, 0.45, 0.48, 0.38 if has_background else 0.50))
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
