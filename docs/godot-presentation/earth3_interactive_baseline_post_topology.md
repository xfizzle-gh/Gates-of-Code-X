# Earth3 interactive performance baseline (post-topology production)

Measurement of **current production** after Kartaly/Kulakshi exclusion.

## Measured authority (current production)

| Field | Value |
|---|---|
| map_id | `earth3_europe_mediterranean` |
| provinces | **3510** |
| land/water | **3295/215** |
| selectable | **3295** |
| included_ids_sha256 | `a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3` |
| dataset_sha256 | `31c899b803db38291334f99c84f3f19247575785b87a603415059a2f25acfc9b` |
| production merge | `b5b4c14a58e54effb5875a35348576057c27ce80` |
| test repair | `f60e715afb2a0a2b197351422edf5fa84a28da70` |

## Historical comparison authority (PR A baseline only)

| Field | Value |
|---|---|
| provinces | 3512 |
| land/water | 3297/215 |
| included_ids_sha256 | `507b0069a9572e915059ff6d21bd9f13a68cf62a26770c94a90c0b0e6a900be7` |
| note | Pre-topology PR A measurement — not current production |

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

## Comparison to PR A pre-topology baseline (3512 historical)

| Scenario | pre avg ms (3512) | post avg ms (3510) | pre draw p95 | post draw p95 |
|---|---:|---:|---:|---:|
| `idle_full_theatre` | 70.998 | 65.428 | 3784 | 3782 |
| `continuous_pan` | 77.952 | 73.191 | 3784 | 3782 |
| `continuous_zoom` | 76.521 | 76.811 | 3791 | 3789 |
| `province_hover_select` | 72.083 | 63.447 | 3787 | 3785 |
| `legal_target_rebuild` | 76.175 | 66.054 | 3790 | 3788 |
| `ownership_recolor` | 77.667 | 66.69 | 3787 | 3785 |
| `overlay_routes_sites_counters` | 78.142 | 68.163 | 3787 | 3785 |
| `pending_battle_presentation` | 78.589 | 69.316 | 3787 | 3785 |

| map provinces | 3512 | 3510 |

Current measured authority is **3510** / `a849b3817d98d34e1687c7f7d4899c21f54925fa458cde8b5fe425f6b05206f3`.
Comparison **pre** columns are the historical **3512** PR A baseline only.
