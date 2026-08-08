# S9A Deterministic Adjacent Retreat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace operational-campaign province fallback retreat with a deterministic, graph-valid, adjacent-only resolver shared by node and edge battle finalization.

**Architecture:** Add a pure policy module that selects an immutable retreat outcome from the authoritative graph, existing contact/capacity/diplomacy helpers, and S8 routes. Keep `CampaignEngine._finalize_positions` as the only applying coordinator, retain the no-graph legacy branch, and centralize origin metadata plus complete trapped elimination without adding movement, contact, blocking, or Ambush systems.

**Tech Stack:** Python 3.11+, standard-library dataclasses, existing operational fixed-point schema, `unittest`, JSON save/load integration, GitHub Actions.

## Global Constraints

- Implement S9A deterministic adjacent retreat only; do not begin S9B or S9C.
- Do not modify `tools/opengs_eval/**`, `docs/research/opengs-evaluation/**`, Earth3 authority/geography, #121, #129, #141 graph assets, S10 Godot presentation, S11 Fog of War, or S8 supply formulas.
- Candidate and disabled production corridors remain unavailable.
- Retreat is mandatory, once per losing strategic formation, with no pursuit, prompt, random roll, multi-edge path, or second pending battle.
- Ranking is recorded origin, then supplied, then integer movement cost, then stable node ID.
- The exact edge-origin rollback alone may ignore reverse direction; every other traversal gate remains authoritative.
- No-graph campaigns retain existing province retreat behavior unchanged.

---

### Task 1: Centralize persisted pre-contact origin metadata

**Files:**

- Create: `src/gates_of_codex/operational_retreat.py`
- Modify: `src/gates_of_codex/operational_interception.py`
- Modify: `src/gates_of_codex/operational_contact.py`
- Modify: `src/gates_of_codex/operational_movement.py`
- Test: `tests/test_operational_s9a_retreat.py`

**Interfaces:**

- Produces `RETREAT_ORIGIN_NODES_KEY = "operational_edge_retreat_nodes"`.
- Produces `record_retreat_origin_node(state, formation_id, node_id) -> None`.
- Produces `retreat_origin_node(state, formation_id) -> str | None`.
- Produces `clear_retreat_origin_nodes(state) -> None` and `clear_retreat_origin_node(state, formation_id) -> None`.
- Extends `try_create_node_contact_battle(state, seed_attacker, seed_defender, *, node_id: str, origin_province_id: str | None = None, retreat_origins: dict[str, str] | None = None) -> PendingBattle | None` additively.
- Extends `resolve_node_entry_contact(state, force, node_id: str, *, create_battle: bool = True, origin_province_id: str | None = None, origin_node_id: str | None = None) -> dict[str, Any]` additively.

- [ ] **Step 1: Add failing origin lifecycle and node save/load tests**

Create the S9A test module with graph/state builders adapted from S4/S6. Add tests that directly prove helper stability and that a successful moving node contact records the exact hop origin while failed/static contact invents nothing:

```python
def test_origin_helpers_use_existing_compatibility_key(self) -> None:
    state, _graph = self.make_state()
    record_retreat_origin_node(state, "sf-n", "node-a")
    self.assertEqual(
        {"sf-n": "node-a"},
        state.map_metadata["operational_edge_retreat_nodes"],
    )
    self.assertEqual("node-a", retreat_origin_node(state, "sf-n"))
    clear_retreat_origin_node(state, "sf-n")
    self.assertIsNone(retreat_origin_node(state, "sf-n"))

def test_node_contact_save_load_preserves_exact_origin(self) -> None:
    state = self.make_moving_node_contact()
    report = advance_operational_tick(state)
    self.assertTrue(report["battle_id"])
    expected = stable_node_id("a")
    self.assertEqual(expected, retreat_origin_node(state, "sf-attacker"))
    loaded = self.round_trip(state)
    self.assertEqual(expected, retreat_origin_node(loaded, "sf-attacker"))
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9AOriginTests -v
```

Expected: import or assertion failures because the helper module/signatures do not exist.

- [ ] **Step 3: Add minimal origin helpers and successful-contact recording**

Start `operational_retreat.py` with strict non-empty writes:

