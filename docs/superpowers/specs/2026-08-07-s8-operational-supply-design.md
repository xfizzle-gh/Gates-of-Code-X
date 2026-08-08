# S8 Operational Supply Hooks Design

**Issue:** #105

**Branch:** `feat/s8-operational-supply`

**Base:** current `origin/main` at `be455985da4c4adcaaf7d7cf54f918b07d321fa7`

**Status:** Approved for implementation on 2026-08-07

**Independent review amendment:** Approved correction requirements received
after exact reviewed head
`92174272be558a9e7ac5e0f70a84f8efa893fd92`.

## Purpose and boundaries

S8 connects the existing strategic supply and degradation system to authoritative operational graph positions, route edges, and controlled source sites. It does not replace the legacy province supply model for campaigns without an operational graph. It also does not add logistics capacity, fuel, convoys, recruitment changes, new damage or attrition formulas, naval blockade simulation, AI supply scoring, or presentation work beyond an additive read-only frontend summary.

OpenGS evaluation files and workflows, Earth3 geography and water policy, theatre-expansion preview assets, island-coastline work, and deferred Godot draw-call optimization are outside S8 and remain untouched.

## Architecture

Create `src/gates_of_codex/operational_supply.py` as the graph-specific authority. The module owns source resolution, supply-edge eligibility, deterministic routing, formation refresh transitions, diagnostics, and schema migration. Existing `supply.py` remains the authority for numeric recovery, drain, encirclement counters, and attrition. For operational campaigns, that existing strategic refresh consumes each strategic formation's S8 connectivity state instead of recalculating province reachability. For no-graph campaigns, all existing `supply.py` behavior remains unchanged.

`StrategicFormation` receives versioned, serialized S8 fields:

- `supplied: bool`
- `cut_off: bool`
- `source_hub_id: str | None`
- `route_cost: int | None`
- `grace_ticks_remaining: int`
- `last_supply_refresh_tick: int | None`
- `last_supply_refresh_turn: int | None`
- `last_grace_consuming_tick: int | None`

The S8 campaign migration version is 8. Migration and validation run only when an operational graph resolves. A no-graph save is not upgraded or rewritten for S8. The stable migration record is stored under `map_metadata["operational_supply_migration"]` using the same convention as the S2 position migration.

## Logical supply sources and routing nodes

Logical source identity is always separate from the operational node used for graph traversal. A node never becomes a source merely because it is an anchor, hub-looking node, port, city, or geometric neighbor.

An authoritative logical source exists only when campaign data already provides one:

1. an explicitly authored supply-source site;
2. an already-constructed province supply hub;
3. existing province `supply_source_for` or `static_supply_source_for` metadata.

Explicit authored sources include depots and supply hubs already represented as sources, plus ports or objectives only when explicitly tagged or marked as supply sources. Names, pixels, terrain, ownership alone, site proximity, and geometry never create sources.

Stable logical IDs are:

- authored source site: its existing `site_id`;
- constructed province hub without an existing object ID: `constructed-supply-hub:<province_id>`;
- province metadata source without an object ID: `province-supply-source:<province_id>`.

If construction-generated `supply_source_for` metadata represents the same constructed hub, source enumeration deduplicates that authority rather than fabricating a second logical source. Independently authored sources in the same province remain distinct.

The routing-node precedence for each logical source is:

1. an explicit authored supply-source site's `route_node_id` in the province;
2. the constructed hub's explicitly associated or authored node when present;
3. the canonical stable province anchor from the existing `stable_node_id(province_id, "anchor")` contract.

No nearest-node or pixel-distance fallback is allowed. Multiple logical sources may use the same routing node and retain distinct source IDs. An authoritative source with no resolvable node is excluded from routing and emitted in a sorted diagnostic record with its source ID, province ID, and stable reason `missing_anchor`. Invalid site or node references similarly fail closed without modifying ownership, site control, or graph content.

Source usability is evaluated at every refresh. Existing faction eligibility is retained: same-faction sources are valid, and allied sources are valid only where the existing legacy model's `allied_factions` and source metadata rules already permit sharing. S8 does not introduce a new coalition logistics pool. The source's province and, for authored sites, current site controller must be friendly under those existing rules. Capture, construction, removal, disabling, or control changes therefore affect the next refresh without mutating source or control state during evaluation.

