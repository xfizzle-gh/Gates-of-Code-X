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
| map open | 1202.0 ms |

## Run

| Field | Value |
|---|---|
| build | `windows-editor-debug-post-topology-3510` |
| OS | Windows |
| adapter | NVIDIA GeForce RTX 4080 SUPER |
| viewport | 1920x1080 |
| scenario frames | 32 |
| snapshot | `res://fixtures/snapshots/earth3_operational.json` |
| fixture | `res://fixtures/presentation/e3_operational.json` |

## Scenario frame times (ms)

| Scenario | avg | p50 | p95 | p99 | max | draw_calls p95 | nodes p95 | tex_mem p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `idle_full_theatre` | 65.428 | 64.26 | 69.903 | 69.917 | 79.048 | 3782 | 21 | 17436959 |
| `continuous_pan` | 73.191 | 72.673 | 78.063 | 78.387 | 79.714 | 3782 | 21 | 17436959 |
| `continuous_zoom` | 76.811 | 75.212 | 89.712 | 92.386 | 100.084 | 3789 | 21 | 17436959 |
| `province_hover_select` | 63.447 | 62.708 | 68.324 | 68.856 | 69.065 | 3785 | 21 | 17436959 |
| `legal_target_rebuild` | 66.054 | 65.312 | 69.507 | 70.0 | 70.389 | 3788 | 21 | 17436959 |
| `ownership_recolor` | 66.69 | 66.277 | 69.364 | 69.947 | 70.05 | 3785 | 21 | 17420579 |
| `overlay_routes_sites_counters` | 68.163 | 68.369 | 70.735 | 70.85 | 71.504 | 3785 | 21 | 17420579 |
| `pending_battle_presentation` | 69.316 | 69.497 | 71.488 | 71.855 | 72.628 | 3785 | 21 | 17420579 |

## Discrete operation timings (ms)

| Op | avg | p95 | p99 | max |
|---|---:|---:|---:|---:|
| `ownership_refresh_ms` | 2.793 | 2.964 | 2.964 | 4.894 |
| `highlight_refresh_ms` | 0.001 | 0.001 | 0.001 | 0.005 |
| `legal_target_rebuild_ms` | 0.008 | 0.008 | 0.008 | 0.047 |
| `hit_test_ms` | 0.033 | 0.034 | 0.05 | 0.05 |
| `overlay_invalidate_sync_ms` | 0.004 | 0.004 | 0.004 | 0.007 |

## Process snapshot (end of run)

| Metric | Value |
|---|---:|
| script_cpu_ms | 71.813 |
| fps | 15.0 |
| draw_calls | 3779 |
| primitives | 699470 |
| node_count | 21 |
| object_count | 1624 |
| resource_count | 17 |
| texture_mem_bytes | 17420579 |
| video_mem_bytes | 51469455 |
| buffer_mem_bytes | 34048876 |
| static_memory_bytes | 136026570 |
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

## Comparison to PR A pre-topology baseline (3512)

| Scenario | pre avg ms | post avg ms | pre draw p95 | post draw p95 |
|---|---:|---:|---:|---:|
| continuous_pan | 77.952 | 73.191 | 3784 | 3782 |
| continuous_zoom | 76.521 | 76.811 | 3791 | 3789 |
| idle_full_theatre | 70.998 | 65.428 | 3784 | 3782 |
| legal_target_rebuild | 76.175 | 66.054 | 3790 | 3788 |
| overlay_routes_sites_counters | 78.142 | 68.163 | 3787 | 3785 |
| ownership_recolor | 77.667 | 66.69 | 3787 | 3785 |
| pending_battle_presentation | 78.589 | 69.316 | 3787 | 3785 |
| province_hover_select | 72.083 | 63.447 | 3787 | 3785 |

| map provinces | 3512 | 3510 |

Post-topology production: 3510 provinces after Kartaly/Kulakshi exclusion. Water non-select retained.
