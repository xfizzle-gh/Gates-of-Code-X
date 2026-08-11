# NORESUS strategic campaign reference study

Status: **static reference study complete; no Gates campaign schema changes made**

Reference: Steam Workshop item `3180617465`, **NORESUS - Strategic Map**, package description `Conquest\Enhanced Campaign 1.9.3.4`.

Related Gates issues: #45, #52, #66, #166, #176, #185, #201, #209.

## Executive conclusion

NORESUS is a strong proof that the broad Gates of Code:X product direction is viable:

- an external strategic campaign can own persistent state;
- it can generate a Gates of Hell Dynamic Conquest battle;
- GoH can be used as the tactical resolution engine;
- tactical losses can be brought back into persistent strategic formations;
- strategic movement, economy, research, supply, fog/intelligence, and unit organization can all live outside GoH.

However, NORESUS does **not** implement the division hierarchy proposed in the current Shutkar1992 discussion. The persistent on-map maneuver/combat object discovered in its save schema and UI is a **battalion**. The application supports battalion composition down into platoon/company-like structure and can request support from nearby battalions, but the supplied snapshot exposes no persistent division/regiment container that owns multiple maneuver battalions.

That distinction is important because Gates of Code:X already has a data model closer to the desired end state than NORESUS does. Current Gates code has:

```text
StrategicFormation
  echelon = battalion | regiment | brigade | division
  battalion_ids = [...]

Battalion
  roster
  authorized_roster
  supply
  condition
  experience
```

The missing product layer is primarily:

```text
strategic formation
  -> select subordinate battalions / support for an operation
  -> create an explicit battle commitment
  -> materialize only the committed tactical slice
  -> preserve battalion identity through tactical waves and survivor import
```

The recommended architecture is therefore **not to port NORESUS**. Keep the Gates engine, Earth3/operational graph, actor model, deterministic persistence, and guarded handoff. Use NORESUS as evidence and design input for battalion organization, operational support, calendar/economy ideas, and tactical AI wave control.

A second major finding directly explains the community complaint that tactical forces arrive in tiny disconnected packets. The supplied NORESUS `conquest.lua` configures the AI to purchase/deploy **exactly 3 units per wave**, with 30 seconds between purchases and 75 to 105 seconds between waves in the inspected configuration. The included AI scripts also select different AI strategy templates from the battalion type. This means the observed three-unit trickle is not evidence of an unavoidable GEM engine limit. In this snapshot it is, at least in part, an authored NORESUS tactical-AI policy.

## Evidence boundary and method

This report is a clean-room behavioral and data-architecture study. It does not copy third-party implementation into Gates of Code:X.

Evidence used:

1. Directly readable reference data and configuration such as `mod.info`, `datamap_reset.sql`, `units_prod.txt`, HTML tech-tree exports, Lua tactical scripts, and text configuration.
2. SQLite schemas from the runtime databases packaged inside the nested NORESUS archive.
3. Static .NET assembly metadata and human-readable strings from `noresus-conquest.exe` to identify named workflows and UI behavior. These are used only as behavioral clues, not as copied implementation.
4. Gates of Code:X current source and GitHub design issues.

This study did **not** execute the Windows NORESUS application or a live Gates of Hell battle in this environment. Statements about the exact live ordering of executable-internal operations remain static-analysis conclusions until reproduced on Windows. The included Lua/config/database findings are direct source artifacts from the supplied package.

## Reference identity and reproducibility

Supplied archive:

- filename: `3180617465.zip`
- bytes: `239,133,688`
- SHA-256: `c58a1da76c65b682236d868f6790dcbf6ef9707365d4dcfc883ab59111034659`
- non-directory files: `10,161`
- installed name: `NORESUS - Strategic Map`
- package description: `Conquest\Enhanced Campaign 1.9.3.4`

Dominant file types:

| Type | Count |
|---|---:|
| `.set` | 5,218 |
| `.png` | 3,315 |
| `.ebm` | 271 |
| `.jpg` | 230 |
| `.tga` | 225 |
| `.ply` | 214 |
| `.info` | 204 |
| `.mi` | 73 |
| `.lua` | 5 |
| `.sql` | 1 |

