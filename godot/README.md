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
# Normal play uses campaign_snapshot.json (or --snapshot=...). Missing snapshot is a visible load error.
Godot.exe --path godot -- --snapshot=res://fixtures/snapshots/em_theatre_profile.json --fixture=res://fixtures/presentation/routes_and_battles.json --debug-map

# CI / tooling (true viewport capture needs a real GL context — not pure dummy headless)
Godot.exe --path godot --audio-driver Dummy -s res://scripts/tools/map_ci_check.gd
Godot.exe --headless --path godot -s res://scripts/tools/map_profiler.gd -- --snapshot=res://fixtures/snapshots/em_theatre_profile.json --out=../docs/godot-presentation/after_profile.json
Godot.exe --path godot --audio-driver Dummy -s res://scripts/tools/map_screenshot.gd -- --snapshot=res://fixtures/snapshots/em_theatre_profile.json --out=../docs/godot-presentation/screenshots/runtime/full_map_1080p.png --width=1920 --height=1080
```

Write-back remains synchronous (`OS.execute`) and can block the UI — see issue #91.
This PR improves map refresh cost; it does not ship final high-res terrain art (#74).

### Presentation fixtures

Godot-local view models under `fixtures/presentation/`. They are **not** production simulation authority. Mock fields use the `presentation_` prefix.

### Architecture notes

- Color-ID hit testing remains nearest-neighbor and authoritative
- Ownership/highlight textures rebuild only on invalidation (cached province pixel runs)
- `scripts/presentation/map_space.gd` centralizes map↔screen transforms
- Marker primitives live in `scripts/presentation/map_markers.gd`

See `docs/godot-presentation/performance-pass.md`.
