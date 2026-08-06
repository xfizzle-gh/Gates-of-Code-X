from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.force_migration import (
    STRATEGIC_FORMATION_SCHEMA_VERSION,
    ensure_strategic_formations,
)
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Formation,
    FormationKind,
    Province,
)
from gates_of_codex.operational_position import (
    OPERATIONAL_POSITION_SCHEMA_VERSION,
    default_asset_search_roots,
    ensure_operational_positions,
    load_operational_graph_payload,
    place_formation_at_province_anchor,
    position_from_dict,
    province_anchor_position,
)
from gates_of_codex.operational_schema import PositionMode, stable_node_id
from gates_of_codex.presentation import build_stack_presentations
from gates_of_codex.state_io import campaign_from_dict, load_campaign, save_campaign


ROOT = Path(__file__).resolve().parents[1]
EM_GRAPH = (
    ROOT
    / "godot/assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
)


def _minimal_state(*, map_id: str = "custom", map_metadata: dict | None = None) -> CampaignState:
    return CampaignState(
        campaign_name="S2 positions",
        map_id=map_id,
        map_metadata=dict(map_metadata or {}),
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=500, is_human_controlled=True)
        },
        formations={
            "toe-nato": Formation(
                formation_id="toe-nato",
                display_name="NATO Template",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            )
        },
        provinces={
            "a": Province("a", "Alpha", owner=Faction.NATO, neighbors=["b"], x=10, y=20),
            "b": Province("b", "Bravo", owner=Faction.NATO, neighbors=["a"], x=30, y=40),
        },
        battalions={
            "bn-1": Battalion(
                battalion_id="bn-1",
                faction=Faction.NATO,
                province_id="a",
                formation_id="toe-nato",
                roster=[BattalionRosterEntry("tank(nato)", 2, category="tank")],
                authorized_roster=[BattalionRosterEntry("tank(nato)", 2, category="tank")],
                is_player_controlled=True,
            )
        },
        schema_version=5,
    )


def _tiny_graph(*, with_sites: bool = False) -> dict:
    nodes = [
        {
            "node_id": stable_node_id("a", "anchor"),
            "display_name": "a anchor",
            "pixel": [11, 21],
            "province_id": "a",
            "site_id": None,
            "kind": "anchor",
            "terrain": "plain",
            "metadata": {},
        },
        {
            "node_id": stable_node_id("b", "anchor"),
            "display_name": "b anchor",
            "pixel": [31, 41],
            "province_id": "b",
            "site_id": None,
            "kind": "anchor",
            "terrain": "plain",
            "metadata": {},
        },
    ]
    sites: list[dict] = []
    if with_sites:
        nodes.append(
            {
                "node_id": "op-node-a-town",
                "display_name": "a town",
                "pixel": [12, 22],
                "province_id": "a",
                "site_id": "op-site-settlement-a-town",
                "kind": "site",
                "terrain": "urban",
                "metadata": {},
            }
        )
        nodes.append(
            {
                "node_id": "op-node-a-depot",
                "display_name": "a depot",
                "pixel": [13, 23],
                "province_id": "a",
                "site_id": "op-site-depot-a-depot",
                "kind": "site",
                "terrain": "plain",
                "metadata": {},
            }
        )
        sites = [
            {
                "site_id": "op-site-settlement-a-town",
                "display_name": "Town",
                "kind": "settlement",
                "province_id": "a",
                "pixel": [12, 22],
                "route_node_id": "op-node-a-town",
                "control_weight_milli": 1000,
                "capture_threshold_milli": 1000,
                "tags": [],
                "facilities": [],
                "owner_faction": None,
                "metadata": {},
            },
            {
                "site_id": "op-site-depot-a-depot",
                "display_name": "Depot",
                "kind": "depot",
                "province_id": "a",
                "pixel": [13, 23],
                "route_node_id": "op-node-a-depot",
                "control_weight_milli": 2500,
                "capture_threshold_milli": 1000,
                "tags": [],
                "facilities": [],
                "owner_faction": None,
                "metadata": {},
            },
        ]
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "test_ops_map",
        "rules": {"ticks_per_strategic_turn": 10},
        "sites": sites,
        "nodes": nodes,
        "edges": [],
        "metadata": {},
    }


