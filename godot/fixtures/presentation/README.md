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
