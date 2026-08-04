# Europe–Mediterranean prototype map assets

## Layers

| File | Role |
|---|---|
| `background_placeholder.png` | **Project-owned** neutral silhouette fixture (repo-safe) |
| `background_config.example.json` | Example local external background config |
| `background_config.json` | **Local only** (gitignored) path to pack-derived artwork |
| `id_map.png` | Project **color-ID** selection/ownership texture |
| `land_mask.png` / `land_silhouette.png` | Gameplay land/water helpers |
| `map_manifest.json` | Province table, adjacency, anchors, provenance |

## Pack background (local only)

Pack campaign artwork is **not stored or distributed by this repository**.

```powershell
python -c "from gates_of_codex.map_background import export_local_pack_background; export_local_pack_background(source_tga=r'path\to\boshin_map_world.tga', output_png=r'C:\Users\...\em_local\europe_mediterranean_background.png', config_json=r'godot\assets\maps\europe_mediterranean\prototype\background_config.json')"
```

Godot loads, in order:

1. `background_config.json` → external `background_texture` path  
2. else `background_placeholder.png`  
3. else land silhouette fallback  

Selection/campaign still work with no local pack image.

## Debug

- `I` — raw color-ID  
- `C` — calibration overlay (background + NE silhouette + control points)

Province geometry remains provisional.
