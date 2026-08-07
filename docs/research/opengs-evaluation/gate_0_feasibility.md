# OpenGS Gate 0 feasibility decision

Issue: #131  
Parent: #130  
Draft PR: #137  
Status: **ready for owner review**

## Decision

Gate 0 supports proceeding to Gate 1 after owner approval.

This decision authorizes only a deterministic, headless experimental generator fork. It does not authorize replacing Earth3, modifying production map authority, integrating the OpenGS Godot runtime, or starting a Gates geometry migration.

Gate 1 has not started.

## Locked Gates authority

The evaluation did not modify:

- `map_id`: `earth3_europe_mediterranean`
- 3514 production records
- 3299 selectable land records
- 215 non-selectable water metadata records
- `polygon_mesh` rendering
- `point_in_polygon_spatial_index` hit testing
- `immutable_geometry_shader_lookup` ownership
- GL Compatibility
- permanent unused IDs `e3_2830` and `e3_2888`

PR #128 was not modified, retargeted, or used as the implementation branch.

## Upstream generator authority

The evaluation pins:

```text
Thomas-Holtvedt/opengs-maptool
06e7ec8517bd45872cf44d77cb8784e5ffca49bb
version 0.3
MIT
```

The upstream license and copyright notice are retained under `tools/opengs_eval/`.

The exact pinned source was benchmarked without modifying its generation functions.

## Provenance feasibility

A legally plausible source path exists.

The real-input benchmark pins Natural Earth vector release `v5.1.2` at commit:

```text
f1890d9f152c896d250a77557a5751a93d494776
```

Natural Earth is published as public-domain data. The benchmark verifies exact Git blob IDs and SHA-256 hashes for:

- land polygons
- lakes
- national boundary lines
- populated places
- river centerlines used as a reference-only pin

The aligned input uses one Lambert Azimuthal Equal Area projection:

```text
+proj=laea +lat_0=45 +lon_0=20 +datum=WGS84 +units=m +no_defs
```

The theatre bounds are longitude `-25..60` and latitude `20..75`.

Terrain was not sourced from Natural Earth or invented for this benchmark. The upstream default terrain behavior was left in place. Candidate terrain, elevation, lake, city, and administrative datasets remain separately inventoried with their published attribution and redistribution constraints.

OpenStreetMap remains conditional and is not part of the benchmark because ODbL obligations require a separate project-specific decision.

## Exact synthetic benchmarks

Actions run `31223766220` tested the exact pinned generator on Linux and Windows.

The generator completed:

- 440 provinces
- approximately 1000 provinces
- approximately 2000 provinces
- three repeated nominal 3514-province runs
- one jagged nominal 3514-province run
- one 5000-province stress run

The nominal 3514 configuration completed in approximately 6.9 seconds on Linux and 9.9 seconds on Windows at 1200x800 synthetic resolution.

The 5000-province synthetic stress case completed without an exception on both platforms.

Every repeated nominal 3514 run produced a different raster hash on both platforms.

## Exact Natural Earth benchmark

Actions run `31224683315` built a projection-aligned 2048x1536 Europe-Mediterranean input and executed the pinned upstream territory and province generators.

Input summary:

| Item | Result |
|---|---:|
| Land pixels | 1,173,339 |
| Ocean pixels | 1,957,073 |
| Lake pixels | 15,316 |
| Connected lake components | 281 |
| Populated places used for density | 1,601 |
| National boundary features | 214 |
| Boundary line parts | 2,373 |

### Non-jagged generation

Three identical runs produced:

| Run | Wall time | Peak RSS | Actual records |
|---:|---:|---:|---:|
| 1 | 50.23 s | 417.3 MB | 3795 |
| 2 | 50.85 s | 410.3 MB | 3795 |
| 3 | 51.53 s | 417.2 MB | 3795 |

All three province-image hashes and all three metadata hashes were different.

### Jagged generation

The jagged-land run produced:

| Wall time | Peak RSS | Actual records |
|---:|---:|---:|
| 122.26 s | 514.1 MB | 3795 |

Jagged generation was approximately 2.39 times slower than the average non-jagged run and used approximately 97 MB more peak RSS.

No generation exception occurred.

