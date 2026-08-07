# OpenGS evaluation tooling

This directory contains isolated research tooling for #130 and #131.

It does not contain the OpenGS Godot runtime, production map assets, or a production map generator.

## Pins

### OpenGS Map Tool

```text
Thomas-Holtvedt/opengs-maptool
06e7ec8517bd45872cf44d77cb8784e5ffca49bb
```

### Natural Earth

```text
nvkelso/natural-earth-vector
v5.1.2
f1890d9f152c896d250a77557a5751a93d494776
```

Exact source blob IDs are recorded in `natural_earth_pin.json`.

The tools verify Git commits, Git blob hashes, and generated input checksums. They fail closed when a pin differs.

## Synthetic benchmark

Install:

```powershell
py -3.11 -m pip install numpy==2.3.5 pillow==12.0.0 scipy==1.16.3 psutil
```

Run:

```powershell
py -3.11 tools/opengs_eval/benchmark_upstream.py `
  --upstream-root ..\opengs-maptool `
  --output build\opengs_eval\gate0_benchmark.json
```

The suite includes 440, 1000, 2000, repeated 3514, jagged 3514, and 5000-province synthetic cases. Every repetition runs in a separate Python process.

## Natural Earth input build

Additional dependencies:

```powershell
py -3.11 -m pip install shapely==2.1.2 pyproj==3.7.2
```

Build one projection-aligned input set:

```powershell
py -3.11 tools/opengs_eval/build_natural_earth_inputs.py `
  --natural-earth-root ..\natural-earth-vector `
  --output build\opengs_eval\natural_earth_inputs `
  --width 2048 `
  --height 1536
```

Run the exact upstream territory and province generators against it:

```powershell
py -3.11 tools/opengs_eval/benchmark_natural_earth.py `
  --upstream-root ..\opengs-maptool `
  --input-root build\opengs_eval\natural_earth_inputs `
  --scenarios tools\opengs_eval\natural_earth_scenarios.json `
  --output build\opengs_eval\natural_earth_benchmark.json
```

The real-input benchmark invokes upstream `generate_territory_map()` and `generate_province_map()` through a minimal non-GUI layout object. It does not copy or modify those functions.

## Current evidence

- Synthetic Linux and Windows run: Actions `31223766220`
- Natural Earth run: Actions `31224683315`
- Real-input artifact: `9011772386`
- Real-input artifact digest: `sha256:eb814a87dac3bcc65a315291b5167c8587aa8858dfa9a002d17b786d227865ea`

The nominal 3514 real-input request generated 3795 records because OpenGS added 281 connected lakes as additional provinces.

Three identical non-jagged real-input runs produced three different province-image hashes. Gate 1 must make all randomness explicit and prove byte-identical regeneration.

## Interpretation

These tools measure source provenance, generation feasibility, resource behavior, nondeterminism, and direct OpenGS output behavior.

They do not provide:

- Gates polygon rings;
- multipart and hole preservation;
- triangulation;
- exact shared-edge adjacency;
- Gates spatial indexing;
- stable production IDs;
- production Godot performance;
- production map replacement authorization.

All output remains Gate 0 research. It must not be installed as a campaign map.

## Attribution

The OpenGS pin and MIT license are recorded in:

- `upstream_pin.json`
- `LICENSE.opengs-maptool`

Natural Earth is public domain. Its exact Gate 0 pin and source checksums are recorded in:

- `natural_earth_pin.json`
- `docs/research/opengs-evaluation/gate_0_natural_earth_summary.json`

Any later copied or modified OpenGS modules must retain the required MIT notice and record original hashes and local differences.
