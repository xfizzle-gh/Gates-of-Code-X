# P3 SDD Progress

| Task | Implementer | Implementation | Reviewer | Review | Commit / evidence |
| --- | --- | --- | --- | --- | --- |
| 1. Frozen inputs and red authority tests | Codex subagent | complete | independent Codex reviewer | PASS | `1eb0221bcfeb634b1c648426b8a165e00f41ee17` |
| 2. Authority record and graph builder | Codex subagent | complete after P1 fix | independent Codex reviewer | PASS at `5ef42fc` | `41adeb9`, `5ef42fccc29ed46fc46b37b2d128da99176764bb` |
| 3. Schema and authenticated loader | Codex subagent | complete after 4-finding fix | independent Codex reviewer | PASS at `22f2896` | `fa8a35c`, `22f2896271db4b7135d1e12c884a948aa507af0d` |
| 4. Atomic P2-to-P3 migration | Codex + ChatGPT correction | complete after pre-auth repair finding | ChatGPT self-review | corrected; external audit pending | `fac1eb7bcfb7e3c0b75fa086506aa56b784b47a9`, `744c8c9c51d7c707b445aeb49e92892a8d74a0c5`, `ddb6161e357d64c392eecb1e182ce38af41cf321` |
| 5. Production scenario wrapper | ChatGPT | complete | ChatGPT self-review | external audit pending | `eee192491ce1eb1344b234cbdd471dff437d4707`, `cf1cc5fc505f7de8f4d71fbed8c8141660615b11` |
| 6. Movement, AI, objectives | ChatGPT | complete proof coverage | ChatGPT self-review | external audit pending | `8c00eecbe75bbd0fd4c36dd67ad611813a9d08de` |
| 7. Supply | ChatGPT | complete after neutral-transit and actor-control corrections | ChatGPT self-review | external audit pending | `ba6c3a7ba8117deff62e584756540c865c0a8180`, `9a46cc40e51c29df0e9a1c2085cc89a92695708b`, `ab3a95401b119e396acef8f84822a05a7dc31b3a`, `a3e4c9735fe4f33440f6429d2d6b772bccaaeabe` |
| 8. Contact, interception, battle, retreat | ChatGPT | complete proof coverage | ChatGPT self-review | external audit pending | `b7197183bcf65b8817bf289075385f37d152d084`, final test correction `fcfae9a620848e9c7772bc6b945c8d34bcd1aa84` |
| 9. Persistence | ChatGPT | complete proof coverage | ChatGPT self-review | external audit pending | `cc8aa3a84bd50f38b3be9bbe5819695e492f2c3a` |
| 10. Verification evidence | ChatGPT | complete | ChatGPT self-review | exact-head CI pending | `4ce581d1032d831d5649481bfb4b977e7b4d92a8` |
| 11. Independent branch review | external reviewer selected by owner | not started | external | PENDING | pending |
| 12. Draft PR and exact-head review request | ChatGPT | draft PR exists; final handoff pending CI | external audit required | PENDING | PR #187 |

## Invariants

- Authorized base: `d16e7b145db82180d628bc9c0a636ebbab51db3c`
- Proposal: `1c51766f4c099d3307db70cffec815772b314d21`
- Approval: issue #141 comment `5234226059`
- Allowlist: 65 IDs; SHA-256 `08901e371baa34688429afc9a6f06cc6361da13eac6eb9907901b47c9c233965`
- Disabled land candidates: 8,690
- Rollback batch: `p3-batch-001`
- Frozen proposal bytes remain unchanged because they are authenticated runtime input.
- Do not merge or rebase `main`; do not begin P4.

## Takeover completion handoff — 2026-08-09

- Codex stop head: `327fe0fb95d08fa4aa3451606add5f09a51294eb`.
- ChatGPT identified and corrected the Task 4 pre-auth formation-repair path before beginning later tasks.
- Production Earth3 now activates P3 only through the authenticated atomic P2-to-P3 wrapper; direct P2 construction remains frozen and P2-only.
- Player/AI proof coverage uses only the exact 65-edge graph and exhaustively checks that all 8,690 disabled land candidates are absent.
- Supply now permits unoccupied-neutral approved corridor transit while rejecting hostile-owned/hostile-occupied transit; authored P2 actor site ownership resolves to tactical faction only in mutable control state.
- The reviewed Zaporizhzhia–Donetsk three-edge arm is exercised through actual S6 swept interception, one pending battle, and graph-authoritative retreat.
- Persistence proof coverage includes initial, in-transit, pending-battle, retreat, supply, raw-P2 one-time migration, and tamper failure cases.
- Verification report: `docs/audits/p3-first-corridor-verification.md`, commit `4ce581d1032d831d5649481bfb4b977e7b4d92a8`.
- Earlier Task 4 test counts are historical evidence only; all post-takeover tests remain unclaimed until the final exact-head GitHub Actions run executes.
- Final exact-head CI and the external independent audit remain the only P3 acceptance gates.
- PR #187 remains draft and unmerged. No P4 work was started.
