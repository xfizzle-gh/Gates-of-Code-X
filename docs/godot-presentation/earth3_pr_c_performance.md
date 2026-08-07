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
| Cheaper terrain shader (1 hash + ridge vs multi-octave noise) | Fragment cost on full land fill |
| Ownership texture: skip rewrite when owners+faction colors unchanged; partial pixel updates when few change | No-op path was ~3ms rewriting all 3514 LUT entries |
| Land mesh `CHUNK` 256→1024 | Fewer MeshInstance2D (13→4) |
| Overlay draw: idle path only visits active provinces (forces/selection/hover/targets), not full 3514 snapshot | Idle frame CPU |

**Not changed:** geography, crop, IDs, adjacency, water policy, island geometry, selection rules, LOD thresholds from PR B.

## After

| Scenario | avg frame ms | Δ vs before | draw_calls p95 |
|---|---:|---:|---:|
| idle_full_theatre | **47.76** | **−24.3 ms** | 3777 |
| continuous_pan | **51.02** | **−24.6 ms** | 3777 |
| continuous_zoom | **62.21** | **−14.6 ms** | 3784 |
| province_hover_select | **58.55** | **−15.6 ms** | 3781 |
| ownership_recolor | 75.27 | −1.3 ms | 3780 |
| legal_target_rebuild | 74.69 | −2.6 ms | 3786 |
| overlay_routes_sites_counters | 75.19 | +0.5 ms | 3780 |
| pending_battle_presentation | 62.57 | −8.8 ms | 3783 |

| Discrete / backend | before | after |
|---|---:|---:|
| ownership_refresh avg ms | 2.99 | 2.84 |
| backend noop rewrite ms | 3.68 | **2.18** |
| mesh_count | 13 | **4** |
| process draw_calls | 3783 | 3775 |

Files: `pr_c_after_interactive.json`, `pr_c_after_backend_profile.json`

## Notes

- Draw-call count remains ~3.7k (Compatibility renderer counter; not reduced materially by chunking alone). Primary win is **frame time** on idle/pan/zoom.
- Ownership recolor scenario still pays LUT update when owners flip (expected).
- Further PR C candidates if needed: border primitive reduction, MultiMesh counters, GPU timers on Vulkan.

## Run

```text
godot --path godot --audio-driver Dummy -s res://scripts/tools/map_interactive_profiler.gd -- \
  --snapshot=res://fixtures/snapshots/earth3_operational.json \
  --fixture=res://fixtures/presentation/e3_operational.json \
  --manifest=res://assets/maps/earth3_europe_mediterranean/map_manifest.json \
  --width=1920 --height=1080 --frames=36 \
  --out=../docs/godot-presentation/pr_c_after_interactive.json
```
