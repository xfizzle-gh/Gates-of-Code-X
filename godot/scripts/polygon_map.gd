class_name PolygonMap
extends RefCounted

## Polygon-mesh strategic map for Earth3 production theatre.
## No per-pixel ColorId scanning. Ownership recolor is event-driven.

const SCHEMA := "gates-of-codex.earth3-polygon-dataset"
const CHUNK := 256

var is_ready := false
var error := ""
var map_id := ""
var province_count := 0
var image_size_v := Vector2.ONE
var load_ms := 0.0
var mesh_count := 0
var visible_province_count := 0
var background_texture: Texture2D = null
var owner_texture: Texture2D = null
var border_texture: Texture2D = null
var highlight_texture: Texture2D = null
var renderer_name := "polygon_mesh"
var _host: Node2D = null

var row_by_province: Dictionary = {}  # gates_id -> row dict
var index_by_province: Dictionary = {}  # gates_id -> int
var province_by_index: PackedStringArray = PackedStringArray()
var owners: PackedStringArray = PackedStringArray()
var is_water: PackedByteArray = PackedByteArray()
var centroids: PackedVector2Array = PackedVector2Array()
var bounds_min: PackedVector2Array = PackedVector2Array()
var bounds_max: PackedVector2Array = PackedVector2Array()

var _meshes: Array = []  # ArrayMesh per chunk
var _mesh_province_indices: Array = []  # PackedInt32Array per chunk
var _mesh_instances: Array = []  # set by host when attached
var _grid: Dictionary = {}  # cell_key -> PackedInt32Array of province indices
var _grid_cell := 48.0
var _owner_colors: Dictionary = {}
var _hover_index := -1
var _selected_id := ""
var _legal_targets: Dictionary = {}
var _fill_images: Array = []  # not used; colors applied via MultiMesh/modulate path
var _chunk_colors: Array = []  # PackedColorArray per chunk matching surface order


func open(manifest_path: String, snapshot: Dictionary, faction_colors: Dictionary) -> bool:
	is_ready = false
	error = ""
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
		# res:// fallback
		if ds_path.begins_with("res://") == false and manifest_path.begins_with("res://"):
			ds_path = base_dir.path_join(ds_rel)
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
	province_by_index.resize(province_count)
	owners.resize(province_count)
	is_water.resize(province_count)
	centroids.resize(province_count)
	bounds_min.resize(province_count)
	bounds_max.resize(province_count)

	# Ownership from snapshot
	var owner_by_id: Dictionary = {}
	for p: Dictionary in snapshot.get("provinces", []):
		owner_by_id[String(p.get("id", ""))] = String(p.get("owner", "neutral"))

	var st := SurfaceTool.new()
	var chunk_i := 0
	var in_chunk := 0
	_meshes.clear()
	_mesh_province_indices.clear()
	_chunk_colors.clear()
	var chunk_indices := PackedInt32Array()
	var chunk_colors := PackedColorArray()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)

	for i in province_count:
		var row: Dictionary = provinces[i]
		var pid := String(row.get("id", ""))
		row_by_province[pid] = row
		index_by_province[pid] = i
		province_by_index[i] = pid
		var water := bool(row.get("is_water", false))
		is_water[i] = 1 if water else 0
		var owner := String(owner_by_id.get(pid, "neutral" if water else "neutral"))
		if water:
			owner = "water"
		owners[i] = owner
		var c: Array = row.get("centroid", [0.0, 0.0])
		centroids[i] = Vector2(float(c[0]), float(c[1]))
		var verts: Array = row.get("vertices", [])
		var tris: Array = row.get("triangles", [])
		var min_v := Vector2(INF, INF)
		var max_v := Vector2(-INF, -INF)
		var color := _color_for_owner(owner, water)
		for t in range(0, tris.size(), 3):
			if t + 2 >= tris.size():
				break
			for k in 3:
				var vi := int(tris[t + k]) * 2
				if vi + 1 >= verts.size():
					continue
				var p := Vector2(float(verts[vi]), float(verts[vi + 1]))
				min_v = min_v.min(p)
				max_v = max_v.max(p)
				st.set_color(color)
				st.add_vertex(Vector3(p.x, p.y, 0.0))
		if min_v.x == INF:
			min_v = centroids[i]
			max_v = centroids[i]
		bounds_min[i] = min_v
		bounds_max[i] = max_v
		chunk_indices.append(i)
		chunk_colors.append(color)
		in_chunk += 1
		if in_chunk >= CHUNK or i == province_count - 1:
			var mesh := st.commit()
			_meshes.append(mesh)
			_mesh_province_indices.append(chunk_indices)
			_chunk_colors.append(chunk_colors)
			mesh_count = _meshes.size()
			st = SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			chunk_indices = PackedInt32Array()
			chunk_colors = PackedColorArray()
			in_chunk = 0
			chunk_i += 1

	_build_spatial_grid()
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
		"province_count": province_count,
		"mesh_count": mesh_count,
		"visible_province_count": visible_province_count,
		"renderer": renderer_name,
	}


