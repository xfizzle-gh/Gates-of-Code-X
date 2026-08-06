extends "res://scripts/main_writeback.gd"

const ColorIdMapScript = preload("res://scripts/color_id_map.gd")
const MapSpaceScript = preload("res://scripts/presentation/map_space.gd")
const MapMarkersScript = preload("res://scripts/presentation/map_markers.gd")
const MapDebugScript = preload("res://scripts/presentation/map_debug.gd")
const MapTextureLayerScript = preload("res://scripts/presentation/map_texture_layer.gd")
const BattleLocationScript = preload("res://scripts/presentation/battle_location.gd")
const OperationalGraphViewScript = preload("res://scripts/presentation/operational_graph_view.gd")
const DEFAULT_MAP_MANIFEST := "res://assets/maps/europe/interim_goe/map_manifest.json"
const EM_FROM_GOE_MANIFEST := "res://assets/maps/europe_mediterranean/from_goe/map_manifest.json"
const DEFAULT_PRESENTATION_FIXTURE := "res://fixtures/presentation/empty_map.json"
const HOME_MAP_MARGIN := Vector2(18, 18)
const HOME_FIT_FILL := 1.06
# Reserve space so title/diagnostic rows never cover the theatre.
const HEADER_SAFE_TOP := 64.0
const FOOTER_SAFE_BOTTOM := 28.0
const OVERLAY_EDGE_PAD := 18.0

var color_id_map = ColorIdMapScript.new()
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
# Separate CanvasItem layers: filtering is per-node in Godot 4.
var _bg_layer: Node2D
var _identity_layer: Node2D
var _layers_dirty := true
var _last_layer_rect := Rect2()


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
	set_process(map_debug.enabled)
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
	status_message = "Saved screenshot err=%s path=%s ready=%s" % [
		err,
		_screenshot_path,
		str(color_id_map.is_ready),
	]
	print(status_message)
	get_tree().quit(0)


func _resolve_map_manifest_path() -> String:
	var contract: Dictionary = snapshot.get("strategic_map", {})
	var exported := String(contract.get("manifest_path", "")).strip_edges()
	if not exported.is_empty() and FileAccess.file_exists(exported):
		return exported
	var map_id := String(contract.get("map_id", ""))
	if map_id == "europe_mediterranean_from_goe" and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
		return EM_FROM_GOE_MANIFEST
	var campaign: Dictionary = snapshot.get("campaign", {})
	var meta: Dictionary = campaign.get("map_metadata", {})
	var configured := String(meta.get("strategic_map_id", ""))
	if configured == "europe_mediterranean_from_goe" and FileAccess.file_exists(EM_FROM_GOE_MANIFEST):
		return EM_FROM_GOE_MANIFEST
	if FileAccess.file_exists(DEFAULT_MAP_MANIFEST):
		return DEFAULT_MAP_MANIFEST
	return DEFAULT_MAP_MANIFEST


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
	if color_id_map == null or not color_id_map.is_ready:
		if _bg_layer != null:
			_bg_layer.set_draw_items([])
			_bg_layer.refresh()
		if _identity_layer != null:
			_identity_layer.set_draw_items([])
			_identity_layer.refresh()
		_layers_dirty = false
		return
	_sync_map_space()
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	var texture_rect := map_space.texture_rect()
	if not _layers_dirty and texture_rect == _last_layer_rect:
		return
	_last_layer_rect = texture_rect
	_layers_dirty = false
	# Linear-filtered visual background underlay (never authoritative).
	var bg_items: Array = []
	if color_id_map.background_texture != null:
		bg_items.append({"texture": color_id_map.background_texture, "rect": texture_rect})
	_bg_layer.set_clear(Rect2(0, 0, map_width, viewport.y), Color(0.025, 0.035, 0.047, 1.0))
	_bg_layer.set_draw_items(bg_items)
	_bg_layer.refresh()
	# Nearest-filtered owner / border / highlight identity presentation layers.
	var id_items: Array = []
	if color_id_map.owner_texture != null:
		id_items.append({"texture": color_id_map.owner_texture, "rect": texture_rect})
	if color_id_map.border_texture != null:
		id_items.append({"texture": color_id_map.border_texture, "rect": texture_rect})
	if color_id_map.highlight_texture != null:
		id_items.append({"texture": color_id_map.highlight_texture, "rect": texture_rect})
	_identity_layer.set_clear(Rect2(), Color(0, 0, 0, 0))
	_identity_layer.set_draw_items(id_items)
	_identity_layer.refresh()


