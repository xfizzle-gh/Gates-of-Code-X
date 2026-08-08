# S11 Fog of War and Detection Design

## Status and authority

Issue #107, issue #77, owner authorization comment `5227987788`, and the correction requested by independent review `4889696294` lock this design. S11 adds deterministic observation and presentation filtering around the existing authoritative campaign state. It does not create a second simulation state and does not alter operational movement, contact, Ambush, retreat, supply, economy, or tactical battle authority.

The design starts from the S10 merge commit `cbef4db96f04d26f4127278041f717691712d7eb`. Delivery remains a reviewed chain:

1. docs-only design PR;
2. Python observation authority and filtering PR;
3. Godot presentation PR.

Each PR remains draft and stops for independent review before the next slice begins.

## Launch phasing and supported play mode

Campaign setup retains:

```text
Fog of War: On / Off
```

The first implementation is available but opt-in for v1 and defaults Off until campaign balance and AI behavior are validated. Fog of War Off preserves current perfect-information behavior.

Fog of War On is supported only for single-player campaigns with exactly one `FactionState.is_human_controlled == true`. Campaign creation, migration to schema 5, load validation, and any command that enables Fog of War must reject a campaign with zero or more than one human-controlled faction using `fog_of_war_requires_single_human_faction`.

Hotseat and remote multiplayer Fog of War are explicit non-goals for the thin slice. They remain usable only with Fog of War Off. There is no seat-transfer protocol, arbitrary observer switch, or retained-client-state purge in PR B or PR C. A human-facing filtered snapshot is bound to the sole human faction; an export caller cannot request another faction's observer picture while Fog of War is On.

Difficulty may change AI planning budget or aggressiveness, but it must not grant hidden-state access.

## Authority boundary

Python owns:

- whether Fog of War is enabled;
- the sole authorized human observer faction;
- observer scope and coalition sharing;
- current detection tier;
- last-known knowledge records;
- deterministic persisted refresh at mutation boundaries;
- pure observation projection for snapshots and AI;
- redaction of enemy formations, stances, strength, locations, orders, site progress, and edge traffic;
- save/load migration and validation.

Godot owns only presentation of the already-filtered snapshot. It must not infer hidden positions, calculate detection, query omitted rows, or recover redacted values from other UI models.

The true `CampaignState` remains authoritative for simulation. Observation is a deterministic projection of that state for one observer scope.

## Observer scope, allied sharing, and alliance validity

The thin slice uses one shared intelligence picture per coalition.

`observer_scope_id(state, faction)` has exactly these results:

- no alliance membership: `faction:<faction_id>`;
- exactly one alliance membership: `alliance:<alliance_id>`;
- more than one alliance membership: fail closed with `ambiguous_observer_scope_multiple_alliances`.

Schema-5 validation rejects any faction appearing in more than one alliance, regardless of whether Fog of War is currently enabled. Schema-4 migration also rejects overlapping membership rather than choosing an alliance by insertion order, name, or sort order.

Coalition members share current contacts and last-known records completely in the thin slice. No duplicate faction and alliance stores may coexist for the same observer. More restrictive sharing policies remain future scenario options under issue #77.

## Information tiers

Enemy knowledge has five ordered tiers:

1. `unknown`
2. `contact`
3. `identified`
4. `assessed`
5. `fully_observed`

`unknown` is represented by absence of a current observation and absence of a retained last-known record. Persisted `KnowledgeRecord` rows with tier `unknown` are invalid.

### Contact

Exposes only:

- that one enemy formation exists;
- a stable opaque contact ID;
- current or last-observed province/node ID, or edge ID without exact progress;
- observation turn and operational tick;
- sorted source labels;
- stale/current state.

It does not expose formation ID, actor, echelon, strength, stance, composition, commander, exact edge progress, or orders.

### Identified

Adds:

- observed strategic formation ID;
- existing formation display identity;
- actor/national identity where already authoritative;
- echelon.

