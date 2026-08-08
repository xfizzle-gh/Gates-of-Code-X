# Supply, encirclement, and strategic AI

## Coalition movement

NATO and Ukraine can move through each other's controlled territory. Russia and PRC can do the same. Moving through allied territory does not transfer ownership, and allied battalions may not stack in the same province.

Retreats may use empty allied provinces. A formation can therefore fall back through coalition territory without converting that territory to its own faction.

## Supply sources and routes

Initial faction supply sources are:

- NATO: Sussex, Wester Ems, Warszawa
- Ukraine: Lwow, Zhytomyr
- Russia: Minsk, Leningrad
- PRC: province_0501 in the provisional Central Asian area

Supply routes traverse provinces controlled by the formation's faction or one of its coalition allies. Coalition members can use each other's valid supply sources, but their resources and formations remain separate.

Campaigns without an operational graph continue to use that province-level
model unchanged. In campaigns with an operational graph, S8 bridges only
authoritative sources already present in campaign data: explicit authored
supply-source sites, constructed supply hubs, and province supply-source
metadata. An anchor, city, port, terrain type, owner, name, or nearby geometry
does not create a source.

An authored site participates only while it is enabled and friendly-controlled.
Candidate/non-authored sites and sites with `metadata.disabled` are neither
logical sources nor bridge candidates. Missing site or node authority uses the
existing schema default, `authored`, for older compatible content; an explicit
non-authored authority fails closed. Hostile sites cannot supply a formation or
lend their route node to a province-metadata or constructed-hub source.

The routing-node precedence is an explicit authored source-site node, then a
constructed hub's authored associated node, then the canonical deterministic
province anchor. The underlying source keeps its own logical ID; the anchor is
only its graph attachment point. Province metadata without an object ID uses
`province-supply-source:<province_id>`. A missing anchor fails closed and emits
a stable diagnostic instead of inventing connectivity.

Every selected routing node must exist, belong to the logical source's
province, and be authored. An invalid authored site's own node makes that site
unavailable with a stable diagnostic. For province-metadata and constructed-hub
sources, an invalid higher-precedence node is skipped so the resolver can try
the next approved A/B/C attachment; it never chooses a geometrically near node.

S8 does not invent coalition-wide logistics. Same-faction sources are valid,
and allied sources are shared only through the existing legacy source
eligibility rule. The current legacy campaign model permits the configured
allies to share valid sources, so S8 preserves that behavior rather than adding
a separate coalition policy.

Operational routes use integer-only reverse multi-source Dijkstra traversal.
Directed edges retain their gameplay direction, disabled candidate corridors
remain disabled, sea and ferry edges require explicit `supply_capable: true`,
and other shared movement eligibility gates still apply. Stable route ordering
is total cost, node-ID path, edge-ID path, then source ID. An on-edge segment
uses exact ceiling division:

```text
(edge_cost * segment_milli + 999) // 1000
```

When the `supply_capable` key is present, its value must be an actual Boolean.
`false` blocks every edge kind, `true` opts sea/ferry edges in, and strings,
integers, floats, or null fail with `invalid_supply_capable`. A missing key
retains the existing land-default-on and sea/ferry-default-off behavior.

No floating-point distance or nearest-node geometry participates. Current
production content contains disabled candidate corridors; S8 does not promote
them or silently create routes. Broad operational connectivity may therefore
need a separate authored-route content follow-up outside S8.

Supply connectivity refreshes once after movement, contact, and site capture
on each completed operational tick. A first disconnected tick enters persisted
one-tick grace (`supplied=true`, `cut_off=false`, no source or route,
`grace_ticks_remaining=1`). The next consecutive disconnected tick becomes
cut off. A restored route clears grace immediately. Turn-start, save/load, and
out-of-tick data refreshes are authoritative but do not consume grace, and a
recorded last consuming tick makes duplicate refresh requests idempotent.

The persisted contract permits exactly four shapes: connected, initial
disconnected before a completed tick, one-tick grace, and cut off. Contradictory
field combinations are rejected before load recomputation. A completed tick
greater than the last consuming tick may advance grace, an equal tick is
idempotent, and a lower tick fails with `stale_completed_tick`. Refresh and
grace-consuming tick markers never move backward.

At a round rollover:

- supplied formations recover 20 supply, up to 100
- isolated formations lose 25 supply
- isolation increments `encircled_turns`
- restored supply resets `encircled_turns` to zero
- formations at zero supply cannot move or attack that round
- starting on the third isolated turn, formations at 25 supply or less lose one unit per round

These values are initial balance constants and can be tuned independently from the save format.

## Strategic AI

The deterministic strategic AI processes each formation once per faction turn. It prioritizes:

1. adjacent hostile battalions
2. adjacent neutral provinces
3. adjacent hostile-controlled empty provinces
4. movement through friendly coalition territory toward the nearest hostile front
5. holding when no legal route is available

Battles initiated by AI factions are auto-resolved immediately. A numeric seed makes equivalent campaign states reproducible in tests and debugging.

## Command line

```powershell
gates-of-codex supply-status campaign.json
gates-of-codex supply-status campaign.json --faction nato --refresh
gates-of-codex run-ai-turn campaign.json --faction rusa --seed 7
gates-of-codex run-ai-turn campaign.json --faction rusa --seed 7 --advance-turn
```

`--advance-turn` is accepted only when the selected AI faction is the campaign's current faction.

`supply-status` reports `authority` as either `province` or
`operational_graph`. Operational reports use logical source IDs and formation
S8 state whether or not `--refresh` is requested, and separate connected,
initial-disconnected, grace, and cut-off groups. Province BFS reach retained for
administration is labeled `legacy_admin_reachable_provinces`; it is not an
operational-route count. `--refresh` applies the existing numeric recovery,
drain, and attrition formulas but does not change which authority is reported.

## Frontend contract

Frontend schema version 13 adds a thin operational supply summary to strategic
formations:

- `supplied`
- `cut_off`
- `source_hub_id`

The existing battalion `is_in_supply` field follows its strategic formation in
operational campaigns. The frontend does not receive route internals or mutate
source/control state. Faction summaries carry `supply_authority`. For no-graph
campaigns, `supply_reachable_provinces` retains its province-BFS value. For
graph campaigns that ambiguous field is null; any province BFS retained for
administration is explicitly named
`legacy_admin_supply_reachable_provinces`. Additive operational aggregates are:

- `operational_supply_source_ids`
- `operational_connected_formations`
- `operational_disconnected_formations`
- `operational_grace_formations`
- `operational_cut_off_formations`

Other existing frontend supply fields include:

- province supply-source faction tags
- battalion `is_in_supply`
- battalion `encircled_turns`

The Godot frontend can display these values without duplicating route calculations.
