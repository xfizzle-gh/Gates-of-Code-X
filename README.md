# Gates of Warfighter (GoW)

A strategic campaign layer for the WarFighter GoH mod of Call to Arms: Gates of Hell.
You move battalions on a province map in a companion application; battles are fought in the game with
WarFighter's units, maps and tactical AI; results come back to the campaign.

**Credits.** GoW is an adaptation of *Gates of Europa*, used with its author's permission. The campaign
application is rebuilt from the Gates of Europa build; its design and most of its code are that
author's work. Unit, faction, research, portrait and map data come from the WarFighter GoH mod by the
WarFighter team. Keep these credits with any release.

Status and history: `docs/milestone-log.md`. This is a working prototype, not a release.

## Two halves

| Half | Where | What it is |
| --- | --- | --- |
| In-game mod | `mod.info`, `resource/` | Loaded by the game after WarFighter (order: vanilla, WarFighter, GoW). One Lua bridge that makes the AI field the strategic enemy battalion. |
| Campaign application | `campaign/` (generated, not in git) → `build/campaign-win64/` | The Unity app: map, turns, economy, research, battle export and result import. |

Everything else here is tooling, data and documentation. The game ignores it.

## Build from scratch

Needs: Python 3.11 with Pillow, .NET SDK, Unity **6000.4.0f1**, the game, WarFighter GoH and Gates of
Europa installed (paths in `tools/paths.json`).

```
python tools/baseline.py all                      # manifests, GOE extraction, archive indexes
build\tools\AssetRipper\AssetRipper.GUI.Free.exe  # export upstream/goe-portable/current to recovered/unity (see milestone log)
tools\recover_campaign.ps1 -Force                 # campaign/ from the export + repairs + WarFighter content + scenario
tools\build_campaign.ps1                          # build/campaign-win64/WarfighterCampaign.exe
python tools/build_gow_mod.py                     # regenerate the in-game conquest.lua hook from installed WarFighter
```

Re-run `build_gow_mod.py` and `recover_campaign.ps1` after every WarFighter update.

## Play

1. In the game's mod menu enable WarFighter GoH, then Gates of Warfighter below it.
2. Run `build\campaign-win64\WarfighterCampaign.exe`, start a campaign, and set the game and profile
   directories. The real profile is under `%LOCALAPPDATA%\digitalmindsoft\gates of hell\profiles\<id>`.
3. Attack with a battalion. The app writes a Conquest save into the profile's `campaign` folder and
   the enemy battalion for the in-game bridge.
4. Load that save from Conquest in the game and fight the battle.
5. Back in the app, resolve the battle. It reads the result and your surviving units from the save.

## Data you can edit

| File | Controls |
| --- | --- |
| `data/scenario_2032.json` (written by `tools/author_scenario_2032.py`) | who owns which province, recruiting provinces, home-base income |
| `data/theaters.json` | faction names and theater matchups |
| `data/maps_pending.json` | maps to add automatically once they exist in WarFighter |
| `data/export_settings.json` | game version, region, required mods written into battle saves |

## Tests

```
python tests/lua/test_gow_bridge.py                                        # bridge logic in a real Lua runtime
tools\run_autoplay.ps1 -Script tests\autoplay\attack_round_trip.txt -Faction 0 -SimulateResult win
python tools/validate_scn.py <save.sav>                                    # structure of an exported battle save
```

The autoplay run needs no mouse or keyboard and only touches a scratch profile. Its "result" is a
script standing in for the game; see the milestone log for what has and has not been played for real.
