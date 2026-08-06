from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"


class GodotPresentationPerformanceTests(unittest.TestCase):
    def test_color_id_map_uses_cached_runs_and_incremental_refresh(self) -> None:
        layer = (GODOT / "scripts/color_id_map.gd").read_text(encoding="utf-8")
        self.assertIn("_province_pixel_runs", layer)
        self.assertIn("_pixel_province_index", layer)
        self.assertIn("_rebuild_owner_partial", layer)
        self.assertIn("_rebuild_owner_full", layer)
        self.assertIn("get_perf_stats", layer)
        self.assertIn("end_frame_stats", layer)
        self.assertIn("owner_texture.update", layer)
        self.assertIn("highlight_texture.update", layer)
        self.assertNotIn('set_meta("goc_filter"', layer)
        # Full-image highlight scans must not remain the only path.
        self.assertIn("_fill_province_pixels", layer)
        self.assertNotIn(
            "for y in range(id_image.get_height()):\n\t\tfor x in range(id_image.get_width()):\n\t\t\tvar province_id: String = province_by_color.get(_rgb_key(id_image.get_pixel(x, y)), \"\")\n\t\t\tif province_id == selected_province_id",
            layer,
        )

    def test_separate_canvasitem_filter_layers(self) -> None:
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        layer = (GODOT / "scripts/presentation/map_texture_layer.gd").read_text(encoding="utf-8")
        self.assertIn("MapBackgroundLayer", main)
        self.assertIn("MapIdentityLayer", main)
        self.assertIn("TEXTURE_FILTER_LINEAR", main)
        self.assertIn("TEXTURE_FILTER_NEAREST", main)
        self.assertIn("_sync_presentation_layers", main)
        self.assertNotIn("texture_filter = filter", main)
        self.assertIn("draw_texture_rect", layer)

    def test_map_space_centralizes_transforms(self) -> None:
        space = (GODOT / "scripts/presentation/map_space.gd").read_text(encoding="utf-8")
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("class_name MapSpace", space)
        self.assertIn("func image_to_screen", space)
        self.assertIn("func screen_to_pixel", space)
        self.assertIn("func texture_rect", space)
        self.assertIn("map_space", main)
        self.assertIn("_sync_map_space", main)
        self.assertNotIn("1314", main)
        self.assertNotIn("1513", main)

    def test_presentation_markers_cover_required_components(self) -> None:
        markers = (GODOT / "scripts/presentation/map_markers.gd").read_text(encoding="utf-8")
        required = [
            "draw_selected_province_ring",
            "draw_hovered_province_ring",
            "draw_formation_counter",
            "draw_stack_badge",
            "draw_route_line",
            "draw_node_contact_marker",
            "draw_edge_contact_marker",
            "draw_crossed_swords_battle_marker",
            "draw_control_site_marker",
            "draw_capture_progress",
            "battle_marker_position",
            "presentation_progress_fp",
        ]
        for token in required:
            self.assertIn(token, markers)

    def test_debug_mode_is_opt_in(self) -> None:
        debug = (GODOT / "scripts/presentation/map_debug.gd").read_text(encoding="utf-8")
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("var enabled := false", debug)
        self.assertIn("KEY_F3", main)
        self.assertIn("map_debug.enabled", main)
        self.assertIn("--debug-map", main)

    def test_presentation_fixtures_exist_and_are_marked_local(self) -> None:
        fixture_dir = GODOT / "fixtures/presentation"
        expected = [
            "empty_map.json",
            "full_theatre_smoke.json",
            "many_counters.json",
            "stack_and_selection.json",
            "routes_and_battles.json",
            "control_sites.json",
            "rapid_hover.json",
            "refresh_stability.json",
            "resolutions.json",
        ]
        for name in expected:
            path = fixture_dir / name
            self.assertTrue(path.is_file(), msg=name)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("schema"), "gates-of-codex.presentation-fixture")
        readme = (fixture_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("not** production simulation authority", readme)
        routes = json.loads((fixture_dir / "routes_and_battles.json").read_text(encoding="utf-8"))
        edge = next(b for b in routes["battles"] if b["kind"] == "edge")
        self.assertIn("presentation_progress_fp", edge)
        self.assertTrue(0 <= int(edge["presentation_progress_fp"]) <= 1000)

    def test_hover_does_not_refresh_ownership_textures(self) -> None:
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        # Hover path must queue redraw without calling refresh_snapshot.
        hover_idx = main.index("next_hover != hovered_province_id")
        hover_block = main[hover_idx : hover_idx + 220]
        self.assertIn("queue_redraw()", hover_block)
        self.assertNotIn("refresh_snapshot", hover_block)
        self.assertNotIn("refresh_highlights", hover_block)
        self.assertIn("Hover never rebuilds ownership/highlight textures", main)

    def test_display_settings_support_hd_and_hidpi(self) -> None:
        project = (GODOT / "project.godot").read_text(encoding="utf-8")
        self.assertIn('window/stretch/mode="canvas_items"', project)
        self.assertIn("window/dpi/allow_hidpi=true", project)
        self.assertIn("viewport_width=1920", project)
        self.assertIn("viewport_height=1080", project)

    def test_profiler_tool_present(self) -> None:
        profiler = (GODOT / "scripts/tools/map_profiler.gd").read_text(encoding="utf-8")
        self.assertIn("refresh_snapshot_ms_avg", profiler)
        self.assertIn("refresh_highlights_ms_avg", profiler)
        self.assertIn("map_open_ms", profiler)
        self.assertIn("--snapshot=", profiler)
        self.assertIn("fixtures/snapshots/em_theatre_profile.json", profiler)
        snapshot = GODOT / "fixtures/snapshots/em_theatre_profile.json"
        self.assertTrue(snapshot.is_file())
        data = json.loads(snapshot.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data.get("provinces", [])), 300)
        ci = (GODOT / "scripts/tools/map_ci_check.gd").read_text(encoding="utf-8")
        self.assertIn("map_ci_check", ci)
        self.assertIn("main.tscn", ci)
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        self.assertIn("godot-map:", workflow)
        self.assertIn("map_ci_check.gd", workflow)
        self.assertIn("map_profiler.gd", workflow)
        self.assertIn("map_screenshot.gd", workflow)

    def test_debug_stats_not_cleared_before_overlay(self) -> None:
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        debug = (GODOT / "scripts/presentation/map_debug.gd").read_text(encoding="utf-8")
        self.assertIn("capture_perf", main)
        self.assertIn("end_frame_stats", main)
        # capture must appear before end_frame_stats in _draw
        self.assertLess(main.index("capture_perf"), main.index("end_frame_stats"))
        self.assertIn("_cached_label_bounds", main)
        self.assertIn("label_bounds", debug)
        self.assertIn("last_event", debug)
        self.assertIn("static_rebuilds_displayed", debug)

    def test_no_silent_fixture_fallback_on_normal_launch(self) -> None:
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertNotIn("DEFAULT_PROFILE_SNAPSHOT", main)
        self.assertIn("Never silently replace", main)
        # Production path must not auto-load profiling fixture.
        self.assertNotIn('_load_snapshot(DEFAULT_PROFILE_SNAPSHOT)', main)
        self.assertNotIn('_load_snapshot("res://fixtures/snapshots/em_theatre_profile.json")', main)

    def test_screenshot_tool_uses_true_viewport_capture(self) -> None:
        shot = (GODOT / "scripts/tools/map_screenshot.gd").read_text(encoding="utf-8")
        ci = (GODOT / "scripts/tools/map_ci_check.gd").read_text(encoding="utf-8")
        self.assertIn("get_image()", shot)
        self.assertIn("force_draw", shot)
        self.assertIn("create_timer", shot)
        self.assertNotIn("_compose_runtime_image", shot)
        self.assertNotIn("_stamp_x", shot)
        self.assertNotIn("blend_rect", shot)
        self.assertIn("get_image()", ci)
        self.assertIn("force_draw", ci)
        self.assertIn("RENDER_FRAMES", ci)
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        self.assertIn("xvfb-run", workflow)
        self.assertIn("map_ci_check.gd", workflow)
        self.assertIn("map_screenshot.gd", workflow)

    def test_edge_marker_interpolation_is_fixed_point(self) -> None:
        markers = (GODOT / "scripts/presentation/map_markers.gd").read_text(encoding="utf-8")
        self.assertIn("progress_fp", markers)
        self.assertIn("clampi(progress_fp, 0, 1000)", markers)
        self.assertIn("float(progress_fp) / 1000.0", markers)

    def test_python_operational_files_untouched_by_this_suite_scope(self) -> None:
        # Guardrail: presentation tests only read Godot paths.
        self.assertTrue((GODOT / "scripts/color_id_map.gd").is_file())
        forbidden_mentions = [
            "operational_movement.py",
            "operational_contact.py",
            "frontend.py",
        ]
        changed_marker = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        for token in forbidden_mentions:
            self.assertNotIn(token, changed_marker)


if __name__ == "__main__":
    unittest.main()
