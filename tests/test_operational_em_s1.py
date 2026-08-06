from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.europe_mediterranean_from_goe import build_europe_mediterranean_from_goe_campaign
from gates_of_codex.models import Faction
from gates_of_codex.operational_em_generate import generate_em_operational_graph
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    EdgeAuthority,
    EdgeKind,
    FormationOperationalPosition,
    FormationStance,
    MoveOrderStatus,
    NodeKind,
    OperationalGraph,
    OperationalMoveOrder,
    OperationalRouteEdge,
    OperationalRouteNode,
    OperationalRules,
    PositionMode,
    require_strict_int,
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
        records: dict[tuple[str, str], dict] = {}
        by_id = {str(row["province_id"]): row for row in manifest["province_table"]}
        defaults = {
            "strait": (1250, False, True, True),
            "ferry": (1500, True, True, True),
            "ferry_or_sea_lane": (1500, True, True, True),
            "sea_lane": (2000, True, True, True),
        }
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
                mult, port, block, bi = defaults[str(etype)]
                if "movement_cost_milli" in meta:
                    cost = int(meta["movement_cost_milli"])
                elif "movement_cost_multiplier" in meta:
                    cost = max(1, int(round(float(meta["movement_cost_multiplier"]) * COST_MILLI_UNITY)))
                else:
                    cost = mult
                records[key] = {
                    "type": str(etype),
                    "movement_cost_milli": cost,
                    "requires_port": bool(meta.get("requires_port", port)),
                    "can_be_blockaded": bool(meta.get("can_be_blockaded", block)),
                    "bidirectional": bool(meta.get("bidirectional", bi)),
                    "traversal_enabled": True,
                }
        return records

    def test_generate_is_deterministic_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "operational"
            first = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)
            second = generate_em_operational_graph(manifest_path=MANIFEST, output_dir=out)
            self.assertEqual(first["graph"], second["graph"])
            graph = first["graph"]
            # validate must not inject private keys into metadata
            self.assertFalse(any(str(k).startswith("_") for k in graph.get("metadata", {})))
            self.assertEqual(2, graph["schema_version"])
            self.assertEqual("europe_mediterranean_from_goe", graph["map_id"])
            self.assertEqual(10, graph["rules"]["ticks_per_strategic_turn"])
            self.assertTrue(graph["rules"]["authored_crossings_traversable_v1"])
            self.assertFalse(graph["rules"]["enforce_port_requirements"])
            self.assertFalse(graph["rules"]["enforce_blockades"])
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
                self.assertIsInstance(x, int)
                self.assertIsInstance(y, int)
                self.assertNotIsInstance(x, bool)
                self.assertEqual(pid, self.color_to_pid.get(self.image.color_at(x, y)))

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
                self.assertIsInstance(edge["length_px"], int)
                self.assertIsInstance(edge["movement_cost_milli"], int)
                self.assertIsInstance(edge["base_move_points_milli"], int)
                self.assertNotIsInstance(edge["movement_cost_milli"], bool)
                if edge["authority"] == EdgeAuthority.AUTHORED.value:
                    authored_edges.append(edge)
                    self.assertTrue(edge["traversal_enabled"])
                    self.assertNotEqual(EdgeKind.CORRIDOR.value, edge["kind"])
                    self.assertIsNotNone(edge.get("legacy_crossing_type"))
                elif edge["authority"] == EdgeAuthority.CANDIDATE.value:
                    candidates += 1
                    self.assertEqual(EdgeKind.CORRIDOR.value, edge["kind"])
                    self.assertFalse(edge["traversal_enabled"])
                    self.assertNotIn(edge["kind"], {EdgeKind.ROAD.value, EdgeKind.RAIL.value})
                else:
                    self.fail(f"unexpected authority {edge['authority']}")
            self.assertGreater(candidates, 100)

            self.assertEqual(EXPECTED_AUTHORED_CROSSINGS, len(self.expected_crossings))
            self.assertEqual(EXPECTED_AUTHORED_CROSSINGS, len(authored_edges))
            got: dict[tuple[str, str], dict] = {}
            for edge in authored_edges:
                a = node_province[edge["a"]]
                b = node_province[edge["b"]]
                key = tuple(sorted((a, b)))
                got[key] = {
                    "type": str(edge["legacy_crossing_type"]),
                    "movement_cost_milli": int(edge["movement_cost_milli"]),
                    "requires_port": bool(edge["requires_port"]),
                    "can_be_blockaded": bool(edge["can_be_blockaded"]),
                    "bidirectional": bool(edge["bidirectional"]),
                    "traversal_enabled": bool(edge["traversal_enabled"]),
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
        self.assertFalse(any(str(k).startswith("_") for k in committed.get("metadata", {})))
        self.assertEqual(
            EXPECTED_AUTHORED_CROSSINGS,
            sum(1 for edge in committed["edges"] if edge["authority"] == "authored"),
        )

    def test_strict_int_helper_rejects_bool_str_float(self) -> None:
        self.assertEqual(3, require_strict_int(3, name="n"))
        for bad in (True, False, "3", 3.0, 1.5, None):
            with self.assertRaises(ValueError):
                require_strict_int(bad, name="n")  # type: ignore[arg-type]

    def test_position_and_order_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph = generate_em_operational_graph(
                manifest_path=MANIFEST, output_dir=Path(temporary) / "operational"
            )["graph"]
        nodes = {node["node_id"] for node in graph["nodes"]}
        edges_by_id = {
            edge["edge_id"]: OperationalRouteEdge(
                edge_id=edge["edge_id"],
                a=edge["a"],
                b=edge["b"],
                kind=edge["kind"],
                authority=edge["authority"],
                length_px=int(edge["length_px"]),
                base_move_points_milli=int(edge["base_move_points_milli"]),
                movement_cost_milli=int(edge["movement_cost_milli"]),
                requires_port=bool(edge["requires_port"]),
                can_be_blockaded=bool(edge["can_be_blockaded"]),
                traversal_enabled=bool(edge["traversal_enabled"]),
                bidirectional=bool(edge["bidirectional"]),
                province_ids=list(edge["province_ids"]),
                legacy_crossing_type=edge.get("legacy_crossing_type"),
                metadata=dict(edge.get("metadata") or {}),
            )
            for edge in graph["edges"]
        }
        edge_ids = set(edges_by_id)
        sample_edge = next(iter(edges_by_id.values()))

        FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=next(iter(nodes)),
            progress_milli=0,
        ).validate(node_ids=nodes, edge_ids=edge_ids, edges_by_id=edges_by_id)

        FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=sample_edge.edge_id,
            progress_milli=500,
            facing_node_id=sample_edge.b,
        ).validate(node_ids=nodes, edge_ids=edge_ids, edges_by_id=edges_by_id)

        with self.assertRaises(ValueError):
            FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=next(iter(nodes)),
                progress_milli=True,  # type: ignore[arg-type]
            ).validate(node_ids=nodes, edge_ids=edge_ids, edges_by_id=edges_by_id)

        with self.assertRaises(ValueError):
            FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=sample_edge.edge_id,
                progress_milli=500,
                facing_node_id="not-an-endpoint",
            ).validate(
                node_ids=nodes | {"not-an-endpoint"},
                edge_ids=edge_ids,
                edges_by_id=edges_by_id,
            )

        # Draft order
        OperationalMoveOrder(
            order_id="ord-1",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            issued_tick=0,
            status=MoveOrderStatus.DRAFT.value,
        ).validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )

        # Committed order requires turn + approved stance ID
        OperationalMoveOrder(
            order_id="ord-2",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            issued_tick=0,
            status=MoveOrderStatus.COMMITTED.value,
            committed_turn=3,
            locked_stance=FormationStance.OPERATIONAL.value,
        ).validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )

        # Active/completed must retain commitment fields
        for status in (
            MoveOrderStatus.ACTIVE.value,
            MoveOrderStatus.COMPLETED.value,
        ):
            OperationalMoveOrder(
                order_id=f"ord-{status}",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                issued_tick=1,
                status=status,
                committed_turn=3,
                locked_stance=FormationStance.FORCED_MARCH.value,
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )
            with self.assertRaises(ValueError):
                OperationalMoveOrder(
                    order_id=f"ord-{status}-missing",
                    formation_id="sf-x",
                    path_node_ids=[sample_edge.a, sample_edge.b],
                    path_edge_ids=[sample_edge.edge_id],
                    status=status,
                ).validate(
                    node_ids=nodes,
                    edge_ids=edge_ids,
                    site_ids=set(),
                    edges_by_id=edges_by_id,
                )

        # Blocked: both commitment fields or neither (like cancelled)
        OperationalMoveOrder(
            order_id="ord-blocked-none",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            status=MoveOrderStatus.BLOCKED.value,
        ).validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )
        OperationalMoveOrder(
            order_id="ord-blocked-both",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            status=MoveOrderStatus.BLOCKED.value,
            committed_turn=2,
            locked_stance=FormationStance.OPERATIONAL.value,
        ).validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )
        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-blocked-half",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                status=MoveOrderStatus.BLOCKED.value,
                committed_turn=2,
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

        # Draft must not carry commitment fields
        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-draft-bad",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                status=MoveOrderStatus.DRAFT.value,
                committed_turn=1,
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

        # Cancelled: neither commitment field (pre-commit cancel)
        OperationalMoveOrder(
            order_id="ord-cancel-none",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            status=MoveOrderStatus.CANCELLED.value,
        ).validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )
        # Cancelled: both commitment fields (post-commit cancel)
        OperationalMoveOrder(
            order_id="ord-cancel-both",
            formation_id="sf-x",
            path_node_ids=[sample_edge.a, sample_edge.b],
            path_edge_ids=[sample_edge.edge_id],
            status=MoveOrderStatus.CANCELLED.value,
            committed_turn=2,
            locked_stance=FormationStance.ENTRENCHED.value,
        ).validate(
            node_ids=nodes,
            edge_ids=edge_ids,
            site_ids=set(),
            edges_by_id=edges_by_id,
        )
        # Cancelled: exactly one field is invalid
        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-cancel-turn-only",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                status=MoveOrderStatus.CANCELLED.value,
                committed_turn=3,
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )
        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-cancel-stance-only",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                status=MoveOrderStatus.CANCELLED.value,
                locked_stance=FormationStance.AMBUSH.value,
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

        # Reject unknown stance text
        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-stance-bad",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                status=MoveOrderStatus.COMMITTED.value,
                committed_turn=1,
                locked_stance="standard",
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-bad-commit",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                status=MoveOrderStatus.COMMITTED.value,
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

        with self.assertRaises(ValueError):
            OperationalMoveOrder(
                order_id="ord-bad-tick",
                formation_id="sf-x",
                path_node_ids=[sample_edge.a, sample_edge.b],
                path_edge_ids=[sample_edge.edge_id],
                issued_tick="0",  # type: ignore[arg-type]
            ).validate(
                node_ids=nodes,
                edge_ids=edge_ids,
                site_ids=set(),
                edges_by_id=edges_by_id,
            )

    def test_validate_does_not_mutate_graph(self) -> None:
        """Compare graph object before and after validate() — no mutation."""
        with tempfile.TemporaryDirectory() as temporary:
            payload = generate_em_operational_graph(
                manifest_path=MANIFEST, output_dir=Path(temporary) / "operational"
            )["graph"]
        graph = OperationalGraph(
            map_id=payload["map_id"],
            schema=payload["schema"],
            schema_version=int(payload["schema_version"]),
            rules=OperationalRules(**payload["rules"]),
            sites=[],
            nodes=[OperationalRouteNode(**node) for node in payload["nodes"]],
            edges=[
                OperationalRouteEdge(
                    edge_id=edge["edge_id"],
                    a=edge["a"],
                    b=edge["b"],
                    kind=edge["kind"],
                    authority=edge["authority"],
                    length_px=int(edge["length_px"]),
                    base_move_points_milli=int(edge["base_move_points_milli"]),
                    movement_cost_milli=int(edge["movement_cost_milli"]),
                    requires_port=bool(edge["requires_port"]),
                    can_be_blockaded=bool(edge["can_be_blockaded"]),
                    traversal_enabled=bool(edge["traversal_enabled"]),
                    bidirectional=bool(edge["bidirectional"]),
                    province_ids=list(edge["province_ids"]),
                    legacy_crossing_type=edge.get("legacy_crossing_type"),
                    metadata=dict(edge.get("metadata") or {}),
                )
                for edge in payload["edges"]
            ],
            metadata=dict(payload.get("metadata") or {}),
        )
        before = graph.to_dict()
        graph.validate(province_ids=self.province_ids)
        after = graph.to_dict()
        self.assertEqual(before, after)
        self.assertNotIn("_validated_edge_ids", after["metadata"])

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
