# Earth3 hydrography owner review (corrected georeference)

Production **unchanged**: 3510 / `a849b381…`.

Transform: **piecewise_regional_affine** · RMS **18.818 km** · max **73.242 km**
Reference: Natural Earth 10m lakes (public domain) + curated AoH3 city control georeference (Natural Earth data is public domain. AoH3 archive used locally for analysis only; not redistributed.)

## Feature table

| Label | geo_class | exact_identity | conf | WGS84 | NE top candidate |
|---|---|---|---|---|---|
| NE01_Kolguyev | `CONFIRMED_MISSING_LAND_RESTORE` | Kolguyev Island | high | 48.1268,68.7242 | — (? km) |
| NE02_Ladoga | `CONFIRMED_REAL_WATER_KEEP` | Lake Ladoga | high | 32.1911,60.7808 | Lake Ladoga (40.36 km) |
| NE03_Onega | `CONFIRMED_REAL_WATER_KEEP` | Lake Onega | high | 34.744,62.0064 | Lake Onega (41.35 km) |
| NE04_WhiteSea_SE_large_hole | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 44.02,66.3533 | — (? km) |
| NE05_Rybinsk | `CONFIRMED_REAL_WATER_KEEP` | Rybinsk Reservoir | high | 38.0041,58.6144 | Rybinsk Reservoir (12.76 km) |
| NE06_Lake_Galichskoye | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | medium | 42.9247,58.5125 | — (? km) |
| NE07_east_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 47.4271,57.5802 | — (? km) |
| NE08_kama_volga_candidate | `UNRESOLVED_REQUIRES_GEOGRAPHIC_MATCH` | UNRESOLVED | low | 53.4429,55.3344 | Nizhnekamsk Reservoir (68.16 km) |
| MED01_Ibiza | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Ibiza | high | 1.463,38.8039 | — (? km) |
| MED02_Pantelleria | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Pantelleria | high | 12.0053,36.6845 | — (? km) |
| MED03_Malta | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Malta | high | 14.3866,35.8348 | — (? km) |
| MED04_Lemnos | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | Lemnos | high | 25.0586,39.6812 | — (? km) |
| NA01_Chott_complex | `CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER` | Chott el Jerid complex (provisional) | medium | 8.5797,33.8619 | — (? km) |

## Details

### NE01_Kolguyev

Archive land source 11836 (ring_verts=239, area≈24725) is Kolguyev and is ABSENT from production crop. Transformed centroid ~(48.127,68.724).

### NE02_Ladoga

gap_0012 area=10704 class=water_presentation_gap hint=scandinavian_or_karelian_lake at ~(32.191,60.781); nearest cities ['Kokkorevo', 'Pitkyaranta', 'Priozersk']; NE top=[{'name': 'Lake Ladoga', 'centroid_lonlat': [31.4604, 60.8501], 'centroid_separation_km': 40.36, 'contains_point': True, 'area_deg2': 2.922682}]

### NE03_Onega

gap_0027 area=6239 class=water_presentation_gap hint=scandinavian_or_karelian_lake at ~(34.744,62.006); nearest cities ['Petrozavodsk', 'Pudozh', 'Oshta']; NE top=[{'name': 'Lake Onega', 'centroid_lonlat': [35.383, 61.7881], 'centroid_separation_km': 41.35, 'contains_point': True, 'area_deg2': 1.706569}, {'name': '(unnamed NE lake)', 'centroid_lonlat': [36.9105, 62.3285], 'centroid_separation_km': 118.03, 'contains_point': False, 'area_deg2': 0.056002}]

### NE04_WhiteSea_SE_large_hole

gap_0039 area=22708 near Koynas/Mezen hinterland ~(44.020,66.353). NE candidates []. Could be merged lakes, wetlands, or exaggerated hole.

### NE05_Rybinsk

gap_0025 area=2751 class=water_presentation_gap hint=inland_lake_or_lagoon at ~(38.004,58.614); nearest cities ['Breitovo', 'Poshekhonye', 'Vesyegonsk']; NE top=[{'name': 'Rybinsk Reservoir', 'centroid_lonlat': [38.1998, 58.5618], 'centroid_separation_km': 12.76, 'contains_point': False, 'area_deg2': 0.750606}, {'name': 'Ozero Kubenskoye', 'centroid_lonlat': [39.4694, 59.6533], 'centroid_separation_km': 142.59, 'contains_point': False, 'area_deg2': 0.071155}]

### NE06_Lake_Galichskoye

gap_0038 area=7772 class=water_presentation_gap hint=inland_lake_or_lagoon at ~(42.925,58.513); nearest cities ['Galich', 'Kadyi', 'Chukhloma']; NE top=[]

### NE07_east_volga_candidate

gap gap_0045 area=6238 at ~(47.427,57.580); cities ['Yaransk', 'Shakhunya', 'Yoshkar Ola']; NE candidates []. Not high-confidence named without stronger polygon overlap.

### NE08_kama_volga_candidate

gap gap_0044 area=11171 at ~(53.443,55.334); cities ['Tuymazy', 'Oktyabrsky', 'Naberezhnye Chelny']; NE candidates ['Nizhnekamsk Reservoir']. Not high-confidence named without stronger polygon overlap.

### MED01_Ibiza

Production land e3_1439 source 2274 present with 2 triangles; simplified ring kept. Coastline=#121.

### MED02_Pantelleria

Production land e3_1978 source 4693 present with 2 triangles; simplified ring kept. Coastline=#121.

### MED03_Malta

Production land e3_0270 source 270 present with 2 triangles; simplified ring kept. Coastline=#121.

### MED04_Lemnos

Production land e3_1738 source 3220 present with 11 triangles; simplified ring kept. Coastline=#121.

### NA01_Chott_complex

gap_0008 near Tozeur/Gafsa/Gabes ~(8.580,33.862). Consistent with Tunisian chott/salt-basin complex; exact basin outline needs OSM/NE overlay review.

## Notes

- `geographic_classification` vs `exact_feature_identity` are separate fields.
- HIGH confidence exact names require low residual + NE proximity/containment.
- Kolguyev restore is preview-only until owner approval.
- Square islands unchanged; coastline work is #121.
- Do not begin #74 PR B until this package is accepted.

## NE07 candidate list
- Cheboksary Reservoir
- local lakes/wetlands near Yaransk / Shakhunya / Yoshkar-Ola
- merged or exaggerated gap-fill

## NE08 candidate list
- Nizhnekamsk Reservoir (nearest NE named water in subset)
- Kuybyshev Reservoir
- Kama River reservoir arms
- malformed merged gap-fill

## NE06
Test first against **Lake Galichskoye** (not "Volga mid reservoir"). Currently exact identity UNRESOLVED pending closer NE polygon match (Galich control residual elevated).

