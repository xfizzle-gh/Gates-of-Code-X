# GOE feature-parity matrix (from decompiled Assembly-CSharp)

Source: `recovered/csharp/*.cs` (ILSpy output). Nothing was executed. Every status below is a reading of method bodies only.
Status vocabulary: **implemented in code (unverified at runtime)** = "impl."; **partial/stubbed**; **absent**.
File refs are `File.cs:line` in the decompiled tree. `PMC` = `ProvinceMapController.cs` (7613 lines, the hub MonoBehaviour).
No decompile failures (`//IL_`, "Expected O", `NotImplementedException`) were found in the strategic-layer files; the only artefacts are two harmless `goto IL_0047` in `BattalionListPanel.cs:98` / `CampaignLedgerPanel.cs:94`.

## 1. Matrix

| # | Feature | Key classes / methods | Status | WWII / hard-coded assumptions WF must change |
|---|---|---|---|---|
| 1a | Province ID texture + picking | PMC `TryGetProvinceIdAtScreenPosition` :5563, `BuildLookups` :7223, `EnsureProvinceIdPixelCache` :4861 | impl. | `provinceIdTexture` (Texture2D) and `provinceDatabaseJson` (TextAsset) are scene-serialized: the Europe map itself is asset data, not code |
| 1b | Adjacency | `ProvinceDefinition.NeighborProvinceIds`; PMC `AreNeighboringProvinces` :5680 | impl. (pure data lookup) | Neighbor lists come from the province JSON asset; no code generates adjacency from the texture |
| 1c | Terrain | `ProvinceDefinition.TerrainType` (string); shown at `ProvinceInfoPanel.cs:119` | partial/stubbed: stored and displayed only, no gameplay effect | none in code |
| 1d | Ownership overlay, selection highlight | PMC `RedrawOwnershipTexture` :4660, `RedrawHighlightTexture` :4759, `GetOwnerTint` :4805, `GetFactionMarkerColor` :4783 | impl. | Per-faction colours hard-coded for 14 WWII nations (:4787-4800, :4809-4822) |
| 1e | Border rendering | none | absent (no border code; any borders are baked into the visible map sprite) | n/a |
| 1f | Map region per province | `ProvinceDefinition.MapRegion`, enum `GohCampaignMapRegion` | impl. | Enum = EasternEurope / WesternEurope / FinlandNorthernRussia / Generic |
| 2a | New campaign | `StartMenuController.StartNewCampaign` :457, `BuildRequestFromUi` :478, `ValidateRequest` :524; `CampaignStateBuilder.BuildFromSetup`; PMC `ApplyNewCampaignSettings` :7049 | impl. | Faction dropdown strings :786-789; DLC gating :563-570; scene name `"SampleScene"` :129 |
| 2b | Save | PMC `SaveCampaignState` :7125 -> `JsonFileService.Save` (Unity `JsonUtility`, pretty-printed) | impl. (autosave after nearly every action; no manual slots) | Path `persistentDataPath/CampaignSaves/<name>.json` (`Paths.cs:32-37`) |
| 2c | Load / delete / host-from-save | `StartMenuController.RefreshLoadList` :896, `LoadSelectedCampaign` :963, `HostSelectedCampaign` :977, `ConfirmDeleteSelectedCampaign` :1003; PMC `LoadCampaignState` :6995 | impl. | none beyond paths |
| 3a | Movement | PMC `TryIssueBattalionOrder` :5689, `MoveBattalionToProvince` :5774, `SwapBattalions` :5837, `TrySpendMovementForProvinceMove` :6677 | impl. | One battalion per province; movement per type from `BattalionTypeRulesAsset` |
| 3b | Attack declaration | PMC `StartAttack` :1968, `OnAttackPressed` :1891, `CanAttackProvince` :5881 | impl. | Requires diplomatic state War; attack costs 1 move + 1 combat action |
| 3c | Turn structure | PMC `BeginCurrentTurnIfNeeded` :6359, `EndTurn` :6398, `AdvanceToNextFaction` :6426, `ResolveNonHumanTurnsUntilHumanTurnRoutine` :7421 | impl. | Sequential faction turns; default order Germany, SovietUnion, Finland, Poland, UK |
| 3d | "Larger battles" reinforcements | PMC `GetEligibleReinforcementsFromNeighbors` :4318, `PromptForBattleReinforcements` :4060, `BuildBattleParticipants` :4407 | impl. | `MaxReinforcementsPerSide = 4` (PMC:122, :4339) |
| 4a | Territory capture | PMC `MoveBattalionToProvince` :5819, `CaptureTargetProvince` :924; `CampaignAllianceUtility.ResolveCaptureOwner` :84 | impl. | AI captures adjacent to an allied human's land are handed to that human |
| 4b | Retreat | PMC `TryRetreatPlayerBattalionToAlliedNeighbor` :941, `TryRetreatPlayerBattalionToOwnedAdjacentProvince` :987; `CampaignAiCombatRunner.TryRetreatBattalion` :666 | impl. | none |
| 4c | Encirclement / surrender | `CampaignEncirclementUtility.FindPockets` :44, `CalculateSurrenderChance` :116; PMC `ApplyEncirclementForFactionTurnStart` :2839, `ResolvePocketSurrenderCheck` :2960 | impl. | Supply source = owned province with `Ammunition` specialization |
| 4d | Faction elimination | PMC `UpdateEliminationStates` :5149 | impl. | none |
| 4e | Victory / defeat conditions | none | **absent** | n/a (must be designed for WF) |
| 5a | Province yields / income | PMC `CalculateIncomeForFaction` :6308, `GrantIncomeToFaction` :6349 | impl. | 4 resources hard-wired into `CampaignResources` |
| 5b | Recruitment cost | `BattalionManagementPanel.RecruitUnit` :516 | impl. | Costs live in serialized `GohUnitCatalog` entries |
| 5c | Upkeep | `CampaignSupplyRulesAsset.CalculateBattalionUpkeep` :206, `CanPayEndOfTurnUpkeep`; PMC `TryPayEndOfTurnSupplyForFaction` :6507 | impl. | Per-type upkeep keyed on WWII `BattalionType` enum |
| 5d | Resupply / refit | `CampaignResupplyUtility.TryResupplyBattalion` :68; PMC `ResupplyAllLocalBattalions` :5365 | impl. (needs full-template data, else blocked) | none |
| 5e | Ammo / fuel as distinct stocks | `CampaignResources.Ammunition` only | partial: one "Ammunition" stock shown as "Supplies"; **fuel absent** | WF fuel must be added if wanted |
| 5f | Buildings (province specialization) | PMC `ApplyProvinceBuildingOperationForFaction` :3804, `TryAddProvinceSpecialization` :3969, `TryUpgradeProvinceSpecialization` :4002; `ProvinceBuildingRulesAsset` | impl. | 4 specializations = the 4 resources |
| 5g | Fortifications | PMC `TryUpgradeProvinceFortification` :4034; `ProvinceBuildingRulesAsset.GetTotalFortificationAutoResolveBonus`, `GetDefenseResearchKeysForLevel` | impl. | Research keys `defense_level_1..3` must exist in the tactical-side mod |
| 6a | Create battalion / recruit / roster edit | PMC `OpenCreateBattalionInSelectedProvince` :1101, `ApplyBattalionManagementResultInternal` :1197; `BattalionManagementPanel` `RecruitUnit` :516, `MoveFromPoolToBattalion` :644, `MoveFromBattalionToPool` :674 | impl. | Category caps per `BattalionType` |
| 6b | Disband | `BattalionManagementPanel.HandleDisbandPressed` :328; PMC `ApplyBattalionDisbandResult` :1258 | impl. | none |
| 6c | Merge / split | none | **absent** (only same-faction position `SwapBattalions`) | n/a |
| 6d | Strength levels | `BattalionStrengthUtility` (`GetStrengthLevelFromPercent` :46, `GetWeightedStrengthValue` :146) | impl. | Type scores hard-coded :326-338 |
| 6e | Ledger / battalion list panels | `CampaignLedgerPanel`, `BattalionListPanel`, PMC `BuildFactionLedgerRows` :6106 | impl. | none |
| 7 | Research | `ResearchTreePanel.OnNodeClicked` :297; PMC `ApplyResearchTreeResultForFaction` :7371; `GohResearchCatalogSync.ApplyResearchToCatalog` :6 | impl. (human only) | One `GohResearchTreeAsset` per hard-coded faction field |
| 8 | Strategic AI | `CampaignAiRunner.RunFactionTurn` :36; `CampaignAiCombatRunner.RunCombat` :29; PMC `RunPlaceholderTurn` :6491 | impl. (spawn, move, capture, attack, auto-resolve); AI research/building/resupply **absent** | Production weights and costs keyed on `BattalionType` |
| 9a | Diplomacy states / declare war | `CampaignDiplomacyUtility`, PMC `ExecuteDeclareWarForFaction` :2770 | partial: only "declare war" is player-reachable; no peace/alliance UI | 5 states: War/Hostile/Neutral/Friendly/Allied |
| 9b | Alliances | `CampaignAllianceUtility` | impl. (transit, no-attack, shared pockets, capture hand-over) | none |
| 9c | Scripted events | `CampaignScriptedEventRunner.ProcessTurnStart` :7 | impl.; 2 action types only (SetDiplomaticState, AnnexFactions) | Event list is asset data; trigger field is called `TriggerWeek` |
| 10 | Auto-resolve | PMC `ExecuteHostAutoResolvePendingBattle` :638, `ApplyPendingBattleAutoResolveConsequences` :833; `BattalionStrengthUtility.CalculateAttackerWinChance` :158, `DetermineOutcome` :165; `CampaignAiCombatRunner.AutoResolveBattle` :441 | impl. | Bias rules per faction pair in `CampaignWorldRulesAsset` |
| 11 | Co-op multiplayer | `CampaignNetworkSessionManager` (NetworkBehaviour), `CampaignMultiplayerUtility`, PMC `ExecuteHost*` | impl. | Max 3 humans; same-side only; Axis/Allies sides |
| 12 | Unit catalog import | `GohUnitCatalogImporter`, `GohFullUnitTemplateImporter`, `GohPakDataSource`, `GohFullUnitTemplateCache(+Attacher)` | **partial/stubbed at runtime**: build uses pre-baked assets; importers have no runtime caller | see notes 12 |
| 13 | Tactical map catalog | `GohConquestMapCatalog.GetRandomMapForContext` :22; `StatusExporter.ExportRandomStatus` :9 | impl. (random pick from a serialized pool) | Pools Ostfront/Talvisota/West/Finest_Hour/West_FH; DLC names hard-coded |
| 14 | Tactical battle round trip | `CampaignScnExporter`, `StatusExporter`, `GohBattleSaveExporter`, `GoeBattleBridgeContextWriter`, `GohBridgeResultReader`, `GohBattleResultReader`, `GohCampaignScnSquadImporter`, `GohModDependencyUtility`, `PendingBattleRecord`; orchestrated by PMC `StartAttack` :2090-2139, `LaunchGatesOfHell` :1819, `ResolvePendingBattleFromBridgeFile` :2214, `TryResolvePendingBattleFromSavStatus` :2271, `TryApplyPostBattleCampaignScnToPlayerBattalion` :2526 | impl. | Mod id `mod_3717998771:0`; see `battle-round-trip.md` |

