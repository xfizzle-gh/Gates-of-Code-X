---
name: gates-authority-change
description: Implement or review Gates of CodeX authority-sensitive changes involving Earth3 maps, scenario bundles, save schemas, stable IDs, actor identity, mod-stack provenance, generated evidence, deterministic serialization, or fail-closed loaders. Do not use for ordinary presentation-only edits.
---

# Gates Authority Change

Use this workflow whenever a change touches data or code that decides what the application treats as canonical, trusted, stable, reproducible, loadable, or safe to mutate.

## 1. Name the authority explicitly

Before editing, identify:

- the governing issue and owner ruling;
- the authority owner and source location;
- exact source commit, file set, bytes, hashes, version, and schema when applicable;
- stable IDs, counts, ordering, topology, identities, and policy fields that must remain fixed;
- derived artifacts and the deterministic recipe that produces them;
- mutable runtime state that must not be confused with immutable initialization or provenance;
- the exact authorized change and all frozen neighboring surfaces.

Stop when the source of authority is ambiguous, unavailable, or contradicted by another accepted record.

## 2. Separate authority classes

Classify every touched value as one of:

1. **external source authority** — installed game/mod files, pinned public datasets, or captured engine evidence;
2. **repository immutable authority** — committed geometry, exact-byte bundles, stable IDs, approved hashes, manifests, and policy records;
3. **derived authority** — deterministically generated catalogs, projections, adjacency, manifests, reports, or signatures;
4. **initial scenario content** — starting ownership, actors, forces, objectives, sites, and rosters;
5. **mutable campaign state** — progress, casualties, positions, resources, completed objectives, and player choices;
6. **presentation data** — snapshots, labels, UI metadata, screenshots, and diagnostics.

Never regenerate mutable state from initialization data during load. Never promote presentation data or stale generated output into gameplay authority.

## 3. Authenticate inputs before interpretation

1. Resolve a canonical repository or configured root.
2. Reject paths that escape the approved root.
3. Reject missing files, duplicate roots, non-regular files, symlinks, junctions, reparse points, or path aliases when the governing contract forbids them.
4. Capture files consistently and detect mutation during capture when exact bytes matter.
5. Require strict UTF-8 and reject duplicate JSON keys, malformed records, unknown fields, and unsupported schema versions when the format is closed.
6. Verify exact hashes, identities, counts, ordering, and cross-file references before constructing runtime state.
7. Do not guess missing Workshop locations, source layers, include chains, national identity, or fallback data.

## 4. Preserve fail-closed behavior

- Missing or mismatched authority must produce a clear actionable error.
- Do not silently select a legacy scenario, old map, unrelated save, another Workshop item, cached artifact, or approximate record.
- Do not repair malformed authority during load unless the schema defines a narrow deterministic migration.
- Do not accept warnings when the governing contract requires a clean catalog.
- Do not bypass validation using call-stack inspection, temporary serialized flags, global construction tokens, monkeypatch-only production behavior, or hidden fallback paths.
- Complete all validation before atomically replacing an existing campaign, deployment, manifest, or published artifact.

## 5. Maintain identity and provenance

1. Preserve stable IDs and actor identity independently of broad tactical side, display label, or mutable ownership.
2. Bind generated artifacts to all inputs that materially affect behavior.
3. Recompute signatures from canonical logical content rather than trusting copied signatures embedded in payloads.
4. Exclude machine-specific absolute paths from portable logical provenance while retaining enough layer identity to detect changed content.
5. Record source commit, schema/version, recipe/config digest, source hashes, output hashes, and policy IDs where required.
6. Detect downgrade attempts that delete provenance markers while retaining authority-exclusive structural content.

## 6. Guarantee deterministic derivation

For generated or serialized output:

- define canonical ordering and normalization;
- avoid filesystem iteration order, locale, current time, random seeds, absolute paths, and platform-specific line endings unless explicitly part of the contract;
- run identical inputs more than once and compare output bytes;
- compare required Linux and Windows outputs when cross-platform parity is claimed;
- publish atomically only after validation;
- keep debug, prototype, candidate, and research artifacts isolated and non-default.

## 7. Write adversarial tests first

Cover the applicable threats:

- missing, extra, malformed, reordered, duplicated, or unknown fields;
- byte tampering and hash mismatch;
- stable-ID substitution, count mismatch, and cross-reference failure;
- path traversal, copied authority, symlink/junction/reparse substitution, and Windows 8.3 aliases;
- mutation during capture;
- duplicate roots or wrong product identity;
- stale cached files and generated-file self-ingestion;
- same-side actor swaps and identity downgrade;
- missing includes, conflicting definitions, cycles, and precedence ambiguity;
- legacy fallback or unrelated-template selection;
- nondeterministic repeated output;
- load/save round trips and backward-compatible migration;
- partial writes and preservation of the previous valid destination after failure.

Tests must assert the intended external contract independently rather than merely mirroring production constants.

## 8. Prove the boundary after implementation

1. Inspect the complete base-to-head diff and confirm frozen files are byte-identical where required.
2. Recompute and record hashes, counts, topology, signatures, and changed-file scope independently of the implementation under test.
3. Run focused adversarial tests, then the full authorized repository matrix.
4. Verify exact-head CI on every required platform and runtime.
5. Perform native acceptance when the authority depends on actual Gates of Hell, Steam Workshop, Windows filesystem, Godot editor, or installed-stack behavior.
6. State clearly which claims remain unproven without owner-machine or native-engine evidence.

## Stop immediately when

- the change requires modifying frozen geometry or stable IDs without explicit authorization;
- a candidate or research artifact would become production/default implicitly;
- the source stack or required external dataset is unavailable and the output would have to be fabricated;
- a correction passes tests but does not change the failing generated artifact;
- validation must be weakened to make existing data pass;
- the requested work crosses into an unapproved scenario, route, UI, packaging, faction, or roadmap phase.

## Required completion report

Report:

1. authority classification and governing record;
2. exact inputs, hashes, versions, policies, and stable identities;
3. changed and frozen files;
4. validation and migration behavior;
5. adversarial tests and deterministic comparisons;
6. exact-head CI and native evidence;
7. residual uncertainty, blockers, and explicit stop point.
