from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, frontend, frontend_commands
from gates_of_codex import frontend_runtime_patch


ROOT = Path(__file__).resolve().parents[1]


class RuntimePatchBackendTests(unittest.TestCase):
    def test_end_player_round_saves_authority_but_skips_full_snapshot_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text('{"static":"unchanged"}\n', encoding="utf-8")
            calls = {"save": 0, "full_snapshot": 0, "runtime_patch": 0}

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

            def fake_full_snapshot(_state, path, *, campaign_path=None, environ=None):
                calls["full_snapshot"] += 1
                Path(path).write_text('{"rewritten":true}\n', encoding="utf-8")
                return Path(path)

            def fake_runtime_patch(_state, *, campaign_path=None, snapshot_path=None, environ=None):
                calls["runtime_patch"] += 1
                return {
                    "schema": frontend_runtime_patch.RUNTIME_PATCH_SCHEMA,
                    "schema_version": frontend_runtime_patch.RUNTIME_PATCH_SCHEMA_VERSION,
                    "merge": {"campaign": {"turn_number": 2}},
                    "replace": {"pending_battle": None},
                }

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
                            "op": "end_player_round",
                            "ok": True,
                            "detail": "player round complete",
                            "data": {},
                        }
                    ],
                }

            with (
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
                patch.object(command_cycle_perf, "_compact_save_campaign", fake_save),
                patch.object(frontend, "write_frontend_snapshot", fake_full_snapshot),
                patch.object(
                    frontend_runtime_patch,
                    "build_frontend_runtime_patch",
                    side_effect=fake_runtime_patch,
                ),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "end_player_round"}],
                    snapshot_path=snapshot,
                )

            self.assertEqual(1, calls["save"])
            self.assertEqual(0, calls["full_snapshot"])
            self.assertEqual(1, calls["runtime_patch"])
            self.assertEqual(
                '{"static":"unchanged"}\n', snapshot.read_text(encoding="utf-8")
            )
            self.assertEqual(
                frontend_runtime_patch.RUNTIME_PATCH_SCHEMA,
                report["frontend_patch"]["schema"],
            )
            self.assertTrue(report["timings"]["runtime_patch_fast_path"])
            self.assertFalse(report["timings"]["snapshot_fast_path"])
            self.assertTrue(report["timings"]["compact_save_path"])

    def test_runtime_patch_module_never_calls_full_snapshot_builder_or_writer(self) -> None:
        source = (ROOT / "src/gates_of_codex/frontend_runtime_patch.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("build_frontend_snapshot(", source)
        self.assertNotIn("write_frontend_snapshot(", source)
        self.assertIn("operational_provinces", source)
        self.assertIn('row.pop("metadata", None)', source)
        self.assertIn('campaign_patch.pop("map_metadata", None)', source)

    def test_runtime_patch_schema_is_versioned(self) -> None:
        self.assertEqual(
            "gates-of-codex.frontend-runtime-patch",
            frontend_runtime_patch.RUNTIME_PATCH_SCHEMA,
        )
        self.assertEqual(1, frontend_runtime_patch.RUNTIME_PATCH_SCHEMA_VERSION)


class RuntimePatchGodotTests(unittest.TestCase):
    def test_end_round_consumes_runtime_patch_without_disk_snapshot_parse(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn('RUNTIME_PATCH_OPS := ["end_player_round"]', source)
        self.assertIn("func _build_runtime_patch_state", source)
        self.assertIn("func _consume_runtime_patch_result", source)
        self.assertIn("_commit_snapshot_state(built", source)
        block = source.split("func _consume_runtime_patch_result(", 1)[1].split(
            "func _on_command_finished(", 1
        )[0]
        self.assertNotIn("_try_build_snapshot_state", block)
        self.assertIn("previous_snapshot := snapshot.duplicate(true)", block)
        self.assertIn("operational_presenter.begin_transition", block)

    def test_patch_candidate_validates_before_live_commit(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        block = source.split("func _build_runtime_patch_state(", 1)[1].split(
            "func _consume_fast_command_result(", 1
        )[0]
        self.assertIn("var candidate := snapshot.duplicate(true)", block)
        self.assertIn("_validate_battalion_stack_contract_on(candidate", block)
        self.assertIn("index_operational_orders(candidate)", block)
        self.assertNotIn("snapshot = candidate", block)


if __name__ == "__main__":
    unittest.main()
