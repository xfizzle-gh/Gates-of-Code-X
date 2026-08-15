# #212 Earth3 rendering comparison

## Corrected ordinary-player baseline

The historical ~3.7k draw-call figure was contaminated by developer `MapDebug` presentation. PR #238 established the controlled debug-off baseline with a reversible `OFF -> ON -> OFF restored` test:

| Mode | Draw calls p50 | Draw calls p95 | Frame p50 ms | Frame p95 ms |
|---|---:|---:|---:|---:|
| Debug OFF | 205 | 205 | 161.558 | 165.906 |
| Debug ON | 3,764 | 3,764 | 265.424 | 279.382 |
| Debug OFF restored | 205 | 205 | 160.581 | 164.458 |

PR #238 provenance: measurement commit `f8f1ff072bc0b9a89c82f210e506d56b372918f8`, workflow run `31849403512`, artifact `9237017273`, Godot 4.7, Ubuntu/Xvfb/OpenGL Compatibility/Mesa llvmpipe, 1920x1080, 24 frames per mode, exact 3,514-province Earth3 authority.

## Phase A: controlled production-layer attribution

The first PR #239 frame-time table was rejected because it compared every later probe against one process-first baseline. Renderer/resource/font/shader warmup survived across fresh scenes and contaminated the causal ranking.

The corrected PR #239 experiment bracketed every presentation category:

`baseline_before -> layer_disabled -> baseline_after`

It burned process-first warmup before recorded brackets, used 24 measured frames, computed each delta against the midpoint of its surrounding baselines, and failed if p50/p95 drift exceeded 15% or if surrounding draw-call/primitive counts changed.

Corrected Phase A measurement provenance: head `59f1db2f3f9c55b839ebd73d38192458b90612c9`, workflow `31852606988`, artifact `9238086887`. Maximum observed baseline drift was 2.66%, with exact 205 draw calls and 456,565 primitives in every surrounding ordinary baseline.

| Disabled category | Draw-call delta | Primitives removed | Frame p50 delta | Frame p95 delta |
|---|---:|---:|---:|---:|
| Land fill, 4 chunks | 4 | 286,495 | **69.976 ms** | **71.551 ms** |
| Shared borders | 1 | 163,988 | **38.320 ms** | **36.962 ms** |
| Ocean mesh | 1 | 2 | 15.129 ms | 17.769 ms |
| Secondary/federal outlines | 48 | 1,714 | 3.104 ms | 5.750 ms |
| Labels/glyphs | 30 | 1,242 | 1.464 ms | -1.989 ms |
| Formation counters | 23 | 124 | -0.588 ms | -0.448 ms |
| Infrastructure/sites | 36 | 552 | 0.480 ms | 2.948 ms |
| Routes | 11 | 394 | -3.758 ms | -5.202 ms |
| Fixture/proof overlays | 78 | 2,956 | 5.136 ms | 8.735 ms |
| Contact/battle probe | -7 | 310 | 18.859 ms | 19.768 ms |

The exact earlier ~123 ms land and ~90 ms border claims are retired. Phase A supports a static-presentation cache experiment while keeping Earth3 polygons/topology/stable IDs as the sole simulation, validation, and picking authority.

## Phase B: audited full-cache vs 512/1024 tiled shadow

PR #241 is a debug-only presentation spike. It does not switch the production renderer. The static cache is derived from an isolated duplicate of the live `Earth3PolygonRoot`; the authoritative `PolygonMap` remains loaded for stable IDs, picking, water policy, owner state, selection/legal-target identity, and operational coordinates. Sparse dynamic overlays remain live and are not baked into the cache.

### Why the first Phase B evidence was rejected

The first matrix used only 8 measured frames per sample and later failed its own 15% bracket contract with roughly 22.7% p95 baseline drift. Its legal-target parity was also vacuous because the presentation fixture had `legal_target_ids: []`, owner refresh only proved that a pixel became different, and the evidence covered only idle/pan/zoom plus one idle screenshot set.