```python
RETREAT_ORIGIN_NODES_KEY = "operational_edge_retreat_nodes"

def record_retreat_origin_node(state, formation_id: str, node_id: str) -> None:
    fid, nid = str(formation_id).strip(), str(node_id).strip()
    if not fid or not nid:
        return
    store = state.map_metadata.setdefault(RETREAT_ORIGIN_NODES_KEY, {})
    if isinstance(store, dict):
        store[fid] = nid

def retreat_origin_node(state, formation_id: str) -> str | None:
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if not isinstance(store, dict):
        return None
    value = str(store.get(str(formation_id)) or "").strip()
    return value or None
```

Refactor edge contact writes to the helper. Pass accepted interval
`path_origin_node` values into node battle creation only after a pending battle
is constructed. Pass `_advance_formation_one_tick`'s `origin_node` through
`resolve_node_entry_contact`.

- [ ] **Step 4: Run origin tests and S4/S6 regressions GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9AOriginTests `
  tests.test_operational_s4_contact `
  tests.test_operational_s6_interception -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the metadata checkpoint**

```powershell
git add src/gates_of_codex/operational_retreat.py `
  src/gates_of_codex/operational_interception.py `
  src/gates_of_codex/operational_contact.py `
  src/gates_of_codex/operational_movement.py `
  tests/test_operational_s9a_retreat.py
git commit -m "feat: preserve S9A retreat origins"
```

### Task 2: Implement the deterministic graph candidate policy

**Files:**

- Modify: `src/gates_of_codex/operational_retreat.py`
- Modify: `tests/test_operational_s9a_retreat.py`

**Interfaces:**

- Produces `TRAPPED_NO_LEGAL_RETREAT = "trapped_no_legal_retreat"`.
- Produces immutable `OperationalRetreatCandidate` and `OperationalRetreatResolution`.
- Produces `resolve_operational_retreat(state, formation_id, *, encounter_node_id, encounter_edge_id, encounter_progress_milli) -> OperationalRetreatResolution`.
- Consumes existing graph `_indexes`, traversal assertions, diplomacy/contact helpers, S8 source/route helpers, and `formation_canonical_on_edge`.

- [ ] **Step 1: Add failing recorded-origin and candidate eligibility tests**

Add one-test-per-behavior methods:

| Test method | Exact fixture change and assertion |
|---|---|
| `test_valid_recorded_origin_is_absolute_priority` | Record friendly node `a`; provide a cheaper supplied fallback `c`; assert destination `a`. |
| `test_invalid_recorded_origin_falls_back_to_adjacent` | Make recorded node hostile-controlled; assert legal adjacent `c`. |
| `test_no_multi_edge_search` | Put the only friendly node two hops away; assert trapped reason. |
| `test_candidate_edge_is_rejected` | Make the sole adjacent edge authority `candidate`; assert trapped reason. |
| `test_disabled_edge_is_rejected` | Set `traversal_enabled=False`; assert trapped reason. |
| `test_metadata_blocked_edge_is_rejected` | Set `metadata.blocked=True`; assert trapped reason. |
| `test_illegal_one_way_fallback_is_rejected` | Orient one-way edge opposite retreat; assert trapped reason. |
| `test_exact_edge_origin_rollback_ignores_reverse_only` | Record endpoint `a` on one-way `a -> b` at edge contact; assert rollback to `a`. |
| `test_unrelated_fallback_obeys_direction` | Record invalid endpoint and expose unrelated reverse fallback; assert that fallback is absent/trapped. |
| `test_ferry_and_sea_fallbacks_are_unresolved` | Run subtests for `ferry`, `ferry_or_sea_lane`, and `sea_lane`; assert trapped reason. |
| `test_hostile_control_is_rejected` | Make destination province Russian-controlled; assert trapped reason. |
| `test_hostile_occupation_is_rejected` | Place a Russian formation at destination; assert trapped reason. |
| `test_stack_full_is_rejected` | Fill destination to graph rule capacity with allies; assert trapped reason. |
| `test_allied_control_uses_existing_diplomacy` | Add NATO/Ukraine alliance and Ukrainian-controlled destination; assert that destination. |
| `test_other_hostile_on_segment_prevents_second_contact` | Put a non-participant Russian formation on the retreat segment; assert trapped reason. |

Each test calls `resolve_operational_retreat` directly and asserts either the
exact `destination_node_id` or `reason == TRAPPED_NO_LEGAL_RETREAT`.