## 2. Notes per area

### 1 Province map
- Picking: screen point -> world -> UV inside `visibleMapRenderer.bounds` -> `provinceIdTexture.GetPixel` -> `provinceIdByColor[Color32]` (PMC:5570-5584). Requires the ID texture to be CPU-readable and colours to match `ProvinceDefinition.IdColor` exactly.
- Two province collections: static `provinceDefsById` (from `provinceDatabaseJson`) and mutable `runtimeProvincesById` (from `CampaignState.Provinces`). Neighbor/name/terrain/yield are back-filled from static into runtime (PMC:7244-7272).
- `ProvinceDefinition` fields: ProvinceId, DisplayName, TerrainType, MapRegion, Owner (`FactionType`), NeighborProvinceIds, IdColor, MarkerPosition, OccupyingBattalionId, ResourceYield{Manpower,Ammunition,Research,Support}, Specialization (string), SpecializationLevel, FortificationLevel.
- Ownership overlay is rebuilt per pixel on change (signature-cached); highlight is a 56-alpha white mask of the selected province.
- Input: left click selects, right click issues move/swap/attack order (PMC:6939-6949), new Input System (`Mouse.current`).

### 2 New / load / save
- Format: one `JsonUtility` JSON of `CampaignState` (fields listed in `CampaignState.cs`: name, turn, selected faction, difficulty, network schema, host id, HumanPlayers, EnabledDlcMapPacks, LargerBattles, GameDirectory, ProfileDirectory, CurrentTurnFaction, income/turn flags, FactionStates, Provinces, Battalions, QueuedAiBattleOrders, legacy Resources/RecruitedPool/ResearchedKeys, DiplomacyProfiles, FiredScriptedEventIds). Enums serialize as integers, so **reordering `FactionType` breaks old saves and all serialized assets**.
- Locations (`Paths.cs`): saves `persistentDataPath/CampaignSaves/<SafeName>.json`; working files `persistentDataPath/Runtime/{pending_battle.json, campaign.scn, status, campaign.sav, ProcessedBattleResults/}`; settings `persistentDataPath/startup_settings.json` (`StartupSettingsService.cs:6`); bridge files `%USERPROFILE%/Documents/My Games/gates of hell/GatesOfEuropa/{goe_battle_context.lua,last_battle_result.txt}` (`Paths.cs:22-26`).
- Declared but unused: `Paths.CampaignStatePath`, `LastResultPath`, `ArchivedCampaignsDirectory`; `CampaignStateExporter` is an empty class.
- The pending battle is a single global file (`pending_battle.json`), not per campaign save; a new campaign clears it (PMC:7012).
- New campaign: provinces cloned from the JSON asset, starting battalions from `CampaignSetupAsset.StartingBattalions`, starting resources from `CampaignFactionDefinition.StartingResources`, diplomacy cloned from world rules. Fallback when no bootstrap object exists: `campaignStateJson` TextAsset (PMC:7029).
- "Legacy" top-level Resources/RecruitedPool/ResearchedKeys mirror the local player's `CampaignFactionState` (`SyncLegacyFieldsFromLocalPlayer` PMC:5249).

