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

Both defects fixed (2026-10-04), verified by `tools/smoke_campaign.ps1`: start menu text is legible
("v 0.2.0", Single Player, Multiplayer, Load Campaign, Exit) and the player log has 0 exceptions.
- Cause 1: AssetRipper writes property-only stub shaders. `tools/repair_shaders.py` swaps 46 of 52 stubs
  for the real sources shipped inside the 6000.4.0f1 editor (URP, SRP Core, TMP), via script-free embedded
  packages so `Packages/…` includes resolve. Left as stubs: 3 terrain-detail shaders (unused; 276,480
  variants unstripped) and 3 TMP HDRP/URP-Lit shader-graph variants (no source, unused).
- Cause 2: `GraphicsSettings.m_RenderPipelineGlobalSettingsMap` was empty; the same script restores the
  URP entry.
- Cause 3: six dynamic TMP font assets had dangling atlas references; `tools/unity/WfRepair.cs` gives each
  a fresh atlas that TMP fills from the recovered `.ttf`.
- Side effect handled: URP's editor-side variant stripping is absent, so `tools/unity/WfShaderStripper.cs`
  strips XR passes and unused post-processing variants (UberPost 46,080 → 9, FinalPost 2,560 → 2).
  If a post effect looks wrong later, this keyword list is the first place to check.
- First clean build compiles shaders for roughly 15 minutes; later builds use the cache.

Input repair (2026-10-04): recovered PlayerSettings had `activeInputHandler: 0`; the game uses only the
new Input System, so no click reached the UI. `tools/recover_campaign.ps1` now sets it to 1, sets
`runInBackground`, and renames product/company to `WarfighterCampaign` so saves live in
`%USERPROFILE%\AppData\LocalLow\WarfighterCampaign\WarfighterCampaign`, apart from any GOE install.

Driven acceptance run (2026-10-04, `tools/drive_campaign.ps1`, screenshots in `build/drive/`, 0 exceptions
in every run). The profile directory given to the app was a scratch folder (`build/scratch-profile`);
the real GoH profile was never written.

| Step | Result |
| --- | --- |
| Start menu → Single Player | New Campaign dialog: faction, difficulty, reinforcements, DLC maps, game/profile directory, name |
| Start Campaign (Germany, Normal) | Map scene loads: provinces, ownership colours, borders, battalion markers, resource bar, Week 1 |
| Click province | Info panel fills: name, owner, neighbours, yield, fortification |
| Research | Tree opens with stage/defense nodes and unit portraits |
| End Turn | Week 2; AI factions spawn battalions and pay upkeep; resources accrue (log confirms each faction's turn) |
| Save / Exit | `CampaignSaves/New Campaign.json` written, `TurnNumber` 2, 28 battalions. Map "Exit" saves and quits the app |
| Relaunch → Load Campaign → select → Load | Week 2 state restored |
| Create Battalion / Manage Battalion | NOT verified: both buttons appear disabled on the province tried and did nothing. Cause not investigated (may be a game rule) |

Not exercised: battalion creation and roster UI, movement, attack, battle export, autoresolve, buildings,
diplomacy, ledger, multiplayer. Battle export is deliberately untested because it edits `options.set`.

Gate status: MET for repeatable build, campaign map, new/save/load. Unit catalog UI is only partly seen
(research portraits render); the battalion roster screen is still unverified.

## M2 — WF adapter: IN PROGRESS (factions, research, portraits done; export templates not started)

2026-10-04. Verified in the running app for US Army and GRM (`build/drive/22-…`, `24-…`), 0 exceptions:
the faction dropdown lists the ten WF factions, the turn banner shows the WF name and flag, and the
research screen shows that faction's WF tree with WF unit names and portraits.

Generators (all read WF read-only and write only into `campaign/`):
- `tools/build_wf_content.py` — per faction `GohUnitCatalog_<tag>` and `GohResearchTree_<tag>` under
  `Assets/Resources/WfContent`, portraits under `Assets/Resources/GohPortraits`.
  - Research: `set/dynamic_campaign/unit_research_<tag>.set`, ids/costs/prerequisites/grid kept as-is.
  - Units: `wf_roster_conquest.inc` (the expanded conquest roster), entries carrying the faction tag.
    Section from `{button}` (inf1, inf2, empl, vehicles, tanks).
  - Names: `desc/squad|entity/<id>` in WF localization. Portraits: `interface/scene/portrait_squad`.
  - Manpower cost is DERIVED: `cost + squad_cost_factor × Σ(member breed cost × count)`. WF has no single
    campaign price field, so this formula is ours and needs balancing.
- `tools/build_wf_scenario.py` + `data/scenario_europe.json` — faction slots, sides, turn order, diplomacy
  (same side Allied, opposite sides at War from week 1), flags, WWII scripted events removed.
- `tools/patch_campaign_code.py` + `tools/unity/runtime/WfFactions.cs` — catalogs and research trees are
  looked up by WF army tag; the dropdown and turn banner come from the scenario table; WWII DLC gates on
  the faction dropdown are disabled.

Coverage (from `build/wf-content-report.json`):

| tag | catalog units | tree unit nodes | units outside tree | hidden | placeholder portraits |
| --- | --- | --- | --- | --- | --- |
| usa | 149 | 138 | 11 | 1 | 10 |
| usmc | 106 | 95 | 11 | 10 | 1 |
| uaf | 108 | 97 | 11 | 1 | 10 |
| ger | 100 | 89 | 11 | 1 | 10 |
| fra | 65 | 0 | 65 | 12 | 53 |
| idf | 53 | 0 | 53 | 10 | 43 |
| grm | 130 | 116 | 14 | 1 | 10 |
| reb | 103 | 87 | 16 | 2 | 40 |
| rus | 162 | 142 | 20 | 1 | 10 |
| pla | 117 | 101 | 16 | 10 | 1 |

- Every research unit node resolved to a roster unit (0 unresolved across all ten).
- fra and idf have no unit research in WF (tech nodes only), so all their units are available from the
  start (`ForceResearchedOverride`), as in WF. WF also ships no portraits for them: they get generated
  "no WF portrait" cards with the unit name, not borrowed art.
- "hidden" = roster squads with no name, no portrait and no research entry (squad16–25 style internals).
- A few breeds referenced by units are missing from the roster's cost table (e.g. `mp/usa/tx_pilot_heli_01`,
  `mp/reb/tg_main`); they count as 0 in the derived cost.

