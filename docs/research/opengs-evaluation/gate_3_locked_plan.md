# OpenGS Gate 3 locked implementation plan

Issue: #134  
Parent: #130  
Draft pull request: #158  
Required Gate 2 starting commit: `62063d70d2bb94f41b4d997578c02556003e9a72`  
Candidate ID: `opengs_gate3_europe_mediterranean_3514_candidate`

## Scope and stop boundary

Gate 3 builds one isolated Europe-Mediterranean comparison candidate through the accepted Gate 1 generator and Gate 2 geometry adapter. It remains research-only, non-default, debug-only, and artifact-only. It does not replace Earth3, register a production map, create campaign authority, or begin Gate 4.

The exact approved configuration is locked by canonical SHA-256:

`b4531f78351871fb91dc1f09e9734d14e9e9870bd9b42a869375af7e908d5d74`

Any change to source paths or hashes, license terms, projection, crop, anchors, dimensions, counts, generator options, density values, terrain policy, Gate 2 threshold, water policy, or isolation policy requires a new material checkpoint on #134.

## Locked authority

### Source bytes

Gate 3 uses Natural Earth v5.1.2 only, from `nvkelso/natural-earth-vector` at exact commit `f1890d9f152c896d250a77557a5751a93d494776`.

The five authenticated roles are land, lakes, national boundary lines, populated places, and rivers. Authority is the exact Git blob at `<commit>:<path>`, read with `git cat-file blob`. Working-tree bytes are never source authority. Every source is authenticated by repository, ref, commit, path, Git blob SHA-1, SHA-256, byte size, and public-domain license record.

### Projection and theatre mask

Projection:

`+proj=laea +lat_0=45 +lon_0=20 +datum=WGS84 +units=m +no_defs`

The raster is 2048 by 1536. Longitude/latitude bounds are west -13, south 27, east 45, north 75.

The densified geographic boundary is projected and rasterized as authenticated `theatre_mask.png`. Pixels outside that polygon are no-data, not ocean. The Gate 3 adapter excludes them from both Gate 1 land and sea masks. Package inspection proves that Gate 1 background pixels exactly match the inverse theatre mask in both territory and province rasters.

The locked geography anchors cover Ireland, Great Britain, Scandinavia, Finland, Sicily, Crete, Cyprus, the North African coast, Anatolia, the Irish Sea, English Channel, western Mediterranean, Adriatic, Black Sea, Kattegat, and Baltic.

### Final hierarchy counts

The locked comparison target remains:

- land provinces: 3,299
- ocean provinces: 215
- requested province total: 3,514

The source-derived hierarchy is:

- land territories: 468
- ocean territories: 30

The 468 land territories preserve every four-connected non-lake land component after lakes are excluded from land seed eligibility. The 30 ocean territories preserve every authoritative ocean component retained by the policy below. Both hierarchy counts remain below their corresponding province targets.

### Ocean-component authority

Candidate ocean uses four-connected topology after the projected theatre mask is applied. A complement component is retained only when it touches the projected theatre boundary or contains a locked `expected: ocean` anchor. Every unanchored enclosed complement cavity is deterministically reclassified as land.

The input manifest and geography/water reports record raw, retained, and reclassified component and pixel counts, retention reasons, and the complete component ledger. Generation fails if retained components exceed the locked 30 ocean territories or any locked ocean anchor is not retained.

Natural Earth lakes remain separate non-selectable lake provinces and are never processed by the ocean-complement rule.

### Lake-aware territory parenting

Natural Earth lake pixels are excluded from land-territory seed eligibility. After the non-lake land territories are generated, lake pixels receive deterministic nearest-land-territory parent coverage. Territory centers are recalculated from the final parent raster. Gate 1 seed provenance is validated against the non-lake land mask, while the final child-union contract still requires land and lake province masks together to cover their parent territory exactly.

This adapter exists only in Gate 3 orchestration. Accepted Gate 1 and Gate 2 source files are unchanged.

