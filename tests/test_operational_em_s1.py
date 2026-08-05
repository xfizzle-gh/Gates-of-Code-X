from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.europe_mediterranean_from_goe import build_europe_mediterranean_from_goe_campaign
from gates_of_codex.models import Faction
from gates_of_codex.operational_em_generate import generate_em_operational_graph
from gates_of_codex.operational_schema import (
    EdgeAuthority,
    EdgeKind,
    FormationOperationalPosition,
    MoveOrderStatus,
    NodeKind,
    OperationalMoveOrder,
    OperationalRouteEdge,
    PositionMode,
)
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_map import decode_png_rgb


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/map_manifest.json"
ID_MAP = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/province_id_map.png"
COMMITTED = ROOT / "godot/assets/maps/europe_mediterranean/from_goe/operational"
EXPECTED_AUTHORED_CROSSINGS = 20


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
        cls.expected_crossings = cls._expected_authored_crossing_records(cls.manifest)

    @staticmethod
    def _expected_authored_crossing_records(manifest: dict) -> dict[tuple[str, str], dict]:
        """Canonical undirected crossing records from theatre edge_types/edge_meta."""
        records: dict[tuple[str, str], dict] = {}
        by_id = {str(row["province_id"]): row for row in manifest["province_table"]}
        for row in manifest["province_table"]:
            pid = str(row["province_id"])
            edge_types = row.get("edge_types") or {}
            edge_meta = row.get("edge_meta") or {}
            for neighbor, etype in edge_types.items():
                if str(etype) == "land":
                    continue
                nid = str(neighbor)
                if nid not in by_id:
                    continue
                key = tuple(sorted((pid, nid)))
                if key in records:
                    continue
                meta = edge_meta.get(nid) if isinstance(edge_meta.get(nid), dict) else None
                if meta is None:
                    other_meta = (by_id[nid].get("edge_meta") or {}).get(pid)
                    if isinstance(other_meta, dict):
                        meta = other_meta
                meta = dict(meta or {})
                # Defaults mirrored from operational_schema.DEFAULT_CROSSING_META.
                defaults = {
                    "strait": (1.25, False, True, True),
                    "ferry": (1.5, True, True, True),
                    "ferry_or_sea_lane": (1.5, True, True, True),
                    "sea_lane": (2.0, True, True, True),
                }
                mult, port, block, bi = defaults[str(etype)]
                records[key] = {
                    "type": str(etype),
                    "movement_cost_multiplier": float(meta.get("movement_cost_multiplier", mult)),
                    "requires_port": bool(meta.get("requires_port", port)),
                    "can_be_blockaded": bool(meta.get("can_be_blockaded", block)),
                    "bidirectional": bool(meta.get("bidirectional", bi)),
                }
        return records

    def test_generate_is_deterministic_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "operational"
            first = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)
            second = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)
            self.assertEqual(first["graph"], second["graph"])
            graph = first["graph"]
            self.assertEqual("europe_mediterranean_from_goe", graph["map_id"])
            self.assertEqual(10, graph["rules"]["ticks_per_strategic_turn"])
            self.assertEqual(len(self.province_ids), len(graph["nodes"]))
            self.assertEqual(0, len(graph["sites"]))

            node_ids = [node["node_id"] for node in graph["nodes"]]
            self.assertEqual(len(node_ids), len(set(node_ids)))
            edge_ids = [edge["edge_id"] for edge in graph["edges"]]
            self.assertEqual(len(edge_ids), len(set(edge_ids)))

            by_province = {node["province_id"]: node for node in graph["nodes"]}
            for pid in self.province_ids:
                node = by_province[pid]
                self.assertEqual(NodeKind.ANCHOR.value, node["kind"])
                self.assertTrue(node["node_id"].startswith("op-node-"))
                self.assertTrue(node["node_id"].endswith("-anchor"))
                x, y = node["pixel"]
                self.assertEqual(pid, self.color_to_pid.get(self.image.color_at(int(x), int(y))))

            node_id_set = set(node_ids)
            node_province = {node["node_id"]: node["province_id"] for node in graph["nodes"]}
            authored_edges = []
            candidates = 0
            for edge in graph["edges"]:
                self.assertIn(edge["a"], node_id_set)
                self.assertIn(edge["b"], node_id_set)
                self.assertNotEqual(edge["a"], edge["b"])
                self.assertEqual(2, len(set(edge["province_ids"])))
                self.assertEqual(
                    {node_province[edge["a"]], node_province[edge["b"]]},
                    set(edge["province_ids"]),
                )
                if edge["authority"] == EdgeAuthority.AUTHORED.value:
                    authored_edges.append(edge)
                    self.assertNotEqual(EdgeKind.CORRIDOR.value, edge["kind"])
                    self.assertIsNotNone(edge.get("legacy_crossing_type"))
                elif edge["authority"] == EdgeAuthority.CANDIDATE.value:
                    candidates += 1
                    self.assertEqual(EdgeKind.CORRIDOR.value, edge["kind"])
                    self.assertNotIn(edge["kind"], {EdgeKind.ROAD.value, EdgeKind.RAIL.value})
                else:
                    self.fail(f"unexpected authority {edge['authority']}")
            self.assertGreater(candidates, 100)

            # Exact preservation of all current authored crossing records.
            self.assertEqual(EXPECTED_AUTHORED_CROSSINGS, len(self.expected_crossings))
            self.assertEqual(EXPECTED_AUTHORED_CROSSINGS, len(authored_edges))
            got: dict[tuple[str, str], dict] = {}
            for edge in authored_edges:
                a = node_province[edge["a"]]
                b = node_province[edge["b"]]
                key = tuple(sorted((a, b)))
                got[key] = {
                    "type": str(edge["legacy_crossing_type"]),
                    "movement_cost_multiplier": float(edge["movement_cost_multiplier"]),
                    "requires_port": bool(edge["requires_port"]),
                    "can_be_blockaded": bool(edge["can_be_blockaded"]),
                    "bidirectional": bool(edge["bidirectional"]),
                }
            self.assertEqual(self.expected_crossings, got)

    def test_committed_assets_match_generator_and_freeze_342(self) -> None:
        self.assertEqual(342, len(self.province_ids))
        if not (COMMITTED / "operational_graph.json").is_file():
            self.skipTest("committed operational assets missing")
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "operational"
            generated = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)["graph"]
        committed = json.loads((COMMITTED / "operational_graph.json").read_text(encoding="utf-8"))
        self.assertEqual(generated, committed)
        self.assertEqual(342, len(committed["nodes"]))
        self.assertEqual(
            EXPECTED_AUTHORED_CROSSINGS,
            sum(1 for edge in committed["edges"] if edge["authority"] == "authored"),
        )

    def test_position_and_order_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = generate_em_operational_graph(
                manifest_path=MANIFEST, output_dir=Path(temporary) / "operational"
            )["graph"]
        nodes = {node["node_id"] for node in graph["nodes"]}
        edges_by_id = {
            edge["edge_id"]: OperationalRouteEdge(**{
                key: edge[key]
                for key in edge
                if key
                in {
                    "edge_id",
                    "a",
                    "b",
                    "kind",
                    "authority",
                    "length_px",
                    "base_move_points",
                    "movement_cost_multiplier",
                    "requires_port",
                    "can_be_blockaded",
                    "bidirectional",
                    "province_ids",
                    "legacy_crossing_type",
                    "metadata",
                }
            })
            for edge in graph["edges"]
        }
        edge_ids = set(edges_by_id)
        sample_edge = next(iter(edges_by_id.values()))
        # at_node ok
        FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=next(iter(nodes)),
            progress_milli=0,
        ).validate(node_ids=nodes, edge_ids=edge_ids, edges_by_id=edges_by_id)
        # on_edge ok
        FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=sample_edge.edge_id,
            progress_milli=500,
            facing_node_id=sample_edge.b,
        ).validate(node_ids=nodes, edge_ids=edge_ids, edges_by_id=edges_by_id)
        with self.assertRaises(ValueError):
            FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=sample_edge.edge_id,
                progress_milli=500,
                facing_node_id="not-an-endpoint",
            ).validate(node_ids=nodes | {"not-an-endpoint"}, edge_ids=edge_ids, edges_by_id=edges_by_id)
        # order path continuity
        order = OperationalMoveOrder(
            order_id="ord-1",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            issued_tick=0,
            status=MoveOrderStatus.PENDING.value,
        )
        order.validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )
        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-bad",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.a],
                path_edge_ids=[sample_edge.edge_id],
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

    def test_old_saves_and_movement_unchanged_by_s1_data(self) -> None:
        state = build_europe_mediterranean_from_goe_campaign(selected_faction=Faction.NATO)
        before = {pid: list(p.neighbors) for pid, p in state.provinces.items()}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
        after = {pid: list(p.neighbors) for pid, p in reloaded.provinces.items()}
        self.assertEqual(before, after)
        original = MANIFEST.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            generate_em_operational_graph(
                manifest_path=MANIFEST, output_dir=Path(temporary) / "operational"
            )
        self.assertEqual(original, MANIFEST.read_bytes())


if __name__ == "__main__":
    unittest.main()
