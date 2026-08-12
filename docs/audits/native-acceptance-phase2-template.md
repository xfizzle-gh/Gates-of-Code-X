# Phase 2 native acceptance template (#194)

Status: **harness only** — owner performs live GoH runs; independent auditor reviews evidence.

## Architecture

- Expanded-mode production uses distinct Gates-owned `goc_*` tactical IDs.
- Phase 1 source/core transport families (`nato`/`ukr`/`rusa`/`prc`) remain the frozen roster boundary labels.
- Core Code:X sides remain available via Core restore; do not mix architectures.

## Playable family checklist

- [ ] install_or_activate_via_supported_gates_path
- [ ] launch_brand_new_conquest_or_tactical_test
- [ ] roster_and_research_open_without_crash
- [ ] purchase_representative_infantry_support_vehicle_artillery_where_present
- [ ] prove_positive_personnel_and_unit_costs
- [ ] start_battle_and_prove_representative_units_spawn
- [ ] prove_opposing_ai_purchases_only_from_intended_actor_profile
- [ ] save_load_succeeds
- [ ] battle_completion_rewrites_cleanly
- [ ] game_log_has_no_new_materialization_or_faction_errors

## Strategic-only checklist

- [ ] actor_appears_in_strategic_ownership_or_diplomacy_where_applicable
- [ ] actor_survives_save_load
- [ ] actor_cannot_be_selected_as_independent_playable
- [ ] actor_cannot_install_or_purchase_fabricated_national_roster
- [ ] local_neutral_battles_may_use_issue_48_garrisons_without_recruitment_transfer
- [ ] no_research_nodes_or_ai_purchase_authority

## Representative families

### phase1_full_national_west (`playable`)
- Actor: `usa`
- Expanded tactical side: `goc_usa`
- Source family: `nato`
- Notes: Phase 1 USA full national on Gates ID; source family nato
- Evidence paths: logs=… screenshots=… saves=…

### phase1_national_hybrid_west (`playable`)
- Actor: `fra`
- Expanded tactical side: `goc_fra`
- Source family: `nato`
- Notes: France ARF/DSK hybrid on Gates ID for same-family USA-vs-France proof
- Evidence paths: logs=… screenshots=… saves=…

### phase1_spain_ildu_nato_fallback (`playable`)
- Actor: `esp`
- Expanded tactical side: `goc_esp`
- Source family: `nato`
- Notes: Spain ILDU NATO-personnel wrappers from Ukraine authority plus approved NATO heavy/support fallback; Azov/3rd Assault forbidden
- Evidence paths: logs=… screenshots=… saves=…

### phase1_ukraine_core (`playable`)
- Actor: `ukr`
- Expanded tactical side: `goc_ukr`
- Source family: `ukr`
- Notes: Ukraine without duplicate ILDU wrappers
- Evidence paths: logs=… screenshots=… saves=…

### phase1_russia_core (`playable`)
- Actor: `rus`
- Expanded tactical side: `goc_rus`
- Source family: `rusa`
- Notes: Russia with KPA/Wagner hosted separation
- Evidence paths: logs=… screenshots=… saves=…

### phase1_proxy_dprk (`playable`)
- Actor: `dprk`
- Expanded tactical side: `goc_dprk`
- Source family: `rusa`
- Notes: DPRK isolation on Gates ID; source family rusa
- Evidence paths: logs=… screenshots=… saves=…

### phase1_proxy_serbia (`playable`)
- Actor: `srb`
- Expanded tactical side: `goc_srb`
- Source family: `rusa`
- Notes: Serbia isolation for srb-vs-rus same-family proof
- Evidence paths: logs=… screenshots=… saves=…

### phase1_prc_passthrough (`playable`)
- Actor: `prc`
- Expanded tactical side: `prc`
- Source family: `prc`
- Notes: PRC Code:X passthrough retains native prc side
- Evidence paths: logs=… screenshots=… saves=…

### phase2_goc_nato_full_fallback (`playable`)
- Actor: `bel`
- Expanded tactical side: `goc_bel`
- Source family: `nato`
- Notes: Production goc_* coalition_fallback family
- Evidence paths: logs=… screenshots=… saves=…

### phase2_goc_national_hybrid_dana (`playable`)
- Actor: `cze`
- Expanded tactical side: `goc_cze`
- Source family: `nato`
- Notes: DANA equipment identity + infantry bridge
- Evidence paths: logs=… screenshots=… saves=…

### phase2_strategic_only (`strategic_only`)
- Actor: `egy`
- Expanded tactical side: `goc_egy`
- Source family: `nato`
- Notes: Strategic-only ownership; fabricated national recruitment must remain impossible
- Evidence paths: logs=… screenshots=… saves=…

## Required battle pairs

### usa_vs_fra_gates_ids_shared_nato_source_family
- Attacker: `usa` / `goc_usa`
- Defender: `fra` / `goc_fra`
- Purpose: Same source family without generic Core nato side leakage
- Evidence paths: …

### srb_vs_rus_gates_ids_shared_rusa_source_family
- Attacker: `srb` / `goc_srb`
- Defender: `rus` / `goc_rus`
- Purpose: Same source family without generic Core rusa side leakage
- Evidence paths: …

### usa_vs_dprk_cross_coalition
- Attacker: `usa` / `goc_usa`
- Defender: `dprk` / `goc_dprk`
- Purpose: Cross-coalition pair on distinct Gates IDs
- Evidence paths: …

### regional_garrison_48
- Attacker: `usa` / `goc_usa`
- Defender: `issue_48_regional_local_garrison` / `issue_48_regional_local_garrison`
- Purpose: Regional/local garrison without sovereign recruitment transfer
- Evidence paths: …

## Core restoration

```text
python -m gates_of_codex.expanded_nations_cli core --gates-root <GATES_ROOT>
```

- [ ] Core restored; `nato`/`ukr`/`rusa`/`prc` retain original Code:X behavior
- [ ] no stale Gates Expanded Nations projections remain
