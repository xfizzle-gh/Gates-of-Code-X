from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gates_of_codex import command_cycle_perf, frontend, frontend_commands
from gates_of_codex.command_cycle_perf import _should_persist_runtime_snapshot
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.frontend_commands import READ_ONLY_OPS, apply_frontend_commands
from gates_of_codex.frontend_runtime_patch import RUNTIME_PATCH_SCHEMA_VERSION
from gates_of_codex.frontend_snapshot_slim import FRONTEND_OMITTED_BATTALION_FIELDS
from gates_of_codex.state_io import campaign_from_dict, save_campaign
from gates_of_codex.supply import (
    CONNECTED_SUPPLY_STATE,
    CUT_OFF_SUPPLY_EFFECT,
    CUT_OFF_SUPPLY_STATE,
    GRACE_SUPPLY_STATE,
    INITIAL_DISCONNECTED_SUPPLY_STATE,
    OPERATIONAL_SUPPLY_STATES,
    formation_supply_state,
    query_supply_status,
)
from tests.test_operational_s8_supply import _lifecycle_state, _only_force, _state


ROOT = Path(__file__).resolve().parents[1]


def _graph_patches(graph: dict):
    return mock.patch.multiple(
        "gates_of_codex.supply",
        load_operational_graph_for_state=mock.Mock(return_value=graph),
    )


