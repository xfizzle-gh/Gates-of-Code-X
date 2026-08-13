from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import frontend, frontend_fastpath
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.frontend_fastpath import (
    build_frontend_snapshot_fast,
    write_frontend_snapshot_fast,
)
from gates_of_codex.scenario import build_scenario
from gates_of_codex.turn_cycle import end_player_round


ROOT = Path(__file__).resolve().parents[1]


class FrontendFastPathTests(unittest.TestCase):
    def test_fast_projection_is_semantically_identical(self) -> None:
        state = build_scenario("legacy_goe_europe")
        expected = frontend.build_frontend_snapshot(state)
        actual = build_frontend_snapshot_fast(state)
        self.assertEqual(expected, actual)

    def test_fast_writer_is_atomic_machine_json_with_same_payload(self) -> None:
        state = build_scenario("legacy_goe_europe")
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "campaign_snapshot.json"
            expected = build_frontend_snapshot_fast(
                state,
                snapshot_path=destination,
            )
            write_frontend_snapshot_fast(state, destination)
            text = destination.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            self.assertEqual(expected, json.loads(text))
            self.assertNotIn("\n  \"", text)

    def test_fast_path_preserves_explicit_environment_contract(self) -> None:
        state = build_scenario("legacy_goe_europe")
        environ = {"GATES_OF_CODEX_HOME": "managed-home"}
        with patch.object(
            frontend,
            "build_frontend_snapshot",
            return_value={"ok": True},
        ) as build:
            self.assertEqual(
                {"ok": True},
                build_frontend_snapshot_fast(state, environ=environ),
            )
        build.assert_called_once_with(
            state,
            campaign_path=None,
            snapshot_path=None,
            environ=environ,
        )

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "campaign_snapshot.json"
            with patch.object(
                frontend_fastpath,
                "build_frontend_snapshot_fast",
                return_value={"ok": True},
            ) as fast_build:
                write_frontend_snapshot_fast(
                    state,
                    destination,
                    environ=environ,
                )
            fast_build.assert_called_once_with(
                state,
                campaign_path=None,
                snapshot_path=destination,
                environ=environ,
            )

    def test_construction_reachability_runs_once_per_snapshot(self) -> None:
        state = build_scenario("legacy_goe_europe")
        original = frontend_fastpath._ORIGINAL_STRATEGIC_REACHABLE
        calls: list[tuple[int, str]] = []

        def counted(candidate, faction):
            calls.append((id(candidate), faction.value))
            return original(candidate, faction)

        with patch.object(
            frontend_fastpath,
            "_ORIGINAL_STRATEGIC_REACHABLE",
            side_effect=counted,
        ):
            build_frontend_snapshot_fast(state)

        selected_calls = [
            row for row in calls if row[1] == state.selected_faction.value
        ]
        self.assertEqual(1, len(selected_calls), selected_calls)

    def test_fast_path_restores_scoped_helpers(self) -> None:
        source = (ROOT / "src/gates_of_codex/frontend_fastpath.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("selected_reachable: set[str] | None = None", source)
        self.assertIn("_ORIGINAL_STRATEGIC_REACHABLE(candidate, faction)", source)
        self.assertIn("projection_identity = candidate_identity", source)
        self.assertIn("_strategic.ensure_strategic_layer = _already_initialized", source)
        self.assertIn("_strategic.reachable_supply_provinces = _snapshot_reachable", source)
        self.assertIn("finally:", source)
        self.assertIn("_strategic.ensure_strategic_layer = previous_ensure", source)
        self.assertIn("_strategic.reachable_supply_provinces = previous_reachable", source)


class PlayerTurnCycleTests(unittest.TestCase):
    def test_one_player_round_returns_control_after_all_ai_seats(self) -> None:
        state = build_scenario("legacy_goe_europe")
        starting_turn = state.turn_number
        selected = state.selected_faction
        expected_ai = [
            faction.value
            for faction in CampaignEngine.TURN_ORDER
            if faction != selected
            and faction.value in state.factions
            and not state.factions[faction.value].is_eliminated
        ]

        # This test is about turn orchestration, not AI decision quality. Keep AI
        # mutation inert while exercising the real CampaignEngine turn order.
        with patch(
            "gates_of_codex.turn_cycle.StrategicAI.take_turn",
            autospec=True,
            return_value=[],
        ):
            report = end_player_round(state)

        self.assertFalse(report["pending_battle"])
        self.assertEqual(selected, state.current_faction)
        self.assertEqual(selected.value, report["current_faction"])
        self.assertEqual(expected_ai, report["ai_factions"])
        self.assertEqual(starting_turn + 1, state.turn_number)
        self.assertIn("_observation_context", report)

    def test_earth3_round_synchronizes_actor_runtime_for_real_ai_seats(self) -> None:
        from gates_of_codex.frontend_commands import _apply_one
        from gates_of_codex.operational_order_options import (
            list_operational_move_options,
        )
        from gates_of_codex.strategic_actors import ACTOR_RUNTIME_KEY
        from test_p5_graph_native_movement import (
            CONTACT_NODE,
            PLAYER_FORMATION,
            _earth3_state,
        )

        state = _earth3_state()
        option = next(
            row
            for row in list_operational_move_options(state, state.selected_faction)
            if row["formation_id"] == PLAYER_FORMATION
            and row["target_node_id"] == CONTACT_NODE
        )
        issued = _apply_one(
            state,
            "issue_move_order",
            {
                "formation": option["formation_id"],
                "path_node_ids": list(option["path_node_ids"]),
                "path_edge_ids": list(option["path_edge_ids"]),
            },
        )
        committed = _apply_one(
            state,
            "commit_move_orders",
            {
                "faction": state.selected_faction.value,
                "locked_stance": option["locked_stance"],
            },
        )
        self.assertTrue(issued.ok, issued.detail)
        self.assertTrue(committed.ok, committed.detail)

        report = end_player_round(state)

        self.assertEqual(["ukr", "rusa"], report["ai_factions"])
        self.assertEqual(state.selected_faction, state.current_faction)
        runtime = state.map_metadata[ACTOR_RUNTIME_KEY]
        current_actor = runtime["actors"][runtime["current_actor_id"]]
        self.assertEqual(state.current_faction.value, current_actor["tactical_side"])

    def test_main_scene_uses_responsiveness_layer_and_retains_stack_contract(self) -> None:
        scene = (ROOT / "godot/main.tscn").read_text(encoding="utf-8")
        self.assertIn('path="res://scripts/main_perf.gd"', scene)
        self.assertIn('path="res://scripts/main_stack_panel.gd"', scene)
        self.assertIn("metadata/_stack_panel_contract", scene)

    def test_end_turn_dispatches_one_backend_player_round_operation(self) -> None:
        source = (ROOT / "godot/scripts/main_perf.gd").read_text(encoding="utf-8")
        self.assertIn('if button_id == "end_turn":', source)
        self.assertIn('_queue_and_apply([{"op": "end_player_round"}])', source)
        self.assertIn('End turn + AI cycle (E)', source)
        # Godot must not duplicate canonical faction order or orchestrate AI
        # itself. Python owns the whole round behind one file-backed operation.
        self.assertNotIn('PLAYER_TURN_ORDER', source)
        self.assertNotIn('"op": "run_ai"', source)

    def test_backend_player_round_uses_existing_campaign_and_ai_authority(self) -> None:
        source = (ROOT / "src/gates_of_codex/turn_cycle.py").read_text(encoding="utf-8")
        self.assertIn("CampaignEngine(state)", source)
        self.assertIn("StrategicAI(state, engine=engine)", source)
        self.assertIn("ai = shared_operational_ai or StrategicAI(state)", source)
        self.assertIn("ai.take_turn(faction)", source)
        self.assertIn("engine.end_turn()", source)
        self.assertIn("state.pending_battle is None", source)
        self.assertIn("state.current_faction != selected", source)
        self.assertIn("ai.observation_context", source)
        self.assertIn('"_observation_context": observation_context', source)
        self.assertNotIn("TURN_ORDER =", source)

    def test_overlay_has_no_all_province_ambient_label_scan(self) -> None:
        source = (ROOT / "godot/scripts/main_perf.gd").read_text(encoding="utf-8")
        overlay = source.split("func _draw_color_id_overlays() -> void:", 1)[1]
        self.assertIn("_build_overlay_active_ids()", overlay)
        self.assertIn("Labels are action context, not wallpaper", overlay)
        self.assertNotIn('snapshot.get("provinces"', overlay)
        self.assertNotIn("named and view_scale", overlay)


class RuntimeEntrypointTests(unittest.TestCase):
    def test_console_and_python_module_install_responsiveness_layer(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        module = (ROOT / "src/gates_of_codex/__main__.py").read_text(encoding="utf-8")
        runtime = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'gates-of-codex = "gates_of_codex.fast_entrypoint:main"', pyproject
        )
        self.assertIn("from .fast_entrypoint import main", module)
        self.assertIn("install_frontend_fast_path()", runtime)
        self.assertIn("install_frontend_turn_cycle_op()", runtime)


if __name__ == "__main__":
    unittest.main()
