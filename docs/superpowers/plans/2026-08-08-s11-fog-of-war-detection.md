# S11 Fog of War and Detection Implementation Plan

> **For agentic workers:** execute this plan in order. Each PR is independently reviewed and merged before the next branch is created. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic observer-scoped Fog of War, last-known contacts, AI information parity, and Godot presentation without changing true campaign simulation authority.

**Architecture:** Python stores one authoritative campaign plus deterministic coalition-scoped knowledge records. Persisted knowledge refresh occurs only inside authoritative mutation transactions immediately before atomic save. Snapshot and AI observation projection are pure and read-only. A restricted immutable planning view is passed to a pure AI planner; a separate executor uses true state only to validate and commit already-ranked intents. Godot consumes only the filtered schema-14 snapshot and renders current and stale contacts without calculating detection.

**Tech stack:** Python 3.11+, dataclasses, JSON campaign persistence, existing operational graph authority, unittest/pytest, Godot 4.7 GDScript, existing SceneTree and screenshot harnesses.

## Global constraints

- Initial docs base is exactly S10 merge `cbef4db96f04d26f4127278041f717691712d7eb`.
- Follow-up branches start from the exact accepted merge of the preceding S11 PR.
- True `CampaignState` remains the only simulation state.
- No pixel LOS, detection RNG, terrain/weather modifiers, false contacts, electronic warfare, spies, or air reconnaissance in the thin slice.
- Province ownership remains public.
- Enemy exact orders and destinations are never exposed.
- Coalition allies share one observation scope in the thin slice.
- Schema-5 campaigns reject factions in multiple alliances.
- Fog of War On supports exactly one human-controlled faction; hotseat/remote multiplayer requires Fog of War Off.
- Campaign schema advances from 4 to 5 only in PR B.
- Frontend schema advances from 13 to 14 only in PR B.
- FOW Off preserves current behavior.
- Do not modify Earth3 geography/assets, route authority, OpenGS evaluation, S8 supply mechanics, S9 contact/Ambush/retreat rules, S10 movement presentation authority, or GoH tactical behavior.

## Locked detection constants

PR B must implement these exact constants and must not substitute heuristics:

```python
INITIAL_RECON_TEMPLATE_IDS = frozenset({
    "nato-us-airborne",
    "nato-gbr-battlegroup",
    "ukr-air-assault",
    "rusa-vdv",
})

ELIGIBLE_OBSERVATION_SITE_KINDS = frozenset({"observation", "command"})
```

`StrategicFormation.recon_capability: bool = False` is persisted on the on-map formation. New bundled campaigns and schema-4 migration set it true only for the exact template-ID whitelist. Custom scenarios may explicitly set it. No unit-name, display-name, roster, doctrine, battalion-type, or preferred-category inference is allowed.

A site contributes only when it is authored, has one of the exact eligible kinds, resolves to an authored route node, is controlled by the observer coalition, and is not tagged `metadata.synthetic_anchor_control_site: true`. Synthetic control anchors are always excluded.

Unique source counts use:

- `R`: distinct recon-capable strategic formation IDs in coverage;
- `S`: distinct eligible authored site IDs in coverage.

The complete pre-Ambush table is:

| Direct contact | R | S | Tier |
|---|---:|---:|---|
| yes | any | any | `fully_observed` |
| no | 0 | 0 | `unknown` |
| no | 0 | 1 | `contact` |
| no | 0 | 2+ | `identified` |
| no | 1 | 0 | `identified` |
| no | 1 | 1+ | `assessed` |
| no | 2+ | any | `assessed` |

Duplicate reports from one source ID do not stack. Non-contact detection is capped at `assessed`. Prepared Ambush reduces the resulting non-contact tier by exactly one step.

---

## PR A: Lock the design contract

**Branch:** `feat/s11-fog-of-war-design`

**Files:**

- Modify only: `docs/superpowers/specs/2026-08-08-s11-fog-of-war-detection-design.md`
- Modify only: `docs/superpowers/plans/2026-08-08-s11-fog-of-war-detection.md`

- [x] **Step 1: Record owner authorization on #107**

