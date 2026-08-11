# P3 first playable corridor verification

## Status

P3 implementation is complete on draft PR #187 and remains **unmerged** pending a fresh independent exact-head audit. P4 has not started.

This report intentionally does not modify `docs/audits/p3-first-corridor-route-proposal.md`. That proposal is an authenticated P3 input whose exact raw bytes are pinned by the production loader; editing it after approval would invalidate the authority chain.

## Governing authority

- Parent P0 issue: #176
- P3 route issue: #141
- Owner approval: issue #141 comment `5234226059`
- Authorized P3 base: `d16e7b145db82180d628bc9c0a636ebbab51db3c`
- Accepted P2 head: `4f2eee80256b9a4c5388c88b2d2e357b883b9e6c`
- Exact proposal commit: `1c51766f4c099d3307db70cffec815772b314d21`
- Batch: `earth3-p3-first-playable-corridors-v1`
- Rollback batch: `p3-batch-001`
- Approved stable edges: exactly 65
- Approved operational nodes: exactly 64
- Remaining disabled land candidates: exactly 8,690
- Allowlist SHA-256: `08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965`
- Disabled-candidate SHA-256: `a7d52fbe2abd1d9b32349ad42e8e00876e3f4727411f58a5e640a3b8a75bbdcf`
- Complete candidate-ID SHA-256: `2385c49e1ddbb851f0c2d16bbcd7f112adce57b8b9aeddcab76850ab71794bad`

No edge ID, endpoint, direction, movement cost, supply flag, or rollback-batch substitution was made after owner approval.

## Frozen authority identities

The P3 loader continues to authenticate the previously frozen P1/P2 inputs before exposing the graph:

- P1 production dataset logical SHA-256: `8ae59bd89419a368fe9131ef7c50d94a7f1cafacd1cfae44362ac9b5d9decced`
- P1 production dataset raw SHA-256: `4aadab4b5106bbfa4c2d37e8173c3d1675f35a448cbd7f32a8b871c464ce1b84`
- P1 embedded dataset SHA-256: `8ae59c33da5094b722b1ffad61d2862cdd4805369d74d6c6298425735982a241`
- P1 structural topology: 10,249 unique undirected edges
- P2 `sites.json` raw SHA-256: `7fbfa2bd7fd40f97f69b5b515bb77cb7145d1299153a2263d79443692f4c2ef3`
- P3 authority raw SHA-256: `3b3330eb90351c7751d3a582c3f4c177796e297314c6e8f5497f516926fb200f`
- P3 operational graph raw SHA-256: `c2d6ab30bfd3e2e15404242144831c5dd6ba284cd132e605e2544be8524d72cf`

The deterministic builder and Task 2 review previously reproduced the same 64-node / 65-edge graph bytes from the pinned proposal, frozen Earth3 dataset, and fixed P2 sites input. Raw P2 cannot discover the committed P3 graph through the legacy loader path.

## Task 4 correction: fail closed before legacy formation repair

The owner review of checkpoint head `327fe0fb95d08fa4aa3451606add5f09a51294eb` found that `campaign_from_dict()` invoked the generic strategic-formation normalizer before P3 migration/authentication. That legacy normalizer could reconstruct a missing formation or append missing membership before the strict P2/P3 authority checks ran.

The correction makes `ensure_strategic_formations()` validation-only for Earth3 P2/P3 campaigns. It now validates the authored Earth3 campaign state before any legacy normalization and returns without repair, summary refresh, schema rewrite, location synchronization, or migration-record insertion. Genuine non-Earth3 legacy campaigns retain the original migration behavior.

Adversarial coverage removes the canonical `sf_usa_tallinn` formation while retaining its battalion reference and separately removes the battalion from its authoritative formation membership. Both must fail without mutating the supplied payload.

## Production P3 activation

Production `earth3_v1` construction now has one explicit P2-to-P3 wrapper:

1. `build_earth3_v1_campaign()` constructs the unchanged fixed P2 scenario.
2. `migrate_earth3_p2_to_p3()` authenticates P3 authority and atomically installs the exact eleven starting anchors.
3. P3 site-control rows initialize after authentication.
4. Authored site owner actor IDs are resolved through the authenticated strategic-actor runtime to their tactical faction for mutable control state.

Direct calls to the P2 builder remain P2-only with no graph and maneuver disabled. Production scenario authority declares both the P3 authority record and the fixed P3 graph asset.

## Movement and AI boundary

P3 player and AI movement use only the authenticated operational graph. The legacy `CampaignEngine.move_or_attack()` polygon-neighbor path remains blocked for Earth3.

