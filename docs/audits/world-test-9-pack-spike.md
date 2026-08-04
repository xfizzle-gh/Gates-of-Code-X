# world_test_9.pack extraction spike

- Source: `C:\Users\paulf\Downloads\world_test_9.pack` (225,201,290 bytes)
- Format: Total War **PFH3** (header + `u32 size` + `name\0` index; sequential payloads)
- Files extracted: **72**
- Local extract only (do **not** commit/redistribute binaries): `C:\Users\paulf\AppData\Local\Temp\opencode\world_test_9_extract`

## Inventory

| Ext | Count | Notes |
|---|---:|---|
| `.dds` | 27 | detail/season textures, parchment mapping |
| `.txt` / `.loc` | 9 / 9 | UTF-16 localized names |
| `.esf` | 6 | regions, pathfinding, poi, sea grids, trade, startpos |
| `.tga` | 5 | world map textures + masks |
| `.dat` | 3 | heightmap (~96 MB), metadata (~16 MB), no_go |
| bare TW DB tables | 7 | settlements, towns, towns/ports, ground types, climates |
| `.xml` / `.lua` / other | rest | settings + scripting |

## High-value payloads confirmed

- `campaign_maps/bos_japan/boshin_map_world.tga` (+ medium/small) — world textures
- `.../display/Heightmap/heightmap.dat` — ~96 MB elevation
- `.../display/Detail/campaign_detail_mask.dds/.tga` — terrain/detail masks
- `campaign_maps/bos_japan/metadata.dat` — ~16 MB
- `campaign_maps/bos_japan/regions.esf` — ~15.1 MB
- `campaign_maps/bos_japan/pathfinding.esf` — ~6.5 MB
- `campaign_maps/bos_japan/poi.esf`, `sea_grids.esf`, `trade_routes.esf`
- `db/regions_tables/regions`
- `db/campaign_map_settlements_tables/campaign_map_settlements`
- `db/campaign_map_towns_and_ports_tables/campaign_map_towns_and_ports`
- UTF-16 loc tables for regions / settlements / towns / ports

Despite the `bos_japan` folder name, content includes **European** `bos_*` regions and settlements (Paris, Berlin, Rome, Brussels, etc.) plus Japanese names mixed into loc tables.

## Name / ID recovery (no geometry yet)

From UTF-16 loc tables:

- Distinct **`bos_*` region/settlement IDs: 92**
- Sample IDs: `bos_ajaccio`, `bos_amsterdam`, `bos_berlin`, `bos_paris`, `bos_rome`, `bos_brussels`, `bos_lisbon`, `bos_edinburgh`, ...
- Region on-screen labels present (e.g. Belgium, West Austria, Hanover, Sardinia, Valencia, Aquitaine, …)
- Settlement on-screen labels present (e.g. Toulouse, Metz, Stockholm, Rome, Turin, Gibraltar, …)

This matches the “~92 European bos_ identifiers + localized names” summary.

## Feasibility for Gates of CodeX

| Item | Status |
|---|---|
| Pack parse / extract | **Done** |
| World / detail / height blobs | **Present** |
| Named settlements / ports / regions tables | **Present** |
| Region ID list | **Present (92 bos_*)** |
| Recovered province polygons | **Not yet** (`regions.esf` still needs geometry decode) |
| Ready-to-import color-ID map | **No** |
| Safe to ship pack binaries in git | **No** until provenance/license is clear |

## Decision (Shutkar proposals)

1. **Strategic path = Proposal 1**: one coherent world projection + geographically grounded provinces large enough for settlements, facilities, and army maneuver.
2. **Reject Proposal 2** (glued landscape maps) for the strategic layer — seams, scale, and adjacency pain.
3. Presentation split already agreed:
   - **HOI-style world map** for ownership/fronts
   - **Total War-style battalion UI** for stack composition
4. Treat `world_test_9.pack` as **research/prototype input**, not a drop-in Godot asset.
5. Keep the current Europe interim color-ID map playable while world conversion is researched.

## Next engineering spike

1. Decode `regions.esf` geometry (RPFM ESF tooling or CAF!/ESF parser).
2. Join settlements/towns/ports tables to region IDs + coordinates.
3. If polygons recover → rasterize to unique-RGB color-ID texture + adjacency + anchors for `import-strategic-map`.
4. If only points recover → author simplified provinces over the same projection using settlement seeds + MapChart/geo boundaries.
5. Do not replace the Europe playable path until a validated world importer exists.

## Machine-readable local outputs

- `C:\Users\paulf\AppData\Local\Temp\opencode\world_test_9_extract\listing.json`
- `C:\Users\paulf\AppData\Local\Temp\opencode\world_test_9_extract\analysis.json`
