extends SceneTree

## #212 E1 behavioral gate for the real main.tscn integration.
##
## Proves default launch stays on visible polygon presentation, then explicitly
## opts into the hybrid candidate and verifies PolygonMap authority/picking stays
## live while presentation moves wide-1x -> lazy-2x -> safe snapshot refresh ->
## polygon fallback. It also covers disabled -> reload -> re-enable so a hidden
## cache can never be resurrected across snapshot generations.

const SNAPSHOT := "res://fixtures/snapshots/earth3_theatre.json"
const FIXTURE := "res://fixtures/presentation/e3_operational.json"
const MANIFEST := "res://assets/maps/earth3_europe_mediterranean/map_manifest.json"
const ENV_KEY := "GOCX_PRESENTATION_CANDIDATE"
const WAIT_FRAMES := 240


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	for path_value in [SNAPSHOT, FIXTURE, MANIFEST]:
		if not FileAccess.file_exists(String(path_value)):
			_fail("required candidate-test input missing: %s" % String(path_value))
			return
	var authority_before := _authority_hashes()
	DisplayServer.window_set_size(Vector2i(1280, 720))
	if root is Window:
		(root as Window).size = Vector2i(1280, 720)
		(root as Window).mode = Window.MODE_WINDOWED

	OS.set_environment(ENV_KEY, "")
	var default_scene := await _build_main_scene()
	if default_scene == null:
		return
	var default_state: Dictionary = default_scene.call("presentation_candidate_debug_state")
	if bool(default_state.get("requested", true)) or bool(default_state.get("active", true)):
		_fail("default launch unexpectedly requested/activated candidate: %s" % JSON.stringify(default_state))
		return
	if default_scene.find_child("Issue212HybridRasterCandidate", true, false) != null:
		_fail("default launch mounted candidate node")
		return
	var default_root := default_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if default_root == null or not default_root.visible:
		_fail("default launch must keep Earth3PolygonRoot visible")
		return
	var default_pick := _authority_pick(default_scene)
	if not bool(default_pick.get("ok", false)):
		_fail("default authority pick failed: %s" % JSON.stringify(default_pick))
		return
	await _dispose(default_scene)

	OS.set_environment(ENV_KEY, "hybrid")
	var candidate_scene := await _build_main_scene()
	if candidate_scene == null:
		return
	if not await _wait_active(candidate_scene, "initial activation"):
		return
	var wide_state: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	var wide: Dictionary = wide_state.get("candidate", {})
	if not bool(wide_state.get("authority_backend_polygon", false)):
		_fail("candidate disabled polygon authority backend")
		return
	if String(wide.get("mode", "")) != "wide_1x":
		_fail("candidate initial mode must be wide_1x: %s" % JSON.stringify(wide))
		return
	if int(wide.get("total_tiles", 0)) != 63:
		_fail("candidate expected 63 lazy descriptors: %s" % JSON.stringify(wide))
		return
	if int(wide.get("resident_tiles", -1)) != 0:
		_fail("wide mode must not retain 2x lazy tiles: %s" % JSON.stringify(wide))
		return
	if int(wide.get("wide_rgba8_bytes", 0)) <= 0:
		_fail("wide mode did not materialize 1x texture")
		return
	var candidate_root := candidate_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if candidate_root == null or candidate_root.visible:
		_fail("candidate active path must shadow, not remove, Earth3PolygonRoot")
		return
	var active_pick := _authority_pick(candidate_scene)
	if active_pick != default_pick:
		_fail("candidate changed authority pick identity default=%s candidate=%s" % [JSON.stringify(default_pick), JSON.stringify(active_pick)])
		return

	candidate_scene.view_scale = 3.0
	if candidate_scene.get("_layers_dirty") != null:
		candidate_scene._layers_dirty = true
	if candidate_scene.has_method("_sync_presentation_layers"):
		candidate_scene.call("_sync_presentation_layers")
	for _i in range(8):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	var lazy_state: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	var lazy: Dictionary = lazy_state.get("candidate", {})
	if String(lazy.get("mode", "")) != "lazy_2x_1024":
		_fail("zoomed candidate did not enter lazy mode: %s" % JSON.stringify(lazy))
		return
	var resident := int(lazy.get("resident_tiles", 0))
	var total := int(lazy.get("total_tiles", 0))
	if resident <= 0 or resident >= total:
		_fail("zoomed lazy mode must materialize a strict subset of tiles resident=%s total=%s" % [resident, total])
		return
	if _authority_pick(candidate_scene) != default_pick:
		_fail("lazy zoom changed authority pick identity")
		return

	# Active reload: stale presentation must disappear synchronously and rebuild.
	candidate_scene.call("_load_snapshot", SNAPSHOT)
	var refresh_transition: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	candidate_root = candidate_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if bool(refresh_transition.get("active", true)):
		_fail("snapshot reload left stale candidate active: %s" % JSON.stringify(refresh_transition))
		return
	if String(refresh_transition.get("status", "")) != "refresh_pending":
		_fail("snapshot reload did not enter refresh_pending: %s" % JSON.stringify(refresh_transition))
		return
	if bool(refresh_transition.get("cache_present", true)):
		_fail("snapshot reload retained stale cache bytes: %s" % JSON.stringify(refresh_transition))
		return
	if candidate_root == null or not candidate_root.visible:
		_fail("snapshot reload did not immediately restore polygon presentation")
		return
	if _authority_pick(candidate_scene) != default_pick:
		_fail("snapshot reload transition changed authority pick identity")
		return
	if not await _wait_active(candidate_scene, "snapshot refresh"):
		return
	var refresh_state: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	candidate_root = candidate_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if candidate_root == null or candidate_root.visible:
		_fail("refreshed candidate did not re-shadow polygon presentation")
		return
	if not bool(refresh_state.get("cache_present", false)):
		_fail("refreshed candidate did not own a fresh cache")
		return
	if candidate_scene.find_children("Issue212HybridRasterCandidate", "Node2D", true, false).size() != 1:
		_fail("snapshot refresh duplicated candidate nodes")
		return
	if _authority_pick(candidate_scene) != default_pick:
		_fail("refreshed candidate changed authority pick identity")
		return

	candidate_scene.call("set_presentation_candidate_enabled", false)
	await process_frame
	var fallback_state: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	if bool(fallback_state.get("active", true)) or bool(fallback_state.get("enabled_intent", true)):
		_fail("manual fallback did not disable candidate intent: %s" % JSON.stringify(fallback_state))
		return
	candidate_root = candidate_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if candidate_root == null or not candidate_root.visible:
		_fail("manual fallback did not restore polygon presentation")
		return
	if _authority_pick(candidate_scene) != default_pick:
		_fail("manual fallback changed authority pick identity")
		return

	# Regression: a cache hidden by manual fallback must still be invalidated by a
	# later snapshot load. Re-enable must build a new candidate, never revive it.
	candidate_scene.call("_load_snapshot", SNAPSHOT)
	await process_frame
	var disabled_reload_state: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	if bool(disabled_reload_state.get("active", true)) \
	or bool(disabled_reload_state.get("enabled_intent", true)) \
	or bool(disabled_reload_state.get("cache_present", true)):
		_fail("disabled snapshot reload retained stale candidate state: %s" % JSON.stringify(disabled_reload_state))
		return
	if candidate_scene.find_child("Issue212HybridRasterCandidate", true, false) != null:
		_fail("disabled snapshot reload retained candidate node")
		return
	candidate_root = candidate_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if candidate_root == null or not candidate_root.visible:
		_fail("disabled snapshot reload did not keep polygons visible")
		return
	candidate_scene.call("set_presentation_candidate_enabled", true)
	if not await _wait_active(candidate_scene, "re-enable after disabled reload"):
		return
	var reenabled_state: Dictionary = candidate_scene.call("presentation_candidate_debug_state")
	if not bool(reenabled_state.get("cache_present", false)) or not bool(reenabled_state.get("enabled_intent", false)):
		_fail("re-enable did not build a fresh candidate: %s" % JSON.stringify(reenabled_state))
		return
	candidate_root = candidate_scene.get_node_or_null("Earth3PolygonRoot") as Node2D
	if candidate_root == null or candidate_root.visible:
		_fail("re-enabled candidate did not shadow polygon presentation")
		return
	if _authority_pick(candidate_scene) != default_pick:
		_fail("re-enabled candidate changed authority pick identity")
		return

	var authority_after := _authority_hashes()
	if authority_after != authority_before:
		_fail("candidate test changed authority bytes")
		return
	print("ISSUE212_PRESENTATION_CANDIDATE_TEST %s" % JSON.stringify({
		"default": default_state,
		"wide": wide,
		"lazy": lazy,
		"refresh_transition": refresh_transition,
		"refresh": refresh_state,
		"fallback": fallback_state,
		"disabled_reload": disabled_reload_state,
		"reenabled": reenabled_state,
		"authority_pick": default_pick,
	}))
	print("map_presentation_candidate_test: PASS")
	await _dispose(candidate_scene)
	OS.set_environment(ENV_KEY, "")
	quit(0)


