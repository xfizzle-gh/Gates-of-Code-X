# Interim GoE-derived strategic map

This directory is the default Godot runtime location for the owner-authorized interim Gates of Europa-derived color-ID map.

The source asset is not fabricated or reconstructed by the repository. Use the available extracted `province_idnew_map` texture as a PNG and import it through the generic validator. The importer discovers dimensions and RGB assignments from the supplied files. Gameplay code does not assume 1314×1513, any specific RGB value, or Unity formatting.

From the repository root on the owner machine:

```powershell
.\.venv\Scripts\gates-of-codex.exe import-strategic-map `
  --goe-interim `
  --id-map "E:\path\to\extracted\province_idnew_map.png" `
  --texture-output ".\godot\assets\maps\europe\interim_goe\province_id_map.png" `
  --output ".\godot\assets\maps\europe\interim_goe\map_manifest.json"
```

The command refuses the import when:

- a province RGB is missing from the texture
- the texture contains an unrecognized non-background RGB
- two campaign provinces share one RGB
- pixel-derived adjacency differs from the 517-node campaign graph
- the PNG encoding is unsupported

Generated runtime files:

- `map_manifest.json`
- `province_id_map.png`

The Godot client loads `map_manifest.json` by default. A different manifest can be supplied as the second user argument after the campaign snapshot path.

## Replacement path

To replace this interim map with project-owned art:

1. Create a new unique-color ID texture.
2. Create a province table mapping each stable campaign `province_id` to its new RGB.
3. Run `import-strategic-map` without `--goe-interim`, using `--province-table`, a new `--map-id`, and project-owned provenance.
4. Correct every missing/orphan color or adjacency error reported by the importer.
5. Point Godot at the new manifest.
6. Re-run pixel-selection, ownership recolor, border, highlight, and label acceptance checks.

No campaign rule, tactical side, save import, or strategic actor record should change during the swap.
