# S8 Operational Supply Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic operational-graph supply connectivity, persisted cut-off grace state, legacy degradation hooks, and an additive frontend summary for issue #105.

**Architecture:** A dedicated `operational_supply.py` resolves authoritative logical sources onto routing nodes, computes integer-cost directed routes with reverse multi-source Dijkstra, and refreshes versioned `StrategicFormation` state. Existing `supply.py` keeps all numeric recovery, drain, encirclement, and attrition formulas; no-graph campaigns retain their current province traversal and serialization behavior.

**Tech Stack:** Python 3.11+, standard-library `dataclasses`, `heapq`, `unittest`, existing fixed-point operational schema and JSON campaign/frontend contracts.

## Global Constraints

- Work only on `feat/s8-operational-supply` based on `be455985da4c4adcaaf7d7cf54f918b07d321fa7` or a later clean current-main base.
- Do not touch `tools/opengs_eval/**`, `docs/research/opengs-evaluation/**`, OpenGS workflows/tests/branches, Earth3 geography or water policy, issue #129 preview assets, issue #121 coastline work, or deferred Godot draw-call optimization.
- Candidate, disabled, metadata-blocked, or directionally illegal edges never carry supply.
- `ferry`, `ferry_or_sea_lane`, and `sea_lane` require `metadata.supply_capable is True`; do not synthesize open-sea connectivity.
- Use integer costs only and the route key `(total_cost, node_id_path, edge_id_path, source_hub_id)`.
- On-edge attachment uses `(C * segment_milli + 999) // 1000`; never use float or geometric distance.
- Only a completed operational tick consumes or begins grace; turn-start, save/load, and external-change refreshes are non-consuming.
- Preserve the exact persisted grace states approved in `docs/superpowers/specs/2026-08-07-s8-operational-supply-design.md`.
- Existing supply recovery, drain, encirclement, attrition, economy, fuel, recruitment, and damage formulas remain unchanged.
- Campaigns without a resolvable operational graph retain existing province supply behavior and do not serialize S8 fields.

---

### Task 1: Versioned formation state and strict serialization

**Files:**
- Modify: `src/gates_of_codex/models.py`
- Modify: `src/gates_of_codex/state_io.py`
- Create: `tests/test_operational_s8_supply.py`

**Interfaces:**
- Produces `StrategicFormation.supplied`, `cut_off`, `source_hub_id`, `route_cost`, `grace_ticks_remaining`, `last_supply_refresh_tick`, `last_supply_refresh_turn`, and `last_grace_consuming_tick`.
- Produces strict `_optional_supply_int(raw, name)` parsing in `state_io.py`.
- Preserves S8-field absence from `CampaignState.to_dict()` while `schema_version < 8`.

- [ ] **Step 1: Write failing serialization and legacy-omission tests**

```python
def test_s8_fields_round_trip_strictly(self):
    state = make_state()
    force = only_force(state)
    state.schema_version = 8
    force.supplied = False
    force.cut_off = True
    force.source_hub_id = None
    force.route_cost = None
    force.grace_ticks_remaining = 0
    force.last_supply_refresh_tick = 12
    force.last_supply_refresh_turn = 3
    force.last_grace_consuming_tick = 12
    loaded = campaign_from_dict(state.to_dict())
    self.assertFalse(only_force(loaded).supplied)
    self.assertEqual(12, only_force(loaded).last_grace_consuming_tick)

def test_schema7_no_graph_payload_omits_s8_fields(self):
    state = make_state(graph=None)
    payload = state.to_dict()
    row = next(iter(payload["strategic_formations"].values()))
    self.assertNotIn("supplied", row)
    self.assertNotIn("last_grace_consuming_tick", row)

def test_s8_optional_int_rejects_bool_string_and_float(self):
    payload = graph_campaign_payload()
    for bad in (True, "1", 1.0):
        payload["strategic_formations"]["sf-nato"]["route_cost"] = bad
        with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "route_cost"):
            campaign_from_dict(payload)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: FAIL because the S8 formation fields and strict parser do not exist.

- [ ] **Step 3: Add the minimal model and serializer implementation**

Add the fields with safe defaults to `StrategicFormation`, validate booleans, nullable IDs, non-negative integer costs/ticks, and extend `state_io.campaign_from_dict()` with strict parsing. Change `CampaignState.to_dict()` to remove these eight keys from strategic-formation rows whenever `schema_version < 8`:

```python
def to_dict(self) -> dict[str, Any]:
    payload = asdict(self)
    if self.schema_version < 8:
        for row in payload.get("strategic_formations", {}).values():
            for key in _OPERATIONAL_SUPPLY_FIELDS:
                row.pop(key, None)
    return payload