### 3 Movement, attacks, turn structure
- Allowance per turn: `BattalionTypeRule.MovementPerTurn`; plus `FriendlyTerritoryMovementBonus` (default 2) free steps while both origin and target are own/allied; combat actions 2 for Motorized/Mechanized/LightTank, else 1 (PMC:6733-6745, duplicated in `CampaignAiRunner.cs:231`).
- Entering an empty enemy province = capture, costs 1 move + 1 combat action (PMC:6687). Entering requires Allied (transit) or War (conquer); otherwise refused.
- Only one pending battle at a time (PMC:1980). AI attacks on humans are queued in `QueuedAiBattleOrders` and started one by one (`TryStartNextQueuedAiBattle` :2323).
- Turn start for a faction: scripted events -> clear spawn list -> income -> reset movement -> encirclement (PMC:6385-6391). Turn end: upkeep payment; humans are blocked from ending the turn if upkeep cannot be paid (:6522-6525), AI auto-disbands cheapest battalions (:6549). `TurnNumber` increments when the order wraps (:6458-6460).
- Human-vs-human battles are explicitly refused (PMC:2023-2026).

### 4 Capture, retreat, encirclement, elimination, victory
- Retreat after a lost defence goes to a random unoccupied own neighbor; failed attacker retreat goes to first unoccupied own/allied neighbor of the origin; with no retreat hex, a human roster is moved to the recruited pool and the battalion removed, AI battalion is deleted.
- Encirclement: flood fill over passable (own/allied, no enemy battalion) provinces; pocket is supplied if it contains an Ammunition-specialized province (`CampaignEncirclementUtility.cs:316-326`). First encircled turn is a grace turn; from turn 2: movement cap 1, no friendly bonus, strength level drops one step per turn, auto-resolve penalty 35, surrender roll (base 0.10, +0.10/turn, modifiers, clamp 0.05..0.85) which deletes all faction battalions in the pocket.
- Elimination = no province and no battalion (PMC:5166-5170); eliminated factions are skipped in turn order. Nothing else happens: **no win/lose screen, no objective, no end-of-campaign logic anywhere in the assembly**.

