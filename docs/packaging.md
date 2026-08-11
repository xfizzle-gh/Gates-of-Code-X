# Packaging and golden path (P6)

## Player install

```powershell
.\tools\install_gates_of_codex.ps1 -WorkshopTestTarget "<dedicated-workshop-path>"
```

Optional packaged executables:

```powershell
.\tools\install_gates_of_codex.ps1 -BuildExecutable -WorkshopTestTarget "<dedicated-workshop-path>"
```

The installer stamps `SOURCE_COMMIT` with `git rev-parse HEAD` so the application
can display exact provenance without trusting a user-edited field.

## Provenance

Order of authority for the displayed source commit:

1. `GATES_OF_CODEX_SOURCE_COMMIT` (40-char hex)
2. `SOURCE_COMMIT` file at the package root
3. `git rev-parse HEAD` when running from a checkout

Invalid stamps fail closed.

## Managed campaign tree

- Home: `%LOCALAPPDATA%\GatesOfCodeX` (override with `GATES_OF_CODEX_HOME`)
- Campaigns: `<home>/campaigns/<scenario_id>/`
- Backups: `<home>/backups/`

`restore_backup` and `reset_test_campaign` refuse paths outside this tree.

## Frontend ops

- `restore_backup` — `{ "op": "restore_backup", "backup": "<backup-dir>" }`
- `reset_test_campaign` — `{ "op": "reset_test_campaign" }`
