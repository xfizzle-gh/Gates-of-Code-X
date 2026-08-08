# National faction wiring

Gates of Code:X treats a strategic country as separate from the tactical side serialized into Gates of Hell.

The tactical export contract remains restricted to:

```text
nato
ukr
rusa
prc
```

A country such as France, Poland, Belarus, or North Korea owns its own roster and research tree in the strategic layer, then resolves to one supported tactical side when a battle is materialized.

## Source policy

1. Code:X is authoritative for modern breeds, units, vehicles, weapons, portraits, and native research branches.
2. West81 is an explicit legacy and reserve source. It is not silently promoted to modern national coverage.
3. Code:X AI Overhaul and Gates of Code:X are higher-priority overlays in the configured stack.
4. This repository references upstream IDs. It does not copy upstream models, textures, portraits, sounds, weapons, or entity definitions.
5. Existing upstream squad and unit IDs are retained. New `goc_*` wrapper IDs are used only where Code:X provides a complete breed family but no purchase-ready squad wrapper.

## Implemented actors

### Playable sovereign or territorial actors

| Actor | Roster class | Tactical side |
|---|---|---|
| United States | Full national | `nato` |
| United Kingdom | Full national | `nato` |
| Germany | Full national | `nato` |
| France | National hybrid | `nato` |
| Poland | National hybrid | `nato` |
| Italy | National hybrid | `nato` |
| Finland | National hybrid | `nato` |
| Sweden | National hybrid | `nato` |
| Netherlands | National hybrid | `nato` |
| Canada | National hybrid | `nato` |
| Norway | NATO coalition fallback | `nato` |
| Denmark | NATO coalition fallback | `nato` |
| Spain | NATO coalition fallback | `nato` |
| Turkey | NATO coalition fallback | `nato` |
| Russia | Full national | `rusa` |
| Ukraine | Full national | `ukr` |
| People's Republic of China | Full national | `prc` |
| North Korea | Eastern hybrid | `rusa` |
| Donbas Forces | Separatist hybrid | `rusa` |
| Belarus | Eastern hybrid | `rusa` |
| Serbia | Balkan/Eastern hybrid | `rusa` |

### Non-state and hosted actors

| Actor | Host | Tactical side |
|---|---|---|
| International Legion for the Defence of Ukraine | Ukraine | `ukr` |
| KPA Expeditionary Corps | Russia | `rusa` |
| Wagner / Russian PMC Forces | Russia | `rusa` |

## National roster boundaries

The bundled manifest deliberately separates mixed Code:X containers:

- NATO is split into US, British, German, French, Polish, Italian, Nordic, Dutch, Canadian, and coalition-fallback components.
- RUSA is split into Russian regular forces, KPA, Donbas, Wagner, Serbian volunteers, and Russian-compatible modernization pools.
- Ukraine keeps its native formation trees and adds an International Legion subtree from the existing `nato_*` and `ildu` breeds.
- The Code:X `2022rusldpr` branch becomes the native Donbas progression.
- The Code:X `kor_*` squads become both a standalone North Korean infantry core and a Russian-hosted expeditionary component.

## Research generation

Three research modes are supported:

- `native`: preserve audited upstream branch structure and costs.
- `hybrid`: preserve native branches, then generate actor-scoped nodes for additional national, legacy, or auxiliary units.
- `generated`: build deterministic category and tier nodes from the actor's resolved roster.

Every emitted key is actor-scoped. A French unlock cannot unlock a German or generic NATO unit merely because both export as `nato`.

Filtered source branches remain valid. When a multinational stepping-stone is removed, the compiler reparents downstream included nodes to the nearest included ancestor.

## Compile and audit

```powershell
.\.venv\Scripts\gates-of-codex-factions.exe `
  --stack-config .\config\mod-stack.windows.json `
  --output .\docs\audits\resolved-factions.json `
  --summary .\docs\audits\resolved-factions.md
```

The command exits nonzero when a required source branch, unit, breed, roster category, or research prerequisite fails resolution.

The checked-in snapshot report was generated against:

```text
codex_faction_audit_20260807_231259.zip
gates_faction_source_audit_20260807_230128.zip
```

The live stack must be regenerated before final merge acceptance because Code:X and its overlays can change independently of this repository.

## Editable authority

```text
src/gates_of_codex/data/faction_wiring.json
src/gates_of_codex/data/faction_components.json
src/gates_of_codex/data/faction_actors.json
```

Resolved JSON and Markdown reports are generated artifacts and must not be hand-edited.
