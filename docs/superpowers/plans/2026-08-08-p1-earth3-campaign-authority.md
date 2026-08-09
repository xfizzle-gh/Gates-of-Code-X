# P1 Earth3 Campaign Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the committed Earth3 Europe–Mediterranean production authority the default scenario for newly created campaigns while preserving explicit legacy creation and existing-save identity.

**Architecture:** A dedicated Earth3 loader/builder validates pinned production assets before projecting scalar province authority into `CampaignState`. An explicit scenario registry controls all new-campaign selection, and frontend map resolution treats Earth3 as the sole production map without legacy fallback. The campaign stores hashes and stable identifiers but never polygon geometry or machine-specific asset paths.

**Tech Stack:** Python 3.11 standard library, dataclasses, argparse, JSON, unittest-style regression tests, Git/GitHub CLI.

## Global Constraints

- Branch from exact base `b8f125fe484c9bf616c75b39587ed9afe3f4ca07` on `feat/p0-p1-earth3-campaign-authority`.
- Do not execute tests, linters, type checks, builds, compilation, smoke checks, Godot, GitHub Actions, or workflow-log inspection.
- Preserve all 3,514 stable province IDs, polygon geometry bytes, production dataset SHA-256 `8ae59bd89419a368fe9131ef7c50d94a7f1cafacd1cfae44362ac9b5d9decced`, production geometry SHA-256 `7715807367932662642ff6d0c52faf8657b379abf6f67978a9acece3d18f2678`, and accepted water/selectability policy.
- Preserve `polygon_dataset.json` and `dataset_meta.json` exactly. Treat only embedded `edge_count: 10223` and `dataset_meta.selectable_province_count: 3295` as stale summaries under issue #176 comment `5229031463`; derive and require 10,249 actual topology edges and 3,299 actual selectable records.
- Never call or derive from a GoE builder on the Earth3 path.
- Add no P2 scenario content, P3 routes, P4 launcher/UI, P5 tactical handoff, P6 packaging, or S11 PR C presentation.
- Publish one draft PR, comment once on issue #176, and stop.

---

### Task 1: Author the P1 regression boundary

**Files:**
- Create: `tests/test_p1_earth3_campaign_authority.py`
- Modify: `tests/test_gates_of_codex.py`
- Modify: `tests/test_earth3_authority_consistency.py`
- Modify: `tests/test_earth3_production_dataset.py`

**Interfaces:**
- Consumes: intended `build_earth3_campaign(authority_root: str | Path | None = None) -> CampaignState`, `build_scenario(scenario_id: str = "earth3_v1", **builder_options) -> CampaignState`, and `scenario_ids() -> tuple[str, ...]`.
- Produces: adversarial regression specifications for every P1 acceptance and failure boundary.

- [ ] **Step 1: Write default creation and registry tests**

Add tests that call the real parser/main path with a temporary output and assert:

```python
self.assertEqual("earth3_v1", state.map_metadata["scenario_id"])
self.assertEqual("earth3_europe_mediterranean", state.map_id)
legacy_goe.assert_not_called()
legacy_em.assert_not_called()
```

Cover unknown scenario errors, explicit legacy builders, legacy non-default status, positional output compatibility, and a stale `campaign_snapshot.json` that must not be read.

- [ ] **Step 2: Write Earth3 authority and serialization tests**

Assert exact external constants independently from production implementation:

```python
self.assertEqual(3514, len(state.provinces))
self.assertEqual(3299, sum(not p.metadata["is_water"] for p in state.provinces.values()))
self.assertEqual(215, sum(p.metadata["is_water"] for p in state.provinces.values()))
self.assertEqual(3299, sum(p.metadata["selectable"] for p in state.provinces.values()))
self.assertNotIn("vertices", json.dumps(state.to_dict()))
self.assertNotIn("triangles", json.dumps(state.to_dict()))
self.assertNotIn("\"ring\"", json.dumps(state.to_dict()))
```

Verify unique deterministic IDs, pinned manifest/dataset hashes, matching authority counts, provenance fields, relative manifest identifier, no absolute provenance path, and unchanged dataset bytes/hash.

- [ ] **Step 3: Write fail-closed asset tests**

Create temporary authority roots using copied committed assets. Independently delete or mutate the manifest/dataset and alter hash/count/map fields. Assert actionable `Earth3AuthorityError` messages. Patch legacy builders and prove they remain uncalled.

For CLI failure, seed an existing valid output and assert its bytes remain identical; with no existing output, assert no output or temporary file remains.

