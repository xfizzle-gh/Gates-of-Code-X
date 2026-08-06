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
- `polygon_dataset.json` — Gates IDs, source provenance, rings, triangulation, adjacency
- `dataset_meta.json` — compact counts/hashes for tests without loading full geometry

## Regenerate (local archive required)

```powershell
python tools/earth3/export_godot_dataset.py --archive "C:\path\to\AOH3_Earth3_map_provinces.zip"
python tools/earth3/build_earth3_snapshot.py
```

## Fallback

`fallback_map_id`: `europe_mediterranean_from_goe` (Color-ID theatre).
