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

## Tests

Unit tests must write under `tempfile` directories, not repository `live/`.
After `python -m unittest discover -s tests`, `git status --short` should stay clean
(aside from intentional local edits).
