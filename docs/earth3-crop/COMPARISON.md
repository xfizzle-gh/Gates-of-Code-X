# Earth3 crop candidate comparison

**Status:** awaiting owner approval on #92. **No production recommendation.**

| ID | Mode | Provinces | Land | Water | Vertices | Edges | Components | Threshold review |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `em_ref_tight` | rect_centroid | 4371 | 4087 | 284 | 443943 | 12779 | 29 | 0 |
| `em_north_east_expand` | rect_centroid | 4492 | 4201 | 291 | 462234 | 13128 | 29 | 0 |
| `em_south_west_expand` | rect_centroid | 4497 | 4201 | 296 | 462223 | 13142 | 30 | 0 |
| `em_reference_masked` | mask_overlap | 3648 | 3431 | 217 | 333352 | 10642 | 25 | 55 |

## em_reference_masked vs em_ref_tight

- added vs tight: **0**
- removed vs tight: **723**
- required includes: `[950, 951, 952, 953, 954, 955, 958, 959, 960, 961, 962, 963, 964, 6847, 6848, 6849, 1268, 1271, 3782, 6627, 10868, 10869, 12175]`
- explicit excludes: `[11370, 11764]`
- threshold review count: **55**
- source bounds: `[7109.0, 714.0, 11409.0, 3822.0]`
- export rect: `(7089,694)-(11429,3842)`

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

