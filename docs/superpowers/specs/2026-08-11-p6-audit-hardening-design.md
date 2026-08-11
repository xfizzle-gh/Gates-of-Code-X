# P6 Audit Hardening Design

## Status and authority

This design corrects the six blocking findings in the independent audit of PR
#216 at `7fe06057ce8d305e785564105ea602815a36b523` and completes the already
required Godot Restore Backup and Reset Test Campaign controls. The governing
records are issue #215 and parent issue #176. The authorized base remains
`e5ab071fb4b07311d5fdeaf42c5b443bf525a481`; the correction remains one coherent
draft PR and must not be marked ready or merged before a new exact-head audit.

The authority classes touched by this correction are:

- repository immutable authority: exact source commit, committed Earth3 assets,
  P3 graph/allowlist, P5 stack and handoff verification contracts;
- derived authority: installed package provenance, frontend snapshots, backup
  manifests, tactical handoff artifacts, and Godot presentation state;
- mutable campaign state: campaign save, command ledger, operational orders,
  pending battle, and imported tactical result;
- presentation data: application identity, authenticated backup availability,
  control enablement, status messages, and headless Godot evidence.

Frozen neighboring surfaces are P1-P3 geometry, stable province/route IDs,
scenario authority, P5 stack ordering, handoff identity, Verify/Import gates,
and the accepted #213 turn-cycle behavior. The correction will not widen the
Earth3 route allowlist, introduce legacy GoE fallback, change tactical result
verification, or include Expanded Nations, OpenGS, S11 Fog, NORESUS, geography,
or unrelated performance work.

## Selected approach

Harden the existing P6 seams in place. The alternative of introducing a new
backup schema and migration layer adds unnecessary authority and compatibility
surface. Splitting packaging, restore, UI, and integration into separate PRs
would prevent one exact head from proving P6 and contradict the approved #216
re-audit sequence.

The implementation will keep `src/gates_of_codex/packaging.py` as the boundary
for package identity and managed campaign maintenance, strengthen
`frontend_commands.py` at self-committing lifecycle boundaries, extend the
existing Godot management panel rather than create a second UI state model, and
replace the current shortcut test with one production-seam integration proof.

## Build and packaged provenance

Source/development runs may resolve the exact commit from a clean Git checkout.
Packaged and installed runtimes must resolve provenance only from a commit stamp
embedded inside the installed `gates_of_codex` package. They must not depend on
an environment variable, repository-root stamp, current working directory, or
ambient Git executable.

The installer will perform these steps before installing or invoking
PyInstaller:

1. Resolve the exact checkout commit with `git rev-parse HEAD`.
2. Reject the build if `git status --porcelain --untracked-files=no` reports any
   tracked staged, unstaged, deleted, or conflicted change. Untracked files do
   not change the claimed tracked source tree and are excluded from this gate.
3. Create a temporary `SOURCE_COMMIT` package-data input containing the exact
   lowercase 40-character commit plus a newline.
4. Install the package with that file included beside `packaging.py`.
5. Build each PyInstaller executable with the same file included in the frozen
   `gates_of_codex` package data.
6. Remove the temporary source-tree stamp in a `finally` path so generated build
   material is never committed.
7. Launch the installed venv entry point and each built executable in a smoke
   check that resolves and prints the embedded exact commit.

Runtime resolution distinguishes a source checkout from an installed/frozen
runtime. An installed or frozen runtime with a missing, malformed, or
non-40-character embedded stamp fails closed. A source/development checkout may
fall back to Git even though the build command separately refuses to package a
dirty tracked tree. Environment injection remains available only as an explicit
test seam and cannot override an embedded packaged identity in production
resolution.

The frontend application block will no longer catch all provenance failures and
publish blank fields. Snapshot creation must carry the exact full commit and
short display form or fail with an actionable packaging error. The Godot
management panel will visibly render the full 40-character commit, while the
snapshot records both the full and short forms.

