# Expanded Nations static matrix (#194 pre-native)

- schema: `gates-of-codex.expanded-nations-static-matrix` v1
- evidence_state: `static_pre_native`
- source_head: `a58c7145dfe119f91769b51a5d3b61e9961f5def`
- matrix_signature: `e677570464fe2c2174d0ba2daebaece30a619adb55b12c280ad34cbe2e0b6bcb`
- architecture: `{"core_sides_preserved": ["nato", "ukr", "rusa", "prc"], "issue_201_status": "partial_owner_approved_for_production_goc_ids", "mixed_architecture_forbidden": true, "owner_disposition": "distinct_gates_owned_tactical_faction_ids"}`
- counts: `{"actor_count": 61, "hosted_actor_count": 3, "phase1_actor_count": 24, "playable_actor_count": 33, "registered_goc_side_count": 37, "strategic_only_actor_count": 25}`

## Native harness (runs pending owner)

### Representative families

| family_id | representative | tactical_side | roster_class | notes |
|---|---|---|---|---|
| phase1_full_national_nato | usa | `nato` | full_national | Phase 1 USA full national; Core transport nato |
| phase1_national_hybrid_nato | fra | `nato` | national_hybrid | France ARF/DSK hybrid boundary |
| phase1_spain_3rd_assault | esp | `nato` | coalition_fallback | Spain seven-unit 3rd Assault allocation |
| phase1_ukraine_core | ukr | `ukr` | full_national | Ukraine without duplicate ILDU wrappers |
| phase1_russia_core | rus | `rusa` | full_national | Russia with KPA/Wagner hosted separation |
| phase1_proxy_dprk | dprk | `rusa` | proxy_hybrid | DPRK isolation on rusa transport |
| phase1_proxy_serbia | srb | `rusa` | proxy_hybrid | Serbia isolation |
| phase1_prc_passthrough | prc | `prc` | full_national | PRC modern vs legacy/reserve; codex_passthrough activation |
| phase2_goc_nato_full_fallback | bel | `goc_bel` | coalition_fallback | Production goc_* coalition_fallback family (#191/#192) |
| phase2_goc_national_hybrid_dana | cze | `goc_cze` | national_hybrid | DANA equipment identity + infantry bridge |
| phase2_strategic_only | egy | `goc_egy` | strategic_only | Strategic-only ownership; no fabricated recruitment |

### Required battle pairs

| pair_id | attacker | defender | purpose |
|---|---|---|---|
| usa_vs_fra_shared_nato_transport | usa | fra | Same historical NATO transport family without generic NATO leakage |
| srb_vs_rus_shared_rusa_transport | srb | rus | Same historical RUSA transport family isolation |
| usa_vs_dprk_cross_coalition | usa | dprk | Cross-coalition pair |
| regional_garrison_48 | usa | issue_48_regional_local_garrison | Regional/local garrison profile from #48 without sovereign recruitment transfer |

## Actors

| actor_id | display | playable | roster_class | tactical_side | campaign | family | units | research | AI | native |
|---|---|---|---|---|---|---|---:|---:|---|---|
| alb | Albania | False | strategic_only | `goc_alb` | `nato` | `nato` | 0 | 0 | none | not_run |
| arm | Armenia | False | strategic_only | `goc_arm` | `rusa` | `rusa` | 0 | 0 | none | not_run |
| aut | Austria | False | strategic_only | `goc_aut` | `nato` | `nato` | 0 | 0 | none | not_run |
| aze | Azerbaijan | False | strategic_only | `goc_aze` | `nato` | `nato` | 0 | 0 | none | not_run |
| bel | Belgium | True | coalition_fallback | `goc_bel` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| bgr | Bulgaria | True | coalition_fallback | `goc_bgr` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| bih | Bosnia and Herzegovina | False | strategic_only | `goc_bih` | `nato` | `nato` | 0 | 0 | none | not_run |
| blr | Belarus | True | proxy_hybrid | `rusa` | `rusa` | `rusa` | None | None | actor_scoped_ai_economy | not_run |
| can | Canada | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| che | Switzerland | False | strategic_only | `goc_che` | `nato` | `nato` | 0 | 0 | none | not_run |
| cyp | Cyprus | False | strategic_only | `goc_cyp` | `nato` | `nato` | 0 | 0 | none | not_run |
| cze | Czechia | True | national_hybrid | `goc_cze` | `nato` | `nato` | 8 | 8 | actor_scoped_ai_economy | not_run |
| deu | Germany | True | full_national | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| dnk | Denmark | True | coalition_fallback | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| donbas | Donbas Forces | True | proxy_hybrid | `rusa` | `rusa` | `rusa` | None | None | actor_scoped_ai_economy | not_run |
| dprk | North Korea | True | proxy_hybrid | `rusa` | `rusa` | `rusa` | None | None | actor_scoped_ai_economy | not_run |
| dza | Algeria | False | strategic_only | `goc_dza` | `rusa` | `rusa` | 0 | 0 | none | not_run |
| egy | Egypt | False | strategic_only | `goc_egy` | `nato` | `nato` | 0 | 0 | none | not_run |
| esp | Spain | True | coalition_fallback | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| est | Estonia | True | coalition_fallback | `goc_est` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| fin | Finland | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| fra | France | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| gbr | United Kingdom | True | full_national | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| geo | Georgia | False | strategic_only | `goc_geo` | `nato` | `nato` | 0 | 0 | none | not_run |
| grc | Greece | True | coalition_fallback | `goc_grc` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| hrv | Croatia | True | coalition_fallback | `goc_hrv` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| hun | Hungary | True | coalition_fallback | `goc_hun` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| irl | Ireland | False | strategic_only | `goc_irl` | `nato` | `nato` | 0 | 0 | none | not_run |
| irq | Iraq | False | strategic_only | `goc_irq` | `nato` | `nato` | 0 | 0 | none | not_run |
| isl | Iceland | False | strategic_only | `goc_isl` | `nato` | `nato` | 0 | 0 | none | not_run |
| isr | Israel | False | strategic_only | `goc_isr` | `nato` | `nato` | 0 | 0 | none | not_run |
| ita | Italy | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| jor | Jordan | False | strategic_only | `goc_jor` | `nato` | `nato` | 0 | 0 | none | not_run |
| kpa_expeditionary | KPA Expeditionary Corps | False | nonstate | `rusa` | `rusa` | `rusa` | 0 | 0 | none | not_run |
| lbn | Lebanon | False | strategic_only | `goc_lbn` | `nato` | `nato` | 0 | 0 | none | not_run |
| lby | Libya | False | strategic_only | `goc_lby` | `rusa` | `rusa` | 0 | 0 | none | not_run |
| ltu | Lithuania | True | coalition_fallback | `goc_ltu` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| lva | Latvia | True | coalition_fallback | `goc_lva` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| mar | Morocco | False | strategic_only | `goc_mar` | `nato` | `nato` | 0 | 0 | none | not_run |
| mda | Moldova | False | strategic_only | `goc_mda` | `rusa` | `rusa` | 0 | 0 | none | not_run |
| mkd | North Macedonia | False | strategic_only | `goc_mkd` | `nato` | `nato` | 0 | 0 | none | not_run |
| mlt | Malta | False | strategic_only | `goc_mlt` | `nato` | `nato` | 0 | 0 | none | not_run |
| mne | Montenegro | False | strategic_only | `goc_mne` | `nato` | `nato` | 0 | 0 | none | not_run |
| nld | Netherlands | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| nor | Norway | True | coalition_fallback | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| pol | Poland | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| prc | People's Republic of China | True | full_national | `prc` | `prc` | `prc` | None | None | actor_scoped_ai_economy | not_run |
| prt | Portugal | True | coalition_fallback | `goc_prt` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| rou | Romania | True | coalition_fallback | `goc_rou` | `nato` | `nato` | 55 | 55 | actor_scoped_ai_economy | not_run |
| rus | Russia | True | full_national | `rusa` | `rusa` | `rusa` | None | None | actor_scoped_ai_economy | not_run |
| srb | Serbia | True | proxy_hybrid | `rusa` | `rusa` | `rusa` | None | None | actor_scoped_ai_economy | not_run |
| svk | Slovakia | True | national_hybrid | `goc_svk` | `nato` | `nato` | 8 | 8 | actor_scoped_ai_economy | not_run |
| svn | Slovenia | False | strategic_only | `goc_svn` | `nato` | `nato` | 0 | 0 | none | not_run |
| swe | Sweden | True | national_hybrid | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| syr | Syria | False | strategic_only | `goc_syr` | `rusa` | `rusa` | 0 | 0 | none | not_run |
| tun | Tunisia | False | strategic_only | `goc_tun` | `nato` | `nato` | 0 | 0 | none | not_run |
| tur | Turkey | True | coalition_fallback | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| ukr | Ukraine | True | full_national | `ukr` | `ukr` | `ukr` | None | None | actor_scoped_ai_economy | not_run |
| ukr_ildu | International Legion for the Defence of Ukraine | False | nonstate | `ukr` | `ukr` | `ukr` | 0 | 0 | none | not_run |
| usa | United States | True | full_national | `nato` | `nato` | `nato` | None | None | actor_scoped_ai_economy | not_run |
| wagner | Wagner / Russian PMC Forces | False | nonstate | `rusa` | `rusa` | `rusa` | 0 | 0 | none | not_run |
