# Experimental OpenGS Map Tool evaluation

Parent: #130  
Current gate: #131

## Purpose

Evaluate whether a legally sourced, deterministic OpenGS Map Tool pipeline can produce a Europe-Mediterranean candidate that satisfies the existing Gates polygon-map contracts.

This research does not authorize replacing Earth3.

## Production authority remains locked

- `map_id`: `earth3_europe_mediterranean`
- total records: `3514`
- selectable land: `3299`
- water metadata: `215`
- renderer: `polygon_mesh`
- hit testing: `point_in_polygon_spatial_index`
- ownership: `immutable_geometry_shader_lookup`
- renderer backend: GL Compatibility
- permanent unused IDs: `e3_2830`, `e3_2888`

PR #128 is outside this work. This branch is based on `main` and must not modify, retarget, or stack onto PR #128.

## Ordered gates

1. #131 Gate 0: provenance and feasibility
2. #132 Gate 1: deterministic headless generator
3. #133 Gate 2: Gates geometry adapter
4. #134 Gate 3: 3514-scale prototype
5. #135 Gate 4: validation
6. #136 Gate 5: go/no-go review

Every gate stops for owner review. A passing gate does not authorize starting the next gate automatically.

## Gate 0 boundaries

Gate 0 may:

- pin and inspect the upstream generator;
- inventory candidate legal source datasets;
- run synthetic feasibility and failure-behavior benchmarks;
- document nondeterminism and resource use;
- add isolated research tooling.

Gate 0 may not:

- fork generation modules into production code;
- modify Earth3 assets, authority, IDs, hashes, or runtime behavior;
- add an experimental map to the default campaign path;
- integrate the OpenGS Godot runtime;
- introduce RenderingDevice compute or JFA borders;
- claim synthetic benchmarks prove geographic quality;
- approve any unpinned input dataset for distribution.

## Runtime compatibility target

A future candidate must emit the existing Gates polygon dataset and strategic-map manifest contracts. Campaign code must not know which generator produced the geometry.

The required later adapter work includes polygon rings, multipart components, holes, triangles, shared-edge adjacency, border classes, interior-safe anchors, spatial indexing support, stable experimental IDs, fixtures, and authority audits. Raster labels and center metadata alone are insufficient.

## Water policy

OpenGS ocean and lake regions do not become selectable Gates provinces. A future adapter must preserve the current Gates policy:

- water retained as metadata where required;
- no normal water click target;
- no ownership tint on water;
- no filled per-water-province meshes;
- no water-to-water internal borders;
- coast and lake-shore classification retained;
- sea movement authored separately through operational nodes and edges.

## OpenGS runtime study boundary

The OpenGS Godot repository may be studied only for:

- map-mode lookup textures;
- label-placement concepts;
- editor interaction and province-editing UX.

Direct JFA compute integration is excluded while Gates remains on GL Compatibility. Any RenderingDevice transition or offline/CPU distance-field alternative requires a separate approved decision.

## Evaluation result

Gate 5 may recommend only one of:

1. no-go and retain Earth3;
2. continue isolated research;
3. authorize a separate production migration design.

Gate 5 itself never switches the production map.
