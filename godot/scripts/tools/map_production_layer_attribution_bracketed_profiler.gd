extends "res://scripts/tools/map_production_layer_attribution_profiler.gd"

## #212 Phase A corrected experimental control.
##
## The original checkpoint measured one process-first baseline and then every
## disabled layer in sequence. This wrapper preserves its scene construction,
## suppression, picking, and metric code, but replaces the experiment schedule
## with a local bracket for every probe:
##
## baseline_before -> layer_disabled -> baseline_after
##
## Each sample is still a fresh main scene. The surrounding baselines remain in
## the same Godot process as the disabled sample, so resource/font/renderer cache
## drift is measured rather than silently folded into the layer delta.

const MAX_BASELINE_DRIFT_RATIO := 0.15
const BRACKETED_PROBES := [
	"land_fill",
	"ocean_mesh",
	"shared_borders",
	"secondary_outlines",
	"labels",
	"formation_counters",
	"infrastructure_sites",
	"routes",
	"contact_battle",
	"fixture_debug_overlays",
	"ui_only_floor",
]


func _run() -> void:
	DisplayServer.window_set_size(Vector2i(_width, _height))
	if root is Window:
		(root as Window).size = Vector2i(_width, _height)
		(root as Window).mode = Window.MODE_WINDOWED
		(root as Window).content_scale_size = Vector2i(_width, _height)

	for required_path in [_snapshot_path, _fixture_path, _manifest_path]:
		if not FileAccess.file_exists(String(required_path)):
			_fail("required fixture missing: %s" % String(required_path))
			return

	# Consume process-first-use work before any recorded bracket.
	var process_warmup := await _measure_fresh_mode("baseline")
	if not bool(process_warmup.get("ok", false)):
		_fail("process warmup failed: %s" % process_warmup.get("error", "unknown"))
		return
	var baseline_picks: Array = process_warmup.get("picking", [])
	var node_inventory: Dictionary = process_warmup.get("map_nodes", {})

	var brackets: Dictionary = {}
	var deltas: Dictionary = {}
	for probe_variant in BRACKETED_PROBES:
		var probe := String(probe_variant)
		var before := await _measure_fresh_mode("baseline")
		var disabled := await _measure_fresh_mode(probe)
		var after := await _measure_fresh_mode("baseline")
		for sample in [before, disabled, after]:
			if not bool(sample.get("ok", false)):
				_fail("probe failed: %s detail=%s" % [probe, sample.get("error", "unknown")])
				return
			if sample.get("picking", []) != baseline_picks:
				_fail("probe changed deterministic picking: %s" % probe)
				return

		var before_metrics: Dictionary = before.get("metrics", {})
		var disabled_metrics: Dictionary = disabled.get("metrics", {})
		var after_metrics: Dictionary = after.get("metrics", {})
		var drift := _baseline_drift(before_metrics, after_metrics)
		var drift_error := _drift_gate_error(probe, drift)
		if not drift_error.is_empty():
			_fail(drift_error)
			return
		var local_baseline := _midpoint_metrics(before_metrics, after_metrics)
		var delta := _delta_from_local_baseline(local_baseline, disabled_metrics)
		brackets[probe] = {
			"baseline_before": before_metrics,
			"disabled": disabled_metrics,
			"baseline_after": after_metrics,
			"local_baseline": local_baseline,
			"baseline_drift": drift,
			"delta": delta,
		}
		if probe != "ui_only_floor":
			deltas[probe] = delta
		print("map_production_layer_attribution_bracketed: probe=%s drift50=%s drift95=%s delta50=%s" % [
			probe,
			drift.frame_ms_p50_ratio,
			drift.frame_ms_p95_ratio,
			delta.frame_ms_p50,
		])

	var result := {
		"ok": true,
		"schema": "gates-of-codex.issue-212-production-layer-attribution",
		"schema_version": 2,
		"issue": 212,
		"viewport": {"width": _width, "height": _height},
		"frames": _frames,
		"control": {
			"design": "baseline_before -> layer_disabled -> baseline_after",
			"max_baseline_drift_ratio": MAX_BASELINE_DRIFT_RATIO,
			"local_baseline": "arithmetic midpoint of surrounding baseline statistics",
			"process_warmup_recorded": true,
		},
		"map": {
			"map_id": "earth3_europe_mediterranean",
			"renderer": "polygon_mesh",
			"province_count": 3514,
			"nodes": node_inventory,
		},
		"picking": {
			"parity": true,
			"baseline": baseline_picks,
		},
		"process_warmup": process_warmup.get("metrics", {}),
		"brackets": brackets,
		"disabled_layer_deltas": deltas,
		"notes": [
			"All samples run with MapDebug disabled.",
			"Every baseline and disabled sample uses a fresh main scene and the same camera/fixtures.",
			"Each probe is bracketed by local before/after baselines inside the same Godot process.",
			"A bracket fails if baseline p50 or p95 wall-frame drift exceeds 15%, or if baseline draw calls/primitives change.",
			"Frame-time, draw-call and primitive deltas use the midpoint of the two local baselines, not a single process-first baseline.",
			"Categories are presentation probes, not additive accounting buckets; some fixture content intentionally overlaps semantic layers.",
			"ui_only_floor is a residual floor and is not included in one-layer deltas.",
			"Absolute CI frame times are llvmpipe measurements and are not owner-native acceptance metrics.",
		],
	}
	_write_json(_out_path, result)
	print("ISSUE212_PRODUCTION_ATTRIBUTION %s" % JSON.stringify(result))
	print("map_production_layer_attribution_profiler: PASS out=%s" % _out_path)
	quit(0)