### Exact grid-pinch splitting

Gate 3 retains the accepted Gate 2 exact directed-boundary trace. If a traced ring revisits a grid vertex nonconsecutively, the Gate 3 orchestration adapter recursively splits that self-touching walk into canonical simple cycles at the repeated vertex before the accepted Gate 2 component builder runs.

The splitter must preserve the complete directed boundary-segment multiset exactly. It rejects degenerate cycles, duplicate cycles, open cycles, any remaining repeated vertex, invalid Shapely polygons, or non-positive-area polygons. It does not smooth, buffer, move, add, delete, bridge, or otherwise repair geography. The accepted Gate 2 component assignment, holes, triangulation, adjacency, topology audit, inspection, and publication contracts remain unchanged.

### Density and terrain

Density deterministically combines populated places, national boundaries, rivers, coastline emphasis, and a bounded background baseline. Coastline weighting is computed after authoritative ocean normalization.

Terrain remains a three-class legal baseline: land is plains, ocean is deep ocean, and lakes are lakes. It is not production terrain authority.

## Evidence-chain contract

The package must prove:

1. packaged config bytes match the locked canonical digest;
2. the input manifest authenticates that exact config and every generated input;
3. the packaged Gate 1 recipe digest matches the Gate 1 run manifest;
4. Gate 1 input references match the packaged authenticated bytes;
5. the Gate 2 manifest authenticates the packaged Gate 1 manifest, recipe authority, and terrain;
6. every report is regenerated from authenticated config, inputs, Gate 1 output, and Gate 2 output;
7. `checksums.json` is regenerated from the payload snapshot;
8. `package_manifest.json` is regenerated from the same authority.

Coherently resealing a modified config, recipe, report, checksum ledger, or package manifest must fail inspection.

## Immutable inspection and publication

Gate 3 captures the complete package tree once as immutable bytes. Capture rejects symlinks, nonregular entries, unexpected files, unexpected directories, and identity changes during capture.

Semantic inspection operates on a sealed reconstruction of that snapshot. Nested Gate 1 and Gate 2 inspection, report derivation, checksums, and package-manifest verification use the same bytes. Publication reconstructs a separate directory from the inspected snapshot, recaptures it, requires byte equality, and atomically renames it into place. The mutable build directory is never published directly.

## Commands

```text
python tools/opengs_eval/gate3_prototype.py validate-config \
  tools/opengs_eval/gate3_natural_earth_config.json

python tools/opengs_eval/gate3_prototype.py run \
  tools/opengs_eval/gate3_natural_earth_config.json \
  --natural-earth-root <pinned-natural-earth-checkout> \
  --output <new-gate3-package-directory>

python tools/opengs_eval/gate3_prototype.py inspect-output <gate3-package-directory>
python tools/opengs_eval/gate3_prototype.py compare-runs <left-package> <right-package>
```

Destinations must not already exist.

## Adversarial coverage

Focused tests cover exact-config mutations across every material block, Git-blob versus transformed working-tree bytes, projected no-data exclusion, ocean retention, lake-aware territory parenting, selectable water, reciprocal adjacency, immutable capture, coherent resealing attacks, production/Gate 4 boundaries, already-simple rings, repeated-vertex figure-eight rings, non-origin pinches, exact boundary-edge conservation, deterministic split order, accepted Gate 2 component construction, and degenerate pinch rejection.

## Validation and stop point

Exact-head CI must provide:

- Ubuntu and Windows focused contracts;
- two complete Gate 1 and Gate 2 candidate paths per operating system;
- strict sealed-package inspection;
- same-OS repeated-output comparison;
- Linux/Windows byte parity;
- Earth3 regression;
- PolygonMap runtime loading;
- Linux and Windows artifacts.

Keep PR #158 draft and unmerged. Keep #134 open. Do not begin Gate 4/#135. A fresh independent audit is required after the exact-head evidence package is green. Any later push or advance of `main` requires another exact-state check.
