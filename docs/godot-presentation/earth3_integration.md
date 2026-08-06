# Earth3 Godot integration

## Play

Default `godot/campaign_snapshot.json` targets `earth3_europe_mediterranean`.

```text
Godot 4.7 → open godot/project.godot → Play (F5)
```

Or:

```powershell
Godot_v4.7-stable_win64.exe --path godot -- --snapshot=res://fixtures/snapshots/earth3_theatre.json --debug-map
```

## Performance (local RTX 4080 SUPER, 1920×1080)

| Metric | Value |
|--------|------:|
| Dataset load + mesh build | ~250–270 ms |
| Mesh chunks | 12 |
| Provinces | 3038 |
| Avg frame (debug overlay on, idle) | ~4–8 ms typical (target ≤16.7 ms @ 60 FPS) |

## Screenshots

- `docs/godot-presentation/screenshots/earth3/full_map_1080p.png`
- `docs/godot-presentation/screenshots/earth3/hover.png`
- `docs/godot-presentation/screenshots/earth3/selected.png`
- `docs/godot-presentation/screenshots/earth3/debug_overlay.png`

## Feature flag

`USE_EARTH3_POLYGON_MAP` in `main_color_id.gd` (default `true`).  
`FALLBACK_GOE_ON_EARTH3_FAIL` keeps GoE Color-ID path available.
