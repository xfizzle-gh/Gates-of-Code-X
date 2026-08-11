# #201 ChatGPT / independent review brief

Use this with the PR diff and `docs/audits/201-native-create-menu-pass.md`.

## One-sentence result

Gates can add real Dynamic Conquest army tokens (`goc_usa`, `goc_fra`) **additively** on the final workshop layer without replacing Core Code:X sides; owner confirms they work in-game.

## Stack that worked

```
West81 → Code:X → Code:X AI Overhaul → Gates of CodeX (3696721120, last)
```

Other Conquest replacement packs (GaW/MW/UFO) disabled during test.

## Minimal surface checklist (must all be true)

- [ ] `armies/goc_*.set` ids in 0–99 (we used 90/91)
- [ ] `alliances_generic.inc` lists goc on West/East **with** Core armies
- [ ] `values.set` has goc matchups on Code:X region keys
- [ ] Final layer `units/conquest/` has every file the roster includes
- [ ] `roster_conquest.set` includes Core pool + `inf_goc_*` + `units_goc_*`
- [ ] `unit_research_goc_*.set` present (owner-tuned)
- [ ] `conquest.goc_*.lua` uses `Repeat`/`Units`/`priority`/`unit`
- [ ] `modes/conquest.lua` = AIO base + nationMap + west/east goc
- [ ] CTF includes `alliances_generic.inc`
- [ ] Flags exist for icons

## Our notes (engineering)

1. **Picker = alliances, not armies alone.**  
2. **Missing roster includes crash harder than wrong content.**  
3. **Final layer winning `roster_conquest.set` must not reference absent parent files** — either copy parents onto final layer or do not own roster.  
4. **Purchase schema is case-sensitive to the working Conquest style** (`Repeat` not `repeat`).  
5. **conquest.lua must be whole-file replace + surgical edits** — partial merge is not how GoH mod FS works.  
6. **Do not ship production actors yet** — spike ids only until deploy tooling + compiler policy are decided.

## Please review / answer

1. PASS vs PARTIAL for #201 given owner “they work” without attached game.log in-repo?  
2. Additive final-layer vs mandatory standalone last mod for production?  
3. Safe army id band for Gates forever?  
4. What is the smallest production follow-up issue set?

## Explicit non-goals for this review

- Do not redesign Earth3  
- Do not rewrite #172 in this PR  
- Do not expand to full national rosters  
- Do not merge to main without owner gate  