## Direct Gates incompatibilities confirmed

### Nondeterminism

The pinned upstream path does not thread explicit seeds through territory seed placement, province seed placement, and Lloyd sampling.

Identical recipes do not regenerate identical maps.

Gate 1 must require a root seed and named derived seeds for every stochastic operation, plus deterministic ordering, rounding, encoding, and output serialization.

### Lake count inflation

The nominal request was:

```text
3299 land + 215 ocean = 3514
```

The upstream generator then created every connected lake as another province:

```text
3299 land + 215 ocean + 281 lake = 3795
```

The output exceeded the requested total by exactly 281 records.

This cannot directly satisfy Gates' 3299 selectable land plus 215 total water-metadata policy. A future adapter must filter, merge, classify, or otherwise convert lakes under an explicit Gates water policy. It must not silently accept OpenGS lake IDs as selectable provinces.

### Raster output is not a Gates geometry dataset

The output still lacks authoritative:

- polygon outer rings
- multipart components
- interior holes
- triangles
- exact shared border edges
- Gates border classes
- spatial-index fixtures
- interior-safe anchors
- reciprocal adjacency audit
- stable Gates IDs
- authority hashes and migration contracts

Gate 2 remains necessary. Campaign code must never become aware of OpenGS.

### Terrain is center-sampled

The upstream terrain path samples one pixel at the province center.

That is insufficient for mixed terrain, narrow mountain corridors, urban overlays, rivers, and multipart provinces. Gate 2 must calculate full-area terrain coverage percentages and allow explicit authored overrides.

### Jagged cleanup is unsafe as a Gates island policy

The upstream jagged cleanup keeps only the largest connected component of a generated region and reassigns smaller fragments.

That behavior may be useful for noise removal, but it cannot be treated as authoritative multipart or island preservation. Gate 2 must preserve legitimate components and report every discarded fragment.

### Generated territories are not semantic regions

The 140 generated territories were used only as province-distribution containers.

They were not interpreted as:

- operational regions
- supply regions
- air regions
- command regions
- countries
- ownership groups

Those assignments remain separately authored Gates data.

### OpenGS JFA borders remain excluded

The evaluation did not copy or plan direct OpenGS JFA compute integration.

Gates remains on GL Compatibility. Border rendering must continue through current polygon edges, CPU or offline preprocessing, or a separately approved renderer decision.

## Gate 0 exit assessment

| Requirement | Result |
|---|---|
| Legal source path identified | Pass |
| Generator commit pinned | Pass |
| MIT attribution recorded | Pass |
| Approximate 3514 scale benchmarked | Pass |
| Linux and Windows synthetic behavior measured | Pass |
| Real aligned theatre input benchmarked | Pass |
| Runtime and memory recorded | Pass |
| Failure and incompatibility behavior documented | Pass |
| Production Earth3 unchanged | Pass |
| PR #128 unchanged | Pass |
| Full OpenGS runtime excluded | Pass |

## Recommendation for Gate 1

Approve Gate 1 only with these conditions:

1. Fork only the required generation modules.
2. Retain upstream MIT notices and original file hashes.
3. Remove PyQt from the generation path.
4. Add a versioned recipe and run-manifest schema.
5. Require explicit named seeds for all randomness.
6. Prove byte-identical generation in clean CI workspaces.
7. Keep all generated artifacts experimental and non-default.
8. Do not begin polygon adaptation, Godot map registration, or production migration in Gate 1.

## Evidence

Committed summaries:

- `gate_0_exact_ci_benchmark.md`
- `gate_0_exact_ci_summary.json`
- `gate_0_natural_earth_summary.json`
- `provenance_inventory.json`

Real-input artifact:

```text
artifact ID: 9011772386
artifact digest: sha256:eb814a87dac3bcc65a315291b5167c8587aa8858dfa9a002d17b786d227865ea
benchmark result SHA-256: c034b518c0ca4167b350a3fd42082c3b0b0dd557d7a69cbf5b1fbe3d2c31eadd
```

## Stop point

Gate 0 implementation is complete and ready for owner review.

PR #137 must remain draft. Issue #131 should remain open until the owner accepts this recommendation. No Gate 1 branch or code should begin before that ruling.
