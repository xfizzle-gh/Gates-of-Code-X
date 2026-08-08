from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"


class GodotAsyncWritebackTests(unittest.TestCase):
    def test_command_runner_exists_and_is_threaded(self) -> None:
        src = (GODOT / "scripts/presentation/command_runner.gd").read_text(encoding="utf-8")
        self.assertIn("extends Node", src)
        self.assertIn("Thread", src)
        self.assertIn("OS.execute", src)
        self.assertIn("call_deferred", src)
        self.assertIn("command_finished", src)
        self.assertIn("duplicate_in_flight", src)
        self.assertIn("_shutting_down", src)
        self.assertIn("generation", src)
        self.assertIn("try_start_candidates", src)
        self.assertIn("could_not_launch", src)
        self.assertIn("exit_code == 127", src)
        self.assertIn("WORKER THREAD", src)

    def test_writeback_transactional_commit_path(self) -> None:
        wb = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("FrontendCommandRunnerScript", wb)
        self.assertIn("try_start_candidates", wb)
        self.assertIn("_on_command_finished", wb)
        self.assertIn("is_command_busy", wb)
        self.assertIn("Duplicate", wb)
        self.assertIn("_try_build_snapshot_state", wb)
        self.assertIn("_commit_snapshot_state", wb)
        self.assertIn("_payload_failure_detail", wb)
        self.assertIn("_fail_command", wb)
        self.assertIn("snapshot_commit_count", wb)
        # No direct OS.execute in writeback apply path.
        self.assertNotIn("OS.execute(", wb)
        # Failure path must not call destructive _load_snapshot.
        self.assertIn("_fail_command(op, detail)", wb)
        fail_section = wb.split("if not success or exit_code != 0:")[1].split(
            "# 2) Payload ok:false"
        )[0]
        self.assertNotIn("_load_snapshot", fail_section)
        self.assertNotIn("_commit_snapshot_state", fail_section)

    def test_backend_launch_fallback_order(self) -> None:
        wb = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("_backend_launch_candidates", wb)
        # Authority markers in order a → b → c.
        a = wb.index("python_executable")
        b = wb.index('"gates-of-codex"')
        c = wb.index('"python"')
        self.assertLess(a, b)
        self.assertLess(b, c)
        compact = wb.replace(" ", "")
        self.assertIn('["-m",python_module]', compact)
        self.assertIn('["-m","gates_of_codex"]', compact)

    def test_busy_disables_mutating_controls(self) -> None:
        wb = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("_command_mutates_state", wb)
        self.assertIn("is_command_busy() and _command_mutates_state", wb)
        self.assertIn("enabled_action_button_ids", wb)
        color = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("_draw_command_busy_overlay", color)
        self.assertIn("KEY_E,KEY_A,KEY_H,KEY_R", color.replace(" ", ""))

    def test_godot_runtime_test_scripts_present(self) -> None:
        runner = (GODOT / "scripts/tools/command_runner_test.gd").read_text(encoding="utf-8")
        for token in [
            "duplicate rejected",
            "busy after start",
            "one finished event",
            "stale did not finish",
            "exit during command did not crash",
            "not busy after failure",
            "try_start",
        ]:
            self.assertIn(token, runner)
        integ = (GODOT / "scripts/tools/writeback_integration_test.gd").read_text(
            encoding="utf-8"
        )
        for token in [
            "duplicate end_turn one submit",
            "duplicate move one submit",
            "different command not submitted",
            "end_turn disabled while busy",
            "pan applied while busy",
            "zoom applied while busy",
            "processed frames during slow command",
            "success commit once",
            "selection province restored",
            "failure no commit",
            "missing snap no commit",
            "malformed no commit",
            "wrong schema no commit",
            "ok:false no commit",
            "end_turn enabled after failure",
            "stale did not commit",
            "free during slow command did not crash",
            "fallback finished once",
            "inject_command_runner",
        ]:
            self.assertIn(token, integ)
        fake = (GODOT / "scripts/tools/fake_command_runner.gd").read_text(encoding="utf-8")
        self.assertIn("try_start_candidates", fake)
        self.assertIn("scripted_results", fake)

    def test_workflow_runs_runner_and_integration_tests(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        self.assertIn("command_runner_test.gd", workflow)
        self.assertIn("writeback_integration_test.gd", workflow)

    def test_workflow_runs_both_s10_godot_suites_as_distinct_headless_steps(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        scripts = (
            "operational_resolution_presenter_test.gd",
            "operational_presentation_scene_test.gd",
        )
        for script in scripts:
            self.assertEqual(1, workflow.count(script))
            before_script = workflow[: workflow.index(script)]
            step = before_script[before_script.rfind("      - name:") :]
            self.assertIn("S10", step)
            self.assertIn('"$HOME/godot" --headless --path .', step)

    def test_frontend_writeback_contract_async_invocation(self) -> None:
        script = (GODOT / "scripts/main_writeback.gd").read_text(encoding="utf-8")
        self.assertIn("FileAccess.file_exists(python_executable)", script)
        self.assertIn("command_runner.try_start_candidates", script)
        self.assertIn("FrontendCommandRunnerScript", script)
        runner = (GODOT / "scripts/presentation/command_runner.gd").read_text(encoding="utf-8")
        self.assertIn("OS.execute", runner)
        self.assertIn("call_deferred", runner)


if __name__ == "__main__":
    unittest.main()
