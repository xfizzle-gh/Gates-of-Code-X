from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex import frontend
from gates_of_codex.frontend_fastpath import (
    build_frontend_snapshot_fast,
    write_frontend_snapshot_fast,
)
from gates_of_codex.scenario import build_scenario


ROOT = Path(__file__).resolve().parents[1]


class FrontendFastPathTests(unittest.TestCase):
    def test_fast_projection_is_semantically_identical(self) -> None:
        state = build_scenario("legacy_goe_europe")
        expected = frontend.build_frontend_snapshot(state)
        actual = build_frontend_snapshot_fast(state)
        self.assertEqual(expected, actual)

    def test_fast_writer_is_atomic_machine_json_with_same_payload(self) -> None:
        state = build_scenario("legacy_goe_europe")
        expected = build_frontend_snapshot_fast(state)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "campaign_snapshot.json"
            write_frontend_snapshot_fast(state, destination)
            text = destination.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(expected, json.loads(text))
            # The runtime snapshot is machine data. Pretty-print indentation was
            # pure disk/parse overhead on the ~14 MB Earth3 snapshot.
            self.assertNotIn("\n  \"", text)

    def test_fast_path_explicitly_deduplicates_construction_traversals(self) -> None:
        source = (ROOT / "src/gates_of_codex/frontend_fastpath.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("selected_reachable = _reachable_supply_provinces", source)
        self.assertIn("_strategic.ensure_strategic_layer = _already_initialized", source)
        self.assertIn("_strategic.reachable_supply_provinces = _snapshot_reachable", source)
        self.assertIn("finally:", source)
        self.assertIn("_strategic.ensure_strategic_layer = previous_ensure", source)
        self.assertIn("_strategic.reachable_supply_provinces = previous_reachable", source)


class PlayerTurnCyclePresentationTests(unittest.TestCase):
    def test_main_scene_uses_responsiveness_layer(self) -> None:
        scene = (ROOT / "godot/main.tscn").read_text(encoding="utf-8")
        self.assertIn('path="res://scripts/main_perf.gd"', scene)

    def test_end_turn_composes_ai_cycle_in_one_backend_batch(self) -> None:
        source = (ROOT / "godot/scripts/main_perf.gd").read_text(encoding="utf-8")
        self.assertIn('if button_id == "end_turn":', source)
        self.assertIn('_queue_and_apply(commands)', source)
        self.assertIn('{"op": "end_turn"}', source)
        self.assertIn('"op": "run_ai"', source)
        self.assertIn('"advance_turn": true', source)
        self.assertIn('PLAYER_TURN_ORDER := ["nato", "ukr", "rusa", "prc"]', source)
        self.assertIn('End turn + AI cycle (E)', source)

    def test_overlay_has_no_all_province_ambient_label_scan(self) -> None:
        source = (ROOT / "godot/scripts/main_perf.gd").read_text(encoding="utf-8")
        overlay = source.split("func _draw_color_id_overlays() -> void:", 1)[1]
        self.assertIn("_build_overlay_active_ids()", overlay)
        self.assertIn("Labels are action context, not wallpaper", overlay)
        self.assertNotIn('snapshot.get("provinces"', overlay)
        self.assertNotIn("named and view_scale", overlay)


class RuntimeEntrypointTests(unittest.TestCase):
    def test_console_and_python_module_install_fast_writer(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        module = (ROOT / "src/gates_of_codex/__main__.py").read_text(encoding="utf-8")
        self.assertIn(
            'gates-of-codex = "gates_of_codex.fast_entrypoint:main"', pyproject
        )
        self.assertIn("from .fast_entrypoint import main", module)


if __name__ == "__main__":
    unittest.main()
