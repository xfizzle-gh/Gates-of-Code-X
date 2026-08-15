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
                "snapshot_fast_path",
                "compact_save_path",
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
                patch.object(
                    command_cycle_perf,
                    "_compact_save_campaign",
                    side_effect=AssertionError("verify_result must not compact-save campaign"),
                ),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "verify_result"}],
                    snapshot_path=snapshot,
                )

            timings = report["timings"]
            self.assertTrue(timings["read_only_fast_path"])
            self.assertFalse(timings["snapshot_fast_path"])
            self.assertFalse(timings["compact_save_path"])
            self.assertEqual(0.0, timings["save_ms"])
            self.assertEqual(0.0, timings["snapshot_ms"])
            self.assertEqual(campaign.stat().st_size, timings["campaign_bytes"])
            self.assertEqual(snapshot.stat().st_size, timings["snapshot_bytes"])
            self.assertGreaterEqual(timings["total_ms"], 0.0)

    def test_move_order_compact_saves_campaign_but_skips_full_snapshot_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text('{"existing":true}\n', encoding="utf-8")
            calls = {"save": 0, "snapshot": 0}

            def fake_save(
                _state,
                path,
                *,
                observation_context=None,
                subphase_seconds=None,
            ):
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
                    "results": [
                        {
                            "op": "issue_move_order",
                            "ok": True,
                            "detail": "draft order-1",
                            "data": {
                                "move_order": {
                                    "order_id": "order-1",
                                    "status": "draft",
                                }
                            },
                        }
                    ],
                }

            with (
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
                patch.object(command_cycle_perf, "_compact_save_campaign", fake_save),
                patch.object(frontend, "write_frontend_snapshot", fake_snapshot),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[
                        {
                            "op": "issue_move_order",
                            "formation_id": "sf-test",
                            "path_node_ids": ["a", "b"],
                        }
                    ],
                    snapshot_path=snapshot,
                )

            self.assertEqual(1, calls["save"])
            self.assertEqual(0, calls["snapshot"])
            self.assertFalse(report["timings"]["read_only_fast_path"])
            self.assertTrue(report["timings"]["snapshot_fast_path"])
            self.assertTrue(report["timings"]["compact_save_path"])
            self.assertGreaterEqual(report["timings"]["save_ms"], 0.0)
            self.assertEqual(0.0, report["timings"]["snapshot_ms"])
            self.assertEqual(
                '{"existing":true}\n', snapshot.read_text(encoding="utf-8")
            )

    def test_non_patch_mutation_uses_compact_save_and_existing_snapshot_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            calls = {"save": 0, "snapshot": 0}

            def fake_save(
                _state,
                path,
                *,
                observation_context=None,
                subphase_seconds=None,
            ):
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
                    "results": [{"op": "end_turn", "ok": True, "data": {}}],
                }

            with (
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
                patch.object(command_cycle_perf, "_compact_save_campaign", fake_save),
                patch.object(frontend, "write_frontend_snapshot", fake_snapshot),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "end_turn"}],
                    snapshot_path=snapshot,
                )

            self.assertEqual(1, calls["save"])
            self.assertEqual(1, calls["snapshot"])
            self.assertFalse(report["timings"]["read_only_fast_path"])
            self.assertFalse(report["timings"]["snapshot_fast_path"])
            self.assertTrue(report["timings"]["compact_save_path"])
            self.assertGreaterEqual(report["timings"]["save_ms"], 0.0)
            self.assertGreaterEqual(report["timings"]["snapshot_ms"], 0.0)

    def test_compact_runtime_writer_preserves_authoritative_save_pipeline(self) -> None:
        source = (ROOT / "src/gates_of_codex/command_cycle_perf.py").read_text(
            encoding="utf-8"
        )
        compact = source.split("def _compact_save_campaign(", 1)[1].split(
            "def measured_apply_frontend_commands(", 1
        )[0]
        for required in (
            "ensure_strategic_layer(state)",
            "_ensure_runtime_operational_positions(state)",
            "ensure_move_orders(state)",
            "ensure_site_control_state(state)",
            "refresh_operational_supply(state, consume_grace=False)",
            "ensure_s11_schema(state)",
            "refresh_all_observer_knowledge(state, observation_context)",
            "_profiled_campaign_validation(state, subphase_seconds)",
            "_runtime_state_json(state)",
            "temporary_path.replace(destination)",
        ):
            self.assertIn(required, compact)
        profiler = source.split("def _profiled_campaign_validation(", 1)[1].split(
            "def _ensure_runtime_operational_positions(", 1
        )[0]
        self.assertIn("state.validate()", profiler)
        self.assertNotIn("ensure_strategic_formations(state)", compact)
        self.assertNotIn("indent=2", compact)

    def test_end_round_exposes_mutation_subphase_timings(self) -> None:
        source = (ROOT / "src/gates_of_codex/turn_cycle.py").read_text(
            encoding="utf-8"
        )
        for key in (
            '"selected_end_turn_ms"',
            '"selected_actor_runtime_ms"',
            '"ai_take_turn_ms"',
            '"ai_end_turn_ms"',
            '"ai_actor_runtime_ms"',
            '"ai_take_turn_total_ms"',
            '"advance_turn_total_ms"',
            '"actor_runtime_total_ms"',
            '"perf_turn_cycle": perf',
        ):
            self.assertIn(key, source)

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

    def test_fast_commands_do_not_reparse_unchanged_snapshot(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        fast_block = source.split("func _consume_fast_command_result(", 1)[1].split(
            "func _consume_runtime_patch_result(", 1
        )[0]
        self.assertIn('op == "verify_result"', fast_block)
        self.assertIn("_capture_verification(backend_payload)", fast_block)
        self.assertIn("_apply_move_order_result_patch", fast_block)
        self.assertIn("_append_backend_timing", fast_block)
        self.assertNotIn("_try_build_snapshot_state", fast_block)

    def test_move_order_patch_is_bounded_to_returned_authoritative_order(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        patch_block = source.split(
            "func _apply_move_order_result_patch(", 1
        )[1].split("func _consume_fast_command_result(", 1)[0]
        self.assertIn('data.has("move_order")', patch_block)
        self.assertIn('force["move_order"] = data.get("move_order", null)', patch_block)
        self.assertIn('snapshot["strategic_formations"] = rows', patch_block)
        self.assertNotIn('snapshot["provinces"]', patch_block)
        self.assertNotIn('snapshot["battalions"]', patch_block)

    def test_godot_status_exposes_backend_phase_breakdown(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("load %.2f", source)
        self.assertIn("mutate %.2f", source)
        self.assertIn("save %.2f", source)
        self.assertIn("snapshot %.2f", source)
        self.assertIn(
            "round: engine %.2fs, AI %.2fs, advance %.2fs, actors %.2fs",
            source,
        )
        self.assertIn('data.get("perf_turn_cycle", {})', source)


if __name__ == "__main__":
    unittest.main()
