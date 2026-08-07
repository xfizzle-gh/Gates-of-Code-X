# Earth3 hydrography owner review

Production **unchanged** at 3510 / `a849b381…`.

**Source 11836 is NOT Kolguyev.** It is mainland Fion (northern Urals / Komi–Yamal).
True Kolguyev (~49.25E, 69.08N) source polygon: **UNRESOLVED — no archive land polygon matches Kolguyev island criteria near 49.25E/69.08N**.

LOO RMS **33.497 km**, max **122.532 km**.
North LOO: {'n': 14, 'rms_km': 13.498, 'max_km': 33.925}

Geometry: **emitted triangle union**. Metrics: **local LAEA meters**.

## Classifications

| Label | geo_class | exact_id | conf | WGS84 | top IoU (m) |
|---|---|---|---|---|---|
| NE01_source11836_Fion_northern_Urals | `UNRESOLVED_MISSING_MAINLAND_OR_CROP_BOUNDARY_DEFECT` | UNRESOLVED | high | 61.305,65.9111 | Kama Reservoir iou=0.0 |
| NE02_Ladoga | `CONFIRMED_REAL_WATER_KEEP` | Lake Ladoga | high | 31.3531,60.8769 | Lake Ladoga iou=0.8328 |
| NE03_Onega | `CONFIRMED_REAL_WATER_KEEP` | Lake Onega | high | 35.4445,61.8718 | Lake Onega iou=0.6217 |
| NE04_WhiteSea_SE_large_hole | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 48.1973,65.2129 | (unnamed) iou=0.0 |
| NE05_Rybinsk | `CONFIRMED_REAL_WATER_KEEP` | Rybinsk Reservoir | high | 38.0981,58.5294 | Rybinsk Reservoir iou=0.5584 |
| NE06_Lake_Galichskoye | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | medium | 43.0087,58.4364 | Gorky Reservoir iou=0.0 |
| NE07_east_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 47.4908,57.5239 | Cheboksary Reservoir iou=0.0 |
| NE08_kama_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 53.4814,55.3128 | Nizhnekamsk Reservoir iou=0.0448 |
| MED01_Ibiza | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Ibiza | high | 1.4528,38.7957 | Lake Geneva iou=0.0 |
| MED02_Pantelleria | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Pantelleria | high | 12.0052,36.6927 | Lake Geneva iou=0.0 |
| MED03_Malta | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Malta | high | 14.3764,35.8266 | Lake Balaton iou=0.0 |
| MED04_Lemnos | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Lemnos | high | 25.0689,39.6806 | Beyşehir iou=0.0 |
| NA01_Chott_complex | `CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER` | Chott el Jerid complex (provisional) | medium | 8.5898,33.8551 | Lake Geneva iou=0.0 |

## Source 11836 identity

- predicted WGS: [61.3733, 66.1381]
- distance to true Kolguyev: 607.3 km
- region: northern_Urals / Komi–Yamal mainland (Fion / Pechora basin periphery)
- v7 mask overlap: 0.0
- shared land contacts: 8
- bordering source-water: []
- overlay: docs/earth3-crop/hydrography_audit/evidence/overlay_NE01_source11836_Fion_ural_boundary.png

## Actual Kolguyev search

- result: **UNRESOLVED — no archive land polygon matches Kolguyev island criteria near 49.25E/69.08N**
- accepted source id: `None`
- note: Closest named production land near the longitude is src 11768 (Indiga), already in 3510, mainland with multiple land contacts. No separate island polygon for Kolguyev was found. Source 11836 is mainland Fion ~630 km away and is not a candidate.

## Diagnostic src11836 preview

- path: `godot/assets/maps/earth3_europe_mediterranean_src11836_preview/`
- all_pass: `True`
- checks: `{"province_count_checked": 3511, "land_count_checked": 3296, "water_count_checked": 215, "all_3511_triangle_rows_valid": true, "failed_triangulations_land_and_water": 0, "no_empty_land_meshes": true, "no_empty_water_meshes": true, "no_dangling_adjacency": true, "no_stable_id_mismatches": true, "source_11836_count": 1, "diagnostic_id_count": 1, "e3_2830_count": 0, "e3_2888_count": 0, "production_dataset_unchanged": true, "mainland_adjacency_derived": true, "not_using_empty_neighbors_for_mainland": true, "composition": {"baseline_production_provinces": 3510, "added_src11836_mainland": 1, "assembled_diagnostic_preview": 3511, "audit_scope": "all_3511_rows_land_and_water_triangle_reconstruction"}}`
- land neighbors (derived): `['e3_3178', 'e3_3180']`
- ID not reserved for production

## Removed stale evidence


## Old hull vs exact triangle-union

| Label | old_iou | new_iou | delta | class_changed |
|---|---:|---:|---:|---|
| NE01_source11836_Fion_northern_Urals | None | 0.0 | None | False |
| NE02_Ladoga | 0.7674 | 0.8328 | 0.0654 | False |
| NE03_Onega | 0.4891 | 0.6217 | 0.1326 | False |
| NE04_WhiteSea_SE_large_hole | 0.0 | 0.0 | 0.0 | False |
| NE05_Rybinsk | 0.4874 | 0.5584 | 0.071 | False |
| NE06_Lake_Galichskoye | 0.0 | 0.0 | 0.0 | False |
| NE07_east_volga_candidate | 0.0 | 0.0 | 0.0 | False |
| NE08_kama_volga_candidate | 0.0416 | 0.0448 | 0.0032 | False |
| MED01_Ibiza | 0.0 | 0.0 | 0.0 | False |
| MED02_Pantelleria | 0.0 | 0.0 | 0.0 | False |
| MED03_Malta | 0.0 | 0.0 | 0.0 | False |
| MED04_Lemnos | 0.0 | 0.0 | 0.0 | False |
| NA01_Chott_complex | 0.0 | 0.0 | 0.0 | False |
