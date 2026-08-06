# Screenshot evidence

## `runtime/` (Godot runtime — acceptance)

Produced by `godot/scripts/tools/map_screenshot.gd` against the real `main.tscn` client:

1. Instantiates the live Godot scene
2. Loads committed `fixtures/snapshots/em_theatre_profile.json`
3. Opens the color-ID map and presentation layers
4. Asserts **LINEAR** background + **NEAREST** identity CanvasItem filters
5. Captures the live `ImageTexture` layers created by `ColorIdMap`

These are the authoritative visual evidence for PR #90.

## `mock_evidence_offline_composites/` (not acceptance)

Offline Python PIL composites from map assets only. **Mock evidence — not Godot runtime acceptance proof.**
