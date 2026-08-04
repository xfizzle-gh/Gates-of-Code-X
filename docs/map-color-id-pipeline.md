# Map pipeline (GoE method, clean-room)

Gates of Europa's author described their map pipeline as:

1. Export a province map from [MapChart HOI4](https://www.mapchart.net/hearts-of-iron-iv.html)
2. Assign every province a **unique RGB id-color**
3. Build neighbor links from the color map
4. Place markers / fill names

That is **not** a hand-drawn polygon mesh and **not** one decorative PNG of Europe with baked ownership colors. Ownership is recolored at runtime by looking up the id-color.

## What CodeX does

| Piece | Source | Shipped? |
|-------|--------|----------|
| Adjacency graph (517) | Observed GoE contract | Yes (`goe_graph_*.b85`) |
| Marker anchors + id-colors | Extracted province DB | Yes (`goe_marker_layout.json`) |
| Decorative / id texture art | GoE Unity `province_idnew_map` | **No** (third-party map art) |
| Runtime ownership paint | Godot fills + counters | Yes |

`apply_marker_layout()` remaps campaign province `x/y` onto observed marker anchors where IDs/names/neighbor growth match. Frontend export always applies this so live campaigns pick up the geographic layout.

## Godot presentation

- Ownership soft blobs + edges (stand-in for full id-map shader)
- HOI-style battalion counters: type glyph + strength on a faction-colored plate
- Pending battle link, fit-to-front, write-back actions

## Future: full color-ID renderer

To match GoE's filled provinces without shipping their texture:

1. Create our own MapChart (or other) export for the theatre we want (modern Europe, 40k, etc.)
2. Run a script: unique RGB per province → neighbor extract → names
3. Ship **our** `province_id_map.png` + id table
4. Godot shader: sample id texture → lookup owner color → draw

This is also the path for "import your own map" tooling.
