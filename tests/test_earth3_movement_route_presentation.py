from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from test_p2_earth3_campaign_bootstrap import _resolved_catalog

from gates_of_codex.earth3_bootstrap import build_earth3_v1_campaign
from gates_of_codex.earth3_operational import P3_GRAPH_RELATIVE_PATH
from gates_of_codex.frontend import (
    _earth3_operational_graph_presentation_path,
    _godot_res_path_from_repo_relative,
    build_frontend_snapshot,
)
from gates_of_codex.scenario import build_scenario


GODOT = ROOT / "godot"
P3_GRAPH = (
    ROOT
    / "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json"
)
P3_GRAPH_RES = (
    "res://assets/maps/earth3_europe_mediterranean/p3_authority/"
    "p3_operational_graph.json"
)
NATIVE_NODES = (
    "op-node-e3_0442-anchor",
    "op-node-e3_0456-anchor",
    "op-node-e3_0455-anchor",
)
NATIVE_EDGES = (
    "op-edge-corridor-op-node-e3_0442-anchor__op-node-e3_0456-anchor",
    "op-edge-corridor-op-node-e3_0455-anchor__op-node-e3_0456-anchor",
)
MAP_TEST = GODOT / "scripts/tools/map_order_controls_test.gd"
GRAPH_VIEW = GODOT / "scripts/presentation/operational_graph_view.gd"


class Earth3MovementRoutePresentationTests(unittest.TestCase):
    def test_repo_relative_converter_only_accepts_godot_assets(self) -> None:
        self.assertEqual(P3_GRAPH_RES, _godot_res_path_from_repo_relative(P3_GRAPH_RELATIVE_PATH))
        self.assertEqual(
            P3_GRAPH_RES,
            _godot_res_path_from_repo_relative(P3_GRAPH_RELATIVE_PATH.replace("/", "\\")),
        )
        self.assertEqual(
            "res://assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json",
            _godot_res_path_from_repo_relative(
                "assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
            ),
        )
        self.assertEqual("", _godot_res_path_from_repo_relative("../p3_authority/p3_operational_graph.json"))
        self.assertEqual("", _godot_res_path_from_repo_relative("docs/audits/p3-first-corridor-route-inventory.json"))
        self.assertEqual(
            "",
            _godot_res_path_from_repo_relative(
                "res://godot/assets/maps/earth3_europe_mediterranean/p3_authority/"
                "p3_operational_graph.json"
            ),
        )

    def test_production_snapshot_identifies_authenticated_p3_graph(self) -> None:
        state = build_scenario("earth3_v1", resolved_catalog=_resolved_catalog())
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(P3_GRAPH_RELATIVE_PATH, snapshot["campaign"]["map_metadata"]["operational_graph"])
        self.assertEqual(P3_GRAPH_RES, snapshot["strategic_map"]["operational_graph_path"])
        self.assertEqual("none", snapshot["strategic_map"]["fallback"])
        self.assertEqual(
            P3_GRAPH_RES,
            _earth3_operational_graph_presentation_path(state),
        )

    def test_p2_only_campaign_does_not_publish_a_graph_path(self) -> None:
        state = build_earth3_v1_campaign(resolved_catalog=_resolved_catalog())
        snapshot = build_frontend_snapshot(state)
        self.assertIn(state.map_metadata.get("operational_graph"), (None, ""))
        self.assertNotIn("operational_graph_path", snapshot["strategic_map"])

    def test_authenticated_p3_graph_contains_native_reproduction_ids(self) -> None:
        graph = json.loads(P3_GRAPH.read_text(encoding="utf-8"))
        node_ids = {str(row["node_id"]) for row in graph["nodes"]}
        edge_ids = {str(row["edge_id"]) for row in graph["edges"]}
        self.assertTrue(NATIVE_NODES[0] in node_ids)
        self.assertTrue(set(NATIVE_NODES) <= node_ids)
        self.assertTrue(set(NATIVE_EDGES) <= edge_ids)
        self.assertNotIn("node-a", node_ids)
        self.assertEqual(P3_GRAPH_RELATIVE_PATH, "godot/assets/maps/earth3_europe_mediterranean/p3_authority/p3_operational_graph.json")

    def test_order_controls_test_crosses_production_graph_loader(self) -> None:
        source = MAP_TEST.read_text(encoding="utf-8")
        self.assertIn("_test_production_p3_graph_loads_and_renders_native_route", source)
        self.assertIn("scene._open_operational_graph()", source)
        self.assertIn(P3_GRAPH_RES, source)
        self.assertIn(P3_GRAPH_RELATIVE_PATH, source)
        for token in NATIVE_NODES + NATIVE_EDGES:
            self.assertIn(token, source)
        production = source[
            source.index("func _production_scene") : source.index("func _test_source_locks_mouse_split")
        ]
        self.assertNotIn("is_ready = true", production)
        self.assertNotIn('"node-a":', production)
        self.assertIn("scene._open_operational_graph()", production)
        view = GRAPH_VIEW.read_text(encoding="utf-8")
        self.assertIn("func presentation_res_path", view)
        self.assertIn('normalized.begins_with("godot/")', view)


if __name__ == "__main__":
    unittest.main()