- [ ] **Step 4: Write legacy and frontend identity tests**

Assert explicit legacy creation remains valid, legacy round trips retain their stored map IDs, legacy frontend export retains that identity, Earth3 export reports only Earth3 production identity and no GoE fallback, and missing Earth3 frontend assets raise clearly.

- [ ] **Step 5: Do not execute the tests**

No test command is authorized. Review names and assertions statically only.

### Task 2: Implement the dedicated Earth3 authority loader and builder

**Files:**
- Create: `src/gates_of_codex/earth3_campaign.py`
- Preserve unchanged: `godot/assets/maps/earth3_europe_mediterranean/map_manifest.json`
- Preserve unchanged: `godot/assets/maps/earth3_europe_mediterranean/polygon_dataset.json`
- Preserve unchanged: `godot/assets/maps/earth3_europe_mediterranean/dataset_meta.json`

**Interfaces:**
- Produces: `Earth3AuthorityError(ValueError)`, `Earth3Authority`, `load_earth3_authority(authority_root=None) -> Earth3Authority`, and `build_earth3_campaign(authority_root=None) -> CampaignState`.

- [ ] **Step 1: Preserve frozen authority and narrow stale-summary handling**

Do not edit the dataset, metadata, or manifest. Pin the two designated stale values exactly so the exception cannot widen. Validate every other required field strictly. Preserve the manifest fallback field as frozen metadata, but ensure no Earth3 code path follows it.

- [ ] **Step 2: Pin and validate asset bytes**

Use constants for stable scenario/map IDs, repository-relative paths, the owner-approved dataset/geometry hashes and asset version, the committed embedded dataset digest, included-ID hash, counts, 10,249 topology edges, and the unchanged manifest-byte hash. Validate `production_authority.json`, `dataset_meta.json`, manifest, and dataset against one another before constructing state.

- [ ] **Step 3: Validate province rows and committed adjacency**

Require exactly 3,514 unique stable `e3_` IDs in dataset order; valid geometry fields and two-element centroid/label anchors; boolean `is_water`; scalar source/terrain/continent metadata; neighbors that exist and are unique; and reciprocal committed adjacency. Normalize the actual edge array, reject malformed/duplicate/self/invalid edges, independently derive neighbor edges, require exact set equality, and require exactly 10,249 actual edges. Derive 3,299 selectable provinces from actual non-water records. Do not infer, repair, or enable operational routes.

- [ ] **Step 4: Build the geometry-free P1 skeleton**

Project each row as:

```python
Province(
    province_id=province_id,
    display_name=province_id,
    owner=Faction.NEUTRAL,
    neighbors=neighbors,
    terrain="water" if is_water else f"earth3_{terrain_id}",
    map_region="earth3_europe_mediterranean",
    x=float(label[0]),
    y=float(label[1]),
    resource_yield=0,
    metadata={
        "source_id": source_id,
        "centroid": centroid,
        "terrain_id": terrain_id,
        "continent_id": continent_id,
        "is_water": is_water,
        "selectable": not is_water,
    },
)
```

Set provenance fields for scenario/map IDs, relative manifest identifier, approved manifest/dataset hashes, included-ID hash, province/land/water/selectable counts, stable-ID policy, water policy, adjacency authority, and explicit absence of an approved operational graph. Set empty strategic objectives/capitals so generic save normalization cannot invent GoE/P2 content.

- [ ] **Step 5: Perform static source review only**

Inspect imports and call graph to prove `earth3_campaign.py` does not import GoE modules or geometry into campaign state. Do not run it.

### Task 3: Add the explicit registry and make Earth3 the default

**Files:**
- Modify: `src/gates_of_codex/scenario.py`
- Modify: `src/gates_of_codex/cli.py`

**Interfaces:**
- Produces: immutable `ScenarioDefinition`, `SCENARIO_REGISTRY`, `DEFAULT_SCENARIO_ID`, `scenario_ids()`, `get_scenario()`, and `build_scenario()`.
- Preserves: `load_bundled_scenario()` as a deterministic registry-backed compatibility API.

- [ ] **Step 1: Define explicit registry records**

Each record contains scenario ID, map ID, display name, `production`/`legacy` status, required authority identifiers, and a builder callable. Use lazy wrapper callables so tests can patch legacy builders and prove Earth3 never invokes them.

- [ ] **Step 2: Add deterministic selection and errors**

Implement:

```python
def get_scenario(scenario_id: str) -> ScenarioDefinition:
    try:
        return SCENARIO_REGISTRY[scenario_id]
    except KeyError as exc:
        valid = ", ".join(scenario_ids())
        raise ValueError(f"Unknown scenario ID {scenario_id!r}; expected one of: {valid}") from exc
```

`build_scenario()` invokes exactly one selected builder and records the registry scenario ID if the builder has not already done so.

- [ ] **Step 3: Update `new` parsing and safe creation**

Add `--scenario` defaulting to `earth3_v1`; accept the output path positionally while preserving `--output`; make `--codex` optional for Earth3 but require it for explicit legacy creation. Earth3 creation sets selected faction and Fog flag but does not populate rosters/economy. Legacy creation retains the existing Code:X scan, starter-roster, economy, and outcome behavior.

Resolve conflicting positional/flag outputs before building. Do not catch an Earth3 authority error or retry another scenario. Call `save_campaign()` only after all creation work succeeds.

- [ ] **Step 4: Statically inspect legacy callers**

Update existing behavior-specific tests/callers to request `legacy_goe_europe` explicitly where they require GoE provinces or formations. Keep new default tests on Earth3.

### Task 4: Enforce frontend map identity without changing Godot presentation

**Files:**
- Modify: `src/gates_of_codex/frontend.py`
- Modify: `tests/test_frontend_writeback_contract.py`

**Interfaces:**
- Consumes: `CampaignState.map_id` and repository-relative `map_metadata["strategic_map_manifest"]`.
- Produces: an Earth3 strategic-map block with `map_id == "earth3_europe_mediterranean"`, no legacy fallback, and explicit production/legacy classifications.

- [ ] **Step 1: Replace ambiguous fallback lookup**

Use exact map-ID mappings only. Never call `dict.get(map_id, legacy_default)`. Unknown IDs with no configured manifest remain disabled or raise an unknown-map error; Earth3 missing assets always raise `FileNotFoundError` listing the required relative manifest.

- [ ] **Step 2: Emit accurate availability and status**

For Earth3 return production identity only:

```python
{
    "enabled": True,
    "map_id": "earth3_europe_mediterranean",
    "available_map_ids": ["earth3_europe_mediterranean"],
    "production_map_ids": ["earth3_europe_mediterranean"],
    "legacy_map_ids": ["goe_europe", "europe_mediterranean_from_goe"],
    "fallback": "none",
}
```

Explicit legacy states retain their exact map ID and legacy manifest resolution; they are never rewritten to Earth3.

- [ ] **Step 3: Keep Godot untouched**

Confirm no scenes, scripts, UI composition, controls, or launcher files changed. Python export must fail before a missing Earth3 manifest can reach any legacy Godot fallback behavior.

### Task 5: Static review, commits, and publication

**Files:**
- Review every changed path.
- Create a temporary PR-body file outside the repository for `gh pr create`.

**Interfaces:**
- Produces: pushed exact head, one draft PR, and one issue #176 comment.

- [ ] **Step 1: Perform non-executing static verification**

Use only Git/read-only inspection: `git status`, `git diff --check`, `git diff --stat`, `git diff --name-only`, `git diff <base>...HEAD`, `git grep`, `git rev-parse`, and JSON text review. Do not invoke Python, pytest, unittest, a linter, compiler, Godot, CI, or workflows.

Verify the complete scope checklist from the brief, confirm the dataset blob ID and hash are unchanged from base, confirm no generated/cache/temp files, and count changed files.

- [ ] **Step 2: Commit intended files only**

Stage explicit paths. Use focused commits for tests, authority/builder, registry/CLI, frontend identity, and final documentation where practical. Confirm the worktree has no unrelated changes.

- [ ] **Step 3: Push the requested branch**

Push `feat/p0-p1-earth3-campaign-authority` with upstream tracking. Do not inspect any automatically triggered workflow.

- [ ] **Step 4: Open the required draft PR**

Title: `P1: make Earth3 authoritative for new campaigns`.

Body includes issue #176, exact base/head, changed-file count, implementation summary, complete tests-authored list, explicit no-tests/CI-executed-or-inspected statement, stale-summary owner ruling, frozen-file/hash proof, limitations, untouched P2–P6/S11 PR C statement, and draft/unmerged review instruction.

- [ ] **Step 5: Comment on issue #176 and stop**

Post the draft PR link and exact head. Do not wait for or inspect CI, do not mark ready, do not merge, and do not begin P2.