Independent review tightens that authority boundary. A source site participates
only when it is authored, enabled, friendly-controlled, and attached to a valid
authored node in the same province. `StrategicSite.authority` and
`OperationalRouteNode.authority` default to `authored`, so a missing serialized
authority retains that existing schema-compatible default; any explicit
non-authored value fails closed. `site.metadata.disabled` uses the repository's
existing disabled metadata vocabulary and excludes the site both as a logical
source and as an A/B/C bridge candidate.

Every node selected by source-site, constructed-hub association, explicit-site
precedence, or canonical anchor must exist, have authored authority, and name
the same province as the logical source. An invalid higher-precedence bridge
candidate is ignored for province-metadata and constructed-hub sources so the
resolver can try the next approved precedence level. An authored site whose own
route node is invalid is excluded and receives a stable diagnostic. Hostile or
disabled sites never hijack the routing node of another logical source.

## Edge eligibility and directed routing

Every supply hop first passes the shared operational movement gates in `assert_edge_hop_legal`: the edge must be enabled, authored rather than candidate, not blocked by shared metadata, and legal in the requested direction.

Land edges are supply-capable by default after those checks. `ferry`, `ferry_or_sea_lane`, and `sea_lane` edges are supply-capable only when `edge.metadata["supply_capable"] is True`. A false `supply_capable` value blocks any edge. No open-sea or geometric connection is synthesized. Candidate corridors remain disabled and are never promoted.

If `supply_capable` is present, its value must be an actual Boolean. `False`
blocks every edge kind and `True` explicitly opts ferry/sea edges in. Strings,
integers, floats, and null fail closed with the stable error token
`invalid_supply_capable`. Missing metadata retains the land-default and
ferry/sea-default-off behavior.

Routing also retains the legacy friendly-territory rule: route nodes must belong to provinces friendly to the formation under existing faction/alliance rules. This preserves the current province supply authority while changing connectivity to use authored graph hops.

## Deterministic traversal contract

For each faction, S8 builds legal directed hops and runs reverse multi-source Dijkstra from all currently usable logical sources. Reversing the search representation does not reverse gameplay legality: an original legal hop `u -> v` contributes a reverse-search expansion `v -> u`, which computes whether `u` can legally reach a source through `v`.

All costs are integers. Each edge contributes `max(1, movement_cost_milli)`. The complete comparison key is:

1. total route cost;
2. tuple of node IDs from the evaluated node toward the source;
3. tuple of edge IDs in that same order;
4. logical source-hub ID.

Heap entries and retained best-path entries use the complete key. Nodes, edges, sources, formations, and diagnostics are enumerated in sorted stable-ID order. No result depends on dictionary or set insertion order.

An at-node formation uses the best result for its node. An on-edge formation evaluates both endpoints when the occupied edge is itself supply-capable and directionally legal from the formation's position toward that endpoint. Let `p` be canonical fixed-point progress from edge `a` to `b`, in `0..1000`, and let `C = max(1, movement_cost_milli)`. Endpoint attachment costs use integer ceiling division:

- toward `a`: `(C * p + 999) // 1000`;
- toward `b`: `(C * (1000 - p) + 999) // 1000`.

The attachment cost is added to that endpoint's routed cost. A one-way `a -> b` edge permits on-edge access toward `b` but not back toward `a`. If only one endpoint reaches a valid source, that endpoint wins. If both do, the same full comparison key chooses the result. Floating-point geometry and Euclidean distance are never used.

## Refresh lifecycle and grace state

Supply refresh runs once per completed operational tick, after movement, swept/static contact resolution, and control-site capture resolution. This is the only refresh mode that may begin or consume grace.

Authoritative non-consuming recomputation also runs:

- at strategic-turn start;
- during save preparation and after load;
- after explicit data or control changes outside an operational tick when invoked by callers.

Non-consuming refreshes update connectivity, chosen source, route cost, diagnostics, and restoration, but never advance an already-disconnected formation through grace. `last_grace_consuming_tick` makes repeated calls for the same completed global tick idempotent.

