# earth3_europe_mediterranean

Earth3 Europe–Mediterranean production theatre (crop em_reference_masked **mask v7 Urals**).

Owner-approved Candidate B on issue #109 (PR production follow-up).

| Field | Value |
|------|------:|
| Provinces | 3523 |
| Land | 3307 |
| Water | 216 |
| Renderer | polygon_mesh |
| Source-ID hash | e8dd0dd16ac06d035398e079f0736a97c2fe39bbb4434cc6c6c119067b490dda |

## Files

- map_manifest.json — strategic-map contract (
enderer: polygon_mesh)
- polygon_dataset.json — Gates IDs, rings, triangulation, adjacency, gap fills
- dataset_meta.json — compact counts/hashes
- 	riangulation_audit.json / lack_hole_audit.json

## Runtime contract

- Geometry immutable after load
- Continuous ocean underlay + water fills + gap fills
- Ownership recolor via lookup texture
- GoE Color-ID is explicit fallback only
