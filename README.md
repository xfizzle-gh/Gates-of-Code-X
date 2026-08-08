# Gates of CodeX

Gates of CodeX is a clean-room strategic campaign application for **Call to Arms: Gates of Hell** with **Code:X**. It recreates the observable interoperability behavior of the supplied Gates of Europa Workshop project without redistributing that project's executable, decompiled implementation, or Unity assets.

The active GoH mod stack is the authoritative source for factions, conquest squads, breeds, vehicles, doctrines, research, and tactical behavior. Gates of CodeX scans the ordered stack at runtime instead of freezing a private copy into the application.

## Canonical mod stack

Load these layers from lowest to highest priority:

1. Vanilla Gates of Hell
2. West81, Workshop `2897299509`
3. Code:X, Workshop `3261086933`
4. Code:X AI Overhaul, Workshop `3636883799`
5. Gates of Code:X, using the active repository, worktree, or verified published package

`config/mod-stack.windows.json` is a portable, fail-closed template. It contains no local absolute paths. Set the five required environment variables before running any stack-aware command:

```powershell
$env:GOH_VANILLA_ROOT = "D:\SteamLibrary\steamapps\common\Call to Arms - Gates of Hell"
$env:WEST81_ROOT = "D:\SteamLibrary\steamapps\workshop\content\400750\2897299509"
$env:CODEX_ROOT = "D:\SteamLibrary\steamapps\workshop\content\400750\3261086933"
$env:CODEX_AI_OVERHAUL_ROOT = "D:\SteamLibrary\steamapps\workshop\content\400750\3636883799"
$env:GATES_CODEX_ROOT = "D:\Projects\Gates-of-Code-X"
```

`GATES_CODEX_ROOT` should point to the exact repository or worktree being tested. The loader validates the fixed layer order, required Vanilla sentinels, exact `mod.info` product identities, duplicate roots, and path existence. It never guesses a Workshop directory or falls back to another package.

Workshop item `3700832981` is **not** Gates of Code:X. Its installed identity is `Imperium vs Xenos Conquest`, so the validated stack rejects it as the final layer. Do not deploy Gates files into that directory.

For a separate disposable deployment, provide an explicit target rather than relying on a remembered Workshop ID:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\deploy_workshop_test.ps1 `
  -TargetRoot "D:\SteamLibrary\steamapps\workshop\content\400750\<dedicated-gates-test-folder>"
```

The deployment manifest in that explicit target records the source commit and deployed files. Later syncs remove only stale files previously written by the deployment script; unrelated files remain untouched.

## Implemented

- Gates of Europa Europe graph with 517 stable provinces and observed reciprocal adjacency
- Deterministic modern control profile spanning NATO, Ukraine, Russia, and provisional PRC territory
- Western and Eastern coalitions with alliance-aware movement, retreat, and supply routes
- National and specialized formation identities beneath each strategic faction
- Provisional Central Asian deployment zone for PRC and a Russia-aligned North Korean contingent
- Deterministic operational-graph supply tracing with persisted grace, plus legacy province supply compatibility, isolation, and attrition
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
- Ordered mod-stack validation and compatibility signatures
- Code:X `.set` and Lua unit-catalog scanning with later-layer overrides
- Formation-aware starter rosters chosen from the active stack
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
powershell -ExecutionPolicy Bypass -File .\tools\install_gates_of_codex.ps1 -NoWorkshopDeploy
```

The installer updates the Python environment. Use `-NoWorkshopDeploy` for normal repository/worktree development. A separate deployment is permitted only with an explicit, dedicated `-WorkshopTestTarget`; never use `3700832981`.

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
# Validate the complete ordered stack
gates-of-codex doctor `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json"

# Create a Europe campaign and persist play context for later handoffs
gates-of-codex new `
  --codex "E:\Steam\steamapps\workshop\content\400750\3261086933" `
  --stack-config ".\config\mod-stack.windows.json" `
  --game "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  --profile "C:\Users\paulf\AppData\Local\digitalmindsoft\gates of hell\profiles\46383268" `
  --map "multi/dcg_[cwa71]_fulda" `
  --output campaign.json

# Strategic actions
gates-of-codex campaign-status campaign.json
gates-of-codex move campaign.json <battalion-id> <province-id>
# Hostile move creates pending_battle

# Hand off the pending battle to GoH (auto install path + printed verify/import)
gates-of-codex-live handoff campaign.json `
  --stack-config ".\config\mod-stack.windows.json" `
  --launch

# Play the printed Conquest entry in GoH, then:
#   verify command printed by handoff
#   import-battle command printed by handoff (only if verify is green)

gates-of-codex end-turn campaign.json
gates-of-codex run-ai-turn campaign.json --faction rusa --advance-turn

# Economy / construction when needed
gates-of-codex research-status campaign.json --faction nato
gates-of-codex list-recruits campaign.json --formation nato-us-armored
gates-of-codex construct campaign.json Warszawa supply_hub --faction nato

# Godot snapshot (read-only viewer)
gates-of-codex export-frontend campaign.json --output .\godot\campaign_snapshot.json
```

`handoff` remembers game/profile/map/install paths on the campaign after the first run, auto-picks a unique GoH save filename from the visible Conquest name, and prints the exact load / verify / import steps. `first-test` remains acceptance-only.

Open `godot/project.godot` after generating `godot/campaign_snapshot.json`. Click provinces to inspect ownership, infrastructure, formations, objectives, and resources. Godot is still a viewer (no write-back yet).

## Guarded live battle notes

- Prefer `handoff` on an existing campaign with a pending battle.
- Use `first-test` only for disposable engine acceptance.
- Always verify before import.
- See `docs/live-acceptance.md` for recovery and first-engine-test details.

## Development

```powershell
py -3.11 -m unittest discover -s tests -v
```

## Runtime validation boundary

The application provides the tooling needed to perform and document the live engine acceptance test. The repository cannot itself prove Gates of Hell engine acceptance without running one generated battle on Windows with the full current stack. Final map artwork, unresolved source province names, and balance remain content and tuning work after that compatibility test.