## Campaign-bound backup discovery

Backup discovery is presentation data derived from authenticated manifests; it
never becomes campaign authority. The backend scans only the managed backups
root, rejects symlinks, junctions, reparse points, non-regular manifests, path
aliases, malformed JSON, and manifests whose recorded backup directory does not
canonically equal the directory containing that manifest.

A backup is eligible for the current campaign only when:

- its campaign authority destination is exactly the selected canonical
  `campaign.json`;
- every other destination is in the same exact campaign directory;
- every destination name is one of `campaign.json`,
  `campaign_snapshot.json`, or `frontend_commands.json`;
- every saved source is a regular, non-reparse file directly inside the selected
  backup directory;
- there are no duplicate destinations, duplicate sources, aliases, missing
  sources, or extra filenames;
- `campaign.json` is present exactly once.

The latest eligible backup is selected deterministically by manifest timestamp,
then canonical directory name as a stable tie-breaker. The frontend snapshot
exposes only this authenticated campaign-bound backup descriptor. If no eligible
backup exists, Restore is disabled.

## Transactional restore

Restore preflights every manifest entry and constructs an immutable restore plan
before writing anything. The plan binds the selected backup, exact current
campaign directory, exact known destination set, and canonical source files.

Execution uses sibling directories on the same volume:

1. Create a unique staging directory beside the campaign directory.
2. Copy the complete restored known-file set into staging. Optional files absent
   from the backup remain absent, preventing stale snapshot or command-queue
   material from surviving.
3. Load and validate the staged `campaign.json` through the normal campaign
   loader before publication.
4. Capture byte hashes for every existing file in the current campaign
   directory and reject unexpected files.
5. Rename the current campaign directory to a unique rollback sibling.
6. Rename staging to the exact campaign directory.
7. If publication fails after step 5, restore the rollback directory to the
   original exact path before reporting failure.
8. After successful publication, remove the rollback sibling and return
   canonical restored paths.

No sequential copy is allowed into the live campaign directory. Staging and
rollback cleanup occurs only after their resolved absolute paths are verified as
siblings of the exact managed campaign directory. The Windows adversarial test
will inject a failure during the second directory replacement and assert that
the original directory path, filenames, and bytes are identical to a pre-call
capture.

## Restore command ledger semantics

`restore_backup` remains a self-committing command and must be submitted alone.
After the directory transaction succeeds, `apply_frontend_commands()` discards
its pre-restore state, command ledger, and observation context. It reloads the
restored campaign and its restored ledger, records only the successful restore
command ID into that restored timeline, saves atomically, and regenerates the
frontend snapshot from the restored campaign.

Command IDs that existed only in the abandoned future timeline therefore do not
survive. A regression will create a backup, apply a later command ID, restore the
backup, and prove that the same later command ID is accepted again while the
restore command itself is recorded exactly once.

## Reset semantics

`reset_test_campaign` remains self-committing, campaign-bound, and limited to
the exact managed directory and known product files. It optionally creates an
authenticated backup first. A successful reset deletes the campaign directory
and returns a lifecycle result explicitly declaring `campaign_deleted: true`
and `next_player_state: new_campaign`.

The frontend command layer will not reload, save, ledger, or regenerate a
snapshot after deletion. Godot will discard the stale snapshot-derived campaign
model, clear pending selection/handoff state, and show the clean New Campaign
surface. It must not try to refresh the deleted campaign.

## Godot controls and lifecycle

The existing management panel gains:

- `Restore Latest Backup`, enabled only when write-back is available, the
  authenticated backup descriptor is present, no battle/presentation blocks
  mutation, and no command is busy;
- `Reset Test Campaign`, enabled under the same mutation guards except backup
  availability is not required.

Each action requires a second click. The first click changes only local
confirmation state and label. Any other action, snapshot reload, or command
start cancels the pending confirmation. While the command runner is busy, both
buttons and their hit-test exposure are disabled.

