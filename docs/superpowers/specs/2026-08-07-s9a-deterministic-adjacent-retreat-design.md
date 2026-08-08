# S9A Deterministic Adjacent Retreat Design

**Issue:** #106

**Scope:** S9A only

**Base:** `6488a17b90412b4bc279b242b7edd359e5372445`

## Goal

Replace the current operational-campaign province-neighbor retreat fallback with
one deterministic graph resolver shared by node and edge battles. Every losing
strategic formation retreats exactly once to the recorded previous legal node
or one legal adjacent node. A trapped formation is removed through the complete
formation/battalion synchronization path. Campaigns without an operational graph
retain the existing province-level retreat behavior unchanged.

S9A does not add blocking rules, Ambush readiness or modifiers, production
routes, presentation, Fog of War, pursuit, voluntary withdrawal, random retreat,
or multi-edge pathfinding.

## Existing authority reused

- `CampaignEngine._finalize_positions` remains the only battle-finalization
  entry point for internal and imported battle results.
- `_formations_for_battalions` retains once-per-strategic-formation participant
  expansion and stable formation-ID ordering.
- `assert_edge_hop_legal` and `assert_edge_traversable` remain the authorities
  for enabled/authored/metadata/direction gates.
- `enemy_formations_at_node`, `friendly_formations_at_node`, and
  `can_enter_node_friendly_stack` remain occupancy and capacity authorities.
- `is_friendly_owner` retains the repository's alliance-aware control rule.
- `resolve_operational_supply_sources` and
  `compute_operational_supply_routes` retain S8 source-sharing and route
  authority.
- `operational_edge_retreat_nodes` remains the persisted compatibility key for
  exact pre-contact origin node IDs. S9A centralizes access behind named helper
  functions and extends recording to moving node-contact participants; it does
  not add a second origin field.
- `_remove_battalion` remains the primitive removal operation and is
  centralized behind a complete formation-elimination helper when retreat is
  impossible.

## Component boundary

Create `gates_of_codex.operational_retreat` as a graph-policy module. It reads
the authoritative graph and campaign state and returns an immutable retreat
resolution containing the selected node/province or the stable trapped reason.
It does not mutate ownership, issue an order, advance a tick, invoke contact
creation, or create a pending battle.

`CampaignEngine` applies the resolution atomically for one strategic formation:
move every surviving member to the selected node, block unfinished movement,
apply the S9A stance reset, or eliminate the complete formation. The existing
finalizer calls this same path for node contact, node simultaneous contact,
edge-cross contact, and edge-catchup contact.

The finalizer returns an additive battle-finalization report. Each losing
formation contributes a deterministic retreat outcome. A trapped outcome emits
`trapped_no_legal_retreat` through that non-persisted report; the reason is not
stored as duplicate campaign state.

## Recorded-origin lifecycle

The compatibility metadata map stores `formation_id -> node_id` only after a
hostile pending battle is successfully created.

- Edge contact continues to record each participant's exact last legal node.
- A moving node-contact participant records the origin node of its final hop.
- A stationary node participant has no invented previous node.
- Save/load preserves the map through ordinary `map_metadata` serialization.
- Failed contact creation restores or avoids the metadata write.
- Battle finalization clears the map after all losing formations have resolved,
  including trapped elimination.

No province name, geometry, anchor proximity, or arbitrary province neighbor is
used to reconstruct a missing origin.

## Candidate construction

The resolver first validates the recorded origin. If it is unavailable, it
constructs only one-edge candidates from the resolved encounter position.

For a node encounter, fallback candidates are the other endpoint of each edge
incident to `encounter_node_id`.

For an edge encounter, fallback candidates are only the two endpoints of
`encounter_edge_id`. The cost from the fixed contact point to an endpoint uses
the S8 fixed-point ceiling formula:

```text
segment_cost = (edge_cost * segment_milli + 999) // 1000
```

where canonical progress is measured from endpoint `a` toward endpoint `b`.
This is integer-only and does not search through either endpoint to a second
edge.

Parallel edges to the same node are reduced deterministically to the legal
representative with the lowest `(movement_cost, edge_id)` before the published
candidate ranking is applied.

## Eligibility gates

Every destination node must:

- exist in the authoritative graph and name an existing province;
- be controlled by the formation's faction or an existing ally according to
  `is_friendly_owner`;
- contain no hostile formation under existing diplomacy;
- remain below the normal allied/friendly formation stack cap, excluding the
  retreating formation itself;
- be reachable through an enabled authored edge that is not candidate,
  disabled, closed, blocked, or blockaded;
- obey normal authored directionality, except for the exact edge-origin
  rollback described below;
- avoid `ferry`, `ferry_or_sea_lane`, and `sea_lane` edges because port/ferry
  enforcement remains unresolved in current operational rules;
- contain no non-participant hostile edge occupant whose position would cause a
  second contact on the retreat segment.

