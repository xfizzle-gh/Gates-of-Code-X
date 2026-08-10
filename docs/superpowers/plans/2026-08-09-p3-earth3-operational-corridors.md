# P3 Earth3 Operational Corridors Implementation Plan

> **Execution:** Use `subagent-driven-development` task by task. Every task starts with a failing test, receives a fresh implementation review, and is committed independently. Do not merge or rebase `main`; the authorized base remains `d16e7b145db82180d628bc9c0a636ebbab51db3c`.

**Goal:** Enable only the owner-approved 65-edge Earth3 operational corridor batch, connect all eleven P2 starting formations, and prove deterministic gameplay and persistence without modifying frozen P1 authority or P2 content.

**Authority:** Issue #141 comment `5234226059` approves proposal commit `1c51766f4c099d3307db70cffec815772b314d21`, allowlist SHA-256 `08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965`, rollback batch `p3-batch-001`, bidirectional traversal cost `1000`, and supply eligibility. All 8,690 other land candidates remain disabled; 1,494 non-land/nonselectable structural edges remain excluded.

**Architecture:** Add a separately versioned P3 authority record and generated operational graph asset. The runtime accepts the graph only through a fixed-path, exact-byte authenticated loader. Approved corridor edges retain their stable candidate-derived IDs but use a new `approved` authority class. Earth3 production construction wraps the frozen P2 builder; raw P2 saves receive one atomic deterministic migration after authentication. Existing P3 state never receives position auto-repair. Gameplay continues through operational orders only, so polygon adjacency cannot become a fallback.

---

## Frozen invariants

- Preserve the authorized merge base and accepted P2 ancestry; do not merge, rebase, or cherry-pick later `main`.
- Preserve exact bytes for P1 authority/assets and all eleven `src/gates_of_codex/data/earth3_v1/*.json` P2 bundle files.
- Do not alter P2 formation identity, starting province, faction, ownership, site intent, or bundle provenance.
- Never select routes from geometry at runtime. The 65 approved IDs and endpoint pairs are explicit authority data.
- Never enable an unlisted edge. Disabled candidate IDs are authenticated as the complete 8,690-item complement.
- Keep `CampaignEngine.move_or_attack` blocked for Earth3; P3 uses operational movement/order APIs only.
- Stop after one draft P3 PR and independent exact-head review request. Do not begin P4.

## Task 1: Pin frozen inputs and establish red authority-contract tests

**Files:**
- Create: `tests/test_earth3_p3_authority.py`
- Create: `tests/fixtures/earth3_p3_frozen_hashes.json`

**Steps:**

1. Add tests that hash the P1 production authority, P1 embedded map assets, proposal inventory, and all eleven P2 bundle files.
2. Assert the authorized base metadata, approval comment ID, proposal commit, allowlist digest, rollback batch, counts, costs, directionality, and supply policy.
3. Assert the proposal is still non-enabling and that no P3 authority/graph exists yet.
4. Run `pytest -q tests/test_earth3_p3_authority.py` and capture the expected red failure.
5. Commit the tests and frozen-hash fixture.

## Task 2: Add the explicit P3 authority record and deterministic graph builder

**Files:**
- Create: `config/earth3/p3_operational_authority.json`
- Create: `tools/earth3/build_p3_operational_graph.py`
- Create: `godot/assets/maps/earth3_europe_mediterranean/operational/operational_graph.json`
- Modify: `tests/test_earth3_p3_authority.py`
- Create: `tests/test_earth3_p3_graph_build.py`

**Steps:**

1. Expand the red tests to require all 65 ordered edge records, exact stable IDs/endpoints, exact approval provenance, graph raw SHA-256, and complete disabled-ID digest/count.
2. Add adversarial fixtures/tests for missing, extra, reordered, duplicate, reversed, endpoint-mutated, cost-mutated, supply-mutated, rollback-mutated, hash-mutated, and unapproved edge records.
3. Implement the authority record directly from the approved proposal. Do not rediscover the allowlist.
4. Implement a deterministic builder that validates every explicit pair against frozen topology, derives presentation-only node geometry deterministically, binds existing P2 site intents, and emits canonical graph bytes.
5. Ensure the graph contains exactly 64 nodes and 65 enabled `approved` corridor edges; unapproved candidates are absent and remain authenticated-disabled.
6. Run the builder twice into temporary outputs and byte-compare both outputs with the committed asset.
7. Run the focused authority/build tests and commit.

## Task 3: Add fail-closed P3 schema and exact-byte loader

