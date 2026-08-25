from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GodotActorForcePanelContractTests(unittest.TestCase):
    def test_stack_panel_draws_treasury_and_force_actions(self) -> None:
        stack = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        writeback = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn('snapshot.get("acting_actor"', writeback)
        self.assertIn("acting_actor_block", stack)
        self.assertIn("Manage Forces", stack)
        self.assertIn("_draw_force_management", stack)
        self.assertIn("FORCE MANAGEMENT", stack)
        self.assertIn("Repair condition", stack)
        self.assertIn("Command %s", stack)
        self.assertIn("command_actor_id", stack)
        self.assertIn('"formation": selected_strategic_formation_id', writeback)
        self.assertIn('"op": "actor_force_panel"', writeback)
        self.assertIn('"op": "research"', writeback)
        self.assertIn('"op": "recruit"', writeback)
        self.assertIn('"op": "assign"', writeback)
        self.assertIn('"op": "repair"', writeback)
        self.assertIn("request_force_panel", stack)
        self.assertIn("force_management_open", writeback)
        color = (ROOT / "godot/scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("KEY_M", color)
        self.assertNotIn("KEY_1", color)
        self.assertNotIn("_first_force_spend_button_id", writeback)
        self.assertNotIn("authorized_roster", stack)
        self.assertNotIn('battalion.get("roster"', stack)

    def test_force_panel_is_event_driven_not_per_province_process(self) -> None:
        stack = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        writeback = (ROOT / "godot/scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("request_force_panel()", stack)
        self.assertIn("_unhandled_input", stack)
        self.assertNotIn("for province in snapshot.get(\"provinces\"", stack)
        self.assertIn('if is_command_busy():', writeback)
        self.assertIn("queue_redraw()", writeback)

    def test_godot_map_runs_headless_force_panel_script(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        self.assertIn("actor_force_panel_test.gd", workflow)
        self.assertIn("Godot actor force-management panel test (#149)", workflow)

    def test_force_management_skips_battalion_list_while_open(self) -> None:
        stack = (ROOT / "godot/scripts/main_stack_panel.gd").read_text(encoding="utf-8")
        draw_at = stack.find("func _draw_stack_section(")
        header_at = stack.find("_draw_formation_header(", draw_at)
        fm_at = stack.find("_draw_force_management(", header_at)
        bn_at = stack.find("BATTALIONS IN FORMATION", header_at)
        self.assertGreater(header_at, draw_at)
        self.assertGreater(fm_at, header_at)
        self.assertGreater(bn_at, fm_at)
        skip = stack[header_at:fm_at]
        self.assertIn("force_management_open", skip)
        self.assertNotIn('selected_strategic_formation_id = ""', skip)
        self.assertNotIn('selected_battalion_id = ""', skip)
        self.assertIn("BATTALIONS IN FORMATION", stack)
        self.assertIn("TACTICAL UNITS IN SELECTED BATTALION", stack)
        self.assertIn("Repair condition", stack)


if __name__ == "__main__":
    unittest.main()
