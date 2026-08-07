class_name PolygonMap
extends RefCounted

## Polygon-mesh strategic map for Earth3 production theatre.
## Land geometry is immutable after open(); ownership recolor updates a 1D lookup texture only.
## Water is a continuous ocean underlay (no per-water-province fills).
## v1 water policy: water IDs are import metadata only — not normally selectable.

const SCHEMA := "gates-of-codex.earth3-polygon-dataset"
# Larger chunks cut MeshInstance2D count (draw setup) while keeping geometry immutable.
const CHUNK := 1024
const OWNERSHIP_SHADER_PATH := "res://shaders/province_ownership.gdshader"
const OCEAN_COLOR := Color(0.09, 0.15, 0.24, 1.0)
const COAST_COLOR := Color(0.05, 0.07, 0.1, 0.96)
const LAND_BORDER_COLOR := Color(0.14, 0.16, 0.18, 0.55)
const FEDERAL_BORDER_COLOR := Color(0.22, 0.2, 0.16, 0.35)
const NEUTRAL_LAND_COLOR := Color(0.55, 0.57, 0.5, 1.0)
const OWNERSHIP_MIX_DEFAULT := 0.46

var is_ready := false
var error := ""
var map_id := ""
var province_count := 0
var image_size_v := Vector2.ONE
var load_ms := 0.0
var refresh_ms := 0.0
var mesh_count := 0
var visible_province_count := 0
var land_province_count := 0
var water_province_count := 0
var background_texture: Texture2D = null
var owner_texture: Texture2D = null
var border_texture: Texture2D = null
var highlight_texture: Texture2D = null
var renderer_name := "polygon_mesh"
var _host: Node2D = null

var row_by_province: Dictionary = {}
var index_by_province: Dictionary = {}
var province_by_index: PackedStringArray = PackedStringArray()
var owners: PackedStringArray = PackedStringArray()
var is_water: PackedByteArray = PackedByteArray()
var centroids: PackedVector2Array = PackedVector2Array()
var bounds_min: PackedVector2Array = PackedVector2Array()
var bounds_max: PackedVector2Array = PackedVector2Array()
var rings: Array = []

var _meshes: Array = []
var _mesh_instances: Array = []
var _ocean_mesh: ArrayMesh = null
var _ocean_instance: MeshInstance2D = null
var _border_mesh: ArrayMesh = null
var _border_instance: MeshInstance2D = null
var _grid: Dictionary = {}
var _grid_cell := 48.0
var _owner_colors: Dictionary = {}
var _hover_index := -1
var _selected_id := ""
var _legal_targets: Dictionary = {}

var _ownership_image: Image = null
var _ownership_tex: ImageTexture = null
var _ownership_shader: Shader = null
var _fill_material: ShaderMaterial = null
var _tex_width := 1
var _geometry_built := false
var _view_scale := 1.0
var _border_base_modulate := Color(1, 1, 1, 1)
var _suppress_border_keys: Dictionary = {}
var _last_faction_colors_sig := ""