func _load_snapshot(path: String) -> void:
	super._load_snapshot(path)
	_invalidate_overlay_cache()
	_layers_dirty = true
	if color_id_map != null and color_id_map.is_ready:
		color_id_map.refresh_snapshot(snapshot, FACTION_COLORS)
		color_id_map.refresh_highlights(selected_province_id, legal_targets)
		map_debug.note_invalidation("snapshot_refresh")
		_sync_presentation_layers()


func _rebuild_legal_targets() -> void:
	super._rebuild_legal_targets()
	_invalidate_overlay_cache()
	_layers_dirty = true
	if color_id_map != null and color_id_map.is_ready:
		color_id_map.refresh_highlights(selected_province_id, legal_targets)
		map_debug.note_invalidation("highlight_refresh")
		_sync_presentation_layers()


func _open_color_id_map() -> void:
	var previous_ready: bool = color_id_map != null and bool(color_id_map.is_ready)
	_invalidate_overlay_cache()
	_ensure_presentation_layers()
	_open_operational_graph()
	if color_id_map.open(map_manifest_source_path, snapshot, FACTION_COLORS):
		color_id_map.refresh_highlights(selected_province_id, legal_targets)
		status_message = "Color-ID province renderer active (%s)." % map_manifest_source_path.get_file()
		fitted_once = false
		_layers_dirty = true
		_fit_complete_theatre()
		map_debug.note_invalidation("map_open")
		_sync_presentation_layers()
	else:
		# Keep a previously successful open; only fall back if nothing is ready.
		if previous_ready:
			status_message = "%s Kept previous color-ID map." % color_id_map.error
		else:
			status_message = "%s Marker fallback remains non-authoritative." % color_id_map.error
			if _bg_layer != null:
				_bg_layer.visible = false
			if _identity_layer != null:
				_identity_layer.visible = false
	queue_redraw()


func _open_operational_graph() -> void:
	var graph_path := operational_graph.resolve_path(map_manifest_source_path, snapshot)
	if graph_path.is_empty():
		operational_graph.clear()
		return
	if not operational_graph.open(graph_path):
		# Presentation-only; unresolved graph uses next legitimate location fallback.
		operational_graph.clear()


func _sync_map_space() -> void:
	if color_id_map == null or not color_id_map.is_ready:
		return
	map_space.configure(color_id_map.image_size(), _map_content_rect(), view_scale, view_offset)


func _draw() -> void:
	if not color_id_map.is_ready:
		if _bg_layer != null:
			_bg_layer.visible = false
		if _identity_layer != null:
			_identity_layer.visible = false
		super._draw()
		return
	if _bg_layer != null:
		_bg_layer.visible = true
	if _identity_layer != null:
		_identity_layer.visible = true
	# Capture rebuild counters BEFORE any end-of-frame clear so F3 can report them.
	if map_debug.enabled and color_id_map.has_method("get_perf_stats"):
		map_debug.capture_perf(color_id_map.get_perf_stats())
	_sync_presentation_layers()
	var viewport := get_viewport_rect().size
	var map_width := viewport.x - PANEL_WIDTH
	# Texture layers are separate CanvasItems. This node draws dynamic overlays + UI only.
	if show_coalition_fronts:
		_draw_coalition_fronts()
	if show_crossing_overlay:
		_draw_crossing_overlay()
	_draw_color_id_pending_battle()
	_draw_presentation_fixture_markers()
	_draw_color_id_overlays()
	if map_debug.enabled:
		map_debug.counter_bounds = _cached_reserved_rects.duplicate()
		map_debug.label_bounds = _cached_label_bounds.duplicate()
		map_debug.draw(
			self,
			map_space,
			color_id_map,
			selected_province_id,
			hovered_province_id,
			presentation_fixture,
			_overlay_clamp_rect()
		)
	if color_id_map.has_method("end_frame_stats"):
		color_id_map.end_frame_stats()

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
		int(snapshot.get("provinces", []).size()),
		color_id_map.background_status(),
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
	_draw_management_panel()


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
			_image_to_screen(color_id_map.anchor_pixel(left_id)),
			_image_to_screen(color_id_map.anchor_pixel(right_id)),
			Color(1.0, 0.76, 0.31, 0.35),
			1.0
		)


