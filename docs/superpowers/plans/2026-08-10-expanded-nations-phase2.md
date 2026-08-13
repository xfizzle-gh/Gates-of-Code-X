# Expanded Nations Phase 2 execution plan

Date: 2026-08-10
Parent epic: #189
Phase 1 PR: #172
Neutral garrisons: #48

## Starting authority

This stacked branch was created from exact PR #172 head:

`c59cbc247c565071d458c5724d9be626fcdf7dc0`

Branch:

`feat/189-expanded-nations-phase2`

Do not move Phase 1 work into this branch retroactively and do not push Phase 2 commits to `feat/170-expanded-nations-activation`.

PR #172 must complete native acceptance and merge before Phase 2 can merge to `main`. Phase 2 planning, live-stack source audit, authored data preparation, and stacked implementation may proceed in parallel.

## Issue chain

1. #190 source/equipment audit and authoritative actor dispositions.
2. #191 Western/Northern/Central implementation.
3. #192 Balkan/Eastern implementation.
4. #193 crop-conditional Near East/Caucasus/North Africa implementation.
5. #194 final deterministic/native acceptance.

#48 remains separate neutral-garrison authority.

## Actor disposition target

### Playable or explicit fallback candidates

`grc rou bgr hun cze svk bel prt hrv ltu lva est`

### Strategic-first candidates

`aut che irl svn bih mne alb mkd mda isl cyp mlt`

### Crop-conditional candidates

`geo arm aze isr lbn syr jor irq mar dza tun lby egy`

The authoritative theatre-country dataset wins over this planning list. Every represented country must receive one explicit disposition: `full_national`, `national_hybrid`, `coalition_fallback`, `regional_fallback`, `strategic_only`, or `excluded` with reason.

## Non-negotiable invariants

- GoH tactical export side remains one of `nato`, `ukr`, `rusa`, or `prc`.
- Strategic actor identity, coalition/alignment, ownership, treasury, diplomacy, research, and tactical side remain separate fields.
- Do not modify Vanilla, West81, Code:X, or Code:X AI Overhaul.
- Do not copy upstream models, textures, portraits, sounds, weapons, or entity definitions into Gates.
- Code:X is modern-content authority. West81 rows must be explicitly legacy/reserve.
- No runtime substring guessing for national roster ownership.
- Do not use Serbia `Serb_*` breeds as generic Balkan infantry.
- Do not use Wagner, militia, contractor, foreign-volunteer, or insurgent encounter content as a sovereign national army without direct evidence.
- Cross-side source reuse requires live target-side materialization proof, not only syntactically valid side rewriting.
- Existing Phase 1 actors remain semantically stable unless a separately approved regression fix is required.
- Strategic-only actors must not accidentally receive recruitment/research authority.
- Neutral-garrison content from #48 must not become recruitable after capture by default.

## Agent 1: live-stack source audit (#190)

This is the first useful overnight task and can run before #172 merges.

Use the real installed stack in this order:

1. Vanilla
2. West81
3. Code:X
4. Code:X AI Overhaul
5. the Phase 2 branch as final Gates layer only when Gates files are required

For every candidate actor, search country names, ISO abbreviations, localization text, breed stems, vehicle names, research roots, and mixed multinational containers. Do not stop at the first generic NATO/Warsaw-Pact fallback.

Produce:

- `docs/audits/expanded-nations-phase2-source-audit.md`
- `docs/audits/expanded-nations-phase2-source-candidates.json`

The JSON should contain, per actor:

```json
{
  "actor_id": "grc",
  "disposition": "national_hybrid",
  "tactical_side": "nato",
  "components": [],
  "exact_units": [],
  "research_roots": [],
  "source_layers": [],
  "legacy_units": [],
  "cross_side_units": [],
  "missing_categories": [],
  "confidence": "medium",
  "blockers": [],
  "notes": []
}
```

Do not commit guessed selectors. Every exact unit/root must be traced to the effective source stack.

## Agent 2: Phase 2 manifest and compiler integration (#191/#192)

