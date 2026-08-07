class_name PolygonMap
extends RefCounted

## Polygon-mesh strategic map for Earth3 production theatre.
## Geometry is immutable after open(); ownership recolor updates a 1D lookup texture only.

const SCHEMA := "gates-of-codex.earth3-polygon-dataset"
const CHUNK := 256
const OWNERSHIP_SHADER_PATH := "res://shaders/province_ownership.gdshader"

var is_ready := false
var error := ""
var map_id := ""
var province_count := 0
var image_size_v := Vector2.ONE
var load_ms := 0.0
var refresh_ms := 0.0
var mesh_count := 0
var visible_province_count := 0
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
var rings: Array = []  # PackedVector2Array per province

var _meshes: Array = []
var _mesh_instances: Array = []
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
	province_by_index.resize(province_count)
	owners.resize(province_count)
	is_water.resize(province_count)
	centroids.resize(province_count)
	bounds_min.resize(province_count)
	bounds_max.resize(province_count)
	rings.resize(province_count)

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

	for i in province_count:
		var row: Dictionary = provinces[i]
		var pid := String(row.get("id", ""))
		row_by_province[pid] = row
		index_by_province[pid] = i
		province_by_index[i] = pid
		var water := bool(row.get("is_water", false))
		is_water[i] = 1 if water else 0
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
		if min_v.x == INF:
			min_v = centroids[i]
			max_v = centroids[i]
		bounds_min[i] = min_v
		bounds_max[i] = max_v
		in_chunk += 1
		if in_chunk >= CHUNK or i == province_count - 1:
			var mesh := st.commit()
			_meshes.append(mesh)
			mesh_count = _meshes.size()
			st = SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			in_chunk = 0

	_build_border_mesh(data.get("border_segments", []))
	_write_all_ownership_colors()
	_build_spatial_grid()
	_geometry_built = true
	load_ms = float(Time.get_ticks_msec() - t0)
	visible_province_count = province_count
	is_ready = province_count > 0
	if not is_ready:
		error = "no provinces loaded"
	return is_ready


func image_size() -> Vector2:
	return image_size_v


func background_status() -> String:
	return "background: polygon_neutral_underlay"


func end_frame_stats() -> void:
	pass


func get_perf_stats() -> Dictionary:
	return {
		"last_event": "polygon_map",
		"load_ms": load_ms,
		"refresh_ms": refresh_ms,
		"province_count": province_count,
		"mesh_count": mesh_count,
		"visible_province_count": visible_province_count,
		"renderer": renderer_name,
		"geometry_immutable": true,
	}


func attach_to(host: Node2D) -> void:
	_host = host
	for n in _mesh_instances:
		if is_instance_valid(n):
			n.queue_free()
	_mesh_instances.clear()
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
	for i in _meshes.size():
		var mi := MeshInstance2D.new()
		mi.name = "Earth3Chunk_%d" % i
		mi.mesh = _meshes[i]
		mi.material = _fill_material
		mi.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		holder.add_child(mi)
		_mesh_instances.append(mi)
	if _border_mesh != null:
		_border_instance = MeshInstance2D.new()
		_border_instance.name = "Earth3Borders"
		_border_instance.mesh = _border_mesh
		_border_instance.z_index = 1
		_border_instance.modulate = Color(0.08, 0.1, 0.12, 0.85)
		holder.add_child(_border_instance)
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


func refresh_snapshot(snapshot: Dictionary, faction_colors: Dictionary) -> void:
	if not is_ready or not _geometry_built:
		return
	var t0 := Time.get_ticks_msec()
	_owner_colors = faction_colors.duplicate(true)
	var owner_by_id: Dictionary = {}
	for p: Dictionary in snapshot.get("provinces", []):
		owner_by_id[String(p.get("id", ""))] = String(p.get("owner", "neutral"))
	for i in province_count:
		var pid := province_by_index[i]
		var water := is_water[i] == 1
		var owner := String(owner_by_id.get(pid, "neutral"))
		if water:
			owner = "water"
		owners[i] = owner
	_write_all_ownership_colors()
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
	var best := ""
	var best_area := INF
	for oy in range(-1, 2):
		for ox in range(-1, 2):
			var k2 := "%d:%d" % [cx + ox, cy + oy]
			var arr: PackedInt32Array = _grid.get(k2, PackedInt32Array())
			for idx in arr:
				if not _point_in_province(pos, idx):
					continue
				var area := _approx_area(idx)
				if area < best_area:
					best_area = area
					best = province_by_index[idx]
	return best


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
	if _hover_index >= 0:
		_draw_province_outline(canvas, map_space, _hover_index, Color(1, 1, 0.2, 0.95), 2.0)
	if not _selected_id.is_empty() and index_by_province.has(_selected_id):
		var si := int(index_by_province[_selected_id])
		_draw_province_outline(canvas, map_space, si, Color(1, 1, 1, 1), 2.5)
	for tid in _legal_targets.keys():
		if index_by_province.has(String(tid)):
			var li := int(index_by_province[String(tid)])
			_draw_province_outline(canvas, map_space, li, Color(0.3, 1.0, 0.45, 0.9), 1.5)


func debug_lines() -> PackedStringArray:
	var lines := PackedStringArray()
	lines.append("PolygonMap map_id=%s" % map_id)
	lines.append("provinces=%d visible=%d meshes=%d" % [province_count, visible_province_count, mesh_count])
	lines.append("load_ms=%.1f refresh_ms=%.2f hover=%s selected=%s" % [load_ms, refresh_ms, str(_hover_index), _selected_id])
	lines.append("geometry_immutable=true ownership_tex_w=%d" % _tex_width)
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
void fragment() {
	COLOR = texture(ownership_colors, UV);
}
"""
	if _fill_material == null:
		_fill_material = ShaderMaterial.new()
		_fill_material.shader = _ownership_shader
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
	if _ownership_tex == null:
		_ownership_tex = ImageTexture.create_from_image(_ownership_image)
	else:
		_ownership_tex.update(_ownership_image)
	_ensure_ownership_material()


func _build_border_mesh(segments: Array) -> void:
	_border_mesh = null
	if segments.is_empty():
		return
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_LINES)
	var border_col := Color(0.05, 0.06, 0.08, 1.0)
	for i in range(0, segments.size(), 4):
		if i + 3 >= segments.size():
			break
		var a := Vector3(float(segments[i]), float(segments[i + 1]), 0.0)
		var b := Vector3(float(segments[i + 2]), float(segments[i + 3]), 0.0)
		st.set_color(border_col)
		st.add_vertex(a)
		st.set_color(border_col)
		st.add_vertex(b)
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
	if water or owner == "water":
		return Color(0.18, 0.32, 0.48, 1.0)
	if _owner_colors.has(owner):
		var c: Color = _owner_colors[owner]
		return Color(c.r, c.g, c.b, 1.0)
	return Color(0.45, 0.48, 0.42, 1.0)


func _load_json(path: String) -> Dictionary:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var txt := f.get_as_text()
	var data = JSON.parse_string(txt)
	if typeof(data) != TYPE_DICTIONARY:
		return {}
	return data
