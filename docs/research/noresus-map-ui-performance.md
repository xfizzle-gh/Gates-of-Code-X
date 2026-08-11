# NORESUS strategic map, icon, and UX performance study

Status: **static clean-room study complete; no production Gates runtime changes made**

Reference: Steam Workshop item `3180617465`, NORESUS - Strategic Map / `Conquest\Enhanced Campaign 1.9.3.4`.

This document complements `noresus-strategic-reference.md` and focuses specifically on why the NORESUS strategic map feels lightweight, how its visual vocabulary is structured, and which ideas are safe and useful to reimplement in Gates of Code:X.

## Evidence boundary

This study is based on the supplied local reference snapshot and static inspection. The NORESUS executable was not run here. Exact internal drawing order or implementation details that require live execution or full IL reconstruction are not claimed.

No NORESUS executable, database, map artwork, icons, portraits, source, or other third-party content is included in this repository. Dimensions, counts, file roles, database schemas, and observable application strings are recorded as derived evidence only.

## Executive finding

NORESUS is fast because its strategic presentation problem is much smaller and more raster-oriented than the current Gates Earth3 presentation:

- one approximately 5000 x 4532 static strategic background image;
- one tiny 250 x 227 minimap plus pre-rendered minimap state images;
- 639 strategic regions rather than 3,514 production Earth3 provinces;
- region boundaries stored as raster-space pixel-coordinate polylines;
- small fixed-size bitmap icons and flags positioned on the map;
- WinForms `PictureBox` / panel-style UI rather than thousands of complex scene objects;
- explicit toggles for icon, name, and empty-region layers;
- no evidence that ordinary interaction rebuilds a complete high-detail strategic geometry presentation.

This is not an apples-to-apples performance comparison. Gates currently solves a denser and more dynamic problem. The useful lesson is architectural: **keep detailed polygon geometry as gameplay authority, but stop requiring that same geometry to be the expensive visual representation every frame or every backend command.**

## 1. Map assets and scale

Observed strategic map assets include:

- `map/mappa.jpg`: 5000 x 4532 RGB, the main strategic background;
- `map/mini_mappa.jpg`: 250 x 227 RGB minimap;
- `map/mini_mappa_n.jpg`: 250 x 227 grayscale minimap;
- `map/minizoom.png`: 52 x 31;
- several 250 x 227 faction/campaign-state minimap images.

The large background is a single image rather than a dynamically reconstructed terrain surface made from every strategic region.

The reference database contains 639 strategic regions. `regionborder` contains one row per region with boundary coordinates stored in source-map pixel space. Mutable `datamap` state also stores five image-coordinate pairs per region (`ic1` through `ic5`), suitable for anchors, labels, icons, or other map-local placement.

### Implication

NORESUS can cheaply pan and zoom a large bitmap while drawing only the currently required text, borders, and sprites over it. It does not need a separately rendered terrain material for every province.

## 2. Observable presentation architecture

Static executable strings expose WinForms controls including `PictureBox`, multiple panels, labels, and a data grid. Observable map-control text includes:

- zoom in / zoom out;
- middle-mouse drag map;
- cursor-key map movement;
- minimap mouse movement;
- toggle empty regions;
- show/hide region names;
- toggle NATO icons;
- save strategic map image.

The executable references the main and mini map assets directly and contains map-export paths such as a strategic-map image output.

`DrawString` is present in the static metadata, consistent with labels being drawn over the map presentation. Static inspection alone does not prove every GDI drawing primitive used, so the exact border/icon draw implementation remains a live/IL follow-up rather than a claim here.

## 3. Icon system

NORESUS uses a deliberately small icon vocabulary.

### Formation / battalion symbols

Observed 33 x 17 bitmap families include infantry, motorized, mechanized, light tank, medium tank, heavy tank, artillery, paratrooper, support, naval, partisan, stock, hide, and NATO-symbol variants.

Multiple numbered variants exist for several types. This gives the application a compact visual language for formation role/echelon without constructing complex map widgets.

