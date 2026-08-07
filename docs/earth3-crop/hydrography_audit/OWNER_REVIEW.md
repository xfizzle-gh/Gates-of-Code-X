# Earth3 hydrography owner review

Audit only — **production F5 unchanged** (3510 / `a849b381…`).

Geographic reference: Natural Earth 110m/50m cultural+physical (conceptual comparison) + AoH3 Earth3 city labels
License: Natural Earth: public domain. AoH3 archive: local analysis only, not redistributed.

## Summary counts

- **CONFIRMED_REAL_WATER_KEEP**: 6 — NE02_Ladoga, NE03_Onega, NE05_Rybinsk, NE06_Volga_mid_reservoir, NE07_Cheboksary_system, NE08_Kuybyshev_Samara_arm
- **CONFIRMED_REAL_ISLAND_RESTORE_FILL**: 0 — —
- **CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP**: 4 — MED01_Ibiza, MED02_Pantelleria, MED03_Malta, MED04_Lemnos
- **CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER**: 1 — NA01_Chott_or_basin
- **CONFIRMED_MISSING_LAND_RESTORE**: 1 — NE01_Kolguyev
- **CONFIRMED_RENDERER_HOLE_FIX**: 0 — —
- **UNRESOLVED_REQUIRES_OWNER_RULING**: 1 — NE04_WhiteSea_SE_large_hole

## Feature table

| Label | Hypothesis | Nearest name | Type | Action | Confidence |
|---|---|---|---|---|---|
| NE01_Kolguyev | Kolguyev Island | Fion | omitted_source_land_province | `CONFIRMED_MISSING_LAND_RESTORE` | high |
| NE02_Ladoga | Lake Ladoga | Kokkorevo | gap_fill_interior_hole | `CONFIRMED_REAL_WATER_KEEP` | high |
| NE03_Onega | Lake Onega | Petrozavodsk | gap_fill_interior_hole | `CONFIRMED_REAL_WATER_KEEP` | high |
| NE04_WhiteSea_SE_large_hole | Large hole SE of White Sea / Mezen basin (possible Lacha-Kenozero region or exaggerated hole) | Koynas | gap_fill_interior_hole | `UNRESOLVED_REQUIRES_OWNER_RULING` | medium |
| NE05_Rybinsk | Rybinsk Reservoir | Breitovo | gap_fill_interior_hole | `CONFIRMED_REAL_WATER_KEEP` | high |
| NE06_Volga_mid_reservoir | Volga mid reservoir / Kostroma-Galich lake cluster | Galich | gap_fill_interior_hole | `CONFIRMED_REAL_WATER_KEEP` | high |
| NE07_Cheboksary_system | Cheboksary / Volga reservoir system | Yaransk | gap_fill_interior_hole | `CONFIRMED_REAL_WATER_KEEP` | high |
| NE08_Kuybyshev_Samara_arm | Kuybyshev (Samara) Reservoir arm | Tuymazy | gap_fill_interior_hole | `CONFIRMED_REAL_WATER_KEEP` | high |
| MED01_Ibiza | Ibiza | Ibiza | province_polygon | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | high |
| MED02_Pantelleria | Pantelleria | Pantelleria | province_polygon | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | high |
| MED03_Malta | Malta / Valletta | Valletta | province_polygon | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | high |
| MED04_Lemnos | Lemnos / Myrina | Myrina | province_polygon | `CONFIRMED_REAL_ISLAND_SIMPLIFIED_GEOMETRY_KEEP` | high |
| NA01_Chott_or_basin | North African chott / salt basin (Chott el Jerid region) | Tozeur | gap_fill_interior_hole | `CONFIRMED_REAL_SALT_BASIN_KEEP_OR_DEFER` | high |

## Evidence notes

### NE01_Kolguyev

Archive source_id=11836 is land (terrain_id=5, ring_verts=239, area≈24725) centered near Kolguyev; ABSENT from production included set. Visual outline likely residual water/coast geometry without land mesh.

- local xy: `[4220.0, 660.0]` source xy: `[11296.0, 802.0]` approx lon/lat: `48.973, 69.1465`

### NE02_Ladoga

Matches ocean_gap_fills gap_0012 area=10704 classification=water_presentation_gap region_hint=scandinavian_or_karelian_lake. Nearest cities Kokkorevo, Pitkyaranta, Priozersk. Continuous-ocean renderer correctly shows interior water (non-selectable).

- local xy: `[2803.0, 1052.0]` source xy: `[9879.0, 1194.0]` approx lon/lat: `20.25, 61.3977`

### NE03_Onega

Matches ocean_gap_fills gap_0027 area=6239 classification=water_presentation_gap region_hint=scandinavian_or_karelian_lake. Nearest cities Petrozavodsk, Pudozh, Oshta. Continuous-ocean renderer correctly shows interior water (non-selectable).

