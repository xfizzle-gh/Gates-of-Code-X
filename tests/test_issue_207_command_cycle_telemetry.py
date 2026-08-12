from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, frontend, frontend_commands


ROOT = Path(__file__).resolve().parents[1]


class CommandCycleTelemetryTests(unittest.TestCase):
    def test_telemetry_contract_has_stable_phase_keys(self) -> None:
        self.assertEqual(
            (
                "load_ms",
                "mutate_ms",
                "save_ms",
                "snapshot_ms",
                "total_ms",
                "campaign_bytes",
                "snapshot_bytes",
                "read_only_fast_path",
            ),
            command_cycle_perf.timing_keys(),
        )

    def test_verify_only_skips_redundant_save_and_snapshot_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text('{"existing":true}\n', encoding="utf-8")

            def fake_apply(campaign_path, *, commands, commands_path, snapshot_path):
                # The measured wrapper installs read-only no-op writers before
                # delegating here. If they call the original sentinels below,
                # this test fails.
                frontend_commands.save_campaign(object(), campaign_path)
                frontend.write_frontend_snapshot(
                    object(),
                    snapshot_path,
                    campaign_path=campaign_path,
                )
                return {
                    "ok": True,
                    "campaign_path": str(campaign_path),
                    "snapshot_path": str(snapshot_path),
                    "commands_applied": 1,
                    "results": [
                        {
                            "op": "verify_result",
                            "ok": True,
                            "detail": "verified",
                            "data": {"verified": True},
                        }
                    ],
                }

            with (
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
                patch.object(
                    frontend_commands,
                    "save_campaign",
                    side_effect=AssertionError("verify_result must not save campaign"),
                ),
                patch.object(
                    frontend,
                    "write_frontend_snapshot",
                    side_effect=AssertionError("verify_result must not publish snapshot"),
                ),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "verify_result"}],
                    snapshot_path=snapshot,
                )

            timings = report["timings"]
            self.assertTrue(timings["read_only_fast_path"])
            self.assertEqual(0.0, timings["save_ms"])
            self.assertEqual(0.0, timings["snapshot_ms"])
            self.assertEqual(campaign.stat().st_size, timings["campaign_bytes"])
            self.assertEqual(snapshot.stat().st_size, timings["snapshot_bytes"])
            self.assertGreaterEqual(timings["total_ms"], 0.0)

    def test_mutating_command_still_uses_existing_save_and_snapshot_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            calls = {"save": 0, "snapshot": 0}

            def fake_save(_state, path, *, observation_context=None):
                calls["save"] += 1
                Path(path).write_text('{"saved":true}\n', encoding="utf-8")
                return Path(path)

            def fake_snapshot(_state, path, *, campaign_path=None, environ=None):
                calls["snapshot"] += 1
                Path(path).write_text('{"snapshot":true}\n', encoding="utf-8")
                return Path(path)

            def fake_apply(campaign_path, *, commands, commands_path, snapshot_path):
                frontend_commands.save_campaign(object(), campaign_path)
                frontend.write_frontend_snapshot(
                    object(), snapshot_path, campaign_path=campaign_path
                )
                return {
                    "ok": True,
                    "campaign_path": str(campaign_path),
                    "snapshot_path": str(snapshot_path),
                    "commands_applied": 1,
                    "results": [{"op": "end_player_round", "ok": True, "data": {}}],
                }

            with (
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
                patch.object(frontend_commands, "save_campaign", fake_save),
                patch.object(frontend, "write_frontend_snapshot", fake_snapshot),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "end_player_round"}],
                    snapshot_path=snapshot,
                )

            self.assertEqual(1, calls["save"])
            self.assertEqual(1, calls["snapshot"])
            self.assertFalse(report["timings"]["read_only_fast_path"])
            self.assertGreaterEqual(report["timings"]["save_ms"], 0.0)
            self.assertGreaterEqual(report["timings"]["snapshot_ms"], 0.0)

    def test_runtime_installer_registers_measured_wrapper(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("install_command_cycle_perf_path", source)
        self.assertIn("install_command_cycle_perf_path()", source)


class GodotMeasuredCommandTests(unittest.TestCase):
    def test_main_scene_uses_measured_perf_layer(self) -> None:
        scene = (ROOT / "godot/main.tscn").read_text(encoding="utf-8")
        self.assertIn('path="res://scripts/main_perf_measured.gd"', scene)
        self.assertIn('path="res://scripts/main_stack_panel.gd"', scene)

    def test_verify_result_does_not_reparse_unchanged_snapshot(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        verify_branch = source.split('if op != "verify_result":', 1)[1]
        self.assertIn("super._on_command_finished", verify_branch)
        self.assertIn("_capture_verification(backend_payload)", verify_branch)
        self.assertIn("_append_backend_timing(backend_payload)", verify_branch)
        self.assertNotIn("_try_build_snapshot_state", source)
        self.assertIn("read-only", source)

    def test_godot_status_exposes_backend_phase_breakdown(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("load %.2f", source)
        self.assertIn("mutate %.2f", source)
        self.assertIn("save %.2f", source)
        self.assertIn("snapshot %.2f", source)


if __name__ == "__main__":
    unittest.main()