It still does not expose exact strength, composition, stance, commander, exact edge progress, or orders.

### Assessed

Adds:

- deterministic strength band;
- readiness/condition band;
- supply-state band;
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
- selection, tooltip, stack-panel, command-result, log, rejection-reason, or error-message side channels containing the same data.

Dimmed or disabled exact values still count as leaks and are prohibited.

## Exact recon capability authority

PR B introduces one persisted field:

```python
StrategicFormation.recon_capability: bool = False
```

The on-map `StrategicFormation` owns the capability. It is not dynamically inferred from unit names, roster names, battalion type, formation display name, doctrine text, or preferred-category substring matching.

For new bundled Europe campaigns and schema-4 migration, `recon_capability` is set `true` only when `template_formation_id` is one of this exact immutable initial whitelist:

```text
nato-us-airborne
nato-gbr-battlegroup
ukr-air-assault
rusa-vdv
```

Every other bundled or migrated formation defaults `false`. A custom scenario may explicitly persist `recon_capability: true`; omission means `false`. Loading schema 5 never recomputes or overwrites the persisted flag from template metadata.

This whitelist is grounded in the existing formation definitions whose exact `preferred_categories` include `recon`, but runtime authority is the new boolean and exact template-ID migration table, not the category list.

## Exact eligible site authority

A site is a detection source only when all of these conditions hold:

1. it is an authored graph site returned from `graph["sites"]`;
2. `kind` is exactly `observation` or exactly `command`;
3. `route_node_id` is non-empty and resolves to an authored graph node;
4. its current `controller_faction` belongs to the observer scope;
5. `metadata.synthetic_anchor_control_site` is not `true`.

No other site kind is eligible in the thin slice. In particular, `objective`, `capital`, `port`, `airfield`, supply, recruitment, and generic control sites do not provide detection unless a later reviewed design explicitly adds their exact kind.

Synthetic per-province anchor/control sites created by `list_control_sites()` are always excluded, even though they currently use `kind: objective`. A synthetic anchor cannot be made eligible by changing its kind alone; the synthetic metadata flag remains an unconditional exclusion.

## Graph coverage of a source

A node-based recon formation or eligible site covers:

- its occupied/source node;
- every edge incident to that node;
- the opposite endpoint node of each incident edge.

A recon formation currently on an edge covers:

- that occupied edge;
- both endpoint nodes of that edge.

It does not project onto other edges incident to those endpoints until it occupies a node. Ordinary non-recon formations project no passive detection area.

Direct encounter authority remains separate and overrides this coverage model.

## Complete deterministic source-combination table

For one enemy formation, count unique source IDs whose coverage includes the enemy's authoritative node/edge/province location:

- `R` = number of unique recon-capable strategic formation IDs;
- `S` = number of unique eligible authored site IDs.

The same source ID reported through multiple coalition members or code paths counts once. Different sources of the same category do stack according to this table. Source labels are stored sorted by `(source_kind, source_id)`.

Before Ambush concealment, the tier is exactly:

| Direct encounter/contact | R | S | Base tier |
|---|---:|---:|---|
| yes | any | any | `fully_observed` |
| no | 0 | 0 | `unknown` |
| no | 0 | 1 | `contact` |
| no | 0 | 2 or more | `identified` |
| no | 1 | 0 | `identified` |
| no | 1 | 1 or more | `assessed` |
| no | 2 or more | any | `assessed` |

Non-contact source combination is capped at `assessed`. Additional recon formations or sites do not exceed that cap. No weighted score, randomness, insertion order, or “best effort” rule exists.

## Direct contact and Ambush

Same encounter node or same encounter edge during resolved contact is `fully_observed` for the authoritative participating formations. A pending tactical battle exposes its authoritative participants and contact location through the existing S10 contract. Direct combat knowledge is retained as last-known information after contact ends.

Before contact, a prepared Ambush reduces the non-contact base tier by one step:

- `assessed` becomes `identified`;
- `identified` becomes `contact`;
- `contact` becomes `unknown`;
- `unknown` remains `unknown`.

Ambush does not reduce `fully_observed` direct-contact authority, never prevents deterministic contact resolution, and never hides a formation already participating in the same encounter. After Ambush triggers, the battle participant contract may expose the triggered state and received multiplier exactly as S9/S10 define.

## Legacy no-graph campaigns

Fog of War Off remains unchanged.

When Fog of War On is explicitly selected for a campaign without an operational graph:

- same province during authoritative contact is `fully_observed`;
- a recon-capable formation or eligible site in an adjacent province contributes its category count to the same source-combination table;
- no synthetic pixel LOS is introduced;
- observation records use province IDs instead of node or edge fields.

## Persisted refresh and pure projections

Persisted knowledge is refreshed only as part of an authoritative mutation transaction. The order is fixed:

1. apply and validate the authoritative campaign mutation;
2. collect any observation-relevant mutation context, including contact participants and confirmed removals;
3. run `refresh_all_observer_knowledge(state, mutation_context)` exactly once;
4. validate the refreshed campaign;
5. atomically save the campaign in the same mutation operation.

The refresh must occur immediately before the existing atomic `save_campaign` boundary after all mutation substeps are complete. If refresh or validation fails, the campaign save does not replace the prior file.

This transaction rule applies to:

- campaign creation and schema migration save;
- operational tick resolution after movement/contact/Ambush/site capture completes;
- battle auto-resolution and verified external battle import;
- any authoritative formation creation, removal, or future replacement operation;
- end-turn or other commands that mutate observation-relevant positions, ownership, or formations.

Snapshot export and AI planning are read operations. They call only pure projection functions such as `project_operational_observation(state, observer_faction)` and must not call persisted refresh, mutate `knowledge_by_observer`, normalize records, modify campaign fields, or save. Repeated snapshot exports and repeated AI planning calls must leave canonical campaign JSON bytes unchanged.

A current projection may combine the already-persisted knowledge store with current friendly/public data for rendering or planning, but it may not write the result back. Persisted knowledge can change only through the mutation transaction above.

## Opaque contact identity, promotion, and multiplicity

Every persisted record has an authority-only `subject_formation_id` used for refresh and validation. That field is never emitted for a `contact` tier frontend/AI row.

For an unidentified subject, the opaque ID is exactly:

```text
contact-<sha256("goc-s11-contact-v1\0" + observer_scope_id + "\0" + subject_formation_id).hexdigest()>
```

The full 64 lowercase hexadecimal digest is used; it is not truncated. The unidentified record key is `contact:<opaque_id>`. Because observer scope is part of the digest, coalition/faction observers receive different opaque IDs for the same true formation.

Collision handling is fail-closed. If two different `subject_formation_id` values produce the same opaque ID in one observer scope, refresh raises `opaque_contact_collision` before save. It never overwrites, suffixes by insertion order, or merges by location.

Multiple anonymous formations at the same node, edge, or province remain separate records because each subject produces a separate opaque ID. Projection ordering is stable by opaque ID.

Reacquisition rules are exact:

- an unidentified stale subject reacquired below `identified` uses the same opaque key and updates that one record;
- when the subject first reaches `identified` or higher, refresh atomically creates `formation:<subject_formation_id>`, merges the prior contact record's earliest-seen and last-known history, and removes `contact:<opaque_id>` in the same save;
- after promotion, the formation key remains authoritative even if current detection later falls to `contact`; previously learned identity is not forgotten in the no-decay thin slice;
- a promoted subject can never coexist under both keys;
- persisted `unknown` records, a contact key whose digest does not match its observer/subject linkage, a formation key whose ID differs from `subject_formation_id`, or duplicate subject records fail validation.

## Confirmed removal and unseen stale-contact lifecycle

A disappearance from true state is not automatically proof of destruction for every observer.

