# #212 Phase A: corrected Earth3 render baseline

## Finding

The long-carried ~3.7k draw-call figure from the #74 interactive profiler is not an ordinary-player presentation baseline.

The #74 profiler enables `MapDebug` before sampling. With `show_anchors` enabled, `MapDebug.draw()` iterates the complete loaded province set and draws one anchor circle per province. Earth3 currently contains 3,514 provinces.

PR #238 adds a same-camera A/B profiler to measure that cost directly without changing the production renderer or Earth3 authority.

## Measurement provenance

- Measurement commit: `f8f1ff072bc0b9a89c82f210e506d56b372918f8`
- Workflow run: `31849403512`
- Artifact: `issue-212-map-attribution`, ID `9237017273`
- Godot: 4.7 stable
- Runner: Ubuntu 24.04, Xvfb, OpenGL Compatibility, Mesa llvmpipe
- Viewport: 1920x1080
- Samples: 24 frames per mode after warmup
- Authority: exact 3,514-province Earth3 polygon dataset

## Same-run attribution

| Mode | Draw calls p50 | Draw calls p95 | Frame p50 ms | Frame p95 ms |
|---|---:|---:|---:|---:|
| Debug OFF | 205 | 205 | 161.558 | 165.906 |
| Debug ON | 3,764 | 3,764 | 265.424 | 279.382 |
| Debug OFF restored | 205 | 205 | 160.581 | 164.458 |

Debug ON adds exactly 3,559 p50/p95 draw calls over the ordinary debug-off presentation in this run. It also adds 113.476 ms to p95 wall frame time under the CI software renderer.

The restoration control returns to 205 draw calls, demonstrating that the difference belongs to the debug presentation rather than accumulated state from the measurement sequence.

## Authority and picking control

Debug toggling did not alter authority or selection identity.

The profiler required the exact 3,514-province Earth3 dataset and repeated a deterministic province-picking suite before debug, with debug enabled, and after debug was disabled again. All sampled points returned the same stable province IDs in all three modes.

No polygon geometry, topology, stable ID, water policy, campaign state, backend command path, or production renderer was changed by this checkpoint.

## Interpretation

The previous ~3.7k draw-call number should be retired as a production-rendering baseline. Approximately 94.6% of the 3,764 debug-enabled draw calls in this controlled run disappear when developer debug presentation is disabled.

This does **not** mean #212 is solved. The actual debug-off presentation still records 205 draw calls and remains slow on the CI llvmpipe renderer. Owner-native P6 feedback also established that the strategic application remains slow in real play.

The absolute CI frame times in this document are not native acceptance targets because llvmpipe is a software renderer and differs from the owner acceptance machine. They are valid for same-run A/B attribution. Accepted production performance claims still require the existing profiler on the owner/native machine with debug disabled.

## Next Phase A work

Continue attribution from the corrected 205-call ordinary-player baseline. Measure production-visible categories one at a time before choosing an architectural rewrite:

1. land fill mesh, ocean, and shared borders;
2. federal/secondary outlines;
3. formation counters and stack badges;
4. infrastructure/site markers;
5. labels and glyphs;
6. routes and movement presentation;
7. contact/pending-battle presentation;
8. UI chrome outside the map.

The next implementation decision should be based on those measurements. Do not justify a raster/tiled rewrite, icon batching, or other production renderer change using the retired debug-enabled ~3.7k figure.