func open(manifest_path: String, snapshot: Dictionary, faction_colors: Dictionary) -> bool:
	is_ready = false
	error = ""
	_geometry_built = false
	var t0 := Time.get_ticks_msec()
	_owner_colors = faction_colors.duplicate(true)
	if not FileAccess.file_exists(manifest_path):
		error = "manifest missing: %s" % manifest_path
		return false
	var manifest := _load_json(manifest_path)
	if manifest.is_empty():
		error = "manifest invalid"
		return false
	if String(manifest.get("renderer", "")) != "polygon_mesh":
		error = "manifest renderer is not polygon_mesh"
		return false
	map_id = String(manifest.get("map_id", ""))
	var ds_rel := String(manifest.get("polygon_dataset", {}).get("path", "polygon_dataset.json"))
	var base_dir := manifest_path.get_base_dir()
	var ds_path := base_dir.path_join(ds_rel)
	if not FileAccess.file_exists(ds_path):
		error = "dataset missing: %s" % ds_path
		return false
	var data := _load_json(ds_path)
	if data.is_empty():
		error = "dataset invalid/empty"
		return false
	if String(data.get("schema", "")) != SCHEMA:
		error = "dataset schema mismatch"
		return false
	var b: Dictionary = data.get("bounds", {})
	image_size_v = Vector2(float(b.get("width", 1.0)), float(b.get("height", 1.0)))
	if image_size_v.x <= 0.0 or image_size_v.y <= 0.0:
		image_size_v = Vector2.ONE

	var provinces: Array = data.get("provinces", [])
	province_count = provinces.size()
	row_by_province.clear()
	index_by_province.clear()
	province_by_index = PackedStringArray()
	owners = PackedStringArray()
	is_water = PackedByteArray()
	centroids = PackedVector2Array()
	bounds_min = PackedVector2Array()
	bounds_max = PackedVector2Array()
	rings.clear()
	_suppress_border_keys.clear()
	# Allowlisted excluded-outline edges only (meta.contract=allowlisted_excluded_source_outline_only).
	# Default: src 11836 northern pseudo-outline — not general crop-exterior borders.
	for seg: Variant in data.get("exterior_border_suppress", []):
		if not (seg is Array and (seg as Array).size() >= 4):
			continue
		var s: Array = seg
		var key := _edge_key(
			Vector2(float(s[0]), float(s[1])),
			Vector2(float(s[2]), float(s[3]))
		)
		if not key.is_empty():
			_suppress_border_keys[key] = true
	province_by_index.resize(province_count)
	owners.resize(province_count)
	is_water.resize(province_count)
	centroids.resize(province_count)
	bounds_min.resize(province_count)
	bounds_max.resize(province_count)
	rings.resize(province_count)
	land_province_count = 0
	water_province_count = 0

	var owner_by_id: Dictionary = {}
	for p: Dictionary in snapshot.get("provinces", []):
		owner_by_id[String(p.get("id", ""))] = String(p.get("owner", "neutral"))

	_tex_width = maxi(1, nearest_po2(maxi(province_count, 1)))
	_ownership_image = Image.create(_tex_width, 1, false, Image.FORMAT_RGBA8)
	_ensure_ownership_material()

	_meshes.clear()
	var st := SurfaceTool.new()
	var in_chunk := 0
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	# edge_key -> [land_registration_count, water_registration_count]
	var edge_counts: Dictionary = {}

	for i in province_count:
		var row: Dictionary = provinces[i]
		var pid := String(row.get("id", ""))
		row_by_province[pid] = row
		index_by_province[pid] = i
		province_by_index[i] = pid
		var water := bool(row.get("is_water", false))
		is_water[i] = 1 if water else 0
		if water:
			water_province_count += 1
		else:
			land_province_count += 1
		var owner := String(owner_by_id.get(pid, "neutral"))
		if water:
			owner = "water"
		owners[i] = owner
		var c: Array = row.get("centroid", [0.0, 0.0])
		centroids[i] = Vector2(float(c[0]), float(c[1]))

		var ring_pts := PackedVector2Array()
		var ring_raw: Array = row.get("ring", [])
		var min_v := Vector2(INF, INF)
		var max_v := Vector2(-INF, -INF)
		for ri in range(0, ring_raw.size(), 2):
			if ri + 1 >= ring_raw.size():
				break
			var rp := Vector2(float(ring_raw[ri]), float(ring_raw[ri + 1]))
			ring_pts.append(rp)
			min_v = min_v.min(rp)
			max_v = max_v.max(rp)
		rings[i] = ring_pts
		_register_ring_edges(edge_counts, ring_pts, water)

		# Water: keep IDs/rings/hit-test only — no filled polygon blocks.
		if not water:
			var verts: Array = row.get("vertices", [])
			var tris: Array = row.get("triangles", [])
			var u := (float(i) + 0.5) / float(_tex_width)
			for t in range(0, tris.size(), 3):
				if t + 2 >= tris.size():
					break
				for k in 3:
					var vi := int(tris[t + k]) * 2
					if vi + 1 >= verts.size():
						continue
					var p := Vector2(float(verts[vi]), float(verts[vi + 1]))
					if min_v.x == INF:
						min_v = p
						max_v = p
					else:
						min_v = min_v.min(p)
						max_v = max_v.max(p)
					st.set_uv(Vector2(u, 0.5))
					st.add_vertex(Vector3(p.x, p.y, 0.0))
			in_chunk += 1
			if in_chunk >= CHUNK:
				var mesh := st.commit()
				_meshes.append(mesh)
				mesh_count = _meshes.size()
				st = SurfaceTool.new()
				st.begin(Mesh.PRIMITIVE_TRIANGLES)
				in_chunk = 0
		if min_v.x == INF:
			min_v = centroids[i]
			max_v = centroids[i]
		bounds_min[i] = min_v
		bounds_max[i] = max_v

	if in_chunk > 0:
		var mesh_last := st.commit()
		_meshes.append(mesh_last)
		mesh_count = _meshes.size()

	_build_ocean_mesh()
	_build_border_mesh_from_edges(edge_counts)
	_write_all_ownership_colors()
	_build_spatial_grid()
	_geometry_built = true
	load_ms = float(Time.get_ticks_msec() - t0)
	visible_province_count = land_province_count
	is_ready = province_count > 0
	if not is_ready:
		error = "no provinces loaded"
	return is_ready


