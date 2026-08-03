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
- Catalog-derived Code:X research progression with prerequisites and resource costs
- Formation-specific recruitment pools, persistent reinforcement reserves, casualty replacement, and force expansion
- Formation condition, supplied repairs, recurring maintenance, and end-of-round income accounting
- Province construction for fortifications, supply hubs, recruitment centers, and command posts
- Infrastructure effects on defense, supply, recruitment prices, and province income
- Operational objectives with persistent progress and coalition rewards
- Coalition victory and defeat through elimination or sustained strategic-capital control
- Deterministic AI research, recruitment, reinforcement, repair, and construction priorities
- Province graph, battalion movement, capture, combat, retreat, casualties, resources, and turns
- Persistent JSON campaigns with atomic writes and backward-compatible schema loading
- Code:X Steam Workshop and local-mod discovery
- Code:X `.set` and Lua unit-catalog scanning
- Formation-aware starter rosters chosen from the installed Code:X catalog
- GoH `status`, `campaign.scn`, and `campaign.sav` generation
- Guarded tactical handoff with installation validation, map discovery, backups, manifest binding, and optional launch
- Post-battle engine acceptance verification and survivor import
- Versioned Godot-facing campaign snapshot contract with supply, economy, infrastructure, objectives, and victory state
- Godot 4 strategic map with province selection and campaign, formation, construction, economy, and objective panels
- Reproducible Windows executable and source release packaging with SHA-256 checksums
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
gates-of-codex-live --help
```

## Strategic campaign flow

```powershell
# Create a Europe campaign from the installed Code:X catalog
gates-of-codex new --codex "E:\Steam\steamapps\workshop\content\400750\<CODEX_ID>" --output campaign.json

# Research, recruit, reinforce, repair, and construct
gates-of-codex research-status campaign.json --faction nato
gates-of-codex list-recruits campaign.json --formation nato-us-armored
gates-of-codex recruit campaign.json --formation nato-us-armored --unit "tank(nato)"
gates-of-codex assign-reinforcements campaign.json --formation nato-us-armored --unit "tank(nato)"
gates-of-codex repair campaign.json --formation nato-us-armored --points 10
gates-of-codex construct campaign.json Warszawa supply_hub --faction nato

# Inspect objectives and campaign outcome
gates-of-codex objectives campaign.json
gates-of-codex campaign-status campaign.json

# Run a non-player strategic, economy, and construction turn
gates-of-codex run-ai-turn campaign.json --faction rusa --seed 7 --advance-turn

# Export data for the Godot frontend
gates-of-codex export-frontend campaign.json --output .\godot\campaign_snapshot.json
```

Open `godot/project.godot` after generating `godot/campaign_snapshot.json`. Click provinces to inspect ownership, infrastructure, available construction, occupying formations, objectives, resources, and campaign status.

## Guarded live battle flow

```powershell
# Validate the game, Code:X, all four factions, maps, profile, and write access
gates-of-codex-live validate --game "<GOH_DIRECTORY>" --codex "<CODEX_DIRECTORY>" --profile "<PROFILE_DIRECTORY>"

# Discover a valid map identifier
gates-of-codex-live maps --game "<GOH_DIRECTORY>" --codex "<CODEX_DIRECTORY>" --contains 2x2

# Back up, export, optionally install, and launch
gates-of-codex-live handoff campaign.json --game "<GOH_DIRECTORY>" --codex "<CODEX_DIRECTORY>" --profile "<PROFILE_DIRECTORY>" --save ".\live\campaign.sav" --map "multi/2x2/<MAP>" --backup-root ".\backups" --launch

# After completing the battle, verify the engine-updated save
gates-of-codex-live verify campaign.json --save ".\live\campaign.sav" --codex "<CODEX_DIRECTORY>" --output ".\live\acceptance-report.json"

# Import only after verification succeeds
gates-of-codex import-battle campaign.json --save ".\live\campaign.sav"
```

See `docs/live-acceptance.md` for the complete first-engine-test and recovery procedure.

## Development

```powershell
py -3.11 -m unittest discover -s tests -v
```

## Runtime validation boundary

The application now provides the tooling needed to perform and document the live engine acceptance test. The repository cannot itself prove Gates of Hell engine acceptance without running one generated battle on a Windows installation with the current Code:X version. Final map artwork, unresolved source province names, and balance remain content and tuning work after that compatibility test.
