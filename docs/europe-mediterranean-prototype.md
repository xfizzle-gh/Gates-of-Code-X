# Europe–Mediterranean strategic map prototype

## Status

**Pipeline checkpoint accepted. Geographic map generation still in progress.**

Playable **non-canonical** Europe–Mediterranean theatre prototype with matching campaign graph.

- Europe interim remains fallback (`interim_goe_europe` / `goe_europe`)
- EM prototype selected only via `strategic_map_id=europe_mediterranean_prototype`
- Full-world map is **out of scope**
- Generated assets are **prototype-only, not approved for distribution**

## What is accepted

- map ID + matching campaign
- explicit map selection
- title/diagnostic
- generic color-ID renderer
- ownership, selection, counters, facilities, movement UI
- Europe fallback

## What is not accepted yet

- final coastlines / province art quality
- fully authored national/regional boundaries
- complete strait/ferry network design
- final province count (driven by geography + gameplay, not fixed first)

## Land mask

Preferred source: **Natural Earth land polygons** (public domain).

```powershell
python -m gates_of_codex generate-europe-mediterranean-prototype `
  --land-geojson path\to\ne_50m_land.geojson `
  --commit-mask-copy `
  --output-dir godot/assets/maps/europe_mediterranean/prototype
```

Without geojson, generator uses package mask `src/gates_of_codex/data/europe_mediterranean_land_mask.png` if present, else a synthetic fixture for tests.

Ocean/lakes/seas stay unselectable background (`RGB 0,0,0`) unless separately authored as naval zones later.

## Province construction

1. Rasterize geographic land mask for theatre `lon -25..50`, `lat 25..72`
2. Label connected land components
3. Seed settlements on land
4. Component-locked Voronoi (no Channel/jump across water)
5. Land adjacency = 4-neighbor land pixel touch only
6. Authored crossings only for `strait` / `ferry_or_sea_lane`

## Create matching campaign

```powershell
python -m gates_of_codex new --map europe_mediterranean_prototype --faction nato --output live/em_campaign.json
python -m gates_of_codex export-frontend live/em_campaign.json --output godot/campaign_snapshot.json
```

## Godot diagnostic

```text
Map: europe_mediterranean_prototype | Provinces: N | Manifest: assets/maps/europe_mediterranean/prototype/...
```
