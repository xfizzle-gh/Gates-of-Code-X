# Live Gates of Hell and Code:X acceptance

The automated test suite validates the strategic campaign, Code:X catalog parsing, generated `status` and `campaign.scn` structures, archive round trips, stale-result protection, and post-battle import logic. The final compatibility boundary is the actual Gates of Hell engine.

## 1. Validate the installation

```powershell
gates-of-codex-live validate `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" `
  --profile "$HOME\Documents\My Games\gates of hell\profiles"
```

The command verifies the game executable, Code:X `mod.info`, all four unit catalogs, map discovery, profile existence, and write access.

## 2. Find a valid tactical map identifier

```powershell
gates-of-codex-live maps `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" `
  --contains 2x2
```

Use one returned `identifier` exactly as the handoff map.

## 3. Create a guarded tactical handoff

First create a pending strategic battle. Then run:

```powershell
gates-of-codex-live handoff campaign.json `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" `
  --profile "$HOME\Documents\My Games\gates of hell\profiles" `
  --save ".\live\campaign.sav" `
  --map "multi/2x2/<MAP_IDENTIFIER>" `
  --backup-root ".\backups" `
  --launch
```

The handoff command:

1. validates the installation and map identifier
2. backs up the strategic campaign, prior tactical save, and prior manifests
3. rejects a Code:X catalog mismatch
4. generates the tactical save and bound manifest
5. optionally copies the save to an explicit installation path
6. optionally launches Gates of Hell
7. records a machine-readable `.session.json`

Use `--install-save <path>` only after identifying the exact profile save path used by the installed game.

## 4. Play and finish the battle

Verify in Gates of Hell:

- the save loads with Code:X enabled
- the selected map opens
- NATO, Ukraine, Russia, or PRC units spawn as expected
- infantry equipment and inventories initialize
- vehicle crews initialize
- attacker and defender stages are correct
- Code:X tactical AI remains active
- the mission completes and writes the updated save

Do not import the battle until the verification command reports success.

## 5. Verify the updated tactical save

```powershell
gates-of-codex-live verify campaign.json `
  --save ".\live\campaign.sav" `
  --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" `
  --output ".\live\acceptance-report.json"
```

The verification checks:

- campaign, battle, and save manifest identity
- Code:X catalog signature
- archive readability
- `campaign.scn` object graph
- surviving campaign squads
- `playedGames` advancement
- win-counter changes

After verification succeeds, import the battle:

```powershell
gates-of-codex import-battle campaign.json --save ".\live\campaign.sav"
```

## Recovery

Every guarded handoff returns a `backup_directory`. Restore it with:

```powershell
gates-of-codex-live restore ".\backups\<BACKUP_DIRECTORY>"
```

The restore operation atomically replaces only the files listed in that backup's `backup.json` manifest.

## Acceptance report to retain

For the first successful engine test, retain:

- validation JSON
- handoff session JSON
- pre-battle backup directory
- updated `campaign.sav`
- `campaign.sav.goc.json`
- acceptance report JSON
- Gates of Hell log
- screenshots of initial spawns and post-battle result

These files establish the first verified engine contract and provide fixtures for compatibility regression work.
