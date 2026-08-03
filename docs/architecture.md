# Architecture notes

The campaign application maintains strategic state outside Gates of Hell and exchanges tactical battles with the game through Dynamic Conquest save files.

Gates of CodeX implements the observable file contract:

- `status` stores battle configuration, factions, resources, research, and battle counters.
- `campaign.scn` stores persistent Human and Entity objects, Inventory blocks, and CampaignSquads stage assignments.
- `campaign.sav` contains `status` and `campaign.scn`.
- A completed battle advances `playedGames`; a player victory advances `wonGames`.
- Surviving CampaignSquads are mapped back to strategic battalions by stage.

The project contains newly written source code and no third-party executable or game assets. Code:X remains the authority for tactical units, breeds, vehicles, doctrines, research, maps, AI purchasing, waves, and mission behavior.