Lock launch phasing, graph-first detection, coalition sharing, AI parity, and the three-PR delivery chain.

- [x] **Step 2: Write the initial design and plan**

Record information tiers, Ambush concealment, last-known behavior, schemas, frontend redaction, AI fairness, and explicit non-goals.

- [x] **Step 3: Address independent review `4889696294`**

Lock all of the following in both documents:

1. exact `StrategicFormation.recon_capability` ownership, default, migration, and four-template initial whitelist;
2. exact authored site kinds `observation` and `command`, valid-node requirement, coalition-control requirement, and unconditional synthetic-anchor exclusion;
3. complete `(direct, R, S)` source-combination table, deduplication, sorted sources, and `assessed` cap;
4. persisted refresh only after authoritative mutation and before the same atomic save;
5. pure byte-neutral snapshot and AI projection;
6. full opaque-contact SHA-256 formula, collision failure, reacquisition, promotion rekey, validation, and same-location multiplicity;
7. confirmed witnessed removal versus unseen stale-record lifecycle and no inferred merge/split lineage;
8. immutable restricted `OperationalPlanningView`, pure planner, and no-rerank true-state executor;
9. Fog-on single-player-only policy;
10. schema-5 rejection of factions in multiple alliances.

- [ ] **Step 4: Inspect the corrected docs-only diff**

Confirm the branch still contains exactly these two Markdown files and no runtime, test, workflow, Godot, generated, or evidence changes.

- [ ] **Step 5: Run exact-head CI**

Record the exact corrected head and workflow run. Full repository CI remains required even though the correction is docs-only.

- [ ] **Step 6: Reply to every review thread**

For each thread, cite the exact corrected head and the section that locks the requested behavior. Leave all threads unresolved for independent confirmation.

- [ ] **Step 7: Request another exact-head independent review and stop**

Keep PR #167 draft and unmerged. Do not create PR B until PR A is accepted and merged.

---

## PR B: Add Python observation authority and AI parity

**Branch after PR A merge:** `feat/s11-fog-of-war-authority`

### Task B1: Add strict persisted observation models and scope validation

**Files:**

- Modify: `src/gates_of_codex/models.py`
- Modify: `src/gates_of_codex/state_io.py`
- Create: `src/gates_of_codex/observation.py`
- Create: `tests/test_s11_observation_model.py`
- Modify or create focused state-I/O migration tests under `tests/`

**Interfaces:**

- `InformationTier` enum with `unknown`, `contact`, `identified`, `assessed`, `fully_observed`.
- `KnowledgeRecord` with authority-only `subject_formation_id`, tier fields, source IDs, visibility state, and last-seen data.
- `StrategicFormation.recon_capability`.
- `CampaignState.fog_of_war_enabled`.
- `CampaignState.knowledge_by_observer`.
- `observer_scope_id(state, faction)`.
- Strict record, alliance, and single-human validation.

- [ ] Write failing tests for exact enum ordering and rejection of persisted `unknown` records.
- [ ] Write failing tests for tier-required and tier-forbidden fields.
- [ ] Write failing tests for sorted unique source labels and duplicate-subject rejection.
- [ ] Write failing observer-scope tests for zero alliance, one alliance, and multiple-alliance rejection.
- [ ] Write failing schema-5 validation tests proving overlapping alliance membership always fails.
- [ ] Write failing Fog-on tests for zero, one, and multiple human-controlled factions; only one must pass.
- [ ] Write FOW-Off hotseat parity tests proving multiple human factions remain legal only when filtering is Off.
- [ ] Run focused tests and verify RED.
- [ ] Implement only the enum, dataclass, campaign fields, observer-scope validation, and play-mode validation.
- [ ] Add schema-4 migration tests proving Fog defaults Off and knowledge defaults empty.
- [ ] Add exact recon migration tests: the four whitelisted template IDs become true; every other or missing template ID becomes false.
- [ ] Add tests proving schema-5 loads preserve persisted recon booleans and do not recompute from template categories.
- [ ] Add custom-scenario tests for explicit true and omitted/false values.
- [ ] Add schema-5 deterministic save/load tests.
- [ ] Run model and state-I/O tests until GREEN.
- [ ] Commit: `feat: add persisted S11 knowledge model`.

