from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import fast_entrypoint


ROOT = Path(__file__).resolve().parents[1]


class StartupTelemetryTests(unittest.TestCase):
    def test_packaged_runner_stamps_epoch_before_importing_application(self) -> None:
        source = (ROOT / "run_gates_of_codex.py").read_text(encoding="utf-8")
        self.assertLess(
            source.index('"GATES_OF_CODEX_STARTUP_EPOCH_MS"'),
            source.index("from gates_of_codex.fast_entrypoint import player_main"),
        )
        self.assertLess(
            source.index('"GATES_OF_CODEX_STARTUP_TELEMETRY"'),
            source.index("from gates_of_codex.fast_entrypoint import player_main"),
        )

    def test_windowed_runner_installs_durable_output_before_application_import(self) -> None:
        source = (ROOT / "run_gates_of_codex.py").read_text(encoding="utf-8")
        application_import = source.index(
            "from gates_of_codex.fast_entrypoint import player_main"
        )
        self.assertIn("def _install_windowed_output()", source)
        self.assertIn("if sys.stdout is None:", source)
        self.assertIn("if sys.stderr is None:", source)
        self.assertIn("startup_telemetry.jsonl", source)
        self.assertLess(source.index("\n_install_windowed_output()\n"), application_import)

    def test_startup_emitter_uses_durable_json_line(self) -> None:
        output = io.StringIO()
        with (
            patch.dict(
                os.environ,
                {
                    fast_entrypoint.STARTUP_TELEMETRY_ENV: "1",
                    fast_entrypoint.STARTUP_EPOCH_ENV: "1000.000",
                },
                clear=False,
            ),
            patch.object(fast_entrypoint.time, "time", return_value=1.25),
            redirect_stdout(output),
        ):
            fast_entrypoint._emit_startup_timing(
                "campaign_discovery",
                duration_ms=12.5,
                ok=True,
            )

        line = output.getvalue().strip()
        self.assertTrue(line.startswith("GOC_STARTUP "))
        payload = json.loads(line.split(" ", 1)[1])
        self.assertEqual("campaign_discovery", payload["stage"])
        self.assertEqual(12.5, payload["duration_ms"])
        self.assertEqual(250.0, payload["since_process_entry_ms"])
        self.assertTrue(payload["ok"])

    def test_startup_phases_cover_required_continue_boundaries(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        for stage in (
            "campaign_discovery",
            "campaign_path_resolution",
            "stack_validation",
            "campaign_load_validate_persist",
            "frontend_snapshot_build_write",
            "godot_project_import",
            "persistent_backend_start_health",
            "godot_process_launch",
            "frozen_authority_configuration",
        ):
            self.assertIn(stage, source)

    def test_godot_first_usable_frame_is_cross_process_timed(self) -> None:
        script = (ROOT / "godot/scripts/main_startup_measured.gd").read_text(
            encoding="utf-8"
        )
        scene = (ROOT / "godot/main.tscn").read_text(encoding="utf-8")
        self.assertIn('extends "res://scripts/main_perf_measured.gd"', script)
        self.assertIn("super._ready()", script)
        self.assertIn("await get_tree().process_frame", script)
        self.assertIn('"first_usable_strategic_frame"', script)
        self.assertIn('print("GOC_STARTUP "', script)
        self.assertIn("res://scripts/main_startup_measured.gd", scene)


if __name__ == "__main__":
    unittest.main()
