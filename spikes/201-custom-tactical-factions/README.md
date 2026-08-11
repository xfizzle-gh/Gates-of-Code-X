# #201 Custom Tactical Faction Spike

**Owner status (2026-08-11):** custom DC factions **`goc_usa` / `goc_fra` work** on the live stack.

- Recipe: [`docs/audits/201-native-create-menu-pass.md`](../../docs/audits/201-native-create-menu-pass.md)  
- Review brief: [`docs/audits/201-chatgpt-review-brief.md`](../../docs/audits/201-chatgpt-review-brief.md)

## Working model

Additive on final Gates layer. Core `nato/ukr/rusa/prc` retained.

| Surface | Working |
|---------|---------|
| Army ids | 90 / 91 |
| Alliances | West: nato, ukr, goc_usa · East: rusa, prc, goc_fra |
| values | Code:X + goc matchups |
| units/conquest | Parent files on final layer + goc |
| roster | Existing includes only + goc |
| research | `unit_research_goc_*` (owner-tuned live) |
| purchase | `Repeat` / `Units` / `priority` / `unit` |
| conquest.lua | AIO + nationMap + coalitions |
| CTF | → `alliances_generic.inc` |

## Stack

`West81 → Code:X → AI Overhaul → Gates last` (`3696721120`)

## Git vs live

Spike snapshots Gates-owned registration/`goc_*` files from the working workshop tree. Parent unit bodies may exist only on the live final layer as deploy-time copies.