func image_size() -> Vector2:
	return image_size_v


func background_status() -> String:
	return "background: continuous_ocean"


func end_frame_stats() -> void:
	pass


func get_perf_stats() -> Dictionary:
	return {
		"last_event": "polygon_map",
		"load_ms": load_ms,
		"refresh_ms": refresh_ms,
		"province_count": province_count,
		"land_province_count": land_province_count,
		"water_province_count": water_province_count,
		"mesh_count": mesh_count,
		"visible_province_count": visible_province_count,
		"renderer": renderer_name,
		"geometry_immutable": true,
		"water_fill": false,
		"water_internal_borders": false,
	}


func attach_to(host: Node2D) -> void:
	_host = host
	for n in _mesh_instances:
		if is_instance_valid(n):
			n.queue_free()
	_mesh_instances.clear()
	if is_instance_valid(_ocean_instance):
		_ocean_instance.queue_free()
	_ocean_instance = null
	if is_instance_valid(_border_instance):
		_border_instance.queue_free()
	_border_instance = null
	var holder := host.get_node_or_null("Earth3PolygonRoot")
	if holder == null:
		holder = Node2D.new()
		holder.name = "Earth3PolygonRoot"
		holder.z_index = -15
		host.add_child(holder)
	else:
		for c in holder.get_children():
			c.queue_free()
	_ensure_ownership_material()
	if _ocean_mesh != null:
		_ocean_instance = MeshInstance2D.new()
		_ocean_instance.name = "Earth3Ocean"
		_ocean_instance.mesh = _ocean_mesh
		_ocean_instance.z_index = -2
		_ocean_instance.modulate = OCEAN_COLOR
		holder.add_child(_ocean_instance)
	for i in _meshes.size():
		var mi := MeshInstance2D.new()
		mi.name = "Earth3Chunk_%d" % i
		mi.mesh = _meshes[i]
		mi.material = _fill_material
		mi.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		mi.z_index = 0
		holder.add_child(mi)
		_mesh_instances.append(mi)
	if _border_mesh != null:
		_border_instance = MeshInstance2D.new()
		_border_instance.name = "Earth3Borders"
		_border_instance.mesh = _border_mesh
		_border_instance.z_index = 1
		holder.add_child(_border_instance)
		_apply_border_visual_weight()
	sync_transform_from_map_space(null)


