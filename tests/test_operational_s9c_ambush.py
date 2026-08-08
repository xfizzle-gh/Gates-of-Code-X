from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    ForceEchelon,
    Formation,
    FormationKind,
    Province,
    StrategicFormation,
)
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_ambush import refresh_ambush_readiness
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    FormationOperationalPosition,
    FormationStance,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


def _node(province_id: str, *, pixel: list[int]) -> dict:
    return {
        "node_id": stable_node_id(province_id),
        "display_name": province_id,
        "pixel": pixel,
        "province_id": province_id,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _edge(a: str, b: str) -> dict:
    node_a, node_b = stable_node_id(a), stable_node_id(b)
    return {
        "edge_id": stable_edge_id("corridor", node_a, node_b),
        "a": node_a,
        "b": node_b,
        "kind": "corridor",
        "authority": "authored",
        "length_px": 100,
        "base_move_points_milli": COST_MILLI_UNITY,
        "movement_cost_milli": 2000,
        "requires_port": False,
        "can_be_blockaded": False,
        "traversal_enabled": True,
        "bidirectional": True,
        "province_ids": [a, b],
        "legacy_crossing_type": None,
        "metadata": {},
    }


def _formation(
    formation_id: str,
    battalion_id: str,
    faction: Faction,
    province_id: str,
) -> StrategicFormation:
    return StrategicFormation(
        strategic_formation_id=formation_id,
        display_name=formation_id,
        faction=faction,
        province_id=province_id,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=[battalion_id],
        template_formation_id=(
            "toe-nato" if faction == Faction.NATO else "toe-russia"
        ),
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province_id),
            progress_milli=0,
        ),
    )


def _battalion(
    battalion_id: str,
    formation_id: str,
    faction: Faction,
    province_id: str,
) -> Battalion:
    return Battalion(
        battalion_id=battalion_id,
        faction=faction,
        province_id=province_id,
        formation_id="toe-nato" if faction == Faction.NATO else "toe-russia",
        roster=[BattalionRosterEntry("tank", 1, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank", 1, category="tank")],
        strategic_formation_id=formation_id,
    )


def _state(root: Path) -> CampaignState:
    graph = {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s9c_test",
        "rules": {"ticks_per_strategic_turn": 10, "capture_hold_ticks": 2},
        "sites": [],
        "nodes": [_node("a", pixel=[0, 0]), _node("b", pixel=[1000, 0])],
        "edges": [_edge("a", "b")],
        "metadata": {},
    }
    graph_path = root / "operational_graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    return CampaignState(
        campaign_name="S9C",
        map_id="s9c_test",
        map_metadata={
            "operational_graph": str(graph_path.resolve()),
            "operational_maneuver_enabled": True,
        },
        factions={
            Faction.NATO.value: FactionState(
                Faction.NATO, resources=500, is_human_controlled=True
            ),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=500),
        },
        formations={
            "toe-nato": Formation(
                formation_id="toe-nato",
                display_name="NATO",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-russia": Formation(
                formation_id="toe-russia",
                display_name="Russia",
                faction=Faction.RUSSIA,
                nation="rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "A", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
            "b": Province("b", "B", owner=Faction.RUSSIA, neighbors=["a"], x=100, y=0),
        },
        battalions={
            "bn-n": _battalion("bn-n", "sf-n", Faction.NATO, "a"),
            "bn-r": _battalion("bn-r", "sf-r", Faction.RUSSIA, "b"),
        },
        strategic_formations={
            "sf-n": _formation("sf-n", "bn-n", Faction.NATO, "a"),
            "sf-r": _formation("sf-r", "bn-r", Faction.RUSSIA, "b"),
        },
        schema_version=8,
        turn_number=1,
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
    )


class OperationalS9CAmbushReadinessTests(unittest.TestCase):
    def test_node_ambush_requires_one_complete_stationary_tick(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            force = state.strategic_formations["sf-n"]
            force.stance = FormationStance.AMBUSH.value

            self.assertIsNone(getattr(force, "ambush_ready_tick", None))
            report = advance_operational_tick(state)

            self.assertTrue(report["advanced"])
            self.assertEqual(report["global_tick"], 1)
            self.assertEqual(getattr(force, "ambush_ready_tick", None), 1)

    def test_readiness_save_load_and_same_tick_refresh_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = _state(root)
            force = state.strategic_formations["sf-n"]
            force.stance = FormationStance.AMBUSH.value
            advance_operational_tick(state)

            refresh_ambush_readiness(state, completed_tick=1)
            refresh_ambush_readiness(state, completed_tick=1)
            self.assertEqual(force.ambush_ready_tick, 1)

            save_path = root / "campaign.json"
            save_campaign(state, save_path)
            loaded = load_campaign(save_path)

            self.assertEqual(
                loaded.strategic_formations["sf-n"].ambush_ready_tick,
                1,
            )

    def test_fixed_edge_position_and_cut_off_state_still_prepare(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            force = state.strategic_formations["sf-n"]
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            force.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=stable_edge_id("corridor", node_a, node_b),
                progress_milli=375,
                facing_node_id=node_b,
            )
            force.stance = FormationStance.AMBUSH.value
            force.supplied = False
            force.cut_off = True
            force.source_hub_id = None
            force.route_cost = None
            force.grace_ticks_remaining = 0

            advance_operational_tick(state)

            self.assertEqual(force.ambush_ready_tick, 1)

    def test_movement_and_stance_change_clear_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            force = state.strategic_formations["sf-n"]
            force.stance = FormationStance.AMBUSH.value
            advance_operational_tick(state)
            self.assertEqual(force.ambush_ready_tick, 1)

            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", node_a, node_b)
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[edge],
                order_id="ord-ambush-move",
            )
            self.assertEqual(
                commit_move_orders(
                    state, locked_stance=FormationStance.AMBUSH.value
                ),
                ["sf-n"],
            )
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertEqual(report["moved"], ["sf-n"])
            self.assertIsNone(force.ambush_ready_tick)

            force.move_order = None
            force.stance = FormationStance.OPERATIONAL.value
            force.ambush_ready_tick = 2
            refresh_ambush_readiness(state, completed_tick=2)
            self.assertIsNone(force.ambush_ready_tick)


if __name__ == "__main__":
    unittest.main()