func _wait_active(scene: Node, label: String) -> bool:
	for _i in range(WAIT_FRAMES):
		var state: Dictionary = scene.call("presentation_candidate_debug_state")
		if bool(state.get("active", false)):
			return true
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	_fail("candidate did not activate during %s: %s" % [label, JSON.stringify(scene.call("presentation_candidate_debug_state"))])
	return false


func _build_main_scene() -> Node:
	var packed := load("res://main.tscn") as PackedScene
	if packed == null:
		_fail("failed to load main.tscn")
		return null
	var scene := packed.instantiate()
	if scene == null:
		_fail("failed to instantiate main.tscn")
		return null
	if scene.get("snapshot_source_path") != null:
		scene.snapshot_source_path = SNAPSHOT
	if scene.get("presentation_fixture_path") != null:
		scene.presentation_fixture_path = FIXTURE
	if scene.get("map_manifest_source_path") != null:
		scene.map_manifest_source_path = MANIFEST
	root.add_child(scene)
	for _i in range(12):
		RenderingServer.force_draw(false, 0.0)
		await process_frame
	if not bool(scene.get("map_backend_is_polygon")):
		_fail("main scene did not open PolygonMap authority")
		return null
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready) or int(pmap.province_count) != 3514:
		_fail("main scene PolygonMap authority not ready/3514")
		return null
	return scene


