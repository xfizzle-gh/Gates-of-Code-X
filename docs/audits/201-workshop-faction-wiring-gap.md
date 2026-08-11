# #201 workshop faction-wiring gap analysis

Compared disposable spike vs three known working Conquest faction packs in the local Workshop folder.

| Workshop ID | Name | Role |
|------------:|------|------|
| **3701399761** | Galaxy At War - Conquest | Full custom SW factions (`rep/cis/imp/reb`) |
| **3692035814** | CoD WW3 Redux Conquest Prototype | Full custom modern factions (`mw_us/mw_ru/mw_ins`) |
| **3700832981** | (no mod.info on disk; LV40k/properties tree) | **Not a complete Conquest faction pack in this install** — no armies/alliances/values/roster found |

Base stack for our failed overlay attempt: West81 + Code:X + AI Overhaul + Gates `3696721120`.

## What working packs do that our Gates overlay did not

### 1. They are **replacement** Conquest packs, not additive overlays

GaW / MW own the entire DC faction surface:

| Surface | GaW / MW pattern | Our Gates overlay attempt |
|---------|------------------|---------------------------|
| `armies/*.set` | Ship **only** their armies (or also ship stubs) | Added `goc_*` beside Code:X armies |
| `alliances_*.inc` | **Replace** with alliances that list **only** their armies | Tried to **append** `goc_*` into West/East next to nato/ukr/rusa/prc |
| `values.set` | **Replace** regions/matchups with **only** their pairs | Tried to patch Code:X Europe/Asia tables |
| `roster_conquest.set` | **Replace** with only their unit/inf includes | Tried to append includes onto full Code:X roster |
| `campaign_capture_the_flag.set` | Own CTF that includes **their** alliances file | Added late; may still lose to stack include resolution |
| `mod.info` | `{tags "… conquest dynamic_campaign"}` + **`{delete …}`** of vanilla armies/units/lua | Gates `mod.info` has no `{delete}` and weak tags |
| Breeds | Full `set/breed/mp/<side>/…` trees | Reused `mp/nato/…` via explicit content (OK for spike) |
| `inf_<side>.set` | Present per custom side | Missing dedicated `inf_goc_*.set` |
| Purchase lua | `script/multiplayer/units/<side>/conquest.<side>.lua` | Present for goc_usa/fra |
| `conquest.lua` / `utility.lua` | Often own pacing/nation hooks | Not shipped (rely on AI Overhaul) |

### 2. Alliance registry is the army picker source of truth

MW comment (verbatim intent):

> DCG `values.set` uses `mw_us`/`mw_ru` as the campaign-facing ids.  
> The **create_dynamic_campaign UI expects these ids to be present in the alliance→army registry**.

GaW CTF:

```text
{alliances
  (include "presets/alliances_gaw_conquest.inc")
}
```

GaW `alliances_gaw_conquest.inc` lists **only** `rep/cis/imp/reb` — not vanilla/Code:X sides.

AI Overhaul (what the live stack actually uses today):

```text
West: nato, ukr
East: rusa, prc
```

So the UI the owner sees (nato/ukr/rusa/prc + West81/WW2 leftovers) matches **AI Overhaul + West81**, not a missing `armies/*.set` alone.

### 3. `mod.info {delete …}` cleans vanilla army clutter

GaW deletes vanilla `eng/fin/ger/rus/usa` army sets (and matching units/inf/lua). That stops WW2 armies from remaining in the scroller when the pack is active.

MW comment also notes referencing **missing** DLC armies in alliances can crash `btn_army_next` — consistent with our earlier access violation while cycling.

### 4. Army numeric IDs must be 0..99

Engine hard fail (our first crash):

`Invalid army identifier (must be in range [0, 99])`

GaW uses 6–9; MW uses small ids. Our corrected ids **90/91** are valid.

### 5. Complete DC UI art pack is expected

GaW/MW ship large `interface/pages/main/dynamic_campaign/*_<side>.*` sets (flag, selected_army, headers, map points, etc.). Missing textures correlate with `btn_army_next` crashes. Spike now includes a nato-derived art pack.

### 6. Purchase bots need per-side lua modules

GaW: `units/rep/conquest.rep.lua`, `cis`, `imp`, `reb`.  
MW: `units/mw_us/conquest.mw_us.lua`, etc.  
Loader path is dynamic from `BotApi.Instance.army` (not a 4-name enum). Spike already has goc lua modules.

### 7. 3700832981 in this install is not a usable faction template

