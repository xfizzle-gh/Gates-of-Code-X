from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CommandLatencyCaptureContractTests(unittest.TestCase):
    def test_capture_uses_production_command_shapes(self) -> None:
        script = (ROOT / "tools/capture_command_latency.py").read_text(encoding="utf-8")
        wrapper = (ROOT / "tools/run_command_latency_capture.ps1").read_text(encoding="utf-8")
        self.assertIn("Owner files are not written", wrapper)
        self.assertIn("move_click_batch", script)
        self.assertIn('"op": "end_player_round"', script)
        self.assertIn("_create_prepared_contact", script)
        self.assertIn("input_to_visible_ms", script)
        self.assertIn("auto_resolve", script)
        self.assertIn("subprocess", script)
        self.assertIn("map_command_reload_latency.gd", script)
        self.assertIn("_clone_prepared", script)
        self.assertNotIn("pending_battle =", script)

    def test_godot_reload_script_is_read_only(self) -> None:
        script = (ROOT / "godot/scripts/tools/map_command_reload_latency.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("_try_build_snapshot_state", script)
        self.assertIn("reload_to_visible_ms", script)
        self.assertIn("draw_ms", script)
        self.assertNotIn("first_visible_ms", script)
        self.assertNotIn("save_campaign", script)
        self.assertNotIn("auto_resolve", script)


if __name__ == "__main__":
    unittest.main()
