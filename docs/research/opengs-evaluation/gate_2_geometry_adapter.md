# OpenGS Gate 2 Gates geometry adapter

Issue: #133  
Parent: #130  
Exact base: `68cba7d06322cec34a9a9c76eff5b635a9d9e01c`

## Scope

Gate 2 converts an inspected Gate 1 label-raster run into the existing Gates polygon dataset and strategic-map manifest contracts. It remains an isolated research adapter. It does not register a new production map, modify Earth3 authority, change campaign code, or begin the 3514-scale Gate 3 prototype.

The one shared-runtime change in this gate is narrowly limited to making the existing `PolygonMap` consume the already-emitted optional `components` geometry for hit testing, bounds, border registration, and outlines. Legacy datasets without `components` continue to use their existing primary `ring` unchanged.

## Commands

```text
python tools/opengs_eval/gate1_to_gate2_adapter.py convert \
  <gate1-output-directory> \
  --terrain <terrain-raster> \
  --config <gate2-config.json> \
  --output <new-output-directory>

python tools/opengs_eval/gate1_to_gate2_adapter.py inspect-output \
  <output-directory> \
  --gate1-output <gate1-output-directory> \
  --terrain <terrain-raster> \
  --config <gate2-config.json>

python tools/opengs_eval/gate1_to_gate2_adapter.py compare-runs \
  <left> <right> \
  --gate1-output <gate1-output-directory> \
  --terrain <terrain-raster> \
  --config <gate2-config.json>
```

The output directory must not already exist. Conversion is failure-atomic: files are built and inspected in a temporary sibling directory and published by one rename.

## Input and provenance authority

The adapter requires and authenticates:

- the exact five-file Gate 1 authoritative output set;
- canonical Gate 1 JSON and the complete embedded Gate 1 run manifest;
- immutable one-read byte snapshots for every Gate 1 authority file, with hashes and decoding derived from the same captured bytes;
- immutable one-read byte snapshots for every Gate 1 authority file, with hashes and decoding derived from the same captured bytes;
- current Gate 1 output checksums and source-record correspondence;
- a terrain raster captured once as immutable bytes, whose SHA-256 and decoded pixels come from that same snapshot and equal the Gate 1 manifest terrain input checksum;
- the exact canonical Gate 2 config digest and embedded settings;
- the current adapter version and adapter source digest;
- matching raster dimensions;
- one stable RGB label for every Gate 1 province record and no unrecorded non-black labels;
- the complete deterministic assertion set.

The adapter does not import Gate 1 implementation modules or campaign/runtime Python modules. Gate 1 remains the generator authority; Gate 2 is only a deterministic conversion and verification boundary.

## Geometry contract

- RGB labels are normalized by sorted Gate 1 province ID into `og2_######` IDs.
- Exact unit pixel edges form the shared boundary graph before simplification.
- Corner-only and diagonal-only contact never creates adjacency.
- The minimum shared-edge threshold is an explicit versioned integer in raster pixels.
- Simplification removes only exactly collinear grid points; no tolerance-based approximation is used.
- Every outer component and hole is retained in `components`; inspection reconstructs the exact rings from the authenticated label raster and requires byte-semantic agreement with each emitted component and primary ring.
- Winding is normalized for downward-positive image coordinates.
- Invalid or self-intersecting rings fail closed; they are not silently repaired.
- Deterministic constrained-Delaunay triangulation must cover each retained component exactly while leaving holes empty.
- Inspection rejects triangle overlaps and verifies that the triangle union equals the complete component geometry; summed area alone is not accepted as proof.
- Every anchor is a strictly interior representative point with measured boundary clearance.
- Terrain is counted across every province pixel and emitted as full-area counts and percentages; inspection recomputes every terrain count, percentage, and dominant terrain ID from the authenticated raster.
- Ocean and lake records remain geometry metadata but are non-selectable.

The Gates-required compatibility fields (`ring`, `vertices`, `triangles`, `neighbors`) remain present. `components` carries complete multipart-and-hole authority. The existing `PolygonMap` now consumes that optional field while preserving the legacy `ring` fallback.

## Topology and border authority

Gate 2 emits deterministic border records for:

- `internal_land`
- `coast`
- `lake_shore`
- `theatre_exterior`
- `suppression`
- `authored_boundary`

Suppression applies only to exact unit segments listed in the versioned config. Authored boundaries apply only to explicit source-ID pairs.

Inspection independently reconstructs shared-edge measurements from the authenticated Gate 1 labels, reapplies the configured threshold, and requires exact agreement with province neighbors and dataset edges. It also reconstructs and authenticates border classes, references, suppression decisions, component and hole counts, and all topology totals rather than trusting a self-consistent output ledger.