- [ ] **Step 2: Run eligibility tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9ACandidateTests -v
```

Expected: failures because the resolver does not exist.

- [ ] **Step 3: Implement candidate construction and filters**

Use immutable records with an exact public ranking key:

```python
@dataclass(frozen=True, slots=True)
class OperationalRetreatCandidate:
    node_id: str
    province_id: str
    edge_id: str
    supplied: bool
    movement_cost: int

    @property
    def rank_key(self) -> tuple[int, int, str]:
        return (0 if self.supplied else 1, self.movement_cost, self.node_id)

@dataclass(frozen=True, slots=True)
class OperationalRetreatResolution:
    formation_id: str
    destination_node_id: str | None = None
    destination_province_id: str | None = None
    reason: str = ""

    @property
    def eliminated(self) -> bool:
        return self.reason == TRAPPED_NO_LEGAL_RETREAT
```

For node contact, enumerate incident edges and call
`assert_edge_hop_legal(edge, origin=encounter_node, dest=other)`. For edge
contact, enumerate only endpoints and use the fixed-point cost:

```python
def _segment_cost(edge_cost: int, segment_milli: int) -> int:
    return (int(edge_cost) * int(segment_milli) + 999) // 1000
```

Recorded edge-origin rollback calls `assert_edge_traversable` instead of
`assert_edge_hop_legal`, but all other eligibility checks still run. Reject the
three ferry/sea kinds before ranking. Reduce parallel routes to the smallest
`(movement_cost, edge_id)` per node.

- [ ] **Step 4: Run candidate tests GREEN**

Run the candidate class command from Step 2. Expected: all methods pass.

- [ ] **Step 5: Add failing supply and tie-break tests**

| Test method | Exact fixture change and assertion |
|---|---|
| `test_supplied_adjacent_node_beats_unsupplied` | Author a NATO source route to higher-cost node `c`; leave cheaper `a` disconnected; assert `c`. |
| `test_grace_occupant_counts_as_supplied` | Put a same-faction grace formation at higher-cost `c`; assert `c` over unsupplied `a`. |
| `test_lower_integer_movement_cost_wins` | Make both candidates equally supplied with costs 900 and 1100; assert cost-900 node. |
| `test_stable_node_id_breaks_equal_cost_tie` | Make supply/cost equal; assert lexicographically smaller node ID. |
| `test_candidate_selection_ignores_insertion_order` | Build forward and reversed node/edge/formation dictionaries; assert identical resolution dataclasses. |

The supply fixture uses authoritative S8 province-source metadata and authored
routes. The grace fixture puts a same-faction occupant at one candidate with
`supplied=True`, `cut_off=False`, no source/route, and
`grace_ticks_remaining=1`.

- [ ] **Step 6: Run supply/ranking tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9ARankingTests -v
```

Expected: supplied/ranking assertions fail before route-table classification.

- [ ] **Step 7: Implement S8 classification and deterministic ranking**

Compute sources/routes once per call for the retreating faction. A node is
supplied when present in that route table or when a same-faction occupant at the
node has `supplied is True`. Sort all graph collections and select:

```python
best = min(candidates, key=lambda item: item.rank_key)
```

Use edge ID only when deterministically reducing multiple routes to the same
node, not as an additional cross-node ranking term.

