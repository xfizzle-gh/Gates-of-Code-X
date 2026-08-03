# Gates of CodeX

Gates of CodeX is a clean-room strategic campaign application for **Call to Arms: Gates of Hell** with **Code:X**. It recreates the observable interoperability behavior of the supplied Gates of Europa Workshop project without redistributing that project's executable, decompiled implementation, or Unity assets.

The installed Code:X mod is the authoritative source for factions, conquest squads, breeds, vehicles, doctrines, and research. Gates of CodeX scans that data at runtime instead of freezing a private copy into the application.

## Implemented

- Gates of Europa Europe graph with 517 stable provinces and observed reciprocal adjacency
- Deterministic modern control profile spanning NATO, Ukraine, Russia, and provisional PRC territory
- Western and Eastern coalitions with alliance-aware movement, retreat, and supply routes
- National and specialized formation identities beneath each strategic faction
- Provisional Central Asian deployment zone for PRC and a Russia-aligned North Korean contingent
- Coalition supply tracing, isolation, encirclement turns, low-supply movement penalties, and attrition
- Deterministic strategic AI movement, neutral capture, hostile attacks, and battle auto-resolution
- Province graph, battalion movement, capture, combat, retreat, casualties, resources, and turns
- Persistent JSON campaigns with atomic writes and backward-compatible schema loading
- Code:X Steam Workshop and local-mod discovery
- Code:X `.set` and Lua unit-catalog scanning
- Formation-aware starter rosters chosen from the installed Code:X catalog
- GoH `status`, `campaign.scn`, and `campaign.sav` generation
- Post-battle result and survivor import
- Versioned Godot-facing campaign snapshot contract with supply and encirclement state
- Initial Godot 4 map viewer with province control, graph edges, formation markers, pan, and zoom
- Command-line workflow and Tk developer campaign map
- Gates of Hell launcher and Windows installation script
- Linux and Windows automated test workflow

The Europe graph is exact for the observed alpha adjacency contract. Only 63 source provinces exposed human-readable names, and the runtime did not expose complete marker coordinates. The current control profile and development layout are deterministic placeholders intended for iteration, not claims about the original alpha data.

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
```

## Command-line flow

```powershell
# Check paths and scan Code:X
gates-of-codex doctor

# Create a Europe campaign with valid units from the installed Code:X mod
gates-of-codex new --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" --output campaign.json

# Inspect or apply supply for the current map state
gates-of-codex supply-status campaign.json
gates-of-codex supply-status campaign.json --refresh

# Run a deterministic non-player strategic turn
gates-of-codex run-ai-turn campaign.json --faction rusa --seed 7 --advance-turn

# Export the stable frontend snapshot used by Godot
gates-of-codex export-frontend campaign.json --output .\godot\campaign_snapshot.json

# Launch the older Tk developer map
gates-of-codex ui campaign.json
```

Open `godot/project.godot` in Godot 4 after generating `godot/campaign_snapshot.json`. The initial viewer draws all 517 provinces, deduplicated graph edges, faction control, and occupied formation markers.

## Development

```powershell
py -3.11 -m unittest discover -s tests -v
```

## Runtime validation boundary

The save structures and result flow are covered by automated synthetic round-trip tests and are based on the clean-room contract recovered from the supplied project. A live Gates of Hell and Code:X installation is still required to validate exact engine acceptance, default inventories, map identifiers, and any changes introduced by future Code:X or GoH releases.
