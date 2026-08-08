# S10 Operational Resolution Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Present authoritative operational movement, contact, Ambush, pending battle, retreat, trapped removal, and session-only contact replay in Godot without changing simulation authority.

**Architecture:** Add deterministic read-only participant and transient command-result payloads in the Python frontend adapter. Feed those payloads into an isolated Godot presenter that owns interpolation and replay view state while the existing scene owns drawing, input gating, snapshot refresh, and handoff.

**Tech Stack:** Python 3.11+, dataclasses/JSON frontend contract, Godot 4.7 GDScript, pytest, existing Godot SceneTree test and screenshot harnesses.

## Global Constraints

- Base commit is exactly `503a71eeb804c5c33e301912228f617847f32df0`.
- Python gameplay behavior and `campaign.py` remain unchanged.
- Frontend schema stays 13 unless implementation proves an unavoidable snapshot incompatibility.
- Presentation fields are additive, read-only, deterministic, and absent-compatible.
- Replay and interpolated positions are session-only and never persisted or written back.
- Default duration is 0.45 seconds; Skip completes every active track at its authoritative endpoint.
- Do not modify Earth3 geography/assets, OpenGS, production routes, S8/S9 mechanics, AI, GoH tactical behavior, or begin S11.

---

### Task 1: Add the transient Python presentation contract

**Files:**
- Modify: `src/gates_of_codex/frontend.py`
- Modify: `src/gates_of_codex/frontend_commands.py`
- Create: `tests/test_s10_frontend_presentation_contract.py`

**Interfaces:**
- Produces: pending participant rows described in the approved design.
- Produces: `CommandResult.data["operational_presentation"]` with `movements` and optional `battle_finalization`.
- Consumes: existing `position_to_dict`, `resolve_display_pixel`, `move_order_to_dict`, and `BattleFinalizationReport`.

- [ ] **Step 1: Write failing participant serialization tests**

Create a pending multi-formation Ambush battle and assert exact participant metadata, stable ordering, formation IDs/names, and no schema bump.

- [ ] **Step 2: Run the participant tests and verify RED**

Run: `python -m pytest tests/test_s10_frontend_presentation_contract.py -q`

Expected: failure because detailed participant rows are absent.

- [ ] **Step 3: Implement minimal participant serialization**

Add a private serializer in `frontend.py` that copies existing `BattleParticipant` values and resolves formation presentation names without mutating state.

- [ ] **Step 4: Run the participant tests and verify GREEN**

Run the same focused pytest command; expected participant cases pass.

- [ ] **Step 5: Write failing transient movement/finalization tests**

Assert exact start/end pixels and path IDs for movement, exact retreat destination/pixel, exact `trapped_no_legal_retreat`, deterministic JSON, and unchanged campaign persistence shape.

- [ ] **Step 6: Run those tests and verify RED**

Expected: failure because command results do not yet contain `operational_presentation`.

- [ ] **Step 7: Implement minimal transient adapter output**

Capture authoritative before/after formation rows around each successful command. Use a private frontend-only `CampaignEngine` subclass for `auto_resolve` to retain the existing finalization report without editing gameplay modules.

- [ ] **Step 8: Run the full new Python module and directly affected frontend tests**

Run: `python -m pytest tests/test_s10_frontend_presentation_contract.py tests/test_frontend_writeback_contract.py tests/test_godot_s6_battle_location.py -q`

Expected: all focused tests pass.

- [ ] **Step 9: Commit the substantive Python contract slice**

Stage only the two adapter modules and their focused tests. Commit: `feat: expose transient S10 presentation data`.

### Task 2: Build the session-only Godot presenter test-first

**Files:**
- Create: `godot/scripts/presentation/operational_resolution_presenter.gd`
- Create: `godot/scripts/tools/operational_resolution_presenter_test.gd`

**Interfaces:**
- `begin_transition(previous_snapshot: Dictionary, next_snapshot: Dictionary, backend_payload: Dictionary, graph_index: Dictionary) -> void`
- `advance(delta: float) -> void`
- `skip() -> void`
- `replay_last_contact() -> bool`
- `reset_session() -> void`
- `display_pixel(formation_id: String, authoritative_pixel: Vector2) -> Vector2`
- Read-only getters for active tracks, contact model, modal model, replay availability, and transient outcome.

- [ ] **Step 1: Write failing endpoint/parallel/skip tests**

Use two real movement records with distinct endpoints. Assert progress zero equals start, shared half-time samples both tracks, natural completion and Skip equal exact endpoints.

- [ ] **Step 2: Run the Godot test and verify RED**

Run: `Godot_v4.7-stable_win64_console.exe --headless --path godot --script res://scripts/tools/operational_resolution_presenter_test.gd`

Expected: parse/load failure because the presenter does not exist.

- [ ] **Step 3: Implement the minimal shared-clock track controller**

Use 0.45 seconds, validate records against supplied path IDs, interpolate only display pixels, and snap invalid/disconnected records to endpoints.

- [ ] **Step 4: Verify endpoint/parallel/skip GREEN**

Run the focused Godot test; expected endpoint/parallel/skip cases pass.

- [ ] **Step 5: Add failing contact, Ambush, replay, retreat, and compatibility cases**

Assert all four direct contact labels, exact contact pixel, participant-only Ambush at received 1150, no label for false-trigger rows, snapshot JSON unchanged by replay, command count unchanged, replay reset on fresh load, exact retreat endpoint, exact trapped reason, and load with absent S10 fields.

- [ ] **Step 6: Implement minimal contact/replay/outcome view models**

