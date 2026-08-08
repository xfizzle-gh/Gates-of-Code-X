# S11 Fog of War and Detection Implementation Plan

> **For agentic workers:** execute this plan in order. Each PR is independently reviewed and merged before the next branch is created. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic observer-scoped Fog of War, last-known contacts, AI information parity, and Godot presentation without changing true campaign simulation authority or breaking Fog-off legacy campaigns.

**Architecture:** Python stores one authoritative campaign plus deterministic coalition-scoped knowledge records. S11 allocates campaign schema 11 because exact-base inspection shows pre-S11 systems already occupy campaign schemas 6 through 10. Persisted knowledge refresh occurs only inside authoritative mutation transactions immediately before atomic save. Snapshot and AI projection are pure. AI planning uses an immutable restricted view; a separate executor validates and commits already-ranked intents. Godot consumes only filtered frontend schema 14.

**Tech stack:** Python 3.11+, dataclasses, deterministic JSON persistence, existing operational graph authority, unittest/pytest, Godot 4.7 GDScript, existing SceneTree and screenshot harnesses.

## Global constraints

- PR A merged as exact commit `316edea97c24acf3490f2a0db9881ac1cb141569`.
- The schema-allocation correction branch starts from that exact PR-A merge.
- Runtime PR B must be recreated only from the exact accepted merge of the schema-allocation correction.
- True `CampaignState` remains the only simulation state.
- Campaign schema advances to 11 only in PR B; schemas 6 through 10 remain valid pre-S11 allocations.
- Every pre-S11 schema 10-or-earlier save with the complete S11 field set absent migrates to schema 11 with Fog Off and empty knowledge.
- Frontend schema advances from 13 to 14 only in PR B.
- Fog Off preserves current campaign behavior and compatibility.
- Fog On supports exactly one human-controlled faction; hotseat/remote multiplayer requires Fog Off.
- Overlapping alliance membership is rejected only when Fog is On, S11 knowledge records exist, or observer scope/projection is requested.
- A Fog-off campaign with empty S11 knowledge is not globally rejected for overlapping alliances.
- No pixel LOS, detection RNG, terrain/weather modifiers, false contacts, electronic warfare, spies, or air reconnaissance.
- Province ownership remains public.
- Enemy exact orders and destinations are never exposed.
- Coalition allies share one observation scope.
- Do not modify Earth3 geography/assets, route authority, OpenGS evaluation, S8 supply, S9 contact/Ambush/retreat, S10 presentation authority, or GoH tactical behavior.

## Locked detection constants

PR B must implement these exact constants:

```python
INITIAL_RECON_TEMPLATE_IDS = frozenset({
    "nato-us-airborne",
    "nato-gbr-battlegroup",
    "ukr-air-assault",
    "rusa-vdv",
})

ELIGIBLE_OBSERVATION_SITE_KINDS = frozenset({"observation", "command"})
```

`StrategicFormation.recon_capability: bool = False` is the persisted runtime authority. New bundled campaigns and both legacy migration paths set it true only for the exact template whitelist. No name, roster, doctrine, battalion-type, formation-kind, or preferred-category inference is allowed.

A site contributes only when authored, exactly `observation` or `command`, attached to a valid authored route node, controlled by the observer coalition, and not tagged `metadata.synthetic_anchor_control_site: true`.

Unique source counts are:

- `R`: distinct recon-capable strategic formation IDs in coverage;
- `S`: distinct eligible authored site IDs in coverage.

| Direct contact | R | S | Tier |
|---|---:|---:|---|
| yes | any | any | `fully_observed` |
| no | 0 | 0 | `unknown` |
| no | 0 | 1 | `contact` |
| no | 0 | 2+ | `identified` |
| no | 1 | 0 | `identified` |
| no | 1 | 1+ | `assessed` |
| no | 2+ | any | `assessed` |

Duplicate source IDs count once. Non-contact detection caps at `assessed`. Prepared Ambush reduces the resulting non-contact tier by one step.

---

## PR A: Lock the design contract — merged

**Branch:** `feat/s11-fog-of-war-design`

**Files:**

- Modify only: `docs/superpowers/specs/2026-08-08-s11-fog-of-war-detection-design.md`
- Modify only: `docs/superpowers/plans/2026-08-08-s11-fog-of-war-detection.md`

- [x] **Step 1: Record owner authorization on #107**

Lock launch phasing, graph-first detection, coalition sharing, AI parity, and the three-PR chain.

- [x] **Step 2: Write the initial design and plan**

