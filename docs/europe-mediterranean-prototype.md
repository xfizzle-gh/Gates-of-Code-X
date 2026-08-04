# Europe–Mediterranean strategic map prototype

## Status

**Not complete.** Renderer + campaign pipeline work; **province layout remains provisional.**

PR #63 is a pipeline checkpoint only. Do not describe the map or PR as finished.

| Layer | Status |
|---|---|
| Map ID + matching campaign | Working |
| Explicit map selection | Working |
| Title / diagnostic | Working |
| Color-ID renderer, ownership, counters, facilities, movement UI | Working |
| Europe fallback (`interim_goe_europe`) | Working |
| Geographic land/water mask | Working (Natural Earth) |
| Province polygons / fronts | **Provisional** (project Voronoi) |
| Pack region-mesh import | **Not recovered for use** |

## Provenance table (authoritative)

| Data | Source used in current generator/manifest | Notes |
|---|---|---|
| **coastline** | **Natural Earth land polygons** (public domain) | Theatre crop `lon -25..50`, `lat 25..72`. Pack TGA is **not** used. |
| **province boundaries** | **Project-authored** component-locked settlement Voronoi on the land mask | Not pack `regions.esf` meshes. Pack outlines may become reference later only after per-ID export succeeds. |
| **settlement names** | Default: title-cased seed keys. Optional generate-time: pack UTF-16 loc via `--settlements-loc` | Current committed assets were generated **without** pack loc input. |
| **settlement coordinates** | **Built-in public lat/lon table** (`SETTLEMENT_GEO`) | Pack DB/ESF coordinates **not recovered**. |
| **ports** | **Not imported** from pack | Pack port/town names exist as research reference only. A few hubs get hand-authored `port` infrastructure flags in the prototype campaign. |
| **terrain** | **Not imported** from pack | Placeholder `temperate` / project metadata only. |
| **adjacency** | **Project**: 4-neighbor land pixel touch + authored `strait` / `ferry_or_sea_lane` | Pack connectivity **not** used. |

### `world_test_9.pack` role

Important **campaign-data reference**, not the shippable map asset:

- Use for: settlement/region/port **names**, ID vocabulary, future anchors, optional region-geometry reference after ESF export.
- Do **not** use for: final coastline, current province polygons, current adjacency, or committed binary pack payloads.

Decode details: [`docs/audits/world-test-9-regions-esf-decode.md`](audits/world-test-9-regions-esf-decode.md).

## Current seed audit (143 provinces)

From the committed EM manifest vs pack settlement ID vocabulary:

| Bucket | Count | Meaning |
|---:|---:|---|
| Seed keys overlapping pack `bos_*` settlement IDs | **89** | Same **ID string** as pack (e.g. `paris`); coordinates still public-geo, not pack |
| Seed keys from built-in public-geo only | **54** | Theatre fill-ins (e.g. `kyiv`, `cairo`, `istanbul`, `moscow`, …) with **no** pack settlement ID |

Pack data **actually present in the generated manifest today**:

- No pack coastline
- No pack polygons
- No pack coordinates
- No pack ports/terrain/adjacency tables
- ID key overlap only (plus optional loc names if passed at generate-time)

## Generate

```powershell
python -m gates_of_codex generate-europe-mediterranean-prototype `
  --land-geojson path\to\ne_50m_land.geojson `
  --settlements-loc path\to\campaign_map_settlements.txt `
  --commit-mask-copy `
  --output-dir godot/assets/maps/europe_mediterranean/prototype
```

- `--land-geojson` / package land mask: Natural Earth-derived land/water only  
- `--settlements-loc`: optional pack labels (names only)  
- `--world-tga`: legacy research path; **not preferred**; do not treat as coastline authority  

## Create matching campaign

```powershell
python -m gates_of_codex new --map europe_mediterranean_prototype --faction nato --output live/em_campaign.json
python -m gates_of_codex export-frontend live/em_campaign.json --output godot/campaign_snapshot.json
```

## Architecture

| Layer | Europe fallback | EM prototype |
|---|---|---|
| Campaign graph | 517 GoE IDs | `em_*` IDs from manifest |
| Color-ID texture | interim_goe 1314×1513 | EM theatre crop (currently 1600×1000) |
| Outside theatre | n/a | excluded |
| Title | Gates of CodeX: Europe | Gates of CodeX: Europe-Mediterranean Prototype |

## Godot diagnostic

```text
Map: europe_mediterranean_prototype | Provinces: N | Manifest: assets/maps/europe_mediterranean/prototype/...
```
