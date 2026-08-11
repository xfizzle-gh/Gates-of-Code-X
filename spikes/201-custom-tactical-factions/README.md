# #201 disposable custom tactical faction spike

Isolated prototype proving whether Gates-owned engine side IDs (`goc_usa`, `goc_fra`, …) can load in Code:X Dynamic Conquest **without** modifying Vanilla/West81/Code:X/AI Overhaul in place.

## Scope

- Feasibility spike only (issue #201).
- Does **not** change Phase 1 Expanded Nations production path (`nato|ukr|rusa|prc`).
- Tiny source-backed test pools; reuses existing `mp/nato/2022s/*` breeds via explicit content paths.
- Deploy only to the final Gates Workshop layer (or another disposable overlay).

## Prototype IDs

| Army ID | Token | Role |
|--------:|-------|------|
| 100 | `goc_usa` | Test A player |
| 101 | `goc_fra` | Test A enemy |

## Files

Under `resource/`:

- `set/multiplayer/armies/goc_{usa,fra}.set`
- `set/dynamic_campaign/unit_research_goc_{usa,fra}.set`
- `set/dynamic_campaign/values.set` (Code:X copy + matchup rows)
- `set/multiplayer/units/roster_conquest.set` (Core includes + spike unit files)
- `set/multiplayer/units/conquest/units_goc_{usa,fra}.set`
- `script/multiplayer/units/goc_{usa,fra}/conquest.goc_*.lua`
- `interface/pages/multi/flag_goc_{usa,fra}.tga` (copied from nato for load)
- localization stub pot

## Deploy / restore

```powershell
.\spikes\201-custom-tactical-factions\deploy.ps1 -GatesRoot $env:GATES_CODEX_ROOT
# after native tests:
.\spikes\201-custom-tactical-factions\deploy.ps1 -GatesRoot $env:GATES_CODEX_ROOT -Restore
```

## Native Test A (owner)

1. Ensure Core Expanded Nations (no actor projection).
2. Deploy spike.
3. Launch GoH with the live stack.
4. Start Dynamic Conquest as **GOC USA (spike)** vs **GOC France (spike)** if offered, or create a save with `{army goc_usa}` / `{enemyArmy goc_fra}`.
5. Confirm: menu load, roster isolation, positive costs, spawn, optional AI purchase, battle complete/save rewrite.
6. Capture full `game.log`, then `-Restore`.

## Known partial risks

AI Overhaul `nationMap` / `player_nation` do not list `goc_*`. Support-wave MI may degrade for unknown sides even if roster/research/army registration succeed. Record that boundary honestly.