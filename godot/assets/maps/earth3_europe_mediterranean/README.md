# earth3_europe_mediterranean

Approved Earth3 Europe–Mediterranean launch theatre (crop `em_reference_masked`).

| Field | Value |
|------|------:|
| Provinces | 3038 |
| Land | 2843 |
| Water | 195 |
| Renderer | `polygon_mesh` |
| Approved source-ID hash | `7effdffbccbcce33ecba364dc8d161ded5053266db2df0deee605a98c36620dc` |

## Files

- `map_manifest.json` — strategic-map contract (`renderer: polygon_mesh`)
- `polygon_dataset.json` — Gates IDs, source provenance, rings, triangulation, adjacency, border segments
- `dataset_meta.json` — compact counts/hashes for tests without loading full geometry
- `triangulation_audit.json` — zero-failure Shapely clipped-Delaunay audit (no fan fallback)

## Runtime contract

- Geometry is immutable after load (chunked `ArrayMesh` + province-index UVs).
- Ownership recolor updates a 1×N lookup `ImageTexture` sampled by `shaders/province_ownership.gdshader`.
- Borders are a separate line mesh from shared-edge segments.
- Hit-test uses ring point-in-polygon + spatial grid.
- GoE Color-ID theatre remains explicit fallback only.

## Regenerate (local archive required)

```powershell
python tools/earth3/export_godot_dataset.py --archive "C:\path\to\AOH3_Earth3_map_provinces.zip"
python tools/earth3/build_earth3_snapshot.py
```

## Fallback

`fallback_map_id`: `europe_mediterranean_from_goe` (Color-ID theatre).
