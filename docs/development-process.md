# Development process — CI and merge safety

## Required before merging to `main`

1. Open a PR from an up-to-date branch.
2. Wait for **exact-head** CI on that PR commit to finish **green**.
3. Required checks (do not merge while pending or red):
   - full Python test matrix (ubuntu/windows × supported Python versions)
   - `godot-map`
   - `windows-executable` when the workflow requires it for the change
4. Merge only the green head. Do not merge a red PR because a later hotfix might pass.
5. A subsequent green hotfix PR **does not** satisfy the requirement that the original production PR itself was green at merge time.
6. Agents and humans follow the same rules. Do not bypass branch protection.

## Earth3 production authority

Exact values live in `config/earth3/production_authority.json` and must match:

- `polygon_dataset.json` / `dataset_meta.json` / `map_manifest.json`
- `triangulation_audit.json` (must be regenerated when the province set changes)
- fixtures/snapshots

Do not use approximate gates such as `province_count >= 3000` for production authority.
