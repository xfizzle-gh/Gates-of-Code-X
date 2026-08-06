# Earth3 Europe–Mediterranean crop candidates

**Status:** awaiting owner crop approval on GitHub issue **#92**.

**Permission:** Earth3 province geometry and adjacency may be used, converted, modified, and redistributed in Gates of Code:X (`APPROVED_EXACT_IMPORT_CROPPED_THEATRE`). The original 81 MB archive and AoH3 background tiles are **not** committed.

## What this folder contains

| File | Purpose |
|---|---|
| `preview_em_ref_tight.png` | Candidate A preview |
| `preview_em_north_east_expand.png` | Candidate B preview |
| `preview_em_south_west_expand.png` | Candidate C preview |
| `crop_candidates_audit.json` | Machine-readable counts, region coverage, diffs, assumptions |

Crop definitions: `config/earth3/crop_candidates_v1.json`

## Rules (enforced)

- Whole Earth3 polygons only (no clipped slivers)
- Not `continent == Europe`
- Far-northern Scandinavia cut by `min_y`
- Iceland retained (centroids sit below far-north cutoff)
- Required theatre coverage checked via Earth3 city anchors (Crimea/Kherson/Zaporizhzhia/Donetsk/Luhansk/Rostov, etc.)
- Murmansk must remain outside the crop
- No AoH3 scenarios/owners/background art imported
- No production normalized subset committed until crop approval

## Candidate summary (from last local archive run)

| ID | Provinces | Land | Water* | Vertices | Edges | Land components |
|---|---:|---:|---:|---:|---:|---:|
| **em_ref_tight** (recommended) | 4371 | 4087 | 284 | 443943 | 12779 | 29 |
| em_north_east_expand | 4492 | 4201 | 291 | 462234 | 13128 | 29 |
| em_south_west_expand | 4497 | 4201 | 296 | 462223 | 13142 | 30 |

\*Ocean-continent provinces inside the crop.

## Regenerating previews

```powershell
$env:PYTHONPATH = "src"
python tools/earth3/render_crop_previews.py `
  --archive "C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip"
```

Requires local archive path + optional `Pillow` for PNG output.

## Assumptions needing owner eyes

- Arkhangelsk can still fall inside the northern Russian fringe of `em_ref_tight`; raise `min_y` or add exclude IDs if too deep.
- ~26 source name-points lie outside their polygon rings (flagged; do not block crop choice).
- Disconnected land components (~29) are expected (islands); ferry/sea-lane crossings are **not** invented here.

## Next step

Owner selects one candidate (or requests a revised rect / include-exclude list) on **#92**. Only then commit the normalized production subset and continue the PR chain (stable IDs → geometry renderer → operational graph → migration).
