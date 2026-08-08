# Faction wiring source audit

Audit date: 2026-08-08

This report records the self-audit performed against the user-provided Code:X, West81, and AI Overhaul source snapshots before independent review.

## Inputs

```text
codex_faction_audit_20260807_231259.zip
gates_faction_source_audit_20260807_230128.zip
```

Audited source order:

1. West81
2. Code:X
3. Code:X AI Overhaul

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

Breed checks were performed against `.set` file stems under the appropriate Code:X side directory, matching the compiler's `_breed_exists` contract. This matters because several breed files use internal content names that differ from their file stems.

The source pass confirmed the high-risk identifiers used for:

- the KPA `kor_*` contingent
- Ukraine's `nato_*` / `ildu` personnel
- Donbas `lud_*`, `spd_*`, `vostok_*`, and `ldnr_*` material
- Wagner and Russian irregular branches
- Serbian `Serb_*` personnel
- US, British, German, French, Polish, Italian, Nordic, Dutch, and Canadian NATO equipment
- West81 Soviet-pattern legacy equipment

## Repository validation

The compiler and manifest tests run in the normal GitHub Actions matrix. They cover:

- exact bundled actor set
- supported tactical export sides only
- strict manifest schema validation
- required selector failure behavior
- existing upstream breed validation for virtual squads
- West81 legacy provenance preservation
- deterministic output on repeated fixture compilation
- actor-scoped research keys
- prerequisite completeness
- filtered-branch prerequisite reparenting
- research graph cycle rejection
- non-empty materializable rosters and research trees

GitHub Actions run `31241093578` passed on Windows and Ubuntu with Python 3.11 and 3.13, plus the Godot, installer, deployment-smoke, and executable-build jobs.

## Important audit boundary

The uploaded Code:X and West81 source snapshots are not committed to this repository and were not available inside GitHub Actions. Therefore this checked-in report does **not** claim live-stack per-actor unit counts, live wiring signatures, or live stack signatures.

Those values must be produced by running the committed compiler against the current installed Workshop stack. The independent audit issue intentionally requires that run and requires the auditor to report any changed or unresolved source references.

## High-risk cases checked

### North Korea

The KPA pool references the existing Code:X `kor_*` squads inside the Russian `2022vdv106` branch. North Korea adds an explicit West81 Soviet-pattern legacy heavy-equipment component. The same Korean squads remain available to the separately hosted KPA Expeditionary Corps under Russia.

### Ukraine International Legion

Six `goc_ildu_*` purchase wrappers reference existing Code:X `nato_*` / `ildu` breed files. Every referenced breed stem exists in the uploaded source snapshot. No breed, portrait, weapon, or model is copied into Gates of Code:X.

### Donbas

The native progression references `2022rusldpr`. Five additional `goc_sparta_*` and `goc_vostok_*` wrappers reference existing latent `spd_*` and `vostok_*` breed files. Every referenced breed stem exists.

### Belarus and Serbia

Both are explicitly labeled constructed hybrids. Belarus combines West81 Soviet legacy equipment with a filtered Russian modernization component. Serbia combines existing `Serb_*` personnel with the approved legacy pool. Neither is represented as a complete native Code:X faction.

### NATO countries

The manifest separates US, British, German, French, Polish, Italian, Swedish, Finnish, Dutch, and Canadian identity from mixed NATO containers. Norway, Denmark, Spain, and Turkey remain visibly labeled coalition-fallback rosters rather than being presented as source-backed national Code:X armies.

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

A changed upstream stack may legitimately produce new stack or wiring signatures. Any changed roster, missing selector, or newly resolved unit must be reviewed rather than accepted by blindly updating a snapshot.
