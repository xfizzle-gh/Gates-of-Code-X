# Strategic formation schema (PR1 / issue #58)

## Naming

| Type | Meaning |
|------|---------|
| `Formation` | Existing TOE / national identity template (`state.formations`) |
| `StrategicFormation` | On-map force container (`state.strategic_formations`) — designer “formation” |
| `Battalion` | Authoritative roster + tactical unit |
| `Commander` | Optional; may be empty on migrated saves |

## Assumptions

1. Old campaigns have **no** authoritative commanders. Migration never invents commander records.
2. Frontend may show **Unassigned Commander** as presentation-only text.
3. `StrategicFormation.province_id` is location authority; battalion provinces are synchronized to it.
4. Each battalion belongs to exactly one strategic formation.
5. Migrated independent formation IDs are deterministic: `sf-{battalion_id}`.
6. Echelon enum is schema-only: `battalion | regiment | brigade | division` — no capacity/cost balance yet.
7. Pending/archived battles are not rewritten in PR1 (no tactical-assignment fields).
8. Campaign `schema_version` becomes **≥ 6** after migration.
9. Frontend snapshot schema becomes **8** and adds `strategic_formations` + `commanders`.

## Dependency

Branch bases on `feat/stack-panel` (PR #57) battalion stack presentation foundations.
