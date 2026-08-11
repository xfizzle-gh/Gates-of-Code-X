# P6 Audit Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make draft PR #216 prove clean packaged provenance, authenticated transactional campaign maintenance, correct Godot Restore/Reset lifecycle, and the complete production-seam Earth3 golden path on one exact head.

**Architecture:** `packaging.py` remains the fail-closed boundary for installed identity and managed campaign maintenance; build scripts supply immutable package data before installation or freezing. `frontend_commands.py` reloads mutable authority at self-committing boundaries, while the existing Godot writeback client renders only authenticated backend capabilities. The integration proof creates an Earth3 campaign through the player shell, reaches contact through real graph/AI operations, produces the real handoff, then alone synthesizes the tactical completion.

**Tech Stack:** Python 3.11/3.13, `unittest`, PowerShell 7/Windows PowerShell, PyInstaller, Godot 4 headless GDScript, GitHub Actions, Git/GitHub CLI.

## Global Constraints

- Keep all corrections on draft PR #216; do not split, mark ready, merge, or change its base.
- Preserve the authorized base `e5ab071fb4b07311d5fdeaf42c5b443bf525a481` and frozen P1-P5/#213 authority surfaces.
- Do not widen the Earth3 route allowlist or alter stable IDs, stack ordering, handoff identity, Verify/Import gates, geography, fog, or unrelated performance behavior.
- Source runs may resolve Git provenance; installed/frozen runs require the embedded lowercase 40-character `SOURCE_COMMIT` and fail closed without it.
- Packaging must reject any tracked staged, unstaged, deleted, or conflicted change; ignored/untracked build material is not part of that test.
- Restore must preflight every manifest entry, publish by sibling directory replacement, and restore byte-identical original state after an injected Windows publication failure.
- Restore reloads the restored state and ledger before recording the restore command; Reset never reloads or snapshots the deleted campaign.
- Restore and Reset require a second click and are disabled while busy; Restore additionally requires an authenticated backup bound to the current campaign.
- The pending battle must arise through real operational campaign logic. Synthetic tactical output is permitted only after the production handoff is generated and verified.
- The generated production snapshot must be consumed by Godot headless, not merely parsed by Python.

## File map and boundaries

- `tools/stamp_package_provenance.ps1`: the only build-time clean-tree check and stamp writer.
- `src/gates_of_codex/SOURCE_COMMIT`: ignored generated package-data input; never committed.
- `src/gates_of_codex/packaging.py`: installed/source identity distinction, authenticated backup plans, latest-backup discovery, transactional restore/reset.
- `src/gates_of_codex/player_shell.py`: atomic clearing of the launcher-only last-campaign pointer.
- `src/gates_of_codex/frontend.py`: fail-closed application identity and authenticated backup presentation.
- `src/gates_of_codex/frontend_commands.py`: self-committing restore/reset lifecycle and restored-ledger rebinding.
- `godot/scripts/main_stack_panel.gd`: visible full commit and maintenance controls.
- `godot/scripts/main_writeback.gd`: two-click confirmations, busy/availability gates, restored snapshot replacement, reset-to-new lifecycle.
- `src/gates_of_codex/turn_cycle.py`: synchronize P2 actor runtime after every canonical seat transition.
- `tests/test_p6_golden_path.py`: one complete production-seam P6 proof; no prepared-contact helper.

---

### Task 1: Embed truthful provenance before every install and freeze

**Files:**
- Create: `tools/stamp_package_provenance.ps1`
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Modify: `src/gates_of_codex/packaging.py`
- Modify: `tools/install_gates_of_codex.ps1`
- Modify: `.github/workflows/gates-of-codex.yml`
- Modify: `.github/workflows/release.yml`
- Test: `tests/test_p6_packaging.py`

**Interfaces:**
- Produces: `resolve_source_commit(*, root: str | Path | None = None, environ: Mapping[str, str] | None = None) -> str`, where an adjacent stamp wins and an environment value is only a source-test seam.
- Produces: PowerShell output object `{ Commit: string, StampPath: string }`; the stamp path is always `src/gates_of_codex/SOURCE_COMMIT`.
- Consumes: the same stamp in wheel/venv package data and PyInstaller `--add-data` input.

- [ ] **Step 1: Replace provenance tests with packaged/source authority tests**

Add these cases to `PackagingProvenanceTests` and remove the test that makes the environment authoritative:

