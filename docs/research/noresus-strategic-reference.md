# NORESUS strategic campaign reference study

## Why this exists

Workshop item `3180617465` is **NORESUS - Strategic Map**, described by its installed `mod.info` as `Conquest\Enhanced Campaign 1.9.3.4`.

The supplied package is a direct predecessor/reference for the kind of operational campaign layer Gates of Code:X is building: a strategic Europe map, persistent campaign state, strategic decisions outside Gates of Hell, and a tactical handoff into GoH for the battle itself.

This reference is especially relevant to the proposed division-scale model:

- strategic map formations represented at division/brigade scale;
- subordinate battalion/regiment packages inside a formation;
- player selection of which forces and support assets participate in a tactical engagement;
- campaign turns measured at an operational timescale, with GoH resolving only the selected tactical slice;
- persistent casualties, equipment, reinforcement, movement, supply, and results feeding back into the strategic state.

## Supplied reference snapshot

The locally supplied archive is:

- filename: `3180617465.zip`
- size: `239,133,688` bytes
- SHA-256: `c58a1da76c65b682236d868f6790dcbf6ef9707365d4dcfc883ab59111034659`
- Workshop identity: `3180617465`
- installed name: `NORESUS - Strategic Map`
- version string: `Conquest\Enhanced Campaign 1.9.3.4`
- file count in the supplied ZIP: `10,161` non-directory files

High-level file inventory from the supplied snapshot:

- `resource/`: 8,247 files
- `image/`: 1,829 files
- `localizations/`: 43 files
- `map/`: 14 files
- nested `NORESUS CONQUEST ENHANCED.rar`: about 3.4 MB
- dominant file types: `.set`, `.png`, `.ebm`, `.jpg`, `.tga`, `.ply`, `.info`, `.def`, `.mi`, `.vol`, `.inc`

The included `READ ME FIRST.txt` describes the runtime flow as follows, paraphrased:

1. The player launches the external NORESUS strategic application.
2. The application identifies the GoH installation and player profile.
3. The player makes campaign decisions on a Europe strategic map.
4. For an attack or defense operation, NORESUS prepares a GoH battle/save and launches Gates of Hell.
5. The player resolves the battle in GoH.
6. NORESUS returns to the strategic layer and updates the campaign from the battle result.

That makes the package useful as an observable interoperability and campaign-design reference, not merely as artwork or a unit pack.

## Clean-room / repository boundary

Do **not** commit the supplied ZIP, nested RAR, executable, images, maps, game resources, or copied implementation into Gates of Code:X.

Reasons:

1. The Gates of Code:X repository is public and already follows a clean-room architecture.
2. The supplied package contains third-party binaries/assets and no redistribution license was found in the supplied snapshot.
3. The ZIP is about 239 MB and is unsuitable for the normal GitHub contents path in any case.

Treat NORESUS exactly as an **external local reference**. Record behavior, schemas, observable file contracts, and independently derived design conclusions. Reimplement required behavior in project-owned code.

Recommended local reference variable on Windows:

```powershell
$env:NORESUS_REFERENCE_ROOT = "E:\Steam\steamapps\workshop\content\400750\3180617465"
```

Research tooling may read from that path when explicitly requested, but tests and normal runtime must not require the external package unless they are specifically tagged as local reference/acceptance probes.

## Study questions

### 1. Strategic state model

Determine what NORESUS persists for:

- countries/factions;
- provinces/regions;
- ownership and control;
- formations;
- manpower/equipment;
- reinforcement and production;
- supply/fuel/resources;
- commanders/ranks/experience;
- movement and operational orders;
- battle history;
- turn/date progression.

### 2. Formation hierarchy

Determine whether the reference models formations explicitly as:

```text
Army / Corps
  -> Division / Brigade
    -> Regiment / Battalion
      -> tactical force package
```

Separate what is truly persisted from what is only UI presentation.

For Gates of Code:X, do not assume the same hierarchy is correct. The likely target should be tested as:

```text
Strategic token: division or brigade
Persistent sub-units: battalion-scale packages
Tactical commitment: selected battalions + support elements
GoH battle: only the committed tactical slice
```

### 3. Tactical handoff contract

Document exactly how NORESUS:

- chooses the GoH map;
- writes or modifies campaign/save files;
- selects attacker and defender units;
- communicates battle identity;
- launches GoH;
- detects completion;
- imports survivors/casualties/result;
- recovers from interrupted or invalid battles.

Compare the observable behavior to the existing Gates of Code:X guarded handoff, verification, and survivor-import pipeline.

### 4. Turn and battle timescale

Determine how strategic turns, battle dates, movement, production, reinforcement, and recovery relate to one another.

Evaluate the proposed Gates of Code:X convention:

- one strategic turn = one week;
- movement/orders resolved at strategic scale;
- a contested operation may produce one or more tactical engagements;
- GoH does not attempt to spawn a literal division at once.

### 5. Pre-battle force assignment

This is the key design target inspired by Ultimate General-style deployment.

The player should be able to select a formation and allocate subordinate packages to a battle or task, for example:

```text
3rd Motor Rifle Division

Assault force
- Motor Rifle Battalion A
- Motor Rifle Battalion B
- Tank Battalion
- Engineers

Fire support
- Artillery Battalion
- Air-defense / support package

Reserve
- Motor Rifle Battalion C
```

The tactical mission generator then translates only the committed packages into a GoH-sized roster.

Research should determine which parts of this NORESUS already demonstrates and which parts would be new Gates of Code:X work.

## Proposed implementation sequence after study

1. **Reference inventory**
   - map files, configs, SQL/schema clues, strategic state files, handoff artifacts, and executable-visible contracts;
   - no code copying.

2. **Operational formation schema**
   - division/brigade container;
   - battalion packages;
   - equipment/manpower/readiness;
   - support attachments;
   - persistence and migrations.

3. **Division designer / force organization**
   - create/reorganize persistent formations;
   - enforce composition rules without requiring literal real-world headcounts in tactical battles.

4. **Pre-battle commitment UI/model**
   - choose participating battalions/support;
   - reserve non-participating elements;
   - validate deployment budgets and tactical scale.

5. **Battle generation bridge**
   - convert committed operational packages into the existing GoH handoff contract;
   - retain exact battle binding, verification, survivor import, and rollback safety.

6. **Post-battle operational resolution**
   - casualties and equipment loss;
   - experience/readiness;
   - reinforcement/replacement;
   - province/control consequences;
   - multi-engagement operation handling if required.

7. **Strategic UI**
   - formation panel;
   - hierarchy and composition;
   - task/commitment selector;
   - operational calendar and weekly turn presentation.

## Non-goals for the first implementation slice

- spawning an entire real-world division simultaneously in GoH;
- simulating every soldier or vehicle individually at strategic scale;
- copying NORESUS code, binaries, SQL data wholesale, or artwork;
- replacing the current guarded tactical handoff before the new model proves compatible with it;
- committing third-party Workshop content to the repository.

## First research deliverable

Produce a factual architecture report from the local reference snapshot containing:

1. observed strategic data stores and schemas;
2. observable formation hierarchy;
3. turn/date model;
4. movement/attack workflow;
5. tactical handoff inputs and outputs;
6. post-battle import behavior;
7. reusable concepts versus concepts that must be redesigned for modern Code:X;
8. a minimal PR chain for adding division-scale persistent formations and battalion commitment without destabilizing the existing campaign engine.

Stop at the research report before changing the authoritative campaign schema.