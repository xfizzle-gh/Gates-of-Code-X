# Issue 212 Phase D UX / LOD evidence

Measurement head: `3cadb7fd8dfe637f04f9abdc612fe776a4848bd4`

Focused workflow: `Issue 212 UX LOD` run `31865769536` — **PASS**

Artifact: `issue-212-ux-lod` (`9241988723`), SHA-256 `85fb313c8fdf5933925544da91ea097527d83284993240328f29345ab3f25fb9`

## Result

Phase D passes as a debug-only strategic-map LOD, layer-control, and cached-minimap proof. The profiler kept the inherited 15% p50/p95 local-drift rejection threshold unchanged and used 24-frame locally bracketed samples. Every profile passed. Worst observed baseline drift was 1.03% (full-theatre p95), well inside the existing fail-closed limit.

| Profile | View scale | Frame p50 | Frame p95 | Draws | Primitives | Draws removed | Primitives removed |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full theatre | 1.0 | 194.849 ms | 202.701 ms | 80 | 452,663 | 125 | 3,902 |
| Operational | 2.0 | 279.578 ms | 290.016 ms | 129 | 453,675 | 78 | 2,956 |
| Detailed | 3.0 | 267.938 ms | 270.505 ms | 159 | 454,917 | 48 | 1,714 |
| All measurable disabled | 3.0 | 267.149 ms | 270.266 ms | 57 | 452,539 | 150 | 4,092 |

The frame-time differences versus each profile's local all-current-layers baseline were small improvements rather than regressions: 3.205 ms p50 / 4.777 ms p95 at full theatre, 2.432 / 1.727 ms operational, 2.567 / 1.430 ms detailed, and 2.464 / 4.206 ms with all currently measurable layers disabled.

## LOD and recurring-work contract

The policy and layer-control prototypes have no `_process()` loop. Policy is applied once per fresh profiler scene. Full-theatre LOD keeps formation symbols while suppressing ordinary names, infrastructure/sites, operational routes, and debug overlays. Operational zoom restores infrastructure/sites and routes while ordinary names remain suppressed. Detailed zoom honors the currently measurable layer toggles.

The issue-required keys for supply, objectives, and fog/intelligence are present in the control contract, but the current #212 fixture has no independent presentation surface for those three. They remain explicitly marked contract-only rather than receiving fabricated measurements.

## Cached minimap

The prototype minimap is one 250x200 downsampled `ImageTexture` derived from the static Earth3 presentation cache, with selection plus seven lightweight front/contact overlay points. It has no process loop and does not create a second live Earth3 scene or PolygonMap.

## Authority controls

PolygonMap remains live. Manifest, polygon dataset, and snapshot fixture SHA-256 values were identical before and after the run:

- manifest: `614a926e79f11e3cfac8c867c7bacce107fc69344b17fabb6b4545cdeaa6a357`
- polygon dataset: `4aadab4b5106bbfa4c2d37e8173c3d1675f35a448cbd7f32a8b871c464ce1b84`
- snapshot fixture: `b405550730f2af7d8bd82ca82ee27924431d9ac0c1dd6b8a5bef979828585ef3`

## Decision

**PASS as a debug-only Phase D proof.** This evidence does not authorize a production renderer switch. The Phase D prototype remains unmounted from production `main.tscn` and must still pass fresh exact-head CI after this evidence commit plus fresh independent exact-head review before merge eligibility.