### Task B2: Implement exact source authority and deterministic tier combination

**Files:**

- Modify: `src/gates_of_codex/observation.py`
- Create: `tests/test_s11_detection_sources.py`
- Create: `tests/test_s11_detection_table.py`

**Interfaces:**

- exact initial recon-template constant;
- exact eligible-site-kind constant;
- source coverage indexes;
- pure current-detection calculation;
- deterministic tier combination before Ambush.

- [ ] Write tests proving only the persisted recon boolean is runtime authority.
- [ ] Prove unit/display/roster/doctrine/preferred-category substrings cannot grant recon.
- [ ] Write authored-site tests for exact kinds `observation` and `command`.
- [ ] Write rejection/non-source tests for `objective`, `capital`, `port`, `airfield`, supply, recruitment, generic control, and unknown kinds.
- [ ] Write tests requiring valid authored `route_node_id` and observer-coalition control.
- [ ] Write tests proving synthetic anchors never contribute, even if their kind is altered to an eligible value.
- [ ] Write graph-coverage tests for node source, incident edges, opposite endpoints, and on-edge recon coverage without adjacent-edge spillover.
- [ ] Parameterize every row of the complete `(direct, R, S)` table.
- [ ] Add duplicate-source tests proving one source ID counts once across coalition members/code paths.
- [ ] Add source-order tests proving stable `(source_kind, source_id)` ordering.
- [ ] Add tests proving additional non-contact sources never exceed `assessed`.
- [ ] Add prepared-Ambush tests applied after source combination and excluded from direct-contact reduction.
- [ ] Add no-graph province-fallback cases using the same combination table.
- [ ] Implement the minimum pure source and tier calculation.
- [ ] Run focused detection/contact/Ambush tests until GREEN.
- [ ] Commit: `feat: compute deterministic S11 detection tiers`.

### Task B3: Implement opaque contact identity and lifecycle

**Files:**

- Modify: `src/gates_of_codex/observation.py`
- Create: `tests/test_s11_contact_identity.py`
- Create: `tests/test_s11_last_known.py`

**Interfaces:**

- `opaque_contact_id(observer_scope_id, subject_formation_id)` using the exact full SHA-256 formula;
- `contact:<opaque_id>` and `formation:<subject_id>` keys;
- deterministic promotion and reacquisition;
- `ObservationMutationContext` carrying witnessed removals;
- retained stale records.

- [ ] Write an exact known-vector test for `contact-<full 64 lowercase hex digest>`.
- [ ] Prove different observer scopes produce different opaque IDs for one subject.
- [ ] Prove the full digest is not truncated.
- [ ] Write a collision-injection test that raises `opaque_contact_collision` before save and never overwrites.
- [ ] Write validation tests for opaque digest mismatch, formation-key mismatch, duplicate subject, dual opaque/formation keys, and persisted unknown records.
- [ ] Write same-location tests with two anonymous enemy formations; two distinct sorted contact records must remain.
- [ ] Write unidentified stale/reacquisition tests proving stable opaque key reuse.
- [ ] Write contact-to-identified promotion tests proving atomic rekey, one merged history, and no duplicate marker record.
- [ ] Prove promoted identity remains known after lower-tier reacquisition in the no-decay slice.
- [ ] Write tests for currently hidden movement leaving the stale location fixed.
- [ ] Write confirmed-removal tests for prior full observation, direct battle participation, and explicit witnessed removal; the record must be deleted in the same transaction.
- [ ] Write unseen-removal tests proving the record remains stale.
- [ ] Write tests proving no merge/split lineage is inferred from location, name, faction, or battalion membership.
- [ ] Implement contact identity, promotion, stale retention, and witnessed-removal handling.
- [ ] Run focused persistence and projection tests until GREEN.
- [ ] Commit: `feat: persist S11 contact identity and lifecycle`.

### Task B4: Enforce mutation-only persisted refresh and pure projections

**Files:**

