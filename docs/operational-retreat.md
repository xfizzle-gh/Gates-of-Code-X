# S9A deterministic operational retreat

S9A centralizes mandatory post-battle retreat for campaigns using the authoritative operational graph. It does not add blocking, Ambush, pursuit, random withdrawal, manual prompts, or another movement/contact simulator.

## Eligibility and priority

A valid recorded pre-contact origin has absolute priority when it remains friendly-accessible, under stack capacity, free of hostile occupancy, and otherwise legal. The exact recorded endpoint rollback from an edge encounter may ignore ordinary reverse-direction restrictions because it restores the last legal position; this exception applies nowhere else.

Without a valid recorded origin, only nodes adjacent to the encounter are considered. Candidates are excluded before ranking when they are hostile-controlled, hostile-occupied, stack-full, reachable only through a candidate, disabled, metadata-blocked, directionally illegal, ferry, sea-lane, or otherwise unresolved edge, or would create another contact.

Eligible fallback nodes are ranked by **supplied, movement cost, stable node ID**. S8 one-tick grace remains supplied because the formation's authoritative `supplied` value is still true. Retreat never searches a multi-edge path.

Candidate corridors remain unavailable. S9A does not change production route authority or infer approval from candidate topology.

## Finalization

Retreat resolves once per losing strategic formation. All surviving member battalions remain co-located at the selected node, unfinished movement is blocked, and no unused movement resumes during the operational tick. Retreat cannot create a second pending battle.

A losing Forced March or Entrenched formation resets to `operational` when displaced. A victorious Entrenched formation remains Entrenched at its position.

When no legal retreat exists, the established synchronized removal path eliminates the formation with reason `trapped_no_legal_retreat`. Formation and battalion commander assignments, battalion membership, move-order state, operational position, and recorded origin metadata are cleaned as one finalization operation.

Campaigns without an operational graph retain the existing province-authoritative retreat behavior.

## Non-production acceptance fixture

The committed fixture is `tests/test_operational_s9a_retreat.py`. It uses temporary graph and campaign files and never mutates the production operational graph.

Run the four acceptance cases from the repository root:

```powershell
py -3.11 -m unittest `
  tests.test_operational_s9a_retreat.OperationalS9AFinalizationTests.test_node_battle_retreats_loser_once_and_reports_destination `
  tests.test_operational_s9a_retreat.OperationalS9AEncounterTests.test_edge_cross_retreat_uses_recorded_origin `
  tests.test_operational_s9a_retreat.OperationalS9ARankingTests.test_supplied_adjacent_node_beats_unsupplied `
  tests.test_operational_s9a_retreat.OperationalS9AFinalizationTests.test_trapped_elimination_cleans_complete_formation_state `
  -v
```

The cases prove, respectively:

1. real moving node contact and one atomic retreat;
2. real swept edge contact and exact recorded-origin rollback;
3. S8-connected adjacent-node preference;
4. synchronized trapped elimination and commander/reference cleanup.
