# GOE battle round trip (from decompiled source)

Source: `recovered/csharp` (ILSpy 9.1.0.7988 on `Assembly-CSharp.dll`, SHA256 `B5A9AF86…109F1`).
Nothing here has been run. Line numbers refer to the decompiled files.

## Call graph

```
ProvinceMapController  (pending battle creation, ~L2080-2212)
 ├─ SavePendingBattle(PendingBattleRecord)            -> Runtime/pending_battle.json
 └─ export (TryRegeneratePendingBattleSav, L1638-1737; same sequence at L2100-2181)
     ├─ ClearOldBridgeResultFile()
     ├─ GoeBattleBridgeContextWriter.Write()          -> Documents/My Games/gates of hell/GatesOfEuropa/goe_battle_context.lua
     ├─ CampaignScnExporter.SaveCampaignScn()         -> Runtime/campaign.scn      (PLAYER side only)
     ├─ StatusExporter.ExportRandomStatus()           -> Runtime/status            (template + map pick + army codes)
     │    └─ GohModDependencyUtility.EnsureRequiredModInStatusText()  ("mod_3717998771:0")
     └─ GohBattleSaveExporter.ExportSav()             -> Runtime/campaign.sav, copied to <profile>/campaign/<name>.sav

  (player loads the save in GoH and plays a native Conquest battle)

ProvinceMapController.ResolvePendingBattleFromBridgeFile()  (L2214)
 ├─ GohBridgeResultReader.Read(last_battle_result.txt)   finished? battleId == pending.BattleId?
 ├─ TryResolvePendingBattleFromSavStatus()  (L2271)
 │    └─ GohBattleResultReader.ReadStatusFromSav()       {playedGames N} / {wonGames N} from `status` in the .sav
 │         finished  = playedGames > ExportedPlayedGames
 │         playerWon = wonGames    > ExportedWonGames
 ├─ ResolvePendingBattleAsAttackerWin / AsDefenderHold(applyPostBattleCampaignScn: true)
 └─ post-battle import (L2545-2578)
      ├─ TryReadPostBattleCampaignScn()   .sav entry -> expected .sav path -> loose Runtime/campaign.scn fallback (L2609, may be pre-battle)
      └─ GohCampaignScnSquadImporter.ApplyToBattalion / ApplyToBattleParticipants
```

## Findings that change the plan

1. **The `.sav` is a plain ZIP with exactly two entries, `campaign.scn` and `status`.**
   (`GohBattleSaveExporter.ExportSav`.) It is a native Conquest save, not a custom mission.

2. **Only the player's force is serialized.** `campaign.scn` carries the player's battalion(s) as
   `CampaignSquads` rows plus `Human`/`Entity`/`Inventory` object blocks. The opponent is identified only by
   `%ENEMY_ARMY%` in `status`; the native Conquest AI buys its own units. Consequences for WF:
   - WF's tactical AI and purchase lists run unmodified, which is what the plan wants.
   - The strategic enemy battalion's composition does not reach the battlefield, and enemy casualties are
     not read back. Plan stages D ("ownership of both forces") and F (AI survivor capture) describe
     capabilities GOE never had; they are new work, not porting.

3. **GOE does not trust the Lua bridge for the winner.** The bridge file is used as a "finished + battleId
   matches" signal. The winner comes from the `wonGames` counter delta in the post-battle `.sav` `status`
   entry. If counters were exported and cannot be read, resolution is cancelled with the message
   "Not using bridge playerWon because it can be wrong after retreats" (L2250). The Lua `playerWon` is
   only a legacy fallback for pendings without counters.
   - Plan stage E's `WinnerDecided` hook is still worth having as a second, cross-checked signal, but the
     save-counter mechanism needs no WF Lua change at all and should be the first thing verified live.

4. **Post-battle roster import reads the same `.sav` path that was exported**, relying on GoH overwriting
   it in place. The loose-file fallback at L2609 can silently restore the pre-battle roster. Replace with a
   hard failure (plan stage F already says this).

5. **Hard-coded identities to replace:** `mod_3717998771:0` (`GohModDependencyUtility`), save prefix
   `GatesOfEuropa_`, exchange directory `…/gates of hell/GatesOfEuropa`, default army codes `ger`/`rus`
   (`StatusExporter.BuildStatusText`), `FactionType` enum of 16 WWII nations, and four fixed catalogs
   (`germany`/`ussr`/`finland`/`commonwealth`) in `GetPostBattleImportCatalogs` (L2619).

6. **`options.set` is edited by text insertion** into the `{mods` block (`EnsureOptionsSetModEnabled`).
   It preserves other content but takes no backup.

7. **Profile selection is "most recently written profile directory"** (`GohProfilePathUtility`,
   `FindLatestProfileDirectory`). Plan requires explicit selection.

8. **`BattleManifest` / `BattleResult` (ForceBuckets, WinnerFaction, losses) are unused leftovers** of an
   earlier design; `BattleResult` even derives from `MonoBehaviour`. Do not treat them as the protocol.

## Not recoverable from code

`GohStatusExportSettings.StatusTemplate` (the `status` text template with `%ARMY%`, `%MAP_STRING%`, … tokens),
`MapCatalog`, selected-map-point strings, MP/SP/AP/RP values, province database, adjacency, world rules and
unit catalogs are Unity serialized assets inside `resources.assets` / `sharedassets*.assets` / `level*`.
They need AssetRipper (or UnityPy) extraction.