### Flags

National flags are generally tiny fixed images around 32 x 16.

### Strategic resource and site icons

Observed resource/site sprites are generally around 18 to 27 pixels, including capital, manpower, credits, regions, oil, aluminum, rubber, steel, tungsten, factories, research, and capture/state markers.

### Tactical/support icons

Other UI sprites are similarly small and fixed-size, such as air-support and simulation buttons.

### Unit-card imagery

The package also contains many GoH portrait-format images for unit cards. The strategic map itself does not attempt to show that detail. Rich unit art is reserved for the management/detail context.

### Gates lesson

Use one original project-owned atlas for strategic symbols, flags, resources, sites, battle/contact states, stance, supply, and formation role. Map counters should be cheap sprites/atlas regions. Rich portraits belong in the selected-formation panel, not the always-visible map layer.

## 4. UX hierarchy

The useful NORESUS UX pattern is not its exact artwork. It is the separation of information density.

### Full strategic view

The map is dominated by geography and sparse strategic symbols. Optional layers can be hidden. Region names and NATO icons are explicitly toggleable.

### Management/detail views

Dense unit information moves into dedicated panels/screens. Large background images and conventional WinForms panels frame those screens, while unit portraits and small resource symbols carry most of the visual identity.

### Minimap

The minimap is independent and very small. It does not appear to be another live rendering of the full strategic scene. Pre-rendered mini-state images also exist.

### Input discoverability

The map exposes direct controls for drag, zoom, minimap movement, name visibility, empty-region visibility, and NATO-icon visibility. This is a simple but useful precedent for an explicit map-layer menu in Gates.

## 5. Current Gates Earth3 comparison

Current production Earth3 intentionally solves a denser problem:

- 3,514 records;
- 3,299 selectable land provinces;
- polygon mesh renderer;
- spatial-index point-in-polygon picking;
- immutable geometry with shader/LUT ownership;
- continuous ocean and shared-edge border mesh;
- dynamic operational overlays.

PR C under #74 reduced the land mesh from 13 to 4 instances and improved measured 1080p editor-debug frame time substantially, but approximately 3.7k draw calls remained unsolved. The recorded final measurements are roughly 50 to 66 ms per frame for common pan/zoom/idle scenarios, with the draw-call count still about 3,778.

There is a second, separate performance problem. Current Earth3 player commands can take approximately 20 to 40 seconds because the backend repeatedly loads/saves a multi-megabyte campaign and republishes a roughly 14 MB full frontend snapshot. That is tracked separately by #207. A faster map renderer alone will not fix that command latency.

## 6. Recommended Gates rendering direction

Do not replace Earth3 authority. Instead separate **authoritative geometry** from **visual presentation** more aggressively.

### A. Cached raster or tiled visual surface

Keep Earth3 polygon rings, topology, stable IDs, anchors, spatial index, and validation as authority. Build a derived visual surface from those records:

- project-owned terrain/background texture;
- cached ownership/color-ID layer driven by the owner LUT;
- cached border mask or tiled border texture;
- optional zoom-level border variants;
- no ordinary per-frame polygon traversal.

A single full texture may be sufficient at the current theatre scale. A tiled 512/1024-pixel scheme should also be benchmarked so only visible tiles are submitted at high zoom.

### B. Dynamic overlays only for active state

Hover, selection, legal targets, contact, routes, and capture progress should be separate sparse dynamic layers. Never redraw every province to show one selected province.

### C. Strategic icon atlas

Replace procedural per-counter rectangles/text where practical with original atlas-backed symbols. Batch/instance map counters and infrastructure markers using the cheapest Godot 2D path available under GL Compatibility. Evaluate `MultiMeshInstance2D`, atlas textures, and lower-level `RenderingServer` batching rather than thousands of individual `draw_*` submissions.

Text should be separate and LOD-gated.

### D. Label LOD

