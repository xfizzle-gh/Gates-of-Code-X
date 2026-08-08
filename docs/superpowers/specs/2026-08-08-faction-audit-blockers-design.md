# Faction Audit Blockers Design

## Purpose

Correct the four blocking findings from independent audit issue #150 without weakening the compiler activation gate, copying upstream assets, modifying PRs #147 or #149, or changing the independent audit worktree. The implementation starts from PR #144 head `e17f516a888f6152f0cae922c01ba211db1adb77` on `fix/150-faction-audit-blockers`.

The accepted live result is exactly 24 actors, zero errors, and zero warnings against this ordered stack:

1. Vanilla
2. West81
3. Code:X
4. Code:X AI Overhaul
5. This Gates of Code:X worktree as the sole final Gates layer

## Confirmed Baseline and Root Causes

The correct five-layer stack reproduces 24 actors, 63 errors, and 38 warnings.

- Thirteen errors come from source scanners that recognize `vehicle(...)` and `entity(...)` but not numbered forms. The fallback then incorrectly treats the squad name as the entity identifier.
- Fifty errors and twenty warnings come from a narrow existence index that reads only loose `set/registry/unit.reg` and `entity/**/*.def`. The live stack also supplies definitions through packed `.def` files, other registries, explicit interaction declarations, inherited/control declarations, purchase-ready wrappers, and explicitly shaped strategic call-ins.
- Eighteen warnings come from valid multiline macros whose `name(...)` attribute is on a continuation line. The current line-oriented scanners start capture too late and lose their member composition.
- Fourteen effective PRC rows resolve from West81 while entering the modern `prc_regular` component.
- `config/mod-stack.windows.json` labels Workshop item `3700832981` as Gates even though its `mod.info` names `Imperium vs Xenos Conquest`.

## Considered Approaches

### 1. Typed effective-definition index and shared stateful parser — selected

Build one reusable parser for bounded GoH source entries and one typed, provenance-retaining `EffectiveDefinitionIndex`. Reuse existing catalog semantics and make every accepted definition form explicit. This addresses the audit defects without treating arbitrary references as definitions.

### 2. Widen the current regular expressions and existence set — rejected

This would fix numbered macros and could suppress known diagnostics, but it would lose definition kinds, shadowed candidates, terminal provenance, collision ambiguity, and packed definitions. It would also risk accepting arbitrary referenced strings.

### 3. Implement a complete general-purpose GoH engine parser — rejected

This would exceed the audit scope and duplicate engine behavior that the repository does not need. The selected parser is intentionally bounded to the source forms required by the catalog, compiler, and live stack.

## Shared Stateful GoH Entry Parser

A focused parser will replace the duplicated entry collection logic in `codex/catalog.py` and `faction_wiring_scan.py`. It will recognize existing block definitions and macro definitions without applying one broad regular expression to arbitrary files.

The scanner tracks:

- top-level brace and parenthesis depth;
- quoted strings, with parentheses and braces inside them ignored;
- the actual GoH comment forms present in the stack (`;` and `//` line comments);
- exact one-based line and column for every entry, token, and diagnostic;
- a bounded maximum token count, entry size, and nesting depth;
- the next proven top-level definition boundary for recovery.

It recognizes `vehicle`, `vehicle1`, `vehicle2`, through `vehicleN`, and the equivalent `entity` forms as the same macro family while preserving the exact macro spelling and ordinal in source evidence. Multiple numbered and unnumbered macros in one unit are retained in source order and deduplicated only where their exact semantic reference is identical. Existing block-form `{vehicle ...}` and `{entity ...}` definitions remain supported.

Macro starts may span lines before `name(...)` appears. Nested current-source macro and block syntax is captured until the balanced top-level close. Whitespace and comments cannot terminate an entry or create a false entry.

Malformed or unterminated input produces deterministic structured diagnostics containing source, line, column, parser state, and bounded captured text. Recovery begins only at the next token sequence proven to be a top-level definition, so a malformed entry cannot swallow a later valid entry. Malformed nested blocks are reported separately from an unterminated outer macro.

