# world_test_9.pack — regions.esf decode pass

Date: 2026-08-04  
Source pack: `C:\Users\paulf\Downloads\world_test_9.pack`  
Local extract (do not commit binaries): `C:\Users\paulf\AppData\Local\Temp\opencode\world_test_9_extract`  
Machine report: `...\world_test_9_extract\regions_geometry_report.json`

## Tools

| Tool | Status |
|---|---|
| Prior PFH3 extract | Available |
| RPFM / `rpfm_cli` | **Not installed** on this machine |
| Custom CAAB header + string-table probe | Run |
| Tagged `0x0C` coord2 scan | Run |
| u32-count + float-pair array scan | Run |
| UTF-16 settlement/region/port txt tables | Run |
| Binary DB key scan | Run |

## regions.esf structure

- Magic: `CAAB` (`0x0000ABCA`)
- String table at header offset `+12` → file offset **15027290**
- ASCII schema tags present (**47**), including:

```text
root, theatres_and_region_keys, region_data, vertices, regions, areas,
faces, outlines, connectivity, settlement_and_slots, slot_descriptions,
roads, links, railways, canals, mountain_data, land_indices, sea_indices,
groundtypes, ...
```

This proves the file is a **real region geometry container**, not merely labels.

## Are region polygons / boundary coordinates recoverable?

| Question | Answer |
|---|---|
| Geometry schema present? | **Yes** (`vertices`, `regions`, `areas`, `faces`, `outlines`, `connectivity`) |
| Raw coordinate-like values present? | **Yes** — ~**6015** tagged coord2 hits; ~**68** float-pair array candidates; values are **campaign map units**, not lon/lat |
| Clean per-region polygon export joined to `bos_*` IDs? | **No — not achieved in this pass** |
| Usable as generator province boundaries today? | **No** |

### Interpretation

- The pack **almost certainly stores** region meshes / outlines in `regions.esf`.
- Without RPFM or a complete ESF tree walker that understands this CAAB layout, we did **not** export:
  - one polygon (or multipolygon) per region id
  - adjacency from pack connectivity
  - settlement slot positions tied to those polygons
- Therefore the project must **not** claim current provinces use pack region geometry.
- If a full ESF export is completed later, pack outlines may be used as **reference** to reshape Natural Earth–clipped provinces — still not as the coastline source.

## Are settlement / port coordinates recoverable?

| Source | Names/IDs | Geographic coordinates |
|---|---|---|
| `text/db/campaign_map_settlements.txt` | **Yes** — **92** `bos_*` settlement labels | No |
| `text/db/regions.txt` | **Yes** — **92** `bos_*` region labels | No |
| `text/db/campaign_map_towns_and_ports.txt` | **Yes** — port/town labels present | No |
| `db/campaign_map_settlements` binary | **Yes** — `bos_*` / `bos_*:*` keys | **No reliable lon/lat** (window float scan hits are non-geographic junk) |
| `db/campaign_map_towns_and_ports` binary | **Yes** — keys present | **No reliable lon/lat** |
| `regions.esf` settlement_and_slots | Schema tag present | Slot coordinates **not exported** in this pass |

**Verdict:** settlement/port **names and IDs** are recoverable; **geographic coordinates are not recovered** from the pack with the current tooling.

## Pack TGA / heightmap

- Present in extract (world TGA, heightmap.dat, detail masks).
- **Do not use** pack TGA as coastline.
- Natural Earth remains the authoritative land/water mask.

## Approved source roles (current)

| Role | Authority |
|---|---|
| Coastline / land-water | **Natural Earth** (public domain) |
| Settlement names, region names, ports, campaign anchors | **`world_test_9.pack`** as research reference |
| Potential region geometry reference | **`regions.esf`** only after a successful per-ID polygon export |
| Final color-ID map, adjacency, anchors, gameplay provinces | **Project generator** |

## Next step if pack geometry is desired later

1. Install RPFM CLI (or another maintained ESF exporter) and dump `regions.esf` to XML/JSON.
2. Export per-region outline vertices + region key join.
3. Transform campaign units → theatre lon/lat (or shared projected space).
4. Clip/reshape Natural Earth land cells with those outlines.
5. Keep pack binaries out of git; commit only project-owned derivatives if rights allow.
