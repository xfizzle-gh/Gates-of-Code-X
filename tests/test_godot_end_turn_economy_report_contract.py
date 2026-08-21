from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GodotEndTurnEconomyReportContractTests(unittest.TestCase):
    def test_overlay_consumes_end_player_round_economy_report(self) -> None:
        writeback = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        stack = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        measured = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(encoding="utf-8")
        self.assertIn("_capture_end_turn_economy_report", writeback)
        self.assertIn('_result_data(payload, "end_player_round")', writeback)
        self.assertIn('data.get("economy_report"', writeback)
        self.assertIn("economy_report_open", writeback)
        self.assertIn("dismiss_end_turn_economy_report", writeback)
        self.assertIn("dismiss_economy_report", writeback)
        self.assertIn("_capture_end_turn_economy_report(backend_payload)", measured)
        self.assertIn("_draw_end_turn_economy_report", stack)
        self.assertIn("ROUND ECONOMY", stack)
        self.assertIn("Income %s   Maintenance %s", stack)
        self.assertIn("Net %s   Treasury %s", stack)
        self.assertIn("other_actors_summary", stack)
        self.assertIn("Dismiss report", stack)
        self.assertIn("KEY_ESCAPE", stack)

    def test_overlay_is_event_driven_not_per_province_process(self) -> None:
        writeback = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        stack = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        measured = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(encoding="utf-8")
        self.assertIn("_capture_end_turn_economy_report(backend_payload)", writeback)
        self.assertIn("queue_redraw()", writeback)
        self.assertNotIn("func _process", writeback)
        self.assertNotIn("func _process", stack)
        self.assertNotIn("func _process", measured)
        self.assertNotIn('for province in snapshot.get("provinces"', stack)
        overlay = stack.split("func _draw_end_turn_economy_report()", 1)[1].split(
            "func pending_battle_modal_model()", 1
        )[0]
        self.assertNotIn("provinces", overlay)
        self.assertIn("if not economy_report_open:", overlay)


if __name__ == "__main__":
    unittest.main()
