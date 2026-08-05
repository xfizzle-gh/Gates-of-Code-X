# Operational graph (S1)

Schema-only operational route data for Europe-Mediterranean.

- `operational_graph.json` — nodes, edges, rules
- `operational_index.json` — counts and paths

No movement, capture, interception, or AI behavior in S1.

## Authority

- **Authored** strait / ferry / sea-lane edges are part of the v1 topology
  and are marked `traversal_enabled=true`.
- **Candidate** land corridors are not gameplay-authoritative:
  `traversal_enabled=false` until explicitly authored or owner-approved.

Port requirement and blockade enforcement are deferred:

```text
rules.authored_crossings_traversable_v1 = true
rules.enforce_port_requirements = false
rules.enforce_blockades = false
```

## Stances (locked commitment)

Approved `locked_stance` IDs only:

```text
operational
forced_march
entrenched
refit_resupply
ambush
```

## Order commitment fields

| status | committed_turn / locked_stance |
|--------|--------------------------------|
| draft | must be absent |
| committed, active, completed, blocked | required |
| cancelled | both present, or neither (not one alone) |