```

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: the Task 1 tests pass with no warnings.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- src/gates_of_codex/models.py src/gates_of_codex/state_io.py tests/test_operational_s8_supply.py
git diff --cached --check
git commit -m "feat(operational): add versioned S8 supply state"
```

### Task 2: Authoritative source bridge and supply-edge gates

**Files:**
- Create: `src/gates_of_codex/operational_supply.py`
- Modify: `tests/test_operational_s8_supply.py`

**Interfaces:**
- Produces immutable `OperationalSupplySource(source_hub_id, source_node_id, province_id, eligible_factions, source_kind)`.
- Produces immutable `OperationalSupplyDiagnostic(source_hub_id, province_id, reason)`.
- Produces `resolve_operational_supply_sources(state, faction) -> tuple[tuple[OperationalSupplySource, ...], tuple[OperationalSupplyDiagnostic, ...]]`.
- Produces `edge_is_supply_capable(edge) -> bool` and `assert_supply_edge_hop_legal(edge, origin, dest) -> None` using shared movement gates.

- [ ] **Step 1: Write failing source-precedence and edge-gate tests**

Add individual tests with explicit assertions:

```python
def test_authored_source_site_node_precedes_anchor(self):
    state = graph_state(site_source=True, province_metadata_source=True)
    sources, diagnostics = resolve_operational_supply_sources(state, Faction.NATO)
    bridged = source_by_id(sources, "province-supply-source:p1")
    self.assertEqual("site-node", bridged.source_node_id)
    self.assertEqual((), diagnostics)

def test_constructed_hub_authored_node_precedes_anchor(self):
    state = graph_state(constructed_hub=True, constructed_hub_node="hub-node")
    sources, _ = resolve_operational_supply_sources(state, Faction.NATO)
    self.assertEqual("hub-node", source_by_id(sources, "constructed-supply-hub:p1").source_node_id)

def test_province_source_falls_back_to_canonical_anchor(self):
    state = graph_state(province_metadata_source=True)
    sources, _ = resolve_operational_supply_sources(state, Faction.NATO)
    self.assertEqual(stable_node_id("p1", "anchor"), sources[0].source_node_id)

def test_anchor_alone_does_not_create_source(self):
    sources, _ = resolve_operational_supply_sources(graph_state(), Faction.NATO)
    self.assertEqual((), sources)

def test_missing_anchor_fails_closed_with_stable_diagnostic(self):
    sources, diagnostics = resolve_operational_supply_sources(
        graph_state(province_metadata_source=True, include_anchor=False), Faction.NATO
    )
    self.assertEqual((), sources)
    self.assertEqual("missing_anchor", diagnostics[0].reason)

def test_two_logical_sources_sharing_anchor_keep_distinct_ids(self):
    state = graph_state(province_metadata_source=True, explicit_second_source=True)
    sources, _ = resolve_operational_supply_sources(state, Faction.NATO)
    self.assertEqual(2, len({item.source_hub_id for item in sources}))
    self.assertEqual(1, len({item.source_node_id for item in sources}))
```

Also add separate tests for no name/port/geometry inference, insertion-order independence, allied sharing matching `_eligible_sources`, hostile source/site control, disabled/candidate/blocked/one-way gates, and sea/ferry explicit opt-in.

