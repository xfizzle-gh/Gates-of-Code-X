---
name: gates-native-acceptance
description: Run and document Gates of CodeX native Windows, Steam, Godot, or Gates of Hell acceptance against the exact installed mod stack. Use for live-engine validation, wrapper spawning, tactical handoff, actor activation, installer smoke, or owner acceptance. Do not edit implementation during an acceptance-only run.
---

# Gates Native Acceptance

Use this skill when repository tests are insufficient and behavior must be proven in the real Windows, Godot, Steam, or Gates of Hell environment. Native acceptance is evidence collection, not an implementation session.

## 1. Freeze the acceptance target

1. Read the governing issue and implementation PR.
2. Record the exact repository commit SHA under test. Confirm the worktree or deployment source resolves to that commit.
3. Record the game build, Godot version when relevant, Python version, executable/package version, profile path, and test-machine time zone.
4. Record the exact acceptance matrix and pass/fail criteria before launching anything.
5. Do not test a moving branch. If the implementation head changes, start a new acceptance record.

## 2. Validate the canonical stack

Resolve and record these layers in this order, lowest to highest priority:

1. Vanilla Gates of Hell
2. West81
3. Code:X
4. Code:X AI Overhaul
5. Gates of Code:X at the exact audited checkout, worktree, or dedicated deployment

For every layer record:

- canonical absolute path;
- existence and directory identity;
- expected product or `mod.info` identity;
- Workshop item identity when applicable;
- relevant file count or stack signature when the governing test requires it.

Use the repository's stack validator. Never guess a Workshop directory, silently substitute another package, accept duplicate roots, or deploy into an unrelated Workshop item. Use an explicit dedicated disposable target for deployment tests.

## 3. Prepare a clean test state

1. Preserve the original user profile, saves, configuration, and live deployment with backups where the repository procedure requires them.
2. Create a brand-new disposable campaign, save, wrapper battle, or actor activation unless the test explicitly requires continuation of a bound campaign.
3. Remove or rule out stale generated files, prior actor projections, old snapshots, unrelated enabled mods, and cached test state.
4. Record the exact command lines and environment variables used.
5. Confirm the generated artifact is bound to the intended campaign, pending battle, actor, map, stack, and source commit.

## 4. Capture pre-run evidence

Before launch retain:

- stack validation output;
- source commit and deployment manifest;
- generated campaign, scenario, save, roster, research, or wrapper artifacts required by the test;
- checksums or signatures required by the governing contract;
- visible dependency list or generated `{mods}` block when testing tactical handoff;
- clean log start boundary.

Do not modify generated evidence by hand unless the issue explicitly defines a diagnostic experiment. Clearly label any manually altered artifact as diagnostic and non-accepting.

## 5. Execute the approved matrix

1. Follow the issue's actor, faction, wrapper, map, campaign, or battle order exactly.
2. Perform every required player-visible step, including load, purchase, spawn, movement, launch, battle completion, verification, import, save, close, and reopen where applicable.
3. Record each matrix row independently. A grouped run may cover several rows, but every required row needs an explicit result.
4. Capture screenshots where they prove visible state, while retaining machine-readable logs and artifacts as primary evidence.
5. Do not continue past an issue-defined blocker or stop condition.

## 6. Capture post-run evidence

Retain the complete unedited evidence package appropriate to the run:

- full `game.log`, Godot/editor logs, installer output, and application diagnostics;
- generated runtime file surrounding any failing line;
- screenshots of required visible states;
- save and manifest identities;
- actual spawned counts, resolved units, side/actor identity, or imported casualties;
- before/after checksums when deterministic replacement or restoration is under test;
- exact reproduction steps and timestamps.

Never quote only the final error line when include chains, generated source, adjacent entries, or stack provenance are needed to identify the real failing authority.

## 7. Classify the result honestly

Use these evidence labels precisely:

- **system implemented**: code exists;
- **fixture demonstrated**: controlled fixture path works;
- **automated integration proven**: repository or CI integration passes;
- **native engine accepted**: exact installed stack passed the real application or game;
- **live player path accepted**: the owner completed the documented end-to-end player flow without manual repair.

Automated tests, synthetic results, parsed source files, screenshots alone, or a manually sanitized diagnostic save do not prove native acceptance of the normal path.

## 8. Handle failures without contaminating evidence

When a native test fails:

1. Stop the acceptance sequence at the governing gate.
2. Preserve the failing state and all evidence before attempting cleanup.
3. Identify what is known, what is inferred, and what remains unproven.
4. Do not edit implementation files on the acceptance branch or during an acceptance-only run.
5. Create or update a focused blocker with the exact commit, stack, reproduction, artifacts, failing line/token, and required next evidence.
6. Reject corrections whose generated runtime outputs or authoritative evidence do not actually change.
7. Resume only from a new exact implementation head after focused and full verification are complete.

## Required acceptance report

Report:

1. governing issue/PR and exact tested commit;
2. game, Godot, Python, package, and machine context;
3. all five resolved stack layers and identities;
4. preparation and exact commands;
5. matrix rows with pass/fail and observed values;
6. logs, screenshots, artifacts, and hashes retained;
7. manual interventions attempted or required;
8. evidence classification;
9. blocker and next required evidence, or final native verdict.
