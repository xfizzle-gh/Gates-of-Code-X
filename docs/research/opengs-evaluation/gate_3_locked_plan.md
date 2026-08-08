# OpenGS Gate 3 locked implementation plan

Issue: #134  
Parent: #130  
Draft pull request: #158  
Required Gate 2 starting commit: `62063d70d2bb94f41b4d997578c02556003e9a72`  
Candidate ID: `opengs_gate3_europe_mediterranean_3514_candidate`

## Purpose

Gate 3 builds one isolated full-scale Europe-Mediterranean comparison candidate through the accepted deterministic Gate 1 generator and Gate 2 geometry adapter. It remains research-only, non-default, debug-only, and artifact-only. It does not replace Earth3, register a production map, create campaign authority, or begin Gate 4.

The implementation and adversarial-test plan was locked on #134 before implementation. The exact owner-approved configuration is now additionally locked by canonical SHA-256:

`4646af6a193374127e1c6c1570d74eb3e70b52748b1724f1e17879dff416ca85`

Any change to source paths or hashes, terms, projection, crop, anchors, dimensions, territory or province counts, generator seed or options, density values, terrain policy, Gate 2 threshold, water policy, or isolation policy requires an explicit configuration change and a new material checkpoint.

## Locked authority

### Source bytes

Gate 3 uses only Natural Earth v5.1.2 from `nvkelso/natural-earth-vector` at exact commit `f1890d9f152c896d250a77557a5751a93d494776`.

The five roles are 1:10m land, lakes, national boundary lines, populated places, and river/lake centerlines. Source authority is the exact Git blob object at `<commit>:<path>`, read with `git cat-file blob`. Working-tree bytes are not source authority and cannot be altered by checkout newline conversion. Every role is authenticated by repository, ref, commit, path, Git blob SHA-1, SHA-256, byte size, and public-domain license record.

### Projection, crop, and no-data mask

Projection:

`+proj=laea +lat_0=45 +lon_0=20 +datum=WGS84 +units=m +no_defs`

Raster dimensions are 2048 by 1536. Longitude/latitude bounds are west -13, south 27, east 45, north 75.

The densified longitude/latitude boundary is transformed into LAEA and rasterized as an explicit authenticated `theatre_mask.png`. Pixels outside that projected polygon are no-data, not ocean. The Gate 3 boundary input records those pixels with a reserved outside color. The Gate 3 mask adapter excludes them from both Gate 1 land and sea masks. Package inspection independently proves that Gate 1 black background pixels exactly equal the inverse theatre mask in both territory and province rasters.

The named land/water anchor set covers Ireland, Great Britain, Scandinavia, Finland, Sicily, Crete, Cyprus, the North African coast, Anatolia, the Irish Sea, English Channel, western Mediterranean, Adriatic, Black Sea, Kattegat, and Baltic.

### Counts

The comparison target remains:

- land provinces: 3,299
- ocean provinces: 215
- requested base total: 3,514

The locked source and raster contain 350 disconnected land components, so Gate 3 requests 350 land territories rather than deleting islands or drawing artificial bridges. It requests 20 ocean territories. The explicit theatre mask must be applied before ocean component counts are evaluated. Any count change remains material and must be recorded on #134.

Natural Earth lake components remain additional non-selectable water records and are reported rather than silently filtered.

### Density and terrain

The deterministic density raster combines populated-place population weighting, national-boundary corridors, river corridors, coastline emphasis, and a bounded background baseline. All parameters are part of the exact locked configuration.

Terrain remains a three-class legal baseline from the same authenticated physical masks: land is plains, ocean is deep ocean, lakes are lakes. It is not production terrain authority.

## Evidence-chain contract

Gate 3 packages must prove the complete chain:

1. packaged config bytes match the locked canonical digest;
2. the input manifest authenticates that exact config and every generated input;
3. the packaged Gate 1 recipe canonical digest matches the Gate 1 run manifest;
4. Gate 1 input references match the packaged authenticated input bytes;
5. the Gate 2 adapter manifest authenticates the packaged Gate 1 manifest, recipe authority, and terrain;
6. every report is deterministically regenerated from authenticated config, inputs, Gate 1 output, and Gate 2 output;
7. `checksums.json` is deterministically regenerated from the payload snapshot;
8. `package_manifest.json` is deterministically regenerated from the same authority.

Coherently resealing a modified config, recipe, report, checksum ledger, or package manifest must still fail inspection.

## Immutable inspection and publication

Gate 3 captures a complete package tree once as immutable bytes. Capture rejects symlinks, nonregular entries, unexpected files, and unexpected directories and verifies that the tree identity did not change during capture.

Semantic inspection operates on a sealed reconstruction of that immutable snapshot. Nested Gate 1 and Gate 2 inspection, report derivation, checksums, and package-manifest verification all use the same captured bytes. Publication creates a separate directory from the inspected snapshot, recaptures it, requires byte equality, and atomically renames that publication directory into place.

The mutable build directory is never renamed as the final package.

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

Focused tests cover exact-config mutations across every material block, Git-blob versus transformed working-tree bytes, projected outside-crop exclusion, source geography and lake classification, selectable water, map namespace and reciprocal adjacency, immutable-tree capture, extra directories, symlinks, coherent config/manifest forgery, coherent recipe forgery, coherent report forgery, and production/Gate 4 scope boundaries.

## CI and stop point

The workflow runs focused contracts on Ubuntu and Windows, two complete 3,514-scale Gate 1 and Gate 2 paths on each operating system, strict snapshot inspection, same-OS repeat comparison, Linux/Windows byte parity, existing Earth3 regression, Gate 3 PolygonMap runtime loading, and artifact capture.

Keep PR #158 draft and unmerged. Keep #134 open. Do not begin Gate 4/#135. A new independent audit is required after exact-head CI, artifacts, parity, and runtime evidence are green. Any later push or advance of `main` requires a new exact-state check.
