# #201 Custom Tactical Faction Spike

**Status:** Test A owner-confirmed working; Tests B/C fixtures ready for native owner runs.  
**PR:** #208 (draft) · **Issue:** #201 (open, PARTIAL until B/C native evidence)

- Recipe: [`docs/audits/201-native-create-menu-pass.md`](../../docs/audits/201-native-create-menu-pass.md)
- Review brief: [`docs/audits/201-chatgpt-review-brief.md`](../../docs/audits/201-chatgpt-review-brief.md)
- Native handoff: [`docs/audits/201-native-test-handoff.md`](../../docs/audits/201-native-test-handoff.md)

## Working model

Additive on final Gates layer. Core `nato/ukr/rusa/prc` retained.

| Surface | Working |
|---------|---------|
| Army ids | 90–94 (`usa/fra/srb/rus/dprk`) |
| Alliances | West: nato, ukr, goc_usa · East: rusa, prc, goc_fra, goc_srb, goc_rus, goc_dprk |
| values | Code:X regions + Test A/B/C matchups |
| units/conquest | Parent files materialized at deploy + goc |
| roster | Existing includes only + goc |
| research | Tiny isolated `unit_research_goc_*` (GOC test units only) |
| purchase | `Repeat` / `Units` / `priority` / `unit` |
| conquest.lua | AIO + nationMap + coalitions |
| CTF | → `alliances_generic.inc` |

## Prototypes

| ID | Test | Army ID | Content family |
|----|------|---------|----------------|
| `goc_usa` | A, C | 90 | USMC breeds + m1126 |
| `goc_fra` | A | 91 | NATO breeds + amx10rc |
| `goc_srb` | B | 92 | Serb_* breeds + bmp-1_rus |
| `goc_rus` | B | 93 | rus_* breeds + btr-82a |
| `goc_dprk` | C | 94 | kor_* (KPA) breeds + bmp-1_rus |

## Stack

`West81 → Code:X → AI Overhaul → Gates last` (`3696721120`)

## Deploy

```powershell
.\deploy.ps1 -GatesRoot "<Gates workshop path>" -WorkshopRoot "<workshop/content/400750>"
.\deploy.ps1 -GatesRoot "<Gates workshop path>" -Restore
```

Standalone last-mod path (idempotent; validates, does not rewrite `conquest.lua`):

```powershell
.\deploy_standalone.ps1 -GameRoot "<GoH game root>"
```

## Static validation

```powershell
python -m unittest tests.test_201_custom_tactical_factions_spike -v
```

Static green ≠ native PASS.