Start only after #190 has enough accepted evidence for the actors being implemented.

Likely touched files:

- `src/gates_of_codex/data/faction_actors.json`
- `src/gates_of_codex/data/faction_components.json`
- `src/gates_of_codex/data/faction_audit_adjustments.json` only when the adjustment layer is genuinely the right authority
- faction manifest/compiler tests
- actor/economy/persistence tests whose expected actor set changes
- judgment-call audit documentation

Prefer adding reusable regional components only when they have a precise semantic boundary. Do not create a broad `europe_common_everything` pool.

For playable actors, required categories remain meaningful. If a country lacks enough content, make it strategic-only rather than weakening validation globally.

## Agent 3: strategic-only actors and map reconciliation (#193)

Read authoritative theatre province/country metadata first. Do not assume every planning candidate is actually in the final crop.

Implement strategic-only actors so they can own provinces, persist, participate in diplomacy/alignment, and appear in presentation without requiring a fake recruitable faction projection.

Local neutral tactical defense remains #48 content and must not mutate sovereign research/economy.

## Agent 4: tests and acceptance preparation (#194)

Expand tests to cover:

- exact actor set after authoritative map reconciliation;
- stable actor IDs;
- supported tactical sides only for projectable actors;
- strategic-only actors cannot install recruitable content;
- same-side national isolation;
- no Phase 1 regression;
- deterministic compilation;
- legacy provenance;
- cross-side reuse is explicitly reported;
- actor-scoped research/economy/save-load isolation;
- complete actor matrix generation and Core restoration.

Native testing should use one representative actor per distinct roster/materialization family rather than needlessly repeating byte-identical fallback families. Cross-side units always require explicit purchase/spawn testing.

## Initial roster hypotheses for audit only

These are search targets, not implementation authority.

- Greece: Greek-service NATO/legacy heavy equipment plus audited infantry/support bridge.
- Romania: Romanian/compatible Eastern equipment with audited NATO/common personnel bridge if necessary.
- Bulgaria: Bulgarian/compatible Warsaw-Pact legacy equipment with explicit modern support where appropriate.
- Hungary: modern NATO equipment where present plus Hungarian legacy assets.
- Czechia/Slovakia: national/Czechoslovak equipment such as BVP/BMP/Pandur/DANA/Zuzana families where actually present.
- Baltics: light-mechanized NATO emphasis; do not manufacture tank-heavy trees.
- Belgium/Portugal: NATO fallback unless national assets are discovered.
- Croatia: Balkan/NATO hybrid if source-backed; no Serbian-personnel reuse.
- Austria/Switzerland/Ireland/Iceland: strategic-first unless the audit proves a credible full roster.
- North Africa/Near East/Caucasus: strategic ownership first; encounter rosters remain separate under #48 unless real national content is found.

## Integration order

1. Finish #172 acceptance and merge.
2. Integrate final `main` into this Phase 2 branch with a normal merge/rebase strategy chosen at that time; do not rewrite accepted #172 history.
3. Accept #190 source audit.
4. Implement #191 and #192 in reviewable slices.
5. Implement only authoritative crop actors from #193.
6. Regenerate complete actor matrix.
7. Run repository CI.
8. Run native representative matrix against live Workshop Gates.
9. Restore Core Code:X.
10. Independent exact-head review under #194.
11. Mark ready/merge only after approval.

## Tomorrow handoff checklist

Before any implementation agent edits:

```text
- fetch live repository state
- confirm PR #172 final accepted/merged state
- confirm this branch still descends from c59cbc247c565071d458c5724d9be626fcdf7dc0 or document later integration
- read #189, #190, the assigned implementation child issue, #48, and #194
- inspect current authoritative theatre-country data
- do not assume a roster decision that #190 has not evidenced
```

At the end of every implementation slice report:

- exact head SHA;
- changed files;
- actors added/changed;
- exact component selectors added;
- source provenance and any cross-side reuse;
- tests executed and results;
- known native-test obligations;
- whether Phase 1 actor output changed;
- explicit stop point.
