# Gates of CodeX Godot frontend

This is the initial Godot 4 map viewer for the versioned Gates of CodeX frontend contract.

## Generate the snapshot

From the repository root:

```powershell
gates-of-codex export-frontend campaign.json --output .\godot\campaign_snapshot.json
```

## Run

Open `godot/project.godot` in Godot 4 and run the project.

The project reads `res://campaign_snapshot.json` by default. A different snapshot can be supplied as the first user command-line argument.

Current controls:

- Hold the left mouse button and drag to pan.
- Use the mouse wheel to zoom.
- Occupied provinces receive a white formation ring.

This checkpoint intentionally uses generated geometry and system fonts. Final map art, hand-corrected positions, interaction panels, and campaign commands are later frontend passes.
