# #201 custom tactical faction seam audit

**Base:** `76b0007f7c153ef42961eeeb6792fc7acf8c8dbf` (`main` after PR #172)  
**Branch:** `spike/201-custom-tactical-factions`  
**Date:** 2026-08-11  
**Stack:** Vanilla → West81 `2897299509` → Code:X `3261086933` → AI Overhaul → Gates Workshop `3696721120`

## Purpose

Determine whether Gates can introduce **real additional Dynamic Conquest army/side tokens** (e.g. `goc_usa`) without replacing Core `nato|ukr|rusa|prc`.

## Verdict (pre-native): engineering feasibility **LIKELY PASS** for registration/roster/research; **PARTIAL risk** for AI Overhaul MI/support maps

Native GoH evidence is still required for final `PASS|PARTIAL|FAIL`.

## Registration surfaces

| Surface | Mechanism | Hardcoded to 4 sides? |
|---------|-----------|------------------------|
| Army registry | `resource/set/multiplayer/armies/<side>.set` | **No** — free filename token; MW mod uses `mw_us` etc. |
| Research | `resource/set/dynamic_campaign/unit_research_<side>.set` | **No** — naming convention from army token |
| Roster | `roster_conquest.set` includes + `side(token)` on purchases | **No** — include/list driven |
| DC matchups | `dynamic_campaign/values.set` `{AvailableMatchups}` | **List** — must add pairs |
| AI purchases | `script/multiplayer/units/<side>/conquest.<side>.lua` via `BotApi.Instance.army` | **Path dynamic**; missing → empty buys |
| AI Overhaul MI | `nationMap` / `player_nation` numeric folds | **Yes** — unknown → default/wrong support pool |
| Gates Python | `SUPPORTED_TACTICAL_SIDES`, `Faction` enum | **Yes** — Phase 1 policy lock (do not change for spike) |
| Save `army`/`enemyArmy` | Free strings in status | **No** — live saves show `mw_us`, `frg`, … |

### Exact Code:X army IDs observed

`rusa=0 ukr=1 nato=2 prc=3 csa=4 sov=5 frg=6 usa=7 rus=8 …`  
Spike uses **100/101** for `goc_usa`/`goc_fra` to avoid collisions.

### Key paths

- Code:X armies: `3261086933/resource/set/multiplayer/armies/{nato,ukr,rusa,prc}.set`
- Code:X research: `.../dynamic_campaign/unit_research_{nato,ukr,rusa,prc}.set`
- Code:X roster: `.../units/roster_conquest.set`
- Code:X matchups: `.../dynamic_campaign/values.set`
- AI purchase loader: `.../script/multiplayer/modes/utility.lua` (army-token path)
- AI Overhaul nationMap: `CodeX AI Overhaul Submod/.../modes/conquest.lua`
- AI Overhaul player_nation: `.../map/multi/dcg_script.inc`
- Prior art: Workshop MW mod `3692035814` (`mw_us`/`mw_ru`/`mw_ins`)

## Prototype package

Disposable files live under:

`spikes/201-custom-tactical-factions/resource/**`

Deploy/restore:

`spikes/201-custom-tactical-factions/deploy.ps1`

Does **not** edit upstream Workshop packages in place; only the final Gates layer receives copies, with backup/restore.

## Native matrix (still open)

1. **Test A** `goc_usa` vs `goc_fra` — menu load, roster isolation, costs, spawn, AI buy, complete/save  
2. **Test B** `goc_srb` vs `goc_rus` — after A  
3. **Test C** `goc_usa` vs `goc_dprk` — after A  

## Production implication (pending native)

- If A–C pass cleanly including AI isolation → prefer unique Gates tactical IDs for sovereign actors; keep four Core sides for compatibility; adapt #172 compiler rather than discard.  
- If only registration works but AI Overhaul MI breaks → **PARTIAL**; compare hybrid cost vs four-side battle-pair overlay (P5/#185).  
- If army/research/roster cannot load or persist → **FAIL**; retain four-side projection.

## Safety

- No Vanilla/West81/Code:X/AI Overhaul in-place edits  
- No Phase 1 production path changes  
- No full national content  
- Spike files isolated under `spikes/201-...`  

## Native launch crash (first deploy)

`Invalid army identifier (must be in range [0, 99])` (`mp_gamemisc.cpp:182`)

Engine hard-limits numeric `{id N}` to **0..99**. Spike IDs 100/101 crashed on launch. Retargeted to **90/91**.

## Critical missing seam (found via MW prior art)

Dynamic Conquest army picker uses **alliance ? army registry**, not armies/*.set alone.

Effective file (AI Overhaul):
`resource/set/multiplayer/games/presets/alliances_generic.inc`

Stock contents only:

- West: `nato`, `ukr`
- East: `rusa`, `prc`

MW comment: *create_dynamic_campaign UI expects these ids to be present in the alliance->army registry*.

Spike now overlays that file and registers `goc_usa` under West and `goc_fra` under East (opposition pairing for Test A).
