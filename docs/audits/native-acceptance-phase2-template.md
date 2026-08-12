# Phase 2 native acceptance template (#194)

Status: **harness only** — owner performs live GoH runs; independent auditor reviews evidence.

## Exact-head gate

- Implementation head: `<sha>`
- Static matrix signature: `<matrix_signature>`
- PR #195 must remain draft until final independent audit of this head + native evidence.

## Architecture

- Distinct Gates-owned tactical faction IDs for production GOC armies.
- Core `nato` / `ukr` / `rusa` / `prc` preserved.
- Do not mix four-side-only overlay architecture with production goc_* IDs.

## Representative families (minimum)

### phase1_full_national_nato
- Representative actor: `usa`
- Tactical side: `nato`
- Roster class: `full_national`
- Notes: Phase 1 USA full national; Core transport nato
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_national_hybrid_nato
- Representative actor: `fra`
- Tactical side: `nato`
- Roster class: `national_hybrid`
- Notes: France ARF/DSK hybrid boundary
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_spain_3rd_assault
- Representative actor: `esp`
- Tactical side: `nato`
- Roster class: `coalition_fallback`
- Notes: Spain seven-unit 3rd Assault allocation
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_ukraine_core
- Representative actor: `ukr`
- Tactical side: `ukr`
- Roster class: `full_national`
- Notes: Ukraine without duplicate ILDU wrappers
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_russia_core
- Representative actor: `rus`
- Tactical side: `rusa`
- Roster class: `full_national`
- Notes: Russia with KPA/Wagner hosted separation
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_proxy_dprk
- Representative actor: `dprk`
- Tactical side: `rusa`
- Roster class: `proxy_hybrid`
- Notes: DPRK isolation on rusa transport
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_proxy_serbia
- Representative actor: `srb`
- Tactical side: `rusa`
- Roster class: `proxy_hybrid`
- Notes: Serbia isolation
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase1_prc_passthrough
- Representative actor: `prc`
- Tactical side: `prc`
- Roster class: `full_national`
- Notes: PRC modern vs legacy/reserve; codex_passthrough activation
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase2_goc_nato_full_fallback
- Representative actor: `bel`
- Tactical side: `goc_bel`
- Roster class: `coalition_fallback`
- Notes: Production goc_* coalition_fallback family (#191/#192)
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase2_goc_national_hybrid_dana
- Representative actor: `cze`
- Tactical side: `goc_cze`
- Roster class: `national_hybrid`
- Notes: DANA equipment identity + infantry bridge
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

### phase2_strategic_only
- Representative actor: `egy`
- Tactical side: `goc_egy`
- Roster class: `strategic_only`
- Notes: Strategic-only ownership; no fabricated recruitment
- [ ] install/activate via supported Gates path
- [ ] brand-new Conquest/tactical test launches
- [ ] roster + research open without crash
- [ ] purchase infantry/support/vehicle/artillery where present
- [ ] positive personnel/unit costs
- [ ] battle start; representative units spawn
- [ ] opposing AI purchases only from intended actor/profile
- [ ] save/load succeeds
- [ ] battle completion rewrites cleanly
- [ ] game.log has no new materialization/faction errors
- Evidence paths: logs=… screenshots=… saves=…

## Required battle pairs

### usa_vs_fra_shared_nato_transport
- Attacker: `usa`
- Defender: `fra`
- Purpose: Same historical NATO transport family without generic NATO leakage
- [ ] both-side AI purchase isolation proven
- [ ] no generic transport-side leakage
- Evidence paths: …

### srb_vs_rus_shared_rusa_transport
- Attacker: `srb`
- Defender: `rus`
- Purpose: Same historical RUSA transport family isolation
- [ ] both-side AI purchase isolation proven
- [ ] no generic transport-side leakage
- Evidence paths: …

### usa_vs_dprk_cross_coalition
- Attacker: `usa`
- Defender: `dprk`
- Purpose: Cross-coalition pair
- [ ] both-side AI purchase isolation proven
- [ ] no generic transport-side leakage
- Evidence paths: …

### regional_garrison_48
- Attacker: `usa`
- Defender: `issue_48_regional_local_garrison`
- Purpose: Regional/local garrison profile from #48 without sovereign recruitment transfer
- [ ] both-side AI purchase isolation proven
- [ ] no generic transport-side leakage
- Evidence paths: …

## Strategic-only checks

- [ ] strategic-only actors appear in ownership/diplomacy where applicable
- [ ] survive save/load
- [ ] cannot install/purchase fabricated national roster
- [ ] #48 regional garrison battles do not transfer units into sovereign recruitment

## Core restoration

```text
python -m gates_of_codex.expanded_nations_cli core --gates-root <GATES_ROOT>
# or: .\tools\activate_expanded_nation.ps1 -Core
```

- [ ] Core mode restored
- [ ] `nato` / `ukr` / `rusa` / `prc` retain original Code:X roster/research/AI behavior
- [ ] no stale Gates Expanded Nations runtime projections remain

## Final independent audit

- Reviewer must not rely only on implementer summary
- Verdict: approve | approve with non-blocking notes | request changes
