# S11 Fog of War and Detection Design

## Status and authority

Issue #107, issue #77, and owner authorization comment `5227987788` approve and lock this design direction. S11 adds deterministic observation and presentation filtering around the existing authoritative campaign state. It does not create a second simulation state and does not alter operational movement, contact, Ambush, retreat, supply, economy, or tactical battle authority.

The design starts from the S10 merge commit `cbef4db96f04d26f4127278041f717691712d7eb`. Delivery remains a reviewed chain:

1. docs-only design PR;
2. Python observation authority and filtering PR;
3. Godot presentation PR.

Each PR remains draft and stops for independent review before the next slice begins.

## Launch phasing

Campaign setup retains:

```text
Fog of War: On / Off
```

The first implementation is available but opt-in for v1 and defaults Off until campaign balance and AI behavior are validated. When Fog of War is Off, current perfect-information behavior remains unchanged for single-player and human-v-human play.

When Fog of War is On, all human-facing snapshots and operational AI planning use the same observer-scoped knowledge model. Difficulty may change planning budget or aggressiveness, but it must not grant hidden-state access.

## Authority boundary

Python owns:

- whether Fog of War is enabled;
- observer scope and coalition sharing;
- current detection tier;
- last-known knowledge records;
- deterministic refresh timing;
- redaction of enemy formations, stances, strength, locations, orders, site progress, and edge traffic;
- the observation object supplied to AI;
- save/load migration and validation.

Godot owns only presentation of the already-filtered snapshot. It must not infer hidden positions, calculate detection, query omitted rows, or recover redacted values from other UI models.

The true `CampaignState` remains authoritative for simulation. Observation is a deterministic projection of that state for one observer scope.

## Observer scope and allied sharing

The thin slice uses one shared intelligence picture per coalition.

- A faction in an alliance reads and writes knowledge under that alliance ID.
- A faction without an alliance uses its faction ID as the observer scope.
- Coalition members share current contacts and last-known records completely in the thin slice.
- More restrictive sharing policies remain future scenario options under issue #77.

The observer scope is derived deterministically from existing alliance membership. No duplicate faction and alliance stores may disagree about the same observation.

## Information tiers

Enemy knowledge has five ordered tiers:

1. `unknown`
2. `contact`
3. `identified`
4. `assessed`
5. `fully_observed`

`unknown` is represented by absence of a current observation and absence of a retained last-known record. The other four tiers use explicit records.

### Contact

Exposes only:

- that an enemy formation exists;
- current or last-observed node ID, or edge ID without exact progress;
- observation turn and operational tick;
- source labels;
- stale/current state.

It does not expose formation ID, actor, echelon, strength, stance, composition, commander, exact edge progress, or orders.

### Identified

Adds:

- stable observed formation ID;
- display identity already present in the strategic formation model;
- actor/national identity where already authoritative;
- echelon.

It still does not expose exact strength, composition, stance, commander, exact edge progress, or orders.

### Assessed

Adds:

- deterministic strength band;
- readiness/condition band;
- supply state band;
- last-observed direction when available.

Bands are derived from existing authoritative values through fixed thresholds. Exact counts and percentages remain hidden.

### Fully observed

Adds the current exact operational position and existing formation details needed for direct contact or battle presentation. Enemy exact movement orders and intended destination remain hidden even at this tier. A triggered Ambush may be exposed through the existing battle participant contract after contact; an untriggered hidden Ambush stance is not exposed merely because another source reached `assessed`.

## Always-known information

With Fog of War On, these remain visible:

- authored province boundaries and IDs;
- the operational route graph, terrain, nodes, and edges;
- friendly formations, positions, orders, stances, and detailed state;
- friendly-controlled province ownership and sites;
- public scenario objectives;
- coalition-shared observations permitted by this design;
- province ownership in the thin slice.

Hiding ownership, construction, recruitment, strategic income, or logistics infrastructure is outside the first S11 implementation.

## Hidden information

Unless the current observation tier permits it, the snapshot and AI observation must not expose:

- exact enemy node or edge progress;
- exact enemy formation identity;
- exact enemy composition or battalion membership;
- exact condition, supply, experience, or strength;
- commander identity;
- stance, including untriggered Ambush;
- movement order, route, remaining path, or intended destination;
- enemy site-control progress;
- hidden edge traffic;
- selection, tooltip, stack-panel, command-result, log, or error-message side channels containing the same data.

Dimmed or disabled exact values still count as leaks and are prohibited.

## Deterministic detection rules

There is no continuous pixel line of sight, no detection RNG, and no weather or terrain modifier in the thin slice.

Detection is recomputed from graph relationships and explicit sources at authoritative operational boundaries.

### Direct contact

- Same encounter node or same encounter edge during resolved contact: `fully_observed` for the participating formations.
- A pending tactical battle exposes its authoritative participants and contact location through the existing S10 contract.
- Direct combat knowledge is retained as last-known information after contact ends.

### Recon-capable formations

A formation receives recon capability only from an explicit existing or newly introduced deterministic capability flag. Formation type names must not be guessed heuristically.

- A recon-capable formation observes enemy presence one graph hop from its occupied node or incident edge.
- Base result is `contact`.
- A dedicated recon capability upgrades one tier to `identified`.
- Recon alone never exceeds `assessed` without direct contact.

The Python implementation must begin with a minimal explicit capability source and document every enabled source. It must not classify the entire roster by substring matching.

### Observation and command sites

- A controlled observation or command site projects one graph hop.
- Site-only detection produces `contact`.
- A site and recon source observing the same enemy combine deterministically and may reach `identified` or `assessed` according to the fixed upgrade rules.
- Site ownership remains authoritative in Python.

### Ordinary formations

Ordinary non-recon formations do not project broad passive vision. They know enemies only through direct contact, retained knowledge, coalition sharing, or an explicit observation source.

### Ambush

Before contact, a prepared Ambush reduces the otherwise computed tier by one step:

- `assessed` becomes `identified`;
- `identified` becomes `contact`;
- `contact` becomes `unknown`.

Ambush never prevents deterministic contact resolution and never hides a formation already participating in the same encounter. After Ambush triggers, the battle participant contract may expose the triggered state and received multiplier exactly as S9/S10 already define.

### Legacy no-graph campaigns

Fog of War Off remains unchanged.

When Fog of War On is explicitly selected for a campaign without an operational graph:

- same province is treated as direct observation;
- adjacent province detection requires the same explicit recon or site source;
- no synthetic pixel LOS is introduced;
- observation records use province IDs instead of node or edge fields.

## Refresh order

Observation refresh is deterministic and occurs only at defined boundaries:

1. campaign creation or migration initialization;
2. after an authoritative operational tick completes movement, contact, and Ambush resolution;
3. after battle finalization changes surviving formations or positions;
4. after site ownership changes;
5. before producing a human-facing snapshot;
6. before operational AI planning when Fog of War is On.

A refresh may update knowledge records but must not alter movement, combat, economy, or ownership results.

## Last-known state

When current detection is lost, the last-known record remains fixed at the last observed location. The hidden formation is never moved speculatively.

Each retained record contains:

- `observer_scope_id`;
- `observed_formation_id` when the tier reached `identified` or higher;
- a stable opaque contact ID when identity remains unknown;
- `information_tier`;
- `last_seen_turn`;
- `last_seen_tick`;
- `location_kind`;
- `last_seen_province_id`;
- `last_seen_node_id`, or `last_seen_edge_id`;
- exact canonical edge progress only when the record was `fully_observed`;
- last-observed direction when the tier permits it;
- actor/echelon fields only when identified;
- strength, condition, and supply bands only when assessed;
- sorted information-source labels;
- `currently_visible`.

The thin slice does not automatically delete or downgrade historical records. Staleness is represented by deterministic age fields derived from the current turn/tick and displayed explicitly. Confidence decay and record expiry remain later balance work under issue #77.

## Campaign persistence contract

The Python implementation introduces explicit campaign fields rather than hiding authoritative knowledge inside arbitrary `map_metadata`:

- `fog_of_war_enabled: bool`;
- `knowledge_by_observer: dict[str, dict[str, KnowledgeRecord]]`.

Campaign schema advances from version 4 to version 5.

Migration rules:

- schema 4 and earlier load with Fog of War Off and an empty knowledge store;
- loading does not silently enable Fog of War;
- knowledge records are strictly validated for tier-appropriate fields;
- serialization order is stable by observer scope and record key;
- save/load round trips are byte-stable under the repository's existing deterministic JSON formatting expectations;
- invalid contradictory records fail closed rather than being normalized silently.

## Frontend snapshot contract

The first Python implementation advances the frontend schema from 13 to 14 because enemy row visibility and observation semantics change materially.

With Fog of War Off, schema 14 preserves the existing complete formation and battalion information.

With Fog of War On:

- friendly `strategic_formations` and `battalions` remain complete;
- currently observed enemy formations are emitted only to the permitted tier;
- unknown enemy formations are omitted;
- retained observations appear in a separate `last_known_contacts` array;
- an explicit `fog_of_war` block states whether filtering is enabled and identifies the observer scope;
- hidden battalion, commander, stack, presentation, and order rows are removed rather than blanked;
- province hit testing, color-ID authority, graph geometry, and public ownership remain unchanged.

Schema 13 consumers remain accepted only for Fog of War Off compatibility paths. Godot S11 presentation targets schema 14 and must fail closed if a filtered snapshot omits required observation metadata.

## AI fairness contract

When Fog of War On, `plan_and_issue_operational_orders` must receive an observer-scoped value object produced by the same observation authority used for frontend filtering.

The AI may use:

- full friendly state;
- public graph, terrain, ownership, and objectives;
- current observed enemy contacts to their permitted tier;
- retained last-known records;
- legal movement and route authority.

The AI may not query true enemy positions, exact strength, stance, orders, site progress, or composition through the original `CampaignState` during ranking.

Implementation tests must construct two different true enemy states that produce the same believed observation and prove identical AI decisions. Additional tests must make a hidden true-state change and fail if the planner's output changes.

## Failure and leakage behavior

- Missing graph authority uses the documented province fallback or leaves the contact unknown; it never invents coordinates.
- Malformed knowledge records fail campaign validation.
- A missing observation source cannot be replaced with a UI-side guess.
- Logs and command responses must not include hidden values when operating in an observer context.
- Export and tactical handoff continue to use true authoritative participants after a battle is created; pre-battle UI receives only the filtered operational picture until contact authority exists.
- Fog of War filtering must not modify the true campaign object.

## Test strategy

Python tests must cover:

- deterministic tier ordering and source combination;
- Ambush one-tier concealment;
- coalition observer-scope sharing;
- same-node and same-edge direct observation;
- one-hop recon and site detection;
- legacy province fallback;
- last-known records remaining fixed while hidden truth moves;
- campaign schema 4 to 5 migration;
- invalid knowledge rejection;
- save/load determinism;
- schema 14 filtering with no side-channel leaks;
- Fog of War Off parity with the existing snapshot;
- paired-state AI non-omniscience.

Godot tests in the later presentation PR must cover:

- unknown enemies absent from the map and panels;
- current contact, identified, assessed, fully observed, and stale states visibly distinct;
- no exact hidden values in tooltips or selection models;
- last-known markers fixed at the last observed location;
- stale age display;
- Fog of War Off visual parity;
- province color-ID hit testing unaffected.

## Explicit non-goals

The first S11 chain does not add:

- pixel or physics-based line of sight;
- detection RNG;
- weather, terrain, electronic warfare, air reconnaissance, false contacts, or spies;
- configurable coalition-sharing policies beyond full thin-slice sharing;
- hidden province ownership, construction, recruitment, income, or logistics;
- automatic intelligence decay or expiry;
- exact enemy orders at any information tier;
- a second AI-only truth model;
- changes to S9 contact, Ambush, blocking, or retreat mechanics;
- changes to Earth3 geography, province IDs, crop, adjacency, route authority, or OpenGS evaluation.
