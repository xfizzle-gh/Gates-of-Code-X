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

## 2. Discover maps and profiles

```powershell
.\.venv\Scripts\gates-of-codex-live.exe maps `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --contains dcg_

.\.venv\Scripts\gates-of-codex-live.exe profiles `
  --search-root "$HOME" `
  --max-depth 8 `
  --output ".\live\profiles.json"
```

Only directories containing a literal `map` or `map.mi` file are returned. Support files such as `ammunition.mi`, `battle_zones.mi`, mode scripts, triggers, and weather helpers are not standalone map identifiers. Profile discovery reports profile roots and likely campaign/save directories.

## 3. Run the first engine test

The recommended first test is a fresh, isolated NATO-versus-Russia acceptance campaign. It does not modify an existing Gates of CodeX campaign.

```powershell
.\.venv\Scripts\gates-of-codex-live.exe first-test `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --profile "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles\46383268" `
  --install-directory "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles\46383268\campaign" `
  --map "multi/dcg_[cwa71]_fulda" `
  --work-root ".\live" `
  --backup-root ".\backups" `
  --output ".\live\first-test-latest.json" `
  --launch
```

The command:

- creates a fresh campaign against the full ordered stack
- selects a deterministic NATO-owned province adjacent to Russian territory
- stages the Polish mechanized and Russian motor-rifle formations there
- creates the pending battle through the normal campaign engine
- creates a unique timestamped session directory
- exports the tactical save on Fulda
- backs up any previous acceptance save
- installs `gates_of_codex_acceptance.sav` into the selected profile
- writes separate manifests for the local export and installed save
- optionally launches Gates of Hell
- prints exact verify and import commands

Before loading the save, confirm the GoH mod selection uses the required five-layer order. Gates of Code:X may need to be enabled manually if the game does not automatically list the nonnumeric development folder.

## 4. Play and finish the battle

Verify:

- the installed acceptance save appears and loads
- the selected Fulda map opens
- NATO and Russian units spawn with the expected inventories
- infantry equipment initializes
- vehicle crews initialize
- attacker and defender stages are correct
- the AI Overhaul remains active
- the mission completes and rewrites the installed save

Do not import the battle until verification succeeds.

## 5. Verify and import

The `first-test` output includes exact commands. Their form is:

```powershell
.\.venv\Scripts\gates-of-codex-live.exe verify "<SESSION>\campaign.json" `
  --save "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles\46383268\campaign\gates_of_codex_acceptance.sav" `
  --stack-config ".\config\mod-stack.windows.json" `
  --output "<SESSION>\acceptance-report.json"
```

Verification checks campaign, battle, save, and stack identity; archive readability; the `campaign.scn` object graph; surviving squads; `playedGames` advancement; and win-counter changes.

After verification succeeds:

```powershell
.\.venv\Scripts\gates-of-codex.exe import-battle "<SESSION>\campaign.json" `
  --save "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles\46383268\campaign\gates_of_codex_acceptance.sav"
```

## Manual campaign handoff

For an existing strategic campaign with a pending battle, use `gates-of-codex-live handoff` instead. Supply the exact campaign file, map identifier, profile directory, and installed save path.

## Recovery

Every guarded handoff returns a `backup_directory`. Restore it with:

```powershell
.\.venv\Scripts\gates-of-codex-live.exe restore ".\backups\<BACKUP_DIRECTORY>"
```

The restore operation atomically replaces only files listed in that backup's `backup.json` manifest.

## Acceptance evidence

Retain the validation JSON, profile-discovery JSON, first-test JSON, handoff session JSON, pre-battle backup, updated installed save, manifest, acceptance report, GoH log, active-mod-order screenshot, initial-spawn screenshot, and post-battle result screenshot.