Record tiers, Ambush concealment, last-known behavior, persistence, frontend redaction, AI fairness, and non-goals.

- [x] **Step 3: Address independent review `4889696294`**

Lock exact recon and site authority, source combination, mutation-only refresh, pure projections, opaque identities, removal lifecycle, restricted AI planning, Fog-on single-player policy, and deterministic observer scope.

- [x] **Step 4: Address compatibility review `4889771055`**

The first correction allocated schema 6 after identifying schema 5 as pre-S11. Exact-base implementation inspection later proved that schemas 6 through 10 were also already allocated.

- [x] **Step 5: Discover the exact-base schema collision**

After PR #167 merged, the required PR-B pre-implementation inspection proved that pre-S11 campaign systems already occupy schemas 6 through 10. The empty PR-B shell was stopped before runtime or test changes.

- [x] **Step 6: Stop the empty PR-B shell**

PR #171 was opened from the exact PR-A merge, changed no runtime or test files, documented the collision, and was closed unmerged with an empty net diff.

---

## PR A.1: Correct campaign schema allocation

**Branch:** `fix/s11-schema-11-design`

**Exact base:** `316edea97c24acf3490f2a0db9881ac1cb141569`

**Files:**

- Modify only: `docs/superpowers/specs/2026-08-08-s11-fog-of-war-detection-design.md`
- Modify only: `docs/superpowers/plans/2026-08-08-s11-fog-of-war-detection.md`

- [x] **Step 1: Lock the corrected schema contract**

Lock all of the following in both documents:

1. S11 campaign schema is 11, the next unused monotonic value;
2. schemas 6 through 10 remain valid pre-S11 allocations;
3. every schema 10-or-earlier save with the complete S11 field set absent migrates to schema 11;
4. all such migrations default Fog Off, empty knowledge, and whitelist-derived recon;
5. any S11 field in schema 10 or earlier fails with `unexpected_s11_fields_in_pre_s11_schema`;
6. schema 11 and later require the complete S11 field set;
7. Fog-off legacy compatibility remains unchanged;
8. overlapping alliances are accepted when Fog is Off, knowledge is empty, and no observer scope is requested;
9. overlapping alliances are rejected when Fog is On, S11 records exist, or observer scope/projection is requested;
10. migration and CLI tests cover every occupied pre-S11 schema 4 through 10 plus the complete range rule.

- [ ] **Step 2: Inspect the docs-only diff**

Confirm exactly the two S11 Markdown files differ and no runtime, test, workflow, Godot, generated, evidence, or PR-B files changed.

- [ ] **Step 3: Run exact-head CI**

Record exact corrected head and workflow run. Full repository CI remains required.

- [ ] **Step 4: Request exact-head independent review**

Post the exact corrected head, exact base, two-file scope, schema-allocation evidence, and required migration tests. Do not begin runtime work.

- [ ] **Step 5: Stop after the correction review**

Keep PR A.1 draft and unmerged. Do not recreate PR B until PR A.1 is independently accepted and merged.

---

## PR B: Add Python observation authority and AI parity

**Branch after PR A.1 merge:** recreate `feat/s11-fog-of-war-authority` from the exact PR-A.1 merge commit. Do not reuse the closed empty PR #171 branch.

### Task B1: Add schema-11 persisted models and conditional observer-scope validation

**Files:**

- Modify: `src/gates_of_codex/models.py`
- Modify: `src/gates_of_codex/state_io.py`
- Create: `src/gates_of_codex/observation.py`
- Create: `tests/test_s11_observation_model.py`
- Create or modify focused migration/state-I/O tests.

**Interfaces:**

- `InformationTier` enum: `unknown`, `contact`, `identified`, `assessed`, `fully_observed`.
- `KnowledgeRecord` with authority-only subject ID, tier fields, source IDs, visibility, and last-seen data.
- `StrategicFormation.recon_capability`.
- `CampaignState.fog_of_war_enabled`.
- `CampaignState.knowledge_by_observer`.
- campaign schema 11.
- `observer_scope_id(state, faction)` that rejects multiple memberships only when invoked.
- `validate_s11_observer_authority(state, *, observer_requested=False)` implementing conditional alliance validation.

