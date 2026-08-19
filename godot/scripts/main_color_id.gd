extends "res://scripts/main_writeback.gd"

const ColorIdMapScript = preload("res://scripts/color_id_map.gd")
const PolygonMapScript = preload("res://scripts/polygon_map.gd")
const MapSpaceScript = preload("res://scripts/presentation/map_space.gd")
const MapMarkersScript = preload("res://scripts/presentation/map_markers.gd")
const MapDebugScript = preload("res://scripts/presentation/map_debug.gd")
const MapTextureLayerScript = preload("res://scripts/presentation/map_texture_layer.gd")
const BattleLocationScript = preload("res://scripts/presentation/battle_location.gd")
const OperationalGraphViewScript = preload("res://scripts/presentation/operational_graph_view.gd")
const DEFAULT_MAP_MANIFEST := "res://assets/maps/europe/interim_goe/map_manifest.json"
const EM_FROM_GOE_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const EARTH3_EM_MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const DEFAULT_PRESENTATION_FIXTURE := "res://fixtures/presentation/empty_map.json"
## Temporary feature flag: prefer Earth3 polygon theatre when assets exist.
const USE_EARTH3_POLYGON_MAP := true
const FALLBACK_GOE_ON_EARTH3_FAIL := true
const HOME_MAP_MARGIN := Vector2(18, 18)
const HOME_FIT_FILL := 1.06
# Reserve space so title/diagnostic rows never cover the theatre.
const HEADER_SAFE_TOP := 64.0
const FOOTER_SAFE_BOTTOM := 28.0
const OVERLAY_EDGE_PAD := 18.0

var color_id_map = ColorIdMapScript.new()
var polygon_map = PolygonMapScript.new()
var map_backend_is_polygon := false
var map_space = MapSpaceScript.new()
var map_debug = MapDebugScript.new()
var operational_graph = OperationalGraphViewScript.new()
var map_manifest_source_path := DEFAULT_MAP_MANIFEST
var presentation_fixture: Dictionary = {}
var presentation_fixture_path := DEFAULT_PRESENTATION_FIXTURE
var hovered_province_id := ""
var show_coalition_fronts := false
var show_crossing_overlay := false
var _screenshot_path := ""
var _screenshot_frames_left := -1
var _overlay_cache_key := ""
var _cached_label_candidates: Array = []
var _cached_reserved_rects: Array = []
var _cached_label_bounds: Array = []
var _snap_by_id: Dictionary = {}
var _snap_by_id_src: Variant = null
## Province IDs with supply_hub / command_post / air_base in the current snapshot.
## Must stay in the overlay active set even when unoccupied (PR C regression fix).
var _infra_province_ids: Dictionary = {}
# Separate CanvasItem layers: filtering is per-node in Godot 4.
var _bg_layer: Node2D
var _identity_layer: Node2D
var _layers_dirty := true
var _last_layer_rect := Rect2()
var _last_layer_viewport := Vector2.ZERO
var _was_camera_moving := false
var overlay_rebuild_count := 0
var overlay_provinces_scanned := 0
var overlay_last_scan_all := false


func _ready() -> void:
	var args := OS.get_cmdline_user_args()
	var filtered: PackedStringArray = PackedStringArray()
	for arg in args:
		var text := String(arg)
		if text.begins_with("--screenshot="):
			_screenshot_path = text.substr(String("--screenshot=").length()).strip_edges()
			continue
		if text.begins_with("--fixture="):
			presentation_fixture_path = text.substr(String("--fixture=").length()).strip_edges()
			continue
		if text.begins_with("--snapshot="):
			# Handled by main.gd; keep parsing other flags here.
			continue
		if text == "--debug-map":
			map_debug.enabled = true
			continue
		if text == "--crossings" or text == "--screenshot-crossings":
			show_crossing_overlay = true
			continue
		filtered.append(text)
	if filtered.size() > 1:
		map_manifest_source_path = String(filtered[1])
	super._ready()
	# Never silently replace a missing/invalid campaign_snapshot with the profiling fixture.
	# Fixture snapshot is only used when explicitly passed via --snapshot= (main.gd) or tooling.
	if filtered.size() <= 1:
		map_manifest_source_path = _resolve_map_manifest_path()
	_ensure_presentation_layers()
	_load_presentation_fixture(presentation_fixture_path)
	_open_color_id_map()
	# S10 presentation advances on the render clock only; campaign authority remains in snapshots.
	set_process(true)
	if not _screenshot_path.is_empty():
		# Legacy in-scene screenshot path: wait for real rendered frames.
		_fit_complete_theatre()
		_layers_dirty = true
		_sync_presentation_layers()
		queue_redraw()
		if not RenderingServer.frame_post_draw.is_connected(_on_screenshot_frame_post_draw):
			RenderingServer.frame_post_draw.connect(_on_screenshot_frame_post_draw)
		_screenshot_frames_left = 12


func _process(delta: float) -> void:
	var moving := has_method("camera_is_moving") and camera_is_moving()
	if _was_camera_moving and not moving:
		_invalidate_overlay_cache()
		queue_redraw()
	_was_camera_moving = moving
	if operational_presenter != null:
		var presentation_visible: bool = operational_presenter.is_active() \
			or not operational_presenter.transient_outcome().is_empty()
		operational_presenter.advance(delta)
		if presentation_visible or operational_presenter.is_active() \
		or not operational_presenter.transient_outcome().is_empty():
			queue_redraw()
	if has_method("is_command_busy") and is_command_busy():
		queue_redraw()
	if map_debug.enabled:
		map_debug.tick_fps(delta)
	if _screenshot_frames_left >= 0:
		_layers_dirty = true
		_sync_presentation_layers()
		queue_redraw()


func _on_screenshot_frame_post_draw() -> void:
	if _screenshot_path.is_empty() or _screenshot_frames_left < 0:
		return
	_screenshot_frames_left -= 1
	if _screenshot_frames_left > 0:
		return
	_screenshot_frames_left = -1
	if RenderingServer.frame_post_draw.is_connected(_on_screenshot_frame_post_draw):
		RenderingServer.frame_post_draw.disconnect(_on_screenshot_frame_post_draw)
	_capture_screenshot_and_quit()


func _capture_screenshot_and_quit() -> void:
	if _screenshot_path.is_empty():
		return
	var image := get_viewport().get_texture().get_image()
	if image == null or image.is_empty():
		push_error("screenshot failed: empty viewport image path=%s" % _screenshot_path)
		get_tree().quit(3)
		return
	var base := _screenshot_path.get_base_dir()
	if not base.is_empty() and not DirAccess.dir_exists_absolute(base):
		DirAccess.make_dir_recursive_absolute(base)
	var err := image.save_png(_screenshot_path)
	if err != OK:
		push_error("screenshot save_png failed err=%s path=%s" % [err, _screenshot_path])
		get_tree().quit(4)
		return
	status_message = "Saved screenshot err=%s path=%s ready=%s backend=%s provinces=%s" % [
		err,
		_screenshot_path,
		str(_active_map() != null and _active_map().is_ready),
		("polygon" if map_backend_is_polygon else "color_id"),
		str(_active_map().province_count) if _active_map() != null and "province_count" in _active_map() else "?",
	]
	print(status_message)
	get_tree().quit(0)


func _resolve_map_manifest_path() -> String:
	var contract: Dictionary = snapshot.get("strategic_map", {})
	var exported := String(contract.get("manifest_path", "")).strip_edges()
	if not exported.is_empty() and FileAccess.file_exists(exported):
		return exported
	var map_id := String(contract.get("map_id", ""))
	var campaign: Dictionary = snapshot.get("campaign", {})
	var meta: Dictionary = campaign.get("map_metadata", {})
	var configured := String(meta.get("strategic_map_id", ""))
	# Prefer approved Earth3 polygon theatre when enabled and assets exist.
	if USE_EARTH3_POLYGON_MAP and FileAccess.file_exists(EARTH3_EM_MANIFEST):
		if map_id.is_empty() or map_id == "earth3_europe_mediterranean" or configured == "earth3_europe_mediterranean" or map_id == "europe_mediterranean_from_goe" or configured.is_empty():
			return EARTH3_EM_MANIFEST
	if map_id == "earth3_europe_mediterranean" and FileAccess.file_exists(EARTH3_EM_MANIFEST):
		return EARTH3_EM_MANIFEST
	if map_id == "europe_mediterranean_from_goe" and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
		return EM_FROM_GOE_MANIFEST
	if configured == "europe_mediterranean_from_goe" and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
		return EM_FROM_GOE_MANIFEST
	if FileAccess.file_exists(DEFAULT_MAP_MANIFEST):
		return DEFAULT_MAP_MANIFEST
	return DEFAULT_MAP_MANIFEST


