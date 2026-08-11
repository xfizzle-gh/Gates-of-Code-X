# #201 Custom Tactical Faction Spike

This is a disposable Dynamic Conquest test pack for proving custom tactical faction IDs on top of the modern stack.

## Corrected wiring

The spike now owns the crash-sensitive Conquest registration surfaces while it is enabled:

| Surface | #201 behavior |
|---|---|
| `mod.info` | Standalone development mod, loaded last |
| `campaign_capture_the_flag.set` | Dedicated CTF copied from the known-working modern/custom compatibility pattern |
| `alliances_goc_201.inc` | Only `goc_usa` and `goc_fra` |
| `values.set` | Only the two GOC matchup directions in the verified Code:X region keys |
| `roster_conquest.set` | `settings.set` + `inf_nato.set` + GOC inf/unit files |
| `inf_goc_*.set` | Reuses existing Code:X NATO breeds and their infantry defines |
| `units_goc_*.set` | Minimal player-facing test squads |
| `conquest.goc_*.lua` | Uses the working `Repeat`/`Units`/`priority` purchase schema |
| `conquest.lua` | AI Overhaul base with GOC nationMap entries |
| army IDs | `goc_usa=90`, `goc_fra=91`; deliberately outside the normal low-ID parent range |
| DC art/localization | GOC-specific test assets and army titles |

The earlier 14/15 IDs were removed because low parent-mod IDs can collide. The earlier purchase scripts also used a non-working lower-case schema and were replaced with the same purchase structure used by the working modern/custom compatibility implementation.

## Recommended test mode

Use the standalone pack rather than copying the spike directly over the Gates workshop tree. This isolates #201 from whichever CTF/alliance registry wins inside the normal four-mod stack.

From the Gates-of-Code-X checkout:

```powershell
.\spikes\201-custom-tactical-factions\deploy_standalone.ps1 `
  -GameRoot "E:\Steam\steamapps\common\Call to Arms - Gates of Hell"
```

Then enable, in this order:

1. West-81
2. Code-X
3. Code:X AI Overhaul
4. Gates of Code:X
5. **GOC 201 Custom Faction Spike**

Disable GaW, MW, UFO Conquest, and other Conquest replacement packs for this test. Fully restart GoH after applying the mod list.

First acceptance checkpoint: opening Dynamic Conquest and creating `goc_usa` vs `goc_fra` must succeed. Only after that should recruitment/research, defender placement, and AI purchasing be judged.

Remove the standalone test mod with:

```powershell
.\spikes\201-custom-tactical-factions\deploy_standalone.ps1 `
  -GameRoot "E:\Steam\steamapps\common\Call to Arms - Gates of Hell" `
  -Remove
```

`deploy.ps1` remains available only for the older direct-to-Gates overlay experiment and should not be used for the next diagnostic run.
