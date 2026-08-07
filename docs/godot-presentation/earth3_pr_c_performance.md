# Earth3 PR C — measured performance optimization (#74)

Authority unchanged: **3514** / 3299 land / 215 water / `f3931d2e…`  
Base: post-PR-B main (`0d567aa`). Visual hierarchy and interaction behavior preserved.

## Method

1. Profile post-PR-B interactive path (`map_interactive_profiler.gd`, 1920×1080, 36 frames/scenario)
2. Profile backend ownership path (`map_profiler.gd`)
3. Optimize **proven** costs only
4. Re-profile and commit before/after JSON

## Before (post-PR-B)

| Scenario | avg frame ms | draw_calls p95 |
|---|---:|---:|
| idle_full_theatre | 72.10 | 3786 |
| continuous_pan | 75.59 | 3786 |
| continuous_zoom | 76.78 | 3793 |
| province_hover_select | 74.12 | 3789 |
| ownership_recolor | 76.61 | 3789 |

| Discrete op | avg ms |
|---|---:|
| ownership_refresh | 2.99 |
| backend noop ownership rewrite | 3.68 |
| mesh_count | 13 |

Files: `pr_c_before_interactive.json`, `pr_c_before_backend_profile.json`

## Changes (visuals preserved)

| Optimization | Rationale |
|---|---|
| Terrain via **precomputed 64×64 smooth noise texture** (linear filter, skewed UVs) | Organic land variation without square cells; cheaper than 3-octave PR B noise |
| Ownership texture: skip rewrite when owners+faction colors unchanged; partial pixel updates when few change | No-op path was ~3ms rewriting all 3514 LUT entries |
| Land mesh `CHUNK` 256→1024 | Fewer MeshInstance2D (13→4) |
| Overlay draw: idle path only visits active provinces (forces/selection/hover/targets/**infrastructure**), not full 3514 snapshot | Idle frame CPU |

**Not changed:** geography, crop, IDs, adjacency, water policy, island geometry, selection rules, LOD thresholds from PR B.

### Terrain visual fix (post-review)

Replaced `floor(VERTEX.xy * 0.07)` single-hash (visible checkerboard) with a CPU-built smooth noise texture sampled in the fragment shader. Palette and ownership mix unchanged.

## After (smooth terrain texture + infra active-set fix)

Re-profile after terrain visual correction (`pr_c_after_smooth_terrain_interactive.json`):

| Scenario | PR B baseline avg ms | PR C final avg ms | Δ |
|---|---:|---:|---:|
| idle_full_theatre | 72.1 | **52.4** | **−19.7** |
| continuous_pan | 75.6 | **50.3** | **−25.3** |
| continuous_zoom | 76.8 | **65.6** | **−11.2** |
| province_hover_select | 74.1 | **59.2** | **−14.9** |
| ownership_recolor | 76.6 | 74.1 | −2.5 |
| overlay_routes_sites_counters | 74.6 | **50.4** | **−24.2** |
| pending_battle_presentation | 71.4 | **61.6** | **−9.8** |

| Discrete / backend | PR B / before | PR C final |
|---|---:|---:|
| backend noop ownership rewrite ms | 3.68 | **~2.2–2.8** |
| mesh_count | 13 | **4** |
| process draw_calls | ~3783 | **~3778** (not solved) |

Most of the PR C frame-time gain is retained after the smooth-terrain fix.

## Overlay infrastructure regression fix

Active set now includes snapshot provinces with `supply_hub` / `command_post` / `air_base`, even when unoccupied. Cached on snapshot identity change. Profiler scenario `overlay_routes_sites_counters` injects three unoccupied infra markers and asserts they remain in the active set.

## Notes

- **Draw-call count remains ~3.7k** and is **not** claimed solved. This is a **substantial frame-time** improvement with a **remaining draw-call bottleneck**.
- Ownership recolor scenario still pays LUT update when owners flip (expected).
- Further candidates (not in this PR): border primitive reduction, MultiMesh counters, GPU timers on Vulkan.

## Screenshots

| | Path |
|---|---|
| Full map (smooth terrain) | `screenshots/earth3/pr_c_full_map_smooth_1080p.png` |
| Zoomed ops | `screenshots/earth3/pr_c_zoom_ops_1080p.png` |
| Unoccupied infra (supply / CP / air) | `screenshots/earth3/pr_c_infra_zoom_1080p.png` |
| PR B full (compare) | `screenshots/earth3/pr_b_full_theatre_1080p.png` |

## Run

```text
godot --path godot --audio-driver Dummy -s res://scripts/tools/map_interactive_profiler.gd -- \
  --snapshot=res://fixtures/snapshots/earth3_operational.json \
  --fixture=res://fixtures/presentation/e3_operational.json \
  --manifest=res://assets/maps/earth3_europe_mediterranean/map_manifest.json \
  --width=1920 --height=1080 --frames=36 \
  --out=../docs/godot-presentation/pr_c_after_interactive.json
```