func sync_transform_from_map_space(map_space) -> void:
	if _host == null:
		return
	var holder := _host.get_node_or_null("Earth3PolygonRoot")
	if holder == null or map_space == null:
		return
	var rect: Rect2 = map_space.texture_rect()
	var sx := rect.size.x / maxf(image_size_v.x, 1.0)
	var sy := rect.size.y / maxf(image_size_v.y, 1.0)
	holder.position = rect.position
	holder.scale = Vector2(sx, sy)
	if map_space.get("view_scale") != null:
		set_view_scale(float(map_space.view_scale))


func set_view_scale(scale: float) -> void:
	_view_scale = clampf(scale, 0.4, 12.0)
	_apply_border_visual_weight()
	if _fill_material != null:
		# Slightly stronger ownership tint when zoomed in for faction readability.
		var mix := OWNERSHIP_MIX_DEFAULT + clampf((_view_scale - 1.0) * 0.04, -0.08, 0.12)
		_fill_material.set_shader_parameter("ownership_mix", mix)


func _apply_border_visual_weight() -> void:
	if not is_instance_valid(_border_instance):
		return
	# Zoom-dependent province borders: quieter at full theatre, stronger when close.
	# Coast edges already use darker COAST_COLOR in the mesh; modulate scales overall weight.
	var a := clampf(0.35 + (_view_scale - 0.7) * 0.28, 0.28, 1.0)
	_border_base_modulate = Color(1, 1, 1, a)
	_border_instance.modulate = _border_base_modulate


func refresh_snapshot(snapshot: Dictionary, faction_colors: Dictionary) -> void:
	if not is_ready or not _geometry_built:
		return
	var t0 := Time.get_ticks_msec()
	_owner_colors = faction_colors.duplicate(true)
	var owner_by_id: Dictionary = {}
	for p: Dictionary in snapshot.get("provinces", []):
		owner_by_id[String(p.get("id", ""))] = String(p.get("owner", "neutral"))
	var colors_sig := str(faction_colors)
	var colors_changed := colors_sig != _last_faction_colors_sig
	_last_faction_colors_sig = colors_sig
	var changed := PackedInt32Array()
	for i in province_count:
		var pid := province_by_index[i]
		var water := is_water[i] == 1
		var owner := String(owner_by_id.get(pid, "neutral"))
		if water:
			owner = "water"
		if owners[i] != owner:
			owners[i] = owner
			changed.append(i)
	if changed.is_empty() and not colors_changed:
		# No-op refresh: skip full ownership texture rewrite (proven ~3ms cost).
		refresh_ms = float(Time.get_ticks_msec() - t0)
		return
	if colors_changed or changed.size() * 8 >= province_count:
		_write_all_ownership_colors()
	else:
		_write_ownership_colors_partial(changed)
	refresh_ms = float(Time.get_ticks_msec() - t0)


func refresh_highlights(selected_id: String, legal_targets: Dictionary) -> void:
	_selected_id = selected_id
	_legal_targets = legal_targets.duplicate(true)


func set_hover_province(province_id: String) -> void:
	if province_id.is_empty():
		_hover_index = -1
	else:
		_hover_index = int(index_by_province.get(province_id, -1))


func province_at_image_pos(pos: Vector2) -> String:
	if not is_ready:
		return ""
	if pos.x < 0.0 or pos.y < 0.0 or pos.x > image_size_v.x or pos.y > image_size_v.y:
		return ""
	var cx := int(floor(pos.x / _grid_cell))
	var cy := int(floor(pos.y / _grid_cell))
	var best_land := ""
	var best_land_area := INF
	for oy in range(-1, 2):
		for ox in range(-1, 2):
			var k2 := "%d:%d" % [cx + ox, cy + oy]
			var arr: PackedInt32Array = _grid.get(k2, PackedInt32Array())
			for idx in arr:
				# v1: water is never a normal selectable hit target.
				if is_water[idx] == 1:
					continue
				if not _point_in_province(pos, idx):
					continue
				var area := _approx_area(idx)
				if area < best_land_area:
					best_land_area = area
					best_land = province_by_index[idx]
	return best_land