Known gaps / provisional:
- Faction slots: the app stores factions as fixed integers, so each WF faction sits in an old WWII slot
  and starts with that slot's 1939 provinces (US Army holds the British Isles, GRM holds Italy, PLA has
  3 provinces in Hungary, …). This is a mechanical placeholder, NOT a scenario. Real starting territory
  has to be authored in `data/scenario_europe.json`.
- Internal enum names are still WWII (`FactionType.Germany` is the Bundeswehr slot, `.UK` is US Army).
- `GohFullUnitTemplateCache` (what battle export needs to write units into `campaign.scn`) still holds
  only WWII units. WF battalions cannot be exported to a battle yet. This is the next M2 item.
- Tactical map catalog and status template still point at WWII regions and `mod_3717998771`.
- Start menu art and title still say Gates of Europa.
- Create Battalion / Manage Battalion still unverified.

### Battle export and tactical maps (2026-10-04)

Reference: a native WF conquest save from the real profile (`conquest 472.sav`), copied read-only to
`build/ref-save`. The real profile is `%LOCALAPPDATA%\digitalmindsoft\gates of hell\profiles\<id>`, not
under Documents as the GOE code assumes.

Maps (`tools/build_wf_maps.py`, `data/maps_pending.json`, `data/export_settings.json`):
- Catalog rebuilt from WF `map_points.set` (Warfighter region): 29 maps, every one verified to have its
  `.mi` and `.info` in WF `map.pak`. Landscape/texmod read from each `.info` (desert 11, winter 6, wood 12).
- 17 maps from MC are registered as pending. None are in the installed WF yet. Each joins the catalog
  automatically on the next generator run once its `.mi` and `.info` exist in WF; until then it is never
  offered.
- Status settings: gameVersion 1.067.0, region `warfighter`, mod dependency `mod_3809475216:0`,
  save name prefix `WarfighterCampaign`. The original author's hard-coded profile path is cleared.
- Map choice is still a uniform random pick from the pool. No per-theater or per-province map binding.

