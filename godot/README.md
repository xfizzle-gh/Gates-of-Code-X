# Gates of CodeX Godot frontend

Godot 4 strategic map client for the versioned Gates of CodeX frontend contract.

## Generate the snapshot

From the repository root:

```powershell
gates-of-codex export-frontend campaign.json --output .\godot\campaign_snapshot.json
```

## Run

Open `godot/project.godot` in Godot 4.7 and run the project.

Default snapshot: `res://campaign_snapshot.json`. Optional first non-flag user argument overrides the snapshot path.

### Controls

- Drag with left mouse to pan; wheel to zoom
- Home: full theatre fit
- F: fit operational front
- F3: developer map-debug overlay (off by default)
- G: coalition front debug lines
- C: crossing topology overlay
- Click provinces / counters; panel actions when write-back is enabled

### CLI helpers

```text
Godot.exe --path godot -- --fixture=res://fixtures/presentation/routes_and_battles.json
Godot.exe --path godot -- --debug-map
Godot.exe --headless --path godot -s res://scripts/tools/map_profiler.gd -- --out=../docs/godot-presentation/after_profile.json
```

### Presentation fixtures

Godot-local view models under `fixtures/presentation/`. They are **not** production simulation authority. Mock fields use the `presentation_` prefix.

### Architecture notes

- Color-ID hit testing remains nearest-neighbor and authoritative
- Ownership/highlight textures rebuild only on invalidation (cached province pixel runs)
- `scripts/presentation/map_space.gd` centralizes map↔screen transforms
- Marker primitives live in `scripts/presentation/map_markers.gd`

See `docs/godot-presentation/performance-pass.md`.
