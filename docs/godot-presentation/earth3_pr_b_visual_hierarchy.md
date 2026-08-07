# Earth3 PR B — production visual hierarchy

Epic: #74  
Branch: `feat/earth3-pr-b-visual-hierarchy`  
Authority: **3514** / 3299 land / 215 water / `f3931d2e…` / merge `db60559`

## Scope

Presentation only. No crop/ID/adjacency/water geometry changes. No island coastline work (#121 deferred).

| Layer | Behavior |
|---|---|
| Ocean underlay | Continuous blue quad (unchanged policy) |
| Land terrain | Clean-room procedural elevation noise in fill shader (not archive art) |
| Ownership | Translucent faction tint mixed over terrain (`ownership_mix` ~0.46, slightly stronger when zoomed in) |
| Province borders | Land–land quieter; coast darker; zoom-dependent modulate alpha |
| Exterior singleton borders | Still suppressed (crop-edge fix from #127) |
| Selection / targets / hover | Weighted outline widths scale with `view_scale` |
| Federal outlines | Quieter at full theatre; stronger when zoomed |
| Counters | LOD: hide ambient at full theatre; keep selected/hovered/target |
| Labels | Ambient names still require `view_scale >= 2.4`; hover/selected priority unchanged |

## Files

- `godot/shaders/province_ownership.gdshader` — terrain base + ownership mix
- `godot/scripts/polygon_map.gd` — mix/border weights, zoom hooks, outline hierarchy
- `godot/scripts/main_color_id.gd` — counter/label/federal LOD

## Non-goals (this PR)

- Draw-call batching (PR C)
- Island coastline reconstruction (#121)
- Hydrography research
- Archive background textures without owner permission

## Geometry / authority

Immutable polygon meshes, stable `e3_*` IDs, water non-selectable, permanent gaps `e3_2830`/`e3_2888` untouched.
