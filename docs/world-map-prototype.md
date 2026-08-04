# World strategic map prototype

## Status

First playable **world projection** prototype for Gates of CodeX.

- Europe interim GoE map remains available as fallback (`interim_goe_europe`)
- World prototype is the new strategic target (`world_prototype`)

## Pre-implementation findings

| Question | Answer |
|---|---|
| Extracted source files | 72 files from `world_test_9.pack` (local temp only) |
| `regions.esf` geometry | Not decoded reliably in this slice (ESF `caab` layout; no quick polygon extract) |
| First theatre approach | Settlement-seeded Voronoi on full equirectangular world |
| Province count | ~110 seeds (pack `bos_*` settlements with public geo + theatre extensions) |
| Output format | Existing `gates-of-codex.strategic-map` manifest + RGB8 color-ID PNG |
| Clean-room boundary | No `.pack`/ESF/heightmap/original TGA committed; generated ID map + manifest only |

## Outputs

```text
godot/assets/maps/world/prototype/world_id_map.png
godot/assets/maps/world/prototype/world_land_silhouette.png
godot/assets/maps/world/prototype/map_manifest.json
```

## Generate

```powershell
python -m gates_of_codex generate-world-prototype --output-dir godot/assets/maps/world/prototype
```

Requires local research extract (default):
`C:\Users\paulf\AppData\Local\Temp\opencode\world_test_9_extract\files`

## Map selection

Campaign / snapshot:

```json
"map_metadata": { "strategic_map_id": "world_prototype" }
```

or

```json
"map_metadata": { "strategic_map_id": "interim_goe_europe" }
```

Godot prefers snapshot `strategic_map.manifest_path`, then `strategic_map_id`, then world prototype if present, else Europe fallback.

## Provenance

- Settlement **names** from research loc tables
- Settlement **coordinates** from public geographic lat/lon
- Land/sea silhouette temporarily sampled from research world TGA (not shipped)
- Province polygons are **generated** Voronoi cells (not recovered TW region meshes)