- [ ] **Step 2: Run the new source and edge tests and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: FAIL importing `gates_of_codex.operational_supply`.

- [ ] **Step 3: Implement source resolution and edge eligibility minimally**

Use `infrastructure_levels`, `allied_factions`, `is_friendly_owner`, `get_site_control_state`, `_eligible_sources` semantics, `stable_node_id`, `_indexes`, and `assert_edge_hop_legal`. Sort every input and output. Treat constructed-hub routing metadata only when it contains an explicit node ID; otherwise apply the canonical anchor fallback. Do not mutate province or site-control dictionaries.

```python
_SEA_SUPPLY_OPT_IN_KINDS = frozenset({
    EdgeKind.FERRY.value,
    EdgeKind.FERRY_OR_SEA_LANE.value,
    EdgeKind.SEA_LANE.value,
})

def assert_supply_edge_hop_legal(edge, *, origin: str, dest: str) -> None:
    assert_edge_hop_legal(edge, origin=origin, dest=dest)
    flag = (edge.metadata or {}).get("supply_capable")
    if flag is False:
        raise ValueError("supply_blocked")
    if edge.kind in _SEA_SUPPLY_OPT_IN_KINDS and flag is not True:
        raise ValueError("supply_opt_in_required")
```

- [ ] **Step 4: Run the source and edge tests and verify GREEN**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: all Task 1-2 tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- src/gates_of_codex/operational_supply.py tests/test_operational_s8_supply.py
git diff --cached --check
git commit -m "feat(operational): resolve authoritative supply sources"
```

### Task 3: Deterministic reverse routing and on-edge endpoint costs

**Files:**
- Modify: `src/gates_of_codex/operational_supply.py`
- Modify: `tests/test_operational_s8_supply.py`

**Interfaces:**
- Produces immutable `OperationalSupplyRoute(route_cost, node_id_path, edge_id_path, source_hub_id)` with comparison key in that field order.
- Produces `compute_operational_supply_routes(state, faction, sources) -> dict[str, OperationalSupplyRoute]`.
- Produces `route_for_formation(state, formation, routes) -> OperationalSupplyRoute | None`.
- Produces `on_edge_attachment_cost(edge_cost, segment_milli) -> int` using ceiling division.

- [ ] **Step 1: Write failing routing tests**

```python
def test_connected_formation_gets_lowest_integer_route(self):
    state = routed_state(costs=(1000, 750))
    routes = routes_for(state, Faction.NATO)
    self.assertEqual(1750, routes["formation-node"].route_cost)

def test_equal_cost_route_key_is_deterministic(self):
    left = routed_state(insertion_order="forward", equal_routes=True)
    right = routed_state(insertion_order="reverse", equal_routes=True)
    self.assertEqual(route_snapshot(left), route_snapshot(right))
    self.assertEqual(("n0", "n-a", "hub"), route_snapshot(left)["node_id_path"])

def test_reverse_search_preserves_one_way_gameplay_direction(self):
    forward = routed_state(one_way=("formation", "hub"))
    reverse = routed_state(one_way=("hub", "formation"))
    self.assertIsNotNone(route_for_only_force(forward))
    self.assertIsNone(route_for_only_force(reverse))

def test_on_edge_fixed_point_cost_rounds_up_exactly(self):
    self.assertEqual(333, on_edge_attachment_cost(1000, 333))
    self.assertEqual(500, on_edge_attachment_cost(1000, 500))
    self.assertEqual(0, on_edge_attachment_cost(1000, 0))

def test_on_edge_uses_sole_reachable_endpoint(self):
    route = route_for_only_force(on_edge_state(left_reachable=False, right_reachable=True))
    self.assertEqual("right-source", route.source_hub_id)

def test_on_edge_chooses_lower_total_endpoint_cost(self):
    route = route_for_only_force(on_edge_state(left_cost=2000, right_cost=500))
    self.assertEqual("right-source", route.source_hub_id)