## Output set

- `polygon_dataset.json`
- `map_manifest.json`
- `dataset_meta.json`
- `topology_audit.json`
- `adapter_manifest.json`

All files are canonical UTF-8/LF JSON. `inspect-output` verifies the exact file set, output hashes, provenance, stable IDs, measured reciprocal adjacency, geometry validity, exact triangle-union coverage, holes, anchors, water policy, terrain totals, border authority, topology ledgers, and manifest consistency.

## Focused acceptance suite

```text
python -m unittest tests.test_opengs_gate1_to_gate2_adapter -v
```

The 23-test suite covers:

- single polygons;
- one and multiple holes;
- multipart islands;
- nested lakes;
- corner-only contacts;
- one-pixel shared edges and the versioned threshold;
- multipart coasts and theatre exterior borders;
- invalid/self-intersecting geometry rejection;
- strictly interior anchors and measured clearance;
- full-area terrain percentages;
- stable isolated IDs and non-selectable water;
- byte-identical repeated conversion of the real Gate 1 CI fixture;
- rejection of a resealed triangle mutation that fills a hole;
- rejection of a duplicate-triangle/equal-area-omission forgery;
- authentication of every adapter, config, Gate 1, terrain, and determinism provenance class;
- province-label and terrain-raster mutation-during-decode races, proving hashes and decoded arrays derive from the same captured bytes;
- rejection of coherently resealed terrain ledgers that disagree with the authenticated raster;
- rejection of translated or reshaped component payloads that do not match the authenticated label raster;
- province-label and terrain-raster mutation-during-decode races, proving hashes and decoded arrays derive from the same captured bytes;
- rejection of coherently resealed terrain ledgers that disagree with the authenticated raster;
- rejection of translated or reshaped component payloads that do not match the authenticated label raster;
- rejection of coherently forged adjacency and dataset-edge ledgers;
- rejection of forged border and topology ledgers;
- strict schema and dependency boundaries.

The dedicated workflow runs the focused suite and two clean conversions on Linux and Windows, authenticates both results against the original inputs, compares every authoritative Gate 2 file across operating systems, preserves the existing Earth3 runtime smoke, checks every real Gate 2 land/water/hole anchor, and exercises a synthetic nested-lake plus secondary multipart component through the existing `PolygonMap`.

## Material assumptions

1. Exact pixel boundaries are authoritative at Gate 2; visual or scale-driven approximation belongs after this gate.
2. The minimum shared-edge threshold is measured in unit raster edges and remains explicit in the config. The Gate 2 CI fixture uses `1` so that the required one-pixel-edge fixture is retained and tested.
3. The existing polygon dataset schema name/version is retained for compatibility. Complete multipart and hole geometry is added as a backward-compatible field rather than creating campaign awareness of OpenGS.
4. Gate 2 rejects invalid geometry instead of applying `make_valid`, because automatic repair could silently alter topology.
5. Ocean and lake records are preserved for borders and topology, but both are non-selectable under the existing Gates water policy.
6. IDs are assigned only from sorted Gate 1 source IDs in the isolated `og2_` namespace; no `e3_*` ID can be emitted.
7. The shared `PolygonMap` change is contract-generic: it consumes optional component/hole geometry and does not import, identify, or depend on OpenGS.

## Known risks and limitations

- The `PolygonMap` component/hole path is backward compatible and is covered by the existing Earth3 smoke plus Gate 2 nested-lake and multipart runtime fixtures, but it is still a shared runtime seam and should receive independent exact-head review.
- Gate 2 uses Shapely 2.1.2 constrained Delaunay triangulation as a pinned build-time dependency. No Shapely or OpenGS dependency enters campaign runtime.
- The CI fixture is intentionally small. Gate 3 owns 3514-scale generation, performance measurement, and production-quality candidate evaluation.

## Protected-path verification

Gate 2 does not modify:

- `config/earth3/**`
- `godot/assets/maps/earth3_europe_mediterranean/**`
- campaign/runtime Python packages under `src/gates_of_codex/**`
- PR #128 assets or presentation code
- map registration or production selection
- Gate 3 / 3514-scale prototype paths

The only shared production-runtime file changed is `godot/scripts/polygon_map.gd`, narrowly to consume optional generic component/hole geometry with a legacy-ring fallback. Earth3 authority and campaign behavior remain unchanged and are regression-tested.

## Stop point

Leave the Gate 2 pull request draft and unmerged for independent exact-head review. Do not begin Gate 3 / #134 until Gate 2 is independently approved, merged, and formally closed.
