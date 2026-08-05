# Repository hygiene

## Tracked vs generated

| Path | Status |
|---|---|
| `tests/fixtures/` | **Authored** fixtures for unit tests |
| `examples/` | **Authored** sample campaigns (if present) |
| `godot/assets/maps/**` | **Authored / generated map assets** committed deliberately |
| `live/` | **Generated runtime** — ignored |
| `live/backups/`, `live/live/` | **Local backups / acceptance sessions** — ignored |
| `godot/campaign_snapshot.json` | **Generated frontend bridge** — ignored |
| `godot/frontend_commands.json` | **Generated write-back queue** — ignored |
| `godot/.godot/` | **Godot editor cache** — ignored |

## Local regenerate

```powershell
python -m gates_of_codex new --strategic-map europe_mediterranean_from_goe --faction nato --output live/em_goe_campaign.json
python -m gates_of_codex export-frontend live/em_goe_campaign.json --output godot/campaign_snapshot.json
```

Open `godot/project.godot` and press F5.

### Stale snapshot warning

`godot/campaign_snapshot.json` is **generated and gitignored**. After pulling UI/presentation
changes (especially stack hierarchy / `strategic_formation_presentations`), you **must**
re-export before F5. A stale snapshot can show contradictions such as:

```text
0 formations | 2 battalions
```

while still drawing tabs, or empty formation membership with leftover Placeholder cards.

A clean export for a two-force stack must look like:

```text
2 formations | 2 battalions | 2 tactical units
```

with each `strategic_formation_presentations` entry listing its `battalion_ids`.

## Tests

Unit tests must write under `tempfile` directories, not repository `live/`.
After `python -m unittest discover -s tests`, `git status --short` should stay clean
(aside from intentional local edits).
