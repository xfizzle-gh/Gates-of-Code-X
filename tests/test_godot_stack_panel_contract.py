from __future__ import annotations

import unittest
from pathlib import Path


class GodotStackPanelContractTests(unittest.TestCase):
    def test_stack_panel_scene_and_selection_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scene = (root / "godot/stack_panel.tscn").read_text(encoding="utf-8")
        script = (root / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")

        self.assertIn("res://scripts/main_stack_panel.gd", scene)
        self.assertIn('extends "res://scripts/main_map_contract.gd"', script)
        self.assertIn('snapshot.get("stack_presentations"', script)
        self.assertIn('snapshot.get("battalion_presentations"', script)
        self.assertIn("selected_battalion_id = battalion_id", script)
        self.assertIn("_rebuild_legal_targets()", script)
        self.assertIn("acting battalion", script)

    def test_horizontal_cards_include_required_indicators(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        required = [
            "portrait_key",
            "portrait_fallback",
            "short_name",
            "quantity",
            "authorized_quantity",
            "condition",
            "supply",
            "experience",
            "replacement_cost",
            "source",
            "legacy_reserve",
            "tooltip",
            "formation_name",
            "actor_marker",
        ]
        for token in required:
            self.assertIn(token, script)

    def test_missing_portraits_use_deterministic_fallback(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        self.assertIn("ResourceLoader.exists(path)", script)
        self.assertIn("portrait_cache", script)
        self.assertIn('card.get("portrait_fallback"', script)
        self.assertIn("hovered_unit_tooltip", script)


if __name__ == "__main__":
    unittest.main()
