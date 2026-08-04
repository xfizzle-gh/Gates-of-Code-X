# Unit-pool audit artifacts

Issue #46 adds a deterministic audit of the ordered Code:X resource stack. The command preserves tactical side, source-layer priority, national inference evidence, West81 legacy status, bridge materialization, human loadouts, and candidate actor capability gaps.

Run from the repository root on the owner machine:

```powershell
.\.venv\Scripts\gates-of-codex.exe audit-unit-pools `
  --stack-config .\config\mod-stack.windows.json `
  --output .\docs\audits\unit-pools.json `
  --summary .\docs\audits\unit-pools-summary.md `
  --unclassified .\docs\audits\unclassified-unit-tokens.json
```

Expected committed outputs:

- `unit-pools.json`
- `unit-pools-summary.md`
- `unclassified-unit-tokens.json`

The output is deterministic for an unchanged ordered stack. It contains no timestamps or machine-specific absolute source paths. The stack signature covers ordered runtime definitions, while every row records source-layer priority and relative source files.

## Classification boundaries

- `tactical_side` remains one of the GoH-compatible values such as `nato`, `ukr`, `rusa`, or `prc`.
- `inferred_nation` is audit evidence only. Runtime campaign logic must not repeat substring inference.
- Conflicting evidence remains `unknown` with the conflicting candidates listed.
- `content_role=legacy_reserve` marks West81 content and does not count as modern Code:X national coverage.
- Human loadout completeness requires a resolved breed with both an emittable primary weapon and ammunition.
- Vehicle materialization and human loadout completeness are reported separately.

## Current environment limitation

The connected execution environment used to implement the scanner does not mount the owner’s Workshop directories. Tests generate a layered fixture containing Code:X, West81, PRC, KPA, conflicting evidence, incomplete loadouts, and a Gates overlay. The three authoritative repository artifacts must be generated from the owner’s exact local stack before issue #46 can be closed.