## Typed Definition and Reference Model

`EffectiveDefinitionIndex` is a shared service, not an untyped existence set.

### Candidate kinds

Each `DefinitionCandidate` has one of these kinds:

- `vehicle_entity`
- `purchase_unit_wrapper`
- `strategic_call_in`
- `interaction_object`
- `registry_alias`

Each candidate retains:

- exact identifier spelling;
- definition kind;
- layer name and numeric stack priority;
- source path and exact line/column or archive member location;
- packed versus loose origin;
- parser form that established the declaration;
- deterministic source order within its container;
- alias target, when applicable;
- complete shadowed/winning candidate chain.

The index retains all candidates, not only winners. Compiler lookups return a resolution record containing the original request, allowed kind, alias chain, winning candidate, terminal candidate, and all shadowed or ambiguous candidates.

### Explicit reference-kind matrix

| Reference syntax/context | Legal terminal candidate kind |
|---|---|
| Vehicle/entity macro or block reference | `vehicle_entity` |
| Purchase unit selector/reference | `purchase_unit_wrapper` |
| Strategic support, doctrine, or off-map action reference | `strategic_call_in` |
| Interaction-object reference | `interaction_object` |
| Registry alias used by any row above | `registry_alias` only while recursively resolving to that row's legal terminal kind |

No lookup uses a broad union merely because an identifier exists. Reference type comes from parsed source syntax and selector context. A call-in cannot satisfy a vehicle lookup, a vehicle cannot satisfy a strategic call-in lookup, and an interaction object cannot satisfy a purchase-unit lookup.

### Definition forms

Only explicit declaration shapes establish candidates:

- packed or loose `.def` declarations establish `vehicle_entity` candidates;
- explicit inherited/control declarations such as a named row with `inherit "vehicle ..."` establish a vehicle alias or entity candidate according to the declaration;
- purchase-ready unit rows establish `purchase_unit_wrapper` candidates;
- an existing catalog vehicle-wrapper shape with no explicit vehicle reference may also establish an implicit same-name `vehicle_entity`, matching the repository's current inference behavior;
- explicit `offmap_support` or `strategic_doctrine` declaration shapes with the required action syntax establish `strategic_call_in` candidates;
- named top-level interaction declarations establish `interaction_object` candidates;
- explicit registry alias rows establish `registry_alias` candidates.

Occurrences inside interaction bodies, actions, doctrine bodies, spawn expressions, includes, or ordinary vehicle references remain references. They do not establish candidates merely because the text contains an identifier.

## Identifier and Alias Resolution

Diagnostics and reports always preserve the original identifier spelling. Resolution first attempts an exact identifier match.

There is no global lowercasing and no identifier-specific exception. Case-insensitive equivalence exists only as indexed evidence:

- an explicit source alias may relate differently cased names;
- a unique case-insensitive `.def` file-stem match may create an explicit resolved alias candidate, retaining both spellings and the file-stem evidence;
- multiple case-folded candidates are a blocking ambiguity;
- unrelated case-folded identifiers receive no fallback.

Registry and source aliases resolve recursively with:

- cycle detection;
- dangling-target detection;
- a fixed bounded maximum depth;
- complete ordered alias-chain retention;
- original alias declaration provenance;
- terminal winning definition provenance.

Provenance policy uses the terminal definition winner. A Code:X alias terminating in a West81 definition is West81-backed for modern-only enforcement.

## Deterministic Precedence and Collisions

The index will document and test precedence rules already established by repository behavior rather than inventing an engine order.

- Later configured mod layers override earlier layers.
- The current catalog treats loose resource overlays as effective input. Packed archive indexing supplements those resources; packed and loose collisions are tested against this established loose-overlay behavior before the rule is encoded.
- Identical duplicate candidates at the same layer and effective priority may be deduplicated semantically while retaining every source candidate.
- Conflicting candidates at the same layer and effective priority are blocking ambiguities unless an existing include order, source order, or loader rule proves a winner.
- A sorted path is used for deterministic enumeration only, never as an unsupported semantic tiebreaker.
- Final Gates definitions override earlier Code:X definitions only through the proven later-layer rule.

