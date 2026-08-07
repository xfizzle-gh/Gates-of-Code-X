# Gate 0 provisional generator benchmark

Issue: #131  
Parent: #130  
Pinned upstream: `Thomas-Holtvedt/opengs-maptool@06e7ec8517bd45872cf44d77cb8784e5ffca49bb`

## Status

**Provisional evidence only. Gate 0 is not complete.**

The execution sandbox could access upstream source through the connected GitHub API but could not clone `github.com`. The initial measurements therefore used a local reconstruction of the pinned core algorithms from `config.py`, `logic/utils.py`, and `logic/numb_gen.py`.

The committed `tools/opengs_eval/benchmark_upstream.py` does not use that reconstruction. It requires an exact Git checkout, verifies the pinned commit, imports the upstream generation modules directly, runs each repetition in a separate process, and writes structured results.

## What this benchmark measures

- raster territory and province generation behavior;
- approximate scaling at 440, 1000, 2000, 3514, and 5000 provinces;
- peak traced allocation and process RSS signals;
- non-jagged versus jagged cost;
- repeated-run label hashes;
- exceptions and incomplete counts.

It does not measure:

- Europe-Mediterranean geographic quality;
- legal fitness of any real input dataset;
- polygon extraction;
- multipart or hole preservation;
- triangulation;
- exact shared-edge adjacency;
- Gates click testing;
- Godot frame time or draw calls.

## Synthetic scale results

| Case | Raster | Territories | Provinces | Wall time | Traced peak | Error |
|---|---:|---:|---:|---:|---:|---|
| sanity | 700x460 | 48 | 440 | 0.98 s | 24.0 MiB | none |
| 1000 | 900x600 | 80 | 1000 | 1.65 s | 40.2 MiB | none |
| 2000 | 1050x700 | 104 | 2000 | 2.66 s | 53.2 MiB | none |
| Earth3 count | 1200x800 | 140 | 3514 | 4.08 s | 67.3 MiB | none |
| jagged Earth3 count | 1200x800 | 140 | 3514 | 19.57 s | 92.7 MiB | none |
| stress | 1400x900 | 185 | 5000 | 6.31 s | 93.8 MiB | none |

The preliminary jagged run was approximately 4.8 times slower than the preliminary non-jagged 3514 run.

These times are specific to the synthetic inputs and this Linux sandbox. They are not performance promises for the final projected theatre inputs.

## Nondeterminism evidence

The same 3514 configuration was run three times.

| Run | Label SHA-256 |
|---:|---|
| 1 | `c1a500763295d8a9bdeaa2a5b22b5d7336cc210ac9898546925a379fe5c0e242` |
| 2 | `b40435a8d592ebc1c27cfc570b025493f421f021a1850607bd8a6372c4c35db2` |
| 3 | `ea750ba460885836d8112bd0e5c44c7cbd5a5fa6ebff5f5816e2868e2946075a` |

All three hashes differ.

This matches the pinned source behavior:

1. `create_region_map()` calls `random_seeds()` without `rng_seed`.
2. `random_seeds()` calls `numpy.random.default_rng(rng_seed)`.
3. With `rng_seed=None`, each generation receives fresh nondeterministic entropy.
4. Lloyd relaxation also accepts a seed but is called without one.
5. Jagged-border noise uses a hard-coded seed of `42`, which is deterministic in isolation but is not sufficient to make the whole run deterministic.

Gate 1 must thread mandatory named seeds through every stochastic operation and stabilize ordering and encoding.

## Failure and resource behavior found in source

- The UI generation path processes heavy work synchronously and calls `QApplication.processEvents()` for progress updates.
- Upstream issue tracking already identifies UI freezing as a concern.
- Exact RGB matching is used for ocean, lake, boundary, and terrain classification. Slight gradients or resampling can change classification.
- Jagged-border cleanup removes every disconnected component except the largest component for a generated region. This is a significant risk for legitimate multipart geography and cannot be used as the Gates polygon-island policy.
- Terrain classification samples only the province center.
- Exported metadata does not provide the complete Gates polygon, triangle, shared-edge, adjacency, or spatial-index contracts.

## Provenance status

A plausible legal evaluation path exists using public-domain Natural Earth layers plus attributed CC BY sources where additional terrain, city, or lake detail is required. The candidate inventory is recorded in `provenance_inventory.json`.

No exact geographic archive has been downloaded, checksummed, or approved yet. Gate 0 therefore remains open.

OpenStreetMap remains conditional because ODbL attribution and derivative-database obligations require project-specific review. Copernicus DEM remains conditional until an exact product and current license annex are selected.

## Required exact-checkout run

From a clean checkout of Gates and the pinned upstream repository:

```powershell
py -3.11 -m pip install numpy==2.3.5 pillow==12.0.0 scipy==1.16.3 psutil
py -3.11 tools/opengs_eval/benchmark_upstream.py `
  --upstream-root ..\opengs-maptool `
  --output build\opengs_eval\gate0_benchmark.json
```

The harness refuses to run if the upstream Git commit does not exactly match the pin.

## Gate 0 remaining work

- Run the committed harness against the exact pinned checkout on the normal Windows development machine.
- Run it in a clean CI job and retain the JSON artifact.
- Download and pin the exact candidate geographic source releases.
- Record source archive checksums, projection, bounds, and transformations.
- Benchmark the real aligned input dimensions.
- Document failures, output counts, and memory behavior from the exact run.
- Complete the feasibility recommendation and stop for owner review.

## Current recommendation

Continue Gate 0. Do not begin Gate 1 yet.

The generator appears computationally feasible enough to justify the exact benchmark and provenance work, but reproducibility, real-input behavior, and legal artifact pinning are still unresolved.
