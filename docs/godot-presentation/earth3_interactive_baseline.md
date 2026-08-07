# Earth3 interactive performance baseline (PR A / #74)

Measurement-only. No renderer rewrite.

## Authority

| Field | Value |
|---|---|
| map_id | `earth3_europe_mediterranean` |
| provinces | 3512 |
| land/water | 3297/215 |
| included_ids_sha256 | `507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7` |
| production merge | `7182f8c6002e48f7235ba5ce6b7dd57ee20f4f68` |
| mesh_count | 13 |
| image | 4306x3449 |
| map open | 1115.0 ms |

## Run

| Field | Value |
|---|---|
| build | `windows-editor-debug` |
| OS | Windows |
| adapter | NVIDIA GeForce RTX 4080 SUPER |
| viewport | 1920x1080 |
| scenario frames | 48 |
| snapshot | `res://fixtures/snapshots/earth3_operational.json` |
| fixture | `res://fixtures/presentation/e3_operational.json` |

## Scenario frame times (ms)

| Scenario | avg | p50 | p95 | p99 | max | draw_calls p95 | nodes p95 | tex_mem p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `idle_full_theatre` | 70.998 | 70.29 | 77.046 | 80.561 | 80.696 | 3784 | 21 | 17436959 |
| `continuous_pan` | 77.952 | 77.376 | 82.707 | 83.41 | 83.53 | 3784 | 21 | 17436959 |
| `continuous_zoom` | 76.521 | 75.927 | 79.303 | 80.961 | 81.137 | 3791 | 21 | 17436959 |
| `province_hover_select` | 72.083 | 70.225 | 76.686 | 79.37 | 99.618 | 3787 | 21 | 17436959 |
| `legal_target_rebuild` | 76.175 | 75.557 | 78.899 | 80.137 | 87.633 | 3790 | 21 | 17436959 |
| `ownership_recolor` | 77.667 | 77.322 | 80.324 | 82.546 | 85.558 | 3787 | 21 | 17420579 |
| `overlay_routes_sites_counters` | 78.142 | 76.763 | 82.95 | 83.36 | 88.057 | 3787 | 21 | 17420579 |
| `pending_battle_presentation` | 78.589 | 77.809 | 84.431 | 88.813 | 89.475 | 3787 | 21 | 17420579 |

## Discrete operation timings (ms)

| Op | avg | p95 | p99 | max |
|---|---:|---:|---:|---:|
| `ownership_refresh_ms` | 3.196 | 4.109 | 4.109 | 5.35 |
| `highlight_refresh_ms` | 0.001 | 0.002 | 0.002 | 0.006 |
| `legal_target_rebuild_ms` | 0.009 | 0.009 | 0.009 | 0.056 |
| `hit_test_ms` | 0.034 | 0.034 | 0.047 | 0.06 |
| `overlay_invalidate_sync_ms` | 0.004 | 0.004 | 0.004 | 0.011 |

## Process snapshot (end of run)

| Metric | Value |
|---|---:|
| script_cpu_ms | 83.209 |
| fps | 13.0 |
| draw_calls | 3781 |
| primitives | 700364 |
| node_count | 21 |
| object_count | 1622 |
| resource_count | 17 |
| texture_mem_bytes | 17420579 |
| video_mem_bytes | 51507403 |
| buffer_mem_bytes | 34086824 |
| static_memory_bytes | 135732053 |
| gpu_ms | <null> |

## Notes

- Frame times are wall-clock ms around force_draw + one process tick (interactive path).
- script_cpu_ms uses Performance.TIME_PROCESS; render counters from Performance.RENDER_*.
- GPU time is only present when the backend exposes it; otherwise null.
- No renderer rewrite in PR A — baseline measurement only.
- Do not change Earth3 crop/IDs/adjacency/water geometry.

## Release export

Release-export capture is optional in PR A when export templates are unavailable on the runner.
Windows editor-debug results above are the committed authority baseline.

## Companion headless backend profile

See `docs/godot-presentation/earth3_operational_backend_profile.json` (map_profiler.gd on earth3_operational snapshot).

Primary interactive findings for PR C candidates:

- ~3.7k draw calls per frame at full theatre (dominant cost signal)
- ownership refresh ~3 ms (geometry immutable path OK)
- hit-test ~0.03 ms
- wall-clock scenario frames ~71–79 ms avg on RTX 4080 SUPER editor-debug @ 1920×1080
