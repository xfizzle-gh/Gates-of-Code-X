# #212 lazy 1024 residency experiment

Measurement head: `9e2a8a73d2fdb97d33a7a587b0ee3d4adffbcd39`

Focused workflow: `31863348773`

Artifact: `9241311218`, SHA-256 `98c7aab50e42283c006589559d6cf284cc43bee6aa8364b818ed5ff4359c79ed`

The experiment keeps the Phase B 1024px partition and exact Earth3 polygon authority, but creates a tile texture only when its map rectangle intersects the viewport plus a 96px prefetch margin. Cold tiles are evicted after two frames. Measurements use 24-frame local polygon brackets and retain the existing 15% p50/p95 rejection gate. Maximum observed baseline drift was 1.38%.

| Scenario | Mode | Frame p50 | Frame p95 | Visible p50 | Resident p50 | Video memory | Difference from all-resident |
|---|---|---:|---:|---:|---:|---:|---:|
| Idle full theatre | all-resident 1024 | 90.234 ms | 91.267 ms | 63 | 63 | 368.156 MiB | control |
| Idle full theatre | lazy 1024 | 90.735 ms | 92.283 ms | 63 | 63 | 368.156 MiB | +0.501 ms, 0 MiB saved |
| Continuous pan | all-resident 1024 | 88.872 ms | 89.813 ms | 63 | 63 | 368.156 MiB | control |
| Continuous pan | lazy 1024 | 89.233 ms | 90.654 ms | 63 | 63 | 368.156 MiB | +0.361 ms, 0 MiB saved |
| Continuous zoom | all-resident 1024 | 91.332 ms | 95.005 ms | 28 | 63 | 368.157 MiB | control |
| Continuous zoom | lazy 1024 | 93.697 ms | 104.899 ms | 35 | 40 | 263.616 MiB | +2.365 ms, 104.541 MiB saved |

At zoom, lazy residency reduces p50 resident tiles from 63 to 40 and estimated resident tile RGBA8 storage from 226.614 MiB to 148.203 MiB. The measured video-memory reduction is about 104.5 MiB. The cost is about 2.4 ms p50 versus the all-resident 1024 control, while remaining about 161.2 ms p50 faster than its local polygon baseline on CI llvmpipe.

At full-theatre and the current wide pan, the viewport still intersects all 63 tiles. Lazy materialization therefore provides no resident-memory reduction there. This is a real design limitation: lazy 1024 residency alone cannot solve the wide-view memory penalty.

Authority controls passed. Manifest, polygon dataset, and fixture hashes were unchanged; PolygonMap remained live. A separately generated production player-shell snapshot rebuilt 63 non-empty real legal targets and preserved exact selection/legal-target identity through the lazy pan/zoom proof.

## B2 decision

Result: **PASS WITH WIDE-VIEW LIMIT**.

Keep 1024px partitioning as a useful zoomed-view residency mechanism, but do not treat lazy loading alone as the production memory design. A production-oriented path needs a cheaper full-theatre representation or LOD strategy for the wide view, then 1024px lazy residency for closer views.

No production renderer switch is authorized by this experiment. Owner-native profiling and fresh independent review remain required.