func _active_map():
	if map_backend_is_polygon and polygon_map != null and polygon_map.is_ready:
		return polygon_map
	return color_id_map


func _manifest_is_polygon(path: String) -> bool:
	if not FileAccess.file_exists(path):
		return false
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return false
	var txt := f.get_as_text()
	return txt.find("polygon_mesh") >= 0


func _load_presentation_fixture(path: String) -> void:
	presentation_fixture = {}
	if path.is_empty() or not FileAccess.file_exists(path):
		return
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return
	var parsed: Variant = JSON.parse_string(file.get_as_text())
	if not parsed is Dictionary:
		return
	presentation_fixture = parsed
	# Presentation fixtures are Godot-local view models only.
	if String(presentation_fixture.get("schema", "")) != "gates-of-codex.presentation-fixture":
		presentation_fixture = {}
		return
	# Optional test/screenshot overlay: inject a pending_battle without Python changes.
	if presentation_fixture.has("pending_battle") and presentation_fixture.get("pending_battle") is Dictionary:
		snapshot["pending_battle"] = (presentation_fixture.get("pending_battle") as Dictionary).duplicate(true)
	if bool(presentation_fixture.get("presentation_writeback_enabled", false)):
		var fixture_control: Dictionary = snapshot.get("control", {}).duplicate(true)
		fixture_control["enabled"] = true
		snapshot["control"] = fixture_control
	_ensure_operational_presenter()
	var graph_index := _operational_graph_index()
	if presentation_fixture.get("presentation_graph_index", null) is Dictionary:
		graph_index = (presentation_fixture.get("presentation_graph_index") as Dictionary).duplicate(true)
	operational_presenter.begin_session(snapshot, graph_index)
	var payload: Variant = presentation_fixture.get("presentation_backend_payload", null)
	if payload is Dictionary:
		operational_presenter.duration_seconds = maxf(
			float(presentation_fixture.get("presentation_duration_seconds", operational_presenter.DEFAULT_DURATION_SECONDS)),
			0.001
		)
		operational_presenter.begin_transition(snapshot, snapshot, payload as Dictionary, graph_index)
		var fixture_progress := clampf(float(presentation_fixture.get("presentation_progress", 0.0)), 0.0, 1.0)
		if fixture_progress > 0.0:
			operational_presenter.advance(operational_presenter.duration_seconds * fixture_progress)
	# Optional selection hints for Earth3 operational screenshots.
	if presentation_fixture.has("selected_province_id"):
		var sp := String(presentation_fixture.get("selected_province_id", ""))
		if not sp.is_empty() and provinces_by_id.has(sp):
			selected_province_id = sp
			_rebuild_legal_targets()


func _invalidate_overlay_cache() -> void:
	_overlay_cache_key = ""
	_cached_label_candidates.clear()
	_cached_reserved_rects.clear()
	_cached_label_bounds.clear()


func _ensure_presentation_layers() -> void:
	if _bg_layer != null and _identity_layer != null:
		return
	_bg_layer = MapTextureLayerScript.new()
	_bg_layer.name = "MapBackgroundLayer"
	_bg_layer.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	_bg_layer.z_index = -20
	add_child(_bg_layer)

	_identity_layer = MapTextureLayerScript.new()
	_identity_layer.name = "MapIdentityLayer"
	_identity_layer.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_identity_layer.z_index = -10
	add_child(_identity_layer)


func _sync_presentation_layers() -> void:
	_ensure_presentation_layers()
	var am = _active_map()
	if am == null or not am.is_ready:
		if _bg_layer != null:
			_bg_layer.set_draw_items([])
			_bg_layer.refresh()
		if _identity_layer != null:
			_identity_layer.set_draw_items([])
			_identity_layer.refresh()
		_layers_dirty = false
		return
	_sync_map_space()
	if map_backend_is_polygon and polygon_map != null:
		polygon_map.sync_transform_from_map_space(map_space)
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	var texture_rect := map_space.texture_rect()
	var viewport_key := Vector2(map_width, viewport.y)
	# Polygon land/ocean/borders live on transformed MeshInstance2D nodes.
	# Camera motion must not rebuild the full-panel clear layer every redraw.
	if map_backend_is_polygon:
		if not _layers_dirty and viewport_key == _last_layer_viewport:
			return
	elif not _layers_dirty and texture_rect == _last_layer_rect:
		return
	_last_layer_rect = texture_rect
	_last_layer_viewport = viewport_key
	_layers_dirty = false
	# Linear-filtered visual background underlay (never authoritative).
	var bg_items: Array = []
	if am.background_texture != null:
		bg_items.append({"texture": am.background_texture, "rect": texture_rect})
	var clear_col := Color(0.09, 0.15, 0.24, 1.0) if map_backend_is_polygon else Color(0.025, 0.035, 0.047, 1.0)
	_bg_layer.set_clear(Rect2(0, 0, map_width, viewport.y), clear_col)
	_bg_layer.set_draw_items(bg_items)
	_bg_layer.refresh()
	if map_backend_is_polygon:
		if _identity_layer != null:
			_identity_layer.visible = false
			_identity_layer.set_draw_items([])
			_identity_layer.refresh()
		return
	# Nearest-filtered owner / border / highlight identity presentation layers.
	if _identity_layer != null:
		_identity_layer.visible = true
	var id_items: Array = []
	if am.owner_texture != null:
		id_items.append({"texture": am.owner_texture, "rect": texture_rect})
	if am.border_texture != null:
		id_items.append({"texture": am.border_texture, "rect": texture_rect})
	if am.highlight_texture != null:
		id_items.append({"texture": am.highlight_texture, "rect": texture_rect})
	_identity_layer.set_clear(Rect2(), Color(0, 0, 0, 0))
	_identity_layer.set_draw_items(id_items)
	_identity_layer.refresh()


func _load_snapshot(path: String) -> void:
	super._load_snapshot(path)
	_invalidate_overlay_cache()
	_layers_dirty = true
	var am = _active_map()
	if am != null and am.is_ready:
		am.refresh_snapshot(snapshot, FACTION_COLORS)
		am.refresh_highlights(selected_province_id, legal_targets)
		map_debug.note_invalidation("snapshot_refresh")
		_sync_presentation_layers()


func _rebuild_legal_targets() -> void:
	super._rebuild_legal_targets()
	_invalidate_overlay_cache()
	_layers_dirty = true
	var am = _active_map()
	if am != null and am.is_ready:
		am.refresh_highlights(selected_province_id, legal_targets)
		map_debug.note_invalidation("highlight_refresh")
		_sync_presentation_layers()


func _open_color_id_map() -> void:
	var previous_ready: bool = _active_map() != null and bool(_active_map().is_ready)
	_invalidate_overlay_cache()
	_ensure_presentation_layers()
	_open_operational_graph()
	map_backend_is_polygon = false
	var opened := false
	if _manifest_is_polygon(map_manifest_source_path):
		if polygon_map.open(map_manifest_source_path, snapshot, FACTION_COLORS):
			map_backend_is_polygon = true
			polygon_map.attach_to(self)
			polygon_map.refresh_highlights(selected_province_id, legal_targets)
			# Hide color-id texture layers; polygon meshes draw underneath overlays.
			if _bg_layer != null:
				_bg_layer.visible = true
				_bg_layer.set_draw_items([])
				var viewport := get_viewport_rect().size
				# Continuous muted ocean behind land polygons (not per-water fills).
				_bg_layer.set_clear(Rect2(0, 0, viewport.x - PANEL_WIDTH, viewport.y), Color(0.09, 0.15, 0.24, 1.0))
				_bg_layer.refresh()
			if _identity_layer != null:
				_identity_layer.visible = false
			status_message = "Earth3 polygon renderer active (%d provinces, load %.0f ms)." % [
				polygon_map.province_count,
				polygon_map.load_ms,
			]
			opened = true
		elif FALLBACK_GOE_ON_EARTH3_FAIL and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
			map_manifest_source_path = EM_FROM_GOE_MANIFEST
			status_message = "Earth3 open failed (%s); falling back to GoE." % polygon_map.error
	if not opened:
		if color_id_map.open(map_manifest_source_path, snapshot, FACTION_COLORS):
			color_id_map.refresh_highlights(selected_province_id, legal_targets)
			status_message = "Color-ID province renderer active (%s)." % map_manifest_source_path.get_file()
			if _identity_layer != null:
				_identity_layer.visible = true
			opened = true
		else:
			if previous_ready:
				status_message = "%s Kept previous map." % color_id_map.error
			else:
				status_message = "%s Marker fallback remains non-authoritative." % color_id_map.error
				if _bg_layer != null:
					_bg_layer.visible = false
				if _identity_layer != null:
					_identity_layer.visible = false
	if opened:
		fitted_once = false
		_layers_dirty = true
		_fit_complete_theatre()
		map_debug.note_invalidation("map_open")
		_sync_presentation_layers()
	queue_redraw()