Export templates (`tools/build_wf_content.py`):
- `GohFullUnitTemplateCache` regenerated for WF: 1,093 units, 0 without a template. Soldier loadout,
  armour, perks and veterancy come from `set/breed/mp/<tag>/*.set`; vehicle inventory from the unit's
  `.def` in WF `entity.pak`; crew/passenger split from the roster `content` string.
- 7 vehicles have no literal inventory block in their `.def` (it comes from an include or macro) and are
  exported with an empty box.

Code (`tools/patch_campaign_code.py`):
- Inventory conversion rewritten to the native WF save form. Before: WF ammo names were not recognised
  and 1,200 rounds became 1,200 single items (test save 260 KB). After: tags quoted separately, stacks as
  one counted line, weapons as `filling <ammo tags> <rounds>` (same test save 19 KB).
- Battle result is read from the save's `playedGames`/`wonGames` counters without waiting for GOE's Lua
  bridge file, which WF does not have.
- Bridge exchange directory moved from Documents into the app's own data folder.

Tests (`tools/unity/WfExportTest.cs`, `tools/validate_scn.py`), run headless in Unity batch mode:
- `WfExportTest.Run`: US Army force of 2 squads + 2 vehicles → `build/export-test/…sav`. Structure checks
  pass (18 objects, 18 inventories, 4 squad rows, status names the WF mod and region).
- `WfExportTest.Sweep`: every player-visible unit of all ten factions built individually through the
  app's own `GohCampaignObjectBuilder`: 1,044 ok, 0 failed, 36 with an empty-inventory warning.

NOT verified: no generated save has been loaded in the game. Open risks until that happens:
- squad rows carry an empty stage (`""`) on the single-battalion path where a native save has `stage_1`;
- item `{cell x y}` positions are sequential, not packed by item size as the game writes them;
- whether WF accepts units outside the player's `unlockedResearch` list;
- native saves give emplacements and off-map strikes no Inventory block; ours always write one.

In-game load (2026-10-04): the owner loaded `WarfighterCampaign_export_test.sav` from Conquest with
WarFighter enabled and reported "no errors, looks good". This is an owner report, not something I
observed, and no detail was given on which units appeared. The file in the profile is byte-identical
afterwards (2,297 bytes, `playedGames 0`), so no battle was played and the game has not yet written a
result back. Loading is therefore confirmed; the empty-stage, item-cell and unlocked-research risks
above are not ruled out until a battle is deployed and finished.

### M3 — first battle round trip at component level (2026-10-04)

The owner then played the test battle to its end. The game rewrote the save in place
(2,297 → 279,215 bytes; entries `campaign.scn`, `hq_b`, `status`). Copy kept at
`build/post-battle/post_battle.sav`.

- Status after battle: `playedGames 1`, `wonGames 0`, `{attacking 0}`, mp 100, ap 250, rp 2.
- All 18 exported objects are present afterwards (16 soldiers, 2 vehicles, 18 inventories, 4 squad rows).
  The game itself set every row's stage to `stage_1` and repacked every inventory into its own cell
  layout, so the empty-stage and sequential-cell risks are closed. Units outside `unlockedResearch`
  were accepted.
- `WfExportTest.Import` ran the application's own classes on that save:
  `GohBattleResultReader` → valid, finished, player did not win;
  `GohCampaignScnSquadImporter.ApplyToBattalion` → parsed 4 squads, kept 4, 0 to pool, 0 unknown category;
  each roster entry now carries the game-written squad state (4, 5, 3 and 6 objects).
- Re-export of the imported battalion (the "preserved state" path) passes `tools/validate_scn.py`.

Still open for M3:
- The result was a non-win with no casualties, so casualty handling (dead soldiers, destroyed vehicles,
  captured equipment) is untested. How the battle ended (defeat or retreat) is not recorded.
- The game granted its own mp/ap/rp in `status`; the app must not also reward the battle (plan stage G).
- This was the exporter/importer driven by a test harness. The same trip from the app's UI (create
  battalion → attack → pending battle → resolve → strategic commit → save/reload) is not done.
- No second trip has been loaded in the game from a re-exported, preserved-state save.

### M3 — in-app round trip (2026-10-04)

Owner decision: casualty import is to be ASSUMED working; no casualty battle will be played for now.
It remains untested.

