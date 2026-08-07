# Earth3 Godot integration

## Play

Default `godot/campaign_snapshot.json` targets `earth3_europe_mediterranean`
(regenerate with `python tools/earth3/build_earth3_snapshot.py`).

```text
Godot 4.7 → open godot/project.godot → Play (F5)
```

Or:

```powershell
Godot_v4.7-stable_win64.exe --path godot -- --snapshot=res://fixtures/snapshots/earth3_theatre.json --debug-map
```

## Production dataset

| Field | Value |
|--------|------:|
| Crop | `em_reference_masked` |
| Provinces | 3038 (2843 land / 195 water) |
| Triangles | 250035 |
| Border segments | 137559 |
| Triangulator | Shapely Delaunay ∩ polygon (no fan fallback) |
| Max area error | ~1e-15 |

## Runtime contract

- Geometry immutable after load (chunked meshes + province-index UVs).
- Ownership recolor: 1×N `ImageTexture` + `shaders/province_ownership.gdshader`.
- Borders: separate line mesh from shared edges.
- GoE Color-ID is explicit fallback only (`FALLBACK_GOE_ON_EARTH3_FAIL`).

## Performance (local RTX 4080 SUPER, Godot 4.7)

| Metric | Value |
|--------|------:|
| Dataset load + mesh build | ~370–480 ms |
| Ownership refresh (partial) | ~4 ms |
| Province pick | ~0.04 ms |
| Mesh chunks | 12 |
| Target | ≤16.7 ms/frame @ 60 FPS idle |

See `ci_profile_earth3.json` and `earth3_perf.json`.

## Screenshots

- `docs/godot-presentation/screenshots/earth3/full_map_1080p.png`
- `docs/godot-presentation/screenshots/earth3/full_map_1440p.png`
- `docs/godot-presentation/screenshots/earth3/selected_hovered_1080p.png`
- `docs/godot-presentation/screenshots/earth3/debug_overlay_1080p.png`

## Feature flag

`USE_EARTH3_POLYGON_MAP` in `main_color_id.gd` (default `true`).  
`FALLBACK_GOE_ON_EARTH3_FAIL` keeps GoE Color-ID path available.