Store only the most recent primary contact in memory; never modify snapshots or invoke commands.

- [ ] **Step 7: Run the complete new Godot unit module**

Expected: all focused cases pass with zero failures.

- [ ] **Step 8: Commit the presenter slice**

Commit: `feat: add session-only operational presenter`.

### Task 3: Integrate animation, Skip, contact emphasis, and the modal gate

**Files:**
- Modify: `godot/scripts/main_writeback.gd`
- Modify: `godot/scripts/main_color_id.gd`
- Modify: `godot/scripts/main_stack_panel.gd`
- Modify: `godot/scripts/presentation/map_markers.gd`
- Modify: `godot/project.godot`
- Create or modify focused Godot integration test under `godot/scripts/tools/`.

**Interfaces:**
- `main_writeback.gd` owns presenter lifecycle and supplies previous/next snapshots plus parsed backend result.
- `main_color_id.gd` consumes presenter pixels and draws transient formation/contact/outcome overlays.
- `main_stack_panel.gd` draws and gates the pending-battle modal and its existing handoff/resolve actions plus replay.

- [ ] **Step 1: Write failing scene integration tests**

Assert active presentation disables mutating actions except Skip, pending battle blocks background input/actions, modal allows Auto-resolve/Handoff/Replay only as applicable, and replay does not start the fake command runner or change snapshot JSON.

- [ ] **Step 2: Run the integration test and verify RED**

Expected: failures for missing presenter integration and modal gate.

- [ ] **Step 3: Integrate the presenter with transactional command completion**

Parse successful command output before snapshot commit, commit the candidate atomically, then start presentation from the preserved prior snapshot and received transient result. Initial loads call `reset_session`.

- [ ] **Step 4: Draw active tracks and contact emphasis**

Reuse `map_space`, `MapMarkers`, `BattleLocation`, and existing overlay layers. Hide endpoint duplicates while a track is active; dim unrelated map content at contact and redraw participants prominently.

- [ ] **Step 5: Add visible Skip and input action**

Add `skip_operational_presentation` to `project.godot` and route it to presenter `skip()` without commands or snapshot mutation.

- [ ] **Step 6: Add the modal gate and replay action**

Draw paused state, exact kind/location, formation side labels, received Ambush 1150, existing Auto-resolve/Handoff, and Replay. Consume all background input while pending.

- [ ] **Step 7: Verify integration GREEN**

Run the new presenter/integration tests plus existing `battle_location_test.gd`, `command_runner_test.gd`, and the directly affected map smoke.

- [ ] **Step 8: Commit the scene integration slice**

Commit: `feat: present operational contacts and pending battles`.

### Task 4: Add deterministic fixtures and true runtime evidence

**Files:**
- Create focused `godot/fixtures/presentation/s10_*.json` files.
- Modify: `godot/fixtures/presentation/README.md` only to list the new fixtures.
- Modify: `godot/scripts/tools/map_screenshot.gd` only if a narrow fixture hook is required.
- Create: `docs/godot-presentation/screenshots/s10/*.png`.

**Interfaces:**
- Fixtures remain `gates-of-codex.presentation-fixture` and prefix mock-only payloads with `presentation_`.
- Runtime captures use the standard 1920x1080 viewport and existing screenshot harness.

- [ ] **Step 1: Add fixtures for all required visual states**

Cover ordinary node contact, node simultaneous, edge cross/catchup, prepared Ambush, pending modal, successful retreat, and trapped removal.

- [ ] **Step 2: Run fixture-driven headless smoke**

Verify every fixture loads with no GDScript parse error.

- [ ] **Step 3: Generate true runtime screenshots**

Run the existing `map_screenshot.gd` harness at 1920x1080 for each required state and record exact output paths.

- [ ] **Step 4: Inspect every capture**

Open each PNG and confirm the intended state is visible, unclipped, and distinguishable. Regenerate only failed captures.

- [ ] **Step 5: Commit fixtures and approved evidence artifacts**

Commit: `test: add S10 runtime presentation evidence`.

### Task 5: Focused validation, protected-path check, and draft PR handoff

**Files:**
- No new runtime files beyond prior tasks.
- Update the draft PR body/comment after push.

**Interfaces:**
- PR targets `main`, links issue #108, remains draft and unmerged.

- [ ] **Step 1: Run only the required focused validation**

Run the new Godot tests, directly affected existing Godot map tests, directly affected Python frontend tests, GDScript import/parse checks, Python compile checks for changed Python files, screenshot generation, and `git diff --check`.

- [ ] **Step 2: Inspect the complete diff from the exact base**

Run: `git diff --stat 503a71eeb804c5c33e301912228f617847f32df0` and inspect every changed file.

- [ ] **Step 3: Verify scope boundaries**

Confirm no Python gameplay module, Earth3 geography/assets, OpenGS, production-route, S8/S9 mechanics, AI, or tactical battle path changed. Remove temporary/debug/generated files not intended for review.

- [ ] **Step 4: Commit final focused corrections**

Stage explicit intended paths and commit tersely.

- [ ] **Step 5: Push and open one draft PR**

Push `feat/s10-operational-resolution-presentation`, create a draft PR targeting `main`, and link issue #108 without marking ready.

- [ ] **Step 6: Update the draft handoff**

Record exact head SHA, changed files, focused commands/pass counts, unchanged schema version, exact transient fields, screenshot locations, backend-data limitations, and confirmation that full CI/independent audit were deferred.

- [ ] **Step 7: Stop**

Do not merge, mark ready, begin S11, or expand scope.