- [ ] Write exact enum and tier-field validation failures.
- [ ] Reject persisted `unknown` records.
- [ ] Reject duplicate subjects and unsorted/duplicate source IDs.
- [ ] Test observer scope with zero alliance, one alliance, and multiple alliances.
- [ ] Prove multiple alliances fail when `observer_scope_id` is called.
- [ ] Prove Fog-on multiple alliances fail.
- [ ] Prove non-empty S11 knowledge with multiple alliances fails.
- [ ] Prove Fog-off, empty-knowledge, no-observer-request multiple alliances remain valid.
- [ ] Prove Fog-on requires exactly one human faction.
- [ ] Prove Fog-off hotseat remains compatible.
- [ ] Run focused tests and verify RED.
- [ ] Implement only models, schema-11 parsing/serialization, conditional scope validation, and play-mode validation.

#### Schema migration tests

- [ ] Add schema-4, schema-5, schema-6, schema-7, schema-8, schema-9, and schema-10 migrations to schema 11.
- [ ] Add schema-3-and-earlier coverage through the same pre-S11 path.
- [ ] Assert Fog Off and empty knowledge after every pre-S11 migration.
- [ ] Assert every schema 10-or-earlier save with the complete S11 field set absent is accepted as valid pre-S11 state.
- [ ] Assert all pre-S11 migrations apply the exact four-template recon whitelist.
- [ ] Assert all non-whitelisted or missing-template formations migrate to recon false.
- [ ] Reject any partial or complete S11 field set in schema 10 or earlier with `unexpected_s11_fields_in_pre_s11_schema`.
- [ ] Reject schema 11 or later missing any required S11 field.
- [ ] Prove schema-11-and-later loads preserve persisted recon booleans without recomputation.
- [ ] Add explicit custom schema-11 recon true/false tests.
- [ ] Add deterministic schema-11 save/load tests.
- [ ] Add Fog-off overlapping-alliance migration compatibility for schemas 4, 5, 6, 7, 8, 9, and 10.
- [ ] Add Fog-on overlapping-alliance rejection after enablement.
- [ ] Add S11-knowledge overlapping-alliance rejection.
- [ ] Run model and state-I/O tests until GREEN.
- [ ] Commit: `feat: add schema 11 S11 knowledge model`.

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
- deterministic pre-Ambush table.

- [ ] Prove only the persisted recon boolean is runtime authority.
- [ ] Prove strings/categories cannot grant recon.
- [ ] Test exact authored site kinds `observation` and `command`.
- [ ] Prove all other site kinds are non-sources.
- [ ] Require a valid authored route node and observer-coalition control.
- [ ] Prove synthetic anchors never contribute, even with an eligible kind.
- [ ] Test node, incident-edge, opposite-endpoint, and on-edge recon coverage.
- [ ] Parameterize every `(direct, R, S)` table row.
- [ ] Test duplicate-source deduplication and stable source ordering.
- [ ] Prove additional sources never exceed `assessed`.
- [ ] Test Ambush reduction after combination and no reduction for direct contact.
- [ ] Test no-graph province fallback with the same table.
- [ ] Implement minimum pure source/tier calculation.
- [ ] Run focused detection/contact/Ambush tests.
- [ ] Commit: `feat: compute deterministic S11 detection tiers`.

### Task B3: Implement opaque contact identity and lifecycle

**Files:**

- Modify: `src/gates_of_codex/observation.py`
- Create: `tests/test_s11_contact_identity.py`
- Create: `tests/test_s11_last_known.py`

**Interfaces:**

- exact full SHA-256 opaque ID formula;
- `contact:<opaque_id>` and `formation:<subject_id>` keys;
- deterministic promotion/reacquisition;
- `ObservationMutationContext` with witnessed removals;
- retained stale records.

- [ ] Add exact known-vector and full-digest tests.
- [ ] Prove observer scopes produce different IDs.
- [ ] Inject collision and require `opaque_contact_collision` before save.
- [ ] Reject digest mismatch, formation-key mismatch, duplicate subjects, dual keys, and persisted unknown rows.
- [ ] Preserve multiple anonymous contacts at one location as distinct sorted records.
- [ ] Reuse opaque key on unidentified reacquisition.
- [ ] Atomically rekey and merge history on first identification.
- [ ] Keep promoted identity known after lower-tier reacquisition.
- [ ] Keep stale location fixed while hidden truth moves.
- [ ] Delete records on confirmed witnessed removal.
- [ ] Retain stale records on unseen removal.
- [ ] Infer no merge/split lineage.
- [ ] Implement and run focused persistence/projection tests.
- [ ] Commit: `feat: persist S11 contact identity and lifecycle`.

### Task B4: Enforce mutation-only refresh and pure projections

**Files:**