Those claims are retired.

### Audited Phase B provenance and controls

Accepted measurement evidence for the corrected experiment:

- measurement head: `ee8e64577b7ffe0514c79613488fc84dd6d1f9ab`;
- focused workflow: `31860104231`;
- audited artifact: `9240484024`, SHA-256 `48fa220b2e6619a3dbbd191f3ce68f9ddd61eca3df07fc8d797e7a5d4d93bfd3`;
- full-cache authority artifact: `9240283477`, SHA-256 `89d63c68b9ba28f3b1475b2df6aa2e835b26eb3e746c636c6d71a0abe82c97b9`;
- Godot 4.7 stable, Ubuntu/Xvfb/OpenGL Compatibility/Mesa llvmpipe;
- 1920x1080;
- 24 measured frames per matrix and dynamic sample;
- two unreported stabilization passes before recorded cache brackets;
- exact 3,514-province Earth3 authority.

Every performance sample remains locally bracketed as:

`polygon_before -> cache_mode -> polygon_after`

The 15% p50/p95 rejection threshold was not relaxed. All brackets passed. The worst observed matrix drift was **4.27%** and the worst dynamic-scenario drift was **2.77%**. Surrounding polygon draw-call and primitive counts matched exactly.

### Authority and interaction parity

The corrected audit strengthens each authority claim:

- manifest, polygon-dataset, and performance-fixture hashes remained byte-identical before/after;
- deterministic stable-ID picking and water non-selection remained unchanged;
- five stable operational anchors remained unchanged;
- a real Earth3 snapshot was generated through the production player-shell `--new --no-launch` path rather than by seeding fixture targets;
- that production snapshot contained **252 complete operational orders**;
- deterministic order `sf_deu_berlin`, origin `e3_0592`, required target `e3_0391`, rebuilt a real set of **63 legal targets**;
- the exact same 63-target set, selected formation, and origin remained identical across polygon, full-cache, 512, and 1024 presentation while `PolygonMap` stayed live;
- owner refresh no longer passes merely because a pixel changed. The refreshed `e3_0000` RUSA pixel is checked against the mean production-rendered cache color of eight unchanged RUSA province anchors. Error was **0.0137** against a **0.02** tolerance, with reference-color spread **0.0098**.

The raw RUSA palette literal is intentionally not the oracle because production static rendering applies presentation treatment; the audit records its larger 0.2235 mismatch only as a diagnostic.

### Audited base matrix

Positive improvement means the cache mode was faster than its own local polygon bracket midpoint.

| Scenario | Mode | Polygon p50 | Cache p50 | Improvement | Cache draws p50 | Cache primitives p50 | Visible tiles p50 |
|---|---|---:|---:|---:|---:|---:|---:|
| Idle full theatre | Full cache | 215.093 ms | **84.138 ms** | **130.955 ms / 60.9%** | 200 | 6,082 | 1 |
| Idle full theatre | 1024 tiles | 214.830 ms | **89.429 ms** | **125.401 ms / 58.4%** | 262 | 6,206 | 63 |
| Idle full theatre | 512 tiles | 216.351 ms | 96.181 ms | 120.170 ms / 55.5% | 437 | 6,556 | 238 |
| Continuous pan | Full cache | 214.952 ms | **82.600 ms** | **132.352 ms / 61.6%** | 200 | 6,082 | 1 |
| Continuous pan | 1024 tiles | 214.168 ms | **87.878 ms** | **126.290 ms / 59.0%** | 262 | 6,206 | 63 |
| Continuous pan | 512 tiles | 214.571 ms | 94.293 ms | 120.278 ms / 56.1% | 420 | 6,522 | 221 |
| Continuous zoom | Full cache | 251.540 ms | **87.757 ms** | **163.783 ms / 65.1%** | 202 | 6,148 | 1 |
| Continuous zoom | 1024 tiles | 253.799 ms | **89.254 ms** | **164.546 ms / 64.8%** | 229 | 6,206 | 28 |
| Continuous zoom | 512 tiles | 252.608 ms | 97.335 ms | 155.273 ms / 61.5% | 285 | 6,314 | 84 |

