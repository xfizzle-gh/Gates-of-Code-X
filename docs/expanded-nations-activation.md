# Expanded Nations activation

Expanded Nations projects one selected strategic actor into the native Gates of Hell Conquest roster and research files. Core Code:X remains the default whenever no projection is active.

## Modes

### Core Code:X

Core mode inherits the canonical Code:X roster and research files. Gates does not add a final-layer `roster_conquest.set` or `unit_research_<side>.set` in this mode.

### Expanded Nations

Expanded mode compiles the installed five-layer stack, selects one playable actor, and generates four managed final-layer files:

- `resource/set/multiplayer/units/roster_conquest.set`
- `resource/set/multiplayer/units/conquest/goc_active_actor_units.set`
- `resource/set/multiplayer/units/conquest/goc_opponent_units.set`
- `resource/set/dynamic_campaign/unit_research_<tactical-side>.set`

The selected actor replaces only its own tactical side. The filtered opponent file preserves effective Core purchase definitions for every non-selected tactical side. Broad source rosters are never directly included in Expanded mode, so actors sharing `nato`, `ukr`, `rusa`, or `prc` cannot leak into the selected actor's purchase or research content.

Hosted actors cannot be selected independently. Purchase IDs are canonicalized to the resolved actor unit IDs, and generated research must unlock exactly those same IDs.

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

## Generate the exact-stack projection matrix

Matrix generation must begin in Core mode. It activates and semantically verifies every playable actor, restores Core after each actor, writes exact-head JSON and Markdown evidence, and confirms no managed projection remains afterward.

```powershell
.\tools\activate_expanded_nation.ps1 -Core

py -3.11 -m gates_of_codex.expanded_nations_cli matrix `
  --stack-config .\config\mod-stack.windows.json `
  --gates-root . `
  --source-head (git rev-parse HEAD).Trim() `
  --json-output .\docs\audits\expanded-nations-projection-signatures.json `
  --markdown-output .\docs\audits\expanded-nations-projection-matrix.md
```

The command refuses to run over an active projection, unmanaged generated-path occupants, a non-final Gates root, or an invalid source stack. A failed actor run attempts Core restoration before returning the failure.

## Safety and determinism

Activation fails closed when:

- the resolved compiler reports errors or warnings;
- the actor is unknown, duplicated, hosted, or non-playable;
- actor units and research unlocks do not match exactly;
- a purchase source definition is missing, malformed, ambiguous, or cannot be canonicalized;
- any new output target is occupied by a file not owned by the current verified activation manifest;
- an existing managed projection was edited after activation;
- generated actor IDs, opponent-side filtering, or research semantics disagree with the manifest;
- generated research contains duplicate IDs, missing prerequisites, foreign actor keys, foreign unlocks, or unexpected untagged definitions;
- the supplied Gates root is not the final stack layer.

Generated artifacts are semantically verified before installation and again after commit inside the rollback boundary. Switching actors restores the entire prior projection after output replacement, stale deletion, manifest replacement, or post-install verification failure.

Core restoration is recoverable. Managed files and the activation manifest are backed up before deletion. A failed or interrupted restoration reconstructs the verified active projection on the next activation, verification, or Core-restoration command.

Repeated activation from identical stack inputs produces byte-identical roster, actor-unit, opponent-unit, and research files.
