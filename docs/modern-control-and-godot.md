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

`gates-of-codex export-frontend` writes a versioned JSON document with schema identifier `gates-of-codex.frontend`.

The document contains:

- campaign identity and active turn
- map metadata and normalized bounds
- factions and alliances
- all provinces and current control
- deduplicated graph edges
- formations and battalions
- occupied province references
- pending-battle state

Godot does not read or mutate Python internals directly. The snapshot is the stable interface between the strategic backend and the presentation layer.

## Godot checkpoint

The `godot/` project is an initial Godot 4 viewer. It loads the snapshot, draws the graph, colors provinces by faction, marks occupied provinces, and supports pan and zoom.

This checkpoint does not include final art, polished interaction panels, hand-corrected geographic positions, or write commands back to the Python backend. Those remain later frontend passes.
