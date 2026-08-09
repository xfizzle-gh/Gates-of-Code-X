# Gates of CodeX repository skills

These repo-scoped Agent Skills are discovered automatically by Codex from `.agents/skills` when work starts anywhere inside this repository.

| Skill | Use it for |
|---|---|
| `gates-pr-gate` | Issue implementation, branches/worktrees, draft PRs, exact-head CI and review, and guarded merges |
| `gates-native-acceptance` | Real Windows, Godot, Steam, Gates of Hell, installer, wrapper, actor, and tactical-handoff acceptance |
| `gates-authority-change` | Earth3, stable IDs, exact-byte scenario data, schemas, provenance, deterministic generators, and fail-closed loaders |

## Invocation

Codex can select a skill automatically from its description. Explicit invocation is preferred for high-risk work:

```text
$gates-pr-gate implement issue #...
$gates-native-acceptance prepare the acceptance record for issue #...
$gates-authority-change review this map/scenario/provenance change
```

Several skills may apply to one task. For example, an Earth3 implementation normally uses `gates-authority-change` for the technical boundary and `gates-pr-gate` for publication and review. A native Gates of Hell test then uses `gates-native-acceptance` as a separate evidence-only phase.

## Boundaries

- Skills guide work but do not override the newest explicit owner ruling or governing issue.
- They do not grant permission to merge, mark a draft ready, begin the next ordered phase, weaken validation, or edit frozen authority.
- Native acceptance remains distinct from fixtures, repository tests, CI, and synthetic integration evidence.
- Project-specific content-authoring skills from other repositories must not be applied to Gates of CodeX unless they are explicitly adapted to this repository's schemas and terminology.