- Modify: `src/gates_of_codex/observation.py`
- Modify only narrow mutation/service boundaries that already atomically save campaigns.
- Create: `tests/test_s11_refresh_transactions.py`
- Create: `tests/test_s11_projection_purity.py`

**Interfaces:**

- `refresh_all_observer_knowledge(state, mutation_context)` for mutation transactions only;
- `project_operational_observation(state, observer_faction)` as a pure read;
- fixed order: mutate, collect context, refresh once, validate, atomic save.

- [ ] Instrument exactly one refresh after each observation-relevant mutation and immediately before save.
- [ ] Cover creation/migration, operational tick, contact/Ambush/site capture, auto-resolve, verified import, end turn, and removal.
- [ ] Prove refresh/validation failure preserves the prior file.
- [ ] Prove no refresh during snapshot export or AI planning.
- [ ] Compare campaign bytes before/after repeated projections, exports, and plans.
- [ ] Prove projection does not sort or normalize collections in place.
- [ ] Prove Fog-off empty-knowledge paths do not derive observer scope.
- [ ] Prove Fog-off overlapping-alliance campaigns remain byte-stable through snapshots and ordinary commands.
- [ ] Implement boundaries and run state-I/O, movement, capture, battle import, frontend, and AI tests.
- [ ] Commit: `feat: refresh S11 knowledge at save boundaries`.

### Task B5: Add observer-filtered frontend schema 14

**Files:**

- Modify: `src/gates_of_codex/frontend.py`
- Modify only narrow adapters needed to bind the sole human observer.
- Create: `tests/test_s11_frontend_filter.py`
- Modify existing frontend compatibility tests.

**Interfaces:**

- observer derived from sole human faction when Fog On;
- no arbitrary observer override;
- `fog_of_war` block;
- tier-redacted enemy rows;
- `last_known_contacts`;
- frontend schema 14.

- [ ] Capture complete Fog-off baseline parity.
- [ ] Prove Fog-off schema-11 campaigns, including overlapping-alliance legacy campaigns, export complete current information without observer-scope derivation.
- [ ] Reject arbitrary observer override while Fog On.
- [ ] Reject overlapping alliances when filtered export requests observer scope.
- [ ] Remove unknown enemy and dependent battalion/commander/stack/presentation/order/site-progress/edge-traffic rows.
- [ ] Test exact fields for each tier.
- [ ] Never emit authority-only subject ID at contact tier.
- [ ] Test all frontend side channels.
- [ ] Preserve same-location multiplicity and one identity after promotion.
- [ ] Remove confirmed destruction and retain unseen stale rows.
- [ ] Implement centralized filtering.
- [ ] Bump frontend schema to 14 and retain Fog-off compatibility.
- [ ] Prove repeated exports are campaign-byte neutral.
- [ ] Run frontend, writeback, S10 presentation-contract, and snapshot tests.
- [ ] Commit: `feat: filter schema 14 by observer knowledge`.

### Task B6: Enforce operational AI non-omniscience structurally

**Files:**

- Modify: `src/gates_of_codex/operational_ai.py`
- Modify narrow AI call sites.
- Create: `tests/test_s11_ai_information_parity.py`

**Interfaces:**

- immutable `OperationalPlanningView` without campaign reference;
- pure `build_operational_planning_view`;
- pure `plan_operational_intents`;
- legality-only `validate_and_commit_operational_intents`.

- [ ] Prove the view contains no callbacks, hidden rows, hidden site progress, or hidden orders.
- [ ] Use an access-denial proxy against the planner.
- [ ] Prove identical views yield identical intents despite differing hidden truth.
- [ ] Prove visible/last-known changes may alter intents.
- [ ] Prove executor cannot rerank, retarget, substitute routes, or create intents.
- [ ] Permit hidden truth only to accept/reject an intent.
- [ ] Sanitize rejection reasons.
- [ ] Preserve deterministic tie-breaking and movement authority.
- [ ] Keep Fog Off on the same two-stage path with a complete view.
- [ ] Prove planning purity and byte neutrality.
- [ ] Run full AI, movement, contact, capture, supply, and Ambush suites.
- [ ] Commit: `feat: plan operational AI from restricted views`.

### Task B7: Add campaign setup control and complete compatibility validation

**Files:**

- Modify: `src/gates_of_codex/entrypoint.py`
- Modify only the campaign creation/service path needed to set Fog explicitly.
- Modify `README.md` only for accepted behavior.
- Create or modify focused CLI tests.

