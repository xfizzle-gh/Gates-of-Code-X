# Milestone log

## 2026-10-04 — repository reset

- Previous project (Gates of CodeX, Godot/Python) removed from the working tree. Its history remains in
  this repository's other branches; local-only work was committed to `archive/pre-warfighter-local-wip`
  (not pushed). Stale worktree records pruned; none of the worktree folders existed on disk.
- New history starts on orphan branch `warfighter-campaign`.
- Deviation from plan: the workspace is this folder (inside the Steam workshop directory) at the owner's
  request, not `Documents\Codex\WarfighterCampaign`. Steam does not manage this ID's content today, but
  nothing here should be assumed safe from a Workshop re-download.

## M0 — frozen baseline and extraction: DONE

| Check | Result |
| --- | --- |
| GOE file count / bytes | 10 / 135,224,771 — matches plan |
| GOE ZIP SHA256 | `926BEA2E…7316B` — matches plan |
| GOE `Assembly-CSharp.dll` SHA256 after extraction | `B5A9AF86…109F1` — matches plan |
| WF file count / bytes | 18,224 / 50,195,940,296 — matches plan |
| Steam build id | 25492057 — matches plan |
| Game executable version | 1.0.6.7 (`1.0.6.7-aaa36ed4d`) |
| ZIP extraction | 201 entries, every path validated inside `upstream/goe-portable` |
| Archive indexes | GOE zip, 5 WF paks (entity 138,490 entries; texture 22,021; sound 21,534; map 1,302; default 101), 11 base-game paks (gamelogic 8,969) |

Files: `tools/baseline.py`, `tools/paths.json`, `evidence/baseline.json`, `evidence/source-manifest.json`,
`evidence/archive-index-summary.json`, `evidence/provenance.json`.

Not done in M0: enabled-mods/profile capture (needs the owner to pick the profile), copies of effective
base conquest modules (planning workspace already holds them under `pl\work\goe-inspection`).

## M1 — recovered build: IN PROGRESS, gate NOT met

Done:
- Managed code decompiled with ilspycmd 9.1.0.7988: 211 files, ~33k lines, in `recovered/csharp`.
- Battle export → result → survivor import traced: `docs/battle-round-trip.md`.
- Feature-parity matrix from source: `docs/feature-parity.md`.

Asset recovery (2026-10-04, AssetRipper 2.0.0 headless, official GitHub release, zip SHA256 `9A7EF0E7…1BAF7`):
- Export to `recovered/unity/ExportedProject` succeeded (170 MB). Import log: one read-size error on
  `globalgamemanagers` asset type 129 (PlayerSettings) and six TMP SDF font atlases not converted to bitmap.
- Recovered: both scenes (`StartMenu`, `SampleScene`), 210 scripts, `Status_Template.txt`,
  province database JSON (517 provinces, 506 with neighbours, 515 with marker positions, 3 map regions),
  `GohFullUnitTemplateCache` (4.8 MB), unit catalogs and research trees for ger/rus/fin/eng,
  `GohConquestMapCatalog`, `CampaignWorldRules`, supply/building/battalion rules, scripted events,
  status and save export settings.
- Notable values: status template is save `version 9` with two fixed map points `hq_a`/`hq_b`;
  `GameVersion` 1.063.0, `Region` ostfront, MP/SP/AP/RP all 0; `GohSaveExportSettings.TargetProfileDirectory`
  is the original author's own profile path; `CampaignSetup.StartingBattalions` is empty.
- AssetRipper emits package code as DLLs under `Assets/Plugins` and a `Packages/manifest.json` with only
  built-in modules. URP, Netcode, Transport, TMP and Input System therefore are not real packages yet.
- Working copy for editing: `campaign/` (copied from the export).
- Editor available: 6000.6.4f1 (licensed), not the build's 6000.4.0f1 (revision `8cf496087c8f`).
  First open is being attempted with 6000.6.4f1; log in `build/unity-open.log`.

Rebuild attempts (2026-10-04):
- 6000.6.4f1: scripts compile after two source repairs, but the player build fails. The package DLLs
  AssetRipper placed in `Assets/Plugins` were compiled for 6000.4 engine internals (URP GPU-driven
  rendering, TextCore, UIElements) and ILLink cannot resolve them. Not usable until the DLLs are replaced
  by real packages.
- 6000.4.0f1 (revision `8cf496087c8f`, exact match): **player build succeeds**, 0 errors,
  output `build/campaign-win64/WarfighterCampaign.exe`.
- Source repairs, both in decompiled Netcode ILPP output in `CampaignNetworkSessionManager.cs` and
  recorded in `tools/recover_campaign.ps1`: `__getTypeName` override modifier (CS0507) and a derived-type
  qualifier on 38 `__rpc_exec_stage` accesses (CS1540).
- Smoke run (25 s, windowed): the start menu scene loads and renders its background and buttons.
  Screenshot `build/player-smoke.png`, log `build/player-smoke.log`. Two defects:
  1. All text renders as solid blocks. The six TMP SDF atlases failed to export.
  2. `NullReferenceException` in `UniversalRenderPipeline..ctor` every frame (1,048 in 25 s). The URP
     pipeline is not created; likely the global settings/runtime resources reference lost with the
     `globalgamemanagers` read error.
- Reproduce: `tools/recover_campaign.ps1 -Force`, then
  `tools/build_campaign.ps1 -Unity '<…>\6000.4.0f1\Editor\Unity.exe'`.

Gate status: build is repeatable; "functioning campaign map, new/load/save, unit catalog UI" is NOT yet
verified. Nothing past the start menu has been exercised.

Next action: regenerate TMP font atlases from the recovered source fonts, repair the URP global settings
reference, then drive new campaign → map → save → load and record results in the parity matrix.

Previously blocked (kept for history):
- No Unity editor is installed (plan expects 6000.4.0f1) and AssetRipper is not installed. Scenes,
  ScriptableObjects (province database, adjacency, world/supply rules, status template, map catalog, unit
  catalogs) and UI prefabs are still inside `resources.assets`, `sharedassets*.assets`, `level0/1`.
- Without those, the recovery gate (repeatable local build with working map, new/load/save, catalog UI)
  cannot be attempted.

WF spot checks against the installed files (2026-10-04):
- Roster include chain exists loose: `campaign_capture_the_flag.set` (32 B) → `roster_conquest.set` (48 B)
  → `wf_roster_conquest.inc` (587,733 B).
- Ten AI purchase lists present: fra, ger, grm, idf, pla, reb, rus, uaf, usa, usmc.
- `values.set` Warfighter matchups are strictly {usa, usmc, uaf, ger, fra, idf} versus {grm, reb, rus, pla},
  in both directions. No same-bloc pairing is allowed, which constrains campaign diplomacy (plan stage H).

Remaining risks: recovery quality of Unity 6 serialized assets; Netcode/Transport/URP package versions
must be read from the recovered project, not guessed; redistribution status of GOE code is unresolved.

Next action: install Unity 6000.4.0f1 and AssetRipper, run asset recovery into `recovered/unity`, attempt
to open and build. In parallel M2 (WF content resolver and catalogs) can start from the archive indexes.