func _open_operational_graph() -> void:
	var graph_path := operational_graph.resolve_path(map_manifest_source_path, snapshot)
	if graph_path.is_empty():
		operational_graph.clear()
		return
	if not operational_graph.open(graph_path):
		# Presentation-only; unresolved graph uses next legitimate location fallback.
		operational_graph.clear()


func _loaded_province_count() -> int:
	# HUD must report the opened map backend count (polygon dataset / color-id map),
	# never a stale snapshot/fixture province list length.
	if map_backend_is_polygon and polygon_map != null and polygon_map.is_ready:
		var pn := int(polygon_map.province_count)
		if pn > 0:
			return pn
	var am = _active_map()
	if am != null and am.is_ready:
		if "province_count" in am and int(am.province_count) > 0:
			return int(am.province_count)
		if "row_by_province" in am and am.row_by_province is Dictionary:
			var rn := int(am.row_by_province.size())
			if rn > 0:
				return rn
	if color_id_map != null and color_id_map.is_ready and color_id_map.row_by_province is Dictionary:
		return int(color_id_map.row_by_province.size())
	return 0


func _ensure_snapshot_overlay_indexes() -> void:
	# Rebuild when snapshot identity changes (writeback replaces the dict).
	if _snap_by_id_src == snapshot:
		return
	_snap_by_id_src = snapshot
	_snap_by_id.clear()
	_infra_province_ids.clear()
	for prow: Dictionary in snapshot.get("provinces", []):
		var pid := String(prow.get("id", ""))
		if pid.is_empty():
			continue
		_snap_by_id[pid] = prow
		var infra: Dictionary = prow.get("infrastructure", {})
		if (
			int(infra.get("supply_hub", 0)) > 0
			or int(infra.get("command_post", 0)) > 0
			or int(infra.get("air_base", 0)) > 0
		):
			_infra_province_ids[pid] = true


func _build_overlay_active_ids() -> Dictionary:
	var active_ids: Dictionary = {}
	for pid_occ: Variant in battalions_by_province.keys():
		active_ids[String(pid_occ)] = true
	if not selected_province_id.is_empty():
		active_ids[selected_province_id] = true
	if not hovered_province_id.is_empty():
		active_ids[hovered_province_id] = true
	for tid: Variant in legal_targets.keys():
		active_ids[String(tid)] = true
	# Unoccupied infrastructure must remain visible at every zoom (PR B behavior).
	for pid_infra: Variant in _infra_province_ids.keys():
		active_ids[String(pid_infra)] = true
	return active_ids


func get_overlay_infrastructure_province_ids() -> PackedStringArray:
	_ensure_snapshot_overlay_indexes()
	var out := PackedStringArray()
	for pid: Variant in _infra_province_ids.keys():
		out.append(String(pid))
	return out


func get_overlay_active_province_ids_for_test() -> PackedStringArray:
	_ensure_snapshot_overlay_indexes()
	var active := _build_overlay_active_ids()
	var out := PackedStringArray()
	for pid: Variant in active.keys():
		out.append(String(pid))
	return out


func ensure_unoccupied_infrastructure_markers_for_test() -> Dictionary:
	## Inject three unoccupied infrastructure provinces into the live snapshot for
	## profiler / regression checks. Returns {supply_hub, command_post, air_base} IDs.
	_ensure_snapshot_overlay_indexes()
	var occupied: Dictionary = {}
	for pid_occ: Variant in battalions_by_province.keys():
		occupied[String(pid_occ)] = true
	var picks := {"supply_hub": "", "command_post": "", "air_base": ""}
	var kinds := ["supply_hub", "command_post", "air_base"]
	# Prefer central land provinces so zoomed screenshots show markers clearly.
	var candidates: Array = []
	var am = _active_map()
	var center := Vector2(2150, 1700)
	if am != null and am.has_method("image_size"):
		var isz: Vector2 = am.image_size()
		center = isz * 0.5
	for prow: Dictionary in snapshot.get("provinces", []):
		var pid := String(prow.get("id", ""))
		if pid.is_empty() or occupied.has(pid):
			continue
		if am != null and not am.row_by_province.has(pid):
			continue
		if am != null and "is_water" in am and am.index_by_province.has(pid):
			var idx := int(am.index_by_province[pid])
			if idx >= 0 and idx < am.is_water.size() and int(am.is_water[idx]) == 1:
				continue
		var anchor := Vector2(center)
		if am != null and am.has_method("anchor_pixel"):
			anchor = am.anchor_pixel(pid)
		candidates.append({"row": prow, "pid": pid, "d": anchor.distance_to(center)})
	candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return float(a["d"]) < float(b["d"])
	)
	for ki in kinds.size():
		if ki >= candidates.size():
			break
		var kind := String(kinds[ki])
		var prow2: Dictionary = candidates[ki]["row"]
		var pid2 := String(candidates[ki]["pid"])
		var infra: Dictionary = prow2.get("infrastructure", {})
		if typeof(infra) != TYPE_DICTIONARY:
			infra = {}
		else:
			infra = infra.duplicate(true)
		infra["supply_hub"] = 1 if kind == "supply_hub" else 0
		infra["command_post"] = 1 if kind == "command_post" else 0
		infra["air_base"] = 1 if kind == "air_base" else 0
		prow2["infrastructure"] = infra
		picks[kind] = pid2
	# Force index rebuild after mutation.
	_snap_by_id_src = null
	_ensure_snapshot_overlay_indexes()
	return picks


func _sync_map_space() -> void:
	var am = _active_map()
	if am == null or not am.is_ready:
		return
	map_space.configure(am.image_size(), _map_content_rect(), view_scale, view_offset)


func _draw() -> void:
	var am = _active_map()
	if am == null or not am.is_ready:
		if _bg_layer != null:
			_bg_layer.visible = false
		if _identity_layer != null:
			_identity_layer.visible = false
		super._draw()
		return
	if _bg_layer != null:
		_bg_layer.visible = true
	if _identity_layer != null:
		_identity_layer.visible = not map_backend_is_polygon
	# Capture rebuild counters BEFORE any end-of-frame clear so F3 can report them.
	if map_debug.enabled and am.has_method("get_perf_stats"):
		map_debug.capture_perf(am.get_perf_stats())
	_sync_presentation_layers()
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	# Texture layers are separate CanvasItems. This node draws dynamic overlays + UI only.
	if map_backend_is_polygon and polygon_map != null:
		polygon_map.draw_overlays(self, map_space)
	if show_coalition_fronts:
		_draw_coalition_fronts()
	if show_crossing_overlay:
		_draw_crossing_overlay()
	_draw_color_id_pending_battle()
	_draw_presentation_fixture_markers()
	_draw_color_id_overlays()
	_draw_operational_presentation()
	if map_debug.enabled:
		map_debug.counter_bounds = _cached_reserved_rects.duplicate()
		map_debug.label_bounds = _cached_label_bounds.duplicate()
		map_debug.draw(
			self,
			map_space,
			am,
			selected_province_id,
			hovered_province_id,
			presentation_fixture,
			_overlay_clamp_rect()
		)
		# Extra polygon debug lines.
		if map_backend_is_polygon and polygon_map != null:
			var y := 92.0
			for line in polygon_map.debug_lines():
				draw_string(ThemeDB.fallback_font, Vector2(20, y), String(line), HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color(0.9, 0.95, 0.7, 1))
				y += 16.0
	if am.has_method("end_frame_stats"):
		am.end_frame_stats()

	var campaign: Dictionary = snapshot.get("campaign", {})
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	# Opaque header band so map never shows through title/status.
	draw_rect(Rect2(0, 0, map_width, HEADER_SAFE_TOP), Color(0.025, 0.035, 0.047, 0.96))
	var title := "%s  |  Turn %s  |  %s" % [
		campaign.get("name", "Gates of CodeX"),
		campaign.get("turn_number", 1),
		String(campaign.get("current_faction", "")).to_upper(),
	]
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, 28),
		title,
		HORIZONTAL_ALIGNMENT_LEFT,
		-1,
		20,
		Color.WHITE
	)
	var front_mode := "fronts:on" if show_coalition_fronts else "fronts:off"
	var cross_mode := "crossings:on" if show_crossing_overlay else "crossings:off"
	var diag := "Map: %s  |  Provinces: %s  |  %s  |  %s  |  %s" % [
		String(map_contract.get("map_id", campaign.get("map_id", ""))),
		_loaded_province_count(),
		"polygon" if map_backend_is_polygon else color_id_map.background_status(),
		front_mode,
		cross_mode,
	]
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, 50),
		diag,
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 48,
		13,
		Color("9fd7ff")
	)
	draw_rect(
		Rect2(0, viewport.y - FOOTER_SAFE_BOTTOM, map_width, FOOTER_SAFE_BOTTOM),
		Color(0.025, 0.035, 0.047, 0.92)
	)
	var hint := "Home full  |  F front  |  F3 debug  |  G fronts  |  C crossings  |  click  |  wheel"
	if not status_message.is_empty():
		hint = status_message
	draw_string(
		ThemeDB.fallback_font,
		Vector2(24, viewport.y - 10),
		hint,
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 48,
		13,
		Color(0.78, 0.82, 0.86, 0.95)
	)
	if not (has_method("camera_is_moving") and camera_is_moving()):
		_draw_management_panel()
	_draw_command_busy_overlay()


