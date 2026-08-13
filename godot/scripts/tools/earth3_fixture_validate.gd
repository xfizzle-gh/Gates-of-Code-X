extends SceneTree

## CI gate: Earth3 operational snapshot/fixture references only valid e3_* IDs
## present in the production polygon dataset. Fails on any GoE IDs.

const DATASET := "res://assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
const SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const FIXTURE := "res://fixtures/presentation/e3_operational.json"
const EXPECT_COUNT := 3514

var _failed := false
var _dataset_path := DATASET
var _snapshot_path := SNAPSHOT
var _fixture_path := FIXTURE


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	_parse_args()
	var ds := _load_json(_dataset_path)
	if _failed:
		return
	if ds.is_empty():
		_fail("dataset missing/invalid: %s" % _dataset_path)
		return
	var count := int(ds.get("province_count", 0))
	if count != EXPECT_COUNT:
		_fail("dataset province_count expected %s got %s" % [EXPECT_COUNT, count])
		return
	var valid: Dictionary = {}
	for row: Variant in _require_array(ds, "provinces"):
		if _failed:
			return
		if row is Dictionary:
			var pid := _as_id((row as Dictionary).get("id", ""), "dataset.provinces.id")
			if _failed:
				return
			if pid.begins_with("e3_"):
				valid[pid] = true
	if valid.size() != EXPECT_COUNT:
		_fail("dataset e3 id table size %s != %s" % [valid.size(), EXPECT_COUNT])
		return

	var snap := _load_json(_snapshot_path)
	if _failed:
		return
	if snap.is_empty():
		_fail("snapshot missing: %s" % _snapshot_path)
		return
	var fix := _load_json(_fixture_path)
	if _failed:
		return
	if fix.is_empty():
		_fail("fixture missing: %s" % _fixture_path)
		return

	var refs: Array = []
	_collect_ids(snap, refs)
	if _failed:
		return
	_collect_ids(fix, refs)
	if _failed:
		return
	var missing: Array = []
	var goe: Array = []
	var seen: Dictionary = {}
	for r in refs:
		if not (r is String):
			_fail("collector emitted non-string ref")
			return
		var id := r as String
		if id.is_empty() or seen.has(id):
			continue
		seen[id] = true
		if not id.begins_with("e3_"):
			if _looks_like_province_id(id):
				goe.append(id)
			continue
		if not valid.has(id):
			missing.append(id)

	if not goe.is_empty():
		_fail("GoE/non-e3 province ids in Earth3 fixture/snapshot: %s" % str(goe))
		return
	if not missing.is_empty():
		_fail("missing e3 province ids: %s" % str(missing))
		return

	var bats: Array = _require_array(snap, "battalions")
	var forms: Array = _require_array(snap, "formations")
	var edges: Array = _require_array(snap, "edges")
	var fronts: Array = _require_array(snap, "front_options")
	if _failed:
		return
	var pending: Variant = snap.get("pending_battle", null)
	if bats.size() < 2:
		_fail("need >=2 battalions")
		return
	if forms.size() < 2:
		_fail("need >=2 formations")
		return
	if edges.is_empty():
		_fail("need authored edges")
		return
	if fronts.is_empty():
		_fail("need legal front_options/targets")
		return
	if not (pending is Dictionary):
		_fail("need pending_battle")
		return
	var pb := pending as Dictionary
	for k in ["origin_province_id", "target_province_id", "encounter_kind", "goh_handoff"]:
		if not pb.has(k):
			_fail("pending_battle missing %s" % k)
			return
	var handoff: Variant = pb.get("goh_handoff")
	if not (handoff is Dictionary) or not bool((handoff as Dictionary).get("enabled", false)):
		_fail("goh_handoff.enabled required")
		return
	var factions: Dictionary = {}
	for b: Variant in bats:
		if b is Dictionary:
			var faction := _as_id((b as Dictionary).get("faction", ""), "battalions.faction")
			if _failed:
				return
			if not faction.is_empty():
				factions[faction] = true
	if factions.size() < 2:
		_fail("need opposing factions among battalions")
		return
	if _failed:
		return

	print(
		"earth3_fixture_validate: PASS dataset=%s snap_provinces=%s refs=%s formations=%s edges=%s"
		% [count, _require_array(snap, "provinces").size(), seen.size(), forms.size(), edges.size()]
	)
	quit(0)


