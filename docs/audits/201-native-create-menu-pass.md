# #201 native evidence: Dynamic Conquest create menu (PARTIAL PASS)

**Date:** 2026-08-11  
**Issue:** https://github.com/xfizzle-gh/Gates-of-Code-X/issues/201  
**Branch:** `spike/201-custom-tactical-factions`  
**Live layer that worked:** Workshop Gates `3696721120` (final overlay)  
**Stack:** West81 → Code:X → Code:X AI Overhaul → Gates of CodeX (last)  
**Verdict:** **PARTIAL PASS** — custom tactical IDs `goc_usa` and `goc_fra` appear in Create Conquest and are selectable without crash.

## Owner evidence

Create Conquest UI loaded with custom faction selected (e.g. `goc_fra`), regions Europe / Asia / Test, enemy nation selectable (e.g. Ukraine). No crash on open or faction cycle for the custom ID.

### Still open (Test A remainder)

- Continue → campaign file created and loads
- Battle load / spawn
- Player roster = goc test pool only when playing goc
- AI purchase isolation
- Research UI behavior (owner adjusted research files on the live layer; treat live research as authority)
- Battle complete + save rewrite

## How we made it work (recipe)

### Core idea

**Additive** custom factions on the **final** Gates layer. Keep Core `nato` / `ukr` / `rusa` / `prc`. Do not rely on a half-empty units tree.

### 1. Army files (ids 90 / 91)

```
resource/set/multiplayer/armies/goc_usa.set  → {id 90}
resource/set/multiplayer/armies/goc_fra.set  → {id 91}
```

Engine range is 0–99. Sparse high ids avoid collisions with Code:X low ids.

### 2. Alliance registry (this is the army picker)

`resource/set/multiplayer/games/presets/alliances_generic.inc` (and matching presets if used):

```
West:  nato, ukr, goc_usa
East:  rusa, prc, goc_fra
```

AI Overhaul CTF includes `alliances_generic.inc`. If the final layer wins CTF, it must include a presets file that lists every army you want in the scroller.

### 3. values.set matchups

Start from Code:X `values.set` (Europe / Asia / Test). Inject both-direction matchups involving `goc_usa` / `goc_fra` (vs each other and vs Core sides as needed). Empty matchups for a shown region crash create.

### 4. Full units/conquest tree on the final layer

Copy onto Gates final layer:

1. Code:X `resource/set/multiplayer/units/conquest/*` needed by roster  
2. AI Overhaul conquest overlays + `2022s/` if used  
3. Gates-only `inf_goc_*.set` and `units_goc_*.set`

### 5. roster_conquest.set — only existing includes

Broken includes = crash. Working live roster:

```
conquest/settings.set
conquest/inf_ukr, inf_rusa, inf_nato, inf_prc_era1960, inf_csa_era1960
conquest/inf_goc_usa, inf_goc_fra
conquest/units_ukr, units_rusa, units_nato, units_sov_era1960, units_csa_era1960, units_prc_era1960
conquest/units_goc_usa, units_goc_fra
```

Include `inf_nato` before `inf_goc_*` so `nato_basic` / `nato_medic` / `nato_supporter` exist.

Do not include Code:X lines for files that are not on disk (e.g. missing `inf_frg_era1960`).

### 6. Research

`unit_research_goc_usa.set` / `unit_research_goc_fra.set`  
Owner-tuned research on the live workshop layer is part of the working state; snapshot into spike for the record.

### 7. Purchase Lua (working schema)

```lua
Purchases["conquest.goc_usa"] = {
  { Repeat = 0, Units = {
      { priority = ..., type = {...}, unit = "goc_usa_test_rifle(goc_usa)" },
  }},
}
```

Match MW / AI Overhaul (`Repeat` / `Units` / `priority` / `unit`). Not lowercase `repeat` / `unit_count`.

### 8. conquest.lua

Copy AI Overhaul `modes/conquest.lua` to final layer, then patch only:

- `nationMap`: `goc_usa = 9`, `goc_fra = 10`
- `westNations`: `goc_usa = true`
- `eastNations`: `goc_fra = true`

Never blind multi-line regex replace (corrupts the file).

### 9. CTF

Final-layer CTF includes `presets/alliances_generic.inc` (AIO-style). Avoid CTF that includes missing `gos_*.inc` paths unless those files resolve.

### 10. Art + loc

Per-side DC/multi flags. Army titles via `mp/army/goc_*` in `dlg_mp2.pot` (raw key shows if msgstr empty — cosmetic).

## What we tried that failed

| Attempt | Result |
|---------|--------|
| Armies only, alliances still Core-only | goc never in picker |
| Replacement roster with missing includes | crash |
| CTF with unresolved gos includes | DC create null crash |
| Army ids 100+ | engine reject |
| Automated lua rewrite bugs | corrupt conquest.lua |
| Overlay Gates without full conquest unit files | roster include failures |

## Deploy / hygiene

- Final layer last in mod manager.  
- Disable GaW/MW/UFO Conquest replacements while testing.  
- Full GoH restart after file changes.  
- Do not commit upstream Code:X/AIO unit binaries as Gates IP; deploy-time copy from installed stack is fine.  
- Spike git keeps Gates-owned `goc_*` surfaces + this recipe + snapshot of registration files from the working live layer.

## Next (issue #201)

1. Finish Test A: Continue → battle → AI buy → complete/save.  
2. Tests B/C after A.  
3. Owner disposition PASS / PARTIAL / FAIL for Expanded Nations production path.  
4. Do not mass-wire production actors until battle path is green.
