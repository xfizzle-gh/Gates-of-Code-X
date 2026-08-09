---
name: gates-pr-gate
description: Govern Gates of CodeX issue, branch, pull-request, exact-head review, CI, and merge work. Use for implementing scoped GitHub issues, preparing or auditing PRs, checking CI, responding to reviews, or merging. Do not use for native Gates of Hell acceptance runs; use gates-native-acceptance instead.
---

# Gates PR Gate

Apply this workflow to every repository change unless the owner gives a narrower written procedure. Preserve the repository's exact-head, independent-review, deterministic-evidence, and phase-boundary rules.

## 1. Establish authority before editing

1. Read the governing issue, parent issue, active PR, and any owner ruling referenced by them.
2. Fetch the live default-branch head and record the exact base commit SHA.
3. State the authorized scope, explicitly excluded adjacent work, required tests, required native acceptance, and stop conditions.
4. Resolve contradictions in favor of the newest explicit owner ruling. Stop and ask for direction when authority remains ambiguous.
5. Never infer permission to begin the next ordered phase merely because the current phase appears complete.

## 2. Isolate the work

1. Create a dedicated branch or worktree from the exact authorized base.
2. Record the branch name, base SHA, initial head SHA, and clean status before mutation.
3. Do not reuse a branch containing unrelated implementation, generated files, local evidence, or another phase's work.
4. Keep user data, Workshop files, game saves, logs, caches, virtual environments, Godot imports, and local editor state out of Git.

## 3. Implement only the approved slice

1. Prefer the smallest coherent diff that satisfies the issue.
2. Add adversarial regression coverage for the changed authority boundary, not only happy-path tests.
3. Preserve fail-closed behavior, deterministic serialization, stable identities, provenance, and backward compatibility unless the issue explicitly changes them.
4. Do not weaken validation, bypass verification, silently fall back to legacy behavior, mass-enable candidates, or create a second source of truth.
5. Do not mix refactors, formatting sweeps, generated artifacts, dependency updates, or adjacent roadmap work into the PR.
6. Treat an interrupted or transport-unknown write as unknown. Inspect repository state before retrying.

## 4. Verify the exact head

1. Inspect `git status`, the base-to-head filename list, diff statistics, and the complete base-to-head diff.
2. Confirm every changed file belongs to the approved scope and no frozen or generated file changed accidentally.
3. Run only the tests and checks authorized by the governing issue or owner instruction.
4. Report tests as one of: authored but not run, run locally, run in CI, or live-engine accepted. Never collapse these evidence levels.
5. Associate every CI claim with the exact PR head SHA and workflow run. A green run for an earlier head is not evidence for the current head.
6. Inspect all required jobs, not only the aggregate status. Record run ID, job IDs, platform/runtime matrix, test counts when available, expected skips, and failures.
7. If the head changes after review or CI, treat prior exact-head acceptance as stale unless the reviewer explicitly accepts the new head.

## 5. Publish a draft PR

Create or update a draft PR containing:

- governing issue and parent dependency;
- exact base SHA, exact current head SHA, branch, draft/merge state, and changed-file count;
- concise implementation summary;
- explicit scope exclusions and untouched phases;
- tests authored and tests actually executed;
- exact-head CI run and job evidence, or a clear statement that CI has not been inspected;
- native acceptance status when applicable;
- known limitations, blockers, migration exceptions, and follow-up work;
- independent-review requirement and stop point.

Do not mark the PR ready merely because CI is green.

## 6. Independent exact-head review

1. Obtain independent review of the full base-to-head diff at the exact current head.
2. Resolve or explicitly disposition every review thread and blocking comment.
3. Re-run required verification after corrections.
4. Record the accepted exact head and review evidence in the PR or governing issue.
5. Keep the PR draft and unmerged until the repository's owner-authorized gate is satisfied.

## 7. Merge safely

Merge only when all of the following are true:

- the owner or governing process explicitly authorizes merge;
- the accepted head still equals the live PR head;
- all required CI jobs pass for that head;
- required native acceptance passes;
- blocking threads and issues are resolved;
- the next phase has not been mixed into the branch.

Use expected-head protection when merging. Never enable auto-merge or mark a draft ready without explicit authorization. After merge, record the resulting merge commit before creating the next ordered branch.

## Stop immediately when

- the live base differs from the required base;
- the requested change would alter frozen geometry, stable IDs, authority bytes, stack validation, or verification policy without explicit permission;
- implementation requires mass-enabling candidate routes or content;
- a native failure lacks sufficient source or runtime evidence;
- tests, CI, review, or acceptance belong to a different head;
- the work would cross into an unapproved phase;
- repository state is dirty or contains unrelated changes that cannot be safely separated.

## Required completion report

Report:

1. repository and branch;
2. exact base and exact head;
3. changed files and scope summary;
4. tests/checks by evidence level;
5. CI run/job evidence;
6. review and native-acceptance state;
7. blockers and stop point;
8. PR link and whether it remains draft/unmerged.