### 5 Economy
- Resources (`CampaignResources.cs`): `Manpower`, `Ammunition` (UI label "Supplies", `ResourceBarPanel.cs:51`), `Research`, `Support`. No fuel, no money.
- Income = sum of owned province `ResourceYield`; Ammunition x `AmmunitionYieldMultiplier` (10); +1 Support per Artillery battalion.
- Upkeep = per-type base Ammunition (100..350) + per-roster-unit Ammunition (10..25) and fractional Support (Aircraft 0.25) with carried `FractionalSupportUpkeepDebt`.
- Recruit: spends Manpower + Support from catalog entry costs; units go to a faction "recruited pool" then into battalions. Resupply: Manpower + Ammunition proportional to missing readiness, per category rule.
- Battalion creation only in own, empty, Manpower-specialized provinces, 1 per province per turn (`CampaignWorldRulesAsset.cs:11-13`, PMC:5942-5984).
- Buildings: a province has at most one specialization (Research/Ammunition/Support/Manpower), levels 1..3, costs paid in Research points; yield from `SpecializationYields` or fallback (level, level, 10xlevel, 10xlevel). Fortification 0..3, +10 auto-resolve defence per level and unlocks `defense_level_N` keys in the exported tactical status when the human defends (PMC:1515-1527).
- Every exported battle also force-unlocks `reinforcement_stage_1..5` (PMC:1517).

### 6 Battalion management
- `BattalionType` enum: Infantry, Motorized, Mechanized, LightTank, MediumTank, HeavyTank, Artillery. Caps per `GohUnitCategory` (Infantry/Emplacement/Vehicle/Tank/Aircraft/Doctrine) in `BattalionTypeRulesAsset` (code defaults in `FillDefaultRules`, :26).
- Changing type dumps the whole roster to the pool (`BattalionManagementPanel.cs:377-404`). At least one unit required. Save is refused if resulting upkeep is unaffordable (PMC:1319).
- Human battalions carry a real `Roster` (`BattalionRosterEntry` UnitName/Stage/Quantity/SquadStates with per-squad post-battle state). AI battalions are "empty": `AbstractUnitCount/AbstractMaxUnitCount` only, no roster.
- Strength level from fill percent: Elite >= 90, High >= 60, Normal >= 25, else Weak. Strength score = type score (30..68) + percent.
- Battalion ids are `<factionTag>_<n>` (PMC:1370).
- `BattalionData.Infantry/Armor/Support` ints are legacy and always 0.

### 7 Research
- `GohResearchTreeAsset` {FactionTag, Nodes[{Id, Kind Unit|Tech, Section, Cost, GridPosition, Requires[]}]}. Cost paid in Research points. Researched keys stored per faction; `ApplyResearchToCatalog` sets `GohUnitCatalogEntry.IsResearched`, which gates recruitment. Zero-cost, no-prerequisite Unit nodes are unlocked by default.
- Node-to-unit matching is by `ResearchKey`/`RawName` with faction suffix `(...)` stripped. `GohResearchProgressAsset` exists but has no caller.
- Tech nodes have no coded gameplay effect other than being stored keys.

