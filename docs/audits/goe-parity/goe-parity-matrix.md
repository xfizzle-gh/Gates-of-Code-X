# GoE parity matrix — #290

**Audit SHA:** `e830d694d68325b3764fc2c20ede3c40400ab6f0`  
**Local files:**  
- `docs/audits/goe-parity/goe-source-inventory.md`  
- `docs/audits/goe-parity/goe-parity-machine.json`  
- `docs/audits/goe-parity/current-main-latency.md`  
- `docs/audits/goe-parity/current-main-latency.json`  

**Machine JSON** carries the full column set. This document is the human reading of the same evidence.

**GoE behavioral columns are UNKNOWN unless geography/UI-only evidence is cited.** This session did **not** find live GoE research/economy/recruitment/building/save sources. See the inventory for the exact missing categories.

Primary dispositions used: `KEEP` | `KEEP_AND_POLISH` | `REWORK` | `REPLACE` | `NOT_BUILT` | `INTENTIONALLY_DIFFERENT` | `UNKNOWN`.

---

## How to read this

- **KEEP** means the current Gates foundation is the right thing to keep even if GoE details are unknown.
- **REWORK** means current code exists but the **player contract** is wrong or incomplete for the stated product (“GoE-style strategic game around Code:X/West81 + Earth3”).
- **NOT_BUILT** means the GoE-like player loop is absent; do not treat docs/epics as shipped behavior.
- **UNKNOWN** means GoE source was not available. That is not a license to invent GoE.

---

## A. Map / theatre