func _draw_operational_presentation() -> void:
	if operational_presenter == null:
		return
	var active: bool = operational_presenter.is_active()
	var outcome: Dictionary = operational_presenter.transient_outcome()
	if not active and outcome.is_empty():
		return
	var contact: Dictionary = operational_presenter.contact_model()
	var participants: Array = contact.get("participant_formation_ids", [])
	if active:
		# Keep all parallel tracks visible, while subdued background counters make the
		# formations involved in the contact the only emphasized group.
		draw_rect(_map_content_rect(), Color(0.015, 0.02, 0.03, 0.34))
		var tracks: Dictionary = operational_presenter.track_model()
		for formation_id: String in operational_presenter.active_formation_ids():
			var track: Dictionary = tracks.get(formation_id, {})
			var route := PackedVector2Array()
			for point: Vector2 in track.get("points", []):
				route.append(_image_to_screen(point))
			if route.size() >= 2:
				MapMarkersScript.draw_route_line(self, route, Color(0.50, 0.91, 1.0, 0.78), 2.2)
			var row := _s10_formation_row(formation_id)
			var authoritative := _s10_pixel(row.get("display_pixel", null))
			if authoritative == Vector2.INF:
				authoritative = track.get("end_pixel", Vector2.ZERO)
			var screen := _image_to_screen(operational_presenter.display_pixel(formation_id, authoritative))
			var faction_color: Color = FACTION_COLORS.get(String(row.get("faction", "neutral")), FACTION_COLORS["neutral"])
			var summary := _s10_formation_summary(formation_id)
			var emphasized := participants.has(formation_id)
			MapMarkersScript.draw_formation_counter(
				self,
				screen,
				faction_color,
				String(summary.get("glyph", "X")),
				int(summary.get("unit_count", 0)),
				emphasized
			)
			if emphasized:
				draw_arc(screen, 25.0, 0.0, TAU, 32, Color("ffd27a"), 2.5)
		for model_variant: Variant in _s10_stationary_participant_models(contact, tracks):
			if not model_variant is Dictionary:
				continue
			var model := model_variant as Dictionary
			var image_pixel: Vector2 = model.get("image_pixel", Vector2.INF)
			if image_pixel == Vector2.INF:
				continue
			var screen_offset: Vector2 = model.get("screen_offset", Vector2.ZERO)
			var screen := _image_to_screen(image_pixel) + screen_offset
			var faction_color: Color = FACTION_COLORS.get(
				String(model.get("faction", "neutral")),
				FACTION_COLORS["neutral"]
			)
			MapMarkersScript.draw_formation_counter(
				self,
				screen,
				faction_color,
				String(model.get("glyph", "X")),
				int(model.get("unit_count", 0)),
				true
			)
			draw_arc(screen, 25.0, 0.0, TAU, 32, Color("ffd27a"), 2.5)
		if not contact.is_empty():
			var encounter_pixel: Variant = contact.get("encounter_pixel", Vector2.INF)
			if encounter_pixel is Vector2 and encounter_pixel != Vector2.INF:
				var contact_screen := _image_to_screen(encounter_pixel)
				MapMarkersScript.draw_crossed_swords_battle_marker(self, contact_screen)
				var kind := String(contact.get("kind", ""))
				if BattleLocationScript.is_edge_encounter_kind(kind):
					MapMarkersScript.draw_edge_contact_marker(self, contact_screen + Vector2(14, 0))
				else:
					MapMarkersScript.draw_node_contact_marker(self, contact_screen + Vector2(14, 0))
				var label := String(contact.get("label", "Contact"))
				var label_rect := Rect2(contact_screen + Vector2(24, -34), Vector2(230, 27))
				draw_rect(label_rect, Color(0.04, 0.055, 0.075, 0.96))
				draw_rect(label_rect, Color("ffd27a"), false, 1.0)
				draw_string(ThemeDB.fallback_font, label_rect.position + Vector2(9, 18), label, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color.WHITE)
	if not outcome.is_empty():
		_draw_operational_outcome(outcome)


func _draw_operational_outcome(outcome: Dictionary) -> void:
	var map_width := get_viewport_rect().size.x - PANEL_WIDTH
	var band := Rect2(18.0, HEADER_SAFE_TOP + 10.0, map_width - 36.0, 70.0)
	draw_rect(band, Color(0.035, 0.047, 0.062, 0.96))
	draw_rect(band, Color("ffd27a"), false, 1.5)
	var winner := String(outcome.get("winner", "")).to_upper()
	var line := "Battle finalized" if winner.is_empty() else "Battle finalized — %s victory" % winner
	var detail: Array = []
	for row_variant: Variant in outcome.get("retreat_outcomes", []):
		if not row_variant is Dictionary:
			continue
		var row := row_variant as Dictionary
		var formation_id := String(row.get("formation_id", "Formation"))
		var destination_value: Variant = row.get("destination_province_id", null)
		if destination_value == null:
			destination_value = row.get("destination_node_id", "")
		var destination := "" if destination_value == null else String(destination_value)
		var reason := String(row.get("reason", ""))
		if not destination.is_empty():
			detail.append("%s retreated to %s" % [formation_id, destination])
			var destination_pixel: Variant = row.get("destination_pixel", null)
			if destination_pixel is Vector2:
				var screen := _image_to_screen(destination_pixel)
				draw_circle(screen, 9.0, Color(0.35, 0.87, 1.0, 0.22))
				draw_arc(screen, 13.0, 0.0, TAU, 28, Color("7fe7ff"), 2.2)
		elif not reason.is_empty():
			detail.append("%s trapped — %s" % [formation_id, reason.replace("_", " ")])
	draw_string(ThemeDB.fallback_font, band.position + Vector2(16, 25), line, HORIZONTAL_ALIGNMENT_LEFT, -1, 17, Color("ffd27a"))
	draw_string(ThemeDB.fallback_font, band.position + Vector2(16, 50), "  |  ".join(detail), HORIZONTAL_ALIGNMENT_LEFT, band.size.x - 32.0, 13, Color.WHITE)


func _s10_formation_row(formation_id: String) -> Dictionary:
	for mock_variant: Variant in presentation_fixture.get("presentation_formations", []):
		if mock_variant is Dictionary and String((mock_variant as Dictionary).get("id", "")) == formation_id:
			return mock_variant as Dictionary
	for row_variant: Variant in snapshot.get("strategic_formations", []):
		if row_variant is Dictionary and String((row_variant as Dictionary).get("id", "")) == formation_id:
			return row_variant as Dictionary
	return {}


func _s10_formation_summary(formation_id: String) -> Dictionary:
	var mock := _s10_formation_row(formation_id)
	if mock.has("presentation_unit_count") or mock.has("presentation_glyph"):
		return {
			"unit_count": int(mock.get("presentation_unit_count", 0)),
			"glyph": String(mock.get("presentation_glyph", "X")),
		}
	var unit_count := 0
	var glyph := "X"
	for row_variant: Variant in snapshot.get("battalions", []):
		if not row_variant is Dictionary:
			continue
		var row := row_variant as Dictionary
		if String(row.get("strategic_formation_id", "")) != formation_id:
			continue
		unit_count += int(row.get("unit_count", 0))
		if glyph == "X":
			glyph = MapMarkersScript.battalion_type_glyph(String(row.get("battalion_type", "")))
	return {"unit_count": unit_count, "glyph": glyph}


