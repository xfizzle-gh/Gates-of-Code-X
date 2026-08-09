# Expanded Nations projection matrix

## Evidence status: invalidated

The complete schema-3 matrix committed at `0926d347138738f75205237b75fef1145383d77f`
is no longer authoritative.

Native Serbia acceptance proved four runtime contracts that the prior matrix did
not validate:

1. a RUSA actor must replace the inherited SOV/CSA purchase family rather than
   retaining those legacy cards as opponents;
2. Soviet-pattern equipment exported to RUSA must use the native 2022s RUSA
   crew contract rather than resolving `mp/rusa/era1960/*` breeds;
3. actor-created squad IDs require localized names and four native portrait
   variants;
4. native research output must contain purchase nodes rather than opaque
   generated technology IDs.

The correction changes opponent rows, actor-unit bytes, research node counts,
managed presentation files, and projection signatures. No actor row or
signature from the previous matrix remains authoritative.

After the correction receives exact-head review and CI acceptance, regenerate
all 21 actors from Core mode against the audited five-layer Workshop stack:

```powershell
py -3.11 -m gates_of_codex.expanded_nations_cli matrix `
  --stack-config .\config\mod-stack.windows.json `
  --gates-root . `
  --source-head (git rev-parse HEAD).Trim() `
  --json-output .\docs\audits\expanded-nations-projection-signatures.json `
  --markdown-output .\docs\audits\expanded-nations-projection-matrix.md
```

Native Serbia testing remains blocked until the regenerated matrix is committed
and independently accepted.
