# Task 4 implementation report

## Result

PASS at implementation commit `fac1eb7bcfb7e3c0b75fa086506aa56b784b47a9`.

Task 4 implements only the atomic deterministic raw-Earth3-P2-to-P3 migration and its minimal load/position validation hooks. It does not switch production scenario construction, implement P3 gameplay, push, merge, rebase, or begin Task 5.

## Authority and boundary

- Governing issue: #176.
- Owner approval: issue #141 comment `5234226059`.
- Authorized base: `d16e7b145db82180d628bc9c0a636ebbab51db3c`.
- Proposal commit: `1c51766f4c099d3307db70cffec815772b314d21`.
- Approved allowlist SHA-256: `08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965`.
- Rollback batch: `p3-batch-001`.
- Reviewed Task 3 head: `22f2896271db4b7135d1e12c884a948aa507af0d`.

Authority classes remain separate: frozen P1/P2 repository authority is validated without mutation; the P3 authority/graph is exact-byte authenticated; migration provenance is immutable metadata; formation positions remain mutable campaign state after the one authorized initialization.

## Implementation

- `migrate_earth3_p2_to_p3` validates raw P2 state, authenticates the fixed P3 inputs, plans all eleven placements, deep-copies the source, installs the closed P3 marker/path/migration record and exact anchors, validates the replacement, and returns it atomically.
- Authentication and placement planning complete before the source is copied or any replacement field is changed.
- Raw P2 remains strict when no P3 marker is present. P3 migration provenance without the marker is a rejected downgrade.
- The separate P3 extension validator authenticates its graph internally and accepts no caller-supplied graph or allowlist trust context.
- Authenticated P3 position handling is validation-only: missing, unknown, malformed, or graph-inconsistent positions fail instead of being repaired. Legacy non-Earth3 position hydration is unchanged.
- Raw P2 loads invoke migration before generic operational normalization. Duplicate serialized formation/position records are rejected during JSON parsing. Save JSON keys are canonicalized for mapping-order-independent bytes.
- The P2 integrity projection keeps every frozen field check. Its only P3 branch expects the exact fixed P3 graph path when the P3 marker exists; raw P2 remains pinned to `operational_graph=None`.

## TDD evidence

Initial RED:

```text
pytest -q tests/test_earth3_p3_migration.py
ImportError: cannot import name 'migrate_earth3_p2_to_p3'
```

First focused GREEN:

```text
11 passed in 148.04s
```

The added marker-downgrade regression was independently observed RED:

```text
1 failed, 1 passed in 14.80s
Failed: DID NOT RAISE Earth3BootstrapError
```

After the narrow downgrade guard, the exact affected contract subset passed:

```text
4 passed in 38.51s
```

That subset covered exact mutation scope/anchors, post-authentication state rejection with source immutability, marker downgrade rejection, and idempotent preservation of an evolved on-edge P3 position.

## Compatibility and closeout evidence

Raw P2 authority/identity plus legacy S2 positions:

```text
python -m pytest -q \
  tests/test_p2_earth3_campaign_bootstrap.py \
  tests/test_p2_identity_downgrade_guard.py \
  tests/test_p2_independent_audit_corrections.py \
  tests/test_p2_catalog_provenance_corrections.py \
  tests/test_operational_s2_positions.py

86 passed, 2 skipped, 17 subtests passed in 245.58s
```

Frozen-file audit:

```text
pytest -q tests/test_earth3_p3_authority.py::test_frozen_p1_p2_and_proposal_bytes_match_the_authorized_base
1 passed in 0.05s
```

`py_compile` completed with exit code 0 for every changed Python source and the new migration test. `git diff --check` completed with exit code 0. The Task 4 diff contains no changes under `config/earth3`, the Earth3 Godot asset root, `src/gates_of_codex/data/earth3_v1`, or the approved proposal inventory.

## Changed files at implementation commit

- `src/gates_of_codex/earth3_bootstrap.py`
- `src/gates_of_codex/earth3_operational.py`
- `src/gates_of_codex/operational_position.py`
- `src/gates_of_codex/p2_integrity.py`
- `src/gates_of_codex/state_io.py`
- `tests/test_earth3_p3_migration.py`

`p2_integrity.py` was the one necessary file beyond the plan's expected list: the package-level campaign validator otherwise rejected the authenticated P3 fixed graph path before the separate extension validator could run. The change is conditional on P3 marker presence and preserves the raw-P2 exact projection.

## Stop point and residual evidence boundary

The owner stop boundary arrived during compatibility verification. The already-running matrix was allowed to finish, followed only by frozen-file, compile, diff, scope, commit, and report work. No Task 5 or broader full-suite run was started. Ignored Python `__pycache__` directories exist from test/compile execution; no tracked or untracked implementation files remain outside the two Task 4 commits after this report is committed.