class QuerySupplyPresentationTests(unittest.TestCase):
    def test_query_classifies_the_four_s8_shapes(self) -> None:
        cases = (
            (
                CONNECTED_SUPPLY_STATE,
                {
                    "supplied": True,
                    "cut_off": False,
                    "source_hub_id": "province-supply-source:p-source",
                    "route_cost": 4,
                    "grace_ticks_remaining": 0,
                },
            ),
            (
                INITIAL_DISCONNECTED_SUPPLY_STATE,
                {
                    "supplied": True,
                    "cut_off": False,
                    "source_hub_id": None,
                    "route_cost": None,
                    "grace_ticks_remaining": 0,
                },
            ),
            (
                GRACE_SUPPLY_STATE,
                {
                    "supplied": True,
                    "cut_off": False,
                    "source_hub_id": None,
                    "route_cost": None,
                    "grace_ticks_remaining": 1,
                },
            ),
            (
                CUT_OFF_SUPPLY_STATE,
                {
                    "supplied": False,
                    "cut_off": True,
                    "source_hub_id": None,
                    "route_cost": None,
                    "grace_ticks_remaining": 0,
                },
            ),
        )
        for expected, fields in cases:
            with self.subTest(expected=expected):
                state, graph = _lifecycle_state(connected=False)
                force = _only_force(state)
                for key, value in fields.items():
                    setattr(force, key, value)
                self.assertEqual(expected, formation_supply_state(force))
                with _graph_patches(graph):
                    payload = query_supply_status(
                        state,
                        strategic_formation_id=force.strategic_formation_id,
                    )
                self.assertEqual("operational_graph", payload["authority"])
                self.assertEqual(force.province_id, payload["province_id"])
                self.assertEqual(1, len(payload["formations"]))
                row = payload["formations"][0]
                self.assertEqual(force.strategic_formation_id, row["strategic_formation_id"])
                self.assertEqual(expected, row["supply_state"])
                self.assertIn(row["supply_state"], OPERATIONAL_SUPPLY_STATES)
                self.assertEqual(fields["supplied"], row["supplied"])
                self.assertEqual(fields["cut_off"], row["cut_off"])
                self.assertEqual(fields["source_hub_id"], row["source_hub_id"])
                self.assertEqual(
                    fields["grace_ticks_remaining"], row["grace_ticks_remaining"]
                )
                self.assertNotIn("roster", row)
                self.assertNotIn("authorized_roster", row["readiness"])
                self.assertEqual(int(force.supply_summary), row["readiness"]["supply"])
                self.assertIn("can_repair", row["readiness"])
                self.assertIn("encircled_turns", row["readiness"])
                self.assertTrue(row["effect"])

    def test_cut_off_query_quotes_existing_drain_and_repair_gate(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        force.source_hub_id = None
        force.route_cost = None
        force.grace_ticks_remaining = 0
        battalion = state.battalions["nato-route"]
        battalion.supply = 40
        battalion.encircled_turns = 1
        with _graph_patches(graph):
            row = query_supply_status(
                state, strategic_formation_id=force.strategic_formation_id
            )["formations"][0]
        self.assertEqual(CUT_OFF_SUPPLY_STATE, row["supply_state"])
        self.assertFalse(row["readiness"]["can_repair"])
        self.assertEqual(1, row["readiness"]["encircled_turns"])
        self.assertEqual(CUT_OFF_SUPPLY_EFFECT, row["effect"])

    def test_unknown_or_mismatched_targets_fail_closed(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        with _graph_patches(graph):
            with self.assertRaisesRegex(ValueError, "query_supply requires"):
                query_supply_status(state)
            with self.assertRaisesRegex(ValueError, "unknown_strategic_formation"):
                query_supply_status(state, strategic_formation_id="missing-force")
            with self.assertRaisesRegex(ValueError, "unknown_province"):
                query_supply_status(state, province_id="missing-province")
            with self.assertRaisesRegex(ValueError, "formation_not_in_province"):
                query_supply_status(
                    state,
                    strategic_formation_id=force.strategic_formation_id,
                    province_id="p-source",
                )

    def test_province_query_is_bounded_to_that_province(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        with _graph_patches(graph):
            payload = query_supply_status(state, province_id=force.province_id)
            empty = query_supply_status(state, province_id="p-source")
        self.assertEqual(
            [force.strategic_formation_id],
            [row["strategic_formation_id"] for row in payload["formations"]],
        )
        self.assertEqual([], empty["formations"])

    def test_save_load_preserves_grace_query(self) -> None:
        state, graph = _lifecycle_state(connected=False)
        state.schema_version = 8
        force = _only_force(state)
        force.supplied = True
        force.cut_off = False
        force.source_hub_id = None
        force.route_cost = None
        force.grace_ticks_remaining = 1
        loaded = campaign_from_dict(state.to_dict())
        restored = _only_force(loaded)
        self.assertEqual(1, restored.grace_ticks_remaining)
        self.assertTrue(restored.supplied)
        self.assertFalse(restored.cut_off)
        with _graph_patches(graph):
            before = query_supply_status(
                state, strategic_formation_id=force.strategic_formation_id
            )
            after = query_supply_status(
                loaded, strategic_formation_id=restored.strategic_formation_id
            )
        self.assertEqual(GRACE_SUPPLY_STATE, before["formations"][0]["supply_state"])
        self.assertEqual(before["formations"][0], after["formations"][0])

    def test_query_supply_command_is_read_only_and_not_a_patch_op(self) -> None:
        self.assertIn("query_supply", READ_ONLY_OPS)
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "query_supply"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertTrue(
            _should_persist_runtime_snapshot(
                [{"op": "issue_move_order"}, {"op": "commit_move_orders"}]
            )
        )
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))
        self.assertEqual(1, RUNTIME_PATCH_SCHEMA_VERSION)

        state = _state()
        force = _only_force(state)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            save_campaign(state, campaign)
            frontend.write_frontend_snapshot(state, snapshot, campaign_path=campaign)
            before_campaign = campaign.read_bytes()
            before_snapshot = snapshot.read_bytes()
            result = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "query_supply",
                        "strategic_formation_id": force.strategic_formation_id,
                    }
                ],
                snapshot_path=snapshot,
            )
            self.assertTrue(result["ok"])
            self.assertEqual("query_supply", result["results"][0]["op"])
            self.assertTrue(result["results"][0]["ok"])
            self.assertEqual(before_campaign, campaign.read_bytes())
            self.assertEqual(before_snapshot, snapshot.read_bytes())
            self.assertIn("formations", result["results"][0]["data"])

    def test_measured_query_supply_uses_read_only_fast_path(self) -> None:
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
                            "op": "query_supply",
                            "ok": True,
                            "detail": "supply sf-test",
                            "data": {"authority": "operational_graph", "formations": []},
                        }
                    ],
                }

            with (
                mock.patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
                mock.patch.object(
                    frontend_commands,
                    "save_campaign",
                    side_effect=AssertionError("query_supply must not save campaign"),
                ),
                mock.patch.object(
                    frontend,
                    "write_frontend_snapshot",
                    side_effect=AssertionError("query_supply must not publish snapshot"),
                ),
                mock.patch.object(
                    command_cycle_perf,
                    "_compact_save_campaign",
                    side_effect=AssertionError("query_supply must not compact-save campaign"),
                ),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "query_supply", "strategic_formation_id": "sf-test"}],
                    snapshot_path=snapshot,
                )

            self.assertTrue(report["timings"]["read_only_fast_path"])
            self.assertFalse(report["timings"]["runtime_patch_fast_path"])
            self.assertEqual(0.0, report["timings"]["save_ms"])
            self.assertEqual(0.0, report["timings"]["snapshot_ms"])
            self.assertEqual(b"{}\n", campaign.read_bytes())
            self.assertEqual(b'{"existing":true}\n', snapshot.read_bytes())

    def test_slim_snapshot_still_omits_roster_and_keeps_existing_supply_fields(self) -> None:
        self.assertEqual(
            frozenset({"roster", "authorized_roster"}),
            FRONTEND_OMITTED_BATTALION_FIELDS,
        )
        state, graph = _lifecycle_state(connected=False)
        force = _only_force(state)
        force.supplied = False
        force.cut_off = True
        force.source_hub_id = None
        force.route_cost = None
        with mock.patch(
            "gates_of_codex.operational_position.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_capture.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.operational_supply.load_operational_graph_for_state",
            return_value=graph,
        ), mock.patch(
            "gates_of_codex.supply.load_operational_graph_for_state",
            return_value=graph,
        ):
            snapshot = build_frontend_snapshot(state)
        exported = snapshot["strategic_formations"][0]
        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertFalse(exported["supplied"])
        self.assertTrue(exported["cut_off"])
        self.assertNotIn("grace_ticks_remaining", exported)
        self.assertNotIn("roster", snapshot["battalions"][0])
        self.assertIn("query_supply", snapshot["control"]["supported_ops"])


