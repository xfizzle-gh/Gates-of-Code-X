# #201 Custom Tactical Faction Spike

**Native status (2026-08-11):** Create Conquest menu **PARTIAL PASS** for `goc_usa` / `goc_fra`.

Full recipe + failure log: [`docs/audits/201-native-create-menu-pass.md`](../../docs/audits/201-native-create-menu-pass.md)

## What worked

Additive custom factions on the **final Gates workshop layer** (`3696721120`), stack:

`West81 → Code:X → AI Overhaul → Gates (last)`

| Surface | Working choice |
|---------|----------------|
| Army ids | `goc_usa=90`, `goc_fra=91` |
| Alliances | West: nato, ukr, goc_usa · East: rusa, prc, goc_fra |
| values | Code:X regions + goc matchups |
| units/conquest | Parent files on final layer + goc inf/units |
| roster | Only existing includes + goc |
| research | `unit_research_goc_*.set` (owner-tuned on live) |
| purchase lua | `Repeat` / `Units` / `priority` / `unit` |
| conquest.lua | Full AIO copy + nationMap + west/east |
| CTF | includes `alliances_generic.inc` |

## Spike contents

Gates-owned registration and `goc_*` content snapshotted from the working live layer. Parent Code:X/AIO unit bodies are deploy-time copies on the live workshop tree, not all vendored here.

## Next

1. Test A battle path (create → fight → AI → save)  
2. Tests B/C  
3. Owner disposition on #201 before production Expanded Nations wiring  
