# OpenGS Gate 2 Gates geometry adapter

Issue: #133  
Parent: #130  
Exact base: `68cba7d06322cec34a9a9c76eff5b635a9d9e01c`

## Scope

Gate 2 converts a strictly inspected Gate 1 label-raster run into the existing Gates polygon dataset and strategic-map manifest contracts. It remains an isolated research adapter. It does not register a production map, modify Earth3 authority, change campaign code, or begin the 3514-scale Gate 3 prototype.

The one shared-runtime change in this gate is narrowly limited to making the existing `PolygonMap` consume optional `components` geometry for hit testing, bounds, border registration, and outlines. Legacy datasets without `components` retain the existing primary-`ring` path.

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

The destination must not already exist.

## Immutable authority and publication

Gate 2 captures every authoritative file set once as immutable bytes.

### Gate 1 input

The adapter requires exactly these five regular, non-symlink files and rejects missing, extra, directory, symlink, and other non-regular entries:

- `territories.png`
- `provinces.png`
- `territories.json`
- `provinces.json`
- `run_manifest.json`

The captured bytes are validated through Gate 1's complete strict inspector. Gate 1 JSON reads, PNG decoding, and checksum reads are supplied from the immutable snapshot rather than reopening the caller's paths. This enforces the full Gate 1 contract, including:

- manifest schema and schema version;
- generator version and current source identity;
- pinned environment and upstream repository/commit;
- recipe and input-reference contracts;
- derived-seed ledger and determinism assertions;
- requested and actual counts;
- manifest payload checksum;
- canonical territory/province JSON records;
- territory and province PNG semantics, centroids, containment, and child unions.

Gate 2 then derives its labels and provenance from those same captured bytes. A path replacement during inspection or decoding cannot change the authority being converted.

### Terrain and configuration

The terrain raster is read once. Its SHA-256 and decoded pixel array come from the same bytes and must match the Gate 1 manifest. The Gate 2 configuration is read once, strictly validated, and embedded canonically in the adapter manifest.

### Gate 2 output

Generation writes to a private temporary directory. Before inspection, all five Gate 2 authoritative files are captured once. Inspection hashes and parses only those captured bytes. Publication writes a second private directory from the exact inspected snapshot, recaptures it to prove byte identity, and then publishes it with one sibling-directory rename.

A replacement of a generated path after capture cannot change the files that are published. Standalone inspection likewise hashes and parses one immutable snapshot instead of reopening output paths between checksum and JSON validation.

## Geometry contract

- RGB labels are normalized by sorted Gate 1 province ID into `og2_######` IDs.
- Exact unit pixel edges form the shared boundary graph before simplification.
- Corner-only and diagonal-only contact never creates adjacency.
- The minimum shared-edge threshold is an explicit versioned integer in raster pixels.
- Simplification removes only exactly collinear grid points; no tolerance-based approximation is used.
- Every outer component and hole is retained in `components`.
- Inspection reconstructs exact rings from the authenticated Gate 1 raster and requires agreement with each emitted component and primary ring.
- Winding is normalized for downward-positive image coordinates.
- Invalid or self-intersecting rings fail closed and are not silently repaired.
- Deterministic constrained-Delaunay triangulation must cover each retained component exactly while leaving holes empty.
- Inspection rejects triangle overlap and requires the triangle union to equal complete component geometry.
- Every anchor is strictly interior with measured boundary clearance.
- Terrain counts, percentages, and the dominant terrain ID are recomputed from every authenticated province pixel.
- Ocean and lake records remain geometry metadata but are non-selectable.

The compatibility fields `ring`, `vertices`, `triangles`, and `neighbors` remain present. `components` carries complete multipart-and-hole authority.

## Topology and border authority

Gate 2 emits deterministic border records for:

- `internal_land`
- `coast`
- `lake_shore`
- `theatre_exterior`
- `suppression`
- `authored_boundary`

Inspection independently reconstructs shared-edge measurements from the authenticated Gate 1 raster, reapplies the configured threshold, and requires exact agreement with province neighbors and dataset edges. It also reconstructs border classes and references, suppression decisions, component/hole counts, and all topology totals.

## Output set

- `polygon_dataset.json`
- `map_manifest.json`
- `dataset_meta.json`
- `topology_audit.json`
- `adapter_manifest.json`

All five files are canonical UTF-8/LF JSON.

## Focused acceptance suite

```text
python -m unittest tests.test_opengs_gate1_to_gate2_adapter -v
```

The 27-test suite covers:

- single polygons, holes, multiple holes, multipart islands, and nested lakes;
- corner-only contact and one-pixel shared-edge thresholds;
- multipart coasts and theatre exterior borders;
- invalid/self-intersecting geometry rejection;
- strictly interior anchors and measured clearance;
- full-area terrain percentages;
- stable isolated IDs and non-selectable water;
- byte-identical repeated conversion of the real Gate 1 CI fixture;
- complete adapter/config/Gate 1/terrain/determinism provenance authentication;
- province-label and terrain mutation during decode;
- Gate 2 output replacement between capture and parse;
- generated-output replacement after inspection but before publication;
- strict rejection of a coherently resealed but semantically invalid Gate 1 bundle;
- rejection of Gate 1 extra directories and symlink entries;
- rejection of hole-filling, duplicate/omitted, and overlapping triangle forgeries;
- rejection of coherently resealed terrain ledgers;
- rejection of raster-inconsistent translated or reshaped components;
- rejection of coherently forged adjacency, border, and topology ledgers;
- strict schema and dependency boundaries.

The dedicated workflow runs the focused suite and two clean conversions on Linux and Windows, inspects both against the original inputs, compares every authoritative file across operating systems, preserves the Earth3 runtime smoke, checks every real Gate 2 land/water/hole anchor, and exercises a synthetic nested lake plus secondary multipart component through `PolygonMap`.

## Material assumptions

1. Exact pixel boundaries are authoritative at Gate 2; visual or scale-driven approximation belongs after this gate.
2. The minimum shared-edge threshold remains explicit in the config. The CI fixture uses `1` to retain the one-pixel fixture.
3. The existing polygon dataset schema remains for compatibility; complete multipart/hole geometry is a backward-compatible field.
4. Invalid geometry fails closed; automatic repair is excluded.
5. Ocean and lake records are preserved for borders and topology but remain non-selectable.
6. IDs derive only from sorted Gate 1 source IDs in the isolated `og2_` namespace.
7. The shared `PolygonMap` change is contract-generic and contains no OpenGS awareness.

## Known limitations

- `PolygonMap` is a shared runtime seam. Existing Earth3 smoke tests and Gate 2 nested-lake/multipart fixtures cover compatibility, but exact-head independent review remains required.
- Shapely 2.1.2 and the Gate 1 generation dependencies remain pinned build-time dependencies only.
- The fixture is intentionally small. Gate 3 owns 3514-scale generation, performance measurement, and candidate evaluation.

## Protected-path verification

Gate 2 does not modify:

- `config/earth3/**`
- `godot/assets/maps/earth3_europe_mediterranean/**`
- campaign/runtime packages under `src/gates_of_codex/**`
- PR #128 assets or presentation code
- production map registration or selection
- Gate 3 / 3514-scale prototype paths

The only shared production-runtime file changed is `godot/scripts/polygon_map.gd`, narrowly to consume optional generic component/hole geometry with a legacy-ring fallback.

## Stop point

Leave PR #143 draft and unmerged for independent exact-head review. Do not close #133 or begin Gate 3 / #134 until Gate 2 is independently approved, merged, and formally closed.
