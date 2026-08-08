# S11 Fog of War and Detection Design

## Status and authority

Issue #107, issue #77, owner authorization comment `5227987788`, independent review `4889696294`, and compatibility review `4889771055` lock this design. S11 adds deterministic observer-scoped knowledge and presentation filtering around the existing authoritative campaign state. It does not create a second simulation state and does not alter operational movement, contact, Ambush, retreat, supply, economy, or tactical battle authority.

The design starts from S10 merge commit `cbef4db96f04d26f4127278041f717691712d7eb`. Delivery remains a reviewed chain:

1. docs-only design PR;
2. Python observation authority and filtering PR;
3. Godot presentation PR.

Each PR remains draft and stops for independent review before the next slice begins.

## Launch phasing and supported play mode

Campaign setup retains:

```text
Fog of War: On / Off
```

Fog of War is opt-in and defaults Off. Fog Off preserves the current perfect-information campaign behavior.

Fog On is supported only for single-player campaigns with exactly one `FactionState.is_human_controlled == true`. Campaign creation, schema-6 migration, load validation, and any command that enables Fog must reject zero or multiple human-controlled factions with `fog_of_war_requires_single_human_faction`.

Hotseat and remote multiplayer remain available only with Fog Off. PR B and PR C add no seat-transfer protocol, arbitrary observer switch, or retained-client-state purge. A Fog-on human-facing snapshot is bound to the sole human faction and cannot request another faction's observer picture.

Difficulty may change AI planning budget or aggressiveness, but it must not grant hidden-state access.

## Authority boundary

Python owns:

- whether Fog is enabled;
- the sole authorized human observer faction;
- observer scope and coalition sharing;
- current detection tiers;
- persisted last-known knowledge;
- deterministic refresh at authoritative mutation boundaries;
- pure read-only projection for snapshots and AI;
- redaction of enemy formations, stances, strength, locations, orders, site progress, and edge traffic;
- campaign migration, validation, and serialization.

Godot owns only presentation of the already-filtered snapshot. It must not calculate detection, query omitted truth, infer hidden positions, or recover redacted values from other UI models.

The true `CampaignState` remains the only simulation authority.

## Observer scope, allied sharing, and alliance compatibility

The thin slice uses one shared intelligence picture per coalition.

`observer_scope_id(state, faction)` has exactly these results when observer scope is requested:

- no alliance membership: `faction:<faction_id>`;
- exactly one alliance membership: `alliance:<alliance_id>`;
- more than one alliance membership: fail with `ambiguous_observer_scope_multiple_alliances`.

Overlapping alliance membership is rejected only when at least one S11 observer condition applies:

1. `fog_of_war_enabled` is `true`;
2. at least one persisted S11 `KnowledgeRecord` exists in `knowledge_by_observer`; or
3. code requests an observer scope, observation projection, filtered snapshot, knowledge refresh, or Fog-on AI planning view.

A valid Fog-off campaign with an empty S11 knowledge store is not globally rejected merely because a faction appears in multiple alliances. This preserves current legacy behavior. Such a campaign may load, migrate, save, and run through the complete Fog-off path without deriving observer scope.

If an overlapping-alliance campaign later enables Fog, gains S11 knowledge, or requests observer scope, it fails closed before projection or save. No implementation may choose one alliance by insertion order, lexical order, display name, or first match.

Coalition members share current contacts and last-known records completely. No duplicate faction and alliance stores may coexist for one observer subject. More restrictive sharing remains future work under #77.

## Information tiers

Enemy knowledge has five ordered tiers:

1. `unknown`
2. `contact`
3. `identified`
4. `assessed`
5. `fully_observed`

`unknown` is represented by absence of a current observation and absence of a retained record. Persisted records with tier `unknown` are invalid.

### Contact

Exposes only:

- that one enemy formation exists;
- a stable opaque contact ID;
- current or last-observed province/node ID, or edge ID without exact progress;
- observation turn and operational tick;
- sorted source labels;
- current/stale state.

It does not expose formation ID, actor, echelon, strength, stance, composition, commander, exact edge progress, or orders.

### Identified

Adds:

- observed strategic formation ID;
- existing display identity;
- actor or national identity where authoritative;
- echelon.

It still hides exact strength, composition, stance, commander, exact edge progress, and orders.

### Assessed

Adds deterministic strength, condition/readiness, and supply bands plus last-observed direction when available. Exact counts and percentages remain hidden.

### Fully observed

Adds the exact current operational position and existing formation details needed for direct contact or battle presentation. Enemy movement orders and intended destinations remain hidden at every tier. Triggered Ambush metadata may appear through the authoritative S9/S10 battle participant contract; untriggered Ambush stance remains hidden.