func province_at_pixel(pixel: Vector2i) -> String:
	return province_at_image_pos(Vector2(pixel))


func get_anchor(province_id: String) -> Vector2:
	var i := int(index_by_province.get(province_id, -1))
	if i < 0:
		return Vector2.ZERO
	return centroids[i]


func anchor_pixel(province_id: String) -> Vector2:
	return get_anchor(province_id)


func draw_overlays(canvas: CanvasItem, map_space) -> void:
	if not is_ready:
		return
	# Visual hierarchy weights: selection > legal targets > hover (land only).
	var w_sel := clampf(2.2 + _view_scale * 0.35, 2.2, 4.0)
	var w_tgt := clampf(1.4 + _view_scale * 0.25, 1.4, 2.8)
	var w_hov := clampf(1.6 + _view_scale * 0.2, 1.6, 3.0)
	if _hover_index >= 0 and is_water[_hover_index] != 1:
		_draw_province_outline(canvas, map_space, _hover_index, Color(1.0, 0.95, 0.35, 0.92), w_hov)
	if not _selected_id.is_empty() and index_by_province.has(_selected_id):
		var si := int(index_by_province[_selected_id])
		if is_water[si] != 1:
			_draw_province_outline(canvas, map_space, si, Color(0.95, 0.98, 1.0, 1.0), w_sel)
	for tid in _legal_targets.keys():
		if index_by_province.has(String(tid)):
			var li := int(index_by_province[String(tid)])
			if is_water[li] == 1:
				continue
			_draw_province_outline(canvas, map_space, li, Color(0.35, 0.95, 0.5, 0.92), w_tgt)


func debug_lines() -> PackedStringArray:
	var lines := PackedStringArray()
	lines.append("PolygonMap map_id=%s" % map_id)
	lines.append(
		"provinces=%d land=%d water=%d meshes=%d"
		% [province_count, land_province_count, water_province_count, mesh_count]
	)
	lines.append(
		"load_ms=%.1f refresh_ms=%.2f hover=%s selected=%s"
		% [load_ms, refresh_ms, str(_hover_index), _selected_id]
	)
	lines.append(
		"ocean_underlay=true terrain_tint=true ownership_mix~%.2f view_scale=%.2f border_a=%.2f"
		% [OWNERSHIP_MIX_DEFAULT, _view_scale, _border_base_modulate.a]
	)
	lines.append(
		"water_fill=false water_water_borders=false exterior_singleton_borders=false suppress_edges=%d"
		% _suppress_border_keys.size()
	)
	return lines


func _ensure_ownership_material() -> void:
	if _ownership_shader == null:
		if ResourceLoader.exists(OWNERSHIP_SHADER_PATH):
			_ownership_shader = load(OWNERSHIP_SHADER_PATH) as Shader
		if _ownership_shader == null:
			_ownership_shader = Shader.new()
			_ownership_shader.code = """
shader_type canvas_item;
uniform sampler2D ownership_colors : filter_nearest, repeat_disable;
uniform float ownership_mix = 0.46;
void fragment() {
	vec4 own = texture(ownership_colors, UV);
	vec3 terrain = vec3(0.42, 0.46, 0.38);
	COLOR = vec4(mix(terrain, own.rgb, ownership_mix), 1.0);
}
"""
	if _fill_material == null:
		_fill_material = ShaderMaterial.new()
		_fill_material.shader = _ownership_shader
		_fill_material.set_shader_parameter("ownership_mix", OWNERSHIP_MIX_DEFAULT)
		_fill_material.set_shader_parameter("terrain_low", Vector3(0.38, 0.43, 0.34))
		_fill_material.set_shader_parameter("terrain_high", Vector3(0.50, 0.48, 0.40))
		_fill_material.set_shader_parameter("terrain_contrast", 0.22)
	if _ownership_tex != null:
		_fill_material.set_shader_parameter("ownership_colors", _ownership_tex)
		owner_texture = _ownership_tex