The nested file named `NORESUS CONQUEST ENHANCED.rar` is ZIP-compatible in the supplied snapshot. It contains the external application, SQLite runtime, config, and README. Important hashes are captured by `tools/probe_noresus_reference.py` and the derived metadata report rather than committing the third-party files.

## 1. Overall runtime architecture

The supplied README explicitly describes a two-application loop:

```text
NORESUS strategic application
  -> player makes strategic decisions on Europe map
  -> attack/defense operation begins
  -> NORESUS prepares a GoH Conquest battle/save
  -> NORESUS launches GoH
  -> player loads "noresus battle"
  -> battle finishes
  -> NORESUS returns to the Europe map
  -> strategic state is updated
```

NORESUS also automatically activates the mod set it expects. That proves an external strategic owner can drive the GoH tactical loop, but Gates should **not** adopt the automatic-mod-mutation behavior. Gates' exact-stack validation and fail-closed export are safer and more reproducible.

### Gates comparison

Gates already has the same fundamental bridge, but with stronger integrity controls:

- a pending battle is explicit campaign state;
- export binds battle ID, campaign path, tactical save path, map, catalog signature, resource stack, and campaign hash;
- import rejects a manifest for another campaign/save/battle;
- import verifies the mod-stack signature has not changed;
- survivors are parsed from the post-battle `campaign.scn` and applied to the persistent battalion;
- operational retreat/finalization is performed by the campaign engine after verified import.

Recommendation: **preserve the Gates handoff architecture**. NORESUS validates the product concept but does not justify replacing the current manifest/verification boundary.

## 2. Strategic map and geographic model

`datamap_reset.sql` defines **639 strategic regions**.

Observed region authority includes:

- stable integer region ID;
- display name;
- nation;
- adjacent-region list;
- faction/alignment integer;
- capital flag;
- front/war-theatre integer;
- surrender date field;
- warehouse/resources/industry fields;
- five map coordinates;
- depot/battalion/map fields.

Reference statistics:

- 639 regions;
- 29 capital regions;
- mean graph degree about 5.02;
- median degree 5;
- maximum degree 10;
- Reykjavik is the only region encoded with no nonzero neighbor in the supplied reset data;
- five map points per region, 3,195 total sample coordinates;
- coordinate extent approximately x 36..4983, y 61..4518.

The largest national region counts are Soviet Union 172, France 85, Italy 50, Germany 45, England 43, Poland 29, and Spain 27. The map is therefore a coarse strategic region graph rather than a fine operational movement mesh.

`noresus-project.db` adds a `regionborder` table with 639 rows, providing region boundary geometry/text plus front assignment.

### Gates comparison

Gates has moved beyond this design:

- Earth3 is planned as 3,514 stable provinces;
- provinces remain administrative ownership/economy authority;
- operational movement uses separately authored nodes/edges;
- formations can occupy authoritative node positions or edge progress rather than teleporting region-to-region;
- only reviewed operational corridors are authoritative.

NORESUS validates the value of a Europe-scale overmap but its 639-region direct-adjacency movement model should **not** replace Earth3 or the operational graph.

## 3. Persistent state stores

The nested runtime contains three SQLite databases.

### `noresus-project.db`

Tables:

- `regionborder`: 639 region-boundary records;
- `compagnie`: unit/company catalog table, empty in the packaged baseline;
- `truppe`: troop/unit catalog table, empty in the packaged baseline;
- `parametri1`: runtime parameters, including movement-speed-like values.

The empty unit tables strongly suggest part of the catalog is populated/scanned during runtime rather than fully frozen in the baseline database.

### `noresus-save.db`

Tables:

- `battaglioni`: persistent battalions;
- `datamap`: mutable strategic map state;
- `parametri2`: campaign/faction/economy resource totals and selected campaign settings;
- `player_career`: player rank, score, battles, kills, medals.

The `battaglioni` table is the most important formation evidence. It stores, among other fields:

- ID;
- cost;
- faction;
- name;
- region;
- serialized content fields;
- front;
- state;
- origin;
- battalion type;
- description;
- slot;
- minimum stage/time gate;
- visibility;
- nation;
- region code;
- action/status fields;
- battalion statistics;
- resupply cost;
- subtype.

No division ID, regiment ID, parent-formation ID, or parent-echelon table was found in the packaged save schema.

### `noresus-anag.db`