func _draw_crossing_overlay() -> void:
	# Debug topology: land / strait / ferry / sea-lane edges from manifest edge_types.
	var drawn: Dictionary = {}
	for province_id: Variant in color_id_map.row_by_province.keys():
		var pid := String(province_id)
		var row: Dictionary = color_id_map.row_by_province.get(pid, {})
		var edge_types: Dictionary = row.get("edge_types", {})
		if edge_types.is_empty():
			continue
		var origin := _image_to_screen(color_id_map.anchor_pixel(pid))
		for neighbor_id: Variant in edge_types.keys():
			var nid := String(neighbor_id)
			if not color_id_map.row_by_province.has(nid):
				continue
			var key := pid + "|" + nid if pid < nid else nid + "|" + pid
			if drawn.has(key):
				continue
			drawn[key] = true
			var etype := String(edge_types.get(nid, "land"))
			var target := _image_to_screen(color_id_map.anchor_pixel(nid))
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
	if color_id_map.row_by_province.has(origin_id):
		legacy_origin = color_id_map.anchor_pixel(origin_id)
	if color_id_map.row_by_province.has(target_id):
		legacy_target = color_id_map.anchor_pixel(target_id)
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


func _draw_color_id_overlays() -> void:
	# Pass 1: facilities + counters (always). Pass 2: priority label declutter.
	# Counters/labels are clamped inside the map viewport (header/footer safe).
	var overlay_bounds := _overlay_clamp_rect()
	var cache_key := "%s|%s|%s|%s|%s" % [
		selected_province_id,
		str(legal_targets.keys()),
		snappedf(view_scale, 0.001),
		snappedf(view_offset.x, 0.5),
		snappedf(view_offset.y, 0.5),
	]
	var rebuild := cache_key != _overlay_cache_key
	var label_candidates: Array = []
	var reserved: Array = []
	if rebuild:
		_overlay_cache_key = cache_key
		_cached_label_candidates.clear()
		_cached_reserved_rects.clear()

	for province: Dictionary in snapshot.get("provinces", []):
		var province_id := String(province.get("id", ""))
		if not color_id_map.row_by_province.has(province_id):
			continue
		var anchor := _image_to_screen(color_id_map.anchor_pixel(province_id))
		var position := _clamp_point_in_rect(anchor, overlay_bounds, OVERLAY_EDGE_PAD)
		var shifted := position.distance_to(anchor) > 0.5
		var battalion: Dictionary = battalions_by_province.get(province_id, {})
		var occupied := not battalion.is_empty()
		var selected := province_id == selected_province_id
		var target := legal_targets.has(province_id)
		var owner := String(province.get("owner", "neutral"))
		var faction_color: Color = FACTION_COLORS.get(owner, FACTION_COLORS["neutral"])
		var hovered := province_id == hovered_province_id

		if selected:
			MapMarkersScript.draw_selected_province_ring(self, position)
		elif hovered:
			MapMarkersScript.draw_hovered_province_ring(self, position)

		if shifted and (occupied or selected or target or hovered):
			draw_line(anchor, position, Color(0.85, 0.9, 0.95, 0.55), 1.0)
			draw_circle(anchor, 2.0, Color(0.85, 0.9, 0.95, 0.7))

		var infrastructure: Dictionary = province.get("infrastructure", {})
		if int(infrastructure.get("supply_hub", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-13, 12), Vector2(6, 6)), Color("63d69f"))
		if int(infrastructure.get("command_post", 0)) > 0:
			draw_rect(Rect2(position + Vector2(-4, 12), Vector2(6, 6)), Color("b892ff"))
		if int(infrastructure.get("air_base", 0)) > 0:
			draw_circle(position + Vector2(8, 15), 3.2, Color("7fe7ff"))

		if occupied:
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
				int(battalion.get("encircled_turns", 0)) > 0
			)
			reserved.append(counter_rect)
			var stack: Array = battalion_stacks_by_province.get(province_id, [])
			if stack.size() > 1:
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
		elif occupied:
			priority = 70
		elif named and view_scale >= 2.4:
			priority = 40
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
		draw_string(
			ThemeDB.fallback_font,
			candidate.get("pos", Vector2.ZERO),
			String(candidate.get("label", "")),
			HORIZONTAL_ALIGNMENT_LEFT,
			-1,
			int(candidate.get("font_size", 11)),
			candidate.get("color", Color.WHITE)
		)
	# Hover label is cheap and not cached into selection layout.
	if not hovered_province_id.is_empty() and color_id_map.row_by_province.has(hovered_province_id):
		var hprov: Dictionary = provinces_by_id.get(hovered_province_id, {})
		if not hprov.is_empty():
			var hlabel := _province_label(hprov, hovered_province_id)
			var hpos := _image_to_screen(color_id_map.anchor_pixel(hovered_province_id)) + Vector2(13, -9)
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
	if not color_id_map.is_ready:
		return super._province_at(screen_position)
	_sync_map_space()
	var rect := map_space.texture_rect()
	if not rect.has_point(screen_position):
		return ""
	var pixel := map_space.screen_to_pixel(screen_position)
	var size := color_id_map.image_size()
	pixel = Vector2i(
		clampi(pixel.x, 0, int(size.x) - 1),
		clampi(pixel.y, 0, int(size.y) - 1)
	)
	return color_id_map.province_at_pixel(pixel)


