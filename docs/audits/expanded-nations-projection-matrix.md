# Expanded Nations projection matrix

## Evidence status: invalidated

The complete schema-3 matrix committed at
`891bfae083e2b6b39986c2c8fbf09bf35e945e2e` is no longer authoritative.

Native Serbia testing at that exact head proved that the generated research tree
could display all 18 purchase IDs while the Army recruitment screen displayed
only the 15 block-form equipment entries. The three block-form virtual Serbian
squads were silently omitted. The session log contained no Serbian breed, macro,
or purchase exception.

Canonical Code:X infantry purchases use top-level `squad_with*` macros. Their
`name(...)` call stores the base ID and the engine derives the effective purchase
ID as `name(side)`. The projector had instead emitted complete suffixed IDs inside
block wrappers for virtual squads and inside `name(...)` for upstream macro-form
squads.

The correction therefore:

1. converts all 14 committed virtual squads to top-level native macros;
2. preserves base `name(...)` values for every projected macro-form squad;
3. authenticates each macro's effective `name(side)` ID against the manifest and
   research purchase ID;
4. adds regression coverage for committed virtual wrappers, Serbia projection,
   upstream macro projection, and verification semantics.

This changes generated actor-unit bytes and projection signatures for every actor
that contains macro-form squads. No actor row or signature from the previous
matrix remains authoritative.

After exact-head CI and independent review accept the correction, regenerate all
21 actors from Core mode against the audited five-layer Workshop stack:

```powershell
py -3.11 -m gates_of_codex.expanded_nations_cli matrix `
  --stack-config .\config\mod-stack.windows.json `
  --gates-root . `
  --source-head (git rev-parse HEAD).Trim() `
  --json-output .\docs\audits\expanded-nations-projection-signatures.json `
  --markdown-output .\docs\audits\expanded-nations-projection-matrix.md
```

Native Serbia testing remains blocked until the regenerated matrix is committed
and independently accepted. DPRK testing and merge remain blocked.