func _midpoint_metrics(before: Dictionary, after: Dictionary) -> Dictionary:
	var out: Dictionary = {}
	for metric_name in [
		"frame_time_ms",
		"script_cpu_ms",
		"draw_calls",
		"primitives",
		"node_count",
		"object_count",
		"texture_mem_bytes",
		"video_mem_bytes",
	]:
		out[metric_name] = _midpoint_stats(before.get(metric_name, {}), after.get(metric_name, {}))
	return out


func _midpoint_stats(before: Dictionary, after: Dictionary) -> Dictionary:
	return {
		"count": mini(int(before.get("count", 0)), int(after.get("count", 0))),
		"avg": _midpoint(float(before.get("avg", 0.0)), float(after.get("avg", 0.0))),
		"p50": _midpoint(float(before.get("p50", 0.0)), float(after.get("p50", 0.0))),
		"p95": _midpoint(float(before.get("p95", 0.0)), float(after.get("p95", 0.0))),
		"max": _midpoint(float(before.get("max", 0.0)), float(after.get("max", 0.0))),
		"min": _midpoint(float(before.get("min", 0.0)), float(after.get("min", 0.0))),
	}


func _baseline_drift(before: Dictionary, after: Dictionary) -> Dictionary:
	var frame_before: Dictionary = before.get("frame_time_ms", {})
	var frame_after: Dictionary = after.get("frame_time_ms", {})
	return {
		"frame_ms_p50_abs": _abs_delta(frame_before, frame_after, "p50"),
		"frame_ms_p50_ratio": _relative_drift(frame_before, frame_after, "p50"),
		"frame_ms_p95_abs": _abs_delta(frame_before, frame_after, "p95"),
		"frame_ms_p95_ratio": _relative_drift(frame_before, frame_after, "p95"),
		"draw_calls_p50_abs": absi(int(after.get("draw_calls", {}).get("p50", 0)) - int(before.get("draw_calls", {}).get("p50", 0))),
		"primitives_p50_abs": absi(int(after.get("primitives", {}).get("p50", 0)) - int(before.get("primitives", {}).get("p50", 0))),
	}


func _drift_gate_error(probe: String, drift: Dictionary) -> String:
	if int(drift.get("draw_calls_p50_abs", 0)) != 0:
		return "baseline draw-call drift in %s: %s" % [probe, drift]
	if int(drift.get("primitives_p50_abs", 0)) != 0:
		return "baseline primitive drift in %s: %s" % [probe, drift]
	if float(drift.get("frame_ms_p50_ratio", 0.0)) > MAX_BASELINE_DRIFT_RATIO:
		return "baseline p50 frame drift exceeds %.1f%% in %s: %s" % [MAX_BASELINE_DRIFT_RATIO * 100.0, probe, drift]
	if float(drift.get("frame_ms_p95_ratio", 0.0)) > MAX_BASELINE_DRIFT_RATIO:
		return "baseline p95 frame drift exceeds %.1f%% in %s: %s" % [MAX_BASELINE_DRIFT_RATIO * 100.0, probe, drift]
	return ""


func _delta_from_local_baseline(local: Dictionary, disabled: Dictionary) -> Dictionary:
	return {
		"draw_calls_p50": _metric_delta(local, disabled, "draw_calls", "p50"),
		"draw_calls_p95": _metric_delta(local, disabled, "draw_calls", "p95"),
		"primitives_p50": _metric_delta(local, disabled, "primitives", "p50"),
		"frame_ms_p50": _metric_delta(local, disabled, "frame_time_ms", "p50"),
		"frame_ms_p95": _metric_delta(local, disabled, "frame_time_ms", "p95"),
		"script_cpu_ms_p50": _metric_delta(local, disabled, "script_cpu_ms", "p50"),
		"video_mem_bytes_p50": _metric_delta(local, disabled, "video_mem_bytes", "p50"),
	}


func _metric_delta(local: Dictionary, disabled: Dictionary, metric_name: String, stat_name: String) -> float:
	return snappedf(
		float(local.get(metric_name, {}).get(stat_name, 0.0)) - float(disabled.get(metric_name, {}).get(stat_name, 0.0)),
		0.001
	)


func _abs_delta(before: Dictionary, after: Dictionary, stat_name: String) -> float:
	return snappedf(absf(float(after.get(stat_name, 0.0)) - float(before.get(stat_name, 0.0))), 0.001)


func _relative_drift(before: Dictionary, after: Dictionary, stat_name: String) -> float:
	var left := float(before.get(stat_name, 0.0))
	var right := float(after.get(stat_name, 0.0))
	var local_midpoint := maxf((left + right) * 0.5, 0.001)
	return snappedf(absf(right - left) / local_midpoint, 0.0001)


func _midpoint(left: float, right: float) -> float:
	return snappedf((left + right) * 0.5, 0.001)