Create Battalion was never broken: the game only allows it in provinces whose specialization is
Manpower (`RequireManpowerProvinceForBattalionSpawn`), and the province tried earlier was not one.

New: `tools/unity/runtime/WfDevAutoplay.cs` (inert unless started with `-wfAutoplay <script>`),
`tools/run_autoplay.ps1`, `tests/autoplay/attack_round_trip.txt`, `tools/simulate_battle_result.py`.
The hook calls the map controller's own methods, needs no mouse or keyboard, and always uses the scratch
profile. Battalion creation through it is free and skips the spawn-province rule; that is a test
shortcut, not game behaviour.

Run as Bundeswehr, both outcomes, 0 exceptions each:

| Step | Result |
| --- | --- |
| New campaign, end turn | AI factions take their turns; 42 battalions on the map |
| Create battalion (2 squads + Leopard 2A4) in Tyrol | created, next to a GRM battalion in Veneto |
| Attack | pending battle created; save exported to the scratch profile: `army ger`, `enemyArmy grm`, WF mod, region `warfighter`, map `dcg_dimitoya_brawl`; passes `validate_scn.py` |
| Resolve after a stand-in WIN | Veneto changes owner to the Bundeswehr slot, battalion moves in, defender removed, roster carries imported squad states |
| Resolve after a stand-in LOSS | Veneto stays with the defender, battalion retreats to an adjacent own province |

The "result" in these two runs is `simulate_battle_result.py` bumping the save's counters, not the game.
The game-written case is the earlier US Army test (loaded, played, read back) through the harness.

Also fixed: province owner, pending-battle owner, auto-resolve winner and co-op messages printed the
WWII enum name of the slot ("Owner: Germany"); they now use the WF faction name.

Observed, not fixed:
- The scratch `options.set` was not modified by an export, although the code path that adds the mod
  dependency exists. Not investigated; the real profile already has WF enabled.
- The Bundeswehr turn banner shows no flag (name is correct).
- Incremental builds now report `errors: 72` (same benign PPtr cast messages).

### Cleanup and ten-faction in-app run (2026-10-04)

- Start menu: GOE artwork/title replaced by WF's own menu image, darkened, with a drawn title
  (`tools/build_wf_branding.py`); version label is "dev build".
- Flags: `build_wf_content.py` was deleting the scenario generator's flag folder on every run; it now
  removes only its own files. Flags prefer WF's full-brightness `flag_<tag>` and brighten the dim
  `tooltip_flag_<tag>` versions (used for usa, ger, rus).
- `options.set` is written only by the app's "Launch Gates of Hell" button, never by export. It now
  keeps a one-time `options.set.wfcampaign.bak` before its first change. User-facing text names WarFighter.
- Autoplay `setup auto` picks the faction's own first infantry squad, support squad and armoured unit.
  A run that put German units in an AFRF battalion was correctly refused by the exporter
  ("No full GoH template data … export aborted") instead of writing a bad save.

`tests/autoplay/attack_round_trip.txt` for each faction, stand-in win, 0 exceptions in all ten runs:

| Faction | Units | Attack | After resolve |
| --- | --- | --- | --- |
| uaf | squad1, command_team_t2, acv-15_aapc | exported, vs PLA | province captured |
| ger | squad1, command_team_t2, gtk_boxer_gmw | exported, vs GRM | province captured |
| fra | squad1, command_team_t2, amx10rc | exported, vs GRM | province captured |
| grm | squad1, command_team_t2, bmp1_grm | exported, vs US Army | province captured |
| rus | squad1, command_team_t2, 2s25m | exported, vs UAF | province captured |
| pla | squad1, command_team_t2, aft10 | exported, vs Bundeswehr | province captured |
| usa, usmc, idf, reb | — | not reached | no own province borders an enemy battalion after one turn |

The four that did not attack are a consequence of the placeholder territory (e.g. US Army in the
British Isles), not an export failure. Their exports are covered by the headless sweep only.

Known noise: incremental player builds log 60 × "PPtr cast failed … PluginImporter to MonoScript" and
report `errors: 60` while succeeding. Clean builds report 0. The built app runs with 0 exceptions.

Next action: load `build/export-test/WarfighterCampaign_export_test.sav` in the game (needs a copy into
the real profile's `campaign` folder), fix what the game rejects, then drive a full attack from the app.

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
