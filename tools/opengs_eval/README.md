# OpenGS evaluation tooling

This directory contains isolated research tooling for #130 and #131.

It does not contain the OpenGS Godot runtime, production map assets, or a production map generator.

## Upstream pin

The Gate 0 benchmark requires:

```text
Thomas-Holtvedt/opengs-maptool
06e7ec8517bd45872cf44d77cb8784e5ffca49bb
```

The script verifies the checkout with `git rev-parse HEAD` and fails closed when the commit differs.

## Install benchmark dependencies

The pinned upstream project declares NumPy, Pillow, SciPy, PyQt6, and tkinterdnd2. The Gate 0 harness imports only the core generation functions and installs a no-op PyQt import stub, so the benchmark path needs:

```powershell
py -3.11 -m pip install numpy==2.3.5 pillow==12.0.0 scipy==1.16.3 psutil
```

This does not alter upstream code. Removing PyQt from an actual generation path belongs to Gate 1, not Gate 0.

## Run

```powershell
py -3.11 tools/opengs_eval/benchmark_upstream.py `
  --upstream-root ..\opengs-maptool `
  --output build\opengs_eval\gate0_benchmark.json
```

The suite includes:

- 440-province sanity generation;
- approximately 1000 and 2000 provinces;
- three repeated 3514-province generations;
- one 3514-province jagged generation;
- one 5000-province stress generation.

Each repetition runs in a separate Python process so memory and failure evidence are not hidden by earlier cases.

## Interpretation

The harness uses synthetic aligned land and density inputs. It measures generator feasibility and nondeterminism only.

It does not prove:

- legal suitability of a geographic dataset;
- Europe-Mediterranean visual quality;
- polygon topology;
- Gates runtime compatibility;
- production performance.

The output must remain a Gate 0 research artifact. It must not be installed as a campaign map.

## Attribution

The upstream pin and MIT license are recorded in:

- `upstream_pin.json`
- `LICENSE.opengs-maptool`

Any later copied or modified upstream modules must retain the required MIT notice and record their original hashes and local differences.