Authored proof coverage checks:

- every one of the eleven P2 starting formations can issue a legal first hop on an approved edge;
- every starting node can reach all four opening objective nodes (`e3_2794`, `e3_3380`, `e3_0442`, `e3_1937`);
- route finding is insertion-order independent;
- the reviewed Kyiv–Zaporizhzhia loop retains both arms;
- the reviewed Donetsk–Rostov loop retains both arms;
- all 8,690 disabled land-candidate IDs are absent from the runtime graph and cannot be injected as orders;
- polygon adjacency does not synthesize an operational edge.

## Supply boundary

P3 supply continues to require the shared movement edge gate plus explicit `supply_capable` authority. Candidate, disabled, metadata-blocked, and `supply_capable=false` edges remain non-routing.

The P3-specific routing correction permits **unoccupied neutral** approved corridor nodes to relay supply. Hostile-owned nodes and neutral nodes occupied by a hostile formation remain closed. Source nodes themselves still require friendly control.

Authored proof coverage checks:

- Berlin Command and Riga Depot bind as NATO sources;
- Kyiv Command and Odesa Port bind as Ukrainian sources;
- Rostov Depot binds as the Russian source;
- all eleven opening formations receive graph-authoritative supply;
- deterministic repeated and reordered-graph route calculations agree;
- the Zaporizhzhia route contains only authenticated approved, supply-capable edges.

## Contact, interception, battle, and retreat

The deliberate opening approach is the approved three-edge chain:

`e3_1962 ↔ e3_2795 ↔ e3_2796 ↔ e3_3380`

With the Zaporizhzhia and Donetsk opening formations moving toward one another, the first tick places them at `e3_2795` and `e3_2796`. The second tick uses the existing S6 swept-interception path on the shared approved edge and creates exactly one edge-contact battle at canonical progress 500.

Authored proof coverage checks deterministic encounter metadata, no ownership flip merely from battle creation, pending-battle blocking, and graph-authoritative loser retreat after explicit battle resolution.

## Persistence boundary

Persistence coverage uses the production `save_campaign()` / `load_campaign()` path and requires byte-stable second saves after normalization for:

- initial P3 state;
- an active in-transit move order and exact edge progress;
- pending edge-contact battle metadata;
- resolved retreat state;
- operational supply source and route fields.

Additional coverage requires raw P2 migration exactly once, preservation of evolved P3 positions across later loads, fail-closed authority/path/position tampering, and preservation of source file bytes after a failed load.

## Verification evidence levels

### Previously executed and reviewed before takeover

Tasks 1–3 had independent reviews on their exact accepted heads. Task 4 at the Codex stop boundary had locally reported:

- focused migration: `11 passed in 148.04s`;
- affected downgrade/atomicity subset: `4 passed in 38.51s`;
- P2/bootstrap/identity/audit/catalog/S2 compatibility: `86 passed, 2 skipped, 17 subtests passed in 245.58s`;
- frozen-file audit: `1 passed in 0.05s`;
- changed-source `py_compile`, diff, and scope checks passed.

Those results predate the owner-identified Task 4 ordering correction and are not claimed as exact-head evidence for the completed P3 branch.

### Authored after takeover, awaiting exact-head execution at report commit time

The completed branch adds focused P3 coverage in:

- `tests/test_earth3_p3_migration.py`
- `tests/test_earth3_p3_scenario.py`
- `tests/test_earth3_p3_movement.py`
- `tests/test_earth3_p3_supply.py`
- `tests/test_earth3_p3_combat_flow.py`
- `tests/test_earth3_p3_persistence.py`

The repository Actions workflow runs the full Python matrix on Ubuntu/Windows Python 3.11/3.13 plus the Godot map job. The final exact-head workflow ID, job IDs, pass/fail totals, and any corrections are recorded in PR #187's final audit handoff because an exact-head run cannot exist until the evidence commit itself is published.

## Explicit exclusions and stop point

P3 does not:

- change the approved 65-edge batch;
- enable any of the 8,690 disabled land candidates;
- derive runtime routing from polygon neighbors;
- edit frozen Earth3 geometry or P1/P2 authority bytes;
- redesign P2 ownership, actor assignments, starting forces, objectives, or sites;
- begin the P4 launcher, P5 handoff, P6 packaging, S11 presentation work, or unrelated faction/geography work.

PR #187 must remain draft and unmerged until a separate independent reviewer audits the final exact head and its exact-head CI evidence.
