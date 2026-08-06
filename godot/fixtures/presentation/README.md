# Godot presentation fixtures

These fixtures are **Godot-only view models** for strategic-map presentation, debug overlays, and visual regression.

They are **not** production simulation authority and must not be treated as Python frontend schema fields.

## Conventions

- Schema: `gates-of-codex.presentation-fixture`
- Mock-only fields are prefixed with `presentation_`
- Edge battle markers use fixed-point progress (`presentation_progress_fp`, 0..1000)
- Adapters that read live snapshot fields remain replaceable after operational S6 merges

## Fixtures

| File | Covers |
|---|---|
| `empty_map.json` | Empty overlays |
| `full_theatre_smoke.json` | Full 342-province map smoke markers |
| `many_counters.json` | Dense counter presentation |
| `stack_and_selection.json` | Stack badge + selected/hovered provinces |
| `routes_and_battles.json` | Route lines, node battle, mock edge battle |
| `control_sites.json` | Control-site + capture progress |
| `rapid_hover.json` | Hover stress marker list |
| `refresh_stability.json` | Repeated refresh node-stability checklist |
| `resolutions.json` | Supported resolution checklist |
| `s6_node_contact.json` | S6 node_contact pending_battle overlay |
| `s6_node_simultaneous.json` | S6 node_simultaneous pending_battle overlay |
| `s6_edge_cross.json` | S6 edge_cross with encounter_pixel authority |
| `s6_edge_catchup.json` | S6 edge_catchup via edge_id + progress_milli |
| `s6_legacy_midpoint.json` | Legacy battle without operational location |

## Snapshots

| File | Covers |
|---|---|
| `../snapshots/em_theatre_profile.json` | Committed deterministic 342-province frontend snapshot for profiler/CI/screenshots (write-back disabled) |