### 8 Strategic AI
- Entry: PMC `RunPlaceholderTurn` (name is historical; body is real). Runs only if `CampaignFactionDefinition.AIEnabled` and faction not human.
- `CampaignAiRunner`: spawn up to `EmptyBattalionsPerTurn` abstract battalions in Manpower provinces (weighted type from `AiProductionWeights`, strength from `BattalionStrengthGenerationRulesAsset`, paid in Manpower, must keep upkeep payable); then move each battalion through friendly territory toward the highest-priority owned province (priority constants :16-34: War border 800 (+160 if enemy province empty), Hostile 700, AlliedWarBorder 650, specialized 600, Neutral 500 ...).
- `CampaignAiCombatRunner`: keep a front-line reserve (`FrontLineReserveBattalions`/`Percent`), capture up to `MaxUnoccupiedProvinceCapturesPerTurn` empty enemy provinces (value + 120 bonus + encirclement estimate, -100 if it would cut own supply), queue up to `MaxPlayerBattalionAttacksPerTurn` attacks on humans (weakest defender first; these become playable battles), auto-resolve up to `MaxAiVsAiAutoResolveBattlesPerTurn` AI-vs-AI fights.
- AI never researches, builds, fortifies, resupplies, or declares war. `CampaignAiSettings` asset is referenced by a PMC field (:268) but never read.

### 9 Alliances, diplomacy, scripted events
- State per faction pair in `CampaignState.DiplomacyProfiles`, seeded from `CampaignWorldRulesAsset.DiplomacyProfiles`; unknown pair = Neutral. Only `War` allows attack/capture; only `Allied` allows transit and joint reinforcement. Hostile/Friendly affect AI movement priority only.
- Player action: declare war on the owner of the selected province (immediate, no cost, no cooldown). No way to make peace or ally except scripted events.
- Scripted events fire at `TriggerWeek == TurnNumber` during `TriggerFaction`'s turn start; actions: set diplomatic state between two factions, or transfer all provinces of listed factions to an annexing faction (battalions are not transferred or removed).

### 10 Auto-resolve
- Chance = A/(A+D), A = attacker strength + modifiers, D = defender strength + modifiers + fortification; clamp 0.05..0.95. Outcome tier from |chance - roll| and score gap; winner loses 5/10/18/32 %, loser 35..100 %.
- Human rosters lose real units via weighted random by category (infantry most likely); AI lose abstract counts.
- Player-involved battles: `PendingBattleResolutionPanel` offers auto-resolve, launch game, manual attacker/defender win. Faction bias rules are applied only in AI-vs-AI (`includeBiasRules: false` at PMC:814-815, :2149-2150).

### 11 Co-op / multiplayer
- Transport: Unity Netcode for GameObjects + `UnityTransport`, direct IP, host binds `0.0.0.0:<port>`, default port 7777 (`CampaignNetworkSessionManager.cs:37`, :209). No relay, lobby or NAT traversal; status text tells users to use Hamachi/ZeroTier (:220).
- Authority: host-authoritative. Clients send ServerRpcs (RegisterPlayer, ClaimFaction, EndTurn, MoveBattalion, StartAttack, PendingBattleReinforcementSelection, SubmitBattleResult, AutoResolvePendingBattle, CancelPendingBattle, ResearchResult, BattalionManagementResult, ProvinceBuildingOperation, DeclareWar; list at :1605-1623). Host checks sender owns the faction and that it is that faction's turn.
- **Max players = 3**, enforced at: `CampaignMultiplayerUtility.cs:7` (const) and :53; `CampaignNetworkSessionManager.cs:583`, :598 (join refusal message); `StartMenuController.cs:577`; PMC:7075.
- Synchronized: the entire `CampaignState` as JSON, split into 12000-char chunks (`ReceiveCampaignSnapshotChunkClientRpc`, :39, :697-711), re-sent after every host mutation; the `PendingBattleRecord` JSON; the player slot list; per-client feedback strings. No delta sync.
- Co-op only: all humans must be on the same side as the host (`CanClaimCoopFaction` PMC:3612; sides from `CampaignFactionDefinition.Side`, fallback Axis/Allies table). Host must press "start turns" (`StartMultiplayerCampaignTurns` :3681).
- Tactical battles are played by the battle owner; a remote owner exports locally and returns the result plus post-battle `campaign.scn` text via `SubmitBattleResultServerRpc`.
- Weak points visible in code: host accepts client-computed `UpdatedResources`, roster and pool in research and battalion-management results without recomputing costs (PMC:1223-1227, :7376-7379); `ResupplyAllLocalBattalions` (:5365) has no RPC path, so on a client it mutates local state only; in the UI a new host campaign always sends exactly one human faction (`StartMenuController.cs:490`), other players claim on join.
- `ChatController.cs` is a TextMeshPro sample, not campaign chat.