The `anagrafica` table tracks personnel/unit identity beneath a battalion. Fields include:

- battalion ID;
- state/faction/period;
- battalion type;
- platoon index/type;
- squad/unit type;
- individual name/index;
- battles;
- rank;
- total and current-battle infantry/vehicle kills;
- score;
- veterancy;
- tag.

This is materially more granular personnel-career persistence than Gates currently needs for the division model. It demonstrates that persistent tactical identity can be tracked below the strategic battalion if desired, but it is not necessary to make division/battalion operations work.

## 4. Formation hierarchy: what NORESUS actually models

The strongest conclusion of the study is:

```text
NORESUS on-map maneuver object = Battalion
```

Direct evidence:

- the save database's persistent force table is `battaglioni`;
- the UI exposes battalion creation, movement, deployment, supply, attack, disbanding, and map selection;
- battalion type is a first-class field;
- detailed personnel records point back to a battalion ID;
- strategic-map strings refer to selecting/moving battalions;
- no persistent division/regiment ownership table was found.

NORESUS organizes **inside** the battalion through platoon/company concepts. It also allows support to be requested from nearby battalions. That is not the same as a persistent division owning subordinate battalions.

### Battalion types discovered

The unit tech-tree UI and tactical-AI mapping expose seven principal battalion types:

1. Infantry
2. Motorized
3. Mechanized
4. Light Tank
5. Medium Tank
6. Heavy Tank
7. Artillery

Paratrooper capability is separately represented in configuration/content and can be derived/trained from infantry-oriented content.

### HQ organization behavior

Static UI evidence shows that the HQ supports:

- creating new battalions by type;
- editing battalion names;
- recruiting units;
- assigning/rearranging units into platoons;
- battalion cost and construction/deployment state;
- reserve versus regular units;
- limits on repeated unit types;
- resupply/reinforcement/repair workflow;
- map access to the selected battalion.

This is the closest NORESUS analogue to the requested “division designer,” but it is actually a **battalion designer/manager**.

## 5. Nearby battalion support is real and relevant

The external application exposes a pre-battle/support workflow in which the player can request support from nearby battalions. Static UI evidence distinguishes concepts such as:

- direct support;
- suppression support;
- off-map support;
- HQ authorization based on the supporting battalion's state/readiness.

This is highly relevant to Gates because it shows a useful separation between:

```text
main maneuver battalion
supporting nearby battalion
support mode for the operation
```

But it still does not prove a division-level parent formation.

### Recommended Gates interpretation

Do not model all support as simply “another battalion fully spawned into the battle.” Add an operation-commitment concept that can classify each subordinate element as, for example:

```text
maneuver
reserve
fire_support
air_defense_support
engineering_support
recon_support
logistics_support
```

Then the tactical bridge can decide whether that commitment means persistent spawned objects, delayed wave, off-map support, or strategic-only modifier.

## 6. Time model

NORESUS is **not turn-based** in the same way Gates currently is.

Direct configuration/UI evidence indicates:

- AI movement interval defaults to 1.0 to 3.0 virtual days;
- AI attack interval defaults to 1.0 to 3.0 virtual days;
- custom deployment behavior references 12 to 36 virtual hours;
- movement records origin/destination, distance, fuel use, arrival date, and supply-until date;
- monthly credit/troop/production concepts exist;
- campaign content uses real calendar dates and historical availability stages;
- the strategic simulation can be paused.

### Gates comparison

Gates #66 currently locks:

```text
10 deterministic operational ticks = 1 strategic turn
```

This deterministic model is more testable and save-safe than a continuous wall-clock-like scheduler.

### Recommendation on Shutkar's “one week per turn” proposal

Adopt the **calendar meaning**, not NORESUS's continuous scheduler:

```text
1 strategic turn = 7 campaign days
10 operational ticks = deterministic subdivisions of that week
```

Store campaign time as deterministic integer values. UI can display day/date/week without making real-time clock progression authoritative. That satisfies the desired operational cadence while preserving the existing engine.

## 7. Economy, production, research, and logistics

NORESUS contains a substantial campaign economy.

Observed resource categories include:

- credits/money;
- manpower/troops;
- warehouses;
- research/labs;
- industry/factories;
- oil;
- aluminum;
- steel;
- tungsten;
- chromium;
- rubber;
- equipment;
- off-map support facilities.

