from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.operational_em_generate import generate_em_operational_graph
from gates_of_codex.operational_schema import EdgeAuthority, EdgeKind, NodeKind
from gates_of_codex.strategic_map import decode_png_rgb
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.europe_mediterranean_from_goe import build_europe_mediterranean_from_goe_campaign
from gates_of_codex.models import Faction


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/map_manifest.json"
ID_MAP = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/province_id_map.png"
COMMITTED = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/operational"


@unittest.skipUnless(MANIFEST.is_file() and ID_MAP.is_file(), "EM theatre assets missing")
class OperationalEmS1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.province_ids = {str(row["province_id"]) for row in cls.manifest["province_table"]}
        cls.image = decode_png_rgb(ID_MAP)
        cls.color_to_pid = {
            tuple(int(c) for c in row["rgb"]): str(row["province_id"])
            for row in cls.manifest["province_table"]
        }

    def test_generate_is_deterministic_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "operational"
            first = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)
            second = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)
            self.assertEqual(first["graph"], second["graph"])
            graph = first["graph"]
            self.assertEqual("europe_mediterranean_from_goe", graph["map_id"])
            self.assertEqual(10, graph["rules"]["ticks_per_strategic_turn"])
            self.assertEqual(342, len(self.province_ids))
            self.assertEqual(len(self.province_ids), len(graph["nodes"]))
            self.assertEqual(0, len(graph["sites"]))

            node_ids = [node["node_id"] for node in graph["nodes"]]
            self.assertEqual(len(node_ids), len(set(node_ids)))
            edge_ids = [edge["edge_id"] for edge in graph["edges"]]
            self.assertEqual(len(edge_ids), len(set(edge_ids)))

            # Every playable province has one migration anchor node inside province.
            by_province = {node["province_id"]: node for node in graph["nodes"]}
            for pid in self.province_ids:
                node = by_province[pid]
                self.assertEqual(NodeKind.ANCHOR.value, node["kind"])
                self.assertTrue(node["node_id"].startswith("op-node-"))
                self.assertTrue(node["node_id"].endswith("-anchor"))
                x, y = node["pixel"]
                self.assertEqual(pid, self.color_to_pid.get(self.image.color_at(int(x), int(y))))

            # Edge refs valid; authority split correct.
            node_id_set = set(node_ids)
            authored = 0
            candidates = 0
            for edge in graph["edges"]:
                self.assertIn(edge["a"], node_id_set)
                self.assertIn(edge["b"], node_id_set)
                self.assertNotEqual(edge["a"], edge["b"])
                if edge["authority"] == EdgeAuthority.AUTHORED.value:
                    authored += 1
                    self.assertIn(
                        edge["kind"],
                        {
                            EdgeKind.STRAIT.value,
                            EdgeKind.FERRY.value,
                            EdgeKind.FERRY_OR_SEA_LANE.value,
                            EdgeKind.SEA_LANE.value,
                        },
                    )
                    self.assertIsNotNone(edge.get("legacy_crossing_type"))
                elif edge["authority"] == EdgeAuthority.CANDIDATE.value:
                    candidates += 1
                    self.assertEqual(EdgeKind.CORRIDOR.value, edge["kind"])
                else:
                    self.fail(f"unexpected authority {edge['authority']}")
            self.assertGreaterEqual(authored, 10)
            self.assertGreater(candidates, 100)

            # All current authored non-land crossings survive with exact type.
            expected_crossings: set[tuple[str, str, str]] = set()
            for row in self.manifest["province_table"]:
                pid = str(row["province_id"])
                for neighbor, etype in (row.get("edge_types") or {}).items():
                    if str(etype) == "land":
                        continue
                    nid = str(neighbor)
                    if nid not in self.province_ids:
                        continue
                    expected_crossings.add((*sorted((pid, nid)), str(etype)))
            got_crossings = set()
            for edge in graph["edges"]:
                if edge["authority"] != EdgeAuthority.AUTHORED.value:
                    continue
                # map node ids back to province ids
                a_pid = edge["a"].removeprefix("op-node-").removesuffix("-anchor").replace("_", " ")
                # node ids use underscores for spaces in province ids - recover via node table
            node_province = {node["node_id"]: node["province_id"] for node in graph["nodes"]}
            for edge in graph["edges"]:
                if edge["authority"] != EdgeAuthority.AUTHORED.value:
                    continue
                a = node_province[edge["a"]]
                b = node_province[edge["b"]]
                got_crossings.add((*sorted((a, b)), str(edge["legacy_crossing_type"])))
            self.assertTrue(expected_crossings.issubset(got_crossings))

            # Land adjacency never exported as road.
            for edge in graph["edges"]:
                if edge["authority"] == EdgeAuthority.CANDIDATE.value:
                    self.assertNotEqual(EdgeKind.ROAD.value, edge["kind"])

    def test_committed_assets_match_generator(self) -> None:
        if not (COMMITTED / "operational_graph.json").is_file():
            self.skipTest("committed operational assets missing")
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "operational"
            generated = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)["graph"]
        committed = json.loads((COMMITTED / "operational_graph.json").read_text(encoding="utf-8"))
        self.assertEqual(generated, committed)

    def test_old_saves_and_movement_unchanged_by_s1_data(self) -> None:
        # S1 assets must not alter campaign load or adjacency movement.
        state = build_europe_mediterranean_from_goe_campaign(selected_faction=Faction.NATO)
        before = {pid: list(p.neighbors) for pid, p in state.provinces.items()}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
        after = {pid: list(p.neighbors) for pid, p in reloaded.provinces.items()}
        self.assertEqual(before, after)
        # Ensure generating operational graph does not mutate theatre manifest.
        original = MANIFEST.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            generate_em_operational_graph(
                manifest_path=MANIFEST, output_dir=Path(temporary) / "operational"
            )
        self.assertEqual(original, MANIFEST.read_bytes())


if __name__ == "__main__":
    unittest.main()
