# P1 Earth3 Campaign Authority Design

## Scope

P1 makes the committed `earth3_europe_mediterranean` production assets authoritative for newly created campaigns. It adds map and scenario identity only: no starting ownership, formations, objectives, commanders, meaningful economy, deployment zones, operational routes, tactical handoff, player launcher, or Fog presentation.

The implementation branches directly from `b8f125fe484c9bf616c75b39587ed9afe3f4ca07` on `feat/p0-p1-earth3-campaign-authority`.

## Architecture

### Earth3 authority loader and builder

A new `gates_of_codex.earth3_campaign` module owns the production authority contract. It resolves the repository-relative Earth3 manifest, polygon dataset, dataset metadata, and production-authority record; validates their approved hashes, map identity, schema identity, counts, stable IDs, water policy, anchors, and committed adjacency; and then constructs a `CampaignState` without importing or calling a GoE builder.

The builder emits one `Province` per committed Earth3 province. Each province uses the stable Earth3 ID as its temporary P1 display name, the committed label anchor as its display coordinate, neutral ownership, zero resource yield, committed adjacency, and scalar metadata for source ID, centroid, terrain, continent, water, and selectability. Polygon rings, render vertices, triangles, borders, and other geometry remain exclusively in `polygon_dataset.json`.

The P1 state contains no formations, battalions, commanders, alliances, objectives, routes, or starting ownership. Because the frontend construction snapshot reads the selected faction's runtime state, the skeleton includes exactly one existing-model NATO `FactionState`, marked human-controlled, with the schema-default numeric resource value and empty research/recruitment/reinforcement pools. Metadata labels it P1 schema compatibility only; it is not P2 economy or force content. Scenario and asset provenance is stored in `map_metadata` using repository-relative identifiers and approved hashes, never machine-specific asset paths.

### Scenario registry and CLI

`gates_of_codex.scenario` exposes an explicit immutable registry with:

- `earth3_v1` → `earth3_europe_mediterranean`, production, Earth3 builder;
- `legacy_goe_europe` → `goe_europe_alpha_graph_v1`, legacy, GoE builder;
- `legacy_goe_europe_mediterranean` → `europe_mediterranean_from_goe`, legacy, derived GoE builder.

Unknown IDs raise an error listing valid IDs. `load_bundled_scenario()` remains as a compatibility entry point but delegates to `earth3_v1` by default. The `new` parser gains explicit `--scenario`; omitted selection resolves only to `earth3_v1`. Legacy post-processing that scans Code:X, populates starter rosters, and initializes the economy remains limited to explicitly selected legacy scenarios. The Earth3 P1 skeleton does not invent P2 content.

Creation completes authority validation before `save_campaign()` is called. Existing atomic save behavior therefore prevents partial output and preserves an existing valid file on any Earth3 validation failure.

### Frontend identity

Python frontend map resolution recognizes Earth3 explicitly and does not use a GoE map as its default lookup for unknown or missing Earth3 assets. Earth3 export raises an actionable missing-asset error. The Earth3 strategic-map block identifies only Earth3 as the active production map and declares no fallback. Explicit legacy state continues to resolve and export its stored legacy map ID.

No scene, UI, launcher, player-control, or Godot presentation code changes are part of P1.

## Owner-ruling authority boundary

Issue #176 comment `5229031463` designates the production dataset SHA-256 `8ae59bd89419a368fe9131ef7c50d94a7f1cafacd1cfae44362ac9b5d9decced`, geometry SHA-256 `7715807367932662642ff6d0c52faf8657b379abf6f67978a9acece3d18f2678`, asset version `earth3_production_v1`, 3,514 stable provinces, 3,299 land/selectable provinces, 215 water provinces, and 10,249 actual unique undirected topology edges as P1 authority.

`polygon_dataset.json`, `dataset_meta.json`, the production manifest, all geometry, IDs, classifications, neighbors, edges, and existing embedded hashes remain byte-for-byte unchanged. The two stale summaries remain present but are not structural authority:

1. embedded `edge_count: 10223` in the dataset and metadata;
2. `dataset_meta.selectable_province_count: 3295`.

The loader pins those exact stale values so the exception cannot widen. It independently derives selectability from actual province water records, normalizes and validates the committed edge array, derives the reciprocal neighbor-edge set separately, requires both sets to equal exactly, and requires the result to contain 10,249 edges. The frozen manifest's legacy fallback field is validated as part of its pinned bytes but is never followed by the Earth3 builder or frontend resolver.

## Failure behavior

The loader fails closed for missing files, modified manifest bytes, modified dataset bytes, mismatched map IDs, schemas, non-exempt counts, hashes, stable IDs, water/selectability policy, geometry structure, malformed/duplicate/self/missing adjacency, invalid endpoints, non-reciprocal neighbors, edge-set disagreement, or mismatched anchors. Errors identify the asset and violated field. No exception handler retries with a legacy scenario.

## Regression coverage

Adversarial tests are written but not executed. They cover default and explicit scenario selection, GoE/snapshot non-use, all Earth3 hashes and counts, deterministic IDs, provenance, geometry exclusion, frozen-file non-rewrite, the two narrowly stale summaries, actual 10,249-edge topology, duplicate/missing/invalid/self/nonreciprocal edge failures, missing/modified/mismatched assets, output atomicity, legacy creation/load/round-trip/export identity, and frontend fail-closed behavior.

## Publication boundary

Static review inspects the complete diff and exact base without running tests, linters, type checks, builds, compilation, Godot, smoke checks, workflows, or CI logs. Publication is one pushed branch, one draft PR, and one issue #176 comment. P2 through P6 and S11 PR C remain unstarted.
