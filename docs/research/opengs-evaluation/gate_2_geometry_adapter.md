# OpenGS Gate 2 Gates geometry adapter

Issue: #133  
Parent: #130  
Exact base: `68cba7d06322cec34a9a9c76eff5b635a9d9e01c`

## Scope

Gate 2 converts an inspected Gate 1 label-raster run into the existing Gates polygon dataset and strategic-map manifest contracts. It remains an isolated research adapter. It does not register a new production map, modify Earth3, change campaign code, or begin the 3514-scale Gate 3 prototype.

## Commands

```text
python tools/opengs_eval/gate1_to_gate2_adapter.py convert \
  <gate1-output-directory> \
  --terrain <terrain-raster> \
  --config <gate2-config.json> \
  --output <new-output-directory>

python tools/opengs_eval/gate1_to_gate2_adapter.py inspect-output <output-directory>
python tools/opengs_eval/gate1_to_gate2_adapter.py compare-runs <left> <right>
```

The output directory must not already exist. Conversion is failure-atomic: files are built and inspected in a temporary sibling directory and published by one rename.

## Input authority

The adapter requires:

- the exact five-file Gate 1 authoritative output set;
- canonical Gate 1 JSON;
- valid Gate 1 output checksums;
- a terrain raster whose SHA-256 equals the Gate 1 manifest's terrain input checksum;
- matching raster dimensions;
- one stable RGB label for every Gate 1 province record and no unrecorded non-black labels.

The adapter does not import Gate 1 implementation modules or campaign/runtime modules. Gate 1 remains the generator authority; Gate 2 is only a deterministic conversion boundary.

## Geometry contract

- RGB labels are normalized by sorted Gate 1 province ID into `og2_######` IDs.
- Exact unit pixel edges form the shared boundary graph before simplification.
- Corner-only and diagonal-only contact never creates adjacency.
- The minimum shared-edge threshold is an explicit versioned integer in raster pixels.
- Simplification removes only exactly collinear grid points; no tolerance-based approximation is used.
- Every outer component and hole is retained in `components`.
- Winding is normalized for downward-positive image coordinates.
- Invalid or self-intersecting rings fail closed; they are not silently repaired.
- Deterministic constrained-Delaunay triangulation must cover each retained component exactly while leaving holes empty.
- Every anchor is a strictly interior representative point with measured boundary clearance.
- Terrain is counted across every province pixel and emitted as full-area counts and percentages.
- Ocean and lake records remain geometry metadata but are non-selectable.

The current Gates-required compatibility fields (`ring`, `vertices`, `triangles`, `neighbors`) remain present. `components` carries the complete multipart-and-hole authority for future runtime consumption without changing campaign code in this gate.

## Border classes

Gate 2 emits deterministic border records for:

- `internal_land`
- `coast`
- `lake_shore`
- `theatre_exterior`
- `suppression`
- `authored_boundary`

Suppression applies only to exact unit segments listed in the versioned config. Authored boundaries apply only to explicit source-ID pairs.

## Output set

- `polygon_dataset.json`
- `map_manifest.json`
- `dataset_meta.json`
- `topology_audit.json`
- `adapter_manifest.json`

All files are canonical UTF-8/LF JSON. `inspect-output` verifies the exact file set, checksums, stable IDs, reciprocal adjacency, geometry validity, triangle coverage, holes, anchors, water policy, terrain totals, border references, and manifest consistency.

## Focused acceptance suite

```text
python -m unittest tests.test_opengs_gate1_to_gate2_adapter -v
```

The 15-test suite covers:

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
- strict schema and dependency boundaries.

The dedicated workflow runs the focused suite and two clean conversions on Linux and Windows, compares every authoritative Gate 2 file across operating systems, and opens the Linux result through the existing Godot `PolygonMap` implementation.

## Material assumptions

1. Exact pixel boundaries are authoritative at Gate 2; visual or scale-driven approximation belongs after this gate.
2. The minimum shared-edge threshold is measured in unit raster edges and remains explicit in the config. The Gate 2 CI fixture uses `1` so that the required one-pixel-edge fixture is retained and tested.
3. The existing polygon dataset schema name/version is retained for compatibility. Complete multipart and hole geometry is added as a backward-compatible field rather than creating campaign awareness of OpenGS.
4. Gate 2 rejects invalid geometry instead of applying `make_valid`, because automatic repair could silently alter topology.
5. Ocean and lake records are preserved for borders and topology, but both are non-selectable under the existing Gates water policy.
6. IDs are assigned only from sorted Gate 1 source IDs in the isolated `og2_` namespace; no `e3_*` ID can be emitted.

## Known risks and limitations

- The current production Godot loader consumes the legacy primary `ring` for hit testing and does not yet consume the complete `components` extension. The Gate 2 runtime smoke proves that a generated candidate opens through the existing loader and preserves non-selectable water, but complete multipart/hole runtime interaction is not expanded here because that would modify shared production runtime behavior. The complete geometry remains authenticated in the Python dataset and inspection contract for independent review.
- Gate 2 uses Shapely 2.1.2 constrained Delaunay triangulation as a pinned build-time dependency. No Shapely or OpenGS dependency enters campaign runtime.
- The CI fixture is intentionally small. Gate 3 owns 3514-scale generation, performance measurement, and production-quality candidate evaluation.

## Protected paths

Gate 2 must not modify:

- `config/earth3/**`
- `godot/assets/maps/earth3_europe_mediterranean/**`
- `godot/scripts/polygon_map.gd`
- campaign/runtime Python packages under `src/gates_of_codex/**`
- PR #128 assets or presentation code
- map registration or production selection

## Stop point

Leave the Gate 2 pull request draft and unmerged for independent exact-head review. Do not begin Gate 3 / #134 until Gate 2 is independently approved, merged, and formally closed.
