# Gate 0 exact pinned CI benchmark

Issue: #131  
Parent: #130  
Workflow run: `31223766220`  
Benchmark head: `5ccb354154e34484803ef0fc7793f19b3c4e5cb9`

## Result

The exact pinned OpenGS Map Tool source completed the synthetic Gate 0 suite on both Linux and Windows.

Both jobs:

- checked out `Thomas-Holtvedt/opengs-maptool@06e7ec8517bd45872cf44d77cb8784e5ffca49bb`;
- verified the upstream Git commit in the benchmark process;
- passed the Gate 0 authority and provenance contract tests;
- completed 440, 1000, 2000, repeated 3514, jagged 3514, and 5000-province scenarios;
- uploaded complete JSON benchmark artifacts.

This proves synthetic generator-scale feasibility only. It does not complete Gate 0.

## Exact 3514 comparison

| Platform | Non-jagged wall time, three runs | Memory signal | Unique label hashes |
|---|---:|---:|---:|
| Linux | 6.98 s, 6.92 s, 6.87 s | 176.6 to 185.0 MB peak RSS | 3 of 3 |
| Windows | 9.87 s, 9.83 s, 9.88 s | approximately 77.2 MB final RSS; 81.5 MB traced peak | 3 of 3 |

Windows does not expose process peak RSS through the standard-library path used by the harness. The Windows value labeled RSS is final RSS from `psutil`; traced Python allocations are recorded separately.

## Nondeterminism confirmed

The exact source generated three different label hashes from three identical 3514 configurations on Linux and three different hashes on Windows.

This confirms that Gate 1 must make seeds mandatory and thread them through all stochastic operations. A single fixed seed in the jagged-noise helper is not enough because territory and province seed placement and Lloyd sampling remain unseeded.

## Jagged-border cost

| Platform | Non-jagged 3514 | Jagged 3514 | Approximate multiplier |
|---|---:|---:|---:|
| Linux | about 6.9 s | 24.9 s | 3.6x |
| Windows | about 9.9 s | 32.7 s | 3.3x |

Jagged generation remains feasible at the synthetic resolution, but it is a significant cost multiplier.

The current upstream cleanup also removes all but the largest connected component of each jagged-generated region. That behavior cannot be treated as the Gates island or multipart-geometry policy.

## Stress result

| Platform | Provinces | Raster | Wall time | Memory signal |
|---|---:|---:|---:|---:|
| Linux | 5000 | 1400x900 | 9.65 s | 202.3 MB peak RSS |
| Windows | 5000 | 1400x900 | 13.89 s | 80.8 MB final RSS; 99.2 MB traced peak |

No exception occurred in either stress run.

## Artifact records

### Linux

- artifact ID: `9011353399`
- artifact name: `opengs-gate0-Linux`
- artifact digest: `sha256:4ce31f8e07220dc47088b050821d057501549c45a0e085275632f73672286f58`
- benchmark result SHA-256: `c8a97303e9cfe8adfb40e77130cf9cc80dca3561cfb8bd35656db4948521b725`

### Windows

- artifact ID: `9011373965`
- artifact name: `opengs-gate0-Windows`
- artifact digest: `sha256:ce8340ebd737db40ac76866cc095eff1dac8f60367010ad319475d6148f64b92`
- benchmark result SHA-256: `534683c5bc6bfada554973f88a5a7c8bef2d41dc2ce4f163183f01632b22ee91`

The compact committed record is `gate_0_exact_ci_summary.json`. The workflow artifacts retain the complete per-run JSON.

## What is now established

- The pinned upstream source can generate approximately Earth3-scale raster regions on Linux and Windows.
- A 5000-province synthetic stress case completes on both platforms.
- Unmodified generation is nondeterministic.
- Jagged generation has a measurable cost increase.
- The headless benchmark can exercise core upstream functions without installing or integrating the OpenGS Godot runtime.
- No Earth3 production map file is required for this work.

## What remains unresolved

- exact geographic source archive selection and checksums;
- projection and aligned input dimensions;
- real Europe-Mediterranean runtime and memory behavior;
- visual and geographic quality;
- polygon rings, holes, multipart components, triangles, borders, adjacency, and anchors;
- Gates non-selectable-water conversion;
- Godot click parity and production performance.

## Gate recommendation

Continue Gate 0 only.

The synthetic scale risk is low enough to proceed with exact source-data pinning and a real aligned-input benchmark. Gate 1 remains blocked until the Gate 0 feasibility report is complete and approved by the owner.