The tech-tree exports contain 746 six-field availability rows in `units_prod.txt` across Germany, USSR, USA, Finland, Hungary, Britain, Italy, France, and Poland. Separate HTML outputs distinguish GoH availability from historical availability and CE/N&V content variants.

Supply behavior is also persistent:

- battalions have resupply cost/state;
- surrounded battalions cannot be resupplied;
- attrition is configured for surrounded formations;
- fuel/ammunition/equipment are distributed for battle;
- replacement and resupply are distinct campaign actions;
- strategic supply lines can be visualized.

### Gates comparison

Gates already has:

- formation/battalion supply;
- operational supply route authority, cutoff/grace state, and attrition;
- faction/actor economy;
- recruitment/reinforcement pools;
- research;
- repair/maintenance;
- infrastructure and supply hubs.

Recommendation: do not replace the Gates economy with NORESUS's resource schema. Consider its **HQ readiness, supply authorization, and industrial gating** as tuning/design references only.

## 8. Fog of war and intelligence

NORESUS configuration enables battalion fog. Static UI evidence includes intelligence/recon-style actions that can reveal regional wealth, resources, production, and garrison information.

### Gates comparison

Gates S11 is building a more explicit observation-authority model with persisted knowledge tiers and recon sources. Current `KnowledgeRecord` supports contact, identified, assessed, and fully observed states plus last-known position/strength/condition/supply bands.

Recommendation: retain the Gates observation model. NORESUS supports the gameplay value of strategic intelligence but does not provide a reason to simplify the current typed knowledge system.

## 9. Tactical handoff and battle lifecycle

Direct README and file evidence show a generated `NORESUS Battle.sav` workflow plus dynamic `campaign.scn` manipulation. Static executable metadata exposes named paths/workflows for creating/updating the campaign scenario, pre-battle temporary saves, post-battle processing, and storing battalion data after battle.

The tactical package includes custom Dynamic Conquest mission/script content and map staging resources.

Observable lifecycle:

```text
strategic attack/defense selected
  -> select/prepare tactical map
  -> prepare battle save/scenario
  -> start GoH
  -> battle result/save rewritten by GoH
  -> post-battle processing
  -> update battalion/map/campaign state
```

Failure-policy strings indicate at least these intended distinctions:

- a detected GoH crash cancels the operation with no strategic-map change;
- restart/abandon behavior may be treated as a loss/cowardice outcome;
- returning from a valid completed battle updates the strategic campaign.

### Gates comparison

Gates is stricter and should stay stricter:

- exact battle manifest;
- exact campaign/save binding;
- exact catalog/stack signature;
- verify completed-battle counter before import;
- survivor parsing by pending battle participants;
- exact-once strategic finalization;
- deterministic retreat/position resolution.

The open #166 stale-template dependency defect must still be fixed, but the architecture itself is superior to simply auto-driving the GoH install/profile state.

## 10. Tactical AI and the three-unit wave finding

This is the most actionable technical discovery for #185.

The supplied NORESUS `resource/script/multiplayer/modes/conquest.lua` directly configures:

| Parameter | Inspected value |
|---|---:|
| units per wave | 3..3 |
| time between unit purchases in active wave | 30 s |
| time between waves | 75..105 s |
| first attacker purchase | 0 s |
| first defender purchase | 5..7 s |
| wave counter | enabled |

This closely matches Shutkar1992's complaint about small groups repeatedly feeding into a battle.

The mod also includes AI logic that can force category counts and AI strategy templates. `bot.strategies.lua` maps the NORESUS battalion type to a strategy-template family:

| Battalion type | Strategy index family in supplied script |
|---|---|
| INF | 1, 3, 6 |
| MOT | 1, 6 |
| MEC | 6 |
| LT | 5 |
| MT | 5 |
| HT | 4, 5 |
| ART | 2 |

The exact semantic meaning of each template must be evaluated from behavior rather than copied into Gates, but this proves the important seam: **the tactical AI can be informed by strategic battalion type**.

### Consequence for #185

#185 previously treated the “three-unit trickle” as an open attribution question. The supplied NORESUS source artifact narrows it substantially:

- it is not merely an unexplained native GoH behavior;
- this NORESUS build explicitly authors three-unit waves;
- the scripts already have a battalion-type-to-AI-strategy seam;
- the hard problem is no longer “can any wave control exist?”;
- the hard problem is “can Gates replace the fixed small purchase waves with exact committed battalion waves while preserving identity, performance, and survivor import under the modern Code:X stack?”

Live testing is still required because Code:X AI Overhaul and the current GoH version may alter the effective behavior.

## 11. Tactical force fidelity

NORESUS has two distinct tactical force ideas:

1. Persistent battalion composition managed in the external campaign.
2. Tactical AI purchases/waves controlled by Lua purchase lists and strategy logic.

Those are related but not identical. A battalion's strategic composition does not by itself guarantee that the AI fields all of it coherently at once. The wave code shows why.

This supports the terminology already proposed in #185:

```text
strategic battalion roster
committed tactical slice
wave
support
native AI purchase
survivor ownership
formation abstraction
```

Recommendation: Gates should make these separate first-class concepts rather than pretending every strategic quantity automatically equals a simultaneous tactical object.

## 12. Post-battle persistence

NORESUS exposes persistent post-battle concepts at several levels:

- battalion content and state;
- casualties/survival;
- resupply/repair;
- personnel/unit battle count;
- rank;
- infantry/vehicle kills;
- score/honor;
- veterancy;
- player career/medals.

Static method names indicate explicit post-battle battalion storage and campaign-scenario reloading/update workflows.

### Gates comparison

Gates currently persists battalion roster entries as quantities and imports survivor rosters by battalion/stage. It also adjusts battalion condition and finalizes formation positions/retreat after the result.

This is enough for the proposed division layer. Per-soldier career persistence is an optional future feature, not a dependency.

## 13. Co-op and snapshot synchronization

The executable exposes host/guest snapshot terminology and synchronization concepts, and the configuration has a cooperative mode flag. This shows NORESUS attempted to keep the external strategic state coordinated for co-op use.

Gates should not absorb this scope into the division implementation. Multi-user campaign synchronization is a separate product boundary and should remain deferred unless explicitly planned.

# Direct NORESUS vs Gates comparison

| Capability | NORESUS supplied snapshot | Gates current implementation | Gates target / future plan |
|---|---|---|---|
| Strategic owner | External Windows app | Python authoritative campaign | Python + Godot player shell |
| Strategic map | 639 region adjacency graph | GoE/interim + Earth3/operational work | Earth3 3,514 provinces + reviewed operational graph |
| On-map force | Battalion | `StrategicFormation` | Division/brigade recommended |
| Subordinate maneuver units | No persistent parent hierarchy found | `StrategicFormation.battalion_ids` already exists | Battalion packages under division/brigade |
| Battalion composition | Rich HQ/platoon management | roster + authorized roster | Full management UI + templates |
| Multiple battalions in operation | Nearby support exists | pending battle supports multiple participants | Explicit commitment selection |
| Division designer | Not found | Data shape partly exists, UI absent | Formation designer / organizer |
| Strategic time | Continuous/pausable virtual calendar | deterministic turns + 10 operational ticks | 7-day turn presentation over deterministic ticks |
| Movement | region-to-region with travel/date/fuel | node/edge operational movement | keep Gates model |
| Supply | persistent, surround/resupply/attrition | operational supply, grace/cutoff, infrastructure | keep Gates model, tune UX |
| Economy/research | broad WWII economy + tech availability | actor/faction economy, research, reinforcement | keep Gates authority |
| Fog/intel | battalion fog + intel operations | typed observation/knowledge model | keep Gates S11 design |
| Tactical handoff | generated NORESUS save, auto launch/return | guarded manifest + export/import | integrate in player shell, fix #166 |
| Battle identity | app-managed | exact `battle_id` manifest | keep exact binding |
| Survivor ownership | battalion/personnel persistence | battalion/stage survivor import | add commitment/wave identity as needed |
| Tactical waves | fixed 3-unit waves in inspected Lua | native Code:X/AI behavior mostly authoritative today | #185 exact committed battalion waves/hybrid |
| Battalion-aware AI | yes, strategy selection by type | actor/roster authority exists, battle AI seam unresolved | #185 prototype |
| Actor identity | WWII side/nation model | strategic actor separated from tactical/source family | #201 decides native custom tactical IDs |
| Mod stack | auto-activates/deactivates expected mods | fail-closed validated ordered stack | keep Gates behavior |
| Crash/recovery | crash can cancel without strategic change | manifest/verification and backups | keep Gates behavior |
| Co-op | external snapshot mechanisms present | not core | defer |

