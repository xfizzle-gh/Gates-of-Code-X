# Modern control profile and Godot contract

## Modern control profile

The recovered Gates of Europa alpha runtime exposes an exact 517-node adjacency graph, but it does not expose a complete modern ownership scenario. Gates of CodeX therefore applies a deterministic development profile named `modern_europe_v1`.

The profile starts from named and formation deployment anchors for NATO, Ukraine, Russia, and PRC, then expands control through the recovered graph. PRC expansion is deliberately limited around the provisional Central Asian anchors. Any disconnected nodes fall back to the nearest non-PRC seed in generated-layout space.

Every province records:

- `control_profile`
- `control_seed`
- `control_distance`
- an optional `formation_anchor`

Existing source-era metadata is preserved rather than overwritten. The campaign map metadata records faction control counts and identifies the ownership profile as generated development data.

## Coalitions

The campaign stores two alliances:

- Western Coalition: NATO and Ukraine
- Eastern Coalition: Russia and PRC

Alliance membership does not merge faction turns, resources, research, recruitment pools, formations, or tactical faction codes. The North Korean contingent remains a Russia-aligned foreign formation.

## Frontend snapshot

`gates-of-codex export-frontend` writes a versioned JSON document with schema identifier `gates-of-codex.frontend` (schema version 6+).

The document contains:

- campaign identity and active turn
- map metadata and normalized bounds
- factions and alliances
- all provinces and current control
- deduplicated graph edges
- formations and battalions
- `battalion_stacks`, a deterministic `province_id -> [battalion_id, ...]` contract
- `occupied_by_battalions` on each province, with legacy `occupied_by` retaining the first sorted ID
- pending-battle state
- `front_options` legal move/attack rows containing the acting `battalion_id`
- `control` write-back paths and the exact `python_executable` / `python_module`

Godot does not read or mutate Python internals directly. The snapshot is the stable interface between the strategic backend and the presentation layer.

## Write-back command queue

Godot writes operator actions to `frontend_commands.json` next to the snapshot:

```json
{
  "commands": [
    {"op": "move", "battalion": "formation-04", "province": "Nowogrodek"},
    {"op": "end_turn"},
    {"op": "run_ai", "faction": "ukr", "advance_turn": true},
    {"op": "auto_resolve"},
    {"op": "construct", "province": "Berlin", "building": "supply_hub"},
    {"op": "refresh"}
  ]
}
```

Apply and refresh with:

```text
gates-of-codex apply-frontend campaign.json --snapshot godot/campaign_snapshot.json
```

For write-enabled snapshots, the control block exports the exact interpreter used for the frontend export, normally the repository `.venv` Python. Godot passes that executable directly to `OS.execute()` and passes every path as a separate argument, so paths containing spaces do not depend on shell parsing or editor PATH configuration. Bare command fallback exists only for older snapshots that omit the explicit executable.

The backend applies commands in order, clears the queue, rewrites the snapshot, and returns a JSON result.

Supported ops: `move`, `end_turn`, `run_ai`, `auto_resolve`, `construct`, `repair`, `handoff`, `refresh`.

## Multi-battalion checkpoint

PR #50 preserves every battalion in each province and displays an aggregate compact counter with a stack-count badge. Until the full selector in #52 lands, the acting battalion is deterministic:

1. retain the currently selected battalion if it still has legal options
2. otherwise select the lexicographically first battalion ID with legal options
3. if none can act, retain the first sorted battalion as the display representative

Every move command includes that exact battalion ID. The full stack tabs, battalion cards, and explicit selection UI remain in #52.

## Godot checkpoint

The `godot/` project is a Godot 4 strategic map client. It loads the snapshot, draws the graph, colors provinces by faction, highlights legal targets for the selected battalion, and supports pan/zoom plus panel actions.

Export a write-enabled snapshot before launching Godot:

```text
gates-of-codex export-frontend live/campaign.json --output godot/campaign_snapshot.json
```

Then open the `godot/` project. Select an owned counter, click a highlighted neighbor to move/attack, or use panel buttons for end turn, AI, auto-resolve, construction, and handoff.

The marker-based map in this checkpoint remains temporary. Authoritative province-shaped selection and runtime recoloring are implemented under #51 using the interim GoE-derived color-ID source behind the generic map-import boundary.