class OperationalS2PositionTests(unittest.TestCase):
    def test_unsupported_map_does_not_invent_positions_or_schema7(self) -> None:
        state = _minimal_state(map_id="custom")
        report = ensure_operational_positions(state)
        self.assertTrue(report.get("skipped"))
        self.assertFalse(report.get("graph_loaded"))
        force = next(iter(state.strategic_formations.values()))
        self.assertIsNone(force.position)
        self.assertEqual(STRATEGIC_FORMATION_SCHEMA_VERSION, state.schema_version)
        self.assertNotIn("operational_position_migration", state.map_metadata)

    def test_missing_graph_leaves_existing_positions_unchanged(self) -> None:
        state = _minimal_state(map_id="custom")
        ensure_strategic_formations(state)
        force = next(iter(state.strategic_formations.values()))
        force.position = province_anchor_position("a")
        before = copy.deepcopy(state.to_dict())
        report = ensure_operational_positions(state)
        self.assertTrue(report.get("skipped"))
        self.assertEqual(before, state.to_dict())
        # Movement-sync also must not erase when graph is missing.
        place_formation_at_province_anchor(force, state)
        self.assertEqual(stable_node_id("a", "anchor"), force.position.node_id)
        self.assertEqual(before, state.to_dict())

    def test_m1_hydrates_when_graph_declared_via_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path = root / "ops" / "operational_graph.json"
            graph_path.parent.mkdir(parents=True)
            graph_path.write_text(json.dumps(_tiny_graph()), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            report = ensure_operational_positions(state)
            self.assertFalse(report.get("skipped", False))
            self.assertTrue(report["graph_loaded"])
            force = next(iter(state.strategic_formations.values()))
            self.assertIsNotNone(force.position)
            assert force.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
            self.assertEqual(stable_node_id("a", "anchor"), force.position.node_id)
            self.assertEqual(0, force.position.progress_milli)
            self.assertGreaterEqual(state.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION)
            self.assertIn("operational_position_migration", state.map_metadata)
            state.validate()

    def test_highest_weight_site_uses_control_weight_milli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph_path = root / "graph.json"
            graph_path.write_text(json.dumps(_tiny_graph(with_sites=True)), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            ensure_operational_positions(state)
            force = next(iter(state.strategic_formations.values()))
            assert force.position is not None
            self.assertEqual("op-node-a-depot", force.position.node_id)

    def test_migration_is_idempotent_with_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph_path = Path(temporary) / "graph.json"
            graph_path.write_text(json.dumps(_tiny_graph()), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            ensure_operational_positions(state)
            first = state.to_dict()
            ensure_operational_positions(state)
            second = state.to_dict()
            self.assertEqual(first, second)

    def test_save_load_round_trip_preserves_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph_path = Path(temporary) / "graph.json"
            graph_path.write_text(json.dumps(_tiny_graph()), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            ensure_operational_positions(state)
            force_id = next(iter(state.strategic_formations))
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            self.assertEqual(
                state.strategic_formations[force_id].position,
                reloaded.strategic_formations[force_id].position,
            )
            self.assertGreaterEqual(reloaded.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION)

    def test_legacy_dict_without_position_hydrates_only_with_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph_path = Path(temporary) / "graph.json"
            graph_path.write_text(json.dumps(_tiny_graph()), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            ensure_strategic_formations(state)
            payload = state.to_dict()
            for force in payload["strategic_formations"].values():
                force.pop("position", None)
            payload["schema_version"] = 6
            reloaded = campaign_from_dict(payload)
            force = next(iter(reloaded.strategic_formations.values()))
            self.assertIsNotNone(force.position)
            assert force.position is not None
            self.assertEqual(stable_node_id(force.province_id, "anchor"), force.position.node_id)

        # Without graph path: stay None
        bare = _minimal_state(map_id="custom")
        ensure_strategic_formations(bare)
        bare_payload = bare.to_dict()
        bare_payload["schema_version"] = 6
        bare_reloaded = campaign_from_dict(bare_payload)
        bare_force = next(iter(bare_reloaded.strategic_formations.values()))
        self.assertIsNone(bare_force.position)
        self.assertEqual(STRATEGIC_FORMATION_SCHEMA_VERSION, bare_reloaded.schema_version)

    def test_adjacency_move_snaps_only_when_graph_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph_path = Path(temporary) / "graph.json"
            graph_path.write_text(json.dumps(_tiny_graph()), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            ensure_operational_positions(state)
            engine = CampaignEngine(state)
            engine.move_or_attack("bn-1", "b")
            force = next(iter(state.strategic_formations.values()))
            self.assertEqual("b", force.province_id)
            assert force.position is not None
            self.assertEqual(stable_node_id("b", "anchor"), force.position.node_id)

        bare = _minimal_state(map_id="custom")
        ensure_strategic_formations(bare)
        force = next(iter(bare.strategic_formations.values()))
        force.position = province_anchor_position("a")
        engine = CampaignEngine(bare)
        engine.move_or_attack("bn-1", "b")
        self.assertEqual("b", force.province_id)
        # Graph missing: do not invent a new anchor and do not wipe the save.
        assert force.position is not None
        self.assertEqual(stable_node_id("a", "anchor"), force.position.node_id)

    def test_position_from_dict_rejects_coerced_ints(self) -> None:
        good = position_from_dict(
            {
                "mode": "at_node",
                "node_id": "op-node-a-anchor",
                "progress_milli": 0,
            }
        )
        self.assertEqual(0, good.progress_milli)
        for bad in ("0", 0.0, True, False, 1.5, "500"):
            with self.assertRaises(ValueError):
                position_from_dict(
                    {
                        "mode": "at_node",
                        "node_id": "op-node-a-anchor",
                        "progress_milli": bad,
                    }
                )

    def test_graph_resolves_via_manifest_sibling_outside_repo_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            map_dir = root / "pack" / "maps" / "demo"
            op_dir = map_dir / "operational"
            op_dir.mkdir(parents=True)
            (map_dir / "map_manifest.json").write_text("{}", encoding="utf-8")
            graph = _tiny_graph()
            (op_dir / "operational_graph.json").write_text(json.dumps(graph), encoding="utf-8")
            loaded = load_operational_graph_payload(
                "demo_map",
                map_metadata={
                    "strategic_map_manifest": str((map_dir / "map_manifest.json").resolve())
                },
                search_roots=[root],
            )
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(2, len(loaded["nodes"]))

            # Relative metadata path + search root (installed layout simulation).
            rel_loaded = load_operational_graph_payload(
                "demo_map",
                map_metadata={
                    "strategic_map_manifest": "pack/maps/demo/map_manifest.json",
                },
                search_roots=[root],
            )
            self.assertIsNotNone(rel_loaded)

    def test_default_search_roots_include_executable_and_cwd(self) -> None:
        roots = default_asset_search_roots()
        self.assertIn(Path(sys.executable).resolve().parent, roots)
        self.assertIn(Path.cwd().resolve(), roots)

    def test_automatic_roots_find_graph_when_cwd_is_elsewhere(self) -> None:
        """Production path: search_roots=None must use executable-dir roots, not cwd alone."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Fake Windows/frozen layout: assets beside a fake executable.
            exe_dir = root / "app"
            exe_dir.mkdir()
            fake_exe = exe_dir / "gates-of-codex.exe"
            fake_exe.write_text("", encoding="utf-8")
            op_dir = exe_dir / "godot" / "assets" / "maps" / "auto_root_test" / "operational"
            op_dir.mkdir(parents=True)
            (op_dir / "operational_graph.json").write_text(
                json.dumps(_tiny_graph()), encoding="utf-8"
            )
            foreign_cwd = root / "elsewhere"
            foreign_cwd.mkdir()
            old_cwd = Path.cwd()
            try:
                os.chdir(foreign_cwd)
                with mock.patch.object(sys, "executable", str(fake_exe)):
                    with mock.patch.object(sys, "argv", [str(fake_exe)]):
                        roots = default_asset_search_roots()
                        self.assertIn(exe_dir.resolve(), roots)
                        loaded = load_operational_graph_payload(
                            "auto_root_test",
                            map_metadata={
                                "operational_graph": (
                                    "assets/maps/auto_root_test/operational/"
                                    "operational_graph.json"
                                )
                            },
                            search_roots=None,
                        )
            finally:
                os.chdir(old_cwd)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(2, len(loaded["nodes"]))

    def test_frozen_meipass_root_is_searched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            meipass = root / "_MEIPASS"
            op_dir = meipass / "godot" / "assets" / "maps" / "frozen_test" / "operational"
            op_dir.mkdir(parents=True)
            (op_dir / "operational_graph.json").write_text(
                json.dumps(_tiny_graph()), encoding="utf-8"
            )
            with mock.patch.object(sys, "_MEIPASS", str(meipass), create=True):
                roots = default_asset_search_roots()
                self.assertIn(meipass.resolve(), roots)
                loaded = load_operational_graph_payload(
                    "frozen_test",
                    map_metadata={
                        "operational_graph": (
                            "assets/maps/frozen_test/operational/operational_graph.json"
                        )
                    },
                    search_roots=None,
                )
            self.assertIsNotNone(loaded)

    def test_frontend_exports_position_when_graph_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            graph_path = Path(temporary) / "graph.json"
            graph_path.write_text(json.dumps(_tiny_graph()), encoding="utf-8")
            state = _minimal_state(
                map_id="test_ops_map",
                map_metadata={"operational_graph": str(graph_path.resolve())},
            )
            snapshot = build_frontend_snapshot(state)
            self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
            self.assertEqual(12, snapshot["schema_version"])
            force_row = snapshot["strategic_formations"][0]
            self.assertEqual(PositionMode.AT_NODE.value, force_row["position"]["mode"])
            self.assertEqual(stable_node_id("a", "anchor"), force_row["position"]["node_id"])
            self.assertEqual([11, 21], force_row["display_pixel"])
            bn_row = next(row for row in snapshot["battalions"] if row["id"] == "bn-1")
            self.assertEqual([11, 21], bn_row["display_pixel"])
            stacks = build_stack_presentations(state, [])
            sf = next(iter(stacks["strategic_formations"].values()))
            self.assertEqual(force_row["position"], sf["position"])

    def test_frontend_without_graph_exports_null_position_province_pixel(self) -> None:
        state = _minimal_state(map_id="custom")
        snapshot = build_frontend_snapshot(state)
        force_row = snapshot["strategic_formations"][0]
        self.assertIsNone(force_row["position"])
        self.assertEqual([10, 20], force_row["display_pixel"])

    def test_province_anchor_helper(self) -> None:
        position = province_anchor_position("Wester Ems")
        self.assertEqual("op-node-Wester_Ems-anchor", position.node_id)

    @unittest.skipUnless(EM_GRAPH.is_file(), "EM operational graph missing")
    def test_em_campaign_positions_match_graph_nodes(self) -> None:
        from gates_of_codex.europe_mediterranean_from_goe import (
            build_europe_mediterranean_from_goe_campaign,
        )

        state = build_europe_mediterranean_from_goe_campaign(selected_faction=Faction.NATO)
        self.assertIn("operational_graph", state.map_metadata)
        ensure_operational_positions(state)
        self.assertGreater(len(state.strategic_formations), 0)
        for force in state.strategic_formations.values():
            self.assertIsNotNone(force.position)
            assert force.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
            self.assertEqual(
                stable_node_id(force.province_id, "anchor"),
                force.position.node_id,
            )
        snapshot = build_frontend_snapshot(state)
        for row in snapshot["strategic_formations"]:
            self.assertIsNotNone(row["display_pixel"])
            self.assertEqual(2, len(row["display_pixel"]))
            self.assertIsInstance(row["display_pixel"][0], int)
            self.assertIsInstance(row["display_pixel"][1], int)

        before = copy.deepcopy(state.to_dict())
        ensure_operational_positions(state)
        self.assertEqual(before, state.to_dict())

    @unittest.skipUnless(EM_GRAPH.is_file(), "EM operational graph missing")
    def test_em_graph_resolves_from_copied_tree_not_package_path(self) -> None:
        """Simulate installed/exported layout: graph only under an external root."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dest = root / "godot" / "assets" / "maps" / "europe_mediterranean" / "from_goe"
            dest.mkdir(parents=True)
            shutil.copytree(EM_GRAPH.parent, dest / "operational")
            loaded = load_operational_graph_payload(
                "europe_mediterranean_from_goe",
                map_metadata={
                    "operational_graph": (
                        "assets/maps/europe_mediterranean/from_goe/operational/"
                        "operational_graph.json"
                    )
                },
                search_roots=[root],
            )
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(342, len(loaded["nodes"]))


if __name__ == "__main__":
    unittest.main()
