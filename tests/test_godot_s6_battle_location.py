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


def _edge_lerp(ax: int, ay: int, bx: int, by: int, progress: int) -> list[int]:
    progress = max(0, min(1000, int(progress)))
    x = ax + (bx - ax) * progress // 1000
    y = ay + (by - ay) * progress // 1000
    return [x, y]


def _resolve(battle: dict, graph: dict, legacy_origin=None, legacy_target=None) -> dict:
    """Pure-Python mirror of BattleLocation.resolve_pending_battle_location priority."""
    nodes = {n["node_id"]: n for n in graph.get("nodes", [])}
    edges = {e["edge_id"]: e for e in graph.get("edges", [])}
    kind = str(battle.get("encounter_kind") or "")

    pixel = battle.get("encounter_pixel")
    if isinstance(pixel, list) and len(pixel) >= 2:
        try:
            return {
                "ok": True,
                "mode": "encounter_pixel",
                "map_pixel": [float(pixel[0]), float(pixel[1])],
                "draw_origin_target_line": False,
                "encounter_kind": kind,
            }
        except (TypeError, ValueError):
            pass

    edge_id = str(battle.get("encounter_edge_id") or "").strip()
    if edge_id and "encounter_progress_milli" in battle and battle["encounter_progress_milli"] is not None:
        edge = edges.get(edge_id)
        if edge is not None:
            a = nodes.get(str(edge["a"]), {})
            b = nodes.get(str(edge["b"]), {})
            ap = a.get("pixel")
            bp = b.get("pixel")
            if isinstance(ap, list) and isinstance(bp, list) and len(ap) >= 2 and len(bp) >= 2:
                progress = int(battle["encounter_progress_milli"])
                progress = max(0, min(1000, progress))
                return {
                    "ok": True,
                    "mode": "edge_progress",
                    "map_pixel": _edge_lerp(int(ap[0]), int(ap[1]), int(bp[0]), int(bp[1]), progress),
                    "draw_origin_target_line": False,
                    "encounter_kind": kind,
                    "a": edge["a"],
                    "b": edge["b"],
                }

    node_id = str(battle.get("encounter_node_id") or "").strip()
    if node_id:
        node = nodes.get(node_id, {})
        npx = node.get("pixel")
        if isinstance(npx, list) and len(npx) >= 2:
            return {
                "ok": True,
                "mode": "node",
                "map_pixel": [float(npx[0]), float(npx[1])],
                "draw_origin_target_line": False,
                "encounter_kind": kind,
            }

    if legacy_origin is not None and legacy_target is not None:
        return {
            "ok": True,
            "mode": "legacy_midpoint",
            "map_pixel": [
                (legacy_origin[0] + legacy_target[0]) / 2.0,
                (legacy_origin[1] + legacy_target[1]) / 2.0,
            ],
            "draw_origin_target_line": True,
            "encounter_kind": kind,
        }
    return {"ok": False, "mode": "none", "draw_origin_target_line": False}