class GodotSupplyPresentationContractTests(unittest.TestCase):
    def test_stack_panel_reads_existing_supply_fields_and_query_cache(self) -> None:
        script = (
            ROOT / "godot" / "scripts" / "main_stack_panel.gd"
        ).read_text(encoding="utf-8")
        writeback = (
            ROOT / "godot" / "scripts" / "main_writeback.gd"
        ).read_text(encoding="utf-8")
        measured = (
            ROOT / "godot" / "scripts" / "main_perf_measured.gd"
        ).read_text(encoding="utf-8")
        for token in (
            "_formation_supply_presentation",
            "_supply_presentation_from_query",
            "_supply_presentation_from_snapshot",
            "_maybe_request_supply_query",
            "_capture_supply_query",
            'force.get("supplied"',
            'force.get("cut_off"',
            'force.get("source_hub_id"',
            "Supply:",
            "Readiness:",
            '"query_supply"',
        ):
            self.assertIn(token, script)
        self.assertNotIn("func _process(", script)
        self.assertNotIn("for province", script.lower())
        self.assertIn("var supply_query_cache", writeback)
        self.assertIn('op == "query_supply"', writeback)
        self.assertIn("_try_build_snapshot_state", writeback)
        query_block = writeback.split('if op == "query_supply":', 1)[1].split(
            "\n\t# 3)", 1
        )[0]
        self.assertNotIn("_try_build_snapshot_state", query_block)
        self.assertIn('op == "query_supply"', measured)
        self.assertIn("_capture_supply_query", measured)

    def test_godot_does_not_read_battalion_roster(self) -> None:
        joined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "godot" / "scripts" / "main_stack_panel.gd",
                ROOT / "godot" / "scripts" / "main_writeback.gd",
                ROOT / "godot" / "scripts" / "main_perf_measured.gd",
            )
        )
        self.assertNotIn('battalion.get("roster"', joined)
        self.assertNotIn('snapshot.get("roster"', joined)


if __name__ == "__main__":
    unittest.main()
