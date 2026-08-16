from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tools" / "run_issue212_native_acceptance.ps1"


class Issue212NativeAcceptanceRunnerTest(unittest.TestCase):
    def test_godot_gui_process_is_waited_before_result_is_read(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")

        self.assertIn("[System.Diagnostics.ProcessStartInfo]::new()", text)
        self.assertIn("$startInfo.ArgumentList.Add", text)
        self.assertIn("$godotProcess.WaitForExit()", text)
        self.assertIn("$godotProcess.ExitCode", text)
        self.assertNotIn("Start-Sleep", text)

        wait_index = text.index("$godotProcess.WaitForExit()")
        exit_index = text.index("$godotProcess.ExitCode")
        json_check_index = text.index(
            "Test-Path -LiteralPath $jsonPath -PathType Leaf"
        )
        self.assertLess(wait_index, exit_index)
        self.assertLess(exit_index, json_check_index)

    def test_profiler_exit_code_remains_fail_closed(self) -> None:
        text = RUNNER.read_text(encoding="utf-8")

        self.assertIn("if ($godotExit -ne 0)", text)
        self.assertIn(
            'throw "Issue #212 native acceptance profiler failed with exit code $godotExit"',
            text,
        )
        self.assertIn(
            'throw "Acceptance JSON was not produced: $jsonPath"',
            text,
        )


if __name__ == "__main__":
    unittest.main()