```python
def test_adjacent_package_stamp_wins_without_git_or_environment(self) -> None:
    commit = "a" * 40
    with tempfile.TemporaryDirectory() as temporary:
        package = Path(temporary) / "gates_of_codex"
        package.mkdir()
        write_source_commit_stamp(package / "SOURCE_COMMIT", commit)
        with mock.patch("gates_of_codex.packaging.subprocess.run") as run:
            self.assertEqual(commit, resolve_source_commit(root=package, environ={}))
            run.assert_not_called()

def test_installed_package_missing_or_malformed_stamp_fails_closed(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        package = Path(temporary) / "gates_of_codex"
        package.mkdir()
        with self.assertRaises(PackagingError):
            resolve_source_commit(root=package, environ={})
        (package / "SOURCE_COMMIT").write_text("dirty\n", encoding="ascii")
        with self.assertRaises(PackagingError):
            resolve_source_commit(root=package, environ={})

def test_source_checkout_without_stamp_uses_git(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "pyproject.toml").write_text("[project]\nname='probe'\n", encoding="utf-8")
        (root / ".git").mkdir()
        completed = subprocess.CompletedProcess([], 0, stdout="b" * 40 + "\n")
        with mock.patch("gates_of_codex.packaging.subprocess.run", return_value=completed):
            self.assertEqual("b" * 40, resolve_source_commit(root=root, environ={}))
```

Import `subprocess` and `from unittest import mock`. Add a Windows-only subprocess test that initializes a temporary Git repository, commits a tracked file, invokes the stamp script successfully, changes the tracked file, invokes it again, and asserts nonzero exit plus `tracked working tree is dirty`.

- [ ] **Step 2: Run the provenance tests red**

Run:

```powershell
python -m unittest tests.test_p6_packaging.PackagingProvenanceTests -v
```

Expected: FAIL because a package-shaped directory without a stamp currently falls through and because the stamp helper does not exist.

- [ ] **Step 3: Add the clean-tree stamp helper**

Create `tools/stamp_package_provenance.ps1` with this complete contract:

```powershell
[CmdletBinding()]
param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path -LiteralPath $Root).Path
$git = Get-Command git -ErrorAction Stop
$dirty = @(& $git.Source -C $resolvedRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw "Unable to inspect tracked working tree." }
if ($dirty.Count -ne 0) { throw "Refusing package build: tracked working tree is dirty." }
$commit = ((& $git.Source -C $resolvedRoot rev-parse HEAD) | Out-String).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
    throw "Unable to resolve a full Git commit."
}
$stampPath = Join-Path $resolvedRoot "src\gates_of_codex\SOURCE_COMMIT"
[System.IO.File]::WriteAllText($stampPath, "$commit`n", [System.Text.Encoding]::ASCII)
[pscustomobject]@{ Commit = $commit; StampPath = $stampPath }
```

Add `/src/gates_of_codex/SOURCE_COMMIT` to `.gitignore` and add `"SOURCE_COMMIT"` to `tool.setuptools.package-data.gates_of_codex` in `pyproject.toml`.

- [ ] **Step 4: Make runtime provenance distinguish source from installed/frozen layout**

In `packaging.py`, implement these exact rules:

```python
def _is_source_checkout(root: Path) -> bool:
    return (root / "pyproject.toml").is_file() and (root / ".git").exists()