- Modify: `src/gates_of_codex/observation.py`
- Modify only the narrow mutation/service boundaries that already perform atomic campaign save.
- Create: `tests/test_s11_refresh_transactions.py`
- Create: `tests/test_s11_projection_purity.py`

**Interfaces:**

- `refresh_all_observer_knowledge(state, mutation_context)` for mutation transactions only;
- `project_operational_observation(state, observer_faction)` as a pure read;
- one fixed transaction order: mutate, collect context, refresh once, validate, atomic save.

- [ ] Instrument refresh and write failing tests proving exactly one refresh after each observation-relevant mutation and immediately before atomic save.
- [ ] Cover campaign creation/migration save, operational tick, contact/Ambush/site capture, battle auto-resolve, verified external import, end turn, and formation removal boundaries.
- [ ] Write failure tests proving refresh/validation failure preserves the prior campaign file.
- [ ] Write tests proving no refresh occurs during snapshot export.
- [ ] Write tests proving no refresh occurs during AI planning.
- [ ] Compare canonical campaign bytes before and after repeated observation projections.
- [ ] Compare canonical campaign bytes before and after repeated frontend exports.
- [ ] Compare canonical campaign bytes before and after repeated AI planning calls.
- [ ] Prove pure projection does not normalize, sort in place, or mutate knowledge/source collections.
- [ ] Implement the mutation wrapper/call sites and pure projection boundary.
- [ ] Run state-I/O, operational movement, capture, battle import, frontend, and AI-focused tests.
- [ ] Commit: `feat: refresh S11 knowledge at save boundaries`.

### Task B5: Add observer-filtered frontend schema 14

**Files:**

- Modify: `src/gates_of_codex/frontend.py`
- Modify: only narrow frontend command adapters required to bind the sole authorized human observer.
- Create: `tests/test_s11_frontend_filter.py`
- Modify: existing frontend compatibility tests.

**Interfaces:**

- observer is derived from the sole human-controlled faction when FOW On;
- no arbitrary observer override in a human-facing export;
- `fog_of_war` metadata block;
- tier-redacted current enemy rows;
- `last_known_contacts` array;
- frontend schema 14.

- [ ] Capture a complete FOW-Off schema-13-equivalent baseline fixture.
- [ ] Write FOW-Off parity tests.
- [ ] Write tests rejecting an arbitrary observer override while FOW On.
- [ ] Write tests that unknown enemies and all dependent battalion, commander, stack, presentation, order, site-progress, and edge-traffic rows are absent.
- [ ] Write exact field-permission tests for contact, identified, assessed, and fully observed rows.
- [ ] Prove contact rows expose only opaque IDs and never authority-only `subject_formation_id`.
- [ ] Write side-channel tests for tooltips/presentation payloads, pending battle, command output, logs, and rejection reasons.
- [ ] Prove same-location anonymous contacts remain separate.
- [ ] Prove contact-to-identified promotion emits one row/marker identity.
- [ ] Prove confirmed destruction removes the row and unseen removal leaves a stale row.
- [ ] Implement one centralized redaction/filter pass.
- [ ] Bump frontend schema to 14 and retain FOW-Off compatibility.
- [ ] Prove repeated exports are byte-neutral to campaign persistence.
- [ ] Run frontend, writeback, S10 presentation-contract, and snapshot determinism tests.
- [ ] Commit: `feat: filter schema 14 by observer knowledge`.

### Task B6: Enforce operational AI non-omniscience structurally

**Files:**

- Modify: `src/gates_of_codex/operational_ai.py`
- Modify narrow AI call sites.
- Create: `tests/test_s11_ai_information_parity.py`
- Modify existing operational AI tests only where the explicit two-stage interface requires it.

**Interfaces:**

- immutable `OperationalPlanningView` with no `CampaignState` reference;
- `build_operational_planning_view(state, faction)` pure projection;
- `plan_operational_intents(view, faction, seed)` pure ranking;
- `validate_and_commit_operational_intents(state, faction, intents)` legality/commit only.