```

Add explicit empty-graph, missing-source, malformed-edge reference, and unresolved formation-position tests returning no route plus stable diagnostics rather than inventing connectivity.

- [ ] **Step 2: Run routing tests and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: FAIL because route computation APIs are absent.

- [ ] **Step 3: Implement deterministic routing minimally**

Build original legal hops in sorted edge-ID order, require friendly endpoint provinces, then add reverse-search adjacency. Seed one heap entry per sorted source. Retain and compare the complete route key:

```python
RouteKey = tuple[int, tuple[str, ...], tuple[str, ...], str]

candidate = OperationalSupplyRoute(
    route_cost=current.route_cost + hop.cost,
    node_id_path=(hop.predecessor,) + current.node_id_path,
    edge_id_path=(hop.edge_id,) + current.edge_id_path,
    source_hub_id=current.source_hub_id,
)
```

For on-edge formations, convert formation-relative progress to canonical `a -> b` progress, enforce legal access toward each endpoint, add the exact attachment cost, prepend the endpoint and occupied edge to tie-break paths, and choose the minimum full key.

- [ ] **Step 4: Run routing tests and verify GREEN**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: all Task 1-3 tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- src/gates_of_codex/operational_supply.py tests/test_operational_s8_supply.py
git diff --cached --check
git commit -m "feat(operational): trace deterministic supply routes"
```

### Task 4: Persisted grace state and refresh lifecycle hooks

**Files:**
- Modify: `src/gates_of_codex/operational_supply.py`
- Modify: `src/gates_of_codex/operational_movement.py`
- Modify: `src/gates_of_codex/campaign.py`
- Modify: `src/gates_of_codex/state_io.py`
- Modify: `tests/test_operational_s8_supply.py`

**Interfaces:**
- Produces `ensure_operational_supply_state(state) -> dict[str, Any]`.
- Produces `refresh_operational_supply(state, *, consume_grace: bool, completed_tick: int | None = None) -> OperationalSupplyReport`.
- Operational tick calls refresh once after capture and before returning its report.
- Turn-start, save, and load hooks call non-consuming authoritative refresh.

- [ ] **Step 1: Write failing state-machine and hook-order tests**

```python
def test_first_disconnected_tick_enters_persisted_grace(self):
    state = connected_state()
    refresh_operational_supply(state, consume_grace=False)
    block_only_edge(state)
    refresh_operational_supply(state, consume_grace=True, completed_tick=1)
    force = only_force(state)
    self.assertTrue(force.supplied)
    self.assertFalse(force.cut_off)
    self.assertIsNone(force.source_hub_id)
    self.assertEqual(1, force.grace_ticks_remaining)

def test_next_disconnected_tick_becomes_cut_off(self):
    state = grace_state(last_tick=1)
    refresh_operational_supply(state, consume_grace=True, completed_tick=2)
    self.assertFalse(only_force(state).supplied)
    self.assertTrue(only_force(state).cut_off)
    self.assertEqual(0, only_force(state).grace_ticks_remaining)

def test_duplicate_tick_refresh_does_not_consume_grace_twice(self):
    state = disconnected_state()
    refresh_operational_supply(state, consume_grace=True, completed_tick=4)
    refresh_operational_supply(state, consume_grace=True, completed_tick=4)
    self.assertEqual(1, only_force(state).grace_ticks_remaining)

def test_post_load_recompute_preserves_grace(self):
    state = grace_state(last_tick=7)
    loaded = campaign_from_dict(state.to_dict())
    self.assertTrue(only_force(loaded).supplied)
    self.assertEqual(1, only_force(loaded).grace_ticks_remaining)

def test_restored_route_clears_cutoff_and_grace_immediately(self):
    state = cut_off_state()
    restore_only_edge(state)
    refresh_operational_supply(state, consume_grace=False)
    force = only_force(state)
    self.assertTrue(force.supplied)
    self.assertFalse(force.cut_off)
    self.assertEqual(0, force.grace_ticks_remaining)
```

Instrument an operational tick fixture so a site capture flips source control, then assert the supply refresh sees the new controller in that completed tick. Assert one refresh call, not one from capture plus another from tick completion.

- [ ] **Step 2: Run lifecycle tests and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: FAIL because refresh state transitions and hooks are absent.

- [ ] **Step 3: Implement migration, idempotent state machine, and hooks**

Use schema version 8 and a stable migration record only when a graph resolves. Non-consuming disconnected recomputation clears stale source/cost but preserves `supplied`, `cut_off`, and `grace_ticks_remaining`. Consuming refresh uses this exact branch:

```python
if force.last_grace_consuming_tick == completed_tick:
    pass
elif force.grace_ticks_remaining == 1:
    force.supplied = False
    force.cut_off = True
    force.grace_ticks_remaining = 0
elif force.cut_off:
    force.supplied = False
else:
    force.supplied = True
    force.cut_off = False
    force.grace_ticks_remaining = 1
force.last_grace_consuming_tick = completed_tick
```

Call it in `advance_operational_tick()` after `advance_site_capture()` and with the incremented global tick. Call non-consuming refresh after `turn_number` increments at strategic-turn start, before numeric supply refresh; before save serialization; and after load ensures positions, orders, and site control.

- [ ] **Step 4: Run lifecycle tests and verify GREEN**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: all Task 1-4 tests pass.

- [ ] **Step 5: Run S1-S7 operational regressions**

Run: `python -m unittest tests.test_operational_em_s1 tests.test_operational_s2_positions tests.test_operational_s3_movement tests.test_operational_s4_contact tests.test_operational_s5_capture tests.test_operational_s6_interception tests.test_operational_s7_ai_orders -v`

Expected: all existing operational tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add -- src/gates_of_codex/operational_supply.py src/gates_of_codex/operational_movement.py src/gates_of_codex/campaign.py src/gates_of_codex/state_io.py tests/test_operational_s8_supply.py
git diff --cached --check
git commit -m "feat(operational): refresh supply with one-tick grace"
```

### Task 5: Feed operational state into existing degradation without changing formulas

**Files:**
- Modify: `src/gates_of_codex/supply.py`
- Modify: `tests/test_operational_s8_supply.py`
- Modify: `tests/test_supply_ai.py`

**Interfaces:**
- Produces `formation_supplied_for_battalion(state, battalion) -> bool | None`, returning `None` for no operational authority.
- `refresh_supply_for_faction` uses that boolean only for operational campaigns and otherwise retains `reachable_supply_provinces` exactly.

- [ ] **Step 1: Write failing degradation and legacy-compatibility tests**

```python
def test_cut_off_formation_uses_existing_supply_drain_once(self):
    state = cut_off_state(battalion_supply=100)
    refresh_supply_for_faction(state, Faction.NATO)
    battalion = only_battalion(state)
    self.assertEqual(75, battalion.supply)
    self.assertEqual(1, battalion.encircled_turns)

def test_grace_formation_does_not_enter_degradation_path(self):
    state = grace_state(battalion_supply=50)
    refresh_supply_for_faction(state, Faction.NATO)
    self.assertEqual(70, only_battalion(state).supply)
    self.assertEqual(0, only_battalion(state).encircled_turns)

def test_no_graph_supply_report_and_serialization_are_unchanged(self):
    before = legacy_state()
    expected_payload = before.to_dict()
    expected_reach = reachable_supply_provinces(before, Faction.NATO)
    expected_report = refresh_supply_for_faction(before, Faction.NATO)
    after = legacy_state()
    ensure_operational_supply_state(after)
    actual_report = refresh_supply_for_faction(after, Faction.NATO)
    self.assertEqual(expected_reach, reachable_supply_provinces(after, Faction.NATO))
    self.assertEqual(expected_report, actual_report)
    self.assertEqual(expected_payload["schema_version"], after.to_dict()["schema_version"])