def resolve_source_commit(*, root=None, environ=None) -> str:
    root_path = package_root(root)
    marker = root_path / PROVENANCE_FILE_NAME
    if marker.is_file():
        value = marker.read_text(encoding="utf-8-sig").strip().lower()
        if not _is_commit_sha(value):
            raise PackagingError(f"{marker} must contain a 40-character lowercase hex commit")
        return value
    if not _is_source_checkout(root_path):
        raise PackagingError(f"Installed package is missing embedded {PROVENANCE_FILE_NAME}: {root_path}")
    test_value = str((os.environ if environ is None else environ).get(PROVENANCE_ENV, "")).strip().lower()
    if test_value:
        if not _is_commit_sha(test_value):
            raise PackagingError(f"{PROVENANCE_ENV} must be a 40-character lowercase hex commit")
        return test_value
    completed = subprocess.run(
        ["git", "-C", str(root_path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    value = completed.stdout.strip().lower()
    if not _is_commit_sha(value):
        raise PackagingError(f"git rev-parse returned a non-commit value: {value!r}")
    return value
```

Adjust `package_root()` so explicit roots are returned unchanged, a repository module resolves to the repository root, and an installed/frozen module resolves to its `gates_of_codex` package directory. Preserve `PackagingError` wrapping for missing Git in a source checkout.

- [ ] **Step 5: Stamp before install/freeze and remove in finally paths**

In `tools/install_gates_of_codex.ps1`, invoke the helper before `pip install .`, retain the returned commit, pass `--add-data "src\gates_of_codex\SOURCE_COMMIT;gates_of_codex"` to both PyInstaller builds, smoke the installed CLI and built executables through the existing identity/snapshot path, then remove only the resolved generated stamp in `finally`.

In both workflows, add a PowerShell stamp step before package install and PyInstaller, add the same `--add-data` argument, expose the exact stamp SHA to later smoke assertions, and delete the generated stamp with `Remove-Item -LiteralPath src\gates_of_codex\SOURCE_COMMIT -Force` in an `if: always()` cleanup step.

- [ ] **Step 6: Prove installed runtime independence**

Extend `test_p6_packaging.py` with a subprocess smoke that builds a wheel from a copied clean fixture containing a stamp, installs it in a temporary venv, launches Python with `cwd` outside the source, `PATH` limited to the venv, and `GATES_OF_CODEX_SOURCE_COMMIT` absent, then asserts `package_identity().source_commit` equals the embedded SHA. Skip only when the `build` module is unavailable and state that dependency in the skip message.

- [ ] **Step 7: Run focused provenance and workflow contract tests green**

Run:

```powershell
python -m unittest tests.test_p6_packaging.PackagingProvenanceTests -v
python -m unittest tests.test_release_workflow tests.test_installer -v
git status --short
```

Expected: all selected tests PASS; the generated stamp is absent and `git status` contains only intentional tracked changes.

- [ ] **Step 8: Commit**

```powershell
git add .gitignore pyproject.toml src/gates_of_codex/packaging.py tools/stamp_package_provenance.ps1 tools/install_gates_of_codex.ps1 .github/workflows/gates-of-codex.yml .github/workflows/release.yml tests/test_p6_packaging.py
git commit -m "fix(p6): embed truthful package provenance"
```

---

### Task 2: Authenticate backup discovery and publish restore as a directory transaction

**Files:**
- Modify: `src/gates_of_codex/packaging.py`
- Modify: `src/gates_of_codex/player_shell.py`
- Test: `tests/test_p6_packaging.py`
- Test: `tests/test_p4_player_shell.py`

**Interfaces:**
- Produces: `ManagedRestorePlan(backup_directory: Path, campaign_directory: Path, campaign_file: Path, staged_files: tuple[tuple[Path, str], ...], created_at_utc: str)`.
- Produces: `latest_managed_backup(campaign_path, *, environ=None) -> dict[str, str] | None` containing `backup_directory`, `campaign_path`, and `created_at_utc` only after full validation.
- Produces: `restore_managed_backup(backup=None, *, expected_campaign, environ=None) -> list[Path]`; `backup=None` selects the authenticated latest backup.
- Produces: `clear_last_campaign_if_matches(campaign, *, environ=None) -> bool`.

- [ ] **Step 1: Write adversarial manifest and rollback tests**

Add helpers that capture `{relative_posix_path: bytes}` for a campaign directory. Add tests for malformed JSON, foreign campaign destination, unexpected filename, missing source, source outside the backup directory, duplicate source alias, and unrelated newest backup. Each must assert `PackagingError` and unchanged live bytes.

Add the mandatory publication-failure test:

```python
def test_restore_publication_failure_rolls_back_byte_identical_tree(self) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        env = self._managed_home(temporary)
        home = Path(env["GATES_OF_CODEX_HOME"])
        campaign = self._seed_campaign(home, '{"turn":7,"marker":"backup"}')
        record = backup_managed_campaign(campaign, environ=env)
        campaign.write_text('{"turn":99,"marker":"live"}\n', encoding="utf-8")
        (campaign.parent / SNAPSHOT_FILE_NAME).write_bytes(b"live snapshot\r\n")
        before = self._tree_bytes(campaign.parent)
        real_replace = packaging._replace_directory
        calls = 0
        def fail_stage_publish(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected publication failure")
            real_replace(source, destination)
        with mock.patch("gates_of_codex.packaging._replace_directory", side_effect=fail_stage_publish):
            with self.assertRaises(PackagingError):
                restore_managed_backup(record.backup_directory, expected_campaign=campaign, environ=env)
        self.assertEqual(before, self._tree_bytes(campaign.parent))
```

Add a Windows-specific assertion that every returned path compares equal to `campaign.parent / path.name` after `.resolve(strict=False)`; never compare caller spelling to a canonicalized path.

- [ ] **Step 2: Run managed restore tests red**

Run:

```powershell
python -m unittest tests.test_p6_packaging.ManagedRestoreResetTests -v
```

Expected: FAIL because `_replace_directory`, authenticated latest discovery, whole-directory rollback, and canonical return values do not exist.

- [ ] **Step 3: Implement immutable manifest preflight**

In `packaging.py`, add a frozen `ManagedRestorePlan` and `_build_restore_plan()`. Parse `backup.json` once, require its `backup_directory` to canonically equal the manifest parent, reject reparse/symlink inputs, require exactly one `campaign.json`, allow only the three known destination names, bind all destinations to the exact expected campaign directory, require each source to be a unique regular direct child of the backup directory, and record the ordered `(source, destination_name)` tuple. The expected campaign argument is mandatory for restore execution.

Use `os.lstat()` plus Windows `st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT` when available. Do not follow a reparse point while validating either manifest, backup directory, source, live campaign directory, stage, or rollback sibling.

- [ ] **Step 4: Implement deterministic latest authenticated backup**

Implement:

```python
def latest_managed_backup(campaign_path, *, environ=None):
    campaign = _canonical_campaign_file(campaign_path, environ=environ)
    candidates = []
    root = managed_backups_root(environ)
    if not root.is_dir():
        return None
    for child in root.iterdir():
        try:
            plan = _build_restore_plan(child, expected_campaign=campaign, environ=environ)
        except (OSError, ValueError, KeyError, PackagingError, json.JSONDecodeError):
            continue
        candidates.append((plan.created_at_utc, child.name, plan))
    if not candidates:
        return None
    plan = max(candidates, key=lambda row: (row[0], row[1]))[2]
    return {
        "backup_directory": str(plan.backup_directory),
        "campaign_path": str(plan.campaign_file),
        "created_at_utc": plan.created_at_utc,
    }
```

The helper must not surface a candidate until `_build_restore_plan` has validated every entry.

- [ ] **Step 5: Implement sibling stage/rollback publication**

Replace the generic `restore_backup(record)` call with this transaction shape:

```python
def _replace_directory(source: Path, destination: Path) -> None:
    source.replace(destination)

def restore_managed_backup(backup=None, *, expected_campaign, environ=None):
    selected = backup
    if selected is None:
        descriptor = latest_managed_backup(expected_campaign, environ=environ)
        if descriptor is None:
            raise PackagingError("No authenticated backup exists for this campaign")
        selected = descriptor["backup_directory"]
    plan = _build_restore_plan(selected, expected_campaign=expected_campaign, environ=environ)
    live = plan.campaign_directory
    stage = Path(tempfile.mkdtemp(prefix=f".{live.name}.restore-", dir=live.parent))
    rollback = live.parent / f".{live.name}.rollback-{uuid.uuid4().hex}"
    live_before = _capture_known_tree(live)
    try:
        for source, name in plan.staged_files:
            shutil.copy2(source, stage / name)
        load_campaign(stage / CAMPAIGN_FILE_NAME)
        _assert_tree_matches_plan(stage, plan)
        _replace_directory(live, rollback)
        try:
            _replace_directory(stage, live)
        except Exception as publish_error:
            _replace_directory(rollback, live)
            if _capture_known_tree(live) != live_before:
                raise PackagingError("Restore publication failed and rollback bytes differ") from publish_error
            raise PackagingError(f"Restore publication failed: {publish_error}") from publish_error
        shutil.rmtree(rollback)
        return [
            (live / name).resolve(strict=False)
            for name in (CAMPAIGN_FILE_NAME, SNAPSHOT_FILE_NAME, COMMANDS_FILE_NAME)
            if (live / name).is_file()
        ]
    finally:
        if stage.exists():
            shutil.rmtree(stage)
```

Import `stat`, `tempfile`, `uuid`, and `load_campaign`. `_capture_known_tree` must reject unexpected entries and return sorted names plus raw bytes. Only remove `stage`/`rollback` after verifying their parent is exactly `live.parent`; if rollback restoration itself fails, retain rollback and include its exact path in the raised error.

- [ ] **Step 6: Clear only the matching remembered campaign after reset**

Add to `player_shell.py`:

```python
def clear_last_campaign_if_matches(campaign, *, environ=None) -> bool:
    remembered = read_last_campaign(environ)
    target = Path(campaign).expanduser().resolve(strict=False)
    if remembered is None or remembered.expanduser().resolve(strict=False) != target:
        return False
    pointer = last_campaign_path(environ)
    try:
        pointer.unlink()
    except FileNotFoundError:
        return False
    return True
```

Call it only after `reset_test_campaign` has successfully removed the exact managed campaign, and return `campaign_deleted: true`, `next_player_state: "new_campaign"`, and `last_campaign_cleared` in the reset report.

- [ ] **Step 7: Run focused restore/reset tests green**

Run:

```powershell
python -m unittest tests.test_p6_packaging.ManagedRestoreResetTests -v
python -m unittest tests.test_p4_player_shell -v
```

Expected: all selected tests PASS, including the injected second replacement failure and matching/nonmatching pointer tests.

- [ ] **Step 8: Commit**

```powershell
git add src/gates_of_codex/packaging.py src/gates_of_codex/player_shell.py tests/test_p6_packaging.py tests/test_p4_player_shell.py
git commit -m "fix(p6): make managed restore transactional"
```

---

### Task 3: Rebind restore to the restored timeline and expose authenticated maintenance state

**Files:**
- Modify: `src/gates_of_codex/frontend.py`
- Modify: `src/gates_of_codex/frontend_commands.py`
- Test: `tests/test_p4_player_shell.py`
- Test: `tests/test_p6_golden_path.py`

**Interfaces:**
- Consumes: `latest_managed_backup(campaign_path, *, environ=None) -> dict[str, str] | None`.
- Produces: `snapshot["control"]["maintenance"] = {"restore_available": bool, "latest_backup": dict | None, "reset_available": bool}`.
- Produces: reset command result data with `campaign_deleted: true` and `next_player_state: "new_campaign"`.

- [ ] **Step 1: Write restored-ledger and reset lifecycle regressions**

Build a managed campaign with ledger entry `before-backup`, back it up, apply later entry `future-only`, then restore with command ID `restore-now`. Assert the saved ledger contains `before-backup` and `restore-now`, omits `future-only`, and accepts `future-only` on a subsequent command. Assert replaying `restore-now` is ignored exactly once after the first restore.

Add snapshot tests that a valid current-campaign backup appears under `control.maintenance.latest_backup`, a foreign/malformed backup does not, and provenance failure raises `PackagingError` rather than writing empty commit strings.

Add a reset response test asserting `ok`, empty `snapshot_path`, absent campaign/snapshot files, and lifecycle fields without calling `load_campaign` after deletion.

- [ ] **Step 2: Run frontend lifecycle tests red**

Run:

```powershell
python -m unittest tests.test_p4_player_shell tests.test_p6_golden_path -v
```

Expected: restored-ledger test FAIL because the pre-restore `ledger` object is persisted; snapshot maintenance descriptor and fail-closed identity assertions also FAIL.

- [ ] **Step 3: Rebind state, ledger, and observation context after restore**

In `apply_frontend_commands`, after successful `_apply_restore_backup`:

```python
result = _apply_restore_backup(campaign, state, raw)
state = load_campaign(campaign)
ledger = read_command_ledger(state)
observation_context = ObservationMutationContext()
before_presentations = _formation_presentation_rows(state)
```

Then let the common success tail append only the restore command ID to this restored ledger. Change `_apply_restore_backup` so an omitted backup selects `latest_managed_backup` and any explicit path still passes the exact same campaign-bound plan. Return the canonical selected backup descriptor in `result.data`.

- [ ] **Step 4: Make application identity and maintenance capability fail closed**

Remove `_application_block`'s broad `except Exception` and always merge `packaging_application_fields()`. Add `_maintenance_block(campaign_path)`:

```python
def _maintenance_block(campaign_path):
    if campaign_path is None:
        return {"restore_available": False, "latest_backup": None, "reset_available": False}
    from .packaging import latest_managed_backup
    latest = latest_managed_backup(campaign_path)
    return {
        "restore_available": latest is not None,
        "latest_backup": latest,
        "reset_available": True,
    }
```

Insert it under `control["maintenance"]`. Do not put raw unauthenticated backup directory scans into Godot.

- [ ] **Step 5: Make reset a terminal command lifecycle**

Keep `reset_test_campaign` isolated by `_batch_rejection`. After its success, return without `_store_command_ledger`, `save_campaign`, or `write_frontend_snapshot`. Ensure failure reporting reloads only when `campaign.is_file()`. Include the reset report unchanged in `CommandResult.data` so Godot can require the explicit lifecycle marker.

- [ ] **Step 6: Run focused frontend tests green**

Run:

```powershell
python -m unittest tests.test_p4_player_shell tests.test_p6_golden_path -v
```

Expected: all selected tests PASS; the restored ledger belongs to the backup timeline plus the restore command only.

- [ ] **Step 7: Commit**

```powershell
git add src/gates_of_codex/frontend.py src/gates_of_codex/frontend_commands.py tests/test_p4_player_shell.py tests/test_p6_golden_path.py
git commit -m "fix(p6): reload authority after campaign maintenance"
```

---

### Task 4: Add visible provenance and explicit Restore/Reset Godot lifecycle

**Files:**
- Modify: `godot/scripts/main_stack_panel.gd`
- Modify: `godot/scripts/main_writeback.gd`
- Modify: `godot/scripts/tools/player_shell_test.gd`
- Modify: `godot/scripts/tools/writeback_integration_test.gd`
- Modify: `tests/test_godot_async_writeback.py`

**Interfaces:**
- Consumes: `snapshot.application.source_commit` and `snapshot.control.maintenance` from Task 3.
- Produces: button IDs `restore_backup` and `reset_test_campaign`.
- Produces: local flags `restore_confirm_pending`, `reset_confirm_pending`, and a terminal `_enter_new_campaign_state(payload)` transition.

- [ ] **Step 1: Add headless contract assertions before controls exist**

In `player_shell_test.gd`, assert the application commit is 40 lowercase hex characters and the panel exposes Restore only with `restore_available` plus a descriptor. Exercise first click confirmation without command dispatch, second click dispatch, cancellation by another action, and both IDs absent from `enabled_action_button_ids()` while the fake runner is busy.

In `writeback_integration_test.gd`, add a restore-success fixture that changes snapshot data and proves stale selection/handoff state is cleared. Add a reset-success payload with `campaign_deleted: true` and `next_player_state: "new_campaign"`; assert no snapshot reload attempt, no Continue/writeback action, New Campaign remains enabled from retained launch arguments, and status is `Campaign reset - start New Campaign.`

- [ ] **Step 2: Run Godot/source contracts red**

Run:

```powershell
python -m unittest tests.test_godot_async_writeback -v
& $env:GODOT_BIN --headless --path godot --audio-driver Dummy -s res://scripts/tools/player_shell_test.gd -- --snapshot=tests/fixtures/frontend_snapshot.json
& $env:GODOT_BIN --headless --path godot --audio-driver Dummy -s res://scripts/tools/writeback_integration_test.gd
```

Expected: Python source contract or Godot assertions FAIL because the commit/control rendering and reset terminal lifecycle do not exist. If `GODOT_BIN` is unset locally, use the repository-documented Godot 4 console executable and record the exact command.

- [ ] **Step 3: Render exact commit and maintenance buttons**

In `main_stack_panel.gd`, display:

```gdscript
var application: Dictionary = snapshot.get("application", {})
_draw_text("Commit: %s" % String(application.get("source_commit", "")), x, y, FONT_SMALL, COLOR_MUTED)
```

Under CAMPAIGN, draw `Restore Latest Backup`/`Confirm Restore Latest Backup` and `Reset Test Campaign`/`Confirm Reset Test Campaign`. Use the actual enabled IDs from `enabled_action_button_ids()`; a disabled visual must never retain a live hit target.

- [ ] **Step 4: Add independent two-click and busy gates**

In `main_writeback.gd`, declare both confirmation flags. Add both IDs to `_command_mutates_state`. Centralize cancellation:

```gdscript
func _cancel_maintenance_confirmations() -> void:
    restore_confirm_pending = false
    reset_confirm_pending = false

func _maintenance() -> Dictionary:
    var control: Dictionary = snapshot.get("control", {})
    return control.get("maintenance", {}) as Dictionary
```

For Restore, first click sets only `restore_confirm_pending`; second click copies `latest_backup.backup_directory` from the snapshot and queues `[{"op":"restore_backup","backup_directory": value}]`. For Reset, first click sets only `reset_confirm_pending`; second click queues `[{"op":"reset_test_campaign"}]`. Cancel both flags on any other action, snapshot load, or command start. Busy or operational-presentation mutation gates must reject both.

- [ ] **Step 5: Implement post-command success transitions**

Before generic snapshot replacement in `_on_command_finished`, inspect the validated payload. For reset require both lifecycle markers, then call:

```gdscript
func _enter_new_campaign_state(payload: Dictionary) -> void:
    var retained_play: Dictionary = snapshot.get("control", {}).get("play", {}).duplicate(true)
    snapshot = {
        "application": snapshot.get("application", {}).duplicate(true),
        "control": {
            "enabled": false,
            "play": {
                "enabled": true,
                "new_args": retained_play.get("new_args", []).duplicate(),
                "continue_args": [],
            },
            "maintenance": {"restore_available": false, "latest_backup": null, "reset_available": false},
        },
    }
    selected_province_id = ""
    selected_battalion_id = ""
    _cancel_maintenance_confirmations()
    status_message = "Campaign reset - start New Campaign."
    _clear_busy_ui()
```

For Restore, require the normal fresh snapshot load, but pass empty previous selections and clear presenter/handoff transient state before `_commit_snapshot_state`. On backend failure retain the entire previous snapshot and both view transforms.

- [ ] **Step 6: Run all Godot contracts green**

Run the three commands from Step 2 plus the repository headless player-shell invocation using a generated production snapshot. Expected: PASS/exit 0, with commit, confirmation, busy, restore reload, and reset-to-new assertions all executed.

- [ ] **Step 7: Commit**

```powershell
git add godot/scripts/main_stack_panel.gd godot/scripts/main_writeback.gd godot/scripts/tools/player_shell_test.gd godot/scripts/tools/writeback_integration_test.gd tests/test_godot_async_writeback.py
git commit -m "feat(p6): add safe restore and reset controls"
```

---

### Task 5: Make the complete Earth3 production golden path mandatory

**Files:**
- Modify: `src/gates_of_codex/turn_cycle.py`
- Modify: `tests/test_issue_207_turn_cycle_ui.py`
- Replace: `tests/test_p6_golden_path.py`
- Modify: `.github/workflows/gates-of-codex.yml`

**Interfaces:**
- Consumes: `ensure_strategic_actor_runtime(state)` after each `CampaignEngine.end_turn()` transition.
- Consumes: production `run_play`, `apply_frontend_commands`, `prepare_stack_handoff`, Verify/Import services, and generated frontend snapshot.
- Produces: a single test that cannot assign `pending_battle` or call `_create_prepared_contact`.

- [ ] **Step 1: Reproduce and pin the P2 actor mismatch**

Add a turn-cycle regression using production Earth3 state, issue the offered `sf_pol_vilnius` route to `op-node-e3_3380-anchor`, commit it, and call the installed `end_player_round` op. Require `result["ok"]`, a nonempty `ai_factions` list, and either return to selected faction or a real pending battle. Remove the current assertion that accepts either success or failure.

- [ ] **Step 2: Run the actor synchronization test red**

Run:

```powershell
python -m unittest tests.test_issue_207_turn_cycle_ui -v
```

Expected: FAIL with `Earth3 P2 current actor tactical side mismatch` after NATO advances to UKR while actor runtime still names `usa`.

- [ ] **Step 3: Synchronize actor runtime after every canonical seat transition**

In `turn_cycle.py`, import `ensure_strategic_actor_runtime` and call it immediately after all three `engine.end_turn()` sites: the initial human end, eliminated-seat recovery, and post-AI advance. Do not change turn order or selected actor semantics.

```python
engine.end_turn()
ensure_strategic_actor_runtime(state)
```

Run the turn-cycle regression again. Expected: PASS and real AI execution is recorded.

- [ ] **Step 4: Replace the shortcut with a filesystem production fixture stack**

In `test_p6_golden_path.py`, remove imports of `_state`, `_create_prepared_contact`, `_write_completed_external_battle`, and `_resolved_catalog`. Build temporary `game`, `profile`, five stack layers, portable stack config, managed campaign, and save roots using the filesystem shapes in `OrderedModStackTests` and the Workshop layer writer in `test_p5_tactical_handoff.py`.

Extend the fixture catalog so the real `FactionWiringCompiler` materializes the five active Earth3 actors `usa`, `deu`, `pol`, `ukr`, and `rus`, each with the exact required categories `infantry`, `tank`, and `artillery`. Populate the bundled manifest's real selector roots: US `2022mar`/`2022sck2`/`2022tank1`, Germany `2022pz10`, Poland's required exact units plus NATO heavy fallback, Ukraine `ukr932022`/`utank2022`/`arty2022`, and Russia `2022rus90`/`tank2022`/`rarty2022`. Supply a valid breed for every squad member and an entity definition for every vehicle/artillery unit. Keep all content inside the fixture stack; do not inject a resolved catalog.

Parse arguments with `build_play_parser().parse_args(["--new", "--force-new", "--no-launch", "--scenario", "earth3_v1", "--campaign", str(campaign), "--stack-config", str(stack_config), "--game", str(game), "--profile", str(profile), "--tactical-map", "multi/2x2/stack_test"])` and call `run_play(args, environ=env)` with no `resolved_catalog`. Assert the result and reloaded state are scenario `earth3_v1`, map `earth3`, and persist the exact validated resource-stack order, Code:X layer, stack config, and catalog signature.

- [ ] **Step 5: Generate and consume the real production snapshot in Godot**

Write `campaign_snapshot.json` with `write_frontend_snapshot`. Launch:

```python
completed = subprocess.run(
    [godot, "--headless", "--path", str(ROOT / "godot"), "--audio-driver", "Dummy",
     "-s", "res://scripts/tools/player_shell_test.gd", "--", f"--snapshot={snapshot_path}"],
    check=False, capture_output=True, text=True, timeout=120,
)
self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
```

The GDScript assertion must instantiate `res://main.tscn` through `PackedScene.instantiate()`, then validate Earth3 identity, the exact full commit, writeback availability, and initial operational controls from this file. Instantiating `MainScript.new()` alone is insufficient.

- [ ] **Step 6: Reach contact only through real orders and player rounds**

From `list_operational_move_options`, select the exact offered row where `formation_id == "sf_pol_vilnius"` and `target_node_id == "op-node-e3_3380-anchor"`. Submit `issue_move_order` and `commit_move_orders` through `apply_frontend_commands` with unique command IDs. Loop at most eight player rounds through the installed `end_player_round` command, reloading the campaign after each. Assert every round succeeds and records AI activity until `pending_battle` exists. Then assert attacker is the selected faction, defender differs, `encounter_kind` is nonempty, and the formation position is the ordered target. Never set pending battle directly.

- [ ] **Step 7: Generate the real handoff before synthesizing tactical completion**

Submit the standalone real command `{"op":"handoff","work_root":str(work_root),"backup_root":str(backup_root),"map":"multi/2x2/stack_test","command_id":"p6-handoff"}`. Assert the installed save and sidecar exist and bind the real campaign path, pending battle ID, map, visible save name, and exact validated stack; assert the save `{mods}` block equals `stack_dependency_tokens(validated_layers)` in order. Only after those assertions, open that installed archive with `CampaignSaveArchive`, preserve `campaign_scn`, increment manifest-baseline `playedGames`, and increment `wonGames` for a NATO win. Pass the installed save path explicitly to `verify_result` and `import_battle`, require verification, require the pending battle clears, and replay the same import ID to prove duplicate suppression.

- [ ] **Step 8: Prove post-import strategic continuation**

Reload from disk, request real operational options, choose one currently valid option, submit it through `apply_frontend_commands`, save/reload, and assert the selected formation's order or position changed according to the accepted command. This action must occur after Import and must not be `refresh`/`noop`.

- [ ] **Step 9: Make Godot CI consume the generated golden snapshot**

In `.github/workflows/gates-of-codex.yml`, keep the golden test in the Godot-capable job and pass the discovered Godot executable through `GODOT_BIN`. Ensure the core Windows/Linux shards still run all non-Godot parts; use the existing skip only when no Godot executable exists outside the dedicated Godot job.

- [ ] **Step 10: Run the complete focused chain green**

Run:

```powershell
python -m unittest tests.test_issue_207_turn_cycle_ui tests.test_p6_golden_path -v
python tools/run_python_test_shard.py core
```

Expected: all tests PASS; `test_p6_golden_path` itself launches Godot with its generated absolute snapshot, proves a real pending battle preceded handoff, and persists a valid post-import strategic command.

- [ ] **Step 11: Commit**

```powershell
git add src/gates_of_codex/turn_cycle.py tests/test_issue_207_turn_cycle_ui.py tests/test_p6_golden_path.py .github/workflows/gates-of-codex.yml
git commit -m "test(p6): prove the complete Earth3 golden path"
```

---

### Task 6: Exact-head verification, review, and draft PR update

**Files:**
- Modify only files required by failures traceable to Tasks 1-5.
- Record evidence in the PR comment; do not add transient logs or generated stamps to Git.

**Interfaces:**
- Consumes: all Task 1-5 commits and the repository's existing shard/workflow commands.
- Produces: one pushed SHA on `feat/p0-p6-golden-path`, full green exact-head CI, and an independent re-audit request while PR #216 remains draft.

- [ ] **Step 1: Run focused adversarial tests**

```powershell
python -m unittest tests.test_p6_packaging tests.test_p4_player_shell tests.test_godot_async_writeback tests.test_issue_207_turn_cycle_ui tests.test_p6_golden_path -v
```

Expected: PASS with zero failures/errors; Windows rollback injection, ledger timeline, lifecycle, actor sync, and production golden path are all exercised.

- [ ] **Step 2: Run the repository Python matrix locally**

Run every shard using the repository runner, then the second supported Python runtime when installed:

```powershell
python tools/run_python_test_shard.py core
python tools/run_python_test_shard.py earth3-authority-bootstrap
python tools/run_python_test_shard.py p4-production-launch
```

Expected: every shard PASS; skips are only documented platform/live-engine skips.

- [ ] **Step 3: Run PowerShell packaging and Godot headless gates**

Invoke the stamp helper in a clean tree, run the installer/package smoke in its test output mode, then run all repository Godot headless scripts used by `.github/workflows/gates-of-codex.yml`. Expected: the installed venv and PyInstaller runtime report the current exact SHA, the stamp is cleaned, and every headless script exits 0.

- [ ] **Step 4: Inspect cleanliness and review the cumulative diff**

```powershell
git status --short
git diff --check 7fe06057ce8d305e785564105ea602815a36b523..HEAD
git diff --stat 7fe06057ce8d305e785564105ea602815a36b523..HEAD
```

Expected: clean worktree, no whitespace errors, no tracked `SOURCE_COMMIT`, and only P6-authorized files.

- [ ] **Step 5: Request broad code review and resolve every material finding**

Use the requesting-code-review workflow against base `7fe06057ce8d305e785564105ea602815a36b523` and current head. Re-run the relevant focused test after each accepted correction, commit it with a scoped message, then repeat the cumulative review until no blocking findings remain.

- [ ] **Step 6: Push one fast-forward head to the existing PR branch**

```powershell
git push origin HEAD:feat/p0-p6-golden-path
```

Expected: non-force fast-forward succeeds; PR #216 remains open, draft, unmerged, one coherent PR.

- [ ] **Step 7: Gate on exact-head CI**

Capture `git rev-parse HEAD`, confirm PR #216 head equals it, and monitor every required Windows/Linux core/authority/integration/acceptance, Windows executable, and Godot check. Do not carry forward evidence from `7fe06057...`. Fix any attributable failure on the same PR branch and repeat local/CI verification on the resulting new exact head.

- [ ] **Step 8: Request independent exact-head re-audit**

Post one concise PR comment naming the exact SHA, local commands, CI run URL, green checks, and mapping of each audit finding to its test. Explicitly state that the PR remains draft and is not ready to merge. Request an independent re-audit of that exact SHA.

- [ ] **Step 9: Stop before native acceptance implementation changes**

After the independent re-audit accepts the exact SHA, switch to the `gates-native-acceptance` workflow for the packaged owner-native Windows/Gates of Hell run. That acceptance-only run may collect evidence but must not edit implementation. If implementation changes become necessary, return to this plan, create a new exact head, and repeat CI plus re-audit before native acceptance.