func _s10_stationary_participant_models(contact: Dictionary, tracks: Dictionary) -> Array:
	## Build one explicit overlay counter per stationary participant using exact
	## strategic formation IDs. Colocated participants receive stable offsets so
	## every formation remains visible; nonparticipants stay in the ordinary layer.
	var grouped: Dictionary = {}
	var participant_ids: Array = contact.get("participant_formation_ids", []).duplicate()
	participant_ids.sort()
	for formation_id_variant: Variant in participant_ids:
		var formation_id := String(formation_id_variant)
		if formation_id.is_empty() or tracks.has(formation_id):
			continue
		var row := _s10_formation_row(formation_id)
		var image_pixel := _s10_pixel(row.get("display_pixel", null))
		if image_pixel == Vector2.INF:
			var encounter: Variant = contact.get("encounter_pixel", Vector2.INF)
			if encounter is Vector2:
				image_pixel = encounter as Vector2
		if image_pixel == Vector2.INF:
			continue
		var summary := _s10_formation_summary(formation_id)
		var key := "%.3f|%.3f" % [image_pixel.x, image_pixel.y]
		if not grouped.has(key):
			grouped[key] = []
		(grouped[key] as Array).append({
			"formation_id": formation_id,
			"faction": String(row.get("faction", "neutral")),
			"image_pixel": image_pixel,
			"glyph": String(summary.get("glyph", "X")),
			"unit_count": int(summary.get("unit_count", 0)),
		})
	var result: Array = []
	var group_keys: Array = grouped.keys()
	group_keys.sort()
	for key_variant: Variant in group_keys:
		var group: Array = grouped[key_variant]
		group.sort_custom(func(left: Dictionary, right: Dictionary) -> bool:
			return String(left.get("formation_id", "")) < String(right.get("formation_id", ""))
		)
		var midpoint := float(group.size() - 1) * 0.5
		for index in range(group.size()):
			var model := (group[index] as Dictionary).duplicate(true)
			model["screen_offset"] = Vector2((float(index) - midpoint) * 40.0, 0.0)
			result.append(model)
	return result


func _s10_pixel(value: Variant) -> Vector2:
	if value is Array and (value as Array).size() == 2:
		return Vector2(float((value as Array)[0]), float((value as Array)[1]))
	return Vector2.INF


func _draw_command_busy_overlay() -> void:
	if not has_method("is_command_busy") or not is_command_busy():
		return
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	var band := Rect2(0, HEADER_SAFE_TOP, map_width, 28.0)
	draw_rect(band, Color(0.12, 0.08, 0.02, 0.92))
	draw_rect(band, Color("ffb14e"), false, 1.0)
	var label := command_busy_label() if has_method("command_busy_label") else "Backend busy..."
	draw_string(
		ThemeDB.fallback_font,
		Vector2(16, HEADER_SAFE_TOP + 19.0),
		label + "  (pan/zoom still available)",
		HORIZONTAL_ALIGNMENT_LEFT,
		map_width - 32,
		14,
		Color("ffd27a")
	)


func _draw_coalition_fronts() -> void:
	# Debug-only: orange lines are ownership-adjacency front segments, not province borders.
	for edge: Array in snapshot.get("edges", []):
		if edge.size() != 2:
			continue
		var left_id := String(edge[0])
		var right_id := String(edge[1])
		var left: Dictionary = provinces_by_id.get(left_id, {})
		var right: Dictionary = provinces_by_id.get(right_id, {})
		if left.is_empty() or right.is_empty():
			continue
		if String(left.get("owner", "neutral")) == String(right.get("owner", "neutral")):
			continue
		draw_line(
			_image_to_screen(_active_map().anchor_pixel(left_id)),
			_image_to_screen(_active_map().anchor_pixel(right_id)),
			Color(1.0, 0.76, 0.31, 0.35),
			1.0
		)


func _draw_crossing_overlay() -> void:
	# Debug topology: land / strait / ferry / sea-lane edges from manifest edge_types.
	var drawn: Dictionary = {}
	for province_id: Variant in _active_map().row_by_province.keys():
		var pid := String(province_id)
		var row: Dictionary = _active_map().row_by_province.get(pid, {})
		var edge_types: Dictionary = row.get("edge_types", {})
		if edge_types.is_empty():
			continue
		var origin := _image_to_screen(_active_map().anchor_pixel(pid))
		for neighbor_id: Variant in edge_types.keys():
			var nid := String(neighbor_id)
			if not _active_map().row_by_province.has(nid):
				continue
			var key := pid + "|" + nid if pid < nid else nid + "|" + pid
			if drawn.has(key):
				continue
			drawn[key] = true
			var etype := String(edge_types.get(nid, "land"))
			var target := _image_to_screen(_active_map().anchor_pixel(nid))
			var color := Color(0.55, 0.58, 0.62, 0.22)
			var width := 1.0
			var label := ""
			if etype == "land":
				color = Color(0.45, 0.48, 0.52, 0.18)
				width = 1.0
			elif etype == "strait":
				color = Color(0.25, 0.85, 1.0, 0.75)
				width = 2.2
				label = "strait"
			elif etype == "ferry" or etype == "ferry_or_sea_lane":
				color = Color(0.35, 1.0, 0.55, 0.78)
				width = 2.0
				label = "ferry" if etype == "ferry" else "ferry/lane"
			elif etype == "sea_lane":
				color = Color(0.95, 0.75, 0.25, 0.80)
				width = 2.0
				label = "sea"
			else:
				color = Color(1.0, 0.4, 0.9, 0.7)
				width = 1.5
				label = etype
			# Land edges stay very faint; non-land get strong strokes + midpoint labels.
			if etype == "land":
				draw_line(origin, target, color, width)
			else:
				draw_line(origin, target, color, width)
				var mid := (origin + target) * 0.5
				if not label.is_empty():
					draw_string(
						ThemeDB.fallback_font,
						mid + Vector2(4, -4),
						label,
						HORIZONTAL_ALIGNMENT_LEFT,
						-1,
						11,
						color
					)


func _draw_color_id_pending_battle() -> void:
	var pending: Variant = snapshot.get("pending_battle")
	if not pending is Dictionary:
		return
	var battle := pending as Dictionary
	var origin_id := String(battle.get("origin_province_id", ""))
	var target_id := String(battle.get("target_province_id", ""))
	var legacy_origin := Vector2.INF
	var legacy_target := Vector2.INF
	if _active_map().row_by_province.has(origin_id):
		legacy_origin = _active_map().anchor_pixel(origin_id)
	if _active_map().row_by_province.has(target_id):
		legacy_target = _active_map().anchor_pixel(target_id)
	var graph_index: Dictionary = operational_graph.index if operational_graph.is_ready else {}
	var resolved: Dictionary = BattleLocationScript.resolve_pending_battle_location(
		battle,
		graph_index,
		legacy_origin,
		legacy_target
	)
	if not bool(resolved.get("ok", false)):
		return
	var map_pixel: Vector2 = resolved.get("map_pixel", Vector2.ZERO)
	var screen := _image_to_screen(map_pixel)
	if bool(resolved.get("draw_origin_target_line", false)) \
	and legacy_origin != Vector2.INF and legacy_target != Vector2.INF:
		draw_line(_image_to_screen(legacy_origin), _image_to_screen(legacy_target), Color("ff9f43"), 3.0)
	var kind := String(resolved.get("encounter_kind", battle.get("encounter_kind", "")))
	MapMarkersScript.draw_crossed_swords_battle_marker(self, screen)
	if BattleLocationScript.is_edge_encounter_kind(kind):
		MapMarkersScript.draw_edge_contact_marker(self, screen + Vector2(14, 0))
	elif BattleLocationScript.is_node_encounter_kind(kind):
		MapMarkersScript.draw_node_contact_marker(self, screen + Vector2(14, 0))


