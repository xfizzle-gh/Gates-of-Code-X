# S9B Hostile-Occupancy Pass-Through Prevention

## Goal

Harden and prove the existing operational node-contact and S6 edge-interception pipelines so a combat-capable hostile formation can never be passed through because of stance, order state, movement source, or save/load timing.

S9B does not add a blocking order, blocking mode, persisted blocking Boolean, second movement simulator, delay mechanic, automatic rerouting, Ambush mechanics, presentation, Fog of War, or route-authority changes.

## Locked behavior

1. Blocking derives only from authoritative hostile formation existence and exact node or edge position.
2. Every stance physically blocks: `operational`, `ambush`, `entrenched`, `forced_march`, and `refit_resupply`.
3. Hostile contact stops movement at the deterministic contact point, creates the existing single pending battle immediately, and discards remaining movement for that operational tick.
4. No automatic rerouting or pass-through is permitted.
5. Refit & Resupply is interrupted at hostile pending-battle creation and resets to `operational` regardless of the eventual result.
6. Forced March ends movement on contact and resets to `operational` after battle participation or retreat.
7. Entrenched remains Entrenched after victory at the same position and resets only when defeated and displaced.
8. Blocking persistence is reconstructed from position and formation existence. No blocking field may be serialized.
9. Candidate, disabled, metadata-blocked, or directionally illegal edges remain unavailable and must not become alternate paths around contact.
10. The existing single-pending-battle rule remains authoritative.

## Scope boundaries

Do not modify:

- production route authority or #141 assets;
- Earth3 geography, province IDs, adjacency, or water authority;
- `tools/opengs_eval/**` or `docs/research/opengs-evaluation/**`;
- S8 supply formulas;
- S9C `ambush_ready_tick`, strength multipliers, or Ambush battle metadata;
- S10 Godot presentation;
- S11 Fog of War.

## Implementation sequence

### Task 1 — Baseline the existing contact authority

Inspect the current S4 node-entry and static-contact paths, S6 swept edge interception, S7 AI order execution, and S9A battle finalization.

Add focused tests that first express the locked no-pass-through contract without introducing new mechanics:

- a moving player formation cannot traverse a hostile-occupied destination node;
- an AI formation uses the same node-contact path and cannot pass through;
- a multi-edge order halts at the first hostile node and does not continue to a later node;
- simultaneous arrivals still choose one deterministic earliest contact;
- an existing pending battle prevents creation of a second battle and prevents continued movement.

### Task 2 — Harden node occupancy for every stance

Parameterize node-contact tests across:

- `operational`;
- `ambush` without implementing S9C readiness or bonuses;
- `entrenched`;
- `forced_march`;
- `refit_resupply`.

Prove that the hostile formation blocks solely because it occupies the node. Stance must not make a formation intangible or alter contact-point selection.

When node contact creates a hostile pending battle:

- set participating `refit_resupply` formations to `operational` immediately;
- preserve Entrenched until battle finalization determines displacement;
- end Forced March movement for the tick without granting additional traversal.

### Task 3 — Harden fixed edge occupancy through S6

Use the existing canonical fixed-point edge authority. Do not add radius checks.

Required cases:

- moving hostile catches a stationary formation with no order;
- moving hostile catches a stationary formation whose order is blocked;
- opposing movement crosses on the same edge;
- same-direction catch-up contacts at the exact rational point;
- stationary/conflicting edge occupants in every stance block identically;
- one-way directionality remains authoritative for movement while contact still occurs when legal intervals meet;
- formations elsewhere on the same edge do not join or block an unrelated contact;
- included participants stop at one shared canonical progress before battle creation.

### Task 4 — Complete stance interruption and finalization rules

Centralize only the stance transitions required by hostile battle participation:

- `refit_resupply` → `operational` at pending-battle creation, regardless of eventual result;
- `forced_march` → `operational` after battle participation or retreat;
- victorious `entrenched` remains Entrenched when not displaced;
- defeated/displaced `entrenched` resets through the S9A finalization path;
- `ambush` receives no new readiness, multiplier, or consumption behavior in S9B.

Avoid duplicating battle finalization or introducing a second stance-state machine.

### Task 5 — Prove derived persistence and deterministic parity

Add save/load and insertion-order regressions proving:

- no `is_blocking`, blocking order, or equivalent field is serialized;
- a hostile formation continues to block after save/load because its position persists;
- moving, retreating, or destroying the formation automatically clears the obstruction;
- player-issued and S7 AI-issued movement reach the same contact result;
- repeated runs and formation insertion-order permutations produce identical pending-battle participants, contact location, order status, and final positions.

### Task 6 — Regression and scope audit

Run:

- all focused S9B tests;
- S4 node-contact tests;
- S6 interception tests;
- S7 AI-order tests;
- S8 supply tests;
- S9A retreat and authority tests;
- full repository suite and all required GitHub Actions jobs.

Confirm the final diff contains no S9C, S10, S11, route-authority, Earth3, OpenGS, or supply-formula expansion.

## Exit criteria

S9B is complete only when:

- hostile node and edge occupants cannot be passed through under any stance;
- contact is immediate and deterministic through the existing S4/S6 pipelines;
- remaining movement is lost and no reroute occurs;
- Refit and Forced March transitions match the locked matrix;
- blocking is fully derived and no blocking state is persisted;
- player/AI, save/load, insertion-order, and single-pending-battle contracts are tested;
- complete exact-head CI is green;
- an independent reviewer accepts the PR before merge.