func attach_to(host: Node2D) -> void:
	_host = host
	# Remove previous
	for n in _mesh_instances:
		if is_instance_valid(n):
			n.queue_free()
	_mesh_instances.clear()
	var holder := host.get_node_or_null("Earth3PolygonRoot")
	if holder == null:
		holder = Node2D.new()
		holder.name = "Earth3PolygonRoot"
		holder.z_index = -15
		host.add_child(holder)
	else:
		for c in holder.get_children():
			c.queue_free()
	for i in _meshes.size():
		var mi := MeshInstance2D.new()
		mi.name = "Earth3Chunk_%d" % i
		mi.mesh = _meshes[i]
		mi.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
		holder.add_child(mi)
		_mesh_instances.append(mi)
	sync_transform_from_map_space(null)


func sync_transform_from_map_space(map_space) -> void:
	if _host == null:
		return
	var holder := _host.get_node_or_null("Earth3PolygonRoot")
	if holder == null:
		return
	if map_space == null:
		return
	var rect: Rect2 = map_space.texture_rect()
	var sx := rect.size.x / maxf(image_size_v.x, 1.0)
	var sy := rect.size.y / maxf(image_size_v.y, 1.0)
	holder.position = rect.position
	holder.scale = Vector2(sx, sy)


func refresh_snapshot(snapshot: Dictionary, faction_colors: Dictionary) -> void:
	if not is_ready:
		return
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
	_rebuild_mesh_colors()


func refresh_highlights(selected_id: String, legal_targets: Dictionary) -> void:
	_selected_id = selected_id
	_legal_targets = legal_targets.duplicate(true)
	# Highlights drawn by host overlay; keep ids only.


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
	var key := _cell_key(pos)
	var candidates: PackedInt32Array = _grid.get(key, PackedInt32Array())
	# Also check neighbor cells for edges.
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
	# Hover fill
	if _hover_index >= 0:
		_draw_province_outline(canvas, map_space, _hover_index, Color(1, 1, 0.2, 0.95), 2.0)
	# Selected
	if not _selected_id.is_empty() and index_by_province.has(_selected_id):
		var si := int(index_by_province[_selected_id])
		_draw_province_outline(canvas, map_space, si, Color(1, 1, 1, 1), 2.5)
	# Legal targets
	for tid in _legal_targets.keys():
		if index_by_province.has(String(tid)):
			var li := int(index_by_province[String(tid)])
			_draw_province_outline(canvas, map_space, li, Color(0.3, 1.0, 0.45, 0.9), 1.5)


func debug_lines() -> PackedStringArray:
	var lines := PackedStringArray()
	lines.append("PolygonMap map_id=%s" % map_id)
	lines.append("provinces=%d visible=%d meshes=%d" % [province_count, visible_province_count, mesh_count])
	lines.append("load_ms=%.1f hover=%s selected=%s" % [load_ms, str(_hover_index), _selected_id])
	return lines


func _rebuild_mesh_colors() -> void:
	# Rebuild mesh vertex colors without changing geometry topology.
	for ci in _meshes.size():
		var indices: PackedInt32Array = _mesh_province_indices[ci]
		var st := SurfaceTool.new()
		st.begin(Mesh.PRIMITIVE_TRIANGLES)
		for idx in indices:
			var row: Dictionary = row_by_province[province_by_index[idx]]
			var verts: Array = row.get("vertices", [])
			var tris: Array = row.get("triangles", [])
			var water := is_water[idx] == 1
			var color := _color_for_owner(owners[idx], water)
			for t in range(0, tris.size(), 3):
				if t + 2 >= tris.size():
					break
				for k in 3:
					var vi := int(tris[t + k]) * 2
					if vi + 1 >= verts.size():
						continue
					var p := Vector2(float(verts[vi]), float(verts[vi + 1]))
					st.set_color(color)
					st.add_vertex(Vector3(p.x, p.y, 0.0))
		var mesh := st.commit()
		_meshes[ci] = mesh
		if ci < _mesh_instances.size() and is_instance_valid(_mesh_instances[ci]):
			(_mesh_instances[ci] as MeshInstance2D).mesh = mesh


func _draw_province_outline(canvas: CanvasItem, map_space, idx: int, color: Color, width: float) -> void:
	var row: Dictionary = row_by_province[province_by_index[idx]]
	var verts: Array = row.get("vertices", [])
	if verts.size() < 6:
		return
	var pts: PackedVector2Array = PackedVector2Array()
	for i in range(0, verts.size(), 2):
		var img := Vector2(float(verts[i]), float(verts[i + 1]))
		pts.append(map_space.image_to_screen(img))
	if pts.size() >= 2:
		pts.append(pts[0])
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


func _cell_key(pos: Vector2) -> String:
	return "%d:%d" % [int(floor(pos.x / _grid_cell)), int(floor(pos.y / _grid_cell))]


func _point_in_province(pos: Vector2, idx: int) -> bool:
	var mn := bounds_min[idx]
	var mx := bounds_max[idx]
	if pos.x < mn.x or pos.y < mn.y or pos.x > mx.x or pos.y > mx.y:
		return false
	var row: Dictionary = row_by_province[province_by_index[idx]]
	var verts: Array = row.get("vertices", [])
	var n := int(verts.size() / 2)
	if n < 3:
		return false
	var inside := false
	var j := n - 1
	for i in n:
		var xi := float(verts[i * 2])
		var yi := float(verts[i * 2 + 1])
		var xj := float(verts[j * 2])
		var yj := float(verts[j * 2 + 1])
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
