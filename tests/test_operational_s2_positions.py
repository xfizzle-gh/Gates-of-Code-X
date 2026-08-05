from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.force_migration import ensure_strategic_formations
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
    ensure_operational_positions,
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


def _minimal_state(*, map_id: str = "custom") -> CampaignState:
    return CampaignState(
        campaign_name="S2 positions",
        map_id=map_id,
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


class OperationalS2PositionTests(unittest.TestCase):
    def test_m1_hydrates_missing_position_to_province_anchor(self) -> None:
        state = _minimal_state()
        ensure_strategic_formations(state)
        force = next(iter(state.strategic_formations.values()))
        self.assertIsNone(force.position)

        report = ensure_operational_positions(state)
        self.assertEqual(OPERATIONAL_POSITION_SCHEMA_VERSION, report["schema_version"])
        self.assertGreaterEqual(state.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION)
        self.assertIsNotNone(force.position)
        assert force.position is not None
        self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
        self.assertEqual(stable_node_id("a", "anchor"), force.position.node_id)
        self.assertEqual(0, force.position.progress_milli)
        self.assertEqual("a", force.province_id)
        state.validate()

    def test_migration_is_idempotent(self) -> None:
        state = _minimal_state()
        ensure_operational_positions(state)
        first = state.to_dict()
        ensure_operational_positions(state)
        second = state.to_dict()
        self.assertEqual(first, second)

    def test_save_load_round_trip_preserves_position(self) -> None:
        state = _minimal_state()
        ensure_operational_positions(state)
        force_id = next(iter(state.strategic_formations))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
        self.assertEqual(
            state.strategic_formations[force_id].position,
            reloaded.strategic_formations[force_id].position,
        )
        self.assertGreaterEqual(reloaded.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION)
        self.assertIn("operational_position_migration", reloaded.map_metadata)

    def test_legacy_dict_without_position_hydrates_on_load(self) -> None:
        state = _minimal_state()
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

    def test_adjacency_move_snaps_position_to_new_province_anchor(self) -> None:
        state = _minimal_state()
        ensure_operational_positions(state)
        engine = CampaignEngine(state)
        engine.move_or_attack("bn-1", "b")
        force = next(iter(state.strategic_formations.values()))
        self.assertEqual("b", force.province_id)
        assert force.position is not None
        self.assertEqual(stable_node_id("b", "anchor"), force.position.node_id)

    def test_frontend_exports_position_and_display_pixel(self) -> None:
        state = _minimal_state()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertEqual(9, snapshot["schema_version"])
        force_row = snapshot["strategic_formations"][0]
        self.assertEqual(PositionMode.AT_NODE.value, force_row["position"]["mode"])
        self.assertEqual(stable_node_id("a", "anchor"), force_row["position"]["node_id"])
        self.assertEqual([10, 20], force_row["display_pixel"])
        bn_row = next(row for row in snapshot["battalions"] if row["id"] == "bn-1")
        self.assertEqual([10, 20], bn_row["display_pixel"])
        stacks = build_stack_presentations(state, [])
        sf = next(iter(stacks["strategic_formations"].values()))
        self.assertEqual(force_row["position"], sf["position"])
        self.assertEqual([10, 20], sf["display_pixel"])

    def test_province_anchor_helper(self) -> None:
        position = province_anchor_position("Wester Ems")
        self.assertEqual("op-node-Wester_Ems-anchor", position.node_id)

    @unittest.skipUnless(EM_GRAPH.is_file(), "EM operational graph missing")
    def test_em_campaign_positions_match_graph_nodes(self) -> None:
        from gates_of_codex.europe_mediterranean_from_goe import (
            build_europe_mediterranean_from_goe_campaign,
        )

        state = build_europe_mediterranean_from_goe_campaign(selected_faction=Faction.NATO)
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
            # Node pixels come from the graph, not necessarily province marker floats.
            self.assertIsInstance(row["display_pixel"][0], int)
            self.assertIsInstance(row["display_pixel"][1], int)

        before = copy.deepcopy(state.to_dict())
        ensure_operational_positions(state)
        self.assertEqual(before, state.to_dict())


if __name__ == "__main__":
    unittest.main()
