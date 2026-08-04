# Gates of Europa province-source audit

## Confirmed extracted sources

The repository now identifies two separate 517-record GoE-derived sources:

- `src/gates_of_codex/data/goe_graph_*.b85` contains the bundled province IDs, display names, adjacency, coordinates, and source metadata used by the campaign graph.
- `src/gates_of_codex/data/goe_marker_layout.json` contains all 517 extracted marker anchors, all 517 unique `IdColor` RGB values, marker-neighbor rows, and the numeric `map_region` field from `province_database_newestV7`.

The original GoE presentation used a color-ID texture rather than baked ownership art:

- Unity asset: `province_idnew_map`
- dimensions: 1314×1513
- format: RGB24
- province ID colors: 517

The owner has authorized this GoE-derived map as an interim implementation asset. #51 must load it through a generic manifest/import boundary so the texture, dimensions, RGB table, and source format can be replaced without changing campaign rules.

## Graph-to-marker coverage

The current 517-node graph and extracted 517-row marker database are not a complete one-to-one identity match.

- 302 graph records can currently be mapped to an extracted marker record by ID, display name, or deterministic unique-neighbor propagation.
- 215 graph records do not have a defensible source-record mapping under that contract.
- PR #50 temporarily places those unmatched graph records by averaging already placed neighbors.
- Neighbor-averaged points do not receive invented RGB IDs and are not authoritative click targets.
- #51 must resolve selection from the actual color-ID texture pixels.

Run the deterministic detailed audit with:

```powershell
.\.venv\Scripts\gates-of-codex.exe audit-goe-provinces `
  --output .\docs\audits\goe-province-detailed.json `
  --summary .\docs\audits\goe-province-detailed.md
```

The detailed JSON emits all 517 graph rows with mapping method, source marker ID when available, exact anchor/RGB provenance, confidence, and explicit missing-field status. The canonical 517 marker/color rows remain in `goe_marker_layout.json` rather than being duplicated under `docs/`.

## Metadata availability

| Field | Status | Source finding | Required treatment |
|---|---|---|---|
| Province ID | available | Bundled graph and marker database | Preserve existing graph IDs unless a proven source defect exists |
| Display name | available | Bundled graph and marker database | Preserve source value and report ambiguities |
| Adjacency | available | Bundled graph plus marker neighbor records | Preserve the reciprocal graph contract |
| Marker anchor | available for all 517 marker records | `province_database_newestV7` extract | Temporary counters and labels only |
| ID color | available for all 517 marker records | `province_database_newestV7` `IdColor` extract | Generic color-ID lookup in #51 |
| Regional grouping | unresolved numeric field | `map_region` exists but semantics are not identified | Do not assign country meaning without source evidence |
| Country ownership | not found | Neither inspected extracted source contains a country table | Author separately as scenario data |
| Capital status | not found | No extracted capital field identified | Author separately as scenario data |
| Ports/coastal | not found | No extracted port/coastal field identified | Author from a defensible geographic source |
| Rail/logistics | not found | No extracted rail/logistics field identified | Author from a defensible logistics source |
| Terrain | not found | No river, mountain, forest, urban, or industrial tags identified | Author stable province tags separately |
| Special zones | not found | No disputed, demilitarized, or special-zone fields identified | Author per scenario |
| Scenario overrides | not found in extracted sources | Existing values are Gates of CodeX design | Keep separate from immutable geography |

## Extracted data versus new scenario design

The extracted GoE sources establish province IDs, display names, adjacency, marker anchors, unique RGB IDs, and an unlabeled numeric `map_region` field. They do not establish a complete modern political scenario.

The following current repository values are new Gates of CodeX scenario design and must not be cited as original GoE metadata:

- `modern_europe_v1` generated faction control
- Atlantic/Eurasian coalition definitions
- formation deployment anchors
- provisional PRC and KPA deployment zones
- default coalition capitals
- strategic objectives and infrastructure

Country ownership, neutral actors, foreign bases, entry nodes, supply corridors, terrain tags, ports, and rail must remain separate data layers so alternate scenarios can reuse the same immutable map.

## Required follow-up authoring

- country and neutral-actor geographic ownership
- capital designations
- ports and coastal access
- rail and logistics corridors
- terrain tags including river, mountain, forest, urban, and industrial
- disputed, demilitarized, and special-zone designations
- scenario-specific ownership and deployment overrides

## Safety and swap boundary

The interim map is source data, not a gameplay constant. No campaign rule may depend on 1314×1513 dimensions, current RGB values, Unity formatting, or neighbor-averaged marker positions. A future project-owned map must be swappable by replacing the manifest, ID texture, and province lookup table while preserving stable campaign province IDs or using an explicit migration map.