- [ ] **Step 8: Run the complete focused resolver suite GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_operational_s9a_retreat -v
```

Expected: all current S9A tests pass.

- [ ] **Step 9: Commit the resolver checkpoint**

```powershell
git add src/gates_of_codex/operational_retreat.py tests/test_operational_s9a_retreat.py
git commit -m "feat: resolve deterministic adjacent retreats"
```

### Task 3: Integrate atomic placement, stance resets, and trapped cleanup

**Files:**

- Modify: `src/gates_of_codex/campaign.py`
- Modify: `src/gates_of_codex/operational_retreat.py`
- Modify: `tests/test_operational_s9a_retreat.py`
- Modify: `tests/test_strategic_formation_schema.py`

**Interfaces:**

- `CampaignEngine.apply_battle_result` and `apply_external_battle_result` return an additive immutable `BattleFinalizationReport` while existing callers may ignore it.
- `CampaignEngine._resolve_formation_after_battle` delegates graph losses to `resolve_operational_retreat` and preserves the existing no-graph province branch.
- Adds `CampaignEngine._eliminate_formation(force_id, *, reason) -> OperationalRetreatResolution`.
- Adds `BattleFinalizationReport(retreat_outcomes: tuple[OperationalRetreatResolution, ...] = ())` in `operational_retreat.py`.

- [ ] **Step 1: Add failing finalization and cleanup tests**

| Test method | Exact fixture change and assertion |
|---|---|
| `test_node_battle_retreats_loser_once` | Resolve a real node battle; assert one outcome and exact destination node. |
| `test_multi_battalion_formation_retreats_once_and_colocates` | Give the loser two battalions; assert one outcome and identical formation/member province. |
| `test_retreat_never_creates_second_pending_battle` | Resolve with a hostile elsewhere; assert final `state.pending_battle is None` and no new battle ID. |
| `test_trapped_elimination_returns_stable_reason` | Remove every eligible node; assert report reason `trapped_no_legal_retreat`. |
| `test_trapped_elimination_cleans_battalions_orders_position_and_commanders` | Add formation/battalion commanders, active order, position, and origin metadata; assert all records/reverse assignments cleaned and `state.validate()` succeeds. |
| `test_losing_forced_march_resets_to_operational` | Set force stance and locked stance to Forced March; assert both become Operational. |
| `test_losing_entrenched_resets_when_displaced` | Set losing force and order Entrenched; assert both become Operational. |
| `test_winning_entrenched_remains_unchanged` | Set winning force and order Entrenched; assert both remain Entrenched. |

The cleanup test creates both a formation commander and a battalion commander,
active move order, operational position, and origin metadata; after resolution
it calls `state.validate()` and asserts every reverse assignment is cleared.

- [ ] **Step 2: Run integration tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9AFinalizationTests `
  tests.test_strategic_formation_schema -v
```

Expected: old province fallback, missing report, or incomplete cleanup failures.

- [ ] **Step 3: Centralize finalization and elimination**

Collect outcomes in stable force-ID order. Apply successful graph results by
placing the force exactly at the returned node, synchronizing members, setting
unfinished orders to `blocked`, and setting member `movement_remaining = 0`.

Use one reset helper:

```python
if lost and current_stance in {
    FormationStance.FORCED_MARCH.value,
    FormationStance.ENTRENCHED.value,
}:
    force.stance = FormationStance.OPERATIONAL.value
    if force.move_order is not None and force.move_order.locked_stance:
        force.move_order = replace(
            force.move_order,
            locked_stance=FormationStance.OPERATIONAL.value,
        )
```

Before removing a battalion or force, clear commanders whose reverse assignment
points at that record. Remove every member using `_remove_battalion`, clear the
origin entry, and return the trapped resolution. Do not mutate ownership.

- [ ] **Step 4: Run finalization tests and S4 regressions GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9AFinalizationTests `
  tests.test_operational_s4_contact `
  tests.test_strategic_formation_schema -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the finalizer checkpoint**

```powershell
git add src/gates_of_codex/campaign.py `
  src/gates_of_codex/operational_retreat.py `
  tests/test_operational_s9a_retreat.py `
  tests/test_strategic_formation_schema.py
git commit -m "feat: finalize S9A retreats atomically"
```

### Task 4: Prove edge encounter and save/load integration

**Files:**

- Modify: `tests/test_operational_s9a_retreat.py`
- Modify: `src/gates_of_codex/campaign.py`
- Modify: `src/gates_of_codex/operational_retreat.py`

**Interfaces:**

- Consumes the same public resolver/finalization report from Tasks 2–3.
- No additional persisted fields.

- [ ] **Step 1: Add failing real encounter tests**

| Test method | Exact fixture change and assertion |
|---|---|
| `test_edge_cross_retreat_uses_recorded_origin` | Create opposing edge movement and lose as NATO; assert NATO returns to its recorded origin. |
| `test_edge_catchup_retreat_uses_recorded_origin` | Create hostile same-direction catchup and lose the rear/attacking side; assert its exact origin. |
| `test_edge_contact_save_load_preserves_deterministic_retreat` | Save/load after real edge pending battle; compare outcome and final state with an unround-tripped copy. |
| `test_node_contact_save_load_preserves_deterministic_retreat_result` | Save/load after real moving node pending battle; compare outcome and final state with an unround-tripped copy. |
| `test_multi_loser_allocation_is_insertion_order_independent` | Reverse losing formation insertion order with constrained capacity; assert identical per-formation outcome tuples. |

Create contact through `issue_move_order`, `commit_move_orders`,
`activate_committed_orders`, and `advance_operational_tick`; do not hand-build
the pending battle in save/load tests. Round-trip with `save_campaign` and
`load_campaign` before calling `CampaignEngine(state).apply_battle_result(winner)`.