func _write_all_ownership_colors() -> void:
	if _ownership_image == null:
		return
	for i in province_count:
		var water := is_water[i] == 1
		var color := _color_for_owner(owners[i], water)
		_ownership_image.set_pixel(i, 0, color)
	_upload_ownership_texture()


func _write_ownership_colors_partial(indices: PackedInt32Array) -> void:
	if _ownership_image == null:
		return
	for j in indices.size():
		var i := int(indices[j])
		if i < 0 or i >= province_count:
			continue
		var water := is_water[i] == 1
		_ownership_image.set_pixel(i, 0, _color_for_owner(owners[i], water))
	_upload_ownership_texture()


func _upload_ownership_texture() -> void:
	if _ownership_tex == null:
		_ownership_tex = ImageTexture.create_from_image(_ownership_image)
	else:
		_ownership_tex.update(_ownership_image)
	_ensure_ownership_material()


func _build_ocean_mesh() -> void:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var w := image_size_v.x
	var h := image_size_v.y
	var col := Color.WHITE
	# Full theatre quad beneath land.
	var corners := [
		Vector3(0, 0, 0),
		Vector3(w, 0, 0),
		Vector3(w, h, 0),
		Vector3(0, h, 0),
	]
	var idx := [0, 1, 2, 0, 2, 3]
	for i in idx:
		st.set_color(col)
		st.add_vertex(corners[i])
	_ocean_mesh = st.commit()


func _register_ring_edges(edge_counts: Dictionary, ring: PackedVector2Array, water: bool) -> void:
	# edge_counts[key] = [land_n, water_n]
	var n := ring.size()
	if n < 2:
		return
	for i in n:
		var a: Vector2 = ring[i]
		var b: Vector2 = ring[(i + 1) % n]
		var key := _edge_key(a, b)
		if key.is_empty():
			continue
		var counts: Array = edge_counts.get(key, [0, 0])
		if water:
			counts[1] = int(counts[1]) + 1
		else:
			counts[0] = int(counts[0]) + 1
		edge_counts[key] = counts


func _edge_key(a: Vector2, b: Vector2) -> String:
	var ax := snappedf(a.x, 0.01)
	var ay := snappedf(a.y, 0.01)
	var bx := snappedf(b.x, 0.01)
	var by := snappedf(b.y, 0.01)
	if is_equal_approx(ax, bx) and is_equal_approx(ay, by):
		return ""
	if ax < bx or (is_equal_approx(ax, bx) and ay <= by):
		return "%s:%s|%s:%s" % [ax, ay, bx, by]
	return "%s:%s|%s:%s" % [bx, by, ax, ay]


func _build_border_mesh_from_edges(edge_counts: Dictionary) -> void:
	_border_mesh = null
	if edge_counts.is_empty():
		return
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_LINES)
	var any := false
	for key in edge_counts.keys():
		var counts: Array = edge_counts[key]
		var land_n := int(counts[0]) if counts.size() > 0 else 0
		var water_n := int(counts[1]) if counts.size() > 1 else 0
		# Pure water–water: skip.
		if land_n <= 0:
			continue
		# Dataset-authored suppress list: edges shared with excluded exterior land (not restored).
		if _suppress_border_keys.has(String(key)):
			continue
		# Singleton land edge with no included opposite (exterior / excluded outside crop):
		# do not draw an outlined empty pseudo-province (e.g. src 11836 crop-edge artifact).
		if land_n == 1 and water_n == 0:
			continue
		# Singleton land against water that is also on the exterior-suppress list already handled.
		# Additional guard: singleton land+water where land has no second land peer stays coast only
		# when not suppressed — real coastline. Exterior hole outlines are in suppress set.
		var parts: PackedStringArray = String(key).split("|")
		if parts.size() != 2:
			continue
		var a_parts: PackedStringArray = parts[0].split(":")
		var b_parts: PackedStringArray = parts[1].split(":")
		if a_parts.size() != 2 or b_parts.size() != 2:
			continue
		var a := Vector3(float(a_parts[0]), float(a_parts[1]), 0.0)
		var b := Vector3(float(b_parts[0]), float(b_parts[1]), 0.0)
		var col := COAST_COLOR if water_n > 0 else LAND_BORDER_COLOR
		st.set_color(col)
		st.add_vertex(a)
		st.set_color(col)
		st.add_vertex(b)
		any = true
	if any:
		_border_mesh = st.commit()