## Always-known and hidden information

With Fog On, these remain public:

- authored province boundaries and IDs;
- route graph, terrain, nodes, and edges;
- friendly formations, positions, orders, stances, and detailed state;
- friendly-controlled ownership and sites;
- public objectives;
- coalition-shared observations;
- province ownership in the thin slice.

Unless permitted by the current tier, snapshots, AI views, command results, logs, rejection messages, tooltips, stack panels, selection models, accessibility text, and cached presentation models must not expose:

- exact enemy node or edge progress;
- exact identity;
- battalion membership or composition;
- exact condition, supply, experience, or strength;
- commander identity;
- stance, including untriggered Ambush;
- movement order, route, remaining path, or destination;
- enemy site-control progress;
- hidden edge traffic.

Blanked, dimmed, disabled, or indirectly countable exact values still constitute leaks.

## Exact recon capability authority

PR B introduces:

```python
StrategicFormation.recon_capability: bool = False
```

The on-map `StrategicFormation` owns this authority. Runtime code must not infer recon from names, roster text, battalion type, formation kind, doctrine text, or preferred-category substrings.

For new bundled campaigns and both legacy migration paths, `recon_capability` becomes `true` only when `template_formation_id` is in this immutable initial whitelist:

```text
nato-us-airborne
nato-gbr-battlegroup
ukr-air-assault
rusa-vdv
```

Every other migrated formation defaults `false`. Custom schema-6 scenarios may explicitly persist either boolean. Schema-6 loads preserve the persisted value and never recompute it.

## Exact eligible site authority

A site contributes detection only when all conditions hold:

1. it is authored in `graph["sites"]`;
2. `kind` is exactly `observation` or `command`;
3. `route_node_id` is non-empty and resolves to an authored graph node;
4. its current controller belongs to the observer scope;
5. `metadata.synthetic_anchor_control_site` is not `true`.

No other site kind is eligible. `objective`, `capital`, `port`, `airfield`, supply, recruitment, generic control, and unknown kinds contribute nothing.

Synthetic per-province anchors created by `list_control_sites()` are always excluded, even if their kind is changed to an eligible value.

## Source coverage

A node-based recon formation or eligible site covers:

- its occupied/source node;
- every incident edge;
- the opposite endpoint of each incident edge.

A recon formation on an edge covers:

- the occupied edge;
- both endpoint nodes.

It does not spill onto other edges incident to those endpoints until it occupies a node. Ordinary formations project no passive detection area. Direct encounter authority is separate and overrides source coverage.

## Complete deterministic source-combination table

For one enemy formation:

- `R` is the number of unique covering recon-capable strategic formation IDs;
- `S` is the number of unique covering eligible authored site IDs.

Duplicate reports of one source ID count once. Different source IDs stack exactly as follows. Source labels sort by `(source_kind, source_id)`.

| Direct contact | R | S | Base tier |
|---|---:|---:|---|
| yes | any | any | `fully_observed` |
| no | 0 | 0 | `unknown` |
| no | 0 | 1 | `contact` |
| no | 0 | 2 or more | `identified` |
| no | 1 | 0 | `identified` |
| no | 1 | 1 or more | `assessed` |
| no | 2 or more | any | `assessed` |

Non-contact detection is capped at `assessed`. No weighted score, randomness, insertion-order rule, or best-effort fallback exists.

## Direct contact and Ambush

An authoritative same-node or same-edge encounter gives `fully_observed` to participating formations. A pending battle exposes authoritative participants and contact location through the existing S10 contract.

Before contact, prepared Ambush reduces the non-contact tier by one step:

- `assessed` to `identified`;
- `identified` to `contact`;
- `contact` to `unknown`;
- `unknown` remains `unknown`.

Ambush never reduces direct-contact authority, prevents contact resolution, or hides a participating formation.

## Legacy no-graph campaigns

Fog Off remains unchanged.

When Fog On is explicitly selected without an operational graph:

- authoritative same-province contact is `fully_observed`;
- recon formations and eligible sites in adjacent provinces contribute to the same source table;
- no pixel line of sight is introduced;
- records use province IDs instead of node/edge fields.

## Campaign schema 6 and migration contract

Current pre-S11 `main` already writes campaign schema 5. S11 therefore allocates campaign schema 6.

PR B introduces:

- `StrategicFormation.recon_capability: bool`;
- `CampaignState.fog_of_war_enabled: bool`;
- `CampaignState.knowledge_by_observer: dict[str, dict[str, KnowledgeRecord]]`.

