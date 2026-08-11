# #201 native evidence: custom tactical factions work (owner-confirmed)

**Date:** 2026-08-11  
**Issue:** https://github.com/xfizzle-gh/Gates-of-Code-X/issues/201  
**Branch:** `spike/201-custom-tactical-factions`  
**Live layer:** Workshop Gates `3696721120` (final overlay)  
**Stack:** West81 → Code:X → Code:X AI Overhaul → Gates of CodeX (last)  
**Owner verdict:** **Works** — custom IDs `goc_usa` / `goc_fra` usable in Dynamic Conquest (create menu confirmed on-record; owner confirms end-to-end function).

## Evidence

- Create Conquest UI: faction `goc_fra` (and `goc_usa`) selectable; regions Europe / Asia / Test; enemy nation selectable (e.g. Ukraine). No crash.
- Owner confirmation (2026-08-11): **they work** after final additive wiring + owner-tuned research on the live layer.

Spike git holds a snapshot of Gates-owned registration/`goc_*` surfaces copied **out of** the working workshop tree (workshop not modified by the git record step).

## How we made it work (recipe)

### Core idea

**Additive** custom factions on the **final** Gates layer. Keep Core `nato` / `ukr` / `rusa` / `prc`. Final layer must own registration surfaces and must not reference missing unit includes.

### 1. Army files (ids 90 / 91)

```
resource/set/multiplayer/armies/goc_usa.set  → {id 90}
resource/set/multiplayer/armies/goc_fra.set  → {id 91}
```

Engine range 0–99. Sparse high ids avoid Code:X low-id collisions.

### 2. Alliance registry (army picker source of truth)

`resource/set/multiplayer/games/presets/alliances_generic.inc` (keep other presets in sync if included):

```
West:  nato, ukr, goc_usa
East:  rusa, prc, goc_fra
```

AI Overhaul CTF includes `alliances_generic.inc`.

### 3. values.set matchups

Start from Code:X `values.set` (Europe / Asia / Test). Inject both-direction matchups for `goc_usa` / `goc_fra` (vs each other and vs Core sides as needed). Empty matchups for a shown region crash create.

### 4. Full units/conquest tree on the final layer

On Gates final layer:

1. Code:X `conquest/*` needed by roster  
2. AI Overhaul conquest overlays (+ `2022s/` if used)  
3. Gates-only `inf_goc_*.set` and `units_goc_*.set`

### 5. roster_conquest.set — only existing includes

```
conquest/settings.set
conquest/inf_ukr, inf_rusa, inf_nato, inf_prc_era1960, inf_csa_era1960
conquest/inf_goc_usa, inf_goc_fra
conquest/units_ukr, units_rusa, units_nato, units_sov_era1960, units_csa_era1960, units_prc_era1960
conquest/units_goc_usa, units_goc_fra
```

Include `inf_nato` before `inf_goc_*` (`nato_basic` / `nato_medic` / `nato_supporter`).  
Do not include missing Code:X paths (e.g. absent `inf_frg_era1960`).

### 6. Research

`unit_research_goc_usa.set` / `unit_research_goc_fra.set`  
**Owner-tuned on live** — live workshop research is authority; spike snapshot mirrors it.

### 7. Purchase Lua

```lua
Purchases["conquest.goc_usa"] = {
  { Repeat = 0, Units = {
      { priority = ..., type = {...}, unit = "goc_usa_test_rifle(goc_usa)" },
  }},
}
```

MW / AI Overhaul schema (`Repeat` / `Units` / `priority` / `unit`).

### 8. conquest.lua

Copy AI Overhaul `modes/conquest.lua`, patch only:

- `nationMap`: `goc_usa = 9`, `goc_fra = 10`
- `westNations`: `goc_usa = true`
- `eastNations`: `goc_fra = true`

No blind multi-line regex (corrupts file).

### 9. CTF

Final-layer CTF includes `presets/alliances_generic.inc`. Avoid unresolved `gos_*.inc` includes.

### 10. Art + loc

Per-side flags. `mp/army/goc_*` in `dlg_mp2.pot` (raw key if msgstr empty — cosmetic).

## Failures not to repeat

| Attempt | Result |
|---------|--------|
| Armies only; alliances Core-only | goc never in picker |
| Roster includes missing files | crash |
| CTF + missing gos includes | create null crash |
| Army ids 100+ | engine reject |
| Bad automated lua rewrite | corrupt conquest.lua |
| Final layer without full conquest unit files | include failures |

## Review notes (for independent / ChatGPT review)

### In scope

- Spike proof that **Gates-owned** DC army tokens can coexist with Core four sides.
- Disposable `goc_usa` / `goc_fra` content and registration recipe.
- Documentation of live stack procedure.

### Out of scope (do not demand in this PR)

- Production Expanded Nations actor mass-wiring (#191+)
- Changing PR #172 four-side compiler defaults without owner disposition
- Merging spike into `main` as default Gates multiplayer content
- Vendoring full Code:X/AIO unit trees into git
- Earth3 / P5 handoff changes

### Questions for reviewer

1. Is **additive** final-layer registration the right long-term pattern vs standalone last mod only?
2. Should production deploy **copy** parent `conquest/*` onto Gates final layer, or keep those only in Code:X/AIO and ship a thinner Gates overlay (risk: missing includes if roster is owned by Gates)?
3. Confirm army id policy: reserve a Gates band (e.g. 90–99) in docs.
4. Is owner-confirmed DC create + “they work” enough for issue #201 **PASS**, or still require unedited `game.log` + battle save artifacts before close?
5. Recommended follow-up issue split: (a) production deploy tooling for custom factions, (b) Test B/C extra ids, (c) compiler mapping strategic actors → `goc_*`.

### Risk / hygiene

- Live workshop may contain deploy-time copies of upstream unit files — do not treat as Gates copyright source of truth in git.
- `conquest.lua` on final layer **replaces** entire AIO mode script — must be rebased when AIO updates.
- Same for `values.set` / CTF / alliances if parents change.

## Recommended production disposition (draft)

If owner accepts PASS:

- Prefer unique Gates tactical IDs for sovereign Expanded Nations actors.
- Keep `nato/ukr/rusa/prc` as Core compatibility.
- Adapt #172 compiler to emit `goc_*` where proven; do not delete four-side path yet.
- Add deploy recipe/tooling so final layer always has complete includes + registration.

## Next

1. Independent review of this branch + notes (this PR).  
2. Owner close/disposition on #201.  
3. Only then: production wiring / extra nations / compiler changes.