```

Keep the existing three-refresh attrition assertion in `test_supply_ai.py` unchanged to prove formula stability.

- [ ] **Step 2: Run supply tests and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply tests.test_supply_ai -v`

Expected: the operational degradation assertions fail while legacy tests still show their current behavior.

- [ ] **Step 3: Make the minimal classification change in `supply.py`**

Resolve each battalion's strategic formation. If graph authority is present, use `force.supplied`; otherwise use the existing `battalion.province_id in reachable` expression. Do not alter constants or `_apply_encirclement_attrition`.

- [ ] **Step 4: Run supply tests and verify GREEN**

Run: `python -m unittest tests.test_operational_s8_supply tests.test_supply_ai -v`

Expected: all focused and legacy supply tests pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add -- src/gates_of_codex/supply.py tests/test_operational_s8_supply.py tests/test_supply_ai.py
git diff --cached --check
git commit -m "feat(supply): consume operational cut-off state"
```

### Task 6: Additive frontend contract

**Files:**
- Modify: `src/gates_of_codex/frontend.py`
- Modify: `tests/test_operational_s8_supply.py`
- Modify: `tests/test_operational_s7_ai_orders.py`
- Modify: `tests/test_godot_s6_battle_location.py`
- Modify: `tests/test_frontend_writeback_contract.py`

**Interfaces:**
- Increments `FRONTEND_SCHEMA_VERSION` from 12 to 13.
- Adds `supplied`, `cut_off`, and `source_hub_id` only to strategic-formation rows.
- Makes existing battalion `is_in_supply` reflect formation S8 state when graph authority exists.

- [ ] **Step 1: Write failing frontend tests**

```python
def test_frontend_exports_thin_operational_supply_summary(self):
    state = cut_off_state()
    snapshot = build_frontend_snapshot(state)
    force = snapshot["strategic_formations"][0]
    battalion = snapshot["battalions"][0]
    self.assertEqual(13, snapshot["schema_version"])
    self.assertFalse(force["supplied"])
    self.assertTrue(force["cut_off"])
    self.assertIsNone(force["source_hub_id"])
    self.assertFalse(battalion["is_in_supply"])
    self.assertNotIn("route_cost", force)
    self.assertNotIn("grace_ticks_remaining", force)
```

Update the two exact version assertions from 12 to 13 while leaving committed schema-12 fixtures intact as older readable snapshots.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply tests.test_control_frontend tests.test_frontend_writeback_contract tests.test_godot_s6_battle_location tests.test_operational_s7_ai_orders -v`

Expected: FAIL on missing S8 keys and version 13.

- [ ] **Step 3: Implement the additive frontend fields**

Call non-consuming operational refresh once at snapshot build after position/site-control ensures. Export only the approved three fields. For battalions, use the parent formation state only when operational authority resolves; keep province reach for legacy snapshots.

- [ ] **Step 4: Run frontend tests and verify GREEN**

Run: `python -m unittest tests.test_operational_s8_supply tests.test_control_frontend tests.test_frontend_writeback_contract tests.test_godot_s6_battle_location tests.test_operational_s7_ai_orders -v`

Expected: all frontend and operational contract tests pass.

- [ ] **Step 5: Commit Task 6**

```powershell
git add -- src/gates_of_codex/frontend.py tests/test_operational_s8_supply.py tests/test_operational_s7_ai_orders.py tests/test_godot_s6_battle_location.py tests/test_frontend_writeback_contract.py
git diff --cached --check
git commit -m "feat(frontend): expose operational supply summary"
```

### Task 7: Documentation, complete validation, review, and publication

**Files:**
- Modify: `docs/supply-and-strategic-ai.md`
- Modify: `README.md` only if its implemented-feature wording requires a precise S8 distinction
- Modify: `docs/superpowers/plans/2026-08-07-s8-operational-supply.md` to check completed steps

**Interfaces:**
- Documents route authority, source bridge, exact grace transition, refresh ordering, allied eligibility, and disabled-candidate content consequence.
- Produces a draft PR targeting `main`; never merges it.

