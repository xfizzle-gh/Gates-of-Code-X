# Code:X and West81 national unit-pool audit

> Audit recommendations only. This report does not change campaign factions, actors, ownership, or GoH tactical sides.

Stack signature: `3610d0a1b33de2cb20f62540352a134e0a5fcbd9e42bc724dd2f7734613d2a13`

## Source layers

| Priority | Layer | Role | Root |
|---:|---|---|---|
| 0 | Call to Arms - Gates of Hell | unknown | `Call to Arms - Gates of Hell` |
| 1 | West81 | legacy_reserve | `2897299509` |
| 2 | Code:X | modern | `3261086933` |
| 3 | Code:X AI Overhaul | overlay | `3636883799` |
| 4 | West81 | legacy_reserve | `3700832981` |

## Actor decision table

| Actor / pool | Tactical side | Raw | Materializable | Modern | Legacy | Complete loadouts | Recommendation |
|---|---|---:|---:|---:|---:|---:|---|
| generic_nato | nato | 422 | 190 | 184 | 0 | 107 | `playable_with_coalition_fallback` |
| generic_rusa | rusa | 464 | 35 | 33 | 0 | 14 | `playable_with_coalition_fallback` |
| germany | nato | 5 | 2 | 2 | 0 | 0 | `diplomatic_or_garrison_actor_only` |
| prc | prc, ukr | 468 | 243 | 91 | 144 | 16 | `playable_with_coalition_fallback` |
| russia | rusa | 283 | 249 | 249 | 0 | 205 | `playable_with_coalition_fallback` |
| serbia | rusa | 7 | 0 | 0 | 0 | 0 | `insufficient_content` |
| ukraine | ukr | 540 | 215 | 215 | 0 | 191 | `playable_with_coalition_fallback` |
| usa | nato | 137 | 106 | 104 | 0 | 105 | `playable_with_coalition_fallback` |

### generic_nato

- Tactical sides: nato
- Periods: 2022s=190
- Categories: anti_armor=53, apc=4, engineering=3, ifv=3, infantry=112, recon=5, tank=10
- Source layers: Code:X, Code:X AI Overhaul
- Missing playable-threshold capabilities: air_defense, artillery_indirect, valid_human_loadouts
- Recommendation: `playable_with_coalition_fallback`

### generic_rusa

- Tactical sides: rusa
- Periods: 2022s=35
- Categories: anti_armor=9, apc=2, artillery=4, infantry=15, recon=5
- Source layers: Code:X, Code:X AI Overhaul
- Missing playable-threshold capabilities: air_defense, valid_human_loadouts
- Recommendation: `playable_with_coalition_fallback`

### germany

- Tactical sides: nato
- Periods: 2022s=2
- Categories: anti_armor=1, infantry=1
- Source layers: Code:X, Code:X AI Overhaul
- Missing playable-threshold capabilities: transport_mechanized, air_defense, artillery_indirect, valid_human_loadouts, meaningful_variety
- Recommendation: `diplomatic_or_garrison_actor_only`

### prc

- Tactical sides: prc, ukr
- Periods: 2022s=84, era1960=159
- Categories: air_defense=1, anti_armor=45, apc=2, artillery=8, engineering=4, infantry=167, logistics_transport=1, recon=9, tank=6
- Source layers: Code:X, Code:X AI Overhaul, West81
- Missing playable-threshold capabilities: valid_human_loadouts
- Recommendation: `playable_with_coalition_fallback`

### russia

- Tactical sides: rusa
- Periods: 2022s=249
- Categories: anti_armor=49, apc=5, artillery=6, ifv=4, infantry=184, recon=1
- Source layers: Code:X, Code:X AI Overhaul
- Missing playable-threshold capabilities: air_defense, valid_human_loadouts
- Recommendation: `playable_with_coalition_fallback`

### serbia

- Tactical sides: rusa
- Periods: none
- Categories: none
- Source layers: Code:X
- Missing playable-threshold capabilities: infantry_family, crews_support, transport_mechanized, armor_or_anti_armor, air_defense, artillery_indirect, valid_human_loadouts, meaningful_variety
- Recommendation: `insufficient_content`

### ukraine

- Tactical sides: ukr
- Periods: 2022s=208, era1960=7
- Categories: anti_armor=30, apc=1, artillery=9, ifv=5, infantry=162, recon=2, tank=6
- Source layers: Code:X, Code:X AI Overhaul
- Missing playable-threshold capabilities: air_defense, valid_human_loadouts
- Recommendation: `playable_with_coalition_fallback`

### usa

- Tactical sides: nato
- Periods: 2022s=106
- Categories: anti_armor=25, apc=2, engineering=1, infantry=75, recon=3
- Source layers: Code:X, Code:X AI Overhaul
- Missing playable-threshold capabilities: air_defense, artillery_indirect, valid_human_loadouts
- Recommendation: `playable_with_coalition_fallback`

## Interpretation rules

- `tactical_side` is preserved independently from national inference.
- West81-only definitions are reserve/legacy evidence, not modern national coverage.
- Conflicting or low-confidence national evidence remains `unknown` or a generic tactical pool.
- Human loadout completeness requires a resolved breed with both a primary weapon and ammunition.
- The fully playable recommendation requires every capability listed by issue #45 plus at least six modern materializable rows.
