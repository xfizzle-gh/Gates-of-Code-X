# Earth3 hydrography owner review

Production **unchanged** at 3510 / `a849b381…`. Kolguyev preview **not** approved for production.

LOO RMS **33.497 km**, max **122.532 km**. Kolguyev is not a control point.
North LOO: {'n': 14, 'rms_km': 13.498, 'max_km': 33.925}
Kolguyev holdout (not control): {'is_control_point': False, 'true_wgs84': [49.0, 69.1], 'predicted': [61.305, 65.9111], 'error_km': 630.531, 'note': 'Arctic source placement is east-biased vs true Kolguyev; identity uses archive src 11836.'}

Geometry: **emitted triangle union only**. Metrics: **local LAEA meters** (not degree-area).

## Classifications

| Label | geo_class | exact_id | conf | WGS84 | top IoU (m) | geom |
|---|---|---|---|---|---|---|
| NE01_Kolguyev | `CONFIRMED_MISSING_LAND_RESTORE` | Kolguyev Island | high | 61.305,65.9111 | Kama Reservoir iou=0.0 | emitted_triangle_union |
| NE02_Ladoga | `CONFIRMED_REAL_WATER_KEEP` | Lake Ladoga | high | 31.3531,60.8769 | Lake Ladoga iou=0.8328 | emitted_triangle_union |
| NE03_Onega | `CONFIRMED_REAL_WATER_KEEP` | Lake Onega | high | 35.4445,61.8718 | Lake Onega iou=0.6217 | emitted_triangle_union |
| NE04_WhiteSea_SE_large_hole | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 48.1973,65.2129 | (unnamed) iou=0.0 | emitted_triangle_union |
| NE05_Rybinsk | `CONFIRMED_REAL_WATER_KEEP` | Rybinsk Reservoir | high | 38.0981,58.5294 | Rybinsk Reservoir iou=0.5584 | emitted_triangle_union |
| NE06_Lake_Galichskoye | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | medium | 43.0087,58.4364 | Gorky Reservoir iou=0.0 | emitted_triangle_union |
| NE07_east_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 47.4908,57.5239 | Cheboksary Reservoir iou=0.0 | emitted_triangle_union |
| NE08_kama_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 53.4814,55.3128 | Nizhnekamsk Reservoir iou=0.0448 | emitted_triangle_union |
| MED01_Ibiza | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Ibiza | high | 1.4528,38.7957 | Lake Geneva iou=0.0 | emitted_triangle_union |
| MED02_Pantelleria | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Pantelleria | high | 12.0052,36.6927 | Lake Geneva iou=0.0 | emitted_triangle_union |
| MED03_Malta | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Malta | high | 14.3764,35.8266 | Lake Balaton iou=0.0 | emitted_triangle_union |
| MED04_Lemnos | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Lemnos | high | 25.0689,39.6806 | Beyşehir iou=0.0 | emitted_triangle_union |
| NA01_Chott_complex | `CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER` | Chott el Jerid complex (provisional) | medium | 8.5898,33.8551 | Lake Geneva iou=0.0 | emitted_triangle_union |

## Unresolved candidates

- **NE04_WhiteSea_SE_large_hole**: ['merged lakes/wetlands', 'exaggerated hydrography', 'false hole', 'missing land']
- **NE06_Lake_Galichskoye**: ['Lake Galichskoye', 'other Kostroma lakes']
- **NE07_east_volga_candidate**: ['Cheboksary Reservoir', 'local lakes near Yaransk/Shakhunya/Yoshkar-Ola', 'merged gap-fill']
- **NE08_kama_volga_candidate**: ['Nizhnekamsk Reservoir', 'Kuybyshev Reservoir', 'Kama arms', 'merged gap-fill']

## Old convex-hull vs exact triangle-union

| Label | old_iou | new_iou | delta | class_changed |
|---|---:|---:|---:|---|
| NE01_Kolguyev | None | 0.0 | None | False |
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

## Kolguyev 3511 preview

- all_pass: `True`
- checks: `{"province_count_checked": 3511, "land_count_checked": 3296, "water_count_checked": 215, "failed_triangulations": 0, "empty_land_meshes": 0, "dangling_adjacency": 0, "retained_stable_id_mismatches": 0, "source_11836_count": 1, "e3_3512_count": 1, "e3_2830_count": 0, "e3_2888_count": 0, "production_dataset_unchanged": true, "composition": {"baseline_production_provinces": 3510, "added_kolguyev": 1, "assembled_preview": 3511, "note": "composed from proven 3510 production + isolated Kolguyev triangulation"}}`
- land neighbors: `[]`
