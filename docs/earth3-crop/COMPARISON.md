# Earth3 crop candidate comparison

**Status:** awaiting owner approval on #92. **No production recommendation.**

| ID | Mode | Provinces | Land | Water | Vertices | Edges | Components | Threshold review |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `em_ref_tight` | rect_centroid | 4371 | 4087 | 284 | 443943 | 12779 | 29 | 0 |
| `em_north_east_expand` | rect_centroid | 4492 | 4201 | 291 | 462234 | 13128 | 29 | 0 |
| `em_south_west_expand` | rect_centroid | 4497 | 4201 | 296 | 462223 | 13142 | 30 | 0 |
| `em_reference_masked` | mask_overlap | 3074 | 2875 | 199 | 268261 | 8961 | 24 | 0 |

## em_reference_masked vs em_ref_tight

- added vs tight: **0**
- removed vs tight: **1297**
- required includes: `[950, 951, 952, 953, 954, 955, 956, 957, 958, 959, 960, 961, 962, 963, 964, 6847, 6848, 6849, 6850, 6851, 1268, 1271, 3782, 6627, 10868, 10869, 12175, 10431, 10436, 2654, 1116, 2207, 2669, 1365, 1028, 1227, 1228, 2670, 2706, 3003, 4348, 4859, 4895, 6632, 6677, 10826, 12180, 12187, 12189, 12451, 12906]`
- explicit excludes: `[11370, 11764, 10857, 11170, 11323, 11689, 10919, 10587, 11177, 11180, 2624, 3507, 10577, 1194, 6162, 6091, 6163, 6193, 6202, 4796, 12307, 1022, 1024, 1044, 1348, 1369, 1379, 1451, 3741, 3746, 4410, 4735, 5051, 5054, 6679, 6685, 10890, 11174, 11559, 11580, 11601, 11649, 12037, 12118, 12508, 13076, 13151, 13352]`
- threshold review count: **0**
- source bounds: `[7084.0, 648.0, 10855.0, 3629.0]`
- export rect: `(7064,628)-(10875,3649)`

### Region coverage (masked)

- OK `Balkans_Greece`
- OK `Baltic`
- OK `Britain_Ireland`
- OK `Caucasus_edge`
- OK `Far_north_should_exclude`
- OK `France_Benelux_Germany`
- OK `Iberia`
- OK `Iceland`
- OK `Italy`
- OK `North_Africa_coast`
- OK `Rostov_approach`
- OK `Turkey`
- OK `Ukraine_Crimea_Donbas`

## Legend

- gold outline = query rect (broad phase)
- magenta outline = authored mask rings
- green outline = reference extent trace
- cyan outline = export bounds of included polygons
- red labels = Murmansk / Arkhangelsk

## Files

- `preview_<id>.png` — shared-camera overviews
- `closeups/<id>_*.png` — Scandinavia/N.Russia, Ukraine/Donbas/Caucasus, N.Africa/E.Med
- `crop_candidates_audit.json` — machine audit