At full-theatre zoom show only critical capitals, selected/hovered regions, objectives, and active contacts. Add regional and local names progressively as zoom increases. Preserve a manual Names toggle.

### E. Independent minimap

Use a small cached minimap texture with only high-level ownership/front/selection overlays. Do not render the full Earth3 scene a second time.

### F. Layer toggles

Add a compact map-layer control modeled on the useful behavior, not the NORESUS art:

- formation symbols;
- province/region names;
- sites/infrastructure;
- operational routes;
- supply;
- objectives;
- fog/intelligence;
- debug overlays.

Layers that are off should incur near-zero presentation work.

## 7. Why the current draw-call problem deserves a dedicated experiment

Current `PolygonMap` already does several correct things:

- immutable land geometry;
- 1D owner lookup texture;
- only four land mesh chunks;
- one ocean mesh;
- one shared border mesh;
- spatial-grid hit testing;
- active-set overlay filtering.

So the remaining approximately 3.7k process draw-call count cannot be explained simply as "3,514 MeshInstance2D nodes". A follow-up must profile the exact Godot 2D submission sources rather than guessing.

Potential sources to measure include:

- shared-edge border primitive submission;
- CanvasItem `draw_*` calls from labels, counters, facilities, routes, debug overlays, and presentation fixtures;
- shader/material batch breaks;
- text glyph submissions;
- editor/debug instrumentation overhead.

The next performance slice should capture RenderingServer/CanvasItem-level counts by layer and temporarily disable one layer at a time to establish a draw-call attribution table.

## 8. Proposed isolated experiments

### Experiment 1: NORESUS-style raster presentation shadow mode

Produce a debug-only Earth3 presentation that uses the same authoritative campaign and hit-testing but renders:

1. one cached/tiled base map;
2. one ownership layer;
3. one border layer;
4. only sparse dynamic overlays.

Do not change campaign state, province IDs, topology, operational routes, or save compatibility.

Compare against production on the same machine:

- load time;
- draw calls;
- idle/pan/zoom/hover p50/p95 frame time;
- texture/video memory;
- ownership update time;
- click parity;
- visual clarity.

### Experiment 2: icon atlas + batched counters

Create original project-owned formation/site/resource icons. Render a stress fixture with hundreds of counters and compare atlas/batched rendering against current procedural `draw_rect`/`draw_string` counters.

### Experiment 3: label and layer LOD

Measure full-theatre, operational zoom, and close zoom with explicit label/icon/site visibility budgets.

### Experiment 4: backend delta publication

Keep this separate under #207. Do not conflate rendering FPS with the 20 to 40 second command/snapshot cycle.

## 9. Proposed performance targets for the experiment

These are research targets, not current production authority:

- reduce full-theatre draw calls by at least an order of magnitude from the current approximately 3.7k baseline;
- target 60 FPS / 16.7 ms p95 for idle and pan at 1920 x 1080 on the same acceptance machine where possible;
- preserve sub-millisecond-class point picking already demonstrated by the spatial index;
- ownership update should remain low-single-digit milliseconds;
- no full-map geometry rebuild for hover, selection, ownership change, or ordinary operational animation;
- byte-identical authoritative campaign/map state before and after switching presentation modes.

If 16.7 ms is not attainable under GL Compatibility, record the measured ceiling and the exact dominant layer rather than weakening correctness contracts.

## 10. Product recommendation

Adopt the **presentation philosophy**, not the NORESUS implementation or assets:

```text
Earth3 polygons/topology       = authoritative simulation + validation
Cached/tiled raster layers     = cheap strategic presentation
Sparse atlas-backed overlays   = formations/sites/contacts
Detailed portraits/cards       = selected formation/management UI
Small independent minimap      = navigation overview
LOD + layer toggles            = information and rendering budget
```

This preserves what Gates already does better while directly attacking the two player-visible complaints:

1. strategic map frame/render cost;
2. visual clutter/readability.

The separate command-cycle latency remains a backend/snapshot problem under #207 and should be solved in parallel, not hidden behind renderer work.