**Files:**
- Modify: `src/gates_of_codex/operational_schema.py`
- Create: `src/gates_of_codex/earth3_operational.py`
- Modify: `src/gates_of_codex/operational_position.py`
- Modify: `tests/test_earth3_p3_authority.py`
- Create: `tests/test_earth3_p3_loader.py`

**Steps:**

1. Add red tests proving an approved corridor is legal only when enabled and carries the exact approval metadata, cost, directionality, supply flag, and rollback batch.
2. Add loader tests proving fixed paths and exact raw bytes are mandatory. Reject arbitrary paths, missing files, path traversal, unknown fields, malformed JSON, hash mismatches, version mismatches, and every adversarial mutation from Task 2.
3. Add `EdgeAuthority.APPROVED` with narrow validation rules; leave candidate corridors disabled and authored legacy behavior unchanged.
4. Implement `earth3_operational.py` with pinned authority/graph identities, independent semantic validation, fixed-path reads, and no partial state mutation on failure.
5. Route P3 Earth3 graph loading through the authenticated loader. Raw P2 state still has no graph.
6. Run focused schema/loader tests and commit.

## Task 4: Implement atomic deterministic P2-to-P3 migration

**Files:**
- Modify: `src/gates_of_codex/earth3_bootstrap.py`
- Modify: `src/gates_of_codex/earth3_operational.py`
- Modify: `src/gates_of_codex/operational_position.py`
- Modify: `src/gates_of_codex/state_io.py`
- Create: `tests/test_earth3_p3_migration.py`

**Steps:**

1. Add red tests for raw P2 construction/load migration to exact stable anchor positions for all eleven formations.
2. Prove migration occurs only after complete authority authentication; every failure leaves the caller-owned state and save bytes unchanged.
3. Prove repeated migration is idempotent, order independent, and byte deterministic.
4. Prove already-P3 state rejects missing, duplicate, unknown, or invalid positions rather than auto-repairing them.
5. Keep the original P2 validator strict when no P3 authority metadata is present. Add a separate authenticated P3 extension validator.
6. Implement the atomic migration by constructing and validating a replacement state before returning it; never progressively mutate the source.
7. Run migration/P2 compatibility tests and commit.

## Task 5: Enable Earth3 production construction without changing frozen P2 content

**Files:**
- Modify: `src/gates_of_codex/scenario.py`
- Modify: `src/gates_of_codex/earth3_bootstrap.py`
- Modify: `src/gates_of_codex/earth3_operational.py`
- Create: `tests/test_earth3_p3_scenario.py`

**Steps:**

1. Add red tests proving the direct P2 builder still emits its original P2-only state while production Earth3 construction emits authenticated P3 state.
2. Assert exact P2 formation/site/ownership projections are unchanged under the P3 wrapper.
3. Assert all eleven positions map to approved nodes and each has at least one legal operational route.
4. Assert the 65-edge graph is one connected 64-node component with both approved maneuver loops and the exact three-edge Zaporizhzhia-to-Donetsk approach.
5. Implement a production wrapper around the frozen P2 builder and switch only the Earth3 scenario registry entry to that wrapper.
6. Assert legacy polygon movement remains rejected even for polygon-adjacent provinces.
7. Run scenario/P2 compatibility tests and commit.

## Task 6: Prove player movement, AI routing, objectives, and disabled-edge enforcement

**Files:**
- Create: `tests/test_earth3_p3_movement.py`
- Modify narrowly if required: `src/gates_of_codex/operational_movement.py`
- Modify narrowly if required: `src/gates_of_codex/operational_ai.py`

**Steps:**

1. Add red integration tests issuing player movement from each of the eleven starting nodes over an approved edge.
2. Prove multi-hop pathfinding reaches each P2 objective cluster and uses only allowlisted IDs.
3. Prove AI routing is deterministic under shuffled node/edge insertion order and selects only legal approved edges.
4. Prove the two maneuver loops offer alternate routes after one approved edge is blocked.
5. For representative and exhaustive IDs, prove every one of the 8,690 disabled candidates cannot be traversed, injected, or resolved.
6. Prove polygon adjacency and geometry never create an edge or route.
7. Make only the narrow runtime changes needed to recognize authenticated `approved` edges.
8. Run movement/AI tests and commit.

## Task 7: Prove operational supply over the approved network

**Files:**
- Create: `tests/test_earth3_p3_supply.py`
- Modify narrowly if required: `src/gates_of_codex/operational_supply.py`

**Steps:**

