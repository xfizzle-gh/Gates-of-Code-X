from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"


class GodotAsyncWritebackTests(unittest.TestCase):
    def test_command_runner_exists_and_is_threaded(self) -> None:
        src = (GODOT / "scripts/presentation/command_runner.gd").read_text(encoding="utf-8")
        self.assertIn("class_name FrontendCommandRunner", src)
        self.assertIn("Thread", src)
        self.assertIn("OS.execute", src)
        self.assertIn("call_deferred", src)
        self.assertIn("command_finished", src)
        self.assertIn("duplicate_in_flight", src)
        self.assertIn("_shutting_down", src)
        self.assertIn("generation", src)
        # Worker must not touch Node APIs beyond call_deferred.
        self.assertIn("WORKER THREAD", src)

    def test_writeback_uses_async_runner_not_sync_execute(self) -> None:
        wb = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("FrontendCommandRunnerScript", wb)
        self.assertIn("try_start", wb)
        self.assertIn("_on_command_finished", wb)
        self.assertIn("is_command_busy", wb)
        self.assertIn("Duplicate", wb)
        # Success path reloads snapshot; failure must not call _load_snapshot before return.
        fail_idx = wb.index("if not success:")
        # After failure block, success continues to _load_snapshot
        self.assertIn("_load_snapshot(load_path)", wb)
        # No direct OS.execute in writeback apply path.
        self.assertNotIn("OS.execute(", wb)

    def test_busy_disables_mutating_controls(self) -> None:
        wb = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("_command_mutates_state", wb)
        self.assertIn("is_command_busy() and _command_mutates_state", wb)
        color = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("_draw_command_busy_overlay", color)
        self.assertIn("KEY_E,KEY_A,KEY_H,KEY_R", color.replace(" ", ""))

    def test_godot_runtime_test_script_present(self) -> None:
        src = (GODOT / "scripts/tools/command_runner_test.gd").read_text(encoding="utf-8")
        required = [
            "duplicate rejected",
            "busy after start",
            "one finished event",
            "stale did not finish",
            "exit during command did not crash",
            "not busy after failure",
            "try_start",
        ]
        for token in required:
            self.assertIn(token, src)

    def test_workflow_runs_command_runner_test(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        self.assertIn("command_runner_test.gd", workflow)

    def test_failure_does_not_reload_snapshot(self) -> None:
        wb = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        # Ensure failure branch returns before _load_snapshot.
        block = wb.split("if not success:")[1].split("Success:")[0]
        self.assertIn("Preserve current valid snapshot", block)
        self.assertNotIn("_load_snapshot", block)


if __name__ == "__main__":
    unittest.main()
