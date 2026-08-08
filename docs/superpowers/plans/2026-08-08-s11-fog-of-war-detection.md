# S11 Fog of War and Detection Implementation Plan

> **For agentic workers:** execute this plan in order. Each PR is independently reviewed and merged before the next branch is created. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic observer-scoped Fog of War, last-known contacts, AI information parity, and Godot presentation without changing true campaign simulation authority.

**Architecture:** Python stores one authoritative campaign plus deterministic coalition-scoped knowledge records. A new observation module computes current visibility and retained knowledge, produces filtered frontend snapshots, and supplies the same believed-state value object to operational AI. Godot consumes only the filtered schema-14 snapshot and renders current and stale contacts without calculating detection.

**Tech stack:** Python 3.11+, dataclasses, JSON campaign persistence, existing operational graph authority, unittest/pytest, Godot 4.7 GDScript, existing SceneTree and screenshot harnesses.

## Global constraints

- Initial docs base is exactly S10 merge `cbef4db96f04d26f4127278041f717691712d7eb`.
- Follow-up branches start from the exact accepted merge of the preceding S11 PR.
- True `CampaignState` remains the only simulation state.
- No pixel LOS, detection RNG, terrain/weather modifiers, false contacts, electronic warfare, spies, or air reconnaissance in the thin slice.
- Province ownership remains public.
- Enemy exact orders and destinations are never exposed.
- Coalition allies share one observation scope in the thin slice.
- AI must use the same observation authority as the human-facing snapshot.
- Campaign schema advances from 4 to 5 only in the Python implementation PR.
- Frontend schema advances from 13 to 14 only in the Python implementation PR.
- FOW Off preserves current behavior.
- Do not modify Earth3 geography/assets, route authority, OpenGS evaluation, S8 supply mechanics, S9 contact/Ambush/retreat rules, S10 movement presentation authority, or GoH tactical behavior.

---

## PR A: Lock the design contract

**Branch:** `feat/s11-fog-of-war-design`

**Files:**

- Create: `docs/superpowers/specs/2026-08-08-s11-fog-of-war-detection-design.md`
- Create: `docs/superpowers/plans/2026-08-08-s11-fog-of-war-detection.md`

- [x] **Step 1: Record owner authorization on #107**

Lock launch phasing, graph-first detection, coalition sharing, AI parity, and the three-PR delivery chain.

- [x] **Step 2: Write the complete design contract**

Specify information tiers, detection sources, Ambush concealment, last-known behavior, persistence, schema changes, frontend redaction, AI fairness, failure behavior, and explicit non-goals.

- [x] **Step 3: Write this implementation plan**

Name the expected modules, tests, schema migrations, validation sequence, and stop points for PR B and PR C.

- [ ] **Step 4: Inspect docs-only diff**

Confirm the branch contains exactly the two intended Markdown files and no runtime or generated changes.

- [ ] **Step 5: Open a draft PR targeting `main`**

Link #107 and #77. Record exact base/head, owner authorization, changed files, and confirmation that no runtime code or tests changed.

- [ ] **Step 6: Stop for independent review**

Do not create the Python implementation branch until PR A is independently accepted and merged.

---

## PR B: Add Python observation authority and AI parity

**Branch after PR A merge:** `feat/s11-fog-of-war-authority`

### Task B1: Add strict persisted observation models

**Files:**

- Modify: `src/gates_of_codex/models.py`
- Modify: `src/gates_of_codex/state_io.py`
- Create: `src/gates_of_codex/observation.py`
- Create: `tests/test_s11_observation_model.py`
- Modify or create focused state-I/O migration tests under `tests/`

**Interfaces:**

- `InformationTier` enum with `unknown`, `contact`, `identified`, `assessed`, `fully_observed`.
- `KnowledgeRecord` dataclass with tier-appropriate optional fields from the approved design.
- `CampaignState.fog_of_war_enabled`.
- `CampaignState.knowledge_by_observer`.
- `observer_scope_id(state, faction)`.
- Strict record validation and deterministic serialization.

- [ ] Write failing model tests for tier ordering, required/forbidden fields, sorted source labels, observer scope, and contradictory records.
- [ ] Run the focused module and verify RED.
- [ ] Implement only the new enum, dataclass, campaign fields, and validation.
- [ ] Add schema-4 migration tests proving Fog of War defaults Off and knowledge defaults empty.
- [ ] Add schema-5 save/load round-trip and deterministic JSON tests.
- [ ] Implement state-I/O parsing and schema version 5.
- [ ] Run model and state-I/O tests until GREEN.
- [ ] Commit: `feat: add persisted S11 knowledge model`.

