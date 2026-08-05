# Map pipeline and interim GoE source

Gates of Europa's author described their map pipeline as:

1. Export a province map from [MapChart HOI4](https://www.mapchart.net/hearts-of-iron-iv.html)
2. Assign every province a **unique RGB id-color**
3. Build neighbor links from the color map
4. Place markers / fill names

That is **not** a hand-drawn polygon mesh and **not** one decorative PNG of Europe with baked ownership colors. Ownership is recolored at runtime by looking up the id-color.

## Current source status

The project owner has authorized the available GoE-derived color-ID source as an **interim implementation asset** so province-shaped rendering is not blocked. A project-owned clean-room replacement remains planned.

| Piece | Source | Status |
|-------|--------|--------|
| Adjacency graph (517) | Observed GoE contract | Tracked (`goe_graph_*.b85`) |
| Marker anchors + id-colors | Extracted province DB | Tracked (`goe_marker_layout.json`) |
| 1314×1513 RGB24 ID texture | GoE Unity `province_idnew_map` | Interim source for #51, isolated behind the generic importer |
| Runtime ownership paint | Godot color-ID renderer | Implemented separately in #51 |

The interim source must remain behind a generic map manifest/import boundary. Gameplay must not depend on the texture dimensions, specific RGB assignments, or original source format. Replacing the texture and lookup table must not require campaign-rule changes.

## PR #50 marker checkpoint

`apply_marker_layout()` remaps campaign province `x/y` onto observed marker anchors where IDs, names, or neighbor growth match. Frontend export applies this so live campaigns receive a recognizable geographic layout.

This marker placement is temporary presentation only. It is not the authoritative clickable province map, and neighbor-assisted marker positions are not a substitute for exact color-ID pixel selection.

The PR #50 Godot presentation includes:

- ownership soft blobs + edges as a temporary stand-in
- HOI-style battalion counters
- pending battle link, fit-to-front, and write-back actions

## Color-ID renderer boundary

Issue #51 replaces marker hit-testing with the real province-shaped renderer:

1. Read a generic map manifest.
2. Load the configured ID texture and RGB-to-province lookup table.
3. Resolve mouse pixels deterministically to province IDs.
4. Recolor ownership at runtime.
5. Draw borders, highlights, supply, infrastructure, bases, counters, and labels as independent layers.

The same importer boundary will accept the future project-owned replacement and additional theatres without hardcoded dimensions or RGB values.