The S11 field set is:

- top-level `fog_of_war_enabled`;
- top-level `knowledge_by_observer`;
- `recon_capability` on every serialized strategic formation.

Migration is exact:

### Schema 4 and earlier to schema 6

- set `fog_of_war_enabled = false`;
- set `knowledge_by_observer = {}`;
- set recon capability through the exact four-template whitelist;
- preserve all existing Fog-off campaign behavior and authoritative state;
- write schema 6 only at the normal atomic migration/save boundary.

### Existing pre-S11 schema 5 to schema 6

A schema-5 save with the S11 field set absent is a valid legacy pre-S11 save, not malformed schema 6.

It migrates exactly like schema 4 and earlier:

- Fog defaults Off;
- knowledge defaults empty;
- recon capability uses the exact whitelist;
- existing campaign state and Fog-off behavior remain unchanged.

Schema 5 is never interpreted as an S11 schema. A schema-5 file containing a partial or complete pre-release S11 field set fails with `unexpected_s11_fields_in_schema5`; it is not silently treated as schema 6.

### Schema 6 validation

Schema 6 requires all S11 fields with their exact types. Missing schema-6 S11 fields are malformed. Records are strictly validated for observer/key/subject linkage, tier-appropriate fields, opaque digest, and sorted unique sources.

Alliance ambiguity validation is conditional:

- overlapping membership is allowed when Fog is Off, knowledge contains no records, and no observer scope is requested;
- overlapping membership fails when Fog is On;
- overlapping membership fails when any S11 knowledge record exists;
- overlapping membership fails whenever observer scope or an observer projection is requested.

Both migration paths default Fog Off. Neither migration silently enables filtering or creates knowledge. Serialization is stable by observer scope and record key, and deterministic save/load round trips are byte-stable.

## Persisted refresh and pure projections

Persisted knowledge changes only inside an authoritative mutation transaction:

1. apply and validate the authoritative mutation;
2. collect observation-relevant context, including contact participants and confirmed removals;
3. run `refresh_all_observer_knowledge(state, mutation_context)` exactly once;
4. validate the refreshed campaign;
5. atomically save in the same operation.

Refresh occurs immediately before the existing atomic save after all mutation substeps. Refresh or validation failure preserves the prior file.

This applies to campaign creation/migration save, operational ticks, site capture, battle auto-resolution, verified external imports, formation creation/removal, end turn, and future observation-relevant mutations.

Snapshot export and AI planning are pure reads. They may call `project_operational_observation(state, observer_faction)` but must not refresh, normalize, mutate, or save. Repeated projections, exports, and plans leave canonical campaign bytes unchanged.

Fog-off legacy paths with empty knowledge do not request observer scope and therefore do not trigger overlapping-alliance rejection.

## Opaque contact identity, promotion, and multiplicity

Every persisted record has an authority-only `subject_formation_id`, never emitted in a contact-tier frontend or AI row.

The opaque ID is exactly:

```text
contact-<sha256("goc-s11-contact-v1\0" + observer_scope_id + "\0" + subject_formation_id).hexdigest()>
```

The full lowercase 64-hex digest is used. Unidentified records use `contact:<opaque_id>`; identified records use `formation:<subject_formation_id>`.

Collisions between distinct subjects fail with `opaque_contact_collision` before save. No suffixing, overwrite, or location merge is allowed. Multiple anonymous formations at one location remain separate and sort by opaque ID.

Reacquisition and promotion are exact:

- unidentified reacquisition below `identified` reuses the same opaque key;
- first identification atomically creates the formation key, merges history, and removes the opaque key;
- promoted identity remains known in this no-decay slice even if later detection falls to contact;
- both keys may never coexist;
- persisted unknown rows, digest mismatches, formation-key mismatches, and duplicate subjects fail validation.

## Confirmed removal and unseen stale lifecycle

A true-state disappearance is not automatically confirmed for every observer.

`ObservationMutationContext.confirmed_removed_formation_ids_by_observer` confirms removal only when:

- the observer had the subject fully observed immediately before removal;
- the observer coalition participated in the destroying/removing battle; or
- an explicit authoritative operation declares that observer a witness.

Confirmed records are deleted in the same atomic save. Unseen removals remain stale at the last observed location. The thin slice stores no destroyed-history marker.

PR B introduces no merge/split command. Future reorganization requires explicit predecessor/successor lineage and witness scopes. Without lineage, old unseen subjects remain stale and new IDs are independent; no lineage is inferred from location, faction, name, or battalion membership.

## Frontend schema 14

