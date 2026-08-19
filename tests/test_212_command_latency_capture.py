from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CommandLatencyCaptureContractTests(unittest.TestCase):
    def test_capture_uses_a_copy_and_production_ops(self) -> None:
        script = (ROOT / "tools/capture_command_latency.py").read_text(encoding="utf-8")
        wrapper = (ROOT / "tools/run_command_latency_capture.ps1").read_text(encoding="utf-8")
        self.assertIn("Owner files are not written", wrapper)
        self.assertIn("end_player_round", script)
        self.assertIn("auto_resolve", script)
        self.assertIn("issue_move_order", script)
        self.assertIn("commit_move_orders", script)
        self.assertIn("install_frontend_turn_cycle_op", script)
        self.assertIn("shutil.copy2", script)
        self.assertIn(".goc-backend-session.json", script)

    def test_wrapper_defaults_to_last_campaign_pointer(self) -> None:
        wrapper = (ROOT / "tools/run_command_latency_capture.ps1").read_text(encoding="utf-8")
        self.assertIn("last_campaign.json", wrapper)
        self.assertIn("capture_command_latency.py", wrapper)


if __name__ == "__main__":
    unittest.main()