func _draw_presentation_fixture_markers() -> void:
	if presentation_fixture.is_empty():
		return
	for route: Variant in presentation_fixture.get("routes", []):
		if not route is Dictionary:
			continue
		var points := PackedVector2Array()
		for px: Variant in (route as Dictionary).get("pixels", []):
			if px is Array and (px as Array).size() >= 2:
				points.append(_image_to_screen(Vector2(float(px[0]), float(px[1]))))
		MapMarkersScript.draw_route_line(self, points)
	for battle: Variant in presentation_fixture.get("battles", []):
		if not battle is Dictionary:
			continue
		var row := battle as Dictionary
		var pos := MapMarkersScript.battle_marker_position(row, map_space)
		if pos == Vector2.ZERO:
			continue
		MapMarkersScript.draw_crossed_swords_battle_marker(self, pos)
		if String(row.get("kind", "")) == "edge":
			MapMarkersScript.draw_edge_contact_marker(self, pos + Vector2(14, 0))
	for contact: Variant in presentation_fixture.get("contacts", []):
		if not contact is Dictionary:
			continue
		var crow := contact as Dictionary
		var cpos := MapMarkersScript.battle_marker_position(crow, map_space)
		if cpos == Vector2.ZERO:
			continue
		if String(crow.get("kind", "")) == "edge":
			MapMarkersScript.draw_edge_contact_marker(self, cpos)
		else:
			MapMarkersScript.draw_node_contact_marker(self, cpos)
	for site: Variant in presentation_fixture.get("control_sites", []):
		if not site is Dictionary:
			continue
		var srow := site as Dictionary
		var spos := MapMarkersScript.battle_marker_position(srow, map_space)
		if spos == Vector2.ZERO and srow.has("pixel"):
			var px2: Variant = srow.get("pixel")
			if px2 is Array and (px2 as Array).size() >= 2:
				spos = _image_to_screen(Vector2(float(px2[0]), float(px2[1])))
		if spos == Vector2.ZERO:
			continue
		MapMarkersScript.draw_control_site_marker(self, spos, bool(srow.get("owned", false)))
		if int(srow.get("presentation_capture_progress_fp", -1)) >= 0:
			MapMarkersScript.draw_capture_progress(
				self,
				spos + Vector2(18, 0),
				int(srow.get("presentation_capture_progress_fp", 0)),
				int(srow.get("presentation_capture_max_fp", 1000))
			)
	for counter: Variant in presentation_fixture.get("synthetic_counters", []):
		if not counter is Dictionary:
			continue
		var crow2 := counter as Dictionary
		var cpx: Variant = crow2.get("pixel", null)
		if not (cpx is Array and (cpx as Array).size() >= 2):
			continue
		var ccenter := _image_to_screen(Vector2(float(cpx[0]), float(cpx[1])))
		var faction := String(crow2.get("faction", "neutral"))
		var color: Color = FACTION_COLORS.get(faction, FACTION_COLORS["neutral"])
		MapMarkersScript.draw_formation_counter(
			self,
			ccenter,
			color,
			String(crow2.get("glyph", "X")),
			int(crow2.get("strength", 0)),
			false
		)
		var stack_n := int(crow2.get("stack", 1))
		if stack_n > 1:
			MapMarkersScript.draw_stack_badge(self, ccenter + Vector2(19, -14), stack_n)
	for badge: Variant in presentation_fixture.get("force_stack_badges", []):
		if not badge is Dictionary:
			continue
		var brow := badge as Dictionary
		var bpx: Variant = brow.get("pixel", null)
		if bpx is Array and (bpx as Array).size() >= 2:
			MapMarkersScript.draw_stack_badge(
				self,
				_image_to_screen(Vector2(float(bpx[0]), float(bpx[1]))),
				int(brow.get("count", 1))
			)
	_draw_presentation_proof_overlays()


func _draw_presentation_proof_overlays() -> void:
	# Temporary presentation-only: eastern extent labels, Europe-Asia boundary, federal outlines.
	if presentation_fixture.is_empty():
		return
	# Federal subject outlines (behind labels). Quieter at full theatre; stronger when zoomed.
	var fed_w := clampf(1.2 + view_scale * 0.35, 1.2, 2.6)
	var fed_a := clampf(0.28 + view_scale * 0.12, 0.28, 0.7)
	if view_scale < 0.9:
		fed_a *= 0.55
	for subj: Variant in presentation_fixture.get("federal_subject_outlines", []):
		if not subj is Dictionary:
			continue
		var srow := subj as Dictionary
		var outline := PackedVector2Array()
		for px: Variant in srow.get("outline_pixels", []):
			if px is Array and (px as Array).size() >= 2:
				outline.append(_image_to_screen(Vector2(float(px[0]), float(px[1]))))
		if outline.size() >= 3:
			outline.append(outline[0])
			var col := Color(0.95, 0.75, 0.2, fed_a)
			var sid := String(srow.get("id", ""))
			if sid.ends_with("-city"):
				col = Color(1.0, 0.45, 0.35, minf(0.85, fed_a + 0.15))
			elif sid.find("oblast") >= 0 or sid.ends_with("-oblast"):
				col = Color(0.35, 0.85, 1.0, fed_a)
			draw_polyline(outline, col, fed_w, true)
	# Conventional Europe-Asia boundary.
	var bpts := PackedVector2Array()
	for px2: Variant in presentation_fixture.get("europe_asia_boundary_pixels", []):
		if px2 is Array and (px2 as Array).size() >= 2:
			bpts.append(_image_to_screen(Vector2(float(px2[0]), float(px2[1]))))
	if bpts.size() >= 2:
		draw_polyline(bpts, Color(1.0, 0.75, 0.1, 0.95), 3.0, true)
		draw_polyline(bpts, Color(1.0, 0.35, 0.05, 0.85), 1.5, true)
	# Eastern city proof labels.
	for lab: Variant in presentation_fixture.get("proof_labels", []):
		if not lab is Dictionary:
			continue
		var lrow := lab as Dictionary
		var lp: Variant = lrow.get("pixel", null)
		if not (lp is Array and (lp as Array).size() >= 2):
			continue
		var pos := _image_to_screen(Vector2(float(lp[0]), float(lp[1])))
		draw_circle(pos, 5.0, Color(1.0, 0.95, 0.3, 1.0))
		draw_arc(pos, 9.0, 0.0, TAU, 24, Color(1.0, 0.4, 0.15, 0.95), 2.0)
		var text := String(lrow.get("label", ""))
		if text.is_empty():
			continue
		draw_string(
			ThemeDB.fallback_font,
			pos + Vector2(12, -6),
			text,
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			14,
			Color(1.0, 0.95, 0.75, 1.0)
		)