func _authority_pick(scene: Node) -> Dictionary:
	var pmap = scene.get("polygon_map")
	if pmap == null or not bool(pmap.is_ready):
		return {"ok": false, "error": "polygon map unavailable"}
	var index := -1
	for i in range(int(pmap.province_count)):
		if int(pmap.is_water[i]) == 0:
			index = i
			break
	if index < 0:
		return {"ok": false, "error": "no land province"}
	var expected := String(pmap.province_by_index[index])
	var actual := String(pmap.province_at_image_pos(pmap.centroids[index]))
	return {
		"ok": expected == actual and not expected.is_empty(),
		"expected": expected,
		"actual": actual,
		"province_count": int(pmap.province_count),
	}


func _authority_hashes() -> Dictionary:
	var dataset_path := ""
	var file := FileAccess.open(MANIFEST, FileAccess.READ)
	if file != null:
		var parsed: Variant = JSON.parse_string(file.get_as_text())
		if parsed is Dictionary:
			var polygon_value: Variant = (parsed as Dictionary).get("polygon_dataset", {})
			if polygon_value is Dictionary:
				var rel := String((polygon_value as Dictionary).get("path", "polygon_dataset.json"))
				dataset_path = MANIFEST.get_base_dir().path_join(rel)
	return {
		"manifest_sha256": FileAccess.get_sha256(MANIFEST),
		"polygon_dataset_sha256": FileAccess.get_sha256(dataset_path) if not dataset_path.is_empty() else "",
		"snapshot_sha256": FileAccess.get_sha256(SNAPSHOT),
	}


func _dispose(scene: Node) -> void:
	if scene != null and is_instance_valid(scene):
		scene.queue_free()
	await process_frame
	await process_frame


func _fail(message: String) -> void:
	push_error("map_presentation_candidate_test: %s" % message)
	OS.set_environment(ENV_KEY, "")
	quit(1)
