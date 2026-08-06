# Earth3 Europe–Mediterranean crop candidates

**Status:** awaiting owner crop approval on GitHub issue **#92**.

Permission has been obtained to use/convert/modify/redistribute applicable AoH3 Earth3 province geometry for Gates of Code:X. The original 81 MB archive and AoH3 background tiles are **not** committed.

## What this folder contains

| File | Purpose |
|---|---|
| `preview_em_ref_tight.png` | Candidate A preview |
| `preview_em_north_east_expand.png` | Candidate B preview |
| `preview_em_south_west_expand.png` | Candidate C preview |
| `crop_candidates_audit.json` | Machine-readable counts, diffs, assumptions |

Crop definitions: `config/earth3/crop_candidates_v1.json`

## Rules (enforced)

- Whole Earth3 polygons only (no clipped slivers)
- Not `continent == Europe`
- Far-northern Scandinavia cut by `min_y`
- Iceland retained (centroids sit below far-north cutoff)
- No AoH3 scenarios/owners/background art imported
- No production normalized subset committed until crop approval

## Regenerating previews

```powershell
$env:PYTHONPATH = "src"
python tools/earth3/render_crop_previews.py `
  --archive "C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip"
```

## Next step

Owner selects one candidate (or requests a revised rect). Only then commit the normalized production subset and continue the PR chain (IDs → renderer → operational graph → migration).
