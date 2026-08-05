# Spike: Intra-province operational maneuver (hybrid route graph)

**Issue:** #66  
**Status:** Design only — **no production implementation in this document**  
**Recommendation:** Hybrid route-graph (deterministic sim + continuous display interpolation)  
**Depends on:** merged formation schema (#61), EM theatre (#64), stack panel (#69)

---

## 1. Goals

Keep **color-ID province polygons** as administrative authority while formations move with real positions:

| Concern | Authority |
|---|---|
| Ownership, economy, construction, recruitment, supply region | **Province** |
| Actual army location, interception, ambush, retreat, battle site | **Operational position on route graph** |
| Settlements, ports, airfields, bridges, facilities, objectives | **StrategicSite** |
| Roads, rail, ferries, straits, mountain passes, sea lanes | **OperationalRouteEdge** |

### Required capabilities

- Multiple formations at different positions inside one province
- Ownership ≠ temporary presence
- Sites with explicit positions
- Interception by route/proximity
- Ambush / blocking
- Retreat paths
- Terrain/route-type movement costs (integrates today’s unused `edge_meta` multipliers)
- Battle location from encounter position
- Capture via site occupation, not mere polygon entry

---

## 2. Option comparison

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Continuous 2D** free movement in polygons | Natural look | Non-deterministic floats, hard AI, saves, interception | Reject for sim core |
| **B. Authored waypoint graph only** | Deterministic, AI-friendly | Rigid; more authoring | Acceptable but stiff |
| **C. Hybrid (recommended)** | Display lerp on graph edges; sim discrete | Need graph + display layer | **Default** |

**Repo fit:** Existing color-ID, province adjacency, formation-authoritative location, and typed sea crossings already resemble a coarse graph. Hybrid extends that without abandoning determinism.

---

## 3. Core schemas (proposed)

### 3.1 `StrategicSite`

```json
{
  "site_id": "site_wester_ems_town",
  "display_name": "Wester Ems",
  "kind": "settlement",
  "province_id": "Wester Ems",
  "pixel": [412, 508],
  "route_node_id": "node_wester_ems_hub",
  "control_weight": 1.0,
  "capture_threshold": 1.0,
  "tags": ["town", "supply_eligible"],
  "facilities": ["supply_hub_slot", "recruitment_slot"],
  "owner_faction": null,
  "metadata": {}
}
```

**Kinds (enum):**  
`settlement | port | airfield | bridge | facility | objective | crossing | fort | depot`

### 3.2 `OperationalRouteNode`

```json
{
  "node_id": "node_wester_ems_hub",
  "display_name": "Wester Ems hub",
  "pixel": [412, 508],
  "province_id": "Wester Ems",
  "site_id": "site_wester_ems_town",
  "terrain": "urban",
  "is_hub": true
}
```

Nodes may exist without sites (road junctions). Every site should reference a node.

### 3.3 `OperationalRouteEdge`

```json
{
  "edge_id": "edge_wester_ems__westfalen_road",
  "a": "node_wester_ems_hub",
  "b": "node_westfalen_hub",
  "kind": "road",
  "length_px": 48,
  "base_move_points": 1.0,
  "movement_cost_multiplier": 1.0,
  "requires_port": false,
  "can_be_blockaded": false,
  "bidirectional": true,
  "province_ids": ["Wester Ems", "Westfalen"],
  "legacy_crossing_type": null
}
```

**Edge kinds:**  
`road | rail | corridor | mountain_pass | strait | ferry | ferry_or_sea_lane | sea_lane | river_crossing`

**Integration with existing authored crossings:**  
Current theatre `AUTHED_CROSSINGS` + `edge_meta` become seed edges of kinds `strait` / `ferry` / `sea_lane` with the same multipliers (today metadata-only; this model makes them real).

### 3.4 Formation operational position (serialization)

Replace sole reliance on `StrategicFormation.province_id` for *location* (province remains derived):

```json
{
  "strategic_formation_id": "sf-formation-01",
  "province_id": "Wester Ems",
  "position": {
    "mode": "at_node",
    "node_id": "node_wester_ems_hub",
    "edge_id": null,
    "progress_0_1": 0.0,
    "facing_node_id": null
  },
  "move_order": null
}
```

**In transit:**

```json
{
  "mode": "on_edge",
  "node_id": null,
  "edge_id": "edge_wester_ems__westfalen_road",
  "progress_0_1": 0.35,
  "facing_node_id": "node_westfalen_hub"
}
```

**Invariants**

- `progress_0_1` is rational in sim ticks (see timing), never free float from input.
- `province_id` is always recomputed from node/edge geometry (majority of edge segment or endpoint rule).
- Display may interpolate smoothly between tick snapshots.

### 3.5 Move order

```json
{
  "order_id": "ord-1001",
  "formation_id": "sf-formation-01",
  "path_node_ids": ["node_wester_ems_hub", "node_a", "node_westfalen_hub"],
  "path_edge_ids": ["edge_1", "edge_2"],
  "destination_site_id": "site_westfalen_town",
  "issued_tick": 120,
  "status": "active"
}
```

---

## 4. Deterministic movement timing

### Tick model

- Campaign turn subdivides into **N operational ticks** (proposal: **N = 10** per strategic turn; owner decision).
- Each edge costs `move_points = base_move_points * movement_cost_multiplier * terrain_mult`.
- Formation has `move_points_per_tick` from echelon/doctrine (default 1.0).
- Progress step:  
  `delta = move_points_per_tick / move_points`  
  quantized to 1/1000 along edge.

### Crossing costs

| Kind | Default multiplier | Port required | Blockadable |
|---|---:|---|---|
| road | 1.0 | no | no |
| rail | 0.75 | no | yes (sabotage) |
| strait | 1.25 | no | yes |
| ferry / ferry_or_sea_lane | 1.5 | yes | yes |
| sea_lane | 2.0 | yes | yes |
| mountain_pass | 1.75 | no | yes |

This **absorbs** the deferred “enforce crossing costs” work into the route model.

---

## 5. Capture, interception, ambush, retreat

### Province capture

1. Province has one or more **control sites** (`control_weight`).
2. A faction controls a site if it has a friendly formation **at the site node** (or within capture radius rule: at_node only for v1) and no enemy formation contesting.
3. Province owner flips when attacker control weight ≥ `capture_threshold` of total site weight **and** hold ticks ≥ H (proposal H=2).
4. Merely entering the province polygon / being on a road through it does **not** flip ownership.

### Interception

- Two enemy formations **intercept** if:
  - on the same node, or
  - on the same edge and `|progress_a - progress_b| ≤ intercept_window` (proposal 0.15), or
  - on adjacent edges sharing a node and both within approach window.
- Interception creates a **pending battle** with `encounter_pixel` = lerp along edge.

### Ambush / blocking

- Formation with stance `ambush` on a node/edge gains first-strike flag if enemy enters intercept window first time.
- `blockade` stance on blockadable edge prevents enemy progress unless combat clears the edge.

### Retreat

1. On loss, pick retreat node among neighbors of encounter node that are:
   - friendly-owned province or contested not enemy-held site
   - not occupied beyond stack cap
2. Prefer toward friendly supply site.
3. If none, destroy/disband per existing destruction rules.

---

## 6. GoH battle-map selection

```text
encounter_pixel + encounter_province_id
  → tactical map pool filtered by province/region tags
  → stable hash(encounter_edge_id, tick, battle_id) picks map
```

Handoff payload gains:

```json
{
  "encounter": {
    "pixel": [430, 501],
    "province_id": "Westfalen",
    "edge_id": "edge_…",
    "node_id": null,
    "site_id": null
  }
}
```

---

## 7. AI pathfinding contract

- Graph search on operational edges (A* with move_points cost).
- Goals: capture site, intercept enemy, reach friendly depot, hold choke edge.
- Must not path through blockaded enemy edges without attack intent.
- Strategic turn AI emits `move_order` objects; tick resolver advances them.

---

## 8. Input / click priority (Godot)

Front-to-back pick order:

1. Formation counter / stack badge  
2. Strategic site marker  
3. Route edge (debug / order mode)  
4. Province fill (color-ID)  

Stack panel remains the authority UI for selecting which formation/battalion issues orders.

---

## 9. Migration from province-only location

| Step | Action |
|---|---|
| M0 | Ship site+node+edge assets for EM theatre (data only) |
| M1 | On load, place each `StrategicFormation` at highest-weight site node in its `province_id`, else province centroid node |
| M2 | Keep writing `province_id` derived from position for all legacy systems (supply, objectives, UI) |
| M3 | Enable move orders on graph; province adjacency remains fallback legal set until parity tests pass |
| M4 | Retire adjacency-only movement for formations |

**Compatibility:** Saves without `position` hydrate via M1. Old saves remain loadable.

---

## 10. Example: Ireland ferry hop

```text
Formation at node_munster_hub (province Munster)
Order path: munster_hub → (ferry edge) → wales_hub
Edge kind=ferry_or_sea_lane multiplier=1.5 requires_port=true
Ticks advance progress_0_1 on ferry edge
On arrival: province_id becomes Wales; capture only if site controlled
```

Existing authored edge `province_0370 ↔ province_0367` seeds this ferry edge.

---

## 11. Staged implementation PRs (after owner approval)

| PR | Scope |
|---|---|
| **S1** | Schema + JSON assets (sites/nodes/edges) for EM; loaders; no gameplay change |
| **S2** | Formation `position` field + migration M1; UI draws at node pixel |
| **S3** | Move orders + tick advance; display interpolation |
| **S4** | Site capture rules; ownership flip |
| **S5** | Interception/ambush/retreat; encounter handoff fields |
| **S6** | AI pathfinding on graph; enforce crossing costs fully |

---

## 12. Explicit owner decisions required

Please confirm or amend:

1. **Ticks per strategic turn:** 10?  
2. **Capture:** site-node only (v1) vs radius?  
3. **Hold ticks H before province flip:** 2?  
4. **Intercept window** on edge progress: 0.15?  
5. **Stack cap** per node (formations): unlimited v1 or cap 3?  
6. **Should rail/road graphs be auto-derived from GoE geometry, fully authored, or hybrid seed+author?** Proposal: **hybrid** — auto candidates, authored allowlist (same philosophy as sea crossings).  
7. **Battalion vs formation movement authority:** formation moves as one stack v1?  
8. **Approve hybrid recommendation (option C)?**

---

## 13. Non-goals (this spike)

- Production code beyond optional throwaway prototypes  
- Building epic #65  
- AI underlay art  
- Standalone crossing-cost hack outside this model  
- Rework of color-ID province authority for ownership polygons  

---

## 14. Diagrams (textual)

```text
[Province polygon = admin]
   embeds Sites -----> bind to Nodes
   roads/rail/ferry --> Edges between Nodes

Formation position:
   (at_node) or (on_edge, progress)

Display:
   pixel = node.pixel
        or lerp(edge.a.pixel, edge.b.pixel, progress)
```

```text
Click priority:
  counter > site > edge(debug) > province
```

---

## 15. Acceptance for this spike document

- [x] A/B/C comparison + hybrid recommendation  
- [x] Schemas for site/node/edge/position/order  
- [x] Serialization + migration  
- [x] Capture / intercept / ambush / retreat sketch  
- [x] Crossing cost integration  
- [x] AI + GoH encounter hooks  
- [x] Click priority  
- [x] Staged PR plan  
- [x] Explicit owner decision list  

**Next step after owner decisions:** open S1 schema PR only.