The exact persisted state machine is:

| Event | supplied | cut_off | source_hub_id | route_cost | grace_ticks_remaining |
|---|---:|---:|---|---:|---:|
| Connected | true | false | deterministic source | deterministic integer | 0 |
| First disconnected operational tick | true | false | null | null | 1 |
| Next consecutive disconnected operational tick | false | true | null | null | 0 |
| Connectivity restored at any refresh | true | false | deterministic source | deterministic integer | 0 |

Those four rows are also the complete set of valid serialized field shapes.
Any contradictory combination of `supplied`, `cut_off`, source, cost, and grace
is rejected before load-time recomputation can normalize it. A consuming tick
must be greater than the formation's last consuming tick to advance grace. An
equal tick is idempotent; a lower tick raises `stale_completed_tick` before any
formation supply field changes. Authoritative and grace-consuming tick markers
are monotonic across tick, turn-start, save, load, and frontend recomputation.

Save/load preserves the one-tick grace row exactly. Post-load authoritative recomputation is non-consuming: if connectivity is still absent it leaves `grace_ticks_remaining=1`; if restored it clears grace immediately. A duplicate refresh of the same operational tick cannot consume grace twice.

The strategic-turn numeric supply refresh remains once per existing round rollover. When an operational graph exists it classifies every battalion through its parent strategic formation's `supplied` state, then applies the existing restore/drain, `encircled_turns`, movement/action gating, and attrition functions unchanged. Multi-battalion formations share one connectivity result but retain per-battalion numeric supply state.

## Save/load and frontend contract

State serialization writes and strictly parses all S8 formation fields. Optional integer fields reject booleans, strings, and floats using repository strict-integer conventions. Malformed references fail closed during operational refresh; malformed serialized scalar shapes raise deterministic validation errors rather than being coerced.

The frontend contract is additive and read-only. Its schema version increases from 12 to 13. Strategic formations export only `supplied`, `cut_off`, and `source_hub_id`. Existing battalion `is_in_supply` reads its strategic formation's S8 state for graph campaigns and retains province reachability for no-graph campaigns. No logistics UI, map visualization, animation, or write-back command is added.

User-facing status reports carry an explicit authority discriminator:
`operational_graph` or `province`. Graph campaigns classify battalions and
formations from S8 state even without a numeric refresh, and expose connected,
grace, and cut-off groups plus logical operational source IDs. Legacy province
BFS data, if retained for administration, is labeled
`legacy_admin_reachable_provinces` and is never presented as operational graph
reach. `SupplyReport`, `supply-status`, and frontend faction aggregates use the
same naming. No-graph output retains its established province fields and adds
only explicit authority/additive status where required by the versioned
contract.

## Independent review implementation choice

Three correction strategies were evaluated:

1. validate and reconstruct the complete `OperationalGraph` on every refresh;
2. add centralized, fail-closed S8 predicates for usable sites and source nodes;
3. broaden the graph schema and migration layer to encode supply-specific
   authority globally.

S8 uses option 2. It applies the existing schema defaults and shared metadata
vocabulary without mutating graph content, keeps invalid higher-precedence
candidates local to source bridging, and avoids rejecting unrelated movement
content or creating a cross-feature schema migration. Full graph validation and
supply-specific graph rewriting remain outside this focused review correction.

## Validation and compatibility

Focused tests cover connected and cut routes, the exact two-tick grace transition, restoration, source capture, on-edge endpoint selection and fixed-point rounding, equal-cost determinism, every edge gate, directed edges, ferry/sea opt-in, serialization, post-load recomputation, insertion-order independence, empty and malformed graphs, missing sites and anchors, unresolved formation positions, all source-bridge precedence rules, and source-sharing behavior.

Compatibility tests snapshot no-graph campaign behavior before and after all S8 entry points and prove that reachable provinces, battalion supply, encirclement, attrition, schema version, and serialized S8 absence remain unchanged. Existing S1-S7, serialization/migration, frontend contract, and full repository CI suites must remain green.

The current production operational graph contains disabled candidate land corridors. S8 will not enable them, so broad operational supply connectivity may require a separate authored-route content follow-up. That content work is explicitly outside issue #105.
