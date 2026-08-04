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
10. Migration is **fully state-idempotent**: after the first successful migration, repeated `ensure_strategic_formations` / load / save does not change `state.to_dict()`.
11. Dangling commander IDs are cleared **only** while migrating legacy pre-schema-6 saves. Schema 6+ leaves invalid references for validation to reject.
12. Until PR2 adds formation-level map selection, the existing **battalion move command temporarily acts as a formation move**: all members of the strategic formation co-locate with the acting battalion.

## Scope note vs PR #57

PR #61 is stacked on `feat/stack-panel` (PR #57). This PR also repairs a missing PR #57 dependency by wiring `build_stack_presentations()` into `frontend.py` (`stack_presentations`, `battalion_presentations`, per-battalion `presentation`). That wiring is required for PR #57’s own tests/UI contracts and is documented here as a foundation repair, not formation gameplay.

## Dependency

Branch bases on `feat/stack-panel` (PR #57) battalion stack presentation foundations.
