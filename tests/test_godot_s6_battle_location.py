from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GODOT = ROOT / "godot"
GRAPH = (
    GODOT
    / "assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
)


def floor_div(numerator: int, denominator: int) -> int:
    """Python // with positive denominator."""
    return numerator // denominator


def edge_lerp(ax: int, ay: int, bx: int, by: int, progress: int) -> list[int]:
    progress = int(progress)
    x = ax + floor_div((bx - ax) * progress, 1000)
    y = ay + floor_div((by - ay) * progress, 1000)
    return [x, y]


class S6BattleLocationContractTests(unittest.TestCase):
    """Source/contract checks; runtime truth is battle_location_test.gd in Godot CI."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = json.loads(GRAPH.read_text(encoding="utf-8"))
        cls.nodes = {n["node_id"]: n for n in cls.graph["nodes"]}
        cls.edges = {e["edge_id"]: e for e in cls.graph["edges"]}
        cls.sample_edge_id = (
            "op-edge-corridor-op-node-Baden-anchor__op-node-Franken-anchor"
        )
        cls.sample_edge = cls.edges[cls.sample_edge_id]
        cls.a = cls.nodes[cls.sample_edge["a"]]["pixel"]
        cls.b = cls.nodes[cls.sample_edge["b"]]["pixel"]

    def test_gdscript_has_floor_div_and_strict_contract(self) -> None:
        src = (GODOT / "scripts/presentation/battle_location.gd").read_text(encoding="utf-8")
        self.assertIn("func floor_div", src)
        self.assertIn("_parse_strict_pixel", src)
        self.assertIn("_parse_strict_progress_milli", src)
        self.assertIn("TYPE_INT", src)
        self.assertIn("arr.size() != 2", src)
        self.assertNotIn("clampi(int(progress_raw)", src)
        self.assertIn("floor_div((bx - ax) * progress", src)

    def test_python_authority_baden_franken_250(self) -> None:
        got = edge_lerp(319, 512, 343, 483, 250)
        self.assertEqual(got, [325, 504])

    def test_python_authority_negative_deltas(self) -> None:
        self.assertEqual(edge_lerp(100, 100, 50, 20, 0), [100, 100])
        self.assertEqual(edge_lerp(100, 100, 50, 20, 250), [87, 80])
        self.assertEqual(edge_lerp(100, 100, 50, 20, 500), [75, 60])
        self.assertEqual(edge_lerp(100, 100, 50, 20, 1000), [50, 20])

    def test_python_authority_endpoints(self) -> None:
        self.assertEqual(edge_lerp(319, 512, 343, 483, 0), [319, 512])
        self.assertEqual(edge_lerp(319, 512, 343, 483, 500), [331, 497])
        self.assertEqual(edge_lerp(319, 512, 343, 483, 1000), [343, 483])

    def test_godot_runtime_test_script_exists_and_covers_cases(self) -> None:
        src = (GODOT / "scripts/tools/battle_location_test.gd").read_text(encoding="utf-8")
        required = [
            "BattleLocationScript.resolve_pending_battle_location",
            "Baden→Franken@250",
            "neg-delta@250",
            "progress0",
            "progress500",
            "progress1000",
            "pixel authority",
            "malformed pixel",
            "bad progress",
            "node_contact",
            "node_simultaneous",
            "legacy mode",
            "unknown manifest no silent EM graph",
            "floor_div negative floor",
            "repo-root godot/ prefix maps to res://assets",
            "wrong res://godot/ conversion fails closed",
            "Earth3 rejects existing EM candidate",
        ]
        for token in required:
            self.assertIn(token, src)

    def test_workflow_runs_battle_location_test_and_s6_shots(self) -> None:
        workflow = (ROOT / ".github/workflows/gates-of-codex.yml").read_text(encoding="utf-8")
        self.assertIn("battle_location_test.gd", workflow)
        for name in [
            "s6_node_contact_1080p.png",
            "s6_node_simultaneous_1080p.png",
            "s6_edge_cross_1080p.png",
            "s6_edge_catchup_1080p.png",
            "s6_legacy_midpoint_1080p.png",
        ]:
            self.assertIn(name, workflow)

    def test_graph_view_no_silent_earth3_fallback(self) -> None:
        src = (GODOT / "scripts/presentation/operational_graph_view.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("_is_known_em_or_interim_manifest", src)
        self.assertIn("resolve_path", src)
        self.assertIn("return \"\"", src)
        runtime = (GODOT / "scripts/tools/battle_location_test.gd").read_text(encoding="utf-8")
        self.assertIn("earth3_europe_mediterranean", runtime)
        self.assertIn("unknown manifest no silent EM graph", runtime)

    def test_presentation_fixtures_cover_s6_kinds(self) -> None:
        fixture_dir = GODOT / "fixtures/presentation"
        required = [
            "s6_node_contact.json",
            "s6_node_simultaneous.json",
            "s6_edge_cross.json",
            "s6_edge_catchup.json",
            "s6_legacy_midpoint.json",
        ]
        for name in required:
            path = fixture_dir / name
            self.assertTrue(path.is_file(), msg=name)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("pending_battle", data)

    def test_fixture_snapshot_is_schema_12(self) -> None:
        snap = json.loads(
            (GODOT / "fixtures/snapshots/em_theatre_profile.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snap.get("schema_version"), 12)

    def test_main_uses_battle_location_helper(self) -> None:
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("BattleLocationScript", main)
        self.assertIn("resolve_pending_battle_location", main)
        self.assertIn("resolve_path", main)


if __name__ == "__main__":
    unittest.main()