### Earth3 production map
| Column | Value |
|---|---|
| GoE behavior | GoE used a 517-province color-ID Europe map (MapChart HOI4 → RGB IdColor). **Not** Earth3. |
| GoE evidence | Extracts + #49; original `campaign_state.json` absent |
| Current Gates | Production `earth3_europe_mediterranean`, 3514 provinces, frozen hashes |
| Authority | `godot/assets/maps/earth3_europe_mediterranean/*`, `earth3_campaign.py` |
| Disposition | **KEEP** |
| Gap | None vs owner ruling. GoE 517-graph is legacy only |
| Target | Keep Earth3. Do not replace with GoE geography |
| Migration | Legacy `legacy_goe_europe*` remain explicit non-default |
| UX | High-count map; presentation work (#212) is separate from command latency |
| Dependencies | Authority-change skill for any geometry edit |
| Owner ruling? | No (already ruled) |
| Confidence | high |

### GoE 517-graph / color-ID extracts
| Disposition | **KEEP** as **legacy/reference only** |
|---|---|
| Current use | Not production default (`player_shell.py`: no GoE fallback) |
| Target | Keep extracts for provenance; do not rebuild the product on them |

---

## B. Campaign loop

### New Campaign / Continue / save
| GoE | UNKNOWN (docs mention supplied alpha `campaign_state.json` with `source_turn: 1`; file absent) |
| Current | `create_new_campaign` → `ww3_2028_core` on Earth3; `save_campaign` compact JSON; Continue = full launcher argv |
| Authority | `player_shell.py`, `state_io.py`, `scenario_2028_core.py` |
| Disposition | **KEEP_AND_POLISH** |
| Gap | Continue is a heavy relaunch (~3 s Python load here; Godot UNKNOWN). New campaign boot ~10 s on this host |
| Target | Instant Continue into the same process; keep fail-closed save |
| Tests | `test_production_new_campaign_2028.py`, P6 handoff tests |
| Production? | yes |

### Turn / day cadence
| GoE | UNKNOWN |
| Current | One strategic turn = one week (`#217` / campaign rules). `end_player_round` runs human seat + all AI seats |
| Disposition | **INTENTIONALLY_DIFFERENT** until GoE cadence is evidenced |
| Owner ruling? | yes — confirm week-turn vs GoE day/turn |

### Contact / battle / Auto-Resolve
| GoE tactical waves | UNKNOWN; #185 forbids inferring from strategic UI |
| Current | Operational contacts create `pending_battle`; Auto-Resolve uses roster×supply×condition; Fight = GoH handoff |
| Authority | `campaign.py`, `operational_contact.py`, `frontend_commands.py` |
| Disposition | Auto-Resolve **KEEP**. Handoff **KEEP**. Wave fidelity **NOT_BUILT** (parked with P11/#185) |
| Production? | yes (Auto-Resolve). Owner manual P10 acceptance incomplete |

### Objectives / victory
| Current | P9 pack `ww3_2028_core.json` war aims + national hubs; Expanded victory **fail-closed** |
| Disposition | **KEEP_AND_POLISH** (Core). Expanded victory **NOT_BUILT** |
| Gap | Not proven against GoE victory |

---

## C. Research (owner-heavy)

### Player loop that exists today (Gates, not GoE)

1. Open Manage Forces (backend `actor_force_panel`, **not** on warm daemon → ~2.6 s load here).
2. Research tab lists actor-scoped nodes from compiled Code:X/`goc_*` trees, costs `max(50, source*50)`.
3. Buy spends **formation economy actor** treasury/research (`usa`/`deu`/`pol`), while the selected Core seat is **`nato`**.
4. This session: `research` failed with `Research key is not scoped to actor nato: actor:usa:…` after **5.2 s load**.

Legacy `economy.py` builds a **category ladder** (Core Forces → recon/vehicles/IFV/tanks/artillery/AD + doctrine nodes). That ladder is **unused** on production Core once `actor_content_runtime` is installed.

| Column | Value |
|---|---|
| GoE tree / prereqs / currency / cadence / national diffs / AI selection | **UNKNOWN** — no GoE research files |
| Current authority | `actor_economy.py`, `faction_wiring_research.py`, `unit_research_goc_*.set`, force panel |
| Disposition | **REWORK** (do not KEEP just because code exists) |
| Gap | Not GoE; Core command/economy identity split; fixture/live trees are Code:X-derived; AI buys cheapest node if `cost <= resources//2` |
| Target | One visible national research graph per playable actor, paid in the same treasury the HUD shows, with unlocks that gate purchase. Import GoE structure **only after** source is mounted |
| Reuse | Keep actor-scoped runtime + compiler; replace the **player-facing tree contract** when GoE source exists |
| UX | Multi-second one-shot; not on daemon |
| Owner ruling? | **yes** — supply GoE research source before any “parity tree” PR |
| Confidence | high for Gates; none for GoE |

**How much of GoE research can be reused cleanly?**  
**Unknown until files exist.** Code:X `unit_research_*.set` **can** be scanned today (`SourceResearchIndex`). That is **Code:X/West81**, not GoE. Do not treat it as GoE parity.

---

## D. Economy

### Player loop today

- HUD can show acting-actor treasury.
- Province **income is structurally inert** on Earth3: `resource_yield == 0` everywhere; `owner_actor_id` only on the 11 P2 footprint provinces; Core remaps tactical `owner` to nato/ukr/rusa/prc **without** remapping income actors.
- Maintenance still charges from rosters at round settlement.
- Starting treasuries: Core overlay `nato/ukr/rusa/prc` 600/600/750/600; Earth3 national seats usa/deu/pol/ukr/rus 600/450/450/600/750. Faction treasuries in `factions.json` are **0**.
- Purchase/repair costs are **synthetic** (category + manpower + vehicles), documented as not native Code:X/GoE prices.

| Disposition | **REWORK** |
|---|---|
| GoE | UNKNOWN |
| Target | A visible earn/spend loop: income from controlled territory (GoE rule TBD), upkeep, purchase, repair, all on one actor treasury |
| #65 | Full civic/resource chains are **not** required to make this loop real |
| Owner ruling? | yes — income formula once GoE source exists; until then, a **minimal** Earth3 yield/ownership map is still needed or the loop stays fake |
| Confidence | high for “income is inert”; none for GoE numbers |

**How much of GoE economy can be reused cleanly?**  
**Unknown.** Actor-scoped treasuries and fail-closed commands are reusable. Numbers, province contribution, stockpiles: no GoE bytes.

---

## E. Recruitment / force development

| Current loop | Research unlock → `recruit` into actor reinforcement pool → `assign` fills authorized then expands |
| GoE | UNKNOWN (UI-only: purchase into a battalion-looking roster) |
| Disposition | **REWORK** |
| Gap | Loop is implemented but **fails on Core NATO** (usa research/units vs nato command actor). Merge/split/rename **NOT_BUILT** on main (`split_battalion` / `merge_battalion` absent). #52 Slices B/C PRs are historical, not this SHA |
| AI | Buys one unlocked unit and assigns to weakest formation (`actor_ai_economy.py`) |
| Target | Same three verbs, one treasury, visible pool, battalion capacity from GoE once sourced |
| Production? | Wired; identity-broken on Core overlay |

---

## F. Battalions / formations

| Layer | Current | GoE (proven) |
|---|---|---|
| Map counter | `StrategicFormation` | UI-only: army/stack counters |
| Tactical persistence | `Battalion` roster | UI-only: unit cards, strength, supply upkeep |
| Template | Earth3 `formations.json` TOE (infantry/tank/artillery counts) | UNKNOWN exact card quantities |
| Multi-battalion stacks | Schema/UI work exists; opening content is 1 BN per SF | UNKNOWN |
| Merge/split/transfer | **NOT_BUILT** on this SHA | UNKNOWN |

| Disposition | **KEEP_AND_POLISH** the three-layer identity (SF / BN / roster). **REWORK** presentation vs GoE information hierarchy (#52). **NOT_BUILT** merge/split |
|---|---|
| Do not claim GoE tactical wave behavior from cards (#185) |

**How different is our battalion model?**  
Strategically: we already have persistent battalion rosters + formation containers + authorized vs current counts + condition. That is a **keepable** foundation. We do **not** know GoE’s capacity, card quantities, or whether “battalion” on their map is the same object. Do not flatten to one aggregate roster (designer amendment on #52 still stands unless re-ruled).

---

## G. Province development / buildings vs #65

| Current production | Four infrastructure types (`fortification`, `supply_hub`, `recruitment_center`, `command_post`) in `strategic.py`; **one** P10 site upgrade: Forward Depot (400, 2 turns, repair half, +10 supply restore that **does not apply** while province BFS supply is disabled) |
| #65 | Huge civic/industry/settlement epic from collaborator docs — **not found as GoE source** |
| GoE buildings | **UNKNOWN** |
| Disposition | Forward Depot **KEEP** as a bounded military verb. Generic construct **KEEP_AND_POLISH** only if it stays small. Full #65 catalog **NOT_BUILT** and **should not proceed as the plan** until GoE buildings are evidenced |
| #65 still correct? | **No, not as the next implementation plan.** Preserve as post-parity expansion notes. See Q9 |

---

## H. Supply / readiness

| Dual authority | Province BFS `supply.py` **disabled** on Earth3 (`none_until_p3` marker persists). Operational S8 `operational_supply.py` **active** (authored hubs) |
| Repair gates | battalion.supply ≥ 50 and not encircled — may disagree with operational cut-off UI |
| GoE | UNKNOWN |
| Disposition | **REWORK** (unify player-facing supply/readiness). Do not expand a second city-builder logistics layer first |
| Forward Depot +10 restore | Ineffective until province restore runs |

---

## I. AI

| Current | Actor economy (research/repair/recruit) → construct → Forward Depot → operational movement. Deterministic cheapest-research / weakest-formation |
| GoE | UNKNOWN |
| Disposition | **KEEP** the “AI uses the same verbs” rule. **REWORK** the policy once GoE/source priorities exist. Do not build a second AI |
| Production? | yes on Earth3 graph campaigns |

---

## J. UX / information architecture (Gates measured; GoE UI-only)

| Gesture | Gates today | GoE |
|---|---|---|
| Left click | Select province / formation (local) | UNKNOWN |
| Right click | Issue+commit move if formation selected | UNKNOWN |
| Force panel | Extra click; backend round-trip | UNKNOWN |
| Research/Recruit/Assign/Repair | Panel tabs → mutating ops | UNKNOWN |
| End Turn | Button/E → `end_player_round` | UNKNOWN |
| Battle | Modal: Auto-Resolve / Fight | UNKNOWN |
| Always visible | Ownership, counters, turn, treasury (if acting_actor) | UNKNOWN |
| Hidden in panels | Research list, offers, repair eligibility, exact supply query | UI-only: GoE showed cards/upkeep on army UI (#52/#185) |

Disposition: **KEEP_AND_POLISH** interaction model (select vs order is already the right split). **REWORK** panel latency and Core identity. Do **not** visual-clone GoE.

---

## K. Tactical bridge / P11

| Piece | Disposition |
|---|---|
| Strategic↔GoH save/status/`CampaignSquads` bridge | **KEEP** |
| Custom tactical factions (#201) | **KEEP** as later feasibility; **NOT_BUILT** in production Core |
| Battalion-faithful waves (#185) | **NOT_BUILT**; observation still required; **do not start** |
| Morale (#273/#274) | **NOT_BUILT** / parked. **Do not resume P11** until owner accepts this matrix |

---

## L. Content audit (#46)

Current main has scanners (`CodeXCatalogScanner`, `SourceUnitIndex`, `SourceResearchIndex`, `gates-of-codex-factions`, cost-evidence, static-matrix) but **no** `audit-unit-pools` CLI and **no** `docs/audits/unit-pools.json`.

| Disposition | Tooling: **KEEP** as foundation. #46 product: **NOT_BUILT** |
|---|---|
| Do not reopen #54 | Rebuild later from this SHA if owner authorizes a **small audit-tool PR** |
| Workshop stack | Required to generate the three artifacts; not mounted here |

---

## Disposition rollup (Gates systems)

| Disposition | Systems |
|---|---|
| **KEEP** | Earth3 map; actor/national identity **architecture**; fail-closed loaders; compact save; Auto-Resolve; GoH bridge; Code:X catalog/materialization compiler; operational graph/movement; P9 Core victory pack; persistent-backend **idea**; Forward Depot as a **small** military verb |
| **KEEP_AND_POLISH** | Godot shell; battalion/SF presentation; Continue/New Campaign UX; AI “same verbs”; construct (tiny set) |
| **REWORK** | Research player contract; economy/income; Core nato-vs-usa command/treasury; recruitment loop identity; supply dual authority; command latency class-2 (force/repair/refresh); AI research policy |
| **REPLACE** | None as a whole-repo rewrite. Do **not** replace Earth3, save schema, or the Godot+Python split |
| **NOT_BUILT** | GoE-parity research/economy (source missing); #65 city-builder; merge/split; #46 unit-pool artifacts; Expanded victory; P11 waves/morale |
| **INTENTIONALLY_DIFFERENT** | Earth3 vs GoE 517 map; national actors vs four GoH sides; Auto-Resolve-only campaign; modern Code:X/West81 content instead of copying GoE assets |
| **UNKNOWN** | All detailed GoE loops; owner Windows input→visible |

---

## Recommended build order (audit-determined, not the template list)

The template order (responsiveness → GoE research → economy → …) is **wrong until GoE files exist**, and **wrong if identity+latency stay broken**.

### 0. Owner supplies GoE source (blocks true research/economy parity)

Without it, implement **playable Gates loop**, not fake GoE.

### 1. Make the existing verbs feel instant (hard gate)

Warm-lease + runtime-patch (or skip snapshot) for: Force panel, Research, Recruit, Assign, Repair. Stop force ops from killing the move/End Turn lease. Measure **owner Windows Godot input→visible**. Target: select/panel open effectively instant; spend/move under comfortable human “click-response” (backend mutate is already 5–30 ms).

### 2. Make Core NATO/Poland actually spend as one player

Resolve `nato` command actor vs `usa`/`deu`/`pol` economy/research/pools. Until this is ruled, the vertical slice **cannot** research→recruit→assign.

### 3. Make earn/spend real with **minimal** Earth3 income

Do not wait for #65. Either author yields/ownership for the Core overlay or explicitly rule “starting treasury only” for the first slice. Maintenance already exists.

### 4. Keep current research trees as a **placeholder**

Do not author a giant new tree. Do not import GoE until source is in hand. One meaningful unlock on the **existing** actor graph is enough for the slice.

### 5. Battalion UX polish (#52 information hierarchy) only after 1–4

Cards/stack tabs on data that already exists. No merge/split yet unless GoE source proves it is load-bearing.

### 6. GoE-parity research/economy/buildings **after** source inventory is complete

Then revisit #76 trees vs GoE. Then decide whether any #65 chain is actually GoE.

### 7. Supply/readiness unification

### 8. AI policy parity (same verbs, better choices)

### 9. Campaign length/objectives polish

### 10. P11 / #185 / #273 **later**, after the strategic game is recognizable

---

## First vertical slice (production architecture, not a toy)

**Seat:** Core `ww3_2028_core`, human NATO commanding Polish/US/German formations on Earth3 (or a single national seat if owner re-rules identity).

```text
New Campaign (NATO)
→ treasury visible and is the treasury that will be spent
→ open Force Management (instant)
→ inspect one research node and buy it
→ recruit one unlocked unit into the pool
→ assign it into sf_pol_vilnius or sf_usa_tallinn
→ right-click one legal hop and see the committed order immediately
→ End Turn → AI uses the same verbs
→ a contact appears
→ Auto-Resolve
→ roster/condition/treasury change is visible
→ next turn can research or replenish again
→ Continue restores that state
```

**Out of slice:** city-builder, GoE tree import, tactical waves, morale, custom GoH factions, map replacement.

**Exit:** owner can play that loop without thinking “this is an engineering framework.”

---

## The 15 decision questions

### 1. Are we better off keeping the current repo foundation?
**Yes.** Earth3, actor identity, save/load, Auto-Resolve, Godot shell, and the GoH bridge are real, tested, and match the owner’s “do not restart the codebase” ruling. A rewrite would throw away the only production map and the fail-closed authority model.

### 2. Which current systems are clearly worth keeping?
Earth3 geometry/stable IDs; strategic actors; compact save + validation; operational movement graph; Auto-Resolve; tactical handoff/import; catalog compiler/materialization; persistent-backend **pattern**; Godot as presentation client.

### 3. Which current systems are overengineered?
Dual economy (legacy faction `economy.py` vs actor runtime); dual supply (disabled province BFS + S8); Core overlay rewriting usa/rus keys while formations stay national; #65-scale building schema relative to the actual four-building + one-depot production; command-cycle that still full-snapshots Repair/Refresh; force ops deliberately left off the warm path.

### 4. Which current systems conflict with GoE?
**Unknown in detail** (no GoE sim source). **Known product conflicts:** we did not import GoE research/economy/buildings; we invented category/doctrine research and synthetic prices; we use Earth3 not GoE 517; Core NATO is a coalition overlay sitting on national formations. UI-only: our force panel is a separate heavy screen vs GoE’s always-on army cards (#52/#185).

### 5. Which major GoE systems are still absent?
Cannot list GoE systems as facts. **Absent vs the intended loop:** a recognizable GoE-like research tree, province-driven income, building/settlement progression, and proven battalion-card economics. Those are **NOT_BUILT** as GoE-parity, regardless of Gates substitutes.

### 6. How much of GoE research can be reused/reproduced cleanly?
**None until source is mounted.** Code:X research `.set` files **can** be reproduced via existing scanners; that is the wrong game unless the owner rules Code:X trees **are** the strategic tree.

### 7. How much of GoE economy can be reused/reproduced cleanly?
**None until source is mounted.** The **plumbing** (actor treasury, maintenance, purchase, repair, round settlement) is reusable.

### 8. How different is our battalion model?
Persistent SF→BN→roster is a solid original model. Opening content is 1:1 SF:BN. No merge/split. Condition/supply fields exist. GoE card quantities/upkeep **unproven**. Do not assume tactical waves from the strategic UI.

### 9. Is #65 still the correct building/economy plan after seeing GoE?
**No as the next plan.** We did **not** see GoE buildings. #65 is a collaborator catalog, already parked post-v1 under #217. Implementing it now would again “build custom 4X before GoE parity.” Keep the typed-effect **ideas**; do not start Phase 0 transcription as mainline.

### 10. Is #76 still the correct research/content plan?
**Partially.** Actor-scoped pools, explicit content modes, and “don’t invent GoH sides” remain correct. The delivery plan’s “author trees from #46” is still needed for **Code:X/West81** coverage, but **must be compared to GoE source** before treating those trees as the player-facing progression. #46 artifacts are missing; #54 stays closed. #201 remains a later tactical-identity spike, not a reason to delay the strategic loop.

### 11. Why does the UI still feel slow?
Because #266 measured the **wrong acceptance surface** (warm Python move/End Turn/Auto-Resolve) and **did not** measure Godot input→visible. Everyday verbs still **cold-load ~2.6–5.9 s**, **kill the warm lease**, and **Repair/Refresh publish a ~6.5 MB snapshot (~47 s on this VM)**. Core research/recruit **fail** after that wait. Busy-banner UX makes 1 s feel like a freeze. See `current-main-latency.md`.

### 12. What can be made effectively instant?
Select (already local). Force panel (~27 ms if leased). Research/recruit/assign/repair **mutate** (5–30 ms) if snapshot is patched and identity works. Move remaining cost is **save validate ~0.6 s** + UNKNOWN Godot apply. End Turn remaining cost is **AI mutate**. Snapshot republish should never be on the click path.

### 13. What is the shortest route to something that FEELS like a game?
Instant verbs + one treasury identity + real (even tiny) earn/spend + one unlock → recruit → assign → move → End Turn → Auto-Resolve on **production** Earth3 Core. Not a new map, not #65, not P11.

### 14. What should remain intentionally better/different than GoE?
Earth3 readability/scale; national actors instead of four anonymous sides; Auto-Resolve-complete campaigns; fail-closed authority/saves; modern Code:X/West81 content; Godot UX that is **clearer** than GoE’s overflow cards without cloning them.

### 15. What should happen to P11 after the reset?
**Stay parked.** #273/#274 unmerged. #185 remains research/observation. #201 remains a later spike. Do not spend the next implementation capacity on morale, waves, or custom GoH factions. Resume P11 only after the owner accepts a strategic vertical slice that feels like the intended game.

---

## Unresolved owner decisions

1. Mount or copy **GoE source** (see inventory §4). Without it, GoE research/economy/buildings stay UNKNOWN.
2. Core **command actor vs economy actor**: should NATO spend `nato` treasury or the selected national formation’s (`usa`/`pol`/`deu`)? Current code mixes both and research/recruit fail.
3. Confirm **week-turn** vs whatever GoE used.
4. **Income before GoE source:** author minimal Earth3 yields, or explicitly play on starting treasuries only?
5. Are **Code:X `unit_research_*.set` trees** acceptable as the v1 strategic research graph, or must they wait for GoE?
6. Is **#65** post-parity expansion (recommended) or still a hidden GoE clone the owner believes is source-accurate? If the latter, produce the GoE files.
7. Authorize a **small #46 audit-tool PR** later? (Recommended: yes, after this review; not opened now.)
8. Authorize **commit of these audit files**? (Not pushed; no PR.)
9. Owner-Windows **Godot input→visible** capture for the same 11 actions.
10. P11 stay parked until slice exit (recommended).

---

## Stop

No implementation PR. No merge. #274/#208/#165/#158/#154/#63/#54 not reopened. #273 Phase B/C not started. #185 production not started. Earth3 not replaced.

**GitHub issue comments:** this environment’s token returns **403** on `POST .../issues/290/comments` (MCP and `gh api`). The owner should paste a short START + this summary onto #290, or grant issue-comment permission.