### 12 Unit catalog import from game data
- Runtime reality: PMC `EnsureGohFullTemplatesEnriched` (:5305) only loads the `GohFullUnitTemplateCache` ScriptableObject (scene field or `Resources.Load("GohFullUnitTemplateCache")`, :5320) and attaches cached templates to catalogs. **No code path in the shipped build opens a game .pak.**
- `GohUnitCatalogImporter.cs`: only private helpers and a nested `NotFound()` survive; the public import entry point was editor-only and is not in the build. It expected loose files in `Assets/GohUnits` (`units_<tag>.set`, `inf_<tag>.set`, `settings.set`, `unit_research_<tag>.set`; `GohUnitCatalogImportSettings.cs:6-18`).
- `GohFullUnitTemplateImporter.EnrichCatalogs` (:87) is complete but its only caller is `GohTemplateValidationUtility`, which itself has no caller. It reads, via `GohPakDataSource` (`System.IO.Compression.ZipArchive`), `<game>/resource/gamelogic.pak` (required) and `<game>/resource/entity/-vehicle.pak` (optional) (`GohPakDataSource.cs:40-53`); folders `set/multiplayer/units/conquest/*.set` (files prefixed `inf_`, `units_`) and `set/breed/mp/<tag>/<period>/<alias>.set`; entity files `*.def/*.inc/*.ext/*.set` (:516). Mod folders / workshop paks are never scanned.
- Parsing is **regex plus brace counting, not a real .set parser**: line split, `{`/`}` depth counting to delimit blocks (`GohUnitCatalogImporter.cs:216-261`, `GohFullUnitTemplateImporter.cs:220-261`), then regexes for `name(...)`, `{"..."`, `cost`, `round_multiple`, `squad_cost_factor|scf`, `vehicle(...)`, `c1(alias:n)`/`crew(...)`, `action`, `side`, `tag`, `period`, skin/portrait/icon/nationality/voice (`GohUnitCatalogImporter.cs:64-80`, `GohFullUnitTemplateImporter.cs:46-62`). `GohSetSyntaxUtility` adds `FindMatchingBrace`/`ExtractNamedBlock`/hex-id rewriting. Comments are recognised only as lines starting with `;`.
- Faction tag is guessed from the catalog asset's *name* substring (`GohFullUnitTemplateImporter.cs:618-641`, `GohFullUnitTemplateCacheAttacher.cs:50-71`): ger / rus|ussr / fin / usa / eng|commonwealth -> {can, eng, pol}.
- Other editor-time leftovers: `GatesOfHellSetNameExtractor` (writes `Assets/GohUnits/*_names.json|txt`), `GohConquestMapImportSettings`, `GohGameDataLocator`.
- `GohDirectoryAutoFinder` (used by start menu) finds the game via Steam `libraryfolders.vdf` and folder name `"Call to Arms - Gates of Hell"` (:22, :42), exe `call_to_arms.exe` (`GohGamePathUtility.cs:6`, expected at `<game>/binaries/x64/`), profiles under `Documents/My Games/gates of hell/profiles` or `%LOCALAPPDATA%/Digitalmindsoft/...` (:125-157).

### 13 Map catalog
- `GohStatusExportSettings.MapCatalog` (asset) holds `Pools` and flat `Maps`. Selection: region of target province + enabled DLC -> ordered pool list -> uniform random map from first non-empty pool -> fallback any map (`GohConquestMapCatalog.cs:22-34`, :97-153). No per-province map binding, no terrain matching, no repeat avoidance.
- `GohConquestMapEntry`: MapId, RawMapPoint, Pool, Region, MapPack, Landscape, Texmod, GameMode (`campaign_capture_the_flag`), Size (`4x4`); emitted as `multi/<id>:<mode>:<size>` and region string ostfront/talvisota/west/finest_hour/west_fh.
- The importer that built the catalog from `set/dynamic_campaign/map_points.set` is not in the build; only its settings class with a developer path `G:\SteamLibrary\...` and `C:\Program Files\7-Zip\7z.exe` remains (`GohConquestMapImportSettings.cs:8-18`).

### 14 Tactical battle round trip (summary)
Export `campaign.scn` (player roster) + `status` (from a TextAsset template with `%ARMY%`, `%ENEMY_ARMY%`, map, seed...) -> zip into `.sav` in the GoH profile campaign folder -> write Lua bridge context -> ensure `mod_3717998771:0` in `options.set` -> launch `call_to_arms.exe`. Result: bridge txt must report finished + matching battle id, then winner is taken from the `.sav` status counters (`playedGames`/`wonGames` delta), and the post-battle `campaign.scn` is imported back into the roster. Details in `docs/battle-round-trip.md`. Oddity: exported `playedGames` = `TurnNumber - 5` clamped at 0 (PMC:1501-1508).

## 3. Hard-coded faction / nation data