func _draw_color_id_overlays() -> void:
	# Pass 1: facilities + counters (always). Pass 2: priority label declutter.
	# Counters/labels are clamped inside the map viewport (header/footer safe).
	var overlay_bounds := _overlay_clamp_rect()
	var cache_key := "%s|%s|%s" % [
		selected_province_id,
		str(legal_targets.keys()),
		snappedf(view_scale, 0.001),
	]
	var rebuild := cache_key != _overlay_cache_key
	var label_candidates: Array = []
	var reserved: Array = []
	if rebuild:
		_overlay_cache_key = cache_key
		_cached_label_candidates.clear()
		_cached_reserved_rects.clear()
		overlay_rebuild_count += 1

	# PR C: avoid scanning all ~3.5k snapshot provinces every frame when idle.
	# Active set = occupied + selected/hovered/targets + infrastructure sites
	# (+ all provinces only when rebuilding ambient labels at high zoom).
	# Camera motion must not walk the full theatre: pan only transforms cached
	# image-space labels.
	_ensure_snapshot_overlay_indexes()
	var active_ids: Dictionary = _build_overlay_active_ids()
	var camera_moving := has_method("camera_is_moving") and camera_is_moving()
	var scan_all := rebuild and view_scale >= 2.4 and not camera_moving
	var province_iter: Array = []
	if scan_all:
		province_iter = snapshot.get("provinces", [])
	else:
		var am_rows = _active_map().row_by_province if _active_map() != null else {}
		for pid_key: Variant in active_ids.keys():
			var pid_s := String(pid_key)
			if am_rows is Dictionary and not am_rows.has(pid_s):
				continue
			if _snap_by_id.has(pid_s):
				province_iter.append(_snap_by_id[pid_s])
			else:
				province_iter.append({"id": pid_s, "owner": "neutral", "infrastructure": {}})

	overlay_provinces_scanned = province_iter.size()
	overlay_last_scan_all = scan_all
	for province: Dictionary in province_iter:
		var province_id := String(province.get("id", ""))
		if not _active_map().row_by_province.has(province_id):
			continue
		var battalion: Dictionary = battalions_by_province.get(province_id, {})
		var occupied := not battalion.is_empty()
		var selected := province_id == selected_province_id
		var target := legal_targets.has(province_id)
		var hovered := province_id == hovered_province_id
		var infrastructure: Dictionary = province.get("infrastructure", {})
		var has_infra := (
			int(infrastructure.get("supply_hub", 0)) > 0
			or int(infrastructure.get("command_post", 0)) > 0
			or int(infrastructure.get("air_base", 0)) > 0
		)
		# Skip empty ambient provinces during non-label frames (infra always kept via active set).
		if not scan_all and not occupied and not selected and not hovered and not target and not has_infra:
			continue
		var anchor := _image_to_screen(_active_map().anchor_pixel(province_id))
		var position := _clamp_point_in_rect(anchor, overlay_bounds, OVERLAY_EDGE_PAD)
		var shifted := position.distance_to(anchor) > 0.5
		var owner := String(province.get("owner", "neutral"))
		var faction_color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])

		if selected:
			MapMarkersScript.draw_selected_province_ring(self, position)
		elif hovered:
			MapMarkersScript.draw_hovered_province_ring(self, position)

		if shifted and (occupied or selected or target or hovered):
			draw_line(anchor, position, Color(0.85, 0.9, 0.95, 0.55), 1.0)
			draw_circle(anchor, 2.0, Color(0.85, 0.9, 0.95, 0.7))

		# Infrastructure icons: every zoom level (same as PR B).
		if int(infrastructure.get("supply_hub", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-13, 12), Vector2(6, 6)), Color("63d69f"))
		if int(infrastructure.get("command_post", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-4, 12), Vector2(6, 6)), Color("b892ff"))
		if int(infrastructure.get("air_base", 0)) > 0:
			draw_circle(position + Vector2(8, 15), 3.2, Color("7fe7ff"))

		if occupied:
			# LOD: full-theatre hides ambient counters; keep selected/hovered/target stacks.
			var show_counter := view_scale >= 0.95 or selected or hovered or target
			if show_counter:
				# Prefer operational display_pixel (node) when present; else province anchor.
				var counter_pos := position
				var display_pixel: Variant = battalion.get("display_pixel", null)
				if display_pixel is Array and (display_pixel as Array).size() >= 2:
					var px := float((display_pixel as Array)[0])
					var py := float((display_pixel as Array)[1])
					counter_pos = _clamp_point_in_rect(
						_image_to_screen(Vector2(px, py)),
						overlay_bounds,
						OVERLAY_EDGE_PAD
					)
				if not bool(battalion.get("is_in_supply", true)):
					draw_arc(counter_pos, 22.0, 0.0, TAU, 30, Color("ff6b5f"), 2.4)
				if int(battalion.get("encircled_turns", 0)) > 0:
					draw_arc(counter_pos, 25.0, 0.0, TAU, 30, Color("ffb14e"), 2.4)
				var counter_rect := MapMarkersScript.draw_formation_counter(
					self,
					counter_pos,
					faction_color,
					MapMarkersScript.battalion_type_glyph(String(battalion.get("battalion_type", ""))),
					int(battalion.get("unit_count", 0)),
					selected,
					bool(battalion.get("is_in_supply", true)),
					int(battalion.get("encircled_turns", 0)) > 0,
					String(battalion.get("strategic_formation_id", ""))
				)
				reserved.append(counter_rect)
				var stack: Array = battalion_stacks_by_province.get(province_id, [])
				if stack.size() > 1 and view_scale >= 1.15:
					var badge := _clamp_point_in_rect(counter_pos + Vector2(19, -14), overlay_bounds, 12.0)
					reserved.append(MapMarkersScript.draw_stack_badge(self, badge, stack.size()))

		if not rebuild:
			continue
		var label := _province_label(province, province_id)
		var named := bool(province.get("name_is_human_readable", _is_named_province(label)))
		var priority := 0
		if selected:
			priority = 100
		elif target:
			priority = 80
		elif occupied and view_scale >= 1.05:
			priority = 70
		elif named and view_scale >= 2.4:
			priority = 40
		elif hovered and view_scale >= 1.3:
			priority = 60
		# Full-theatre Home: suppress ambient names (declutter). Hover labels added live.
		if priority <= 0:
			continue
		var font_size := 12 if priority >= 70 else 11
		var text_w := float(ThemeDB.fallback_font.get_string_size(label, HORIZONTAL_ALIGNMENT_LEFT, -1, font_size).x)
		var raw_text_pos := position + Vector2(13, -9)
		var text_pos := _clamp_point_in_rect(raw_text_pos, overlay_bounds, OVERLAY_EDGE_PAD)
		text_pos.x = minf(text_pos.x, overlay_bounds.position.x + overlay_bounds.size.x - text_w - 4.0)
		text_pos.y = clampf(text_pos.y, overlay_bounds.position.y + font_size, overlay_bounds.position.y + overlay_bounds.size.y - 4.0)
		var text_rect := Rect2(text_pos + Vector2(0, -font_size), Vector2(text_w + 4.0, float(font_size) + 4.0))
		label_candidates.append({
			"priority": priority,
			"label": label,
			"image": _active_map().anchor_pixel(province_id),
			"pos": text_pos,
			"rect": text_rect,
			"font_size": font_size,
			"color": Color(0.95, 0.96, 0.98, 0.98 if priority >= 70 else 0.78),
			"must_show": priority >= 100,
			"province_id": province_id,
		})

	if rebuild:
		label_candidates.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
			return int(a.get("priority", 0)) > int(b.get("priority", 0))
		)
		var accepted: Array = []
		var accepted_bounds: Array = []
		var occupied_rects: Array = reserved.duplicate()
		for candidate: Dictionary in label_candidates:
			var rect: Rect2 = candidate.get("rect", Rect2())
			var blocked := false
			if not bool(candidate.get("must_show", false)):
				for prior: Variant in occupied_rects:
					if rect.intersects(prior as Rect2):
						blocked = true
						break
			if blocked:
				continue
			accepted.append(candidate)
			accepted_bounds.append(rect)
			occupied_rects.append(rect)
		_cached_label_candidates = accepted
		_cached_label_bounds = accepted_bounds
		_cached_reserved_rects = reserved.duplicate()
	else:
		reserved = _cached_reserved_rects.duplicate()

	for candidate: Dictionary in _cached_label_candidates:
		var image_pos: Vector2 = candidate.get("image", Vector2.ZERO)
		var label_pos: Vector2 = candidate.get("pos", Vector2.ZERO)
		if image_pos != Vector2.ZERO or candidate.has("image"):
			label_pos = _clamp_point_in_rect(
				_image_to_screen(image_pos) + Vector2(13, -9),
				overlay_bounds,
				OVERLAY_EDGE_PAD
			)
		draw_string(
			ThemeDB.fallback_font,
			label_pos,
			String(candidate.get("label", "")),
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			int(candidate.get("font_size", 11)),
			candidate.get("color", Color.WHITE)
		)
	# Hover label is cheap and not cached into selection layout.
	if not hovered_province_id.is_empty() and _active_map().row_by_province.has(hovered_province_id):
		var hprov: Dictionary = provinces_by_id.get(hovered_province_id, {})
		if not hprov.is_empty():
			var hlabel := _province_label(hprov, hovered_province_id)
			var hpos := _image_to_screen(_active_map().anchor_pixel(hovered_province_id)) + Vector2(13, -9)
			hpos = _clamp_point_in_rect(hpos, overlay_bounds, OVERLAY_EDGE_PAD)
			draw_string(
				ThemeDB.fallback_font,
				hpos,
				hlabel,
				HORIZONTAL_ALIGNMENT_LEFT,
				-1,
				12,
				Color(1.0, 1.0, 1.0, 0.95)
			)


func _province_at(screen_position: Vector2) -> String:
	var am = _active_map()
	if am == null or not am.is_ready:
		return super._province_at(screen_position)
	_sync_map_space()
	var rect := map_space.texture_rect()
	if not rect.has_point(screen_position):
		return ""
	var pixel := map_space.screen_to_pixel(screen_position)
	var size: Vector2 = am.image_size()
	pixel = Vector2i(
		clampi(pixel.x, 0, int(size.x) - 1),
		clampi(pixel.y, 0, int(size.y) - 1)
	)
	return am.province_at_pixel(pixel)


func _map_to_screen(province: Dictionary) -> Vector2:
	var am = _active_map()
	if am != null and am.is_ready:
		return _image_to_screen(am.anchor_pixel(String(province.get("id", ""))))
	return super._map_to_screen(province)


func _image_to_screen(pixel: Vector2) -> Vector2:
	_sync_map_space()
	return map_space.image_to_screen(pixel)


func _map_content_rect() -> Rect2:
	# Usable map panel excluding header/footer chrome and side panel.
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	return Rect2(
		Vector2(HOME_MAP_MARGIN.x, HEADER_SAFE_TOP + HOME_MAP_MARGIN.y),
		Vector2(
			map_width - HOME_MAP_MARGIN.x * 2.0,
			viewport.y - HEADER_SAFE_TOP - FOOTER_SAFE_BOTTOM - HOME_MAP_MARGIN.y * 2.0
		)
	)


func _map_texture_rect() -> Rect2:
	_sync_map_space()
	return map_space.texture_rect()


func _overlay_clamp_rect() -> Rect2:
	# Keep counters/labels fully inside the visible map panel (under header).
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	return Rect2(
		Vector2(4.0, HEADER_SAFE_TOP + 4.0),
		Vector2(map_width - 8.0, viewport.y - HEADER_SAFE_TOP - FOOTER_SAFE_BOTTOM - 8.0)
	)


func _clamp_point_in_rect(point: Vector2, bounds: Rect2, pad: float) -> Vector2:
	return Vector2(
		clampf(point.x, bounds.position.x + pad, bounds.position.x + bounds.size.x - pad),
		clampf(point.y, bounds.position.y + pad, bounds.position.y + bounds.size.y - pad)
	)


func _province_label(province: Dictionary, province_id: String) -> String:
	var label := String(province.get("display_name", province_id)).strip_edges()
	if label.is_empty():
		return province_id
	# Prefer manifest source name when campaign still has a generic label.
	if not _is_named_province(label) and color_id_map != null and _active_map().row_by_province.has(province_id):
		var row: Dictionary = _active_map().row_by_province[province_id]
		var source_label := String(row.get("display_name", "")).strip_edges()
		if _is_named_province(source_label):
			return source_label
	return label


