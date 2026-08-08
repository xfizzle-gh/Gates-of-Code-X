# OpenGS Gate 3 locked implementation plan

Issue: #134  
Parent: #130  
Required base: `62063d70d2bb94f41b4d997578c02556003e9a72`  
Candidate ID: `opengs_gate3_europe_mediterranean_3514_candidate`

## Purpose

Gate 3 builds one isolated full-scale Europe-Mediterranean comparison candidate through the accepted deterministic Gate 1 generator and Gate 2 geometry adapter. It remains research-only, non-default, and debug-only. It does not replace Earth3, register a production map, or generate campaign authority.

The implementation and adversarial-test plan was locked on issue #134 before the implementation branch was created.

## Locked authority

### Source

Gate 3 uses only Natural Earth v5.1.2 from `nvkelso/natural-earth-vector` at exact commit `f1890d9f152c896d250a77557a5751a93d494776`.

The five source roles are 1:10m land, lakes, national boundary lines, populated places, and river/lake centerlines. Every source path, Git blob SHA-1, SHA-256, byte size, repository, ref, commit, and public-domain license record is authenticated. Gate 3 does not add ESA WorldCover, HydroLAKES, GeoNames, OpenStreetMap, Copernicus DEM, or another source.

### Projection and crop

Projection:

`+proj=laea +lat_0=45 +lon_0=20 +datum=WGS84 +units=m +no_defs`

Raster dimensions are 2048 by 1536. The longitude and latitude crop is west -13, south 27, east 45, north 75.

This implements the owner theatre policy: Europe and the Mediterranean, full Ireland, continental Europe, Scandinavia and the Baltic, the Black Sea, limited North Africa, and the Near East. It excludes far-Atlantic filler, deep Central Asia, deep sub-Saharan Africa, and extreme Arctic filler.

The build fails unless named land and water anchors remain correctly classified. The anchor set covers Ireland, Great Britain, Scandinavia, Finland, Sicily, Crete, Cyprus, the North African coast, Anatolia, the Irish Sea, English Channel, Mediterranean, Adriatic, Black Sea, Kattegat, and Baltic.

### Counts

Gate 3 requests the direct Earth3 comparison split:

- land provinces: 3,299
- ocean provinces: 215
- requested base total: 3,514

All Natural Earth lake components remain represented as additional non-selectable water metadata. The package reports requested and actual land, ocean, lake, water, and total counts. It does not silently delete lakes to force an exact total.

### Density

One deterministic density raster combines populated-place population weighting, national-boundary corridors, river corridors, coastline and narrow-geography emphasis, and a bounded background baseline.

Every radius, depth, sigma, threshold, and combination rule is versioned in `gate3_natural_earth_config.json` and copied into the provenance package.

### Terrain

Gate 3 uses a three-class baseline derived from the same Natural Earth land, ocean, and lake mask: land is plains, ocean is deep ocean, and lakes are lakes. This is a legal and deterministic physical baseline only. It is not production terrain authority.

### Water and campaign authority

Ocean and lake records are non-selectable. Gate 3 generates no operational sea nodes or edges. It generates no supply, air, political, command, ownership, reinforcement, or campaign authority.

## Commands

Validate the locked configuration:

```text
python tools/opengs_eval/gate3_prototype.py validate-config \
  tools/opengs_eval/gate3_natural_earth_config.json
```

Build one complete candidate. The command internally performs two clean Gate 1 generations, two clean Gate 2 conversions, strict inspection, same-platform package comparison, source recapture, and atomic publication:

```text
python tools/opengs_eval/gate3_prototype.py run \
  tools/opengs_eval/gate3_natural_earth_config.json \
  --natural-earth-root <pinned-natural-earth-checkout> \
  --output <new-gate3-package-directory>
```

Inspect or compare published packages:

```text
python tools/opengs_eval/gate3_prototype.py inspect-output <gate3-package-directory>
python tools/opengs_eval/gate3_prototype.py compare-runs <left-package> <right-package>
```

Destinations must not already exist.

## Package contents

The atomic package contains aligned land, boundary, density, and terrain rasters; exact Gate 3 config; generated Gate 1 recipe and Gate 2 config; Gate 3 input manifest; all five authoritative Gate 1 outputs; all five authoritative Gate 2 outputs; provenance and checksums; count, topology, adjacency, terrain, water-policy, geography, density, and performance reports; a debug-only map wrapper; and the package manifest.

The package manifest authenticates every contained file except itself. Inspection rejects missing, extra, symlink, directory-as-file, nonregular, or hash-mismatched entries.

## Determinism and mutation resistance

- Source files are captured once from regular non-symlink file descriptors.
- Git commit, Git blob, and SHA-256 authority are verified before decode.
- Geometry and populated-place decoding use captured bytes.
- Source paths are recaptured before publication.
- Gate 1 validates and publishes from its accepted immutable-input contract.
- Gate 2 validates and publishes from its accepted immutable Gate 1, terrain, config, and output contracts.
- Two complete end-to-end packages must be byte-identical before publication.
- Linux and Windows packages must be byte-identical in CI.

## Adversarial coverage

Tests reject source, commit, blob, checksum, license, or role-set changes; projection, crop, dimensions, count, density, terrain, water, or isolation changes; unapproved sources; selectable water; production registration; wrong map or ID namespace; nonreciprocal or inconsistent adjacency; missing geography anchors; empty density corridors; symlink and nonregular authority files; nondeterministic repeated packages; Linux and Windows byte differences; and production Earth3 or Gate 4 scope entering the workflow.

## CI

The workflow runs adversarial contract tests on Ubuntu and Windows, full 3,514-scale end-to-end generation on both operating systems, two clean generations and conversions per operating system, strict package inspection, complete Linux/Windows package parity, existing Earth3 runtime regression, real Gate 3 candidate loading through the existing `PolygonMap` runtime, and artifact capture for both operating systems.

Wall time and memory are CI observations and are excluded from deterministic package authority.

## Stop point

Leave the Gate 3 pull request draft and unmerged for independent review. Do not close #134 and do not begin Gate 4 or #135 until a fresh exact-head Gate 3 audit is accepted and the protected merge and formal closeout are complete.
