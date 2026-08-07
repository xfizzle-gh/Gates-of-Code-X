# Earth3 hydrography owner review

Production **unchanged** at 3510 / `a849b381…`.

## Exact owner-circle render trace

See `owner_circle_render_trace.json` and `evidence/owner_circles_numbered_traced.png`.

Godot model: land triangle fills only; water not meshed; `ocean_gap_fills` **not** drawn;
continuous ocean underlay; borders from province rings (no pure water–water).

| Circle | pixel | final | recommendation |
|---|---|---|---|
| NE01_northern_outline | `continuous_water_background` | `CROP_EDGE_PRESENTATION_ARTIFACT` | no_production_change_document_crop_edge_presentation |
| NE02_Ladoga | `gap_fill_metadata_ocean_shows_through` | `REAL_WATER_KEEP` | keep |
| NE03_Onega | `gap_fill_metadata_ocean_shows_through` | `REAL_WATER_KEEP` | keep |
| NE04_WhiteSea_SE_large_hole | `gap_fill_metadata_ocean_shows_through` | `SOURCE_GEOMETRY_DEFECT` | owner_ruling_restore_excluded_land_or_accept_water_gap_presentation |
| NE05_Rybinsk | `gap_fill_metadata_ocean_shows_through` | `REAL_WATER_KEEP` | keep |
| NE06_Galich_area | `gap_fill_metadata_ocean_shows_through` | `SOURCE_GEOMETRY_DEFECT` | owner_ruling_restore_excluded_land_or_accept_water_gap_presentation |
| NE07_east_volga | `gap_fill_metadata_ocean_shows_through` | `SOURCE_GEOMETRY_DEFECT` | owner_ruling_restore_excluded_land_or_accept_water_gap_presentation |
| NE08_kama_volga | `gap_fill_metadata_ocean_shows_through` | `SOURCE_GEOMETRY_DEFECT` | owner_ruling_restore_excluded_land_or_accept_water_gap_presentation |

### NE01 top outline

- Sample map-local **(4220, 660)** / source **(11296, 802)**
- Archive land **src 11836 Fion** at point; **not in production**
- v7 mask overlap 0 — exterior crop exclusion inside image bounds
- Classification: **CROP_EDGE_PRESENTATION_ARTIFACT**
- **Not Kolguyev** (~624 km from 49.25E/69.08N); true Kolguyev source still unresolved

### NE04 / NE06 / NE07 / NE08

Each is a dataset `ocean_gap_fill` over a crop **explicit_exclude_ids** land province:

| Circle | gap | excluded src | city |
|---|---|---:|---|
| NE04 | gap_0039 | 11790 | Koynas |
| NE06 | gap_0038 | 11689 | Galich |
| NE07 | gap_0045 | 11170 | Yaransk |
| NE08 | gap_0044 | 11323 | Tuymazy |

Classification: **SOURCE_GEOMETRY_DEFECT** — not confirmed real water at gap scale.
Recommendation: owner ruling to restore excluded land **or** accept water-gap presentation.

### Confirmed keep

- Ladoga, Onega, Rybinsk — REAL_WATER_KEEP
- Ibiza, Pantelleria, Malta, Lemnos — simplified real islands

### Removed from merge package

- `godot/assets/maps/earth3_europe_mediterranean_src11836_preview/`
- prior Kolguyev-labelled 11836 screenshots

Identity reports retained: `source_11836_identity_report.json`, Ural boundary overlay,
`kolguyev_true_island_search.json`.

