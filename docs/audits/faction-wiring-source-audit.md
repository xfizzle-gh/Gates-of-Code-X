# Faction wiring source audit

Audit date: 2026-08-08

This report records the self-audit performed against the user-provided Code:X and West81 source snapshots before the implementation was submitted for independent review.

## Inputs

```text
codex_faction_audit_20260807_231259.zip
gates_faction_source_audit_20260807_230128.zip
```

Ordered source layers used by the compiler:

1. West81
2. Code:X
3. Code:X AI Overhaul

Code:X remains authoritative for modern content. West81 content is accepted only through explicitly named legacy/reserve components.

## Result

```text
Actors:             24
Playable actors:    21
Hosted/non-state:    3
Resolution errors:   0
Warnings:            0
Wiring signature:   e8c63de8ca04f4985dce7b099e4eb5883ea7522aaf778ffb54215004819d35f4
Stack signature:    c2298b7c75d40f48749add4e72d21bd5060ffeb4418a9a433e678801d40b6cc9
```

All resolved battle rosters export through `nato`, `ukr`, `rusa`, or `prc`. No strategic country ID was introduced as an unsupported GoH tactical side.

## Resolved roster and research counts

| Actor | Units | Research nodes | Classification |
|---|---:|---:|---|
| Belarus | 36 | 50 | Proxy hybrid |
| Canada | 13 | 20 | National hybrid |
| Germany | 29 | 42 | Full national |
| Denmark | 55 | 64 | NATO coalition fallback |
| Donbas Forces | 52 | 70 | Separatist hybrid |
| North Korea | 28 | 37 | Eastern hybrid |
| Spain | 55 | 64 | NATO coalition fallback |
| Finland | 36 | 51 | National hybrid |
| France | 21 | 29 | National hybrid |
| United Kingdom | 33 | 44 | Full national |
| Italy | 19 | 27 | National hybrid |
| KPA Expeditionary Corps | 7 | 10 | Hosted auxiliary |
| Netherlands | 15 | 23 | National hybrid |
| Norway | 55 | 64 | NATO coalition fallback |
| Poland | 18 | 26 | National hybrid |
| People's Republic of China | 85 | 102 | Full national |
| Russia | 212 | 249 | Full national |
| Serbia | 24 | 35 | Balkan/Eastern hybrid |
| Sweden | 17 | 26 | National hybrid |
| Turkey | 55 | 64 | NATO coalition fallback |
| Ukraine | 185 | 227 | Full national |
| International Legion | 6 | 13 | Hosted volunteer force |
| United States | 74 | 93 | Full national |
| Wagner / Russian PMC Forces | 15 | 17 | Hosted PMC |

Every actor met its declared required category coverage in the audited snapshot.

## High-risk cases checked

### North Korea

The KPA pool resolves from the existing Code:X `kor_*` squads inside the Russian `2022vdv106` branch. North Korea adds an explicit West81 Soviet-pattern legacy heavy-equipment component. The same Korean squads remain available to the separately hosted KPA Expeditionary Corps under Russia.

### Ukraine International Legion

Six `goc_ildu_*` purchase wrappers reference the existing Code:X `nato_*` / `ildu` breeds. The audit confirmed every referenced breed exists. No breed, portrait, weapon, or model is copied into Gates of Code:X.

### Donbas

The native progression resolves from `2022rusldpr`. Five additional `goc_sparta_*` and `goc_vostok_*` wrappers reference existing latent `spd_*` and `vostok_*` breeds. Every referenced breed resolved.

### Belarus and Serbia

Both are explicitly labeled constructed hybrids. Belarus combines West81 Soviet legacy equipment with a filtered Russian modernization component. Serbia combines existing `Serb_*` personnel with the approved legacy pool. Neither is represented as a complete native Code:X faction.

### NATO countries

The audit separates US, British, German, French, Polish, Italian, Swedish, Finnish, Dutch, and Canadian identity from mixed NATO containers. Norway, Denmark, Spain, and Turkey remain visibly labeled coalition-fallback rosters rather than being presented as source-backed national Code:X armies.

## Automated checks completed

- Bundled manifest schema and exact actor set
- Supported tactical export sides only
- Required selector resolution
- Missing source unit failure behavior
- Existing upstream breed validation for virtual squads
- West81 legacy provenance preservation
- Deterministic output on repeated compilation
- Actor-scoped research keys
- Research prerequisite completeness
- Filtered-branch prerequisite reparenting
- Research graph cycle rejection
- Non-empty materializable rosters and research trees

## Live-stack acceptance command

The independent auditor must rerun against the current installed stack, not rely only on this snapshot:

```powershell
.\.venv\Scripts\gates-of-codex-factions.exe `
  --stack-config .\config\mod-stack.windows.json `
  --output .\docs\audits\resolved-factions.json `
  --summary .\docs\audits\resolved-factions.md
```

Expected acceptance condition:

```text
actor_count = 24
error_count = 0
warning_count = 0
```

A changed upstream stack may legitimately produce a new stack or wiring signature. Any change must be reviewed rather than blindly updating the checked-in report.
