# #201 fix: GaW/MW-style replacement pack

## Why it failed before
Additive overlay on AI Overhaul kept `West: nato/ukr` and `East: rusa/prc`. DC army picker only shows armies in the **winning alliances include**. GaW/MW work because they **replace** alliances/values/roster.

## What we ship now
| File | Behavior |
|------|----------|
| `alliances_*.inc` | **Only** `goc_usa` / `goc_fra` |
| `values.set` | **Only** goc_usa vs goc_fra matchups |
| `roster_conquest.set` | settings + inf_goc_* + units_goc_* |
| `settings.set` | Code:X macros copy (needed for defines) |
| `inf_goc_*.set` / `units_goc_*.set` | test pools |
| `campaign_capture_the_flag.set` | includes `alliances_goc_201.inc` |
| `modes/conquest.lua` | AI Overhaul base + goc nationMap ids |
| armies id 90/91 | engine range 0-99 |

## How to test (do this)

1. **Gates workshop already has the pack** at `3696721120` (highest in your load order).
2. Optional extra: local mod `Call to Arms - Gates of Hell\mods\goc_201_faction_spike` — enable it if you want a second copy.
3. In mod manager keep: West81 + Code:X + AI Overhaul + **Gates of CodeX** (and/or the mini-mod on top).
4. Disable other conquest faction packs (GaW/MW/etc.) while testing.
5. Restart GoH fully.
6. Dynamic Conquest → you should only see **GOC USA spike** vs **GOC France spike** (BLUEFOR/OPFOR).

## Restore Gates workshop after test
```powershell
.\spikes\201-custom-tactical-factions\deploy.ps1 -GatesRoot "E:\Steam\steamapps\workshop\content\400750\3696721120" -Restore
```