### Task B2: Implement deterministic detection and last-known refresh

**Files:**

- Modify: `src/gates_of_codex/observation.py`
- Modify only the narrow authoritative boundary modules required to call refresh after operational ticks, battle finalization, and site-control changes.
- Create: `tests/test_s11_detection.py`
- Create: `tests/test_s11_last_known.py`

**Interfaces:**

- `refresh_observer_knowledge(state, observer_faction)`.
- `refresh_all_observer_knowledge(state)`.
- `build_operational_observation(state, observer_faction)`.
- Explicit recon capability resolver with no substring heuristics.
- Stable current observation and retained record keys.

- [ ] Write failing tests for same-node and same-edge full observation.
- [ ] Write failing tests for one-hop site contact and explicit recon upgrades.
- [ ] Write failing source-combination tests capped at `assessed` without contact.
- [ ] Write failing Ambush one-tier concealment tests.
- [ ] Write failing coalition-sharing tests.
- [ ] Write failing no-graph province fallback tests.
- [ ] Implement graph/province indexes and deterministic source evaluation.
- [ ] Implement current observation merge by highest tier, then stable source ordering.
- [ ] Write failing last-known tests proving hidden truth may move while the marker remains fixed.
- [ ] Implement retained records with current/stale flags and deterministic age fields.
- [ ] Add refresh calls only at the approved authoritative boundaries.
- [ ] Run focused detection, contact, Ambush, capture, retreat, and state-I/O tests.
- [ ] Commit: `feat: compute deterministic S11 observations`.

### Task B3: Add observer-filtered frontend schema 14

**Files:**

- Modify: `src/gates_of_codex/frontend.py`
- Modify: any narrow frontend command adapter needed to carry observer identity without exposing hidden truth.
- Create: `tests/test_s11_frontend_filter.py`
- Modify: existing frontend compatibility tests.

**Interfaces:**

- `build_frontend_snapshot(..., observer_faction=...)` or an equivalent explicit observer parameter.
- `fog_of_war` metadata block.
- Tier-redacted current enemy formation rows.
- `last_known_contacts` array.
- Frontend schema 14.

- [ ] Capture a complete FOW-Off schema-13-equivalent baseline fixture.
- [ ] Write failing FOW-Off parity tests.
- [ ] Write failing tests that unknown enemy formations and all dependent battalion, commander, stack, presentation, and order rows are absent.
- [ ] Write exact tier tests for contact, identified, assessed, and fully observed fields.
- [ ] Write side-channel tests for tooltips/presentation payloads, pending battle, command output, and serialized logs available through the frontend path.
- [ ] Implement one centralized redaction/filter pass rather than scattered UI-specific omissions.
- [ ] Bump frontend schema to 14 and retain accepted FOW-Off compatibility.
- [ ] Run all frontend, writeback, S10 presentation-contract, and snapshot determinism tests.
- [ ] Commit: `feat: filter schema 14 by observer knowledge`.

### Task B4: Enforce operational AI non-omniscience

**Files:**

- Modify: `src/gates_of_codex/operational_ai.py`
- Modify narrow AI call sites to supply the observer-scoped observation value object.
- Create: `tests/test_s11_ai_information_parity.py`
- Modify: existing operational AI tests only where the new explicit interface requires it.

**Interfaces:**

- AI ranking receives full friendly state, public map authority, and `OperationalObservation` enemy knowledge.
- Enemy goal and threat helpers cannot iterate true hidden enemy formations when FOW is On.
- FOW Off uses the complete observation projection and retains existing behavior.

- [ ] Write paired true-state tests whose enemy positions differ but believed observation is identical; outputs must match exactly.
- [ ] Write tests proving an observed/last-known change can alter the decision.
- [ ] Add a guard test that fails if FOW-On ranking reads hidden enemy rows from `CampaignState`.
- [ ] Refactor enemy-dependent ranking helpers behind the observation interface.
- [ ] Preserve existing movement issue/commit authority and deterministic tie-breaking.
- [ ] Run the full operational AI, movement, contact, capture, supply, and Ambush suites.
- [ ] Commit: `feat: plan operational AI from believed state`.

### Task B5: Add campaign setup control and complete validation

**Files:**

- Modify: `src/gates_of_codex/entrypoint.py`
- Modify only the current campaign creation/service module needed to set the field explicitly.
- Modify: `README.md` only for the final accepted CLI/setup behavior.
- Create or modify focused CLI tests.