1. Add red tests binding the existing P2 supply-hub intents to their authenticated graph nodes.
2. Prove all eleven starting formations receive the expected opening supply state through approved, supply-eligible routes.
3. Permit neutral unoccupied transit nodes but reject hostile-owned/hostile-occupied nodes; do not change polygon ownership.
4. Prove `supply_eligible=false`, disabled, blocked, candidate, unapproved, or unauthenticated edges cannot carry supply.
5. Prove deterministic supply results under repeated refresh and shuffled graph order.
6. Implement the narrow neutral-transit rule in operational supply only, with hostile endpoints remaining closed.
7. Run supply and prior S7/S8 compatibility tests and commit.

## Task 8: Prove contact, swept interception, pending battle, and retreat

**Files:**
- Create: `tests/test_earth3_p3_combat_flow.py`
- Modify narrowly if required: `src/gates_of_codex/operational_contact.py`
- Modify narrowly if required: `src/gates_of_codex/operational_interception.py`
- Modify narrowly if required: `src/gates_of_codex/operational_retreat.py`

**Steps:**

1. Add a deterministic Zaporizhzhia-to-Donetsk three-edge approach test.
2. Prove hostile contact and swept interception occur on the authenticated route, not from polygon adjacency.
3. Prove interception produces exactly one pending battle with stable participants, location, route provenance, and deterministic serialization.
4. Resolve/seed the battle result as existing APIs require, then prove retreat selects only a legal approved edge and cannot use disabled candidates or polygon neighbors.
5. Ensure retreat recognizes approved corridor authority without weakening legacy authored-route validation.
6. Run contact/interception/retreat/battle-generation tests and commit.

## Task 9: Prove save/load and fail-closed persistence

**Files:**
- Modify: `src/gates_of_codex/state_io.py`
- Create: `tests/test_earth3_p3_persistence.py`

**Steps:**

1. Add red round-trip tests for initial P3 state, in-transit orders, contact/interception state, pending battle, resolved retreat, and supply state.
2. Assert stable IDs, route provenance, P3 authority identities, positions, orders, and battle data survive byte-deterministic save/load.
3. Prove raw P2 saves migrate deterministically once; authenticated P3 saves never auto-repair.
4. Prove tampered authority, graph, route, position, cost, supply, approval, or rollback metadata fails before returning a state.
5. Prove failed loads do not overwrite or rewrite the source save.
6. Implement only the required persistence hooks and run focused tests; commit.

## Task 10: Run frozen-authority, compatibility, determinism, and full verification

**Files:**
- Modify: `docs/audits/p3-first-corridor-route-proposal.md`
- Create: `docs/audits/p3-first-corridor-verification.md`

**Steps:**

1. Recompute and compare every frozen P1 and P2 file hash against Task 1.
2. Run the deterministic graph build at least twice and byte-compare results.
3. Run focused P3 tests plus existing S3-S10 operational suites.
4. Run the complete test suite in the pinned Python 3.11 environment.
5. Run repository validation/lint/type-check commands required by CI.
6. Record exact commands, versions, counts, hashes, and outcomes in the verification audit.
7. Update the proposal status from non-enabling proposal to implemented-by-authorized-batch without altering the original approved facts.
8. Commit verification evidence.

## Task 11: Independent branch review and exact-head remediation

**Files:**
- Modify only files required by confirmed review findings.

**Steps:**

1. Dispatch an independent whole-branch reviewer with the approved authority contract, base commit, diff, and verification evidence.
2. Require explicit review of authority boundaries, mass-enablement risk, geometry fallback, migration atomicity, persistence, and frozen-byte preservation.
3. Resolve every valid finding with a new red test first; rerun affected focused suites.
4. Repeat independent review until no blocking findings remain.
5. Run final full verification at the exact reviewed head.

## Task 12: Publish one draft PR and stop before P4

**Files:**
- No implementation changes after exact-head verification except review-driven fixes followed by re-verification.

**Steps:**

1. Confirm the branch merge-base is still `d16e7b145db82180d628bc9c0a636ebbab51db3c` and no unrelated `main` commits were merged or rebased.
2. Push the exact verified head.
3. Open one draft PR referencing #176 and #141, approval comment `5234226059`, proposal commit, allowlist digest, rollback batch, frozen hashes, and exact verification evidence.
4. Record both the authorized base and the current live `main` independently in the PR body.
5. Wait for CI on the exact head and attach the exact-head results.
6. Request an independent GitHub review of that exact head.
7. Leave the PR draft and unmerged. Do not mark ready, merge, or begin P4.
