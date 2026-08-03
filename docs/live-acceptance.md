# Live Gates of Hell and Code:X acceptance

The automated suite validates the strategic campaign, ordered resource-stack parsing, Code:X catalog overlays, generated `status` and `campaign.scn` structures, archive round trips, stale-result protection, and post-battle import logic. The final compatibility boundary is the actual Gates of Hell engine.

## Required load order

Enable these GoH layers from lowest to highest priority:

1. Vanilla Gates of Hell
2. West81, Workshop `2897299509`
3. Code:X, Workshop `3261086933`
4. Code:X AI Overhaul, Workshop `3636883799`
5. Gates of Code:X

The checked-in `config/mod-stack.windows.json` represents this order for the current `E:\Steam` installation. The primary `--codex` argument must point to `3261086933`, not the AI Overhaul.

## 1. Validate the installation and stack

```powershell
.\.venv\Scripts\gates-of-codex-live.exe validate `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --output ".\live\validation.json"
```

The command verifies the game executable, primary Code:X metadata, every required stack path, West81 to Code:X to AI Overhaul ordering, all four unit catalogs, a signature covering runtime scripts and sets from every mod layer, playable map roots, and optional profile write access.

## 2. Find a valid tactical map identifier

```powershell
.\.venv\Scripts\gates-of-codex-live.exe maps `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --contains dcg_
```

Only directories containing a literal `map` or `map.mi` file are returned. Support files such as `ammunition.mi`, `battle_zones.mi`, mode scripts, triggers, and weather helpers are not standalone map identifiers. When multiple layers provide the same map, the highest-priority layer wins. Use one returned `identifier` exactly as the handoff map.

## 3. Discover the GoH profile and save location

```powershell
.\.venv\Scripts\gates-of-codex-live.exe profiles `
  --search-root "$HOME" `
  --max-depth 8 `
  --output ".\live\profiles.json"
```

The command checks standard Documents and OneDrive locations, then performs a bounded search under any supplied roots. It reports profile roots and likely `save`, `saves`, `campaign`, `campaigns`, or `dynamic_conquest` directories. Do not use `--install-save` until the actual save location is identified.

## 4. Create the campaign against the same stack

```powershell
.\.venv\Scripts\gates-of-codex.exe new `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --output ".\live\campaign.json" `
  --faction nato
```

The campaign stores the ordered resource stack and the full stack signature. A later export is rejected if Code:X or the AI Overhaul changed.

## 5. Create a guarded tactical handoff

First create a pending strategic battle. Then run:

```powershell
.\.venv\Scripts\gates-of-codex-live.exe handoff ".\live\campaign.json" `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --save ".\live\campaign.sav" `
  --map "multi/dcg_[cwa71]_fulda" `
  --profile "<PROFILE_ROOT>" `
  --install-save "<EXACT_GAME_SAVE_PATH>" `
  --backup-root ".\backups" `
  --launch
```

The handoff command validates the stack, backs up strategic and tactical files, rejects stack-signature mismatches, resolves breeds from highest to lowest layer, generates the tactical save and manifest, optionally installs the save, optionally launches GoH, and records a machine-readable session file.

## 6. Play and finish the battle

Before loading the save, confirm the GoH mod selection uses the required order. Verify:

- the save loads with West81, Code:X, the AI Overhaul, and Gates of Code:X enabled
- the selected map opens
- NATO, Ukraine, Russia, or PRC units spawn as expected
- infantry equipment and inventories initialize
- vehicle crews initialize
- attacker and defender stages are correct
- the AI Overhaul remains active
- the mission completes and writes the updated save

Do not import the battle until verification succeeds.

## 7. Verify the updated tactical save

```powershell
.\.venv\Scripts\gates-of-codex-live.exe verify ".\live\campaign.json" `
  --save ".\live\campaign.sav" `
  --stack-config ".\config\mod-stack.windows.json" `
  --output ".\live\acceptance-report.json"
```

Verification checks campaign, battle, save, and stack identity; archive readability; the `campaign.scn` object graph; surviving squads; `playedGames` advancement; and win-counter changes.

After verification succeeds:

```powershell
.\.venv\Scripts\gates-of-codex.exe import-battle ".\live\campaign.json" --save ".\live\campaign.sav"
```

## Recovery

Every guarded handoff returns a `backup_directory`. Restore it with:

```powershell
.\.venv\Scripts\gates-of-codex-live.exe restore ".\backups\<BACKUP_DIRECTORY>"
```

The restore operation atomically replaces only files listed in that backup's `backup.json` manifest.

## Acceptance evidence

Retain the validation JSON, profile-discovery JSON, handoff session JSON, pre-battle backup, updated `campaign.sav`, manifest, acceptance report, GoH log, active-mod-order screenshot, initial-spawn screenshot, and post-battle result screenshot.