PR B advances the frontend schema from 13 to 14.

Fog Off preserves complete current formation and battalion information. Schema-13 compatibility remains accepted only on Fog-off paths.

With Fog On:

- the observer is the sole human faction and cannot be overridden;
- friendly formations and battalions remain complete;
- observed enemies are emitted only to the permitted tier;
- unknown enemies are omitted;
- retained observations appear in `last_known_contacts`;
- `fog_of_war` identifies filtering and observer scope;
- hidden battalion, commander, stack, presentation, order, site-progress, and edge-traffic rows are removed;
- contact rows expose opaque IDs, never `subject_formation_id`;
- graph geometry, province hit testing, color-ID authority, and public ownership remain unchanged.

Snapshot creation is pure and byte-neutral.

## AI fairness and structural separation

Fog-on AI has two stages.

### Pure restricted planner

`build_operational_planning_view(state, faction)` returns an immutable `OperationalPlanningView` containing only friendly state, public graph/terrain/ownership/objectives, eligible friendly sites, permitted current observations, retained last-known records, and legal route topology/costs.

It contains no `CampaignState` reference, hidden enemy collection, callbacks, hidden site progress, or hidden orders.

`plan_operational_intents(view, faction, seed)` is pure and ranks only from this view.

### True-state validator/executor

`validate_and_commit_operational_intents(state, faction, intents)` may use truth only to accept or reject already-ranked intents and commit accepted intents through existing authority. It must preserve order and may not rerank, retarget, substitute routes, select alternate goals, or create new intents.

Hidden-truth rejection is sanitized, such as `route_unavailable`, without revealing formation, stance, strength, or location.

Fog Off uses the same two-stage structure with a complete planning view.

## Failure and leakage behavior

- Missing graph authority uses the documented province fallback or leaves contact unknown.
- Malformed knowledge records fail validation.
- Missing sources are not replaced by UI guesses.
- Logs, commands, errors, and rejection reasons expose no hidden values.
- Tactical export uses true participants only after battle creation.
- Projection never mutates campaign truth.
- Overlapping alliances fail only when S11 observer authority is active or requested.
- Unsupported multi-human Fog-on campaigns, opaque collisions, and contradictory record keys fail before save.

## Test strategy

PR B must test:

- exact recon defaults, whitelist migration, explicit custom values, and no heuristic inference;
- exact site eligibility and synthetic-anchor exclusion;
- every source-table row, deduplication, ordering, and assessed cap;
- Ambush concealment;
- coalition sharing;
- schema-4 to schema-6 migration;
- existing pre-S11 schema-5 to schema-6 migration with absent S11 fields;
- Fog Off by default on both migration paths;
- missing S11 fields in schema 5 accepted as valid legacy state;
- missing required S11 fields in schema 6 rejected;
- Fog-off overlapping-alliance compatibility;
- Fog-on overlapping-alliance rejection;
- S11-knowledge overlapping-alliance rejection;
- observer-scope-request overlapping-alliance rejection;
- exactly-one-human Fog-on validation and Fog-off hotseat parity;
- same-node/same-edge contact and no-graph fallback;
- mutation-only refresh and atomic failure behavior;
- byte-neutral projections, exports, and AI planning;
- opaque-ID vectors, collisions, reacquisition, promotion, multiplicity, and validation;
- confirmed destruction versus unseen stale retention;
- no inferred merge/split lineage;
- schema-14 redaction and side-channel closure;
- restricted planning-view access and executor no-rerank behavior.

PR C must test:

- unknown enemies absent;
- current contact, identified, assessed, fully observed, and stale states visibly distinct;
- anonymous same-location multiplicity;
- one marker after promotion;
- confirmed removal absent versus unseen removal stale;
- no exact hidden values in UI or cached models;
- fixed last-known location and age;
- Fog-off visual parity;
- unchanged province hit testing.

## Explicit non-goals

The first S11 chain does not add:

- Fog-on hotseat or remote multiplayer;
- arbitrary observer switching;
- pixel or physics line of sight;
- detection RNG;
- weather, terrain, electronic warfare, air reconnaissance, false contacts, or spies;
- configurable sharing beyond full coalition sharing;
- hidden province ownership, construction, recruitment, income, or logistics;
- automatic intelligence decay or expiry;
- exact enemy orders at any tier;
- a second AI truth model;
- inferred merge/split lineage;
- a campaign-wide prohibition on overlapping alliances while S11 observer authority is inactive;
- changes to S9 contact/Ambush/blocking/retreat;
- changes to Earth3 geography, IDs, crop, adjacency, route authority, or OpenGS evaluation.