| What | Where |
|---|---|
| `enum FactionType` (16): Germany, SovietUnion, USA, UK, Poland, Finland, Netherlands, Belgium, Italy, Neutral, France, Hungary, Romania, Estonia, Latvia, Lithuania | `FactionType.cs:1-18` |
| `enum FactionChoice` (playable): Germany, USSR, Finland, Commonwealth, USA | `FactionChoice.cs:1-7` |
| `enum CampaignFactionSide`: Unspecified, Axis, Allies, Neutral | `CampaignFactionSide.cs` |
| FactionChoice -> FactionType map (Commonwealth -> UK) | PMC:5260-5270; `CampaignMultiplayerUtility.cs:118-128` |
| Faction -> army tag `ger/rus/usa/eng/fin`, default `ger` | PMC:1478-1486, :7559-7567; `CampaignWorldRulesAsset.cs:265-276` |
| Default tag `"ger"` in data classes | `BattalionData.cs:21`, `BattalionDefinitionAsset.cs:15`, `CampaignFactionDefinition.cs:21`, `GohUnitCatalogImportSettings.cs:6`, `CampaignScnExporter.cs:344` |
| Status fallback army `ger` vs `rus` | `StatusExporter.cs:52-53` |
| Catalog-name tag guessing incl. `can`, `pol` | `GohFullUnitTemplateImporter.cs:618-641`; `GohFullUnitTemplateCacheAttacher.cs:53-71` |
| Default turn order Germany, SovietUnion, Finland, Poland, UK | `CampaignTurnOrder.cs:3-10`; `CampaignWorldRulesAsset.cs:23-30`, :147-151 |
| Default Axis/Allies membership | `CampaignWorldRulesAsset.cs:278-300`; PMC:7530-7550 |
| Per-faction catalog/research fields (germany, ussr, finland, commonwealth; USA and UK share commonwealth) | PMC:215-236, :7471-7487, :7570-7611 |
| Faction colours | PMC:4783-4825 |
| Start-menu faction list "Germany","USSR","Finland","Commonwealth" (USA not offered) | `StartMenuController.cs:786-789` |
| DLC names "Finest Hour", "Liberation", "Talvisota" and faction gating | `StartMenuController.cs:506-514`, :563-570, :593-600; `GohConquestMapCatalog.cs:99-101`, :155-188 |
| Map pools / packs / regions | `GohConquestMapPoolName.cs`, `GohMapPack.cs`, `GohCampaignMapRegion.cs`, `GohConquestMapEntry.cs:50-57` |

Other hard-coded identifiers: mod id `mod_3717998771:0` (`GohModDependencyUtility.cs:8`, :80-133); exe `call_to_arms.exe`; `gamelogic.pak`, `-vehicle.pak`; `options.set`; `campaign.scn`, `campaign.sav`, `status`; save prefix `GatesOfEuropa_Battle`, game version `1.062.0`, fog `fog_realistic`, map points `hq_a`/`hq_b` (`GohStatusExportSettings.cs:13-43`, asset may override); scenes `"SampleScene"` and `"StartMenu"`; port 7777; research keys `reinforcement_stage_1..5`, `defense_level_1..3`; resource names Manpower/Ammunition("Supplies")/Research/Support.

## 4. Data living in Unity serialized assets (recover with AssetRipper)

Values below are *code defaults*; the shipped assets may differ, and list fields are usually empty in code.

| ScriptableObject | Serialized fields | Referenced from |
|---|---|---|
| `CampaignWorldRulesAsset` | FriendlyTerritoryMovementBonus, RequireManpowerProvinceForBattalionSpawn, MaxBattalionSpawnsPerProvincePerTurn, AiUnoccupiedEnemyProvinceCaptureBonus, AiUnoccupiedEnemyProvinceBorderPriorityBonus, **Factions** (`CampaignFactionDefinition`: Faction, DisplayName, Side, ParticipatesInTurnOrder, HumanSelectable, AIEnabled, UnitFactionTag + RequiredDlc, Backup tag + RequiredDlc, Fallback tag, StartingResources, DefaultAiBattalionType, EmptyBattalionsPerTurn, AI caps, reserve settings, Flag sprite), TurnOrder, **DiplomacyProfiles**, BaseAutoResolveAttack/DefenseBonus, AutoResolveBiasRules, encirclement constants | PMC:279 |
| `CampaignSupplyRulesAsset` | AmmunitionYieldMultiplier, ArtilleryBattalionSupportIncomeBonus, BattalionTypeRules, RosterCategoryRules, ResupplyCategoryRules, AiProductionWeights, AiManpowerPurchaseCosts, AiStrengthManpowerPurchaseCosts | PMC:283 |
| `ProvinceBuildingRulesAsset` | MaxSpecializationLevel, MaxFortificationLevel, Remove/Add/DefaultUpgrade costs, SpecializationUpgradeCosts, SpecializationYields, DefaultFortificationUpgradeCost, DefaultFortificationAutoResolveBonusPerLevel, FortificationLevels | PMC:294 |
| `BattalionTypeRulesAsset` | Rules[] (BattalionType, MovementPerTurn, MaxInfantry/Emplacement/Vehicle/Tank/Aircraft/Doctrine) | PMC:262 |
| `BattalionStrengthGenerationRulesAsset` | DefaultWeights (Weak/Normal/High/Elite), ModifierRules (faction, difficulty, turn window, weight deltas) | PMC:265 |
| `CampaignScriptedEventsAsset` | Events[] (EventId, Title, Description, TriggerWeek, TriggerFaction, FireOnlyOnce, Enabled, Actions[]) | PMC:287 |
| `CampaignSetupAsset` | StartingTurn, StartingBattalions (refs to `BattalionDefinitionAsset`) | PMC:169 |
| `BattalionDefinitionAsset` | BattalionId, Faction, ProvinceId, IsPlayerControlled, GohFactionTag, Roster, BattalionType | via setup |
| `GohUnitCatalog` (x4: germany, ussr, finland, commonwealth) | Entries[] (RawName, DisplayName, EntryType, AppendFactionTagInCampaignScn, Category, Section, portrait paths, IsResearched, ForceResearchedOverride, HideFromBattalionManagement, ResearchKey, ManpowerCost, SupportCost, CostsImportedFromGame, full-template fields) | PMC:215-224 |
| `GohResearchTreeAsset` (x4) | FactionTag, Nodes[] | PMC:227-236 |
| `GohFullUnitTemplateCache` | SourceGameDirectory, BuiltAtUtc, BuilderVersion, pak signatures, Entries[] (CatalogAssetName, RawName, FactionTag, HasFullTemplateData, BuildError, Warnings, Template: raw conquest definition, humans with raw breed/inventory/armor/perk/veterancy blocks, entities with raw definition/inventory/extenders) | PMC:211; `Resources/GohFullUnitTemplateCache` |
| `GohConquestMapCatalog` | Pools[], Maps[] | via status settings |
| `GohStatusExportSettings` | StatusTemplate (TextAsset), MapCatalog, SaveNamePrefix, GameVersion, Duration, Resources, FogOfWar, ManualControlMode, Region, WonGames, MP/SP/AP/RP, map-point names, fallback landscape/texmod/mode/size | PMC:205 |
| `GohSaveExportSettings` | TargetProfileDirectory, SaveFileName, TempOutputDirectory, OverwriteExistingSave, AlsoKeepLocalCopy, LocalCopyFileName | PMC:208 |
| `BattalionTypeIconSet`, `BattalionStrengthIconSet`, `ProvinceSpecializationIconSet` | sprites | PMC:198-201, :246 |
| `CampaignAiSettings` | 4 fields, **unused by code** | PMC:268 |
| `GohResearchProgressAsset`, `GohUnitCatalogImportSettings`, `GohConquestMapImportSettings` | editor-time; no runtime reader | - |