All cache modes remove roughly 450k static primitives. Tiling raises draw calls because each visible tile is a separate submitted presentation item in this spike. This is why 512px tiles are not preferred despite their frame-time improvement.

### Required dynamic scenarios

The audit now measures and captures identical-camera evidence for all previously missing Phase B surfaces. Each row below is the 1024px result; full-cache and 512px results are retained in `raster-shadow-comparison.json` and the workflow artifact.

| Scenario | Proved surface | 1024 polygon p50 | 1024 cache p50 | Improvement | Alignment probes |
|---|---|---:|---:|---:|---:|
| Hover/select | selected `e3_2108`, hovered `e3_2781` | 262.843 ms | 93.854 ms | 168.989 ms / 64.3% | 2 |
| Large formation counters | 12 counters | 218.173 ms | 89.843 ms | 128.330 ms / 58.8% | 12 |
| Infrastructure/routes | 6 sites, 1 route | 268.490 ms | 94.746 ms | 173.744 ms / 64.7% | 8 |
| Pending battle/contact | 2 battles, 1 contact, pending battle present | 219.306 ms | 90.242 ms | 129.064 ms / 58.9% | 4 |

Across full-cache, 512, and 1024 validation there are **78 cache-mode map-space probe points across 12 scenario/mode validations**. Every one reported **0.0 px maximum alignment error** against the live map transform while the tested pan/zoom motion ran.

The artifact contains:

- 4 same-camera base matrix screenshots: polygon/full/512/1024;
- 4 real legal-target screenshots: polygon/full/512/1024;
- 16 dynamic screenshots: four scenarios times polygon/full/512/1024.

Direct base screenshot comparison remains effectively identical between cache representations: full-cache vs 1024 differs at about 0.008198% of pixels, with only 0.000048% over five channel levels and maximum channel delta 9/255. The 512/1024 pair differs at about 0.005064%, maximum channel delta 4/255.

### Memory and residency finding

The 2x cache is 8,612 x 6,898 RGBA8, about **226.6 MiB raw**. The polygon baseline records about **66.0 MiB** video memory while the current shadow process records about **368.2 MiB**, roughly **+302.1 MiB**.

The current tiled spike materializes every tile texture up front. Viewport culling therefore reduces submitted tiles but does not reduce resident cache memory. At full-theatre view all 63 1024px tiles and 238 512px tiles are visible; during the zoom probe p50 visible tiles fall to 28 for 1024 and 84 for 512.

This is a performance/architecture proof, not a production memory design.

## Phase B decision

**Phase B debug-shadow evidence passes.** Proceed to a 1024px map-space tiled static cache experiment with lazy tile materialization/streaming and viewport culling. Do not promote the current all-resident shadow directly into production.

Rationale:

- full-cache is fastest in CI but concentrates the entire 8,612 x 6,898 cache into one large presentation image and offers no residency partitioning;
- 512px tiles create excessive wide-view submission pressure, reaching 437 p50 draw calls at full-theatre view;
- 1024px tiles retain most of the measured raster speedup, use materially fewer draw calls than 512, and provide the partition boundary needed to load/retain only visible or near-visible tiles later.

A production renderer switch remains unauthorized. The next experiment must preserve polygon authority, materially reduce the current ~302 MiB shadow-memory penalty, retain the measured frame-time gain, pass owner-native profiling, and receive independent visual/interaction review.

## Native-performance caveat

All absolute frame times above are Mesa llvmpipe measurements and are not owner-native acceptance targets. The bracketed A/B deltas are CI experimental evidence. Any claim that the eventual implementation materially improves production performance still requires identical-camera testing on the owner/native machine with debug disabled.

No Phase A or Phase B measurement changes polygon geometry, topology, stable IDs, water policy, campaign state, backend command architecture, or production rendering behavior.