func _draw_province_outline(canvas: CanvasItem, map_space, idx: int, color: Color, width: float) -> void:
	var ring: PackedVector2Array = rings[idx] if idx < rings.size() else PackedVector2Array()
	if ring.size() < 2:
		return
	var pts := PackedVector2Array()
	pts.resize(ring.size() + 1)
	for i in ring.size():
		pts[i] = map_space.image_to_screen(ring[i])
	pts[ring.size()] = pts[0]
	canvas.draw_polyline(pts, color, width, true)


func _build_spatial_grid() -> void:
	_grid.clear()
	for i in province_count:
		var mn := bounds_min[i]
		var mx := bounds_max[i]
		var x0 := int(floor(mn.x / _grid_cell))
		var y0 := int(floor(mn.y / _grid_cell))
		var x1 := int(floor(mx.x / _grid_cell))
		var y1 := int(floor(mx.y / _grid_cell))
		for gy in range(y0, y1 + 1):
			for gx in range(x0, x1 + 1):
				var key := "%d:%d" % [gx, gy]
				if not _grid.has(key):
					_grid[key] = PackedInt32Array()
				var arr: PackedInt32Array = _grid[key]
				arr.append(i)
				_grid[key] = arr


func _point_in_province(pos: Vector2, idx: int) -> bool:
	var mn := bounds_min[idx]
	var mx := bounds_max[idx]
	if pos.x < mn.x or pos.y < mn.y or pos.x > mx.x or pos.y > mx.y:
		return false
	var ring: PackedVector2Array = rings[idx] if idx < rings.size() else PackedVector2Array()
	var n := ring.size()
	if n < 3:
		return false
	var inside := false
	var j := n - 1
	for i in n:
		var yi := ring[i].y
		var yj := ring[j].y
		var xi := ring[i].x
		var xj := ring[j].x
		var intersect := ((yi > pos.y) != (yj > pos.y)) and (
			pos.x < (xj - xi) * (pos.y - yi) / ((yj - yi) if absf(yj - yi) > 1e-12 else 1e-12) + xi
		)
		if intersect:
			inside = not inside
		j = i
	return inside


func _approx_area(idx: int) -> float:
	var mn := bounds_min[idx]
	var mx := bounds_max[idx]
	return maxf(1.0, (mx.x - mn.x) * (mx.y - mn.y))


func _color_for_owner(owner: String, water: bool) -> Color:
	# Water is not filled via mesh; lookup entry unused for draws but kept stable.
	# Land: saturated faction colors; shader mixes with procedural terrain (translucent tint).
	if water or owner == "water":
		return OCEAN_COLOR
	if _owner_colors.has(owner):
		var c: Color = _owner_colors[owner]
		return Color(c.r, c.g, c.b, 1.0)
	if owner == "neutral" or owner.is_empty():
		return NEUTRAL_LAND_COLOR
	return NEUTRAL_LAND_COLOR


func _load_json(path: String) -> Dictionary:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var txt := f.get_as_text()
	var data = JSON.parse_string(txt)
	if typeof(data) != TYPE_DICTIONARY:
		return {}
	return data