func _map_to_screen(province: Dictionary) -> Vector2:
	if color_id_map != null and color_id_map.is_ready:
		return _image_to_screen(color_id_map.anchor_pixel(String(province.get("id", ""))))
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
	if not _is_named_province(label) and color_id_map != null and color_id_map.row_by_province.has(province_id):
		var row: Dictionary = color_id_map.row_by_province[province_id]
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
	if event is InputEventMouseMotion and color_id_map != null and color_id_map.is_ready:
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
	if color_id_map == null or not color_id_map.is_ready:
		view_scale = HOME_FIT_FILL
		view_offset = Vector2.ZERO
		fitted_once = true
		status_message = "Fitted full theatre."
		queue_redraw()
		return
	# Fill more of the map panel while keeping aspect ratio; panel stays clear.
	view_scale = HOME_FIT_FILL
	view_offset = Vector2.ZERO
	fitted_once = true
	var map_contract: Dictionary = snapshot.get("strategic_map", {})
	status_message = "Fitted complete theatre (%s provinces). Home=full  F=front." % [
		int(snapshot.get("provinces", []).size())
	]
	if not String(map_contract.get("map_id", "")).is_empty():
		status_message = "Fitted complete theatre map %s (%s provinces)." % [
			String(map_contract.get("map_id", "")),
			int(snapshot.get("provinces", []).size()),
		]
	queue_redraw()


func _fit_to_focus(force: bool) -> void:
	if color_id_map == null or not color_id_map.is_ready:
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
		if province_id.is_empty() or not color_id_map.row_by_province.has(province_id):
			continue
		var anchor := color_id_map.anchor_pixel(province_id)
		min_x = minf(min_x, anchor.x)
		max_x = maxf(max_x, anchor.x)
		min_y = minf(min_y, anchor.y)
		max_y = maxf(max_y, anchor.y)
		count += 1
	if count < 4:
		_fit_complete_theatre()
		status_message = "Fit Front had <4 nodes; fell back to complete theatre."
		return
	var image_size := color_id_map.image_size()
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
