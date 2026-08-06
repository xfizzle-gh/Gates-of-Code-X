# Earth3 Europe–Mediterranean crop candidates

**Status:** awaiting owner crop approval on GitHub issue **#92**.  
**No production recommendation** in this package.

**Permission:** Earth3 province geometry and adjacency may be used, converted, modified, and redistributed in Gates of Code:X (`APPROVED_EXACT_IMPORT_CROPPED_THEATRE`). The original 81 MB archive and AoH3 background tiles are **not** committed.

## Comparison package

| File | Purpose |
|---|---|
| `preview_em_ref_tight.png` | Rect A — shared camera |
| `preview_em_north_east_expand.png` | Rect B — shared camera |
| `preview_em_south_west_expand.png` | Rect C — shared camera |
| `preview_em_reference_masked.png` | **Mask D** — shared camera |
| `closeups/*_scandinavia_north_russia.png` | N Scandinavia / N Russia close-up |
| `closeups/*_ukraine_donbas_caucasus.png` | Crimea / Donbas / Rostov / Caucasus |
| `closeups/*_north_africa_east_med.png` | Maghreb / E.Med close-up |
| `crop_candidates_audit.json` | Machine audit |
| `COMPARISON.md` | Human summary |

Crop definitions: `config/earth3/crop_candidates_v1.json` (schema v2)

## Selection rules

| Candidate | Mode | Authority |
|---|---|---|
| `em_ref_tight` / N-E / S-W | `rect_centroid` | axis-aligned rect (comparison only) |
| **`em_reference_masked`** | `mask_overlap` | authored multi-ring mask + area overlap ratio |

Masked inclusion:

1. Broad-phase AABB = query rect ∩ mask bounds  
2. `overlap_ratio = area(province ∩ mask) / area(province)` via ear-clip + Sutherland–Hodgman  
3. Include whole Earth3 polygon if `ratio >= 0.35`  
4. Flag review if `0.15 <= ratio <= 0.50`  
5. `required_include_ids` / `explicit_exclude_ids` override  
6. **Never clip** province rings  

## Latest counts

| ID | Mode | Provinces | Land | Water | Vertices | Edges | Components | Review |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| em_ref_tight | rect | 4371 | 4087 | 284 | 443943 | 12779 | 29 | 0 |
| em_north_east_expand | rect | 4492 | 4201 | 291 | 462234 | 13128 | 29 | 0 |
| em_south_west_expand | rect | 4497 | 4201 | 296 | 462223 | 13142 | 30 | 0 |
| **em_reference_masked** | mask | **3648** | 3431 | 217 | 333352 | 10642 | 25 | 55 |

`em_reference_masked` vs `em_ref_tight`: **−723** provinces (0 added).  
Murmansk + Arkhangelsk excluded on masked candidate. All required region city-anchors OK.

## Legend (previews)

- **gold** = query rect (broad phase)  
- **magenta** = authored mask rings  
- **green** = reference extent outline  
- **cyan** = export bounds of included polygons  
- **red labels** = Murmansk / Arkhangelsk  
- **red muted fills** = excluded boundary-touch provinces  

## Authoritative geometry engine

**Shapely is mandatory** for authoritative Earth3 mask crop generation
(`AUTHORITATIVE_GEOMETRY_ENGINE = "shapely"`).

- Install: `pip install -e ".[earth3]"`
- If Shapely is missing, crop generation **fails closed** (no silent stdlib fallback).
- The stdlib ear-clip path is comparison/oracle tooling only.

## Local archive audit (committed machine-readable)

| File | Role |
|---|---|
| `local_crop_audit.json` | Local-only archive run results (hashes, oracle, counts, locations) |
| `boundary_review_em_reference_masked.json` | 55 threshold-band boundary review rows |
| `BOUNDARY_REVIEW.md` | Human-readable boundary review sheet |

CI validates the **committed audit artifact schema/hashes/counts** without the archive.
Archive-dependent unittest cases skip with **`LOCAL SOURCE REQUIRED`** when the zip is absent.

## Regenerating (local archive required)

```powershell
$env:PYTHONPATH = "src"
pip install -e ".[earth3]" Pillow
python tools/earth3/generate_local_audit.py `
  --archive "C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip"
python tools/earth3/render_crop_previews.py `
  --archive "C:\Users\paulf\Downloads\AOH3_Earth3_map_provinces.zip"
```

The original archive is never committed.

## Next step

Owner reviews the four-candidate package on **#92** (especially `em_reference_masked` and close-ups).  
Only after explicit approval: commit normalized production subset + stable Gates IDs.
