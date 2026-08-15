# #212 Earth3 rendering comparison

## Corrected ordinary-player baseline

The historical ~3.7k draw-call figure was contaminated by developer `MapDebug` presentation. PR #238 established the controlled debug-off baseline with a reversible `OFF -> ON -> OFF restored` test:

| Mode | Draw calls p50 | Draw calls p95 | Frame p50 ms | Frame p95 ms |
|---|---:|---:|---:|---:|
| Debug OFF | 205 | 205 | 161.558 | 165.906 |
| Debug ON | 3,764 | 3,764 | 265.424 | 279.382 |
| Debug OFF restored | 205 | 205 | 160.581 | 164.458 |

PR #238 provenance: measurement commit `f8f1ff072bc0b9a89c82f210e506d56b372918f8`, workflow run `31849403512`, artifact `9237017273`, Godot 4.7, Ubuntu 24.04/Xvfb/OpenGL Compatibility/Mesa llvmpipe, 1920x1080, 24 frames per mode, exact 3,514-province Earth3 authority.

## Why the first PR #239 frame-time table was rejected

The first #239 profiler used one process-first baseline and then measured all disabled layers sequentially. Every mode got a fresh scene, but renderer/resource/font/shader caches survived inside the same Godot process. That made the original frame-time deltas vulnerable to order/cache drift.

The warning sign was strong: disabling the ocean removed only 2 primitives yet appeared about 65.6 ms faster, while labels, counters, sites, routes and proof overlays all clustered around roughly 52-55 ms despite very different workloads.

Independent review `4942009996` correctly required a local reversible control for every probe.

## Corrected bracketed experiment

PR #239 now uses this schedule for every presentation category:

`baseline_before -> layer_disabled -> baseline_after`

Each sample still instantiates a fresh `main.tscn`, but the three samples stay in the same Godot process. The layer delta is calculated against the arithmetic midpoint of its two surrounding local baselines.

The harness also burns one unreported process-warmup baseline before any recorded bracket. A bracket fails if either p50 or p95 wall-frame baseline drift exceeds 15%, or if surrounding baseline draw-call or primitive counts differ.

Corrected measurement provenance:

- head: `59f1db2f3f9c55b839ebd73d38192458b90612c9`;
- workflow run: `31852606988`;
- artifact: `9238086887`;
- Godot 4.7 stable;
- Ubuntu 24.04, Xvfb, OpenGL Compatibility, Mesa llvmpipe;
- 1920x1080;
- 24 frames per sample;
- `MapDebug` disabled;
- exact 3,514-province Earth3 authority;
- deterministic province-picking parity preserved.

The process-first warmup measured 274.483 ms p50 / 285.934 ms p95. Later local baselines were generally around 215-219 ms p50. That directly confirms the audit finding: process-first-use work materially contaminated the old single-baseline frame-time attribution.

All corrected brackets passed. Maximum observed local baseline drift was only 2.66%, well below the declared 15% rejection threshold, with exact 205 draw calls and 456,565 primitives in every surrounding ordinary baseline.

### Corrected controlled deltas

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

Positive frame deltas mean the disabled sample was faster than its local bracketed baseline. Small negative values should be treated as noise/no measurable improvement, not as evidence that rendering the layer is beneficial.

The contact/battle probe remains semantically non-additive: suppressing it raises draw calls by 7 while reducing frame time. It should not be ranked as an independent accounting bucket.

The UI-only residual floor, with all measured map presentation categories suppressed, measured 58 draw calls / 1,744 primitives and 41.740 ms p50 / 42.589 ms p95. Its surrounding local baseline was 215.632 ms p50 / 222.296 ms p95. It is a residual diagnostic, not a one-layer delta.

## What the corrected experiment supports

The independent audit was correct that the first frame-time ranking overstated layer costs. The corrected controls materially reduce most sparse-overlay deltas from the old ~52-55 ms cluster to approximately zero through single-digit milliseconds.

The two large static geometry categories nevertheless remain clearly separated from those sparse overlays:

- land fill removes 286,495 primitives and improves the local bracket by about 70 ms p50 / 72 ms p95;
- shared borders remove 163,988 primitives and improve the local bracket by about 38 ms p50 / 37 ms p95;
- together they still account for roughly 450k of 456,565 ordinary baseline primitives.

The exact old claims of ~123 ms for land and ~90 ms for borders are retired. The corrected controlled values above are the only frame-time attribution values PR #239 should cite.

The ocean result remains disproportionate to its two reported primitives, so it should be treated as a measured presentation-node effect requiring follow-up rather than interpreted as primitive rasterization cost.

## Phase A decision

Phase A now supports proceeding to #212 Phase B as a **debug-only presentation experiment**, not a production switch.

The next experiment should compare:

1. one full cached-theatre static presentation layer set;
2. 512/1024 tiled cached presentation with viewport culling.

The goal is to remove repeated static land/border presentation work while retaining the current Earth3 polygon/topology/stable-ID data as the sole simulation, validation and picking authority. The existing polygon path must remain available in parallel for parity checks.

Required parity remains unchanged: same stable province IDs, owner colors, water non-selection, selection/legal-target identity, operational coordinates, and campaign/map authority bytes.

Phase C icon-atlas work still matters for draw-call reduction, but the corrected Phase A evidence does not show sparse counters/labels/sites/routes dominating wall-frame cost on this fixture.

## Native-performance caveat

All absolute frame times above are Mesa llvmpipe measurements and are not owner-native acceptance targets. The bracketed A/B deltas are valid CI experimental evidence. Any claim that Phase B materially improves production performance still requires identical-camera testing on the owner/native machine with debug disabled.

No Phase A measurement changes polygon geometry, topology, stable IDs, water policy, campaign state, backend command architecture, or production rendering behavior.
