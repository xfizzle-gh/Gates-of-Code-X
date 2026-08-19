from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OvermapInteractionContractTests(unittest.TestCase):
    def test_production_overlay_cache_ignores_pan_offset(self) -> None:
        source = (ROOT / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn('var cache_key := "%s|%s|%s" % [', source)
        self.assertNotIn("snappedf(view_offset.x, 0.5)", source)
        self.assertIn("scan_all := rebuild and view_scale >= 2.4 and not camera_moving", source)
        self.assertIn('"image": _active_map().anchor_pixel(province_id)', source)
        self.assertIn("polygon land/ocean/borders live on transformed meshinstance2d", source.lower())

    def test_camera_motion_keeps_management_panel_visible(self) -> None:
        source = (ROOT / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("_draw_management_panel()", source)
        self.assertNotIn(
            "if not (has_method(\"camera_is_moving\") and camera_is_moving()):",
            source,
        )
        draw = source.split("func _draw() -> void:", 1)[1].split("func _draw_operational_presentation", 1)[0]
        self.assertIn("_draw_management_panel()", draw)
        self.assertNotIn("camera_is_moving()", draw)
        main = (ROOT / "godot/scripts/main.gd").read_text(encoding="utf-8")
        self.assertIn("func mark_camera_moving", main)
        self.assertIn("func camera_is_moving", main)

    def test_pending_battle_card_makes_autoresolve_the_default(self) -> None:
        source = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        self.assertIn('_draw_panel_text("PENDING BATTLE"', source)
        self.assertIn("AUTO-RESOLVE (A)", source)
        self.assertIn("FIGHT IN GATES OF HELL (H)", source)
        self.assertNotIn("OPERATIONAL RESOLUTION PAUSED", source)
        self.assertIn("if has_method(\"is_pending_battle_modal_active\") and is_pending_battle_modal_active():", source)
        writeback = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn('requested_op not in ["handoff", "import_battle", "verify_result", "auto_resolve"]', writeback)
        self.assertIn('id != "auto_resolve"', writeback)


if __name__ == "__main__":
    unittest.main()