- [ ] **Step 1: Add focused documentation assertions first**

Add a test in `tests/test_operational_s8_supply.py` that reads `docs/supply-and-strategic-ai.md` and asserts the stable phrases `one operational tick of grace`, `province-supply-source:`, `supply_capable`, and `disabled candidate corridors` are present.

- [ ] **Step 2: Run the documentation assertion and verify RED**

Run: `python -m unittest tests.test_operational_s8_supply -v`

Expected: FAIL because S8 documentation has not been added to the public supply document.

- [ ] **Step 3: Document S8 without future-scope implementation**

Add concise sections describing the approved source bridge, exact state table, reverse directed routing and tie key, legacy fallback, and the separate authored-route follow-up. Do not modify OpenGS or Earth3 documents.

- [ ] **Step 4: Run focused, operational, serialization, and frontend validation**

```powershell
python -m unittest tests.test_operational_s8_supply tests.test_supply_ai -v
python -m unittest tests.test_operational_em_s1 tests.test_operational_s2_positions tests.test_operational_s3_movement tests.test_operational_s4_contact tests.test_operational_s5_capture tests.test_operational_s6_interception tests.test_operational_s7_ai_orders -v
python -m unittest tests.test_campaign_play_loop tests.test_control_frontend tests.test_frontend_writeback_contract tests.test_godot_s6_battle_location -v
```

Expected: every command exits 0 with no failures or errors.

- [ ] **Step 5: Run the complete repository test matrix locally**

Run: `python -m unittest discover -s tests -v`

Expected: exit 0 with all discovered tests passing.

- [ ] **Step 6: Verify repository hygiene and protected boundaries**

```powershell
git diff --check origin/main...HEAD
git status --short --branch
git diff --name-only origin/main...HEAD
git diff --name-only origin/main...HEAD | Select-String -Pattern '^(tools/opengs_eval/|docs/research/opengs-evaluation/|\.github/workflows/opengs)'
```

Expected: `git diff --check` exits 0; the protected-path search returns no matches; no unrelated or generated files appear.

- [ ] **Step 7: Request independent code review and address findings through TDD**

Provide the reviewer `BASE_SHA=be455985da4c4adcaaf7d7cf54f918b07d321fa7`, current `HEAD_SHA`, issue #105 requirements, the design spec, and protected boundaries. For each critical or important issue, add a failing regression test, verify RED, implement the fix, verify GREEN, and rerun the relevant broader suite.

- [ ] **Step 8: Commit final docs and review fixes**

```powershell
git add -- docs/supply-and-strategic-ai.md docs/superpowers/plans/2026-08-07-s8-operational-supply.md tests/test_operational_s8_supply.py
git diff --cached --check
git commit -m "docs: describe operational supply authority"
```

- [ ] **Step 9: Update issue #105 with locked rulings and implementation status**

Use `gh issue comment 105 --repo xfizzle-gh/Gates-of-Code-X --body-file <temp-file>` with the exact refresh timing, grace table, bridge precedence, route tie key, legacy proof, current head SHA, and test results.

- [ ] **Step 10: Push and open one draft PR**

```powershell
git push -u origin feat/s8-operational-supply
gh pr create --repo xfizzle-gh/Gates-of-Code-X --base main --head feat/s8-operational-supply --draft --title "feat(operational): add S8 supply hooks" --body-file <temp-file>
```

The PR body must summarize behavior, locked constraints, schema migration, compatibility, tests, protected-path verification, and the authored-route follow-up risk.

- [ ] **Step 11: Wait for exact-head CI and fix only this PR**

Run `gh pr checks <pr-number> --repo xfizzle-gh/Gates-of-Code-X --watch`. If a check fails, inspect logs, reproduce locally, add a failing regression test when applicable, fix, rerun the complete local suite, push the new exact head, and wait again. Stop only when all required checks for the current PR head are green. Do not merge.
