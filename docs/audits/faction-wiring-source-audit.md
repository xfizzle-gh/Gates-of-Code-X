# Faction wiring source audit

Audit date: 2026-08-08

This report records two self-audit passes against the user-provided Code:X, West81, and AI Overhaul source snapshots before independent review.

## Inputs

```text
codex_faction_audit_20260807_231259.zip
gates_faction_source_audit_20260807_230128.zip
```

Audited source order:

1. West81
2. Code:X
3. Code:X AI Overhaul
4. Gates of Code:X corrections and faction wiring

Code:X remains authoritative for modern content. West81 content is accepted only through explicitly named legacy/reserve components.

## Verified source references

A direct static pass over the extracted source snapshots checked every source identifier named by the bundled faction manifest.

```text
Research branch roots checked: 32
Missing research roots:          0
Exact unit IDs checked:         67
Missing exact unit IDs:          0
Virtual-wrapper breed stems:    47
Missing breed stems:             0
```

Breed checks were performed against `.set` file stems under the appropriate Code:X side directory. This matters because several breed files use internal content names that differ from their file stems.

The source pass confirmed the high-risk identifiers used for:

- the KPA `kor_*` contingent
- Ukraine's `nato_*` / `ildu` personnel
- Donbas `lud_*`, `spd_*`, `vostok_*`, and `ldnr_*` material
- Wagner and Russian irregular branches
- Serbian `Serb_*` personnel
- US, British, German, French, Polish, Italian, Nordic, Dutch, and Canadian NATO equipment
- West81 Soviet-pattern legacy equipment

## Second-pass breed findings and repairs

The first pass proved that referenced breed file stems existed. The second pass inspected the selected breed definitions themselves and found three cut-and-dry malformed definitions:

| Breed | Source defect | Gates correction |
|---|---|---|
| `kor_crew` | Empty inventory item; generic weapon crew lacked the standard crew perk | Removed the empty item and added `guncrew`, preserving KPA skin, portrait, nationality, rifle, ammunition, grenades, bandages, and shovel |
| `fr_spotter` | Stray text appended after the binocular inventory item | Removed the trailing token and preserved the existing SOF kit |
| `rus114_marksman` | Empty inventory item and malformed stealth perk notation | Removed the empty item and normalized the stealth perk while preserving the 114th marksman kit |

These are narrow final-layer overrides. They do not duplicate models, textures, portraits, weapons, or other upstream assets.

## Compiler hardening

The compiler now validates every selected unit, including units inherited directly from upstream research branches and exact selectors. Before a unit may enter an actor roster, it verifies:

- every member breed exists under the selected source side
- selected breed definitions have balanced braces
- selected breed inventories do not contain empty item IDs
- selected breed definitions do not contain junk text after a closing brace
- every referenced vehicle/entity ID exists in the configured stack's unit registry or entity definitions

A failed required selector is an error and the invalid unit is excluded. Optional selectors remain warnings.

Regression tests cover missing breeds, malformed breed definitions, and missing vehicle/entity IDs in addition to the previous research, provenance, actor-scope, and determinism checks.

## Repository validation

The compiler and manifest tests cover:

- exact bundled actor set
- supported tactical export sides only
- strict manifest schema validation
- required selector failure behavior
- source-unit and virtual-wrapper breed validation
- vehicle/entity validation
- West81 legacy provenance preservation
- deterministic output on repeated fixture compilation
- actor-scoped research keys
- prerequisite completeness
- filtered-branch prerequisite reparenting
- research graph cycle rejection
- non-empty materializable rosters and research trees

The current GitHub Actions run for the second-pass changes must complete before this report is treated as CI-verified.

## Important audit boundary

The uploaded Workshop source snapshots are not committed to this repository and are not available inside GitHub Actions. Therefore this checked-in report does **not** claim live-stack per-actor unit counts, live wiring signatures, live stack signatures, or native tactical spawnability.

Those values must be produced by running the committed compiler against the current installed Workshop stack. The independent audit must report every changed or unresolved reference.

The `goc_*` ILDU, Sparta/Vostok, and Serbian entries are strategic catalog squad wrappers assembled from existing source breeds. Breed existence and definition quality are validated. Independent acceptance must still prove that the tactical battle materializer emits or resolves purchase-ready native GoH squad definitions for those wrapper IDs.

## High-risk cases checked

### North Korea

The KPA pool references the existing Code:X `kor_*` squads inside the Russian `2022vdv106` branch. North Korea adds an explicit West81 Soviet-pattern legacy heavy-equipment component. The same Korean squads remain available to the separately hosted KPA Expeditionary Corps under Russia.

The standalone DPRK heavy roster remains a judgment call. Code:X directly supports the infantry contingent but not a complete national DPRK armor, artillery, air-defense, logistics, or aviation tree.

### Ukraine International Legion

Six `goc_ildu_*` catalog wrappers reference existing Code:X `nato_*` / `ildu` breed files. Every referenced breed stem exists in the uploaded source snapshot. The squad compositions remain inferred wrappers rather than native Code:X purchase entries.

### Donbas

The native progression references `2022rusldpr`. Five additional `goc_sparta_*` and `goc_vostok_*` wrappers reference existing latent `spd_*` and `vostok_*` breed files. Every referenced breed stem exists.

### Belarus and Serbia

Both are explicitly labeled constructed hybrids. Belarus combines West81 Soviet legacy equipment with a filtered Russian modernization component. Serbia combines existing `Serb_*` personnel with the approved legacy pool. Neither is represented as a complete native Code:X faction.

### NATO countries

The manifest separates US, British, German, French, Polish, Italian, Swedish, Finnish, Dutch, and Canadian identity from mixed NATO containers. Norway, Denmark, Spain, and Turkey remain visibly labeled coalition-fallback rosters rather than being presented as source-backed national Code:X armies.

All inferred assignments and alternatives are documented in `docs/audits/faction-judgment-calls.md`.

## Live-stack acceptance command

The independent auditor must rerun against the current installed stack:

```powershell
.\.venv\Scripts\gates-of-codex-factions.exe `
  --stack-config .\config\mod-stack.windows.json `
  --output .\docs\audits\resolved-factions.independent.json `
  --summary .\docs\audits\resolved-factions.independent.md
```

Required acceptance condition:

```text
actor_count = 24
error_count = 0
warning_count = 0
```

A changed upstream stack may legitimately produce new stack or wiring signatures. Any changed roster, missing selector, invalid breed, missing vehicle, or newly resolved unit must be reviewed rather than accepted by blindly updating a snapshot.
