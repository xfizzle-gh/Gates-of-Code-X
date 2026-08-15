from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Issue218SceneCompositionTests(unittest.TestCase):
    def test_production_scene_composes_order_startup_and_measured_layers(self) -> None:
        scene = (ROOT / "godot/main.tscn").read_text(encoding="utf-8")
        refresh_safe = (
            ROOT / "godot/scripts/main_composed_presentation_refresh_safe.gd"
        ).read_text(encoding="utf-8")
        composed = (
            ROOT / "godot/scripts/main_composed_presentation.gd"
        ).read_text(encoding="utf-8")
        presentation = (
            ROOT / "godot/scripts/main_presentation_candidate.gd"
        ).read_text(encoding="utf-8")
        order = (ROOT / "godot/scripts/main_order_controls.gd").read_text(
            encoding="utf-8"
        )
        startup = (ROOT / "godot/scripts/main_startup_measured.gd").read_text(
            encoding="utf-8"
        )
        measured = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )

        active = re.search(
            r'\[ext_resource type="Script" path="([^"]+)" id="1_main"\]',
            scene,
        )
        self.assertIsNotNone(active)
        self.assertEqual(
            "res://scripts/main_composed_presentation_refresh_safe.gd",
            active.group(1),
        )
        self.assertRegex(scene, r'(?m)^script = ExtResource\("1_main"\)$')
        self.assertIn('path="res://scripts/main_startup_measured.gd"', scene)
        self.assertIn('path="res://scripts/main_perf_measured.gd"', scene)
        self.assertIn("metadata/_startup_contract", scene)
        self.assertIn("metadata/_measured_perf_contract", scene)

        # #212 adds default-off presentation layers above #218. Preserve and
        # prove the complete production inheritance chain rather than requiring
        # the old order layer to remain the top-level scene script.
        self.assertTrue(
            refresh_safe.startswith(
                'extends "res://scripts/main_composed_presentation.gd"\n'
            )
        )
        self.assertTrue(
            composed.startswith(
                'extends "res://scripts/main_presentation_candidate.gd"\n'
            )
        )
        self.assertTrue(
            presentation.startswith('extends "res://scripts/main_order_controls.gd"\n')
        )
        self.assertTrue(
            order.startswith('extends "res://scripts/main_startup_measured.gd"\n')
        )
        self.assertNotIn("func _ready(", order)
        self.assertTrue(
            startup.startswith('extends "res://scripts/main_perf_measured.gd"\n')
        )
        self.assertIn("super._ready()", startup)
        self.assertIn('"first_usable_strategic_frame"', startup)
        self.assertTrue(measured.startswith('extends "res://scripts/main_perf.gd"\n'))


if __name__ == "__main__":
    unittest.main()