# How Shutkar1992's proposal relates to NORESUS

The proposal is best described as **NORESUS plus one higher operational echelon and better tactical commitment control**.

NORESUS today is approximately:

```text
Strategic map
  -> Battalion A
  -> Battalion B
  -> Battalion C

Battalion A attacks
  -> its battle plus possible nearby support
  -> GoH tactical AI purchases/spawns waves
```

Shutkar's target is:

```text
Strategic map
  -> Division
       -> Motor Rifle Battalion A
       -> Motor Rifle Battalion B
       -> Motor Rifle Battalion C
       -> Tank Battalion
       -> Artillery Battalion
       -> Air Defense / Engineer / Logistics support

Operation
  -> choose battalions/support by task
  -> GoH receives only the committed tactical slice
  -> remaining battalions stay in reserve
```

That is not present as a persistent hierarchy in the supplied NORESUS database.

The proposal is nevertheless technically aligned with Gates because Gates already has a `StrategicFormation` container that can be brigade/division echelon and own battalion IDs.

# Recommended Gates architecture

## Keep current authority boundaries

Do not create a second campaign state or a parallel NORESUS-like database.

Keep:

- `CampaignState` as authoritative state;
- `StrategicFormation` as on-map movement authority;
- `Battalion` as persistent subordinate force package;
- operational graph as location/movement authority;
- actor model as identity/economy/recruitment authority;
- `PendingBattle` plus battle manifest as tactical boundary;
- Python as write authority;
- Godot as player-facing UI.

## Add an explicit operation/commitment layer

Recommended conceptual shape, to be designed in a later schema PR:

```text
Operation
  operation_id
  contact / objective / province / node / edge
  attacker_formation_ids
  defender_formation_ids
  status

OperationCommitment
  operation_id
  formation_id
  battalion_id
  role
  wave_index
  committed_fraction_or_scale
  persistent = true|false
  support_mode
```

Roles should be data-driven and may include:

- maneuver;
- reserve;
- fire support;
- air defense;
- engineers;
- reconnaissance;
- logistics;
- tactical-only support where explicitly allowed.

Do **not** add this schema until its migration and interaction with current `PendingBattle` are independently designed.

## Reuse `PendingBattle` rather than replacing it

The commitment layer should compile into the existing battle participants.

Current `PendingBattle` already has:

- attacking and defending participant lists;
- battalion IDs;
- stage;
- attacker/defender formation IDs;
- encounter node/edge/progress metadata.

Likely extension points after design approval:

- commitment ID;
- explicit wave index;
- operation role;
- tactical scale/materialization rule;
- support persistence class.

This keeps current survivor import and operational finalization useful.

## Division designer should manipulate organization, not tactical headcount

A division designer should answer:

- which battalions belong to the formation;
- battalion type/template;
- authorized roster;
- attachments/support;
- commander;
- readiness and supply;
- reinforcement priority;
- reserve status.

It should **not** promise that every strategic squad/vehicle appears simultaneously in GEM.

## Add deterministic tactical scaling

The strategic roster remains authoritative, but a battle may use a deterministic representation ratio when the full force is beyond practical GoH scale.

Any abstraction must record:

- source strategic quantity;
- tactical quantity;
- scaling rule/version;
- casualty mapping rule;
- minimum/maximum representation;
- support treatment.

Do not lock Shutkar's proposed 40-squad / 20-IFV / 10-APC style values until #185 benchmarks them.

# Specific consequences for current GitHub plans

## #66 operational maneuver

**Do not rewrite it.** It is already pointed in the right direction.

Formation is the movement authority, and formation position is node/edge based. That is exactly what a division-scale map token needs. Battalion movement should become subordinate to the formation except where a split/detachment operation is explicitly created.

## #52 battalion stack/composition UI

The issue remains useful but should eventually become a two-level organization UI:

```text
selected strategic formation
  -> subordinate battalion cards/tabs
  -> selected battalion roster
```

