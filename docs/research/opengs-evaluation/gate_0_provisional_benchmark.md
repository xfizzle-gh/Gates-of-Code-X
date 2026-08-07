# Gate 0 provisional generator benchmark

Issue: #131  
Parent: #130  
Pinned upstream: `Thomas-Holtvedt/opengs-maptool@06e7ec8517bd45872cf44d77cb8784e5ffca49bb`

## Status

This file preserves the first sandbox reconstruction benchmark for audit history.

It is superseded for scale evidence by:

- `gate_0_exact_ci_benchmark.md`
- `gate_0_exact_ci_summary.json`
- Linux and Windows artifacts from Actions run `31223766220`

Gate 0 remains open because no exact real geographic input set has been pinned and benchmarked.

## Why this provisional run existed

The execution sandbox could access upstream source through the connected GitHub API but could not clone `github.com`. The initial measurements therefore used a local reconstruction of the pinned core algorithms from `config.py`, `logic/utils.py`, and `logic/numb_gen.py`.

The committed `tools/opengs_eval/benchmark_upstream.py` does not use that reconstruction. It requires an exact Git checkout, verifies the pinned commit, imports the upstream generation modules directly, runs each repetition in a separate process, and writes structured results.

## Synthetic reconstruction results

| Case | Raster | Territories | Provinces | Wall time | Traced peak | Error |
|---|---:|---:|---:|---:|---:|---|
| sanity | 700x460 | 48 | 440 | 0.98 s | 24.0 MiB | none |
| 1000 | 900x600 | 80 | 1000 | 1.65 s | 40.2 MiB | none |
| 2000 | 1050x700 | 104 | 2000 | 2.66 s | 53.2 MiB | none |
| Earth3 count | 1200x800 | 140 | 3514 | 4.08 s | 67.3 MiB | none |
| jagged Earth3 count | 1200x800 | 140 | 3514 | 19.57 s | 92.7 MiB | none |
| stress | 1400x900 | 185 | 5000 | 6.31 s | 93.8 MiB | none |

Three repeated reconstructed 3514 runs produced three different label hashes. The exact Linux and Windows jobs later confirmed the same nondeterministic behavior directly from the pinned checkout.

## Limitations

This reconstruction did not establish:

- exact upstream working-tree execution;
- Europe-Mediterranean geographic quality;
- legal suitability of real input data;
- polygon extraction or topology;
- Gates runtime compatibility;
- production performance.

Refer to `gate_0_exact_ci_benchmark.md` for the authoritative synthetic scale evidence from the pinned upstream checkout.