func _parse_args() -> void:
	for raw in OS.get_cmdline_user_args():
		var text := raw as String
		if text.begins_with("--dataset="):
			_dataset_path = text.substr(String("--dataset=").length()).strip_edges()
		elif text.begins_with("--snapshot="):
			_snapshot_path = text.substr(String("--snapshot=").length()).strip_edges()
		elif text.begins_with("--fixture="):
			_fixture_path = text.substr(String("--fixture=").length()).strip_edges()


func _looks_like_province_id(id: String) -> bool:
	if id.begins_with("e3_"):
		return true
	if id.begins_with("bat-") or id.begins_with("form-") or id.begins_with("site-"):
		return false
	if id.begins_with("e3-") or id.begins_with("presentation_") or id.begins_with("fixture"):
		return false
	if id.find("-") >= 0 or id.find("_") >= 0:
		if id.begins_with("ru-") or id.begins_with("proof-"):
			return false
	if id.length() >= 3 and id[0] == id[0].to_upper() and not id.begins_with("NATO"):
		var lower := id.to_lower()
		if lower != id and not id.begins_with("e3"):
			return true
	return false


func _collect_ids(node: Variant, out: Array) -> void:
	if _failed:
		return
	if node is Dictionary:
		var d := node as Dictionary
		for k in d.keys():
			var ks := _as_key(k)
			if _failed:
				return
			var v: Variant = d[k]
			if (
				ks.ends_with("province_id")
				or ks == "origin"
				or ks == "target"
				or ks == "origin_province_id"
				or ks == "target_province_id"
			):
				out.append(_as_id(v, ks))
				if _failed:
					return
			elif ks == "province_ids" and v is Array:
				for item in v:
					out.append(_as_id(item, ks))
					if _failed:
						return
			else:
				_collect_ids(v, out)
				if _failed:
					return
	elif node is Array:
		for item2 in node:
			if item2 is Array and (item2 as Array).size() == 2:
				var pair := item2 as Array
				var left: Variant = pair[0]
				var right: Variant = pair[1]
				if left is String and right is String:
					out.append(left as String)
					out.append(right as String)
					continue
				if _is_number(left) and _is_number(right):
					continue
				if left is Dictionary or left is Array or right is Dictionary or right is Array:
					_collect_ids(left, out)
					if _failed:
						return
					_collect_ids(right, out)
					if _failed:
						return
					continue
				_fail(
					"malformed 2-tuple reference (expected string IDs or numeric pixels), types=%s/%s"
					% [_type_name(left), _type_name(right)]
				)
				return
			_collect_ids(item2, out)
			if _failed:
				return


func _as_key(value: Variant) -> String:
	if value is String:
		return value as String
	_fail("non-string dictionary key type=%s" % _type_name(value))
	return ""


func _as_id(value: Variant, context: String) -> String:
	if value is String:
		return value as String
	if value == null:
		_fail("null identifier at %s" % context)
		return ""
	_fail("non-string identifier at %s (type=%s)" % [context, _type_name(value)])
	return ""


func _is_number(value: Variant) -> bool:
	return value is int or value is float


func _type_name(value: Variant) -> String:
	if value == null:
		return "null"
	return type_string(typeof(value))


func _require_array(container: Dictionary, key: String) -> Array:
	var value: Variant = container.get(key, null)
	if not (value is Array):
		_fail("%s must be an array" % key)
		return []
	return value


func _load_json(path: String) -> Dictionary:
	if path.is_empty() or not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var parsed: Variant = JSON.parse_string(f.get_as_text())
	if parsed is Dictionary:
		return parsed
	return {}


func _fail(msg: String) -> void:
	_failed = true
	push_error("earth3_fixture_validate FAIL: %s" % msg)
	print("earth3_fixture_validate: FAIL %s" % msg)
	quit(1)
