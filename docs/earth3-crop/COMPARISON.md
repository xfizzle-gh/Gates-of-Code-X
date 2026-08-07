# Earth3 crop candidate comparison

**Status:** awaiting owner approval on #92. **No production recommendation.**

| ID | Mode | Provinces | Land | Water | Vertices | Edges | Components | Threshold review |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `em_ref_tight` | rect_centroid | 4371 | 4087 | 284 | 443943 | 12779 | 29 | 0 |
| `em_north_east_expand` | rect_centroid | 4492 | 4201 | 291 | 462234 | 13128 | 29 | 0 |
| `em_south_west_expand` | rect_centroid | 4497 | 4201 | 296 | 462223 | 13142 | 30 | 0 |
| `em_reference_masked` | mask_overlap | 3345 | 3133 | 212 | 320116 | 9756 | 23 | 43 |

## em_reference_masked vs em_ref_tight

- added vs tight: **30**
- removed vs tight: **1056**
- required includes: `[950, 951, 952, 953, 954, 955, 956, 957, 958, 959, 960, 961, 962, 963, 964, 6847, 6848, 6849, 6850, 6851, 1268, 1271, 3782, 6627, 10868, 10869, 12175, 10431, 10436, 2654, 1116, 2207, 2669, 1365, 2662, 2666, 2683, 2707, 2668, 3723, 8065, 12580, 4686, 8066, 6087, 3719, 6085, 5052, 1096, 1464, 11120, 1458, 1077, 1054, 11656]`
- explicit excludes: `[11764, 10857, 11170, 11323, 11689, 10919, 10587, 11177, 11180, 2624, 3507, 10577, 1194, 6162, 6091, 6163, 6193, 6202, 4796, 12307, 4348, 4859, 4895, 12906, 6065, 6160, 6192]`
- threshold review count: **43**
- source bounds: `[7084.0, 150.0, 10919.0, 3583.0]`
- export rect: `(7064,130)-(10939,3603)`

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

