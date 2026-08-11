# P3 Earth3 Operational Corridors Design

## Scope and approval gate

P3 installs only the first owner-reviewed Earth3 land-corridor batch needed by
the merged P2 opening state. The exact proposal is recorded in
`docs/audits/p3-first-corridor-route-proposal.md`; its companion JSON contains
the complete proposed 65-edge allowlist and all 8,690 remaining disabled land
candidate IDs. Both files are review evidence only. No production edge may be
enabled until issue #141 contains explicit owner approval for that exact
allowlist, endpoints, bidirectional flags, movement costs, supply flags, and
rollback batch.

The implementation starts at merge commit
`d16e7b145db82180d628bc9c0a636ebbab51db3c`, preserves accepted P2 head
`4f2eee80256b9a4c5388c88b2d2e357b883b9e6c`, and stops before P4.

## Route shape

The proposed graph uses 64 existing province-anchor node IDs and 65 existing
stable corridor edge IDs. It joins Berlin, Tallinn, Riga, Vilnius, Kyiv, Odesa,
Kherson, Zaporizhzhia, Donetsk, Luhansk, and Rostov without deriving runtime
IDs from insertion order, coordinate searches, or geometry scans.

The graph contains a Baltic-to-Ukraine spine, a two-arm Kyiv–Zaporizhzhia loop,
and a two-arm Donetsk–Rostov loop. Those loops provide meaningful route choice,
alternate AI paths, supply redundancy, interception opportunities, and retreat
destinations without enabling the rest of Earth3. The Zaporizhzhia–Donetsk arm
is the deliberate opening contact and battle approach.

Every proposed edge is bidirectional, costs exactly 1,000 fixed-point movement
units, is explicitly supply eligible, and belongs to rollback batch
`p3-batch-001`. Any change to an ID, endpoint, direction, cost, supply flag, or
batch requires new owner review.

## Separate authenticated authority

P3 route authority remains separate from the frozen P1 polygon authority and
the fixed P2 scenario bundle. The production graph asset contains only the
approved nodes, sites, and enabled edges. A separate versioned authority record
pins:

- map and batch identity;
- the approving issue-comment ID;
- exact graph and allowlist digests;
- the ordered enabled edge IDs;
- exact endpoint, direction, cost, and supply records;
- the frozen P1 dataset and topology identities;
- the rollback batch.

Earth3 graph loading authenticates captured bytes before exposing any graph to
movement, AI, supply, contact, interception, retreat, or save migration. Unknown,
missing, duplicate, malformed, substituted, reversed, endpoint-mismatched, or
extra edges fail closed. Ordinary `candidate` edges remain non-traversable, and
the runtime never builds a route graph by scanning polygon neighbors.

## P2-to-P3 state transition

The immutable P2 bootstrap provenance remains intact, including its statement
that P2 itself supplied no movement or connectivity authority. P3 adds a
separate authenticated operational-authority record and enables maneuver only
when that record and the graph agree exactly.

New Earth3 campaigns install the authenticated P3 record, resolve all eleven
formation provinces to their existing stable anchor nodes, and retain each
formation's canonical P2 `province_id`. A P2 save without positions migrates
deterministically only after the same P3 authority authenticates. Missing or
mismatched P3 assets abort migration without altering positions, schema, supply,
or saved campaign bytes.

The legacy `CampaignEngine.move_or_attack()` polygon-neighbor path remains
blocked for Earth3 P2/P3 campaigns. Player and AI maneuver use only operational
orders over the authenticated graph, so structural province adjacency can never
act as a fallback.

## Gameplay behavior

The approved graph must drive the existing S3–S10 systems:

- movement orders from every starting formation;
- deterministic S7 AI routes toward the merged P2 objectives;
- S8 supply over edges whose explicit `supply_capable` flag is true;
- S4/S6 contact and swept interception on the opening approach;
- S9 retreat to legal adjacent nodes without one-way traps;
- pending-battle generation on a deliberate Zaporizhzhia–Donetsk approach.

P3 route-node access and supply behavior are operational state, not polygon
ownership. The implementation must not expand P2 territorial ownership or make
outside provinces scenario-actionable. Disabled candidate IDs are absent from
all player, AI, supply, contact, interception, and retreat paths.

## Save/load and determinism

Saved P3 state persists exact authority identity, positions, route IDs, progress,
move orders, contact state, and retreat origins. Loading re-authenticates the
installed graph before accepting these fields. Repeated builds, reordered input
records, and P2 migration produce byte-stable authority and campaign state.

## Verification

Tests are authored and executed test-first. Focused P3 coverage proves the exact
allowlist, edge records, fail-closed substitutions, all eleven starting
positions, route choice, AI objectives, supply, no polygon fallback, contact,
interception, battle creation, retreat, disabled-edge exclusion, round trips,
P2 migration, and insertion-order stability. Static byte comparisons prove the
four frozen P1 authority files and eleven fixed P2 bundle files remain identical
to the exact base. The relevant existing S3–S10 suites and the full repository
suite run before publication.

## Exclusions

P3 does not mass-enable candidates, edit Earth3 geometry or province authority,
redesign P2 content, add the P4 launcher, implement P5/#166 handoff, perform P6
packaging, add S11 PR C Fog presentation, or touch OpenGS or unrelated factions
and geography.
