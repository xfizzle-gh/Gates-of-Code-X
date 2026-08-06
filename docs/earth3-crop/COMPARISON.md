# Earth3 crop candidate comparison

**Status:** awaiting owner approval on #92. **No production recommendation.**

| ID | Mode | Provinces | Land | Water | Vertices | Edges | Components | Threshold review |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `em_ref_tight` | rect_centroid | 4371 | 4087 | 284 | 443943 | 12779 | 29 | 0 |
| `em_north_east_expand` | rect_centroid | 4492 | 4201 | 291 | 462234 | 13128 | 29 | 0 |
| `em_south_west_expand` | rect_centroid | 4497 | 4201 | 296 | 462223 | 13142 | 30 | 0 |
| `em_reference_masked` | mask_overlap | 3238 | 3037 | 201 | 282374 | 9450 | 24 | 0 |

## em_reference_masked vs em_ref_tight

- added vs tight: **0**
- removed vs tight: **1133**
- required includes: `[950, 951, 952, 953, 954, 955, 956, 957, 958, 959, 960, 961, 962, 963, 964, 6847, 6848, 6849, 6850, 6851, 1268, 1271, 3782, 6627, 10868, 10869, 12175, 10431, 10436, 2654, 1116, 2207, 2669, 1365, 1028, 1194, 3003, 4796, 4808, 4971, 6193, 6202, 6632, 6677, 10890, 12180, 12187, 12189, 12307, 13346]`
- explicit excludes: `[11370, 11764, 10857, 11170, 11323, 11689, 10919, 10587, 11177, 11180, 2624, 3507, 10577, 6162, 6091, 6163, 1022, 1024, 1044, 1451, 2593, 3741, 3746, 4294, 4401, 4407, 4945, 4946, 4956, 4959, 6070, 6194, 6679, 6685, 7319, 11559, 11580, 11601, 11649, 12037, 13076, 13151, 13350, 13352]`
- threshold review count: **0**
- source bounds: `[7084.0, 648.0, 10855.0, 3648.0]`
- export rect: `(7064,628)-(10875,3668)`

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