- [ ] **Step 2: Run real encounter tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9AEncounterTests -v
```

Expected: at least the old edge/province placement or save/load result assertion fails.

- [ ] **Step 3: Pass exact encounter context through finalization**

Pass `pending.encounter_node_id`, `pending.encounter_edge_id`, and
`pending.encounter_progress_milli` into every losing formation's shared resolver.
Keep winner placement on the pending battle's exact node or canonical edge
progress. Clear the compatibility origin map once after all retreat outcomes and
before final state validation.

- [ ] **Step 4: Run focused S9A and S6 GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operational_s9a_retreat `
  tests.test_operational_s6_interception -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit encounter integration**

```powershell
git add tests/test_operational_s9a_retreat.py `
  src/gates_of_codex/campaign.py src/gates_of_codex/operational_retreat.py
git commit -m "test: prove S9A encounter retreat integration"
```

### Task 5: Document, validate, review, and publish the draft PR

**Files:**

- Create: `docs/operational-retreat.md`
- Modify: `docs/superpowers/plans/2026-08-07-s9a-deterministic-adjacent-retreat.md` to check completed task boxes
- Test: `tests/test_operational_s9a_retreat.py`

**Interfaces:**

- Documents candidate eligibility, ranking key, rollback exception,
  `trapped_no_legal_retreat`, stance resets, and compatibility boundaries.

- [ ] **Step 1: Add failing documentation contract test**

```python
def test_documented_contract_contains_locked_terms(self) -> None:
    body = Path("docs/operational-retreat.md").read_text(encoding="utf-8")
    for phrase in (
        "trapped_no_legal_retreat",
        "supplied, movement cost, stable node ID",
        "recorded pre-contact origin",
        "candidate corridors remain unavailable",
        "campaigns without an operational graph",
    ):
        self.assertIn(phrase, body)
```

- [ ] **Step 2: Run the documentation test and verify RED**

Run the single test by its final class/method name. Expected: missing file failure.

- [ ] **Step 3: Write the operational retreat document**

Describe the exact locked terms without extending into S9B/S9C.

- [ ] **Step 4: Run required local validation**

Run, in order:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_operational_s9a_retreat -v
.\.venv\Scripts\python.exe -m unittest tests.test_operational_s4_contact -v
.\.venv\Scripts\python.exe -m unittest tests.test_operational_s6_interception -v
.\.venv\Scripts\python.exe -m unittest tests.test_operational_s7_ai_orders -v
.\.venv\Scripts\python.exe -m unittest tests.test_operational_s8_supply -v
.\.venv\Scripts\python.exe -m unittest tests.test_strategic_formation_schema tests.test_operational_s2_positions -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\gates-of-codex.exe --help
.\.venv\Scripts\gates-of-codex-live.exe --help
```

Record exact focused and full counts.

- [ ] **Step 5: Audit the complete diff and protected paths**

Run:

```powershell
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
git status --short
```

Fail the audit if any protected OpenGS, Earth3, production graph, Godot, S10,
S11, #121, #129, or #141 path appears.

- [ ] **Step 6: Request code review and address all critical/important findings**

Review the exact `origin/main...HEAD` diff against the design and issue #106.
For every valid defect, add a failing regression test before changing production
code, then rerun the affected focused suite.

- [ ] **Step 7: Commit final docs/corrections and publish**

```powershell
git add docs/operational-retreat.md `
  tests/test_operational_s9a_retreat.py `
  src/gates_of_codex/campaign.py `
  src/gates_of_codex/operational_retreat.py `
  src/gates_of_codex/operational_contact.py `
  src/gates_of_codex/operational_interception.py `
  src/gates_of_codex/operational_movement.py
git commit -m "docs: record S9A retreat contract"
git push -u origin feat/s9a-deterministic-retreat
```

Open one draft PR against `main` that tracks but does not close #106. Include
base SHA, exact head, scope, counts, risks, and the disabled-candidate note.

- [ ] **Step 8: Update #106 and verify exact-head Actions**

Post the draft PR URL, base SHA, exact head, implemented S9A-only scope, test
counts, protected-path audit, and unresolved risks. Wait for the PR Actions run
at the exact head and record its URL and terminal status. Leave S9B/S9C and #106
open and do not merge.
