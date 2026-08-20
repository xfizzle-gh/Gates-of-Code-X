from __future__ import annotations

import unittest
from pathlib import Path


class GodotStackPanelContractTests(unittest.TestCase):
    def test_stack_panel_scene_and_selection_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scene = (root / "godot/stack_panel.tscn").read_text(encoding="utf-8")
        script = (root / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        main_scene = (root / "godot/main.tscn").read_text(encoding="utf-8")

        self.assertIn("res://scripts/main_stack_panel.gd", scene)
        self.assertIn("res://scripts/main_stack_panel.gd", main_scene)
        self.assertIn(
            "res://scripts/main_composed_presentation_refresh_safe.gd",
            main_scene,
        )
        self.assertIn('extends "res://scripts/main_map_contract.gd"', script)
        self.assertIn("func apply_stack_panel_fixture", script)
        self.assertIn("func select_acting_battalion", script)
        self.assertIn("func acting_battalion_legal_target_ids", script)
        self.assertIn('snapshot.get("stack_presentations"', script)
        self.assertIn('snapshot.get("battalion_presentations"', script)
        self.assertIn("strategic_formation_presentations", script)
        self.assertIn("selected_strategic_formation_id", script)
        self.assertIn("_rebuild_legal_targets()", script)
        self.assertIn("STRATEGIC FORMATION", script)
        self.assertIn("BATTALIONS IN FORMATION", script)
        self.assertIn("TACTICAL UNITS IN SELECTED BATTALION", script)
        self.assertIn("stack_panel_expanded", script)
        self.assertNotIn("super._draw_management_panel()", script)

    def test_tabs_are_strategic_formations_not_raw_ids(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        self.assertIn("_draw_formation_tab", script)
        self.assertIn("tab_label", script)
        self.assertIn("Unassigned Commander", script)
        self.assertIn("echelon", script)

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
            "actor_marker",
            "unit_scroll_offset",
            "_fmt_int",
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
