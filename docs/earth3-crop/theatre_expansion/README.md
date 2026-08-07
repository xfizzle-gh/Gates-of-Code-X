# Earth3 theatre expansion planning (preview only)

**Not production.** No crop promotion. Authority remains **3514**.

Designer scope reference: complete northern Russia/Karelia coherence + Turkey/Levant (Israel and surrounds). Rough political-map attachment is scope-only — not committed art.

## Current production (locked)

| Field | Value |
|---|---|
| provinces | 3514 |
| land / water | 3299 / 215 |
| hash | `f3931d2e34558e451d02a7c49270b2071a79a628668c49228f5ff607a75315b8` |
| max Gates ID | `e3_3515` |
| permanent gaps | `e3_2830`, `e3_2888` (never recycle) |

## Method (estimate)

Archive provinces **not** in production 3514, selected by:

- **North:** source-space band `x∈[9600,11050]`, `y≤900` (Kola/Karelia scraps west of Pechora/Fion)
- **Levant/Turkey/Caucasus/Sinai:** LOO piecewise georef centroid in WGS box `lon 25–49, lat 28–43.5`
- **Proposal B extras:** wider WGS boxes (Iraq/Iran, Arabia, Kazakhstan, deeper N. Africa)

This is a **centroid/band planning estimate**, not an authored polygon mask. Final mask must be owner-drawn.

## Proposal A — recommended minimum

| | |
|---|---:|
| Added land | **247** |
| Added water | **10** |
| Added total | **257** |
| New province count | **~3771** |
| New land / water | **~3546 / 225** |
| New Gates IDs | `e3_3516` … `e3_3772` (append only) |
| Land mesh chunks (CHUNK=256) | 13 → **14** |

North note: only **2** excluded land scraps in the west-of-Pechora band (`10969` Krasino, `11367` Tumanny). Most Karelia/Kola already sits in 3514; remaining “incomplete north” may be mask-edge polish rather than large missing blocks.

Levant/Turkey band drives almost all Proposal A adds (~245 land).

### ID / fixture impact

- Retain all **3514** existing `e3_*` mappings
- Append new IDs only; **never** reuse `e3_2830` / `e3_2888`
- Adjacency: rebuild mutual edges among expanded included set
- Fixtures/snapshots: regenerate province tables; gameplay refs stay valid for retained IDs
- Draw calls: modest (+1 land mesh chunk vs PR A ~3.7k baseline order)

## Proposal B — broader reference (not recommended without gameplay justification)

| | |
|---|---:|
| Added land | **1267** |
| Added water | **63** |
| Added total | **1330** |
| New province count | **~4844** |
| New land / water | **~4566 / 278** |
| New Gates IDs | `e3_3516` … `e3_4845` |
| Land mesh chunks | 13 → **18** |

Includes Proposal A plus Iraq/Iran core, Arabia, Kazakhstan, deeper North Africa. Large fixture and performance cost.

## Previews

| File | Content |
|---|---|
| `comparison_current_vs_proposal_a.png` | Current grey + A green |
| `comparison_current_vs_proposal_b.png` | + B amber extras |
| `closeup_karelia_kola_proposal_a.png` | North band |
| `closeup_turkey_levant_proposal_a.png` | Turkey/Levant |
| `planning_estimate.json` | Machine-readable counts |
| `proposal_*_added_*_ids.json` | Source ID lists |

## Stop condition

Owner/designer must approve an **exact theatre outline** (authored mask) before any production crop PR.
