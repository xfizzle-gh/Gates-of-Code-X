# Expanded Nations Phase 2 source audit

Status: **LIVE-STACK AUDIT COMPLETE (evidence-only)**  
Parent: #189  
Audit issue: #190  
Phase 2 branch: `feat/189-expanded-nations-phase2`  
Repository head at audit: `e7974005173c3cf48fc28f7f0307288ba87875d1`  
Integrated main: `2d5be91fe3c9a3ed18c0e16333444ccca08b3763`  

Architecture authority (#201 owner-approved): Expanded Nations should prefer distinct Gates-owned `goc_*` tactical faction IDs for sovereign/persistent actors while Core Code:X `nato`/`ukr`/`rusa`/`prc` remain unchanged. Formal #201 battle-completion evidence remains PARTIAL; this audit does **not** claim native PASS and does **not** implement production wiring.

## Exact audit environment

```text
Audit date/time (UTC): 2026-08-11T16:20:58.355977+00:00
Auditor: agent-opencode-#190-strict
Repository head: e7974005173c3cf48fc28f7f0307288ba87875d1
Python version: 3.11.9
Method: Strict distinctive-token scan of breed stems/paths, unit IDs, research stems, and entity names across Vanilla/West81/Code:X/AIO/Gates. Generic common equipment (unqualified T-72/BMP/M113/BTR/Leopard) is NOT attributed to a nation without a national qualifier. Short ISO prefixes that collide were excluded.
vanilla: root=E:\Steam\steamapps\common\Call to Arms - Gates of Hell exists=True name=None mod_info_sha256=None mtime=2026-08-02T23:42:05.550986+00:00
west81: root=E:\Steam\steamapps\workshop\content\400750\2897299509 exists=True name=West-81 mod_info_sha256=eb50ad1d70c99ee3381c28bf92985565146f03745b55e905e82f5ba6b3d91c9a mtime=2026-08-03T00:03:38.884970+00:00
codex: root=E:\Steam\steamapps\workshop\content\400750\3261086933 exists=True name=Code-X mod_info_sha256=1e46dad6e520c9cea20c2cd69d02ca0b71bfd58ea370893b5de8b1514d9ab6c3 mtime=2026-08-10T14:58:33.164935+00:00
aio: root=E:\Steam\steamapps\workshop\content\400750\3636883799 exists=True name=CodeX Conquest AI Overhaul 1.5 mod_info_sha256=1cfe26b426459f77c3cd56cdeb21d75b2dc16d63524b0e88da2773016f4ecfa0 mtime=2026-08-03T00:03:38.780542+00:00
gates: root=E:\Steam\steamapps\workshop\content\400750\3696721120 exists=True name=Gates of CodeX mod_info_sha256=f0b232f51847833deec5575c9254a43ec8650eedb62f930e71bc07cc09eb4e69 mtime=2026-08-11T14:42:45.167204+00:00
```

Required load order audited: Vanilla → West81 → Code:X → Code:X AI Overhaul → Gates of Code:X.

## Disposition vocabulary

- `full_national` — complete source-backed national military suitable for normal play.
- `national_hybrid` — national identity/equipment plus explicit audited gap-fill.
- `coalition_fallback` — playable via explicitly labeled coalition roster; national content insufficient.
- `regional_fallback` — geographic non-national fallback (owner-approved only; none assigned without owner call).
- `strategic_only` — ownership/diplomacy/persistence only; no authorized sovereign recruitment tree.
- `excluded` — not in theatre authority and/or intentionally omitted.

## Candidate disposition matrix

| Actor | Theatre | Disposition | Preferred tactical ID | Breeds | Nat. units | Equip units | Research | Components | Legacy | Cross-side | Confidence | Blockers |
|---|---:|---|---|---:|---:|---:|---:|---|---:|---:|---|---|
| grc | True | `coalition_fallback` | `goc_grc` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| rou | True | `coalition_fallback` | `goc_rou` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| bgr | True | `coalition_fallback` | `goc_bgr` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| hun | True | `coalition_fallback` | `goc_hun` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| cze | True | `national_hybrid` | `goc_cze` | 0 | 3 | 0 | 0 | cze_national,gapfill_equipment_audited | 0 | 3 | medium | — |
| svk | True | `national_hybrid` | `goc_svk` | 0 | 0 | 3 | 0 | svk_equipment_identity,nato_common_infantry_bridge | 0 | 3 | medium-low | — |
| bel | True | `coalition_fallback` | `goc_bel` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| prt | True | `coalition_fallback` | `goc_prt` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| hrv | True | `coalition_fallback` | `goc_hrv` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| ltu | True | `coalition_fallback` | `goc_ltu` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| lva | True | `coalition_fallback` | `goc_lva` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| est | True | `coalition_fallback` | `goc_est` | 0 | 0 | 0 | 0 | nato_full_fallback | 0 | 0 | medium | no_distinctive_national_source_content |
| aut | True | `strategic_only` | `goc_aut` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| che | True | `strategic_only` | `goc_che` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| irl | True | `strategic_only` | `goc_irl` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| svn | True | `strategic_only` | `goc_svn` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| bih | True | `strategic_only` | `goc_bih` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| mne | True | `strategic_only` | `goc_mne` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| alb | True | `strategic_only` | `goc_alb` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| mkd | True | `strategic_only` | `goc_mkd` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| mda | True | `strategic_only` | `goc_mda` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| isl | True | `strategic_only` | `goc_isl` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_standing_army_content_expected |
| cyp | True | `strategic_only` | `goc_cyp` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_distinctive_national_source_content |
| mlt | True | `strategic_only` | `goc_mlt` | 0 | 0 | 0 | 0 | — | 0 | 0 | high | no_standing_army_content_expected |
| geo | True | `strategic_only` | `goc_geo` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| arm | True | `strategic_only` | `goc_arm` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| aze | True | `strategic_only` | `goc_aze` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| isr | True | `national_hybrid` | `goc_isr` | 0 | 0 | 0 | 0 | isr_equipment_identity,nato_common_infantry_bridge | 0 | 0 | medium-low | — |
| lbn | True | `strategic_only` | `goc_lbn` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| syr | True | `strategic_only` | `goc_syr` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| jor | True | `strategic_only` | `goc_jor` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| irq | True | `strategic_only` | `goc_irq` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| mar | True | `strategic_only` | `goc_mar` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| dza | True | `strategic_only` | `goc_dza` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| tun | True | `strategic_only` | `goc_tun` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| lby | True | `strategic_only` | `goc_lby` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |
| egy | True | `strategic_only` | `goc_egy` | 0 | 0 | 0 | 0 | — | 0 | 0 | medium | no_distinctive_national_source_content |

Preferred tactical ID is the #201 production direction (`goc_<iso>`), not a claim the faction is already wired.

## Judgment / fallback decisions (explicit)

### grc / Greece — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_grc` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### rou / Romania — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_rou` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### bgr / Bulgaria — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_bgr` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### hun / Hungary — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_hun` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### cze / Czechia — `national_hybrid` (medium)
- No dedicated national research root; generated/hybrid research expected under goc_* later.
- National seed present but incomplete for full sovereign package.
- Architecture (#201 approved): prefer Gates tactical ID `goc_cze` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- 3 side-tagged source rows require goc_* side-remap/materialization testing.
- **Missing:** complete_national_equipment_tree, native_research_tree
- **Proposed components:** `cze_national, gapfill_equipment_audited`
- **Exact evidenced unit IDs (sample):** `vz_77_dana`

### svk / Slovakia — `national_hybrid` (medium-low)
- Distinctive equipment identity without national breed family; infantry bridge must be explicit and labeled.
- Architecture (#201 approved): prefer Gates tactical ID `goc_svk` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- 3 side-tagged source rows require goc_* side-remap/materialization testing.
- **Missing:** national_infantry_breeds, native_research_tree
- **Proposed components:** `svk_equipment_identity, nato_common_infantry_bridge`
- **Exact evidenced unit IDs (sample):** `vz_77_dana`

### bel / Belgium — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_bel` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### prt / Portugal — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_prt` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### hrv / Croatia — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_hrv` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### ltu / Lithuania — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_ltu` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### lva / Latvia — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_lva` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### est / Estonia — `coalition_fallback` (medium)
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_est` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Missing:** national_equipment, national_infantry, national_research
- **Proposed components:** `nato_full_fallback`
- **Exact evidenced unit IDs:** none under strict filter

### aut / Austria — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_aut` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### che / Switzerland — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_che` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### irl / Ireland — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_irl` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### svn / Slovenia — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_svn` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### bih / Bosnia and Herzegovina — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_bih` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### mne / Montenegro — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_mne` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### alb / Albania — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_alb` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### mkd / North Macedonia — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_mkd` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### mda / Moldova — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_mda` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### isl / Iceland — `strategic_only` (high)
- No standing national land-force package expected or evidenced.
- Architecture (#201 approved): prefer Gates tactical ID `goc_isl` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_standing_army_content_expected
- **Exact evidenced unit IDs:** none under strict filter

### cyp / Cyprus — `strategic_only` (high)
- Architecture (#201 approved): prefer Gates tactical ID `goc_cyp` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### mlt / Malta — `strategic_only` (high)
- No standing national land-force package expected or evidenced.
- Architecture (#201 approved): prefer Gates tactical ID `goc_mlt` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_standing_army_content_expected
- **Exact evidenced unit IDs:** none under strict filter

### geo / Georgia — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_geo` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### arm / Armenia — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_arm` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### aze / Azerbaijan — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_aze` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### isr / Israel — `national_hybrid` (medium-low)
- Distinctive equipment identity without national breed family; infantry bridge must be explicit and labeled.
- Architecture (#201 approved): prefer Gates tactical ID `goc_isr` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Missing:** national_infantry_breeds, native_research_tree
- **Proposed components:** `isr_equipment_identity, nato_common_infantry_bridge`
- **Exact evidenced unit IDs:** none under strict filter

### lbn / Lebanon — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_lbn` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### syr / Syria — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_syr` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### jor / Jordan — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_jor` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### irq / Iraq — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_irq` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### mar / Morocco — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_mar` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### dza / Algeria — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_dza` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### tun / Tunisia — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_tun` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### lby / Libya — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_lby` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

### egy / Egypt — `strategic_only` (medium)
- Architecture (#201 approved): prefer Gates tactical ID `goc_egy` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Exact evidenced unit IDs:** none under strict filter

## Per-actor evidence blocks

### `grc` / Greece

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "grc",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_grc",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_grc` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `rou` / Romania

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "rou",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_rou",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_rou` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `bgr` / Bulgaria

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "bgr",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_bgr",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_bgr` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `hun` / Hungary

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "hun",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_hun",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_hun` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `cze` / Czechia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 3
  - `vz_77_dana` @ `codex`:`resource/set/multiplayer/units/conquest/units_nato.set`
  - `vz_77_dana` @ `aio`:`resource/set/multiplayer/units/conquest/units_nato.set`
  - `vz_77_dana` @ `gates`:`resource/set/multiplayer/units/conquest/units_nato.set`

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0
- artillery: `vz_77_dana`

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- `vz_77_dana|src=nato|layer=codex|path=resource/set/multiplayer/units/conquest/units_nato.set`
- `vz_77_dana|src=nato|layer=aio|path=resource/set/multiplayer/units/conquest/units_nato.set`
- `vz_77_dana|src=nato|layer=gates|path=resource/set/multiplayer/units/conquest/units_nato.set`

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "cze",
  "disposition": "national_hybrid",
  "tactical_side": "goc_cze",
  "provisional_coalition_family": "nato",
  "components": [
    "cze_national",
    "gapfill_equipment_audited"
  ],
  "exact_units": [
    "vz_77_dana"
  ],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": [
    "vz_77_dana|src=nato|layer=codex|path=resource/set/multiplayer/units/conquest/units_nato.set",
    "vz_77_dana|src=nato|layer=aio|path=resource/set/multiplayer/units/conquest/units_nato.set",
    "vz_77_dana|src=nato|layer=gates|path=resource/set/multiplayer/units/conquest/units_nato.set"
  ]
}
```

**Judgment**

- Confidence: medium
- No dedicated national research root; generated/hybrid research expected under goc_* later.
- National seed present but incomplete for full sovereign package.
- Architecture (#201 approved): prefer Gates tactical ID `goc_cze` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- 3 side-tagged source rows require goc_* side-remap/materialization testing.

### `svk` / Slovakia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 3
  - `vz_77_dana` @ `codex`:`resource/set/multiplayer/units/conquest/units_nato.set`
  - `vz_77_dana` @ `aio`:`resource/set/multiplayer/units/conquest/units_nato.set`
  - `vz_77_dana` @ `gates`:`resource/set/multiplayer/units/conquest/units_nato.set`
- Entity-name hits: 0
- artillery: `vz_77_dana`

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- `vz_77_dana|src=nato|layer=codex|path=resource/set/multiplayer/units/conquest/units_nato.set`
- `vz_77_dana|src=nato|layer=aio|path=resource/set/multiplayer/units/conquest/units_nato.set`
- `vz_77_dana|src=nato|layer=gates|path=resource/set/multiplayer/units/conquest/units_nato.set`

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "svk",
  "disposition": "national_hybrid",
  "tactical_side": "goc_svk",
  "provisional_coalition_family": "nato",
  "components": [
    "svk_equipment_identity",
    "nato_common_infantry_bridge"
  ],
  "exact_units": [
    "vz_77_dana"
  ],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": [
    "vz_77_dana|src=nato|layer=codex|path=resource/set/multiplayer/units/conquest/units_nato.set",
    "vz_77_dana|src=nato|layer=aio|path=resource/set/multiplayer/units/conquest/units_nato.set",
    "vz_77_dana|src=nato|layer=gates|path=resource/set/multiplayer/units/conquest/units_nato.set"
  ]
}
```

**Judgment**

- Confidence: medium-low
- Distinctive equipment identity without national breed family; infantry bridge must be explicit and labeled.
- Architecture (#201 approved): prefer Gates tactical ID `goc_svk` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- 3 side-tagged source rows require goc_* side-remap/materialization testing.

### `bel` / Belgium

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "bel",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_bel",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_bel` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `prt` / Portugal

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "prt",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_prt",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_prt` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `hrv` / Croatia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "hrv",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_hrv",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_hrv` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `ltu` / Lithuania

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "ltu",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_ltu",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_ltu` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `lva` / Latvia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "lva",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_lva",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_lva` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `est` / Estonia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `playable_or_fallback`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "est",
  "disposition": "coalition_fallback",
  "tactical_side": "goc_est",
  "provisional_coalition_family": "nato",
  "components": [
    "nato_full_fallback"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- No distinctive national breeds/units/equipment IDs found after strict token filter. Playable only via explicit labeled coalition fallback if owner authorizes.
- Architecture (#201 approved): prefer Gates tactical ID `goc_est` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `aut` / Austria

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "aut",
  "disposition": "strategic_only",
  "tactical_side": "goc_aut",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_aut` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `che` / Switzerland

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "che",
  "disposition": "strategic_only",
  "tactical_side": "goc_che",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_che` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `irl` / Ireland

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "irl",
  "disposition": "strategic_only",
  "tactical_side": "goc_irl",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_irl` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `svn` / Slovenia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "svn",
  "disposition": "strategic_only",
  "tactical_side": "goc_svn",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_svn` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `bih` / Bosnia and Herzegovina

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "bih",
  "disposition": "strategic_only",
  "tactical_side": "goc_bih",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_bih` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `mne` / Montenegro

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "mne",
  "disposition": "strategic_only",
  "tactical_side": "goc_mne",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_mne` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `alb` / Albania

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "alb",
  "disposition": "strategic_only",
  "tactical_side": "goc_alb",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_alb` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `mkd` / North Macedonia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "mkd",
  "disposition": "strategic_only",
  "tactical_side": "goc_mkd",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_mkd` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `mda` / Moldova

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "mda",
  "disposition": "strategic_only",
  "tactical_side": "goc_mda",
  "provisional_coalition_family": "rusa",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_mda` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- Blocking gaps: no_distinctive_national_source_content

### `isl` / Iceland

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "isl",
  "disposition": "strategic_only",
  "tactical_side": "goc_isl",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- No standing national land-force package expected or evidenced.
- Architecture (#201 approved): prefer Gates tactical ID `goc_isl` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_standing_army_content_expected

### `cyp` / Cyprus

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "cyp",
  "disposition": "strategic_only",
  "tactical_side": "goc_cyp",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- Architecture (#201 approved): prefer Gates tactical ID `goc_cyp` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `mlt` / Malta

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `strategic_first`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "mlt",
  "disposition": "strategic_only",
  "tactical_side": "goc_mlt",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: high
- No standing national land-force package expected or evidenced.
- Architecture (#201 approved): prefer Gates tactical ID `goc_mlt` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_standing_army_content_expected

### `geo` / Georgia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "geo",
  "disposition": "strategic_only",
  "tactical_side": "goc_geo",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_geo` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `arm` / Armenia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "arm",
  "disposition": "strategic_only",
  "tactical_side": "goc_arm",
  "provisional_coalition_family": "rusa",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_arm` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- Blocking gaps: no_distinctive_national_source_content

### `aze` / Azerbaijan

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "aze",
  "disposition": "strategic_only",
  "tactical_side": "goc_aze",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_aze` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `isr` / Israel

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 2
  - `spike-er` @ `codex`
  - `spike-sr` @ `codex`

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "isr",
  "disposition": "national_hybrid",
  "tactical_side": "goc_isr",
  "provisional_coalition_family": "nato",
  "components": [
    "isr_equipment_identity",
    "nato_common_infantry_bridge"
  ],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium-low
- Distinctive equipment identity without national breed family; infantry bridge must be explicit and labeled.
- Architecture (#201 approved): prefer Gates tactical ID `goc_isr` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.

### `lbn` / Lebanon

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "lbn",
  "disposition": "strategic_only",
  "tactical_side": "goc_lbn",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_lbn` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `syr` / Syria

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "syr",
  "disposition": "strategic_only",
  "tactical_side": "goc_syr",
  "provisional_coalition_family": "rusa",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_syr` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- Blocking gaps: no_distinctive_national_source_content

### `jor` / Jordan

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "jor",
  "disposition": "strategic_only",
  "tactical_side": "goc_jor",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_jor` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `irq` / Iraq

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "irq",
  "disposition": "strategic_only",
  "tactical_side": "goc_irq",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_irq` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `mar` / Morocco

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "mar",
  "disposition": "strategic_only",
  "tactical_side": "goc_mar",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_mar` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `dza` / Algeria

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "dza",
  "disposition": "strategic_only",
  "tactical_side": "goc_dza",
  "provisional_coalition_family": "rusa",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_dza` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- Blocking gaps: no_distinctive_national_source_content

### `tun` / Tunisia

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "tun",
  "disposition": "strategic_only",
  "tactical_side": "goc_tun",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_tun` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

### `lby` / Libya

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "lby",
  "disposition": "strategic_only",
  "tactical_side": "goc_lby",
  "provisional_coalition_family": "rusa",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_lby` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- Blocking gaps: no_distinctive_national_source_content

### `egy` / Egypt

**Authoritative theatre presence**

- Theatre present (Earth3/expanded-nations catalog scan): `True`
- Planning class: `crop_conditional`

**National personnel evidence**

- Breed hits: 0
  - none under strict distinctive filter
- National-token unit IDs: 0

**National equipment evidence**

- Distinctive equipment unit hits: 0
- Entity-name hits: 0

**Research evidence**

- none dedicated under strict filter

**Legacy/reserve (West81-terminal samples)**

- none flagged

**Cross-side / side-sensitive rows (nato/rusa/… namespaces)**

- none flagged among evidenced national/equip hits

**Recommended selectors (not implemented)**

```json
{
  "actor_id": "egy",
  "disposition": "strategic_only",
  "tactical_side": "goc_egy",
  "provisional_coalition_family": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "legacy_units": [],
  "cross_side_units": []
}
```

**Judgment**

- Confidence: medium
- Architecture (#201 approved): prefer Gates tactical ID `goc_egy` for sovereign/persistent production wiring; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- Blocking gaps: no_distinctive_national_source_content

## Audit-wide rejection rules (applied)

- No guessed national IDs without a resolving path/token hit under the **strict** filter.
- Generic shared equipment (unqualified T-72/BMP/M113/BTR/Leopard pools) is **not** attributed to a Phase 2 nation.
- West81 hits are legacy/reserve only, never modern Code:X authority.
- Cross-side nato/rusa rows among evidenced hits are enumerated for later `goc_*` materialization testing.
- PMC/militia/foreign-volunteer pools are not promoted to sovereign national armies.
- `regional_fallback` was **not** auto-assigned (requires explicit owner geographic fallback ruling).
- No upstream mods modified; no #191/#192/#193 implementation; no #201 spike edits; no PR #172 changes.

## Completion checklist

- [x] exact source environment recorded
- [x] theatre presence resolved for every candidate (catalog scan)
- [x] all 37 candidates have one disposition
- [x] selectors/roots tied to source path/layer evidence in JSON ledger
- [x] legacy rows explicitly marked
- [x] cross-side rows enumerated
- [x] JSON candidate ledger updated
- [ ] #190 comment posted with summary and exact head (post-push)
- [x] no upstream mod modified
- [x] no Phase 2 roster implementation started

Machine-readable ledger: `docs/audits/expanded-nations-phase2-source-candidates.json`.

