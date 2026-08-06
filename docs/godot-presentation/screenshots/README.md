# Screenshot evidence

## `runtime/` (true Godot viewport captures — acceptance)

Produced by `godot/scripts/tools/map_screenshot.gd`:

1. Instantiates live `main.tscn`
2. Loads committed snapshot via explicit `--snapshot=`
3. Opens color-ID map and verifies `MapBackgroundLayer` (LINEAR) + `MapIdentityLayer` (NEAREST)
4. Runs multiple `RenderingServer.force_draw` frames with the real scene `_draw()` path
5. Captures `Viewport.get_texture().get_image()` (actual CanvasItem output)
6. Exits nonzero on empty image or `save_png` failure

Includes real labels, counters, routes, battle/contact markers, control sites, and F3 debug when fixtures/flags enable them.

**Requires a real GL context** (local windowed Godot, or CI `xvfb-run`). Pure `--headless` dummy rendering cannot produce these captures.

## `mock_evidence_offline_composites/` (not acceptance)

Offline Python PIL blends. **Mock only** — not proof of Godot CanvasItem filtering or layout.
