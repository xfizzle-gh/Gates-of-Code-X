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
| **visual background** | **Local external only** (optional pack TGA export) | Loaded via gitignored `background_config.json`. **Not stored in the repository.** Repo ships `background_placeholder.png` only. |
| **gameplay land/water mask** | **Natural Earth land polygons** (public domain) | Used to keep ocean unselectable and to clip province cells. Independent of the painted background. |
| **province boundaries (selection)** | **Project color-ID texture** (`id_map.png`) | Invisible in normal view except as borders/tint. Handles click, ownership, highlights. |
| **province boundaries (layout)** | **Provisional** project Voronoi over land mask | Reshape later using settlements/roads/rivers/mountains/ports/crossings on the pack basemap. `regions.esf` polygons optional, not a blocker. |
| **settlement names** | Default: title-cased seed keys. Optional generate-time: pack UTF-16 loc via `--settlements-loc` | Current committed assets were generated **without** pack loc input. |
| **settlement coordinates** | **Built-in public lat/lon table** (`SETTLEMENT_GEO`) | Pack DB/ESF coordinates **not recovered**. |
| **ports** | **Not imported** from pack | Pack port/town names exist as research reference only. A few hubs get hand-authored `port` infrastructure flags in the prototype campaign. |
| **terrain (gameplay)** | **Not imported** from pack | Visual terrain comes from pack background; gameplay terrain fields remain placeholders. |
| **adjacency** | **Project**: 4-neighbor land pixel touch + authored `strait` / `ferry_or_sea_lane` | Pack connectivity **not** used. |

### Rendering layers

**Normal view**

1. Local pack terrain background if configured, else project placeholder  
2. Transparent faction ownership tint  
3. Province borders  
4. Labels / formations / facilities / highlights  

**Debug**

- `I` — raw color-ID + province IDs/anchors  
- `C` — measured calibration: background + NE silhouette + target (cyan) vs resulting (orange) points with px error (median≤8, max≤20)

Do not paint solid full-opacity ownership fills over the background.

### Local pack background (not in git)

```powershell
python -c "from gates_of_codex.map_background import export_local_pack_background; export_local_pack_background(source_tga=r'path\to\boshin_map_world.tga', output_png=r'C:\Users\...\em_local\europe_mediterranean_background.png', config_json=r'godot\assets\maps\europe_mediterranean\prototype\background_config.json')"
```

PR language:

```text
Pack background integration works locally.
Pack image is not stored or distributed by the repository.
Province geometry remains provisional.
```

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