- [ ] Add `--fog-of-war on|off` or repository-consistent equivalent, default Off.
- [ ] Prove old command lines retain Fog Off.
- [ ] Prove representative schema-4 creation/load path upgrades to schema 11 with Fog Off.
- [ ] Prove pre-S11 schema-10 load path upgrades to schema 11 with Fog Off.
- [ ] Prove explicit On succeeds only with exactly one human faction.
- [ ] Prove On rejects multiple-human/hotseat configuration.
- [ ] Prove Off retains multi-human compatibility.
- [ ] Prove Fog-off overlapping-alliance campaigns remain accepted.
- [ ] Prove enabling Fog on an overlapping-alliance campaign is rejected.
- [ ] Prove loading non-empty S11 knowledge with overlapping alliances is rejected.
- [ ] Prove explicit observer-scope requests on overlapping alliances are rejected.
- [ ] Prove explicit On initializes deterministic knowledge without changing true simulation results.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Run compile checks and `git diff --check`.
- [ ] Inspect complete diff against exact PR-A merge.
- [ ] Confirm no Godot, Earth3, OpenGS, tactical export, or unrelated gameplay file changed.
- [ ] Open one draft PR linked to #107 and stop.

Do not begin PR C until PR B is independently accepted and merged.

---

## PR C: Present current and stale intelligence in Godot

**Branch after PR B merge:** `feat/s11-fog-of-war-presentation`

### Task C1: Add a simulation-free intelligence presenter

**Files:**

- Create: `godot/scripts/presentation/fog_of_war_presenter.gd`
- Create: `godot/scripts/tools/fog_of_war_presenter_test.gd`

- [ ] Parse only schema-14 `fog_of_war`, filtered formation rows, and `last_known_contacts`.
- [ ] Test tier styles, fixed stale locations, and stale ages.
- [ ] Prove absent exact fields are never synthesized.
- [ ] Test anonymous multiplicity, promotion to one marker, and confirmed versus unseen removal.
- [ ] Implement immutable presentation view models.
- [ ] Run focused GDScript tests.
- [ ] Commit: `feat: add S11 intelligence presenter`.

### Task C2: Integrate map, selection, panels, and tooltips

**Files:**

- Modify: `godot/scripts/main_color_id.gd`
- Modify: `godot/scripts/main_stack_panel.gd`
- Modify only narrow selection/tooltip consumers.
- Modify `map_markers.gd` only if required.
- Create: `godot/scripts/tools/fog_of_war_scene_test.gd`

- [ ] Test unknown absence, tier distinction, stale markers, multiplicity, promotion, removal lifecycle, and Fog-off parity.
- [ ] Render only permitted contact/identified/assessed fields.
- [ ] Render stale records at their stored locations with age.
- [ ] Remove unknown enemies from every UI/count/accessibility/cache path.
- [ ] Preserve S10 pending-battle participant presentation.
- [ ] Provide no Fog-on observer switch.
- [ ] Preserve color-ID hit testing, pan, zoom, and S10 playback.
- [ ] Run affected Godot suites.
- [ ] Commit: `feat: render S11 current and stale contacts`.

### Task C3: Add fixtures and owner evidence

Create deterministic schema-14 fixtures and runtime captures for:

1. Fog Off parity;
2. unknown absent;
3. contact-only;
4. two anonymous contacts at one location;
5. identified after promotion without duplicate;
6. assessed band;
7. fully observed contact;
8. stale contact with age;
9. confirmed destroyed absent;
10. unseen removed still stale;
11. prepared Ambush concealed;
12. pending battle participants;
13. coalition-shared contact.

- [ ] Ensure fixtures contain no hidden truth.
- [ ] Run headless fixture smoke.
- [ ] Generate repository-standard runtime captures.
- [ ] Inspect for clipping and leakage.
- [ ] Commit only approved fixtures/evidence.

### Task C4: Validate and hand off

- [ ] Run S11 Godot tests and directly affected S10/map/writeback tests.
- [ ] Run full Python matrix because schema-14 fixtures cross the frontend boundary.
- [ ] Run Godot import/parse, screenshots, and `git diff --check`.
- [ ] Inspect complete diff against exact PR-B merge.
- [ ] Confirm Python authority, campaign truth, Earth3, OpenGS, tactical behavior, and unrelated UI did not change.
- [ ] Open one draft PR linked to #107.
- [ ] Stop for independent review and owner visual approval.

Do not merge PR C or close #107 until exact-head CI, independent review, and owner visual acceptance pass.