Non-ScriptableObject serialized data on the scene `ProvinceMapController`: `provinceIdTexture` (Texture2D), `provinceDatabaseJson` (TextAsset = the whole province graph), `campaignStateJson` (TextAsset fallback), visible map sprite, marker prefabs, UI panel refs, `turnStepDelaySeconds`. Unit portraits are loaded with `Resources.Load` from `GohPortraits/<name>` (`GohPortraitResolver.cs:25-34`). The Netcode `NetworkManager` + `UnityTransport` prefab config is also scene data.

## 5. Open questions / things the code alone cannot answer

1. Actual contents of every asset in section 4: province count, IDs, colours, neighbors, yields and specializations; faction definitions and which are `HumanSelectable`/`AIEnabled`; real turn order; diplomacy matrix; scripted events; starting battalions; cost tables. Code defaults may be overridden.
2. `provinceIdTexture` resolution/format and whether it is saved readable; whether borders are drawn into the visible map sprite.
3. The `StatusTemplate` TextAsset text (placeholders and fixed fields); it defines what the tactical game actually receives.
4. Contents and format assumptions of `GohFullUnitTemplateCache`: which game version it was baked from, and whether it can be regenerated for WF without the missing editor importer. If not, `GohFullUnitTemplateImporter.EnrichCatalogs` must be wired in and pointed at WF mod paks (it currently reads only base-game paks and only `set/multiplayer/units/conquest` + `set/breed/mp`).
5. Whether WF defines conquest unit files under the same folders and `inf_`/`units_` naming, and which faction tags and breed folder layout it uses (the regex parser assumes `mp/<tag>/<period>/<alias>`).
6. Whether WF conquest maps exist in a `map_points.set` equivalent and what pool/region names it uses; GOE's pool enum is WWII-DLC specific.
7. What mod `3717998771` contains (Lua bridge writing `last_battle_result.txt`, research keys `reinforcement_stage_*`, `defense_level_*`) and whether WF is compatible with or replaces those scripts.
8. Unity version, Netcode for GameObjects version, `persistentDataPath` company/product names (determine the real save folder), and scene list (only names `StartMenu` and `SampleScene` appear).
9. Which UI buttons are wired in scenes (e.g. whether "declare war", "resupply all", research, building panel and auto-resolve are all exposed), since button hookups are scene data for many handlers.
10. Runtime behaviour of everything: snapshot size limits for large campaigns over Netcode reliable RPC (12000-char chunks), JsonUtility handling of `Color32`/nested lists in saves, coroutine turn loop edge cases, and the 64-iteration safety cap in the AI turn loop (PMC:7424).
11. Intended meaning of `PlayedGames = TurnNumber - 5` and of static `MP/SP/AP/RP` values in the status export.
12. Whether more than one human faction per campaign was ever tested: UI always creates one human slot; extra slots only appear when clients claim factions.