- local xy: `[2996.0, 978.0]` source xy: `[10072.0, 1120.0]` approx lon/lat: `24.1622, 62.8605`

### NE04_WhiteSea_SE_large_hole

gap_0039 area=22708 near Koynas (Arkhangelsk/Mezen hinterland). May be merged/exaggerated hydrography rather than a single named great lake; not proven false. Do not fill without stronger proof.

- local xy: `[3618.0, 685.0]` source xy: `[10694.0, 827.0]` approx lon/lat: `36.7703, 68.6523`

### NE05_Rybinsk

Matches ocean_gap_fills gap_0025 area=2751 classification=water_presentation_gap region_hint=inland_lake_or_lagoon. Nearest cities Breitovo, Poshekhonye, Rybinsk. Continuous-ocean renderer correctly shows interior water (non-selectable).

- local xy: `[3133.0, 1255.0]` source xy: `[10209.0, 1397.0]` approx lon/lat: `26.9392, 57.3849`

### NE06_Volga_mid_reservoir

Matches ocean_gap_fills gap_0038 area=7772 classification=water_presentation_gap region_hint=inland_lake_or_lagoon. Nearest cities Galich, Kadyi, Chukhloma. Continuous-ocean renderer correctly shows interior water (non-selectable).

- local xy: `[3376.0, 1273.0]` source xy: `[10452.0, 1415.0]` approx lon/lat: `31.8649, 57.0291`

### NE07_Cheboksary_system

Matches ocean_gap_fills gap_0045 area=6238 classification=water_presentation_gap region_hint=inland_lake_or_lagoon. Nearest cities Yaransk, Shakhunya, Yoshkar Ola. Continuous-ocean renderer correctly shows interior water (non-selectable).

- local xy: `[3597.0, 1356.0]` source xy: `[10673.0, 1498.0]` approx lon/lat: `36.3446, 55.3884`

### NE08_Kuybyshev_Samara_arm

Matches ocean_gap_fills gap_0044 area=11171 classification=water_presentation_gap region_hint=inland_lake_or_lagoon. Nearest cities Tuymazy, Oktyabrsky, Naberezhnye Chelny. Continuous-ocean renderer correctly shows interior water (non-selectable).

- local xy: `[3889.0, 1546.0]` source xy: `[10965.0, 1688.0]` approx lon/lat: `42.2635, 51.6326`

### MED01_Ibiza

Production land e3_1439 source_id=2274 area=891.0 ring_verts=4 triangles=2. City anchor supports Ibiza. Rectangular/low-vert rings are simplified real islands — KEEP IDs; coastline work is #121.

- local xy: `[1340.0, 2730.0]` source xy: `[8416.0, 2872.0]` approx lon/lat: `-9.4054, 28.2279`

### MED02_Pantelleria

Production land e3_1978 source_id=4693 area=506.0 ring_verts=4 triangles=2. City anchor supports Pantelleria. Rectangular/low-vert rings are simplified real islands — KEEP IDs; coastline work is #121.

- local xy: `[1854.0, 2860.0]` source xy: `[8930.0, 3002.0]` approx lon/lat: `1.0135, 25.6581`

### MED03_Malta

Production land e3_0270 source_id=270 area=1287.0 ring_verts=4 triangles=2. City anchor supports Malta / Valletta. Rectangular/low-vert rings are simplified real islands — KEEP IDs; coastline work is #121.

- local xy: `[1970.0, 2912.0]` source xy: `[9046.0, 3054.0]` approx lon/lat: `3.3649, 24.6302`

### MED04_Lemnos

Production land e3_1738 source_id=3220 area=465.0 ring_verts=28 triangles=11. City anchor supports Lemnos / Myrina. Rectangular/low-vert rings are simplified real islands — KEEP IDs; coastline work is #121.

- local xy: `[2492.0, 2678.0]` source xy: `[9568.0, 2820.0]` approx lon/lat: `13.9459, 29.2558`

### NA01_Chott_or_basin

gap_0008 area=1629 near Tozeur/Gafsa/Gabes — consistent with Chott el Jerid / Tunisian salt-basin complex. Keep as water presentation; terrain styling deferred to PR B / visual hierarchy.

- local xy: `[1686.0, 3032.0]` source xy: `[8762.0, 3174.0]` approx lon/lat: `-2.3919, 22.2581`

## Production policy

- Do **not** change production for UNRESOLVED items.
- CONFIRMED_REAL_WATER_KEEP / SIMPLIFIED_ISLAND_KEEP / SALT_BASIN: no production geometry change.
- CONFIRMED_MISSING_LAND_RESTORE (Kolguyev): requires separate owner-approved crop inclusion PR; not auto-applied.
- Island coastline reconstruction remains **#121**.
- Do not begin #74 PR B until owner accepts this package.
