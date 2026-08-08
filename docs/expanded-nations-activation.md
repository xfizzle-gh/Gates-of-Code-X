# Expanded Nations activation

Expanded Nations projects one selected strategic actor into the native Gates of Hell Conquest roster and research files. Core Code:X remains the default whenever no projection is active.

## Modes

### Core Code:X

Core mode inherits the canonical Code:X roster and research files. Gates does not add a final-layer `roster_conquest.set` or `unit_research_<side>.set` in this mode.

### Expanded Nations

Expanded mode compiles the installed five-layer stack, selects one playable actor, and generates three managed final-layer files:

- `resource/set/multiplayer/units/roster_conquest.set`
- `resource/set/multiplayer/units/conquest/goc_active_actor_units.set`
- `resource/set/dynamic_campaign/unit_research_<tactical-side>.set`

Only the selected actor's resolved units and actor-scoped research graph are projected. Actors that share `nato` or `rusa` do not share projected content. Hosted actors cannot be selected independently.

No upstream Workshop tree is modified. Upstream purchase definitions are read from the installed stack and projected into ignored runtime files under the final Gates layer. Those generated files are not committed or deployed by the tracked-file Workshop deployment script.

## Windows activation

Set or pass the five roots required by `config/mod-stack.windows.json`, then run from the repository root:

```powershell
.\tools\activate_expanded_nation.ps1 -Actor srb
```

This compiles the current stack, activates Serbia, verifies the generated files, and launches Gates of Hell.

Compile and activate without launching:

```powershell
.\tools\activate_expanded_nation.ps1 -Actor dprk -NoLaunch
```

Restore Core Code:X:

```powershell
.\tools\activate_expanded_nation.ps1 -Core
```

List playable actors:

```powershell
py -3.11 -m gates_of_codex.expanded_nations_cli list `
  --stack-config .\config\mod-stack.windows.json
```

Verify the active projection:

```powershell
py -3.11 -m gates_of_codex.expanded_nations_cli verify `
  --gates-root .
```

## Safety and determinism

Activation fails closed when:

- the resolved compiler reports errors or warnings;
- the actor is unknown, duplicated, hosted, or non-playable;
- actor units and research unlocks do not match exactly;
- a source definition is missing or malformed;
- a generated path is already occupied by an unmanaged file;
- an existing managed projection was edited after activation;
- the supplied Gates root is not the final stack layer.

Switching actors is transactional. Stale research files from the previous tactical side are removed only after their hashes are verified. Repeated activation from identical stack inputs produces byte-identical roster, unit, and research files.