The authoritative mutation transaction supplies `confirmed_removed_formation_ids_by_observer` in its mutation context. A removal is confirmed for an observer scope only when at least one of these is true at that mutation boundary:

- the observer had the subject `fully_observed` immediately before removal;
- the observer coalition was an authoritative participant in the battle that destroyed or removed the formation;
- a future explicit authoritative removal operation declares that observer scope as a witness.

For a confirmed observer, refresh deletes the subject's contact or formation record in the same atomic save. The thin slice does not retain a destroyed-history marker.

For every other observer, the last record remains stale at its last observed location. It is not deleted merely because the true formation no longer exists. This intentionally permits an obsolete last-known contact until a later intelligence-decay feature or explicit confirmation resolves it.

PR B introduces no formation merge or split command. Any future merge/split/reorganization operation must provide explicit predecessor/successor lineage and witnessed-removal scopes before it can be used with Fog of War On. Without explicit lineage, old unseen subjects remain stale and new formation IDs are treated as new independent subjects; refresh must not infer lineage from location, faction, name, or battalion membership.

## Campaign persistence contract

PR B introduces:

- `StrategicFormation.recon_capability: bool`;
- `CampaignState.fog_of_war_enabled: bool`;
- `CampaignState.knowledge_by_observer: dict[str, dict[str, KnowledgeRecord]]`.

Campaign schema advances from version 4 to version 5.

Migration and validation rules:

- schema 4 and earlier default Fog of War Off;
- schema-4 knowledge defaults empty;
- recon capability migrates only through the exact four-template whitelist above;
- loading does not silently enable Fog of War;
- schema 5 rejects overlapping alliance membership;
- schema 5 with Fog of War On requires exactly one human-controlled faction;
- knowledge records are strictly validated for key, subject linkage, tier-appropriate fields, opaque digest, and sorted unique sources;
- serialization order is stable by observer scope and record key;
- save/load round trips are byte-stable under existing deterministic JSON formatting;
- invalid contradictory records fail closed rather than being normalized silently.

## Frontend snapshot contract

PR B advances the frontend schema from 13 to 14 because enemy row visibility and observation semantics change materially.

With Fog of War Off, schema 14 preserves the existing complete formation and battalion information.

With Fog of War On:

- the observer is the sole human-controlled faction and cannot be overridden by an arbitrary export parameter;
- friendly `strategic_formations` and `battalions` remain complete;
- currently observed enemy formations are emitted only to the permitted tier;
- unknown enemy formations are omitted;
- retained observations appear in `last_known_contacts`;
- `fog_of_war` states filtering and the derived observer scope;
- hidden battalion, commander, stack, presentation, order, site-progress, and edge-traffic rows are removed rather than blanked;
- contact rows expose opaque IDs, never `subject_formation_id`;
- province hit testing, color-ID authority, graph geometry, and public ownership remain unchanged.

Schema-13 consumers remain accepted only for Fog of War Off compatibility paths. Godot S11 presentation targets schema 14 and fails closed if a filtered snapshot omits required observation metadata.

Snapshot creation is pure and read-only. Tests compare serialized campaign bytes before and after repeated exports.

## AI fairness and structural separation

Fog-on AI is split into two stages.

### Pure restricted planner

`build_operational_planning_view(state, faction)` returns an immutable `OperationalPlanningView` containing only:

- full friendly formation state needed for planning;
- public graph, terrain, ownership, objectives, and eligible friendly site state;
- current observed enemy rows to their permitted tier;
- retained last-known records;
- legal route topology and public movement costs.

The value object contains no `CampaignState` reference, no hidden enemy collection, no callback into campaign lookup, and no true-state site-progress or order data.

`plan_operational_intents(view, faction, seed)` is pure. It may rank goals and paths only from this restricted view and returns immutable intents. Access-denial tests pass a proxy that raises if the planner attempts to access undeclared fields or a `CampaignState` object.

### True-state validator/executor