On disk it has `resource/set/multiplayer/armies` / `games` / `units` directories but **no army sets, alliances, values, or roster files** in the scanned tree (and no `mod.info`). Treat as incomplete/unpacked for this analysis — do not use as the wiring reference.

## Gap checklist (spike vs GaW/MW)

| Required for DC army to appear & pair | GaW | MW | Our overlay | Standalone mini-mod (new) |
|--------------------------------------|:---:|:--:|:-----------:|:-------------------------:|
| `armies/<id>.set` id 0–99 | Y | Y | Y (90/91) | Y |
| Alliance registry lists army | Y (only theirs) | Y (only theirs) | Partial (additive) | Y (only goc) |
| CTF includes that alliances file | Y | Y | Attempted | Y |
| `values.set` matchups for pair | Y (replace) | Y (replace) | Partial (patch) | Y (replace) |
| Roster includes custom units | Y | Y | Y | Y |
| `inf_<side>.set` | Y | Y | N | N (uses inf_nato) |
| Breed tree `mp/<side>/` | Y | Y | N (explicit nato paths) | N |
| DC UI art pack | Y | Y | Y | Y |
| Localization titles | Y | Y | Partial | Literal titles |
| `mod.info` tags conquest/dcg | Y | Y | N | Y |
| `mod.info {delete}` vanilla armies | Y | N/limited | N | Y (vanilla WW2) |
| Own `conquest.lua` | often | Y | N | N |
| Purchase lua per side | Y | Y | Y | Y |

## Why the Gates overlay still showed only Code:X/West81 armies

Most likely combination:

1. **Live DC UI army list = alliance registry from the winning CTF/alliances include**, which on the owner’s active set is still effectively AI Overhaul/West81’s four modern + legacy sides.
2. Additive West/East entries for `goc_*` either never won the include, or armies were skipped when presentation/title/art were incomplete (earlier crash on `btn_army_next` shows the scroller *can* reach bad army entries).
3. Working Workshop packs **do not try to remain compatible with Code:X’s four sides in the same DC picker** — they **replace** the picker space.

## Recommended spike method going forward (matches GaW/MW bones)

1. Use a **standalone disposable mod** (not only Gates workshop overlay):  
   `Call to Arms - Gates of Hell\mods\goc_201_faction_spike\`
2. Enable it in the mod manager **for Test A**, with Code:X still present for shared `conquest/settings.set` + nato breeds/entities.
3. That mini-mod now follows GaW/MW bones:
   - own `mod.info` with conquest tags + vanilla army `{delete}`s
   - alliances list **only** `goc_usa` / `goc_fra`
   - values matchups **only** that pair
   - roster only spike units (+ settings/inf_nato includes)
   - CTF → `alliances_goc_201.inc`
4. Owner action: enable **GOC 201 Custom Faction Spike** in GoH mod manager, restart, create DC as **GOC USA spike** vs **GOC France spike**.

## Production implication (still provisional until native PASS)

| If standalone mini-mod Test A works | Custom tactical IDs are **engine-viable**; production should plan a **Gates-owned conquest faction pack layer** (GaW/MW style), not a silent additive patch on AI Overhaul alliances. |
| If even standalone fails | Deeper engine/UI hardcoding beyond these packs — reassess. |
| Either way for Code:X coexistence | Keeping `nato/ukr/rusa/prc` Core mode means **two DC faction regimes** (Core four-side vs Expanded custom IDs), not one merged picker without careful mod isolation. |

## Files to mirror next (if Test A still fails on mini-mod)

Priority order from GaW/MW:

1. Confirm mini-mod is **activated** in log (`Mod: activate` path under `mods/goc_201_faction_spike`).
2. Add `inf_goc_usa.set` / `inf_goc_fra.set` (even if thin).
3. Ship minimal `mp/goc_usa` / `mp/goc_fra` breed aliases if explicit content paths fail spawn.
4. Own `conquest.lua` nationMap entries if AI Overhaul rejects unknown sides after load.
5. Only then consider `{delete}` of Code:X army files via mod.info (breaks Core four-side while spike enabled — acceptable for disposable test).

## conquest.lua (added from GatesOfEuropa 3717998771)

Snagged `resource/script/multiplayer/modes/conquest.lua` from Workshop **3717998771** (GatesOfEuropa) and extended `nationMap`:

- retained GOE ids: rus/ger/fin/usa/eng
- added Code:X modern ids (AI Overhaul numbering): rusa/ukr/nato/csa/sov/prc/frg/pol
- added spike nations: `goc_usa = 9`, `goc_fra = 10`

Shipped under spike `resource/script/multiplayer/modes/conquest.lua` and standalone mini-mod.
