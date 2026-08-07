extends SceneTree

## CI gate: Earth3 operational snapshot/fixture references only valid e3_* IDs
## present in the production polygon dataset. Fails on any GoE IDs.

const DATASET := "res://assets/maps/earth3_europe_mediterranean/polygon_dataset.json"
const SNAPSHOT := "res://fixtures/snapshots/earth3_operational.json"
const FIXTURE := "res://fixtures/presentation/e3_operational.json"
const EXPECT_COUNT := 3514


func _initialize() -> void:
	call_deferred("_run")


func _run() -> void:
	var ds := _load_json(DATASET)
	if ds.is_empty():
		_fail("dataset missing/invalid: %s" % DATASET)
		return
	var count := int(ds.get("province_count", 0))
	if count != EXPECT_COUNT:
		_fail("dataset province_count expected %s got %s" % [EXPECT_COUNT, count])
		return
	var valid: Dictionary = {}
	for row: Variant in ds.get("provinces", []):
		if row is Dictionary:
			var pid := String((row as Dictionary).get("id", ""))
			if pid.begins_with("e3_"):
				valid[pid] = true
	if valid.size() != EXPECT_COUNT:
		_fail("dataset e3 id table size %s != %s" % [valid.size(), EXPECT_COUNT])
		return

	var snap := _load_json(SNAPSHOT)
	if snap.is_empty():
		_fail("snapshot missing: %s" % SNAPSHOT)
		return
	var fix := _load_json(FIXTURE)
	if fix.is_empty():
		_fail("fixture missing: %s" % FIXTURE)
		return

	var refs: Array = []
	_collect_ids(snap, refs)
	_collect_ids(fix, refs)
	var missing: Array = []
	var goe: Array = []
	var seen: Dictionary = {}
	for r in refs:
		var id := String(r)
		if id.is_empty() or seen.has(id):
			continue
		seen[id] = true
		if not id.begins_with("e3_"):
			# Allow non-province ids (formation/battalion/route ids).
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

	# Structural requirements
	var bats: Array = snap.get("battalions", [])
	var forms: Array = snap.get("formations", [])
	var edges: Array = snap.get("edges", [])
	var fronts: Array = snap.get("front_options", [])
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
			factions[String((b as Dictionary).get("faction", ""))] = true
	if factions.size() < 2:
		_fail("need opposing factions among battalions")
		return

	print(
		"earth3_fixture_validate: PASS dataset=%s snap_provinces=%s refs=%s formations=%s edges=%s"
		% [count, int(snap.get("provinces", []).size()), seen.size(), forms.size(), edges.size()]
	)
	quit(0)


func _looks_like_province_id(id: String) -> bool:
	if id.begins_with("e3_"):
		return true
	if id.begins_with("bat-") or id.begins_with("form-") or id.begins_with("site-"):
		return false
	if id.begins_with("e3-") or id.begins_with("presentation_") or id.begins_with("fixture"):
		return false
	if id.find("-") >= 0 or id.find("_") >= 0:
		# formation-like
		if id.begins_with("ru-") or id.begins_with("proof-"):
			return false
	# Capitalized GoE names like Baden/Franken
	if id.length() >= 3 and id[0] == id[0].to_upper() and not id.begins_with("NATO"):
		var lower := id.to_lower()
		if lower != id and not id.begins_with("e3"):
			return true
	return false


func _collect_ids(node: Variant, out: Array) -> void:
	if node is Dictionary:
		var d := node as Dictionary
		for k in d.keys():
			var ks := String(k)
			var v: Variant = d[k]
			if ks.ends_with("province_id") or ks == "origin" or ks == "target" or ks == "origin_province_id" or ks == "target_province_id":
				out.append(String(v))
			elif ks == "province_ids" and v is Array:
				for item in v:
					out.append(String(item))
			else:
				_collect_ids(v, out)
	elif node is Array:
		for item2 in node:
			# edge pairs
			if item2 is Array and (item2 as Array).size() == 2:
				var a := String((item2 as Array)[0])
				var b := String((item2 as Array)[1])
				if a.begins_with("e3_") or b.begins_with("e3_"):
					out.append(a)
					out.append(b)
					continue
			_collect_ids(item2, out)


func _load_json(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var parsed: Variant = JSON.parse_string(f.get_as_text())
	if parsed is Dictionary:
		return parsed
	return {}


func _fail(msg: String) -> void:
	push_error("earth3_fixture_validate FAIL: %s" % msg)
	print("earth3_fixture_validate: FAIL %s" % msg)
	quit(1)