`validate_and_commit_operational_intents(state, faction, intents)` may use true state only to validate and commit the already-ranked intents through existing movement authority. It must preserve intent order and may only accept or reject each intent. It may not rerank, retarget, choose an alternate goal, substitute a different route, or create a new intent from hidden truth.

A rejection caused by hidden truth is exposed to the observer only as a sanitized existing/general legality result such as `route_unavailable`; logs and command responses must not identify the hidden formation, stance, strength, or exact location that caused rejection.

The compatibility wrapper for FOW Off may build a complete planning view, but the same two-stage structure remains.

Tests must prove:

- two different true enemy states with identical planning views produce identical intents;
- the executor does not alter intent order or targets;
- hidden-state changes may change accept/reject outcomes but never planner ranking;
- the pure planner cannot access true campaign state;
- a visible/last-known observation change may alter intents.

## Failure and leakage behavior

- Missing graph authority uses the documented province fallback or leaves the contact unknown; it never invents coordinates.
- Malformed knowledge records fail campaign validation.
- A missing observation source cannot be replaced with a UI-side guess.
- Logs, command responses, rejection reasons, and frontend payloads do not include hidden values.
- Export and tactical handoff use true authoritative participants only after battle creation; pre-battle UI receives the filtered picture until contact authority exists.
- Fog filtering and planning projection do not modify the true campaign object.
- Ambiguous alliance scope, unsupported multi-human Fog-on campaigns, opaque collisions, and contradictory record keys fail closed before save.

## Test strategy

PR B tests must cover:

- exact recon field default, four-template migration whitelist, custom explicit enablement, and no substring/category inference;
- exact eligible site kinds, authored-site requirement, valid route-node requirement, coalition control, and unconditional synthetic-anchor exclusion;
- every row of the deterministic `(direct, R, S)` source-combination table;
- duplicate source deduplication and the non-contact `assessed` cap;
- Ambush one-tier concealment after source combination;
- coalition observer sharing and overlapping-alliance rejection;
- Fog-on exactly-one-human validation and Fog-off hotseat parity;
- same-node/same-edge direct observation and one-hop graph coverage;
- legacy province fallback;
- persisted refresh only before atomic saves at mutation boundaries;
- repeated snapshot exports and AI projections leaving canonical campaign bytes unchanged;
- full opaque-ID formula, reacquisition, collision failure, promotion rekey, duplicate-key rejection, and same-location multiplicity;
- confirmed observed destruction deleting records and unseen removal retaining stale records;
- no inferred merge/split lineage;
- campaign schema 4-to-5 migration and byte-stable save/load;
- schema-14 field filtering with no side-channel leaks;
- Fog-off parity;
- restricted `OperationalPlanningView`, access-denial proxy, paired-state intent parity, and executor no-rerank behavior.

PR C Godot tests must cover:

- unknown enemies absent from map and panels;
- current contact, identified, assessed, fully observed, and stale states visibly distinct;
- separate anonymous contacts at one location remain separately represented;
- contact-to-identified promotion produces one marker, not duplicates;
- confirmed destruction removes a marker while unseen stale removal remains;
- no exact hidden values in tooltips, selection, accessibility text, or cached models;
- last-known markers fixed at the last observed location;
- stale age display;
- Fog-off visual parity;
- province color-ID hit testing unaffected.

## Explicit non-goals

The first S11 chain does not add:

- Fog-on hotseat or remote multiplayer;
- arbitrary observer switching;
- pixel or physics-based line of sight;
- detection RNG;
- weather, terrain, electronic warfare, air reconnaissance, false contacts, or spies;
- configurable coalition-sharing policies beyond full thin-slice sharing;
- hidden province ownership, construction, recruitment, income, or logistics;
- automatic intelligence decay or expiry;
- exact enemy orders at any information tier;
- a second AI-only truth model;
- inferred formation merge/split lineage;
- changes to S9 contact, Ambush, blocking, or retreat mechanics;
- changes to Earth3 geography, province IDs, crop, adjacency, route authority, or OpenGS evaluation.
