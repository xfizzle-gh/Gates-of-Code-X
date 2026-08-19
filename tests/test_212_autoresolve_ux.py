from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AutoResolveUxContractTests(unittest.TestCase):
    def test_pending_battle_card_makes_autoresolve_the_default(self) -> None:
        source = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        self.assertIn('_draw_panel_text("PENDING BATTLE"', source)
        self.assertIn("AUTO-RESOLVE (A)", source)
        self.assertIn("FIGHT IN GATES OF HELL (H)", source)
        self.assertNotIn("OPERATIONAL RESOLUTION PAUSED", source)
        self.assertIn(
            'if has_method("is_pending_battle_modal_active") and is_pending_battle_modal_active():',
            source,
        )
        writeback = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn(
            'requested_op not in ["handoff", "import_battle", "verify_result", "auto_resolve"]',
            writeback,
        )
        self.assertIn('id != "auto_resolve"', writeback)
        self.assertNotIn("mark_camera_moving", source)
        main = (ROOT / "godot/scripts/main.gd").read_text(encoding="utf-8")
        self.assertNotIn("func mark_camera_moving", main)


if __name__ == "__main__":
    unittest.main()
