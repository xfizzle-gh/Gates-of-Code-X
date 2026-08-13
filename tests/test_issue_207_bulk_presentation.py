from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex import command_cycle_perf


class BulkPresentationProjectionTests(unittest.TestCase):
    def test_bulk_projection_authenticates_graph_once_for_all_formations(self) -> None:
        forces = {
            "sf-a": SimpleNamespace(
                strategic_formation_id="sf-a",
                position=SimpleNamespace(),
                province_id="p-a",
                move_order=None,
            ),
            "sf-b": SimpleNamespace(
                strategic_formation_id="sf-b",
                position=SimpleNamespace(),
                province_id="p-b",
                move_order=None,
            ),
        }
        state = SimpleNamespace(
            strategic_formations=forces,
            provinces={
                "p-a": SimpleNamespace(x=10.0, y=20.0),
                "p-b": SimpleNamespace(x=30.0, y=40.0),
            },
        )
        graph = {"nodes": [], "edges": []}
        calls = {"graph": 0, "pixel": 0}

        def fake_graph(_state):
            calls["graph"] += 1
            return graph

        def fake_pixel(_position, received_graph):
            self.assertIs(graph, received_graph)
            calls["pixel"] += 1
            return [calls["pixel"], calls["pixel"]]

        with (
            patch(
                "gates_of_codex.operational_position.load_operational_graph_for_state",
                side_effect=fake_graph,
            ),
            patch(
                "gates_of_codex.operational_position._pixel_from_position",
                side_effect=fake_pixel,
            ),
            patch(
                "gates_of_codex.operational_position.position_to_dict",
                return_value={"mode": "at_node"},
            ),
            patch(
                "gates_of_codex.operational_movement.move_order_to_dict",
                return_value=None,
            ),
        ):
            rows = command_cycle_perf._bulk_formation_presentation_rows(state)

        self.assertEqual(1, calls["graph"])
        self.assertEqual(2, calls["pixel"])
        self.assertEqual([1, 1], rows["sf-a"]["pixel"])
        self.assertEqual([2, 2], rows["sf-b"]["pixel"])

    def test_bulk_projection_keeps_province_fallback_when_graph_pixel_missing(self) -> None:
        force = SimpleNamespace(
            strategic_formation_id="sf-a",
            position=SimpleNamespace(),
            province_id="p-a",
            move_order=None,
        )
        state = SimpleNamespace(
            strategic_formations={"sf-a": force},
            provinces={"p-a": SimpleNamespace(x=10.4, y=20.6)},
        )

        with (
            patch(
                "gates_of_codex.operational_position.load_operational_graph_for_state",
                return_value={"nodes": [], "edges": []},
            ),
            patch(
                "gates_of_codex.operational_position._pixel_from_position",
                return_value=None,
            ),
            patch(
                "gates_of_codex.operational_position.position_to_dict",
                return_value={"mode": "at_node"},
            ),
            patch(
                "gates_of_codex.operational_movement.move_order_to_dict",
                return_value=None,
            ),
        ):
            rows = command_cycle_perf._bulk_formation_presentation_rows(state)

        self.assertEqual([10, 21], rows["sf-a"]["pixel"])

    def test_measured_wrapper_installs_and_restores_bulk_projection(self) -> None:
        from gates_of_codex import frontend_commands

        original = frontend_commands._formation_presentation_rows
        source = command_cycle_perf.measured_apply_frontend_commands.__code__.co_names

        self.assertIn("_formation_presentation_rows", source)
        self.assertIs(frontend_commands._formation_presentation_rows, original)


if __name__ == "__main__":
    unittest.main()
