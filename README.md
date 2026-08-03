# Gates of CodeX

Gates of CodeX is a clean-room strategic campaign application for **Call to Arms: Gates of Hell** with **Code:X**. It recreates the observable interoperability behavior of the supplied Gates of Europa Workshop project without redistributing that project's executable, decompiled implementation, or Unity assets.

The installed Code:X mod is the authoritative source for factions, conquest squads, breeds, vehicles, doctrines, and research. Gates of CodeX scans that data at runtime instead of freezing a private copy into the application.

## Implemented

- NATO, Ukraine, Russia, and PRC strategic factions
- Province graph, battalion movement, capture, combat, retreat, casualties, supply, resources, and turns
- Persistent JSON campaigns with atomic writes
- Code:X Steam Workshop and local-mod discovery
- Code:X `.set` and Lua unit-catalog scanning
- Dynamic starter rosters chosen from the installed Code:X catalog
- GoH `status`, `campaign.scn`, and `campaign.sav` generation
- Post-battle result and survivor import
- Command-line workflow and Tk desktop campaign map
- Gates of Hell launcher and Windows installation script
- Linux and Windows automated test workflow

## Install from source on Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_gates_of_codex.ps1
```

Alternatively:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
gates-of-codex doctor
gates-of-codex ui
```

## Command-line flow

```powershell
# Check paths and scan Code:X
gates-of-codex doctor

# Create a campaign with valid units from the installed Code:X mod
gates-of-codex new --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" --output campaign.json

# Move a battalion. An enemy target creates a pending battle.
gates-of-codex move campaign.json nato-1 rusa_north

# Export the pending battle to a GoH Dynamic Conquest save
gates-of-codex export-battle campaign.json `
  --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" `
  --save "<PROFILE>\campaign\GatesOfCodeX\campaign.sav" `
  --map "multi/4x4/<MAP>"

# Launch Gates of Hell and play the generated Dynamic Conquest battle
gates-of-codex launch --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell"

# After GoH updates campaign.sav, import the survivors and result
gates-of-codex import-battle campaign.json --save "<PROFILE>\campaign\GatesOfCodeX\campaign.sav"
```

The export creates a matching `.goc.json` manifest beside `campaign.sav`. That manifest prevents a stale or unrelated GoH battle from being applied to the campaign.

## Desktop map

```powershell
gates-of-codex ui campaign.json
```

The desktop map supports campaign opening and saving, battalion selection, movement and attack creation, auto-resolve, GoH export and import, and turn advancement.

## Development

```powershell
py -3.11 -m unittest discover -s tests -v
```

## Runtime validation boundary

The save structures and result flow are covered by automated synthetic round-trip tests and are based on the clean-room contract recovered from the supplied project. A live Gates of Hell and Code:X installation is still required to validate exact engine acceptance, default inventories, map identifiers, and any changes introduced by future Code:X or GoH releases.
