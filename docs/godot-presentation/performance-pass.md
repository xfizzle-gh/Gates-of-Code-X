# Godot strategic map performance and presentation pass

Tracking: #85  
Parent epic: #74  
Branch: `feat/godot-strategic-map-performance`  
Base: main @ `b166167` (#81)

## Scope

Godot-only presentation improvements. No Python operational/schema changes.

### Exact Godot paths discovered

| Role | Path |
|---|---|
| Main scene | `godot/main.tscn` |
| Active client script chain | `main_stack_panel.gd` → `main_map_contract.gd` → `main_color_id.gd` → `main_writeback.gd` → `main.gd` |
| Color-ID renderer | `godot/scripts/color_id_map.gd` |
| EM theatre assets | `godot/assets/maps/europe_mediterranean/from_goe/` |
| ID texture | `province_id_map.png` (817×920, nearest, 342 provinces) |
| Background underlay | `background_procedural.png` |
| Manifest | `map_manifest.json` |
| Presentation components | `godot/scripts/presentation/` |
| Fixtures | `godot/fixtures/presentation/` |
| Profiler | `godot/scripts/tools/map_profiler.gd` |

### Rendering model

- **Authoritative hit-test:** unique-RGB ID image, nearest sampling, never linearly filtered
- **Visual layers:** background underlay + ownership tint + borders + highlight mask
- **Dynamic overlays:** counters, labels, routes, battle/contact/site markers, debug

## Baseline (before)

Headless Godot 4.7 profiler on EM theatre + `campaign_snapshot.json`:

| Metric | Before | Method |
|---|---:|---|
| Map open | 1093.39 ms | `map_profiler.gd` |
| Ownership full rebuild | 321.58 ms avg | full pixel scan each `refresh_snapshot` |
| Highlight rebuild | 267.07 ms avg | full pixel scan each `refresh_highlights` |
| Province pick | ~0.001 ms | ID sample |
| Image | 817×920 | manifest |
| Provinces | 342 | manifest/snapshot |
| Node count | 1 root Node2D + UI draw | immediate-mode canvas |
| Draw calls | n/a in headless script profiler | limitation |
| Idle/hover FPS | n/a | requires interactive capture |

Root causes:

1. Every ownership/highlight refresh rescanned all ~751k ID pixels with `get_pixel` RGB decode.
2. Hover/`queue_redraw` did not rebuild textures (good), but selection felt slow because highlight rebuild was hundreds of ms.
3. Background/owner textures shared default filtering with no explicit nearest/linear split.
4. No centralized map-space transform helper; texture dimensions risked hardcoding.
5. No reusable marker components, debug invalidation counters, or presentation fixtures.

## After

| Metric | After | Method |
|---|---:|---|
| Map open | 388.05 ms | includes one-time pixel-run cache build |
| Ownership no-op refresh | 0.247 ms avg | event-driven skip when unchanged |
| Ownership partial (1 province) | 0.82 ms | province pixel runs only |
| Highlight no-op | 0.027 ms avg | selection/target equality skip |
| Highlight change | 0.21 ms avg | paint selected+targets only |
| Province pick | ~0.0 ms | packed province index |
| Cached runs | 342 | one per province |
| Pixel index size | 751640 | w×h |

Files: `docs/godot-presentation/baseline_profile.json`, `after_profile.json`.

## Performance changes

- Precompute `_pixel_province_index` and per-province pixel runs once on open
- Incremental ownership updates (`_rebuild_owner_partial`)
- Highlight rebuild paints only selected + legal-target provinces
- `ImageTexture.update` instead of recreating textures every time
- Overlay label layout cache keyed by selection/targets/view transform; hover label is live-only
- Hover never calls `refresh_snapshot` / `refresh_highlights`
- Perf counters via `get_perf_stats()` / debug overlay

## Visual / scaling quality

- Default window 1920×1080, `canvas_items` stretch, `aspect=expand`, HiDPI allowed
- Background drawn with **linear** filter; owner/border/highlight with **nearest**
- Soft 1px border halo to reduce harsh stair-steps when upscaled
- `MapSpace` centralizes image↔screen transforms; no hardcoded 817×920 UI math
- CLI flags (`--screenshot=`, `--fixture=`, `--debug-map`) no longer steal the snapshot path

## Presentation components

`godot/scripts/presentation/map_markers.gd`:

- selected/hovered province rings
- formation counter + stack badge
- route line
- node/edge contact markers
- crossed-swords battle marker
- control-site marker + fixed-point capture progress

Battle marker accepts node pixel, edge endpoints + `presentation_progress_fp` (0..1000), or supplied pixel. **Does not decide Python battle detection.**

## Debug mode

- Toggle: **F3** or `--debug-map`
- Shows anchors, IDs (selected/hover), bounds, FPS/frame ms, redraw/invalidation counters, optional fixture graph/sites
- Disabled by default for ordinary play

## Fixtures

See `godot/fixtures/presentation/`. Schema `gates-of-codex.presentation-fixture`. Mock fields use `presentation_` prefix.

## Visual evidence

`docs/godot-presentation/screenshots/`:

- before/after full map 1080p and 1440p
- selected province, formation counters
- route, node battle, mock edge battle
- debug overlay + control sites

Note: interactive Godot window capture hung in this agent environment; composites were generated offline from the same Godot assets/fixtures via `tools/render_presentation_evidence.py` and labeled accordingly. Headless CPU timings above are live Godot engine measurements.

## Assumptions

- 817×920 ID map remains authoritative until a future geometry PR (#74 stages 2–3)
- Live operational edge-contact serialization will arrive from S6; adapters stay Godot-side
- Immediate-mode CanvasItem drawing remains acceptable; node pooling is less relevant than texture invalidation

## Dependencies on S6

- None for this PR
- After S6 merges, replace presentation-only edge fixtures with read-only live fields in Godot adapters only

## Known limitations

- Source art resolution still 817×920; true smooth vector borders are out of scope
- Interactive FPS / draw-call GPU counters not captured in headless mode
- Stack panel UI performance is unchanged except shared map-layer gains
- `campaign_snapshot.json` used for local profiling is a generated runtime artifact (not required in git)

## Regressions covered

Python contract tests + new presentation suite (see PR checks). Manual checklist in fixtures `refresh_stability.json` / `rapid_hover.json`.
