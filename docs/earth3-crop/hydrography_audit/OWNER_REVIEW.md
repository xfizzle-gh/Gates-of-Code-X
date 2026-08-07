# Earth3 hydrography owner review

Production **unchanged** at 3510 / `a849b381…`.

LOO RMS **33.497 km**, max **122.532 km**. Kolguyev is not a control point.
North LOO: {'n': 14, 'rms_km': 13.498, 'max_km': 33.925}
Kolguyev holdout (not control): {'is_control_point': False, 'true_wgs84': [49.0, 69.1], 'predicted': [61.305, 65.9111], 'error_km': 630.531, 'note': 'Arctic source placement is east-biased vs true Kolguyev; identity uses archive src 11836.'}

| Label | geo_class | exact_id | conf | WGS84 | top IoU |
|---|---|---|---|---|---|
| NE01_Kolguyev | `CONFIRMED_MISSING_LAND_RESTORE` | Kolguyev Island | high | 61.305,65.9111 | Kama Reservoir iou=0.0 |
| NE02_Ladoga | `CONFIRMED_REAL_WATER_KEEP` | Lake Ladoga | high | 31.3531,60.8769 | Lake Ladoga iou=0.7674 |
| NE03_Onega | `CONFIRMED_REAL_WATER_KEEP` | Lake Onega | high | 35.4445,61.8718 | Lake Onega iou=0.4891 |
| NE04_WhiteSea_SE_large_hole | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 48.1973,65.2129 | (unnamed) iou=0.0 |
| NE05_Rybinsk | `CONFIRMED_REAL_WATER_KEEP` | Rybinsk Reservoir | high | 38.0981,58.5294 | Rybinsk Reservoir iou=0.4874 |
| NE06_Lake_Galichskoye | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | medium | 43.0087,58.4364 | Gorky Reservoir iou=0.0 |
| NE07_east_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 47.4908,57.5239 | Cheboksary Reservoir iou=0.0 |
| NE08_kama_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 53.4814,55.3128 | Nizhnekamsk Reservoir iou=0.0416 |
| MED01_Ibiza | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Ibiza | high | 1.4528,38.7957 | Lake Geneva iou=0.0 |
| MED02_Pantelleria | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Pantelleria | high | 12.0052,36.6927 | Lake Geneva iou=0.0 |
| MED03_Malta | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Malta | high | 14.3764,35.8266 | Lake Balaton iou=0.0 |
| MED04_Lemnos | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Lemnos | high | 25.0689,39.6806 | Beyşehir iou=0.0 |
| NA01_Chott_complex | `CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER` | Chott el Jerid complex (provisional) | medium | 8.5898,33.8551 | Lake Geneva iou=0.0 |

## Unresolved candidates

- **NE04_WhiteSea_SE_large_hole**: ['merged lakes/wetlands', 'exaggerated hydrography', 'false hole', 'missing land']
- **NE06_Lake_Galichskoye**: ['Lake Galichskoye', 'other Kostroma lakes']
- **NE07_east_volga_candidate**: ['Cheboksary Reservoir', 'local lakes near Yaransk/Shakhunya/Yoshkar-Ola', 'merged gap-fill']
- **NE08_kama_volga_candidate**: ['Nizhnekamsk Reservoir', 'Kuybyshev Reservoir', 'Kama arms', 'merged gap-fill']
