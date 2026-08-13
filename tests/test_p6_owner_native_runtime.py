"""P6 regressions for owner-native player startup and frozen write-back seams."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gates_of_codex import fast_entrypoint
from gates_of_codex.player_shell import PlayerShellError


ROOT = Path(__file__).resolve().parents[1]


class P6OwnerNativeRuntimeTests(unittest.TestCase):
    def test_godot_import_completes_synchronously_before_gui_launch(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="Godot Engine v4.7\n", stderr=""
        )
        with patch(
            "gates_of_codex.fast_entrypoint.subprocess.run",
            return_value=completed,
        ) as run:
            fast_entrypoint._prepare_godot_project(
                Path("C:/Godot/Godot.exe"),
                Path("C:/Gates/godot"),
            )

        arguments = run.call_args.args[0]
        self.assertEqual("C:/Godot/Godot.exe", arguments[0].replace("\\", "/"))
        self.assertIn("--headless", arguments)
        self.assertIn("--import", arguments)
        self.assertEqual(["--quit-after", "1"], arguments[-2:])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual("C:/Gates/godot", run.call_args.kwargs["cwd"].replace("\\", "/"))

    def test_godot_import_parse_error_fails_before_interactive_launch(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='SCRIPT ERROR: Parse Error: Could not resolve class "main_stack_panel.gd"',
            stderr="",
        )
        with patch(
            "gates_of_codex.fast_entrypoint.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaises(PlayerShellError) as raised:
                fast_entrypoint._prepare_godot_project(
                    Path("Godot.exe"), Path("deployed/godot")
                )
        self.assertIn("Godot project import failed", str(raised.exception))

    def test_packaged_player_normalizes_embedded_module_backend_invocation(self) -> None:
        general_main = Mock(return_value=0)
        shell_main = Mock(return_value=99)
        with (
            patch("gates_of_codex.fast_entrypoint._install_fast_paths"),
            patch("gates_of_codex.fast_entrypoint.main", general_main),
            patch("gates_of_codex.frozen_runtime.configure_frozen_earth3_authority"),
            patch("gates_of_codex.player_shell.main", shell_main),
            patch.object(sys, "frozen", False, create=True),
        ):
            code = fast_entrypoint.player_main(
                [
                    "-m",
                    "gates_of_codex",
                    "apply-frontend",
                    "campaign.json",
                    "--snapshot",
                    "campaign_snapshot.json",
                    "--commands",
                    "frontend_commands.json",
                ]
            )

        self.assertEqual(0, code)
        general_main.assert_called_once_with(
            [
                "apply-frontend",
                "campaign.json",
                "--snapshot",
                "campaign_snapshot.json",
                "--commands",
                "frontend_commands.json",
            ]
        )
        shell_main.assert_not_called()

    def test_direct_player_flags_stay_on_player_shell(self) -> None:
        shell_main = Mock(return_value=0)
        with (
            patch("gates_of_codex.fast_entrypoint._install_fast_paths"),
            patch("gates_of_codex.frozen_runtime.configure_frozen_earth3_authority"),
            patch("gates_of_codex.player_shell.main", shell_main),
            patch("gates_of_codex.player_shell.read_last_campaign") as remembered,
            patch.object(sys, "frozen", False, create=True),
        ):
            self.assertEqual(
                0,
                fast_entrypoint.player_main(
                    ["--continue", "--campaign", "campaign.json"]
                ),
            )
        shell_main.assert_called_once_with(
            ["--continue", "--campaign", "campaign.json"]
        )
        remembered.assert_not_called()

    def test_frozen_runtime_publishes_console_backend_and_stable_godot_map_path(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('with_name("GatesOfCodeXLive.exe")', source)
        self.assertIn("_require_frozen_console_backend", source)
        self.assertIn('block["python_executable"] = str(backend)', source)
        self.assertIn('block["backend_kind"] = "frozen_console"', source)
        self.assertIn('block["manifest_path"] = f"res://{CAMPAIGN_MANIFEST_IDENTIFIER}"', source)
        self.assertIn("_prepare_godot_project", source)

    def test_live_console_keeps_acceptance_commands_and_routes_writeback_cli(self) -> None:
        source = (ROOT / "run_gates_of_codex_live.py").read_text(encoding="utf-8")
        self.assertIn('"validate"', source)
        self.assertIn('"handoff"', source)
        self.assertIn('["-m", "gates_of_codex"]', source)
        self.assertIn("from gates_of_codex.fast_entrypoint import main as application_main", source)
        self.assertIn("return application_main(arguments)", source)


if __name__ == "__main__":
    unittest.main()