class S6BattleLocationTests(unittest.TestCase):
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

    def test_gdscript_helper_priority_order(self) -> None:
        src = (GODOT / "scripts/presentation/battle_location.gd").read_text(encoding="utf-8")
        self.assertIn("encounter_pixel", src)
        self.assertIn("encounter_edge_id", src)
        self.assertIn("encounter_progress_milli", src)
        self.assertIn("encounter_node_id", src)
        self.assertIn("legacy_midpoint", src)
        # Priority: pixel block before edge before node before legacy.
        self.assertLess(src.index("encounter_pixel"), src.index("encounter_edge_id"))
        self.assertLess(src.index("encounter_edge_id"), src.index("encounter_node_id"))
        self.assertLess(src.index("encounter_node_id"), src.index("legacy_midpoint"))
        self.assertIn("edge_lerp_pixel", src)
        self.assertIn("PROGRESS_MILLI_MAX", src)

    def test_main_uses_battle_location_helper(self) -> None:
        main = (GODOT / "scripts/main_color_id.gd").read_text(encoding="utf-8")
        self.assertIn("BattleLocationScript", main)
        self.assertIn("resolve_pending_battle_location", main)
        self.assertIn("operational_graph", main)
        self.assertIn("draw_origin_target_line", main)

    def test_encounter_pixel_authority(self) -> None:
        battle = {
            "encounter_kind": "edge_cross",
            "encounter_pixel": [111, 222],
            "encounter_edge_id": self.sample_edge_id,
            "encounter_progress_milli": 0,
            "encounter_node_id": "op-node-Baden-anchor",
        }
        resolved = _resolve(battle, self.graph)
        self.assertTrue(resolved["ok"])
        self.assertEqual(resolved["mode"], "encounter_pixel")
        self.assertEqual(resolved["map_pixel"], [111.0, 222.0])
        self.assertFalse(resolved["draw_origin_target_line"])

    def test_edge_progress_fallback_and_exact_values(self) -> None:
        for progress, expected in [
            (0, self.a),
            (500, _edge_lerp(self.a[0], self.a[1], self.b[0], self.b[1], 500)),
            (1000, self.b),
        ]:
            battle = {
                "encounter_kind": "edge_cross",
                "encounter_pixel": [],
                "encounter_edge_id": self.sample_edge_id,
                "encounter_progress_milli": progress,
                "encounter_node_id": "",
            }
            resolved = _resolve(battle, self.graph)
            self.assertTrue(resolved["ok"], msg=progress)
            self.assertEqual(resolved["mode"], "edge_progress")
            self.assertEqual(resolved["map_pixel"], list(map(int, expected)))
            self.assertFalse(resolved["draw_origin_target_line"])

    def test_reversed_edge_endpoint_ordering_uses_graph_a_to_b(self) -> None:
        # Progress is always along graph a→b, not presentation-flipped.
        battle = {
            "encounter_kind": "edge_catchup",
            "encounter_pixel": [],
            "encounter_edge_id": self.sample_edge_id,
            "encounter_progress_milli": 250,
        }
        resolved = _resolve(battle, self.graph)
        expected = _edge_lerp(self.a[0], self.a[1], self.b[0], self.b[1], 250)
        reversed_expected = _edge_lerp(self.b[0], self.b[1], self.a[0], self.a[1], 250)
        self.assertEqual(resolved["map_pixel"], expected)
        self.assertNotEqual(resolved["map_pixel"], reversed_expected)
        self.assertEqual(resolved["a"], self.sample_edge["a"])
        self.assertEqual(resolved["b"], self.sample_edge["b"])

    def test_node_contact_location(self) -> None:
        battle = {
            "encounter_kind": "node_contact",
            "encounter_pixel": [],
            "encounter_edge_id": "",
            "encounter_progress_milli": None,
            "encounter_node_id": "op-node-Baden-anchor",
        }
        resolved = _resolve(battle, self.graph)
        self.assertEqual(resolved["mode"], "node")
        self.assertEqual(resolved["map_pixel"], [319.0, 512.0])
        self.assertFalse(resolved["draw_origin_target_line"])

    def test_node_simultaneous_location(self) -> None:
        node_id = "op-node-Hannover-anchor"
        self.assertIn(node_id, self.nodes)
        battle = {
            "encounter_kind": "node_simultaneous",
            "encounter_node_id": node_id,
            "encounter_pixel": [],
        }
        resolved = _resolve(battle, self.graph)
        self.assertEqual(resolved["mode"], "node")
        self.assertEqual(resolved["map_pixel"], list(map(float, self.nodes[node_id]["pixel"])))

    def test_malformed_or_missing_fields(self) -> None:
        cases = [
            {"encounter_pixel": [1]},  # too short
            {"encounter_pixel": ["x", "y"]},  # non-numeric
            {"encounter_edge_id": "missing-edge", "encounter_progress_milli": 500},
            {"encounter_edge_id": self.sample_edge_id},  # progress missing
            {"encounter_node_id": "missing-node"},
            {},
        ]
        for battle in cases:
            resolved = _resolve(battle, self.graph)
            self.assertFalse(resolved["ok"], msg=battle)

    def test_legacy_midpoint_fallback(self) -> None:
        battle = {
            "encounter_kind": "",
            "origin_province_id": "Warszawa",
            "target_province_id": "Bialystok",
            "encounter_pixel": [],
            "encounter_edge_id": "",
            "encounter_node_id": "",
        }
        resolved = _resolve(battle, self.graph, legacy_origin=[0, 0], legacy_target=[10, 20])
        self.assertEqual(resolved["mode"], "legacy_midpoint")
        self.assertEqual(resolved["map_pixel"], [5.0, 10.0])
        self.assertTrue(resolved["draw_origin_target_line"])

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
            self.assertEqual(data["schema"], "gates-of-codex.presentation-fixture")
            self.assertIn("pending_battle", data)
            battle = data["pending_battle"]
            resolved = _resolve(battle, self.graph, legacy_origin=[100, 100], legacy_target=[200, 300])
            self.assertTrue(resolved["ok"], msg=name)

    def test_fixture_snapshot_is_schema_12(self) -> None:
        snap = json.loads(
            (GODOT / "fixtures/snapshots/em_theatre_profile.json").read_text(encoding="utf-8")
        )
        self.assertEqual(snap.get("schema_version"), 12)


if __name__ == "__main__":
    unittest.main()