The current battle's participants are ignored only as occupants of the resolved
contact point. Retreat never calls the contact pipeline, and a candidate that
would encounter a different hostile formation is rejected.

## Recorded edge-origin rollback exception

For an edge encounter, the exact recorded pre-contact origin is restoration to
the last legal position. Its incident encounter edge must still be authored,
enabled, metadata-open, non-ferry/non-sea, and lead to an eligible destination.
Only the reverse-direction check may be ignored.

The exception never applies to:

- a different endpoint;
- a node-battle recorded origin;
- a fallback edge;
- candidate, disabled, metadata-blocked, ferry, or sea traversal.

All unrelated fallback candidates use `assert_edge_hop_legal` normally.

## Supply preference and exact ranking

Recorded origin priority is absolute when that node is eligible. Otherwise the
resolver ranks adjacent candidates by:

```text
(
    0 if supplied else 1,
    legal_movement_cost,
    node_id,
)
```

Stack capacity is only an eligibility filter.

A node is S8-supplied for the retreating faction when it has a legal route in
the S8 route table computed from the current authoritative sources. A same-
faction formation already occupying that node also carries its current S8
`supplied` Boolean into the node classification. This explicitly treats a
one-tick grace occupant (`supplied=true`, `grace_ticks_remaining=1`) as supplied
without inventing allied source sharing. Allied sources influence the route
table only when the existing S8 eligibility rules already permit them.

All source, route, edge, node, and formation iterations are explicitly sorted;
no dictionary or set insertion order affects the result.

## Placement and stance reset

A successful operational retreat:

- places the strategic formation exactly at the selected node;
- synchronizes every surviving member battalion to the selected province;
- sets the formation movement state to `at_anchor`;
- blocks any unfinished move order and prevents unused movement from resuming
  during the completed contact tick;
- never changes province ownership or control-site state;
- never creates a second pending battle.

Forced March resets to `operational` after losing and retreating. Entrenched
resets to `operational` only when the formation loses and is displaced. The
reset updates both the formation's persisted stance value and any retained
move-order `locked_stance`. Refit/Resupply retreats normally and is otherwise
unchanged in S9A. Winning Entrenched formations remain unchanged. Ambush logic
is deferred to S9C.

## Trapped elimination

When no candidate exists, the finalizer emits
`trapped_no_legal_retreat` and removes the formation through a centralized
synchronization helper. The helper:

- unassigns formation and battalion commanders that point at removed records;
- removes every member battalion through the established battalion-removal
  primitive;
- removes the empty strategic formation, including its order and position;
- clears that formation's retreat-origin metadata;
- leaves province ownership and control sites unchanged.

The pending battle is completed and cleared only after every losing formation
has received exactly one outcome.

## Determinism and multi-formation resolution

Losing strategic formations resolve in stable formation-ID order. Earlier
successful placements become real occupancy for later capacity checks, so two
formations cannot overfill one destination. This ordering is independent of
campaign insertion order and makes constrained multi-formation retreat
allocation reproducible.

Winner placement remains the existing encounter node or exact edge progress.
No participant resumes movement in the resolved tick and no pursuit occurs.

## Save/load compatibility

No schema version bump is required. The existing origin-node map is already
serialized inside `map_metadata`; formation position, move order, stance, and S8
supply state retain their current serializers. Tests round-trip a live node
contact and a live edge contact before applying the battle result and compare
the deterministic retreat result.

Campaigns without an operational graph do not call the new resolver. Their
current province-neighbor retreat, destruction fallback, and serialization
remain byte-compatible apart from unrelated normal runtime fields.

## Tests

Focused S9A tests cover:

1. recorded-origin priority and invalid-origin fallback;
2. S8 route supply preference and one-tick-grace occupant classification;
3. movement-cost and stable-node-ID tie breaks;
4. one-edge-only search;
5. candidate, disabled, metadata-blocked, illegal-direction, and unresolved
   ferry/sea exclusions;
6. the exact edge-origin reverse-direction exception and its narrow scope;
7. hostile control, hostile occupancy, second-contact, and stack-cap exclusion;
8. alliance-aware friendly control;
9. node contact, edge cross, and edge catchup finalization;
10. one retreat per multi-battalion formation and no second pending battle;
11. complete trapped elimination and the stable reason token;
12. Forced March and Entrenched reset/preservation rules;
13. real node-contact and edge-contact save/load integration;
14. insertion-order independence;
15. no-graph legacy compatibility.

Regression validation includes S4 node contact, S6 interception, S7 AI orders,
S8 supply, serialization/save-load tests, the full repository suite, both CLI
smoke commands, and the complete GitHub Actions matrix.

## Protected boundaries

S9A does not modify OpenGS evaluation paths, Earth3 geography or authority,
coastline/theatre work, production operational graph assets, candidate-route
authority, Godot presentation, Fog of War, or S8 degradation/attrition formulas.
Candidate production corridors remain unavailable.