Restore submits the exact authenticated backup directory from the current
snapshot. On success Godot discards the pre-command snapshot, loads the freshly
generated restored snapshot, clears stale selections and tactical handoff UI,
and redraws from restored state. On failure it retains the prior valid snapshot
and reports the backend error.

Reset submits no caller-selected filesystem path. On success Godot clears the
campaign snapshot and mutation state and transitions to New Campaign. On
failure it retains the prior valid snapshot. Headless Godot contract tests cover
enablement, both confirmation clicks, busy disabling, no-backup disabling,
restore reload, and reset-to-new lifecycle.

## Automated golden path

The current S10 prepared-contact shortcut is removed as P6 proof. The replacement
test performs the required production chain:

1. Build a filesystem fixture stack with the intended validated layer roles and
   run the production stack validator successfully.
2. Create a production `earth3_v1` campaign through the player-shell creation
   path using that validated stack, preserving stack signature/config metadata.
3. Generate the production frontend snapshot and pass its actual file path to a
   headless Godot contract check that loads the real player scene and asserts
   Earth3 identity, exact commit display data, and actionable controls.
4. Select a real offered P3 graph route, issue the operational order through
   `apply_frontend_commands()`, and commit it through the authoritative campaign
   path.
5. Invoke the installed #213 `end_player_round` operation and require success,
   real player-seat advancement, and real AI path execution.
6. Continue legal operational orders/rounds through campaign logic until the
   authenticated route produces a real pending battle. The test may choose a
   deterministic approved opening sequence, but may not assign
   `pending_battle`, call a prepared-contact test helper, or fabricate completed
   operational state.
7. Invoke the real P5 handoff service against a filesystem Gates of Hell fixture
   and exact validated fixture stack. Assert the generated save/manifest bind
   the campaign, real pending battle, map, visible save name, and exact stack.
8. Only after the genuine handoff exists, write a synthetic completed tactical
   result in the generated save and run the real Verify operation.
9. Import through the real verified Import gate and assert the pending battle is
   cleared exactly once.
10. Reload the campaign from disk, request fresh operational options, execute a
    subsequent valid strategic action, save, and reload again.

The proof may use test-owned filesystem fixtures for the external game and mod
stack, but it may not bypass stack validation, Earth3 construction, operational
movement/contact, handoff generation, result verification, import, or Godot
snapshot consumption.

## Test strategy

Every behavior change follows red-green-refactor. Focused coverage includes:

- Windows canonical path equality for returned restored paths;
- clean checkout build acceptance and dirty tracked checkout rejection;
- installed package and PyInstaller embedded provenance without environment
  injection;
- missing/malformed packaged stamp failure;
- visible full commit in the Godot management panel and headless contract;
- backup manifest source escape, destination escape, wrong campaign, wrong
  filename, duplicate/aliased path, symlink/reparse, missing source, and malformed
  manifest rejection;
- injected Windows directory-publication failure with byte-identical rollback;
- restored ledger timeline replacement and restore exactly-once recording;
- Restore/Reset confirmation, busy, availability, success, and failure lifecycle;
- the complete production-seam golden path and post-import continuation.

Focused tests run before the authorized repository matrix. The final local gate
includes the full Python partition verification, both supported local Python
runtimes when available, PowerShell installer/package smokes, and Godot headless
checks. CI evidence must belong to the single new PR head and include every
Windows/Linux Python shard, Windows executable job, and Godot job.

## Completion and stop point

After local verification, the correction is committed and pushed to the existing
`feat/p0-p6-golden-path` PR branch as one new #216 head. PR #216 remains draft and
unmerged. Exact-head CI must be green, then a fresh independent audit must accept
that exact SHA. The packaged owner-native Windows/Gates of Hell run follows as a
separate acceptance-only gate using the native-acceptance workflow. No result
from `7fe06057ce8d305e785564105ea602815a36b523` carries forward.