The planned recruit/transfer/rename/split/merge transaction model is compatible with the NORESUS HQ lesson. Add a later operation-commitment panel rather than overloading the normal roster manager.

Do not implement the division hierarchy by merely labeling a battalion card “division.” The parent/subordinate relationship must be real campaign data.

## #176 Earth3 playable vertical slice

**Keep the P1-P6 chain scope-stable.** Do not insert a division-system rewrite into the current Earth3 golden-path milestone.

#176's job is to prove:

```text
Earth3 -> operational move -> pending battle -> GoH -> verified import -> continue/save/reopen
```

That bridge must be stable before adding richer force commitment.

The division system should extend the proven path after P5/P6, not become a new prerequisite that prevents the first playable loop from landing.

## #185 battalion-composition-driven tactical AI waves

This study materially changes the research baseline.

New direct evidence from NORESUS:

- a tactical wave controller exists in the supplied mod;
- the inspected version sets waves to exactly three purchased units;
- inter-wave/inter-purchase timing is explicitly authored;
- AI strategy is selected using battalion type;
- AI logic can bias/force unit categories.

Therefore #185 should now focus its live work on:

1. proving which of these seams still function under the exact current Vanilla -> West81 -> Code:X -> AI Overhaul -> Gates stack;
2. replacing fixed generic three-unit waves with battle-specific committed battalion manifests;
3. preserving source battalion identity through delayed waves;
4. preventing unrelated native purchases;
5. benchmarking two and three committed battalions;
6. determining whether support should be persistent objects, delayed waves, or off-map assets.

This is stronger than the previous “maybe GEM cannot do it” assumption.

## #201 custom tactical faction IDs

#201 remains a critical architectural gate.

NORESUS proves battalion-type tactical AI specialization in its WWII side model, but it does not answer whether modern Code:X safely supports distinct Gates-owned faction IDs for every persistent national actor.

Do not let the division work bypass this problem. A committed Serbian battalion and a committed Russian battalion must retain actor-specific tactical authority even if they share a source family.

## #45 strategic actor model

NORESUS reinforces, rather than weakens, the Gates decision to separate strategic identity from tactical/source-family identity. The modern campaign has substantially more actor complexity than the WWII reference.

# What to borrow conceptually

These NORESUS concepts are worth carrying forward in original Gates code:

1. **External strategic ownership, GoH tactical resolution.** Already implemented in Gates.
2. **Persistent battalion composition.** Already partly implemented; deepen management UX.
3. **Parent formation organization.** New Gates layer, not directly present in NORESUS.
4. **Nearby formation support authorization.** Good model for operation support roles.
5. **Battalion-type-informed tactical AI.** Very relevant to #185.
6. **Battle waves as an explicit tactical control surface.** Replace fixed three-unit trickle with committed-wave logic.
7. **Persistent readiness/resupply/repair.** Already compatible with Gates.
8. **Calendar presentation and historical/period availability concept.** Adapt to modern scenario, not copy data.
9. **Crash means no strategic mutation until a valid result exists.** Gates already does this more safely.
10. **Post-battle continuity.** Casualties and readiness matter to the next operation.

# What not to copy

1. Do not redistribute the NORESUS executable, SQL map data, images, maps, or scripts.
2. Do not auto-enable/disable the user's GoH mods as the normal Gates contract.
3. Do not replace Earth3 with the 639-region map.
4. Do not replace deterministic turn/tick simulation with real-time virtual-day timers.
5. Do not make one battalion the top strategic echelon.
6. Do not inherit the fixed three-unit wave policy.
7. Do not use generic faction-wide purchases when exact committed actor/battalion identity can be preserved.
8. Do not make per-soldier persistence a blocker for division operations.
9. Do not assume historical WWII production/resource values transfer to a modern Code:X campaign.
10. Do not weaken exact battle verification or rollback to mimic the reference's automatic flow.

# Proposed implementation sequence

This is a recommended future chain, not authorization to begin it before the current gates are complete.

## R0: research record

This branch.

Deliver:

- reproducible clean-room metadata probe;
- architecture report;
- comparison against current Gates state;
- no production schema or runtime changes.

## R1: operation/commitment schema design

Design-only first.

Define:

- operation identity;
- formation participants;
- battalion commitments;
- support roles;
- reserve state;
- wave ordering;
- tactical scaling contract;
- save migration;
- exact interaction with `PendingBattle`.

Stop for independent review before implementation.

## R2: additive backend commitment implementation

After accepted design:

- add schema/migration;
- formation remains movement authority;
- commit/uncommit battalions transactionally;
- generate current `BattleParticipant` records from commitments;
- no tactical wave override yet;
- tests for save/load, duplicate commitment, wrong formation, destroyed/cutoff battalion, and rollback.

## R3: formation and commitment UI

Extend #52 concepts:

- division/brigade header;
- subordinate battalion cards;
- reserve/commit selection;
- support-role assignment;
- tactical-size preview;
- disabled reason text;
- Python-validated command queue.

## R4: exact battle materialization manifest

Extend the current handoff, not replace it:

- bind each exported object/stage to operation + commitment + battalion;
- distinguish persistent maneuver assets from tactical-only support;
- preserve exact participant/source identity for import;
- no unrelated AI purchases.

Depends on #201 disposition and stable #176 P5 behavior.

## R5: controlled battalion wave prototype

Fold into #185 research/prototype:

- one attacker formation;
- two deliberately small battalions;
- wave 1 and wave 2 deterministic;
- no fixed three-unit trickle;
- battalion-aware AI strategy;
- exact survivor return to each battalion;
- performance/log evidence;
- production behavior unchanged until independent acceptance.

## R6: weekly calendar layer

If owner confirms one week per strategic turn:

- map each strategic turn to seven campaign days;
- keep ten operational ticks deterministic;
- derive UI date from campaign epoch + turn/tick;
- avoid wall-clock dependence;
- define reinforcement/recovery/research/build times in deterministic ticks/days.

## R7: division organization and balance

Only after the engine path is proven:

- division/brigade templates;
- battalion capacity rules;
- attachments;
- reinforcement priorities;
- strategic strength summaries;
- AI formation construction/reorganization;
- doctrine and actor-specific templates;
- tactical abstraction ratios based on benchmark data.

# Priority recommendation

Do the work in this order:

1. Finish and independently disposition #201 so tactical actor identity is known.
2. Keep #176 moving to the first stable Earth3 strategic-to-tactical-to-strategic golden path.
3. Update #185 with the new direct NORESUS wave evidence and run the modern-stack live tests.
4. Design the operation/commitment schema on top of `StrategicFormation.battalion_ids`.
5. Extend #52 into formation -> battalion -> operation presentation.
6. Only then tune real-world division/battalion sizes and weekly campaign pacing.

This avoids throwing away working Gates architecture to chase a reference implementation that is actually less hierarchical than the target design.

# Final verdict

### Is NORESUS worth studying for Gates of Code:X?

**Yes, substantially.** It proves the strategic/tactical product pattern and exposes several mature campaign concepts.

### Does NORESUS already implement Shutkar1992's proposed division system?

**No.** The supplied persistent force model is battalion-centric. Nearby battalion support exists, but no persistent division/regiment parent hierarchy was found.

### Is the proposed division system plausible in our current architecture?

**More plausible than it first sounded.** Gates already has the key parent/subordinate data shape and multi-battalion pending-battle participant model. The missing pieces are organization/commitment UX, explicit operation semantics, tactical scaling, and controlled battalion-wave materialization.

### Is the three-unit tactical trickle an unavoidable GEM limit?

**The supplied NORESUS snapshot does not support that conclusion.** Its own tactical script explicitly configures three-unit waves. We still need a current-stack live test, but this is strong evidence that the behavior is at least partly authored and therefore potentially changeable.

### Should Gates copy NORESUS architecture wholesale?

**No.** Keep Gates' Earth3/operational graph, actor model, deterministic turn/tick engine, exact mod-stack validation, battle manifests, verification, and survivor import. Borrow concepts, not code or authority boundaries.

## Clean-room artifacts on this branch

- `docs/research/noresus-strategic-reference.md`: this report.
- `docs/research/noresus-reference-metadata.json`: derived hashes/schema/counts only, no third-party content.
- `tools/probe_noresus_reference.py`: project-owned local-reference metadata/schema probe.

The raw Workshop archive, nested runtime, executable, databases, maps, and assets remain external and are not committed.
