# Expanded Nations projection matrix

## Evidence status: invalidated

The previously tracked 21-actor matrix was generated before exact head
`0f739d0c0b6134c8fafb4c0ac5e60623b983b148` removed six Soviet infantry
purchases from `soviet_legacy_core`.

That component is used by Belarus, Donbas, DPRK, and Serbia. Their prior actor
counts, research counts, and projection signatures are therefore stale. The old
matrix has been removed rather than partially preserving mixed-head evidence.
No actor count or signature in this document is currently authoritative.

Regenerate the complete matrix from Core mode against the exact installed
five-layer Workshop stack:

```powershell
py -3.11 -m gates_of_codex.expanded_nations_cli matrix `
  --stack-config .\config\mod-stack.windows.json `
  --gates-root . `
  --source-head (git rev-parse HEAD).Trim() `
  --json-output .\docs\audits\expanded-nations-projection-signatures.json `
  --markdown-output .\docs\audits\expanded-nations-projection-matrix.md
```

The command activates and semantically verifies every playable actor, restores
Core after each actor, records exact actor/opponent/research counts and managed
file hashes, and leaves the installation in Core mode. Native gameplay
acceptance remains separate.