func _is_named_province(label: String) -> bool:
	var lower := label.to_lower().strip_edges()
	if lower.is_empty():
		return false
	if lower.begins_with("province"):
		return false
	return true


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		var key := event as InputEventKey
		if has_method("is_command_busy") and is_command_busy():
			if key.keycode in [KEY_E, KEY_A, KEY_H, KEY_R]:
				var busy_label := "backend"
				if has_method("command_busy_label"):
					busy_label = String(command_busy_label())
				status_message = "Busy - wait for command (%s)." % busy_label
				queue_redraw()
				get_viewport().set_input_as_handled()
				return
		if key.keycode == KEY_F3:
			map_debug.toggle()
			set_process(map_debug.enabled or _screenshot_frames_left >= 0)
			status_message = (
				"Map debug ON (F3). Boundaries/IDs/FPS/invalidation. Disabled in ordinary play."
				if map_debug.enabled
				else "Map debug OFF."
			)
			queue_redraw()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_G:
			show_coalition_fronts = not show_coalition_fronts
			status_message = (
				"Coalition front lines ON (ownership-adjacency debug). Press G to hide."
				if show_coalition_fronts
				else "Coalition front lines OFF."
			)
			queue_redraw()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_C:
			show_crossing_overlay = not show_crossing_overlay
			status_message = (
				"Crossing overlay ON (land faint / strait cyan / ferry green / sea gold). Press C to hide."
				if show_crossing_overlay
				else "Crossing overlay OFF."
			)
			queue_redraw()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_HOME:
			_fit_complete_theatre()
			get_viewport().set_input_as_handled()
			return
		if key.keycode == KEY_F:
			_fit_to_focus(true)
			get_viewport().set_input_as_handled()
			return
	if event is InputEventMouseMotion and _active_map() != null and _active_map().is_ready:
		var motion := event as InputEventMouseMotion
		var map_width := get_viewport_rect().size.x - PANEL_WIDTH
		var next_hover := ""
		if motion.position.x < map_width:
			next_hover = _province_at(motion.position)
			if map_debug.enabled:
				map_debug.last_screen_pos = motion.position
				map_debug.last_map_pixel = map_space.screen_to_pixel(motion.position)
		# Hover never rebuilds ownership/highlight textures — canvas redraw only.
		if next_hover != hovered_province_id:
			hovered_province_id = next_hover
			queue_redraw()
	super._unhandled_input(event)


func _fit_complete_theatre() -> void:
	_invalidate_overlay_cache()
	_layers_dirty = true
	var am = _active_map()
	if am == null or not am.is_ready:
		view_scale = HOME_FIT_FILL
		view_offset = Vector2.ZERO
		fitted_once = true
		status_message = "Fitted full theatre."
		queue_redraw()
		return
	# Earth3: prefer a tighter home framing (less empty ocean) while remaining fully pannable/zoomable.
	if map_backend_is_polygon and _apply_earth3_home_framing(am):
		fitted_once = true
		var map_contract0: Dictionary = snapshot.get("strategic_map", {})
		var mid0 := String(map_contract0.get("map_id", "earth3_europe_mediterranean"))
		var pcount0 := _loaded_province_count()
		status_message = "Fitted Earth3 home frame map %s (%s provinces). Home=frame  F=front." % [mid0, pcount0]
		queue_redraw()
		return
	# Fill more of the map panel while keeping aspect ratio; panel stays clear.
	view_scale = HOME_FIT_FILL
	view_offset = Vector2.ZERO
	fitted_once = true
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	var pcount := _loaded_province_count()
	status_message = "Fitted complete theatre (%s provinces). Home=full  F=front." % [pcount]
	var mid := String(map_contract.get("map_id", ""))
	if mid.is_empty() and map_backend_is_polygon:
		mid = "earth3_europe_mediterranean"
	if not mid.is_empty():
		status_message = "Fitted complete theatre map %s (%s provinces)." % [mid, pcount]
	queue_redraw()


func _apply_earth3_home_framing(am) -> bool:
	var rect_d: Dictionary = {}
	if presentation_fixture.has("home_image_rect") and presentation_fixture.get("home_image_rect") is Dictionary:
		rect_d = presentation_fixture.get("home_image_rect")
	else:
		var sm: Dictionary = snapshot.get("strategic_map", {})
		if sm.has("home_image_rect") and sm.get("home_image_rect") is Dictionary:
			rect_d = sm.get("home_image_rect")
	if rect_d.is_empty():
		# Default tighter frame for Earth3 full theatre (image space).
		var img: Vector2 = am.image_size()
		rect_d = {"x": 20.0, "y": 220.0, "w": maxf(img.x - 40.0, 1.0), "h": maxf(img.y - 450.0, 1.0)}
	var rx := float(rect_d.get("x", 0.0))
	var ry := float(rect_d.get("y", 0.0))
	var rw := float(rect_d.get("w", 0.0))
	var rh := float(rect_d.get("h", 0.0))
	if rw <= 1.0 or rh <= 1.0:
		return false
	var img_size: Vector2 = am.image_size()
	var content := _map_content_rect()
	var fit_full := minf(content.size.x / maxf(img_size.x, 1.0), content.size.y / maxf(img_size.y, 1.0))
	if fit_full <= 0.0:
		return false
	var fit_home := minf(content.size.x / rw, content.size.y / rh)
	view_scale = clampf(fit_home / fit_full, 0.85, 3.5)
	# Center the home rect in the map panel.
	_sync_map_space()
	var home_center := Vector2(rx + rw * 0.5, ry + rh * 0.5)
	var map_center := Vector2(content.position.x + content.size.x * 0.5, content.position.y + content.size.y * 0.5)
	view_offset = Vector2.ZERO
	_sync_map_space()
	var screen_pt: Vector2 = map_space.image_to_screen(home_center)
	view_offset = map_center - screen_pt
	return true


func _fit_to_focus(force: bool) -> void:
	if color_id_map == null or _active_map() == null or not _active_map().is_ready:
		super._fit_to_focus(force)
		return
	if fitted_once and not force:
		return
	_invalidate_overlay_cache()
	var ids: Dictionary = {}
	for id: Variant in focus_province_ids.keys():
		ids[String(id)] = true
	var campaign: Dictionary = snapshot.get("campaign", {})
	var current := String(campaign.get("current_faction", ""))
	for battalion: Dictionary in snapshot.get("battalions", []):
		if String(battalion.get("faction", "")) == current:
			ids[String(battalion.get("province_id", ""))] = true
	for option: Dictionary in snapshot.get("operational_orders", []):
		ids[String(option.get("origin_province_id", ""))] = true
		ids[String(option.get("target_province_id", ""))] = true
	for option: Dictionary in snapshot.get("front_options", []):
		ids[String(option.get("origin", ""))] = true
		ids[String(option.get("target", ""))] = true
	var pending: Variant = snapshot.get("pending_battle")
	if pending is Dictionary:
		var battle := pending as Dictionary
		ids[String(battle.get("origin_province_id", ""))] = true
		ids[String(battle.get("target_province_id", ""))] = true

	var min_x := INF
	var min_y := INF
	var max_x := -INF
	var max_y := -INF
	var count := 0
	for id: Variant in ids.keys():
		var province_id := String(id)
		if province_id.is_empty() or not _active_map().row_by_province.has(province_id):
			continue
		var anchor := _active_map().anchor_pixel(province_id)
		min_x = minf(min_x, anchor.x)
		max_x = maxf(max_x, anchor.x)
		min_y = minf(min_y, anchor.y)
		max_y = maxf(max_y, anchor.y)
		count += 1
	if count < 4:
		_fit_complete_theatre()
		status_message = "Fit Front had <4 nodes; fell back to complete theatre."
		return
	var image_size := _active_map().image_size()
	var span := Vector2(maxf(max_x - min_x, 48.0), maxf(max_y - min_y, 48.0))
	var padding := 1.45
	view_scale = clampf(minf(image_size.x / (span.x * padding), image_size.y / (span.y * padding)), 1.0, 4.5)
	view_offset = Vector2.ZERO
	var focus_center := Vector2((min_x + max_x) * 0.5, (min_y + max_y) * 0.5)
	var map_center := Vector2(
		(get_viewport_rect().size.x - PANEL_WIDTH) * 0.5,
		get_viewport_rect().size.y * 0.5
	)
	view_offset = map_center - _image_to_screen(focus_center)
	fitted_once = true
	status_message = "Fitted operational front (%s provinces). Home=full theatre." % count
	queue_redraw()
