from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COLOR = ROOT / "godot/scripts/main_color_id.gd"
MAIN = ROOT / "godot/scripts/main.gd"
POLYGON = ROOT / "godot/scripts/polygon_map.gd"
GRAPH_TEST = ROOT / "godot/scripts/tools/graph_movement_scene_test.gd"


class TargetPresentationLodTests(unittest.TestCase):
    def test_theatre_lod_separates_legal_targets_from_draw_highlights(self) -> None:
        src = COLOR.read_text(encoding="utf-8")
        self.assertIn("func _highlight_targets_for_draw()", src)
        self.assertIn("func _draw_theatre_legal_target_markers()", src)
        self.assertIn("draw_multiline", src)
        self.assertIn("polygon_map.draw_overlays(self, map_space, _highlight_targets_for_draw())", src)
        self.assertIn("func _legal_target_on_screen(", src)
        highlight = src[src.find("func _highlight_targets_for_draw()") : src.find("func _build_overlay_active_ids()")]
        self.assertIn("_emphasis_legal_target_ids", highlight)
        self.assertNotIn("return legal_targets", highlight)
        self.assertNotIn(
            "for tid: Variant in legal_targets.keys():\n\t\tactive_ids[String(tid)] = true",
            src,
        )

    def test_focus_set_no_longer_indexes_every_operational_order(self) -> None:
        src = MAIN.read_text(encoding="utf-8")
        start = src.find("func _rebuild_focus_set()")
        self.assertGreater(start, 0)
        body = src[start : src.find("\nfunc ", start + 1)]
        self.assertIn("legal_targets.keys()", body)
        self.assertNotIn("snapshot.get(\"operational_orders\"", body)
        self.assertNotIn("snapshot.get(\"front_options\"", body)

    def test_polygon_overlays_accept_a_presentation_subset(self) -> None:
        src = POLYGON.read_text(encoding="utf-8")
        self.assertIn("func draw_overlays(canvas: CanvasItem, map_space, presented_targets: Variant = null)", src)
        self.assertIn("if presented_targets is Dictionary:", src)

    def test_graph_scene_covers_lod_and_order_parity(self) -> None:
        src = GRAPH_TEST.read_text(encoding="utf-8")
        self.assertIn("_test_focus_set_ignores_unrelated_formation_orders", src)
        self.assertIn("_test_theatre_lod_keeps_legal_targets_and_order_payload", src)
        self.assertIn("LOD does not rewrite path_node_ids", src)
        self.assertIn("closer zoom does not globally restore every legal destination", src)


if __name__ == "__main__":
    unittest.main()
