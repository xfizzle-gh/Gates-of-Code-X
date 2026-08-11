# #201 native test handoff (Tests A/B/C)

**Issue:** #201  
**PR:** #208 (draft)  
**Branch:** `spike/201-custom-tactical-factions`  
**Status:** fixtures + static checks ready — **no native PASS claimed by agents**

## Stack

```
West-81 → Code-X → Code:X AI Overhaul → Gates of CodeX (last)
```

Disable other Conquest replacement packs (GaW/MW/UFO/etc.) during these tests.

## Deploy (deterministic final-layer materializer)

From repo / worktree:

```powershell
cd spikes\201-custom-tactical-factions

# Preferred: Workshop root auto-resolves West81/CodeX/AIO ids
.\deploy.ps1 `
  -GatesRoot "E:\Steam\steamapps\workshop\content\400750\3696721120" `
  -WorkshopRoot "E:\Steam\steamapps\workshop\content\400750"

# Restore previous Gates files after testing
.\deploy.ps1 -GatesRoot "E:\Steam\steamapps\workshop\content\400750\3696721120" -Restore
```

What deploy does:

1. Treats West81 / Code:X / AI Overhaul as **read-only**
2. Copies only the parent `units/conquest/*.set` files required by `roster_conquest.set` into Gates
3. Installs GOC prototype files
4. Records SHA-256 + source path for each parent file under `.deploy-backup/`
5. Verifies roster includes resolve
6. Audits GOC army IDs for collisions in the effective stack
7. Backs up overwritten Gates files (restore supported)

Optional standalone last-mod path (idempotent; does **not** mutate `conquest.lua`):

```powershell
.\deploy_standalone.ps1 -GameRoot "<GoH game root>"
```

## Army IDs (collision-audited on Vanilla→West81→Code:X→AIO→Gates)

| Faction   | Army ID | nationMap | Coalition |
|-----------|---------|-----------|-----------|
| goc_usa   | 90      | 9         | West      |
| goc_fra   | 91      | 10        | East      |
| goc_srb   | 92      | 11        | East      |
| goc_rus   | 93      | 12        | East      |
| goc_dprk  | 94      | 13        | East      |

IDs 92–94 were free in the audited stack (used set included 0–8, 10–13, 90–91).

## Static check (not native)

```powershell
python -m unittest tests.test_201_custom_tactical_factions_spike -v
```

## Owner native procedure (in order)

Collect for each case:

- unedited `game.log`
- before-battle Conquest save/status
- after-battle Conquest save/status
- roster + research screenshots if practical

### Test A regression — `goc_usa` vs `goc_fra`

1. Create Dynamic Conquest, region **Test** or **Europe**
2. Player: **GOC USA spike** (`goc_usa`); Enemy: **GOC France spike** (`goc_fra`)
3. Confirm selectable, campaign creates
4. Confirm player roster is only the three USA test units
5. Confirm research tree shows only GOC USA test entries (no NATO blob)
6. Enter battle: both sides spawn; costs positive
7. Complete battle; save rewrites; reload works

### Test B — `goc_srb` vs `goc_rus`

Purpose: two former RUSA-transport actors keep distinct identities.

1. Player: **GOC Serbia spike**; Enemy: **GOC Russia spike** (or reverse)
2. Confirm both selectable and campaign creates
3. Player roster = only `goc_srb_test_*`
4. Research = only Serbia GOC test entries
5. Enemy AI purchases only `goc_rus_test_*` (no generic RUSA squad IDs)
6. Infantry + vehicle costs positive; both sides spawn; battle completes; save/reload OK

### Test C — `goc_usa` vs `goc_dprk`

1. Player: **GOC USA spike**; Enemy: **GOC DPRK spike**
2. Same isolation checks as above
3. **Critical:** DPRK purchase/research must show **zero ordinary Russian/RUSA squad leakage**
4. DPRK content is KPA `kor_*` breeds + GOC-wrapped squad IDs only

## Prototype content (disposable)

Each faction exposes exactly three purchase units:

- `*_test_rifle(goc_*)`
- `*_test_at(goc_*)`
- `*_test_vehicle(goc_*)`

Source-backed breeds/entities (not invented):

- **USA:** Code:X `mp/nato/2022s/usmc_*` + `m1126`
- **France:** Code:X `mp/nato/2022s/nato_*` + `amx10rc`
- **Serbia:** Code:X `mp/rusa/2022s/Serb_*` + `bmp-1_rus`
- **Russia:** Code:X `mp/rusa/2022s/rus_*` + `btr-82a`
- **DPRK:** Code:X `mp/rusa/2022s/kor_*` + `bmp-1_rus`

## Out of scope

- Production #191/#192/#193 national wiring
- PR #172 compiler changes
- Earth3 / P4 / P5
- Claiming native PASS without owner evidence
