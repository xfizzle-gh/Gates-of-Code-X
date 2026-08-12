# Expanded Nations static matrix (#194 pre-native)

- schema: `gates-of-codex.expanded-nations-static-matrix` v2
- evidence_state: `static_pre_native`
- source_head: `5d1fe4d7d785134bcd6587f7f909a377865bb454`
- matrix_signature: `61427243f671c1da60bb1a2ba0329f1190ea45e571ee1efcdc74e6d8ddf7728d`
- architecture: `{"core_sides_preserved": ["nato", "ukr", "rusa", "prc"], "expanded_mode_uses_gates_ids": true, "issue_201_status": "partial_owner_approved_for_production_goc_ids", "mixed_architecture_forbidden": true, "owner_disposition": "distinct_gates_owned_tactical_faction_ids", "phase1_source_families_frozen": true}`
- counts: `{"actor_count": 61, "hosted_actor_count": 3, "phase1_actor_count": 24, "playable_actor_count": 33, "registered_goc_side_count": 57, "strategic_only_actor_count": 25}`

## Native harness

### Representative families

| family_id | actor | expanded_side | source_family | checklist | notes |
|---|---|---|---|---|---|
| phase1_full_national_west | usa | `goc_usa` | `nato` | playable | Phase 1 USA full national on Gates ID; source family nato |
| phase1_national_hybrid_west | fra | `goc_fra` | `nato` | playable | France ARF/DSK hybrid on Gates ID for same-family USA-vs-France proof |
| phase1_spain_3rd_assault | esp | `goc_esp` | `nato` | playable | Spain seven-unit 3rd Assault allocation |
| phase1_ukraine_core | ukr | `goc_ukr` | `ukr` | playable | Ukraine without duplicate ILDU wrappers |
| phase1_russia_core | rus | `goc_rus` | `rusa` | playable | Russia with KPA/Wagner hosted separation |
| phase1_proxy_dprk | dprk | `goc_dprk` | `rusa` | playable | DPRK isolation on Gates ID; source family rusa |
| phase1_proxy_serbia | srb | `goc_srb` | `rusa` | playable | Serbia isolation for srb-vs-rus same-family proof |
| phase1_prc_passthrough | prc | `prc` | `prc` | playable | PRC Code:X passthrough retains native prc side |
| phase2_goc_nato_full_fallback | bel | `goc_bel` | `nato` | playable | Production goc_* coalition_fallback family |
| phase2_goc_national_hybrid_dana | cze | `goc_cze` | `nato` | playable | DANA equipment identity + infantry bridge |
| phase2_strategic_only | egy | `goc_egy` | `nato` | strategic_only | Strategic-only ownership; fabricated national recruitment must remain impossible |

### Required battle pairs

| pair_id | attacker | attacker_side | defender | defender_side | purpose |
|---|---|---|---|---|---|
| usa_vs_fra_gates_ids_shared_nato_source_family | usa | `goc_usa` | fra | `goc_fra` | Same source family without generic Core nato side leakage |
| srb_vs_rus_gates_ids_shared_rusa_source_family | srb | `goc_srb` | rus | `goc_rus` | Same source family without generic Core rusa side leakage |
| usa_vs_dprk_cross_coalition | usa | `goc_usa` | dprk | `goc_dprk` | Cross-coalition pair on distinct Gates IDs |
| regional_garrison_48 | usa | `goc_usa` | issue_48_regional_local_garrison | `issue_48_regional_local_garrison` | Regional/local garrison without sovereign recruitment transfer |

### Checklists

Playable:

- install_or_activate_via_supported_gates_path
- launch_brand_new_conquest_or_tactical_test
- roster_and_research_open_without_crash
- purchase_representative_infantry_support_vehicle_artillery_where_present
- prove_positive_personnel_and_unit_costs
- start_battle_and_prove_representative_units_spawn
- prove_opposing_ai_purchases_only_from_intended_actor_profile
- save_load_succeeds
- battle_completion_rewrites_cleanly
- game_log_has_no_new_materialization_or_faction_errors

Strategic-only:

- actor_appears_in_strategic_ownership_or_diplomacy_where_applicable
- actor_survives_save_load
- actor_cannot_be_selected_as_independent_playable
- actor_cannot_install_or_purchase_fabricated_national_roster
- local_neutral_battles_may_use_issue_48_garrisons_without_recruitment_transfer
- no_research_nodes_or_ai_purchase_authority

## Actors

| actor_id | playable | roster | expanded_side | source_family | units | research | modern | legacy | opponents | AI | native |
|---|---|---|---|---|---:|---:|---:|---:|---:|---|---|
| alb | False | strategic_only | `goc_alb` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| arm | False | strategic_only | `goc_arm` | `rusa` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| aut | False | strategic_only | `goc_aut` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| aze | False | strategic_only | `goc_aze` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| bel | True | coalition_fallback | `goc_bel` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| bgr | True | coalition_fallback | `goc_bgr` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| bih | False | strategic_only | `goc_bih` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| blr | True | proxy_hybrid | `goc_blr` | `rusa` | 30 | 42 | 15 | 15 | 32 | actor_scoped_ai_economy | not_run |
| can | True | national_hybrid | `goc_can` | `nato` | 21 | 30 | 21 | 0 | 32 | actor_scoped_ai_economy | not_run |
| che | False | strategic_only | `goc_che` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| cyp | False | strategic_only | `goc_cyp` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| cze | True | national_hybrid | `goc_cze` | `nato` | 8 | 14 | 8 | 0 | 32 | actor_scoped_ai_economy | not_run |
| deu | True | full_national | `goc_deu` | `nato` | 29 | 42 | 29 | 0 | 32 | actor_scoped_ai_economy | not_run |
| dnk | True | coalition_fallback | `goc_dnk` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| donbas | True | proxy_hybrid | `goc_donbas` | `rusa` | 45 | 62 | 30 | 15 | 32 | actor_scoped_ai_economy | not_run |
| dprk | True | proxy_hybrid | `goc_dprk` | `rusa` | 20 | 29 | 5 | 15 | 32 | actor_scoped_ai_economy | not_run |
| dza | False | strategic_only | `goc_dza` | `rusa` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| egy | False | strategic_only | `goc_egy` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| esp | True | coalition_fallback | `goc_esp` | `nato` | 50 | 63 | 50 | 0 | 32 | actor_scoped_ai_economy | not_run |
| est | True | coalition_fallback | `goc_est` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| fin | True | national_hybrid | `goc_fin` | `nato` | 22 | 32 | 22 | 0 | 32 | actor_scoped_ai_economy | not_run |
| fra | True | national_hybrid | `goc_fra` | `nato` | 28 | 36 | 28 | 0 | 32 | actor_scoped_ai_economy | not_run |
| gbr | True | full_national | `goc_gbr` | `nato` | 33 | 44 | 33 | 0 | 32 | actor_scoped_ai_economy | not_run |
| geo | False | strategic_only | `goc_geo` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| grc | True | coalition_fallback | `goc_grc` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| hrv | True | coalition_fallback | `goc_hrv` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| hun | True | coalition_fallback | `goc_hun` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| irl | False | strategic_only | `goc_irl` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| irq | False | strategic_only | `goc_irq` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| isl | False | strategic_only | `goc_isl` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| isr | False | strategic_only | `goc_isr` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| ita | True | national_hybrid | `goc_ita` | `nato` | 26 | 36 | 26 | 0 | 32 | actor_scoped_ai_economy | not_run |
| jor | False | strategic_only | `goc_jor` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| kpa_expeditionary | False | nonstate | `goc_rus` | `rusa` | 5 | 8 | 5 | 0 | 0 | none | not_run |
| lbn | False | strategic_only | `goc_lbn` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| lby | False | strategic_only | `goc_lby` | `rusa` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| ltu | True | coalition_fallback | `goc_ltu` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| lva | True | coalition_fallback | `goc_lva` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| mar | False | strategic_only | `goc_mar` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| mda | False | strategic_only | `goc_mda` | `rusa` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| mkd | False | strategic_only | `goc_mkd` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| mlt | False | strategic_only | `goc_mlt` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| mne | False | strategic_only | `goc_mne` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| nld | True | national_hybrid | `goc_nld` | `nato` | 22 | 32 | 22 | 0 | 32 | actor_scoped_ai_economy | not_run |
| nor | True | coalition_fallback | `goc_nor` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| pol | True | national_hybrid | `goc_pol` | `nato` | 25 | 35 | 25 | 0 | 32 | actor_scoped_ai_economy | not_run |
| prc | True | full_national | `prc` | `prc` | 80 | 100 | 66 | 14 | 32 | actor_scoped_ai_economy | not_run |
| prt | True | coalition_fallback | `goc_prt` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| rou | True | coalition_fallback | `goc_rou` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| rus | True | full_national | `goc_rus` | `rusa` | 210 | 247 | 210 | 0 | 32 | actor_scoped_ai_economy | not_run |
| srb | True | proxy_hybrid | `goc_srb` | `rusa` | 18 | 28 | 3 | 15 | 32 | actor_scoped_ai_economy | not_run |
| svk | True | national_hybrid | `goc_svk` | `nato` | 8 | 14 | 8 | 0 | 32 | actor_scoped_ai_economy | not_run |
| svn | False | strategic_only | `goc_svn` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| swe | True | national_hybrid | `goc_swe` | `nato` | 24 | 35 | 24 | 0 | 32 | actor_scoped_ai_economy | not_run |
| syr | False | strategic_only | `goc_syr` | `rusa` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| tun | False | strategic_only | `goc_tun` | `nato` | 0 | 0 | 0 | 0 | 0 | none | not_run |
| tur | True | coalition_fallback | `goc_tur` | `nato` | 55 | 64 | 55 | 0 | 32 | actor_scoped_ai_economy | not_run |
| ukr | True | full_national | `goc_ukr` | `ukr` | 179 | 215 | 179 | 0 | 32 | actor_scoped_ai_economy | not_run |
| ukr_ildu | False | nonstate | `goc_ukr` | `ukr` | 6 | 13 | 6 | 0 | 0 | none | not_run |
| usa | True | full_national | `goc_usa` | `nato` | 74 | 93 | 74 | 0 | 32 | actor_scoped_ai_economy | not_run |
| wagner | False | nonstate | `goc_rus` | `rusa` | 15 | 17 | 15 | 0 | 0 | none | not_run |
