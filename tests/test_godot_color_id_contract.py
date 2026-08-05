from __future__ import annotations

import unittest
from pathlib import Path


class GodotColorIdContractTests(unittest.TestCase):
    def test_scene_uses_color_id_client_and_pixel_selection(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scene = (root / "godot/main.tscn").read_text(encoding="utf-8")
        contract = (root / "godot/scripts/main_map_contract.gd").read_text(encoding="utf-8")
        main = (root / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        layer = (root / "godot/scripts/color_id_map.gd").read_text(encoding="utf-8")

        self.assertIn("res://scripts/main_map_contract.gd", scene)
        self.assertIn('extends "res://scripts/main_color_id.gd"', contract)
        self.assertIn('snapshot.get("strategic_map"', contract)
        self.assertIn("manifest_path", contract)
        self.assertIn("DEFAULT_MAP_MANIFEST", main)
        self.assertIn("province_at_pixel(pixel)", main)
        self.assertIn("func _province_at(screen_position", main)
        self.assertIn("func _map_texture_rect", main)
        self.assertIn("sampling", layer)
        self.assertIn('!= "nearest"', layer)
        self.assertIn("owner_texture", layer)
        self.assertIn("border_texture", layer)
        self.assertIn("highlight_texture", layer)
        self.assertIn("refresh_snapshot", layer)
        self.assertIn("refresh_highlights", layer)
        self.assertNotIn("1314", contract + main + layer)
        self.assertNotIn("1513", contract + main + layer)

    def test_visual_layers_remain_independent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        main = (root / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        expected = [
            "owner_texture",
            "border_texture",
            "highlight_texture",
            "_draw_coalition_fronts",
            "_draw_color_id_pending_battle",
            "infrastructure",
            "is_in_supply",
            "encircled_turns",
            "_draw_battalion_counter",
            "display_name",
        ]
        for token in expected:
            self.assertIn(token, main)

    def test_marker_fallback_is_not_claimed_as_authoritative(self) -> None:
        root = Path(__file__).resolve().parents[1]
        main = (root / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        instructions = (
            root / "godot/assets/maps/europe/interim_goe/README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Marker fallback remains non-authoritative", main)
        self.assertIn("generic validator", instructions)
        self.assertIn("Replacement path", instructions)
        self.assertIn("adjacency differs", instructions)


if __name__ == "__main__":
    unittest.main()