- [ ] Add `--fog-of-war on|off` or the repository-consistent equivalent, default Off.
- [ ] Prove old command lines retain Off behavior.
- [ ] Prove explicit On initializes deterministic knowledge without changing true simulation state.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run Python compile checks and `git diff --check`.
- [ ] Inspect the complete diff against the exact PR-A merge.
- [ ] Confirm no Godot, Earth3, OpenGS, tactical export, or unrelated gameplay file changed.
- [ ] Open one draft PR linked to #107 and stop for independent review.

Do not begin PR C until PR B is independently accepted and merged.

---

## PR C: Present current and stale intelligence in Godot

**Branch after PR B merge:** `feat/s11-fog-of-war-presentation`

### Task C1: Add a simulation-free intelligence presenter

**Files:**

- Create: `godot/scripts/presentation/fog_of_war_presenter.gd`
- Create: `godot/scripts/tools/fog_of_war_presenter_test.gd`

**Interfaces:**

- Consume schema-14 `fog_of_war`, filtered formation rows, and `last_known_contacts` only.
- Return view models for current contact, identified, assessed, fully observed, and stale records.
- Never query or reconstruct omitted truth.

- [ ] Write failing parsing and tier-style tests.
- [ ] Write failing tests for fixed last-known positions and stale ages.
- [ ] Write failing absent-field tests proving no exact hidden values are synthesized.
- [ ] Implement the minimal immutable presenter.
- [ ] Run the complete focused GDScript suite.
- [ ] Commit: `feat: add S11 intelligence presenter`.

### Task C2: Integrate map, selection, panels, and tooltips

**Files:**

- Modify: `godot/scripts/main_color_id.gd`
- Modify: `godot/scripts/main_stack_panel.gd`
- Modify: narrow selection/tooltip modules that currently consume strategic formation rows.
- Modify: `godot/scripts/presentation/map_markers.gd` only if required for new marker primitives.
- Create: `godot/scripts/tools/fog_of_war_scene_test.gd`

- [ ] Write active-scene failures for unknown absence, tier distinction, stale markers, and FOW-Off parity.
- [ ] Render current contacts without exact identity.
- [ ] Render identified and assessed contacts with only permitted fields.
- [ ] Render stale contacts at their recorded location with visible age/stale treatment.
- [ ] Ensure unknown enemies do not appear in stacks, panels, selection, hover, tooltips, counts, or accessibility text.
- [ ] Ensure direct-contact/pending-battle presentation continues to use S10 authoritative participants.
- [ ] Prove color-ID province hit testing, panning, zoom, and S10 movement playback remain unchanged.
- [ ] Run new and directly affected Godot suites.
- [ ] Commit: `feat: render S11 current and stale contacts`.

### Task C3: Add deterministic fixtures and owner evidence

**Files:**

- Create: `godot/fixtures/presentation/s11_*.json`.
- Modify: `godot/fixtures/presentation/README.md`.
- Create: `docs/godot-presentation/screenshots/s11/*.png`.
- Modify screenshot harness only if an isolated schema-14 fixture hook is required.

Required captures:

1. FOW Off parity;
2. unknown enemy absent;
3. contact-only marker;
4. identified marker;
5. assessed strength-band marker;
6. fully observed direct contact;
7. stale last-known marker with age;
8. prepared Ambush remaining concealed before contact;
9. pending battle revealing authoritative participants;
10. coalition-shared contact.

- [ ] Add deterministic fixtures with no hidden truth in filtered payloads.
- [ ] Run headless fixture smoke.
- [ ] Generate true runtime captures at the repository-standard viewport.
- [ ] Inspect every capture for clipping and information leakage.
- [ ] Commit only approved fixtures and evidence.

### Task C4: Validate and hand off

- [ ] Run new S11 Godot tests and all directly affected S10/map/writeback tests.
- [ ] Run the full Python matrix because schema-14 fixtures cross the frontend boundary.
- [ ] Run Godot import/parse checks, screenshot generation, and `git diff --check`.
- [ ] Inspect the complete diff against the exact PR-B merge.
- [ ] Confirm no Python observation authority, campaign truth, Earth3, OpenGS, tactical behavior, or unrelated UI changed.
- [ ] Open one draft PR linked to #107.
- [ ] Stop for independent review and owner visual approval.

Do not merge PR C or close #107 until exact-head CI, independent review, and owner visual acceptance all pass.
