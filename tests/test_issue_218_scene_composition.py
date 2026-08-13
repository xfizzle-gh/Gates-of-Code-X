from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Issue218SceneCompositionTests(unittest.TestCase):
    def test_production_scene_composes_order_startup_and_measured_layers(self) -> None:
        scene = (ROOT / "godot/main.tscn").read_text(encoding="utf-8")
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
        self.assertEqual("res://scripts/main_order_controls.gd", active.group(1))
        self.assertRegex(scene, r'(?m)^script = ExtResource\("1_main"\)$')
        self.assertIn('path="res://scripts/main_startup_measured.gd"', scene)
        self.assertIn('path="res://scripts/main_perf_measured.gd"', scene)
        self.assertIn("metadata/_startup_contract", scene)
        self.assertIn("metadata/_measured_perf_contract", scene)

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
