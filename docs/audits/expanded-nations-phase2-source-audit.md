# Expanded Nations Phase 2 source audit

Status: **LIVE-STACK AUDIT COMPLETE (CORRECTED)**  
Parent: #189 · Audit issue: #190 · Branch: `feat/189-expanded-nations-phase2`  
Prior rejected head: `de6a6bb5226e20c7f5855ae721f3e7e0ca625b5d`  
Repository head at audit: `de6a6bb5226e20c7f5855ae721f3e7e0ca625b5d`  
Source corpus SHA-256: `81b9f93cb78221aec94e8f890011dd2cb7f145202127e941c41ea244c7386e96`  
Source manifest: `docs/audits/expanded-nations-phase2-source-manifest.json`  

## BLOCKER 1 — #201 restore + Gates quarantine

```text
Restore: E:\Steam\steamapps\workshop\content\400750\Gates-of-Code-X-201-custom-factions\spikes\201-custom-tactical-factions\deploy.ps1 -GatesRoot E:\Steam\steamapps\workshop\content\400750\3696721120 -Restore
ForceDiscardBackup: False
deploy-state: {"status": "restored", "timestampUtc": "2026-08-11T16:42:02.2656329Z", "message": "explicit -Restore", "gatesRoot": "E:\\Steam\\steamapps\\workshop\\content\\400750\\3696721120"}
original-ledger sha256: 6d0067a7e5db51e379d025bb2cdeefd421088fc20a5aa96b808bc6537e24cd86
B/C prototypes absent: True
  goc_dprk.set: ABSENT
  goc_rus.set: ABSENT
  goc_srb.set: ABSENT
  inf_goc_dprk.set: ABSENT
  inf_goc_rus.set: ABSENT
  inf_goc_srb.set: ABSENT
  unit_research_goc_dprk.set: ABSENT
  unit_research_goc_rus.set: ABSENT
  unit_research_goc_srb.set: ABSENT
  units_goc_dprk.set: ABSENT
  units_goc_rus.set: ABSENT
  units_goc_srb.set: ABSENT
Remaining goc_* paths on Gates (quarantined, not production authority): 111
All Gates paths matching goc_*, alliances_goc_201, units_goc_*, unit_research_goc_*, conquest.goc_*, and /spikes/ are quarantined from #190 production source authority. goc_usa/goc_fra remaining after restore were ledger-existed=true pre-deploy originals; still quarantined (not Phase-2 national evidence).
```

Note: After restore, `goc_usa`/`goc_fra` surfaces that were **ledger existed=true** (pre-deploy originals) may remain on disk. They are **quarantined** and are not used as Phase 2 national source authority. Test B/C prototypes (`goc_srb`/`goc_rus`/`goc_dprk`) are proven absent.

## BLOCKER 2 — Effective stack precedence

Every logical breed/unit/research/entity ID is resolved once through:
`Vanilla → West81 → Code:X → AI Overhaul → Gates` (Gates goc_*/#201 quarantined).
Duplicate overlay sightings are recorded in `provenance_chain` / `overlay_sightings` and **not** counted as multiple national units.

## Exact audit environment

```text
vanilla: root=E:\Steam\steamapps\common\Call to Arms - Gates of Hell files=0 inventory_sha256=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 mod_info_sha256=None
west81: root=E:\Steam\steamapps\workshop\content\400750\2897299509 files=2834 inventory_sha256=e0cf446bc1e14e849bab8f8c3e4eb8ff2a5e2291c7fc4e3e441c96d9ac4c8d49 mod_info_sha256=eb50ad1d70c99ee3381c28bf92985565146f03745b55e905e82f5ba6b3d91c9a
codex: root=E:\Steam\steamapps\workshop\content\400750\3261086933 files=2603 inventory_sha256=344102b78c7a4575f7dd4f2a04449a0e8e8b69637786734b53284d500135aa27 mod_info_sha256=1e46dad6e520c9cea20c2cd69d02ca0b71bfd58ea370893b5de8b1514d9ab6c3
aio: root=E:\Steam\steamapps\workshop\content\400750\3636883799 files=179 inventory_sha256=65545a2b76f2b1eb4de318c16f7accdaa9c6043089d58b0755b5cfdaa7c0fa02 mod_info_sha256=1cfe26b426459f77c3cd56cdeb21d75b2dc16d63524b0e88da2773016f4ecfa0
gates: root=E:\Steam\steamapps\workshop\content\400750\3696721120 files=36 inventory_sha256=1c5f12510a80ba29b896e177293f6765d6a87735672975e5d6d4921dc4bfdccf mod_info_sha256=f0b232f51847833deec5575c9254a43ec8650eedb62f930e71bc07cc09eb4e69
corpus_sha256=81b9f93cb78221aec94e8f890011dd2cb7f145202127e941c41ea244c7386e96
```

## Disposition matrix (effective IDs)

| Actor | Theatre | Disposition | Preferred ID | Eff. breeds | Eff. infantry units | Eff. arty | Eff. vehicles | Eff. PR units | Research | Inf present | Eq present | Confidence | Blockers |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| grc | True | `coalition_fallback` | `goc_grc` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| rou | True | `coalition_fallback` | `goc_rou` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| bgr | True | `coalition_fallback` | `goc_bgr` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| hun | True | `coalition_fallback` | `goc_hun` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| cze | True | `national_hybrid` | `goc_cze` | 0 | 0 | 1 | 0 | 1 | 0 | False | True | medium-low | — |
| svk | True | `national_hybrid` | `goc_svk` | 0 | 0 | 1 | 0 | 1 | 0 | False | True | medium-low | — |
| bel | True | `coalition_fallback` | `goc_bel` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| prt | True | `coalition_fallback` | `goc_prt` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| hrv | True | `coalition_fallback` | `goc_hrv` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| ltu | True | `coalition_fallback` | `goc_ltu` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| lva | True | `coalition_fallback` | `goc_lva` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| est | True | `coalition_fallback` | `goc_est` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| aut | True | `strategic_only` | `goc_aut` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| che | True | `strategic_only` | `goc_che` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| irl | True | `strategic_only` | `goc_irl` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| svn | True | `strategic_only` | `goc_svn` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| bih | True | `strategic_only` | `goc_bih` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| mne | True | `strategic_only` | `goc_mne` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| alb | True | `strategic_only` | `goc_alb` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| mkd | True | `strategic_only` | `goc_mkd` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| mda | True | `strategic_only` | `goc_mda` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| isl | True | `strategic_only` | `goc_isl` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_standing_army_content_expected |
| cyp | True | `strategic_only` | `goc_cyp` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_distinctive_national_source_content |
| mlt | True | `strategic_only` | `goc_mlt` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_standing_army_content_expected |
| geo | True | `strategic_only` | `goc_geo` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| arm | True | `strategic_only` | `goc_arm` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| aze | True | `strategic_only` | `goc_aze` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| isr | True | `strategic_only` | `goc_isr` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | high | no_purchase_ready_israeli_unit_definitions |
| lbn | True | `strategic_only` | `goc_lbn` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| syr | True | `strategic_only` | `goc_syr` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| jor | True | `strategic_only` | `goc_jor` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| irq | True | `strategic_only` | `goc_irq` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| mar | True | `strategic_only` | `goc_mar` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| dza | True | `strategic_only` | `goc_dza` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| tun | True | `strategic_only` | `goc_tun` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| lby | True | `strategic_only` | `goc_lby` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |
| egy | True | `strategic_only` | `goc_egy` | 0 | 0 | 0 | 0 | 0 | 0 | False | False | medium | no_distinctive_national_source_content |

## Disposition changes vs rejected head `de6a6bb5226e20c7f5855ae721f3e7e0ca625b5d`

- `isr`: `national_hybrid` -> `strategic_only` — Spike entity names and NATO squads that *use* Spike munitions are not purchase-ready IDF/Israeli national unit definitions.
- `cze`/`svk`: remain `national_hybrid` but counts corrected to **1 effective** purchase-ready unit (`vz_77_dana`) with `national_infantry_present=false`.
- All other actors: disposition labels unchanged from rejected head, but evidence now uses effective-precedence counts + mandated search ledgers (not layer sightings).

## Judgment / fallback decisions

### grc / Greece — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 36 (zero-hit: 28, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_grc`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `greek` scope=effective breeds (terminal layer)
  - `breeds` token `hellenic` scope=effective breeds (terminal layer)
  - `breeds` token `grc_` scope=effective breeds (terminal layer)
  - `breeds` token `greece` scope=effective breeds (terminal layer)
  - `units` token `greek` scope=effective unit IDs (terminal layer)
  - `units` token `hellenic` scope=effective unit IDs (terminal layer)
  - `units` token `grc_` scope=effective unit IDs (terminal layer)
  - `units` token `greece` scope=effective unit IDs (terminal layer)
  - `units` token `leonidas` scope=effective unit IDs (terminal layer)
  - `entities` token `leonidas` scope=effective entity defs (terminal layer)

### rou / Romania — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 41 (zero-hit: 37, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_rou`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `romanian` scope=effective breeds (terminal layer)
  - `breeds` token `romania` scope=effective breeds (terminal layer)
  - `breeds` token `rou_` scope=effective breeds (terminal layer)
  - `units` token `romanian` scope=effective unit IDs (terminal layer)
  - `units` token `romania` scope=effective unit IDs (terminal layer)
  - `units` token `rou_` scope=effective unit IDs (terminal layer)
  - `units` token `tr-85` scope=effective unit IDs (terminal layer)
  - `units` token `tr85` scope=effective unit IDs (terminal layer)
  - `units` token `tr-580` scope=effective unit IDs (terminal layer)
  - `units` token `tr580` scope=effective unit IDs (terminal layer)

### bgr / Bulgaria — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 35 (zero-hit: 23, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_bgr`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `bulgarian` scope=effective breeds (terminal layer)
  - `breeds` token `bulgaria` scope=effective breeds (terminal layer)
  - `breeds` token `bgr_` scope=effective breeds (terminal layer)
  - `units` token `bulgarian` scope=effective unit IDs (terminal layer)
  - `units` token `bulgaria` scope=effective unit IDs (terminal layer)
  - `units` token `bgr_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `entities` token `2s1` scope=effective entity defs (terminal layer)
  - `entities` token `bm-21` scope=effective entity defs (terminal layer)
  - `entities` token `shilka` scope=effective entity defs (terminal layer)

### hun / Hungary — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 38 (zero-hit: 32, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_hun`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `hungarian` scope=effective breeds (terminal layer)
  - `breeds` token `hungary` scope=effective breeds (terminal layer)
  - `breeds` token `hun_` scope=effective breeds (terminal layer)
  - `breeds` token `magyar` scope=effective breeds (terminal layer)
  - `units` token `hungarian` scope=effective unit IDs (terminal layer)
  - `units` token `hungary` scope=effective unit IDs (terminal layer)
  - `units` token `hun_` scope=effective unit IDs (terminal layer)
  - `units` token `magyar` scope=effective unit IDs (terminal layer)
  - `units` token `2a7hu` scope=effective unit IDs (terminal layer)
  - `units` token `lynx` scope=effective unit IDs (terminal layer)

### cze / Czechia — `national_hybrid` (medium-low)
- Effective breeds: 0; infantry units: 0; artillery: 1; vehicles: 0; purchase-ready total: 1
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 38 (zero-hit: 28, accepted: 4)
- Purchase-ready effective unit IDs: `vz_77_dana`
- Purchase-ready equipment without national infantry/personnel evidence.
- Architecture (#201 approved): prefer Gates tactical ID `goc_cze`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- 1 side-tagged purchase-ready rows require goc_* remap/materialization testing.
- **Components:** `cze_equipment_identity, nato_common_infantry_bridge`
- Accepted search samples:
  - `units` token `dana` raw=1 accepted=1 samples=['gates:resource/set/multiplayer/units/conquest/units_nato.set::vz_77_dana']
  - `units` token `vz_77_dana` raw=1 accepted=1 samples=['gates:resource/set/multiplayer/units/conquest/units_nato.set::vz_77_dana']
  - `localization` token `Czech` raw=1 accepted=1 samples=['gates:resource/localizations/default/interface/text/dlg_mp2.pot']
  - `localization` token `Czechoslovak` raw=1 accepted=1 samples=['gates:resource/localizations/default/interface/text/dlg_mp2.pot']
- Zero-hit search samples:
  - `breeds` token `czech` scope=effective breeds (terminal layer)
  - `breeds` token `czechoslovak` scope=effective breeds (terminal layer)
  - `breeds` token `cze_` scope=effective breeds (terminal layer)
  - `units` token `czech` scope=effective unit IDs (terminal layer)
  - `units` token `czechoslovak` scope=effective unit IDs (terminal layer)
  - `units` token `cze_` scope=effective unit IDs (terminal layer)
  - `units` token `pandur` scope=effective unit IDs (terminal layer)
  - `units` token `bvp` scope=effective unit IDs (terminal layer)
  - `units` token `t72m4` scope=effective unit IDs (terminal layer)
  - `units` token `zuzana` scope=effective unit IDs (terminal layer)

### svk / Slovakia — `national_hybrid` (medium-low)
- Effective breeds: 0; infantry units: 0; artillery: 1; vehicles: 0; purchase-ready total: 1
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 35 (zero-hit: 26, accepted: 3)
- Purchase-ready effective unit IDs: `vz_77_dana`
- Purchase-ready equipment without national infantry/personnel evidence.
- Architecture (#201 approved): prefer Gates tactical ID `goc_svk`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- 1 side-tagged purchase-ready rows require goc_* remap/materialization testing.
- **Components:** `svk_equipment_identity, nato_common_infantry_bridge`
- Accepted search samples:
  - `units` token `dana` raw=1 accepted=1 samples=['gates:resource/set/multiplayer/units/conquest/units_nato.set::vz_77_dana']
  - `units` token `vz_77_dana` raw=1 accepted=1 samples=['gates:resource/set/multiplayer/units/conquest/units_nato.set::vz_77_dana']
  - `localization` token `Slovak` raw=1 accepted=1 samples=['gates:resource/localizations/default/interface/text/dlg_mp2.pot']
- Zero-hit search samples:
  - `breeds` token `slovak` scope=effective breeds (terminal layer)
  - `breeds` token `slovakia` scope=effective breeds (terminal layer)
  - `breeds` token `svk_` scope=effective breeds (terminal layer)
  - `units` token `slovak` scope=effective unit IDs (terminal layer)
  - `units` token `slovakia` scope=effective unit IDs (terminal layer)
  - `units` token `svk_` scope=effective unit IDs (terminal layer)
  - `units` token `pandur` scope=effective unit IDs (terminal layer)
  - `units` token `bvp` scope=effective unit IDs (terminal layer)
  - `units` token `zuzana` scope=effective unit IDs (terminal layer)
  - `entities` token `pandur` scope=effective entity defs (terminal layer)

### bel / Belgium — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 23, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_bel`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `belgian` scope=effective breeds (terminal layer)
  - `breeds` token `belgium` scope=effective breeds (terminal layer)
  - `breeds` token `bel_` scope=effective breeds (terminal layer)
  - `units` token `belgian` scope=effective unit IDs (terminal layer)
  - `units` token `belgium` scope=effective unit IDs (terminal layer)
  - `units` token `bel_` scope=effective unit IDs (terminal layer)
  - `units` token `piranha` scope=effective unit IDs (terminal layer)
  - `units` token `df90` scope=effective unit IDs (terminal layer)
  - `units` token `pandur` scope=effective unit IDs (terminal layer)
  - `entities` token `piranha` scope=effective entity defs (terminal layer)

### prt / Portugal — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 23 (zero-hit: 18, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_prt`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `portuguese` scope=effective breeds (terminal layer)
  - `breeds` token `portugal` scope=effective breeds (terminal layer)
  - `breeds` token `prt_` scope=effective breeds (terminal layer)
  - `units` token `portuguese` scope=effective unit IDs (terminal layer)
  - `units` token `portugal` scope=effective unit IDs (terminal layer)
  - `units` token `prt_` scope=effective unit IDs (terminal layer)
  - `units` token `pandur` scope=effective unit IDs (terminal layer)
  - `entities` token `pandur` scope=effective entity defs (terminal layer)
  - `entities` token `leopard` scope=effective entity defs (terminal layer)
  - `research` token `portuguese` scope=effective research stems (terminal layer)

### hrv / Croatia — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 23, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_hrv`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `croatian` scope=effective breeds (terminal layer)
  - `breeds` token `croatia` scope=effective breeds (terminal layer)
  - `breeds` token `hrv_` scope=effective breeds (terminal layer)
  - `units` token `croatian` scope=effective unit IDs (terminal layer)
  - `units` token `croatia` scope=effective unit IDs (terminal layer)
  - `units` token `hrv_` scope=effective unit IDs (terminal layer)
  - `units` token `m-84` scope=effective unit IDs (terminal layer)
  - `units` token `m84` scope=effective unit IDs (terminal layer)
  - `units` token `bvp` scope=effective unit IDs (terminal layer)
  - `units` token `patria` scope=effective unit IDs (terminal layer)

### ltu / Lithuania — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 38 (zero-hit: 31, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_ltu`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `lithuanian` scope=effective breeds (terminal layer)
  - `breeds` token `lithuania` scope=effective breeds (terminal layer)
  - `breeds` token `ltu_` scope=effective breeds (terminal layer)
  - `units` token `lithuanian` scope=effective unit IDs (terminal layer)
  - `units` token `lithuania` scope=effective unit IDs (terminal layer)
  - `units` token `ltu_` scope=effective unit IDs (terminal layer)
  - `units` token `piranha` scope=effective unit IDs (terminal layer)
  - `units` token `patria` scope=effective unit IDs (terminal layer)
  - `units` token `vilkas` scope=effective unit IDs (terminal layer)
  - `entities` token `cv90` scope=effective entity defs (terminal layer)

### lva / Latvia — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 32 (zero-hit: 26, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_lva`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `latvian` scope=effective breeds (terminal layer)
  - `breeds` token `latvia` scope=effective breeds (terminal layer)
  - `breeds` token `lva_` scope=effective breeds (terminal layer)
  - `units` token `latvian` scope=effective unit IDs (terminal layer)
  - `units` token `latvia` scope=effective unit IDs (terminal layer)
  - `units` token `lva_` scope=effective unit IDs (terminal layer)
  - `units` token `piranha` scope=effective unit IDs (terminal layer)
  - `units` token `patria` scope=effective unit IDs (terminal layer)
  - `entities` token `cv90` scope=effective entity defs (terminal layer)
  - `entities` token `piranha` scope=effective entity defs (terminal layer)

### est / Estonia — `coalition_fallback` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 29 (zero-hit: 24, accepted: 0)
- Purchase-ready effective unit IDs: none
- Strict special-case search found no accepted national personnel/equipment definitions.
- Architecture (#201 approved): prefer Gates tactical ID `goc_est`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- **Components:** `nato_full_fallback`
- Zero-hit search samples:
  - `breeds` token `estonian` scope=effective breeds (terminal layer)
  - `breeds` token `estonia` scope=effective breeds (terminal layer)
  - `units` token `estonian` scope=effective unit IDs (terminal layer)
  - `units` token `estonia` scope=effective unit IDs (terminal layer)
  - `units` token `piranha` scope=effective unit IDs (terminal layer)
  - `units` token `patria` scope=effective unit IDs (terminal layer)
  - `units` token `k9` scope=effective unit IDs (terminal layer)
  - `entities` token `cv90` scope=effective entity defs (terminal layer)
  - `entities` token `piranha` scope=effective entity defs (terminal layer)
  - `entities` token `patria` scope=effective entity defs (terminal layer)

### aut / Austria — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 24, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_aut`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `austrian` scope=effective breeds (terminal layer)
  - `breeds` token `austria` scope=effective breeds (terminal layer)
  - `breeds` token `aut_` scope=effective breeds (terminal layer)
  - `units` token `austrian` scope=effective unit IDs (terminal layer)
  - `units` token `austria` scope=effective unit IDs (terminal layer)
  - `units` token `aut_` scope=effective unit IDs (terminal layer)
  - `units` token `ulani` scope=effective unit IDs (terminal layer)
  - `units` token `ulan` scope=effective unit IDs (terminal layer)
  - `units` token `pandur` scope=effective unit IDs (terminal layer)
  - `entities` token `ulani` scope=effective entity defs (terminal layer)

### che / Switzerland — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 23 (zero-hit: 20, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_che`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `swiss` scope=effective breeds (terminal layer)
  - `breeds` token `switzerland` scope=effective breeds (terminal layer)
  - `breeds` token `schweiz` scope=effective breeds (terminal layer)
  - `units` token `swiss` scope=effective unit IDs (terminal layer)
  - `units` token `switzerland` scope=effective unit IDs (terminal layer)
  - `units` token `schweiz` scope=effective unit IDs (terminal layer)
  - `units` token `piranha` scope=effective unit IDs (terminal layer)
  - `entities` token `leopard` scope=effective entity defs (terminal layer)
  - `entities` token `piranha` scope=effective entity defs (terminal layer)
  - `entities` token `m109` scope=effective entity defs (terminal layer)

### irl / Ireland — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 20 (zero-hit: 20, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_irl`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `irish` scope=effective breeds (terminal layer)
  - `breeds` token `ireland` scope=effective breeds (terminal layer)
  - `breeds` token `irl_` scope=effective breeds (terminal layer)
  - `units` token `irish` scope=effective unit IDs (terminal layer)
  - `units` token `ireland` scope=effective unit IDs (terminal layer)
  - `units` token `irl_` scope=effective unit IDs (terminal layer)
  - `units` token `mowag` scope=effective unit IDs (terminal layer)
  - `units` token `rg32` scope=effective unit IDs (terminal layer)
  - `units` token `piranha` scope=effective unit IDs (terminal layer)
  - `entities` token `mowag` scope=effective entity defs (terminal layer)

### svn / Slovenia — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 32 (zero-hit: 27, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_svn`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `slovenian` scope=effective breeds (terminal layer)
  - `breeds` token `slovenia` scope=effective breeds (terminal layer)
  - `breeds` token `svn_` scope=effective breeds (terminal layer)
  - `units` token `slovenian` scope=effective unit IDs (terminal layer)
  - `units` token `slovenia` scope=effective unit IDs (terminal layer)
  - `units` token `svn_` scope=effective unit IDs (terminal layer)
  - `units` token `m-84` scope=effective unit IDs (terminal layer)
  - `units` token `m84` scope=effective unit IDs (terminal layer)
  - `units` token `valuk` scope=effective unit IDs (terminal layer)
  - `units` token `patria` scope=effective unit IDs (terminal layer)

### bih / Bosnia and Herzegovina — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 35 (zero-hit: 26, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_bih`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `bosnian` scope=effective breeds (terminal layer)
  - `breeds` token `bosnia` scope=effective breeds (terminal layer)
  - `breeds` token `bih_` scope=effective breeds (terminal layer)
  - `breeds` token `bosniak` scope=effective breeds (terminal layer)
  - `units` token `bosnian` scope=effective unit IDs (terminal layer)
  - `units` token `bosnia` scope=effective unit IDs (terminal layer)
  - `units` token `bih_` scope=effective unit IDs (terminal layer)
  - `units` token `bosniak` scope=effective unit IDs (terminal layer)
  - `units` token `m-84` scope=effective unit IDs (terminal layer)
  - `units` token `m84` scope=effective unit IDs (terminal layer)

### mne / Montenegro — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 23 (zero-hit: 16, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_mne`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `montenegrin` scope=effective breeds (terminal layer)
  - `breeds` token `montenegro` scope=effective breeds (terminal layer)
  - `breeds` token `mne_` scope=effective breeds (terminal layer)
  - `units` token `montenegrin` scope=effective unit IDs (terminal layer)
  - `units` token `montenegro` scope=effective unit IDs (terminal layer)
  - `units` token `mne_` scope=effective unit IDs (terminal layer)
  - `units` token `bov` scope=effective unit IDs (terminal layer)
  - `research` token `montenegrin` scope=effective research stems (terminal layer)
  - `research` token `montenegro` scope=effective research stems (terminal layer)
  - `research` token `mne_` scope=effective research stems (terminal layer)

### alb / Albania — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 20 (zero-hit: 17, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_alb`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `albanian` scope=effective breeds (terminal layer)
  - `breeds` token `albania` scope=effective breeds (terminal layer)
  - `breeds` token `alb_` scope=effective breeds (terminal layer)
  - `units` token `albanian` scope=effective unit IDs (terminal layer)
  - `units` token `albania` scope=effective unit IDs (terminal layer)
  - `units` token `alb_` scope=effective unit IDs (terminal layer)
  - `units` token `tip-59` scope=effective unit IDs (terminal layer)
  - `entities` token `type59` scope=effective entity defs (terminal layer)
  - `entities` token `tip-59` scope=effective entity defs (terminal layer)
  - `research` token `albanian` scope=effective research stems (terminal layer)

### mkd / North Macedonia — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 27 (zero-hit: 18, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_mkd`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `macedonian` scope=effective breeds (terminal layer)
  - `breeds` token `macedonia` scope=effective breeds (terminal layer)
  - `breeds` token `mkd_` scope=effective breeds (terminal layer)
  - `units` token `macedonian` scope=effective unit IDs (terminal layer)
  - `units` token `macedonia` scope=effective unit IDs (terminal layer)
  - `units` token `mkd_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `research` token `macedonian` scope=effective research stems (terminal layer)
  - `research` token `macedonia` scope=effective research stems (terminal layer)
  - `research` token `mkd_` scope=effective research stems (terminal layer)

### mda / Moldova — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 18, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_mda`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `moldovan` scope=effective breeds (terminal layer)
  - `breeds` token `moldova` scope=effective breeds (terminal layer)
  - `breeds` token `mda_` scope=effective breeds (terminal layer)
  - `units` token `moldovan` scope=effective unit IDs (terminal layer)
  - `units` token `moldova` scope=effective unit IDs (terminal layer)
  - `units` token `mda_` scope=effective unit IDs (terminal layer)
  - `entities` token `mtlb` scope=effective entity defs (terminal layer)
  - `entities` token `bm-21` scope=effective entity defs (terminal layer)
  - `research` token `moldovan` scope=effective research stems (terminal layer)
  - `research` token `moldova` scope=effective research stems (terminal layer)

### isl / Iceland — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 11 (zero-hit: 11, accepted: 0)
- Purchase-ready effective unit IDs: none
- No standing national land-force package expected or evidenced.
- Architecture (#201 approved): prefer Gates tactical ID `goc_isl`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_standing_army_content_expected
- Zero-hit search samples:
  - `breeds` token `icelandic` scope=effective breeds (terminal layer)
  - `breeds` token `iceland` scope=effective breeds (terminal layer)
  - `breeds` token `isl_` scope=effective breeds (terminal layer)
  - `units` token `icelandic` scope=effective unit IDs (terminal layer)
  - `units` token `iceland` scope=effective unit IDs (terminal layer)
  - `units` token `isl_` scope=effective unit IDs (terminal layer)
  - `research` token `icelandic` scope=effective research stems (terminal layer)
  - `research` token `iceland` scope=effective research stems (terminal layer)
  - `research` token `isl_` scope=effective research stems (terminal layer)
  - `localization` token `Iceland` scope=localization text corpora (all layers, non-quarantined)

### cyp / Cyprus — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 20, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_cyp`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `cypriot` scope=effective breeds (terminal layer)
  - `breeds` token `cyprus` scope=effective breeds (terminal layer)
  - `breeds` token `cyp_` scope=effective breeds (terminal layer)
  - `units` token `cypriot` scope=effective unit IDs (terminal layer)
  - `units` token `cyprus` scope=effective unit IDs (terminal layer)
  - `units` token `cyp_` scope=effective unit IDs (terminal layer)
  - `units` token `leonidas` scope=effective unit IDs (terminal layer)
  - `entities` token `t-80` scope=effective entity defs (terminal layer)
  - `entities` token `leonidas` scope=effective entity defs (terminal layer)
  - `entities` token `amx` scope=effective entity defs (terminal layer)

### mlt / Malta — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 11 (zero-hit: 11, accepted: 0)
- Purchase-ready effective unit IDs: none
- No standing national land-force package expected or evidenced.
- Architecture (#201 approved): prefer Gates tactical ID `goc_mlt`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_standing_army_content_expected
- Zero-hit search samples:
  - `breeds` token `maltese` scope=effective breeds (terminal layer)
  - `breeds` token `malta` scope=effective breeds (terminal layer)
  - `breeds` token `mlt_` scope=effective breeds (terminal layer)
  - `units` token `maltese` scope=effective unit IDs (terminal layer)
  - `units` token `malta` scope=effective unit IDs (terminal layer)
  - `units` token `mlt_` scope=effective unit IDs (terminal layer)
  - `research` token `maltese` scope=effective research stems (terminal layer)
  - `research` token `malta` scope=effective research stems (terminal layer)
  - `research` token `mlt_` scope=effective research stems (terminal layer)
  - `localization` token `Malta` scope=localization text corpora (all layers, non-quarantined)

### geo / Georgia — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 19, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_geo`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `georgian` scope=effective breeds (terminal layer)
  - `breeds` token `georgia` scope=effective breeds (terminal layer)
  - `breeds` token `geo_` scope=effective breeds (terminal layer)
  - `units` token `georgian` scope=effective unit IDs (terminal layer)
  - `units` token `georgia` scope=effective unit IDs (terminal layer)
  - `units` token `geo_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `entities` token `cougar` scope=effective entity defs (terminal layer)
  - `entities` token `humvee` scope=effective entity defs (terminal layer)
  - `research` token `georgian` scope=effective research stems (terminal layer)

### arm / Armenia — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 26 (zero-hit: 17, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_arm`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `armenian` scope=effective breeds (terminal layer)
  - `breeds` token `armenia` scope=effective breeds (terminal layer)
  - `units` token `armenian` scope=effective unit IDs (terminal layer)
  - `units` token `armenia` scope=effective unit IDs (terminal layer)
  - `units` token `smerch` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `entities` token `smerch` scope=effective entity defs (terminal layer)
  - `research` token `armenian` scope=effective research stems (terminal layer)
  - `research` token `armenia` scope=effective research stems (terminal layer)
  - `research` token `t-72` scope=effective research stems (terminal layer)

### aze / Azerbaijan — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 38 (zero-hit: 27, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_aze`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `azerbaijani` scope=effective breeds (terminal layer)
  - `breeds` token `azerbaijan` scope=effective breeds (terminal layer)
  - `breeds` token `aze_` scope=effective breeds (terminal layer)
  - `units` token `azerbaijani` scope=effective unit IDs (terminal layer)
  - `units` token `azerbaijan` scope=effective unit IDs (terminal layer)
  - `units` token `aze_` scope=effective unit IDs (terminal layer)
  - `units` token `t-90` scope=effective unit IDs (terminal layer)
  - `units` token `smerch` scope=effective unit IDs (terminal layer)
  - `units` token `bayraktar` scope=effective unit IDs (terminal layer)
  - `entities` token `t-90` scope=effective entity defs (terminal layer)

### isr / Israel — `strategic_only` (high)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 48 (zero-hit: 40, accepted: 0)
- Purchase-ready effective unit IDs: none
- Code:X contains Spike missile *entities* and NATO squads that *use* Spike munitions (e.g. squad_arf_rifle_spike); those are not purchase-ready IDF/Israeli national units. No merkava/namer/magach/idf_* purchase-ready definitions were accepted.
- Architecture (#201): preferred future tactical ID `goc_isr`; Core four sides unchanged.
- **Blockers:** no_purchase_ready_israeli_unit_definitions
- Zero-hit search samples:
  - `breeds` token `israeli` scope=effective breeds (terminal layer)
  - `breeds` token `israel` scope=effective breeds (terminal layer)
  - `breeds` token `idf_` scope=effective breeds (terminal layer)
  - `breeds` token `isr_` scope=effective breeds (terminal layer)
  - `breeds` token `tsahal` scope=effective breeds (terminal layer)
  - `units` token `israeli` scope=effective unit IDs (terminal layer)
  - `units` token `israel` scope=effective unit IDs (terminal layer)
  - `units` token `idf_` scope=effective unit IDs (terminal layer)
  - `units` token `isr_` scope=effective unit IDs (terminal layer)
  - `units` token `tsahal` scope=effective unit IDs (terminal layer)

### lbn / Lebanon — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 29 (zero-hit: 18, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_lbn`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `lebanese` scope=effective breeds (terminal layer)
  - `breeds` token `lebanon` scope=effective breeds (terminal layer)
  - `breeds` token `lbn_` scope=effective breeds (terminal layer)
  - `units` token `lebanese` scope=effective unit IDs (terminal layer)
  - `units` token `lebanon` scope=effective unit IDs (terminal layer)
  - `units` token `lbn_` scope=effective unit IDs (terminal layer)
  - `entities` token `t54` scope=effective entity defs (terminal layer)
  - `research` token `lebanese` scope=effective research stems (terminal layer)
  - `research` token `lebanon` scope=effective research stems (terminal layer)
  - `research` token `lbn_` scope=effective research stems (terminal layer)

### syr / Syria — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 35 (zero-hit: 21, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_syr`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `syrian` scope=effective breeds (terminal layer)
  - `breeds` token `syria` scope=effective breeds (terminal layer)
  - `breeds` token `syr_` scope=effective breeds (terminal layer)
  - `units` token `syrian` scope=effective unit IDs (terminal layer)
  - `units` token `syria` scope=effective unit IDs (terminal layer)
  - `units` token `syr_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `entities` token `bm-21` scope=effective entity defs (terminal layer)
  - `research` token `syrian` scope=effective research stems (terminal layer)
  - `research` token `syria` scope=effective research stems (terminal layer)

### jor / Jordan — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 23 (zero-hit: 17, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_jor`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `jordanian` scope=effective breeds (terminal layer)
  - `breeds` token `jordan` scope=effective breeds (terminal layer)
  - `breeds` token `jor_` scope=effective breeds (terminal layer)
  - `units` token `jordanian` scope=effective unit IDs (terminal layer)
  - `units` token `jordan` scope=effective unit IDs (terminal layer)
  - `units` token `jor_` scope=effective unit IDs (terminal layer)
  - `units` token `ratel` scope=effective unit IDs (terminal layer)
  - `entities` token `ratel` scope=effective entity defs (terminal layer)
  - `research` token `jordanian` scope=effective research stems (terminal layer)
  - `research` token `jordan` scope=effective research stems (terminal layer)

### irq / Iraq — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 29 (zero-hit: 19, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_irq`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `iraqi` scope=effective breeds (terminal layer)
  - `breeds` token `iraq` scope=effective breeds (terminal layer)
  - `breeds` token `irq_` scope=effective breeds (terminal layer)
  - `units` token `iraqi` scope=effective unit IDs (terminal layer)
  - `units` token `iraq` scope=effective unit IDs (terminal layer)
  - `units` token `irq_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `entities` token `humvee` scope=effective entity defs (terminal layer)
  - `research` token `iraqi` scope=effective research stems (terminal layer)
  - `research` token `iraq` scope=effective research stems (terminal layer)

### mar / Morocco — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 23 (zero-hit: 15, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_mar`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `moroccan` scope=effective breeds (terminal layer)
  - `breeds` token `morocco` scope=effective breeds (terminal layer)
  - `units` token `moroccan` scope=effective unit IDs (terminal layer)
  - `units` token `morocco` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `entities` token `amx` scope=effective entity defs (terminal layer)
  - `research` token `moroccan` scope=effective research stems (terminal layer)
  - `research` token `morocco` scope=effective research stems (terminal layer)
  - `research` token `m1a1` scope=effective research stems (terminal layer)
  - `research` token `t-72` scope=effective research stems (terminal layer)

### dza / Algeria — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 32 (zero-hit: 23, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_dza`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `algerian` scope=effective breeds (terminal layer)
  - `breeds` token `algeria` scope=effective breeds (terminal layer)
  - `breeds` token `dza_` scope=effective breeds (terminal layer)
  - `units` token `algerian` scope=effective unit IDs (terminal layer)
  - `units` token `algeria` scope=effective unit IDs (terminal layer)
  - `units` token `dza_` scope=effective unit IDs (terminal layer)
  - `units` token `t-90` scope=effective unit IDs (terminal layer)
  - `units` token `smerch` scope=effective unit IDs (terminal layer)
  - `entities` token `t-90` scope=effective entity defs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)

### tun / Tunisia — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 20 (zero-hit: 15, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_tun`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `tunisian` scope=effective breeds (terminal layer)
  - `breeds` token `tunisia` scope=effective breeds (terminal layer)
  - `breeds` token `tun_` scope=effective breeds (terminal layer)
  - `units` token `tunisian` scope=effective unit IDs (terminal layer)
  - `units` token `tunisia` scope=effective unit IDs (terminal layer)
  - `units` token `tun_` scope=effective unit IDs (terminal layer)
  - `entities` token `aml` scope=effective entity defs (terminal layer)
  - `research` token `tunisian` scope=effective research stems (terminal layer)
  - `research` token `tunisia` scope=effective research stems (terminal layer)
  - `research` token `tun_` scope=effective research stems (terminal layer)

### lby / Libya — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 32 (zero-hit: 19, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_lby`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `rusa`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `libyan` scope=effective breeds (terminal layer)
  - `breeds` token `libya` scope=effective breeds (terminal layer)
  - `breeds` token `lby_` scope=effective breeds (terminal layer)
  - `units` token `libyan` scope=effective unit IDs (terminal layer)
  - `units` token `libya` scope=effective unit IDs (terminal layer)
  - `units` token `lby_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-72` scope=effective entity defs (terminal layer)
  - `research` token `libyan` scope=effective research stems (terminal layer)
  - `research` token `libya` scope=effective research stems (terminal layer)
  - `research` token `lby_` scope=effective research stems (terminal layer)

### egy / Egypt — `strategic_only` (medium)
- Effective breeds: 0; infantry units: 0; artillery: 0; vehicles: 0; purchase-ready total: 0
- `national_infantry_present=False` (breeds or infantry squads only; artillery/entities do not qualify)
- Search queries: 29 (zero-hit: 18, accepted: 0)
- Purchase-ready effective unit IDs: none
- Architecture (#201 approved): prefer Gates tactical ID `goc_egy`; Core nato/ukr/rusa/prc unchanged. Provisional coalition family for labeled gap-fill only: `nato`.
- **Blockers:** no_distinctive_national_source_content
- Zero-hit search samples:
  - `breeds` token `egyptian` scope=effective breeds (terminal layer)
  - `breeds` token `egypt` scope=effective breeds (terminal layer)
  - `breeds` token `egy_` scope=effective breeds (terminal layer)
  - `units` token `egyptian` scope=effective unit IDs (terminal layer)
  - `units` token `egypt` scope=effective unit IDs (terminal layer)
  - `units` token `egy_` scope=effective unit IDs (terminal layer)
  - `entities` token `t-62` scope=effective entity defs (terminal layer)
  - `research` token `egyptian` scope=effective research stems (terminal layer)
  - `research` token `egypt` scope=effective research stems (terminal layer)
  - `research` token `egy_` scope=effective research stems (terminal layer)

## Israel disposition rationale

- Disposition: `strategic_only`
- Purchase-ready units: 0
- Entities accepted: []
- Entity-only Spike names are not treated as purchase-ready sovereign roster evidence.

## Validation checklist

- [x] JSON ledger rewritten with 37 candidates
- [x] no pending_audit
- [x] effective IDs counted once (precedence-resolved)
- [x] national_infantry_present requires breeds/infantry squads
- [x] special-case search ledger includes zero-hits
- [x] source manifest inventory hashes recorded
- [x] #201 B/C prototypes absent; Gates goc_* quarantined
- [x] no #191/#192/#193 / no production wiring / no #201 spike edits

