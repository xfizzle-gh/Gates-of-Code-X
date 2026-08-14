# #212 Earth3 rendering comparison

## Corrected baseline

The long-carried ~3.7k draw-call figure from the #74 interactive profiler is not an ordinary-player presentation baseline.

The #74 profiler enables `MapDebug` before sampling. With `show_anchors` enabled, `MapDebug.draw()` iterates the complete loaded province set and draws one anchor circle per province. Earth3 currently contains 3,514 provinces.

PR #238 added a same-camera A/B profiler and measured:

| Mode | Draw calls p50 | Draw calls p95 | Frame p50 ms | Frame p95 ms |
|---|---:|---:|---:|---:|
| Debug OFF | 205 | 205 | 161.558 | 165.906 |
| Debug ON | 3,764 | 3,764 | 265.424 | 279.382 |
| Debug OFF restored | 205 | 205 | 160.581 | 164.458 |

Debug presentation added exactly 3,559 draw calls in that controlled run. The old ~3.7k figure is retired as a production-rendering baseline.

PR #238 provenance:

- measurement commit `f8f1ff072bc0b9a89c82f210e506d56b372918f8`;
- workflow run `31849403512`;
- artifact `9237017273`;
- Godot 4.7 stable;
- Ubuntu 24.04, Xvfb, OpenGL Compatibility, Mesa llvmpipe;
- 1920x1080, 24 frames per mode;
- exact 3,514-province Earth3 authority.

## Phase A production-layer attribution

PR #239 then measured the real debug-OFF path with one production-visible category disabled at a time. Every mode used a fresh `main.tscn`, the same Earth3 snapshot/fixture and camera, and deterministic province-picking parity.

Measurement provenance:

- measurement head `454a044899e0917f4f60630a37a28a757d0ae964`;
- workflow run `31851127955`;
- artifact `9237595280`;
- same 1920x1080 llvmpipe environment;
- 24 rendered frames per mode;
- `MapDebug` disabled for every mode;
- exact 3,514-province Earth3 authority and stable picking preserved.

### One-layer-disabled measurements

| Disabled category | Draw calls p50 | Draw-call delta | Primitives removed | Frame p50 ms | p50 improvement | Frame p95 ms | p95 improvement |
|---|---:|---:|---:|---:|---:|---:|---:|
| None, baseline | 205 | 0 | 0 | 269.038 | 0 | 278.971 | 0 |
| Land fill, 4 chunks | 201 | 4 | 286,495 | 146.278 | **122.760** | 147.939 | **131.032** |
| Shared borders | 204 | 1 | 163,988 | 179.180 | **89.858** | 180.696 | **98.275** |
| Ocean mesh | 204 | 1 | 2 | 203.488 | 65.550 | 210.521 | 68.450 |
| Secondary/federal outlines | 157 | 48 | 1,714 | 214.279 | 54.759 | 218.371 | 60.600 |
| Labels/glyphs | 175 | 30 | 1,242 | 215.296 | 53.742 | 219.652 | 59.319 |
| Formation counters | 182 | 23 | 124 | 216.716 | 52.322 | 222.269 | 56.702 |
| Infrastructure/sites | 169 | 36 | 552 | 216.098 | 52.940 | 219.629 | 59.342 |
| Routes | 194 | 11 | 394 | 215.967 | 53.071 | 221.477 | 57.494 |
| Fixture/proof overlays | 127 | 78 | 2,956 | 213.716 | 55.322 | 220.886 | 58.085 |
| UI-only residual floor | 58 | n/a | 454,821 versus baseline | 42.415 | n/a | 43.167 | n/a |

The pending-contact suppression produced a non-additive/noisy result, including a higher draw-call count than baseline, so it is not treated as an independent accounting bucket. The Phase A harness deliberately warns that semantic categories overlap and their deltas must not be summed.

### What actually dominates

The key result is that **draw-call count and frame cost are not the same bottleneck**.

The largest ordinary presentation draw-call category in this fixture is the fixture/proof overlay family at 78 calls. Secondary outlines account for 48, infrastructure/sites 36, labels 30, formation counters 23, and routes 11.

But the dominant frame cost comes from static polygon rasterization:

- four land-fill draw calls carry roughly **286,495 primitives** and removing them improved p50 by about **122.8 ms** in the same llvmpipe run;
- the single shared-border draw call carries roughly **163,988 primitives** and removing it improved p50 by about **89.9 ms**;
- together those two static categories account for about 450k of the baseline's 456,565 primitives.

So reducing 205 draw calls by batching sparse overlays alone would not attack the dominant measured CI rendering workload. Conversely, the old 3.7k debug number also does not justify a draw-call-centric rewrite.

## Phase A decision

Phase A supports proceeding to the issue's **Phase B debug-only raster/tiled presentation shadow mode**.

The experiment should cache or rasterize the expensive static visual geometry while preserving the existing Earth3 polygon/topology/stable-ID data as authority for simulation, validation and picking. It should evaluate both:

1. one full cached-theatre presentation layer set;
2. 512/1024 tiled cached presentation with viewport culling.

The authoritative polygon path must remain available in parallel for parity checks. The shadow renderer must prove the same stable province IDs, owner colors, water non-selection, legal-target identity, operational coordinates and campaign/map authority bytes.

Phase C icon-atlas work still matters because overlays contribute many of the remaining draw calls, but it should follow the static-geometry cache experiment rather than precede it.

## Native-performance caveat

Absolute frame times above are from Mesa llvmpipe and are not owner-native acceptance targets. They are valid for same-run A/B attribution. Any claim that Phase B materially improves production performance still requires identical-camera testing on the owner/native machine with debug disabled.

No Phase A measurement changed polygon geometry, topology, stable IDs, water policy, campaign state, backend command architecture or production rendering behavior.