Every ambiguity diagnostic includes the full candidate chain, exact locations, kinds, origins, and priorities. Tests cover packed versus loose definitions, multiple loose definitions, later versus earlier layers, final Gates versus Code:X, aliases, and inherited/control declarations.

## Compiler Integration

`SourceUnit` retains typed definition references alongside the existing serialized member, vehicle, and action fields. Parsing determines each reference type. Asset validation requests only the legal terminal kind from the matrix.

The old `_vehicle_index` set is replaced with `EffectiveDefinitionIndex`. Missing, dangling, cyclic, or ambiguous resolutions retain current selector severity semantics:

- required selector failures are errors;
- optional selector failures are warnings;
- valid optional references produce no warning;
- no result is silently accepted merely to reach the activation gate.

Packed archives are read deterministically with Python's standard ZIP support and are never extracted into the repository. Only relevant member metadata and bounded definition text are read.

## PRC Legacy / Reserve Provenance

`prc_regular` remains Code:X-authoritative and carries an enforced `modern_only` component policy. Terminal provenance backed by West81 is a blocking error in this component.

The new `prc_legacy_reserve` component contains exactly these fourteen independently audited West81-backed rows:

1. `artillery_barrage_light_prc`
2. `artillery_barrage_medium_prc`
3. `artillery_barrage_rocket_prc`
4. `artillery_barrage_smoke_prc`
5. `mortar_barrage_light_prc`
6. `mortar_barrage_medium_prc`
7. `mortar_barrage_smoke_prc`
8. `paradrop_supply_prc`
9. `ptl-02`
10. `t62_545`
11. `type80`
12. `ztz852`
13. `ztz853`
14. `ztz96a`

It is included for the PRC actor but remains separate from regular PLA research. Component metadata creates a visible research branch and generated-report label exactly named `PRC Legacy / Reserve Equipment`. Units retain their source-derived vehicle, artillery-action, mortar-action, and supply-call-in categories. Terminal provenance reports West81. No upstream file, model, texture, portrait, sound, weapon, entity, or definition is copied.

`docs/audits/faction-judgment-calls.md` records the source evidence, inference, confidence, and best alternative for this decision.

## Portable Windows Stack Configuration

`config/mod-stack.windows.json` remains checked in at its current path. It contains no machine-specific absolute paths and uses these explicit placeholders:

- `${GOH_VANILLA_ROOT}`
- `${WEST81_ROOT}`
- `${CODEX_ROOT}`
- `${CODEX_AI_OVERHAUL_ROOT}`
- `${GATES_CODEX_ROOT}`

The stack loader expands placeholders itself. JSON is never assumed to perform expansion. The loader fails closed for a missing variable, unresolved placeholder, nonexistent root, incorrect identity, duplicate normalized root, duplicate logical layer, wrong order, missing Vanilla sentinel, or unrelated Gates product. It never scans Workshop directories, guesses another path, or silently falls back.

Vanilla uses stable sentinel paths because it does not share the Workshop `mod.info` contract. West81, Code:X, AI Overhaul, and Gates use exact accepted product names or explicitly configured exact identity aliases read from `mod.info`; substring matching is prohibited. The current `3700832981` package, whose name is `Imperium vs Xenos Conquest`, is rejected as the Gates layer.

`GATES_CODEX_ROOT` may point to the active repository or worktree when its `mod.info` has an accepted Gates identity. Documentation provides PowerShell assignments for all five variables and a copy-paste example, but the current worktree's absolute path is not committed.

The configured order is exactly Vanilla, West81, Code:X, Code:X AI Overhaul, and Gates of Code:X, with Gates last.

## Test Design

All behavior is implemented test-first. Focused tests include the following.

### Stateful source parser