- [ ] Write type/shape tests proving the view has no campaign reference, callbacks, hidden enemy rows, hidden site progress, or hidden orders.
- [ ] Build an access-denial proxy that raises on undeclared field access and prove the pure planner passes.
- [ ] Write paired true-state tests whose hidden enemy positions, strength, stances, and orders differ but planning views match; intents must match exactly.
- [ ] Write tests proving a visible or last-known change may alter intents.
- [ ] Write executor tests proving intent order, goal, and route cannot be reranked, retargeted, or substituted.
- [ ] Prove hidden truth may only accept/reject an existing intent.
- [ ] Prove hidden-truth rejection uses sanitized observer-facing reasons and leaks no formation/location/stance detail.
- [ ] Preserve deterministic tie-breaking and existing movement commit authority.
- [ ] Keep FOW-Off on the same two-stage path using a complete planning view.
- [ ] Prove repeated planning is pure and campaign-byte neutral.
- [ ] Run full operational AI, movement, contact, capture, supply, and Ambush suites.
- [ ] Commit: `feat: plan operational AI from restricted views`.

### Task B7: Add campaign setup control and complete validation

**Files:**

- Modify: `src/gates_of_codex/entrypoint.py`
- Modify only the current campaign creation/service module needed to set the field explicitly.
- Modify: `README.md` only for final accepted CLI/setup behavior.
- Create or modify focused CLI tests.

- [ ] Add `--fog-of-war on|off` or repository-consistent equivalent, default Off.
- [ ] Prove old command lines retain Off behavior.
- [ ] Prove explicit On succeeds only with exactly one human-controlled faction.
- [ ] Prove On rejects hotseat/multiple-human configuration with the locked error.
- [ ] Prove Off retains multi-human compatibility.
- [ ] Prove explicit On initializes deterministic knowledge without changing true simulation results.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run Python compile checks and `git diff --check`.
- [ ] Inspect the complete diff against exact PR-A merge.
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
- [ ] Write same-location multiplicity tests for anonymous contacts.
- [ ] Write contact-to-identified promotion tests proving one marker.
- [ ] Write confirmed-destruction versus unseen-stale tests.
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

- [ ] Write active-scene failures for unknown absence, tier distinction, stale markers, multiplicity, promotion, removal lifecycle, and FOW-Off parity.
- [ ] Render current contacts without exact identity.
- [ ] Render identified and assessed contacts with only permitted fields.
- [ ] Render stale contacts at recorded locations with visible age/stale treatment.
- [ ] Ensure unknown enemies do not appear in stacks, panels, selection, hover, tooltips, counts, accessibility text, or cached models.
- [ ] Ensure direct-contact/pending-battle presentation continues to use S10 authoritative participants.
- [ ] Prove no observer-switch control exists in Fog-on single-player.
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
4. two anonymous contacts at one location;
5. identified marker after promotion without duplicate;
6. assessed strength-band marker;
7. fully observed direct contact;
8. stale last-known marker with age;
9. confirmed destroyed contact absent;
10. unseen removed contact still stale;
11. prepared Ambush remaining concealed before contact;
12. pending battle revealing authoritative participants;
13. coalition-shared contact.

- [ ] Add deterministic fixtures with no hidden truth in filtered payloads.
- [ ] Run headless fixture smoke.
- [ ] Generate true runtime captures at repository-standard viewport.
- [ ] Inspect every capture for clipping and information leakage.
- [ ] Commit only approved fixtures and evidence.

### Task C4: Validate and hand off

- [ ] Run new S11 Godot tests and all directly affected S10/map/writeback tests.
- [ ] Run full Python matrix because schema-14 fixtures cross the frontend boundary.
- [ ] Run Godot import/parse checks, screenshot generation, and `git diff --check`.
- [ ] Inspect complete diff against exact PR-B merge.
- [ ] Confirm no Python observation authority, campaign truth, Earth3, OpenGS, tactical behavior, or unrelated UI changed.
- [ ] Open one draft PR linked to #107.
- [ ] Stop for independent review and owner visual approval.

Do not merge PR C or close #107 until exact-head CI, independent review, and owner visual acceptance all pass.
