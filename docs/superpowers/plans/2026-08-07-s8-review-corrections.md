# S8 Independent Review Corrections Implementation Plan

> Continue PR #140 from reviewed head
> `92174272be558a9e7ac5e0f70a84f8efa893fd92`. Keep the PR draft and do not
> merge, start S9, author production corridors, or touch protected OpenGS,
> Earth3, #129, or #121 paths.

**Goal:** Close the independent-review blockers by tightening source and node
authority, metadata types, persisted-state invariants, status reporting, and
integration evidence without changing S8 routing architecture or legacy supply
formulas.

**Architecture:** Keep graph supply in `operational_supply.py`. Add centralized
usable-site and valid-source-node predicates using existing graph defaults and
metadata vocabulary. Keep numeric recovery/drain in `supply.py`, but make its
report explicitly identify province versus operational authority. Reject bad
serialized state before load-time recomputation.

**Test discipline:** Each behavior change starts with a focused failing test,
then the minimum implementation, then focused and adjacent regressions.

---

## Task 1: Source and node authority

**Files:**

- Modify `src/gates_of_codex/operational_supply.py`
- Modify `tests/test_operational_s8_supply.py`

1. Add failing tests for candidate/disabled depots, hostile-site bridge
   exclusion, cross-province site and associated nodes, candidate nodes, valid
   authored precedence, and insertion-order independence.
2. Run the focused tests and confirm failures arise from current permissive
   source/site selection.
3. Add helpers equivalent to:

   ```python
   def _site_is_usable_source(site, controller, friendly) -> bool: ...
   def _valid_source_node(nodes, node_id, province_id) -> str | None: ...
   ```

   Missing site/node authority uses the schema default `authored`; explicit
   non-authored values and `metadata.disabled` fail closed. Build bridge-site
   precedence only from usable friendly sites. Validate every selected node's
   existence, province, and authority.
4. Emit stable diagnostics for authored sources whose own node is invalid.
   Province and constructed sources fall through invalid higher precedence to
   the next approved candidate.
5. Run focused and S2/S5 regressions, then commit the slice.

## Task 2: Strict `supply_capable`

**Files:**

- Modify `src/gates_of_codex/operational_supply.py`
- Modify `tests/test_operational_s8_supply.py`

1. Add failing land and ferry/sea cases for string, integer, float, and null
   metadata values.
2. Confirm the current code incorrectly treats malformed land metadata as
   absent or truthy.
3. When the key exists, require `type(value) is bool`; otherwise raise
   `ValueError("invalid_supply_capable")`. Preserve the shared movement gate
   call before the S8-specific check.
4. Run focused edge/routing tests and commit.

## Task 3: Persisted states and monotonic ticks

**Files:**

- Modify `src/gates_of_codex/models.py`
- Modify `src/gates_of_codex/state_io.py`
- Modify `src/gates_of_codex/operational_supply.py`
- Modify `tests/test_operational_s8_supply.py`

1. Add a table-driven failing test over supplied/cut-off/source/cost/grace
   combinations. Only connected, initial-disconnected, grace, and cut-off rows
   may load.
2. Add failing tests for increasing, duplicate, and stale completed ticks and
   monotonic `last_supply_refresh_tick` / `last_grace_consuming_tick`.
3. Validate cross-field state in `StrategicFormation.validate()` and validate
   parsed formations before load-time refresh can normalize bad payloads.
4. Preflight all formations before a consuming refresh. Reject a lower tick
   with `stale_completed_tick`; equal ticks do not consume grace; greater ticks
   may transition. Never assign a refresh tick lower than the stored value.
5. Run focused serialization/lifecycle tests and commit.

## Task 4: Graph-aware status contracts

**Files:**

- Modify `src/gates_of_codex/supply.py`
- Modify `src/gates_of_codex/cli.py`
- Modify `src/gates_of_codex/frontend.py`
- Modify `tests/test_operational_s8_supply.py`
- Modify `tests/test_supply_ai.py`
- Modify affected frontend contract tests

1. Add failing graph/no-graph tests for `SupplyReport`, `supply-status` with and
   without `--refresh`, and frontend faction aggregates.
2. Extend `SupplyReport` additively with authority, logical source IDs,
   connected/grace/cut-off formation and battalion IDs, and explicitly named
   legacy administrative reach where applicable.
3. Centralize a non-mutating status snapshot so graph CLI classification always
   reads formation S8 state, while no-graph status retains province
   classification.
4. In frontend schema 13, replace ambiguous faction
   `supply_reachable_provinces` for graph campaigns with explicit operational
   aggregate fields and a separately labeled legacy/admin count. Preserve the
   old field for no-graph compatibility.
5. Verify `--refresh` changes numeric supply only once and does not change the
   authority classification source.
6. Run CLI, supply, and frontend regressions and commit.

## Task 5: Reproducible integration evidence

**Files:**

- Modify `tests/test_operational_s8_supply.py`
- Modify `tests/test_supply_ai.py` only if the canonical legacy fixture belongs
  there

1. Add canonical no-graph payload and `save_campaign` byte comparisons before
   and after every S8 entry point; assert no S8 fields or migration metadata.
2. Add a real temporary operational graph JSON referenced through
   `map_metadata["operational_graph"]`. Exercise actual
   `save_campaign -> load_campaign` and prove grace survives.
3. Prove save, load, frontend, and strategic-turn-start recomputation cannot
   consume grace.
4. Add end-to-end cut route -> grace tick -> cut-off tick -> numeric drain,
   hostile source capture -> disconnect, friendly recapture -> recovery, and
   source/constructed-hub removal -> next-refresh disconnect tests.
5. Exercise the committed production graph and prove candidate corridors remain
   unavailable without changing that asset.
6. Run focused and integration tests and commit.

## Task 6: Documentation, review, and publication

**Files:**

- Modify `docs/superpowers/specs/2026-08-07-s8-operational-supply-design.md`
- Modify `docs/supply-and-strategic-ai.md`
- Modify this plan only for discovered factual corrections

1. Document reviewed authority/default/disable rules, strict metadata token,
   four legal states, monotonic ticks, status authority fields, and new
   integration evidence.
2. Run focused S8, S1-S7, serialization/CLI/frontend groups, full discovery,
   and both CLI smoke commands.
3. Audit the diff against protected OpenGS and Earth3 paths.
4. Perform a structured self-review because repository instructions prohibit
   spawning a review subagent unless the user explicitly requests delegation.
5. Commit intentionally, update PR #140 and issue #105 bodies/status, push the
   same branch without force, and wait for the full exact-head Actions matrix.
6. Stop with PR #140 draft, issue #105 open, and no merge.