- `vehicle`, `vehicle1`, and `vehicle2` resolve identically;
- `entity`, `entity1`, and mixed numbered forms resolve identically;
- block-form vehicle/entity definitions remain supported;
- macros split across lines before `name(...)` retain members and references;
- nested current-source blocks and parentheses parse correctly;
- multiple numbered macros retain source order;
- actual GoH comments and whitespace are ignored safely;
- quoted parentheses and braces do not alter depth;
- malformed nested and unterminated entries report exact line/column;
- recovery preserves the next valid top-level definition;
- malformed-input diagnostics are deterministic.

### Effective definition index

- exact identifier match;
- explicit source-proven case alias;
- unique file-stem alias represented explicitly;
- ambiguous case collision is blocking;
- unrelated case-fold fallback is rejected;
- packed `.def` vehicle resolves;
- loose `.def` vehicle resolves;
- packed-versus-loose precedence follows the proven repository rule;
- identical same-layer duplicates retain all candidates;
- conflicting same-layer candidates are ambiguous without a proven order;
- later mod layer overrides earlier layer;
- final Gates definition overrides Code:X;
- purchase wrapper, call-in, interaction, registry, and inherited/control declarations retain distinct kinds;
- explicit interaction declaration establishes an interaction object;
- interaction reference alone does not establish existence;
- call-in cannot satisfy a vehicle lookup;
- vehicle cannot satisfy a call-in lookup;
- alias chains retain alias and terminal provenance;
- alias cycles, dangling targets, and depth overflow fail;
- terminal West81 provenance remains West81 through a Code:X alias;
- full candidate chains and collision reports are deterministic.

### Compiler and provenance integration

- valid inherited entity resolves;
- valid interaction object resolves in its legal context;
- valid strategic call-in resolves in its legal context;
- genuinely missing entity fails;
- optional selector produces a warning;
- required selector produces an error;
- all thirteen numbered-macro false errors disappear;
- all fifty incomplete-index false errors disappear;
- all thirty-eight reproduced warnings disappear through valid parser/index resolution;
- West81 content cannot enter a modern-only component;
- `prc_legacy_reserve` contains exactly the fourteen approved rows;
- every approved row reports West81 terminal provenance and the correct category;
- the visible research/report branch label is exact.

### Windows stack configuration matrix

- successful environment-variable expansion;
- missing variable rejected;
- unresolved placeholder rejected;
- nonexistent root rejected;
- incorrect `mod.info` identity rejected;
- duplicate logical layer or normalized root rejected;
- incorrect layer order rejected;
- Vanilla sentinel validation succeeds and fails appropriately;
- active worktree accepted as the final Gates layer;
- unrelated Workshop package `3700832981` rejected;
- no silent path fallback or Workshop guessing occurs.

## Acceptance and Verification

Before commit or push, run fresh verification and preserve correction-validation outputs under distinct names.

1. Run the complete repository test suite.
2. Run focused parser, index, provenance, configuration, campaign, actor, economy, and tactical preflight tests.
3. Run the live compiler twice using the five explicit environment variables, with this worktree as the sole final Gates layer.
4. Require `actor_count = 24`, `error_count = 0`, and `warning_count = 0` on both runs.
5. Compare the two JSON files byte-for-byte.
6. Compare the two Markdown files byte-for-byte.
7. Confirm all fourteen `goc_*` national wrappers remain materializable.
8. Confirm `kor_crew`, `fr_spotter`, and `rus114_marksman` final overrides resolve and remain valid.
9. Confirm Code:X Core remains inherited and unchanged.
10. Confirm no canonical Code:X conquest file was copied or destructively overridden.
11. Confirm no validation bypass, warning suppression, or activation-gate weakening was introduced.

If the live result differs from 24 actors, zero errors, and zero warnings, implementation stops and reports the remaining diagnostics.

## Delivery

Commit implementation to `fix/150-faction-audit-blockers`, push the branch, do not merge, and post a concise implementation report to issue #150. Report the commit SHA, exact files changed, tests and results, live compiler counts, deterministic comparisons, remaining blockers, the precise PRC reserve decision, and the stack-configuration correction.
