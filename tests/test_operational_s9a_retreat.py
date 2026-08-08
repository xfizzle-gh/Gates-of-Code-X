from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gates_of_codex.models import (
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
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
from gates_of_codex.operational_retreat import (
    RETREAT_ORIGIN_NODES_KEY,
    clear_retreat_origin_node,
    clear_retreat_origin_nodes,
    record_retreat_origin_node,
    retreat_origin_node,
)
from gates_of_codex.operational_schema import (
    FormationOperationalPosition,
    FormationStance,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


def _node(province_id: str) -> dict:
    return {
        "node_id": stable_node_id(province_id),
        "display_name": province_id,
        "pixel": [ord(province_id[0]) * 10, 0],
        "province_id": province_id,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _edge(
    a: str,
    b: str,
    *,
    edge_id: str | None = None,
    cost: int = 1000,
    enabled: bool = True,
    authority: str = "authored",
    kind: str = "road",
    bidirectional: bool = True,
    metadata: dict | None = None,
) -> dict:
    node_a, node_b = stable_node_id(a), stable_node_id(b)
    return {
        "edge_id": edge_id or stable_edge_id("corridor", node_a, node_b),
        "a": node_a,
        "b": node_b,
        "kind": kind,
        "authority": authority,
        "length_px": 100,
        "base_move_points_milli": 1000,
        "movement_cost_milli": cost,
        "requires_port": kind in {"ferry", "ferry_or_sea_lane", "sea_lane"},
        "can_be_blockaded": False,
        "traversal_enabled": enabled,
        "bidirectional": bidirectional,
        "province_ids": [a, b],
        "legacy_crossing_type": None,
        "metadata": dict(metadata or {}),
    }


def _graph(*, edges: list[dict] | None = None) -> dict:
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s9a-test",
        "rules": {
            "ticks_per_strategic_turn": 10,
            "max_friendly_formations_per_node": 3,
        },
        "sites": [],
        "nodes": [_node("a"), _node("b"), _node("c"), _node("d")],
        "edges": list(edges or [_edge("a", "b"), _edge("b", "c"), _edge("b", "d")]),
        "metadata": {},
    }


def _formation(
    force_id: str,
    battalion_id: str,
    faction: Faction,
    province_id: str,
) -> tuple[StrategicFormation, Battalion]:
    template = "toe-nato" if faction == Faction.NATO else "toe-rusa"
    force = StrategicFormation(
        strategic_formation_id=force_id,
        display_name=force_id,
        faction=faction,
        province_id=province_id,
        battalion_ids=[battalion_id],
        template_formation_id=template,
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province_id),
            progress_milli=0,
        ),
    )
    battalion = Battalion(
        battalion_id=battalion_id,
        faction=faction,
        province_id=province_id,
        strategic_formation_id=force_id,
        formation_id=template,
        roster=[BattalionRosterEntry("tank", 2, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank", 2, category="tank")],
    )
    return force, battalion


def _state(root: Path, *, graph: dict | None = None) -> CampaignState:
    graph_path = root / "operational_graph.json"
    graph_path.write_text(json.dumps(graph or _graph()), encoding="utf-8")
    nato_force, nato_bn = _formation("sf-nato", "bn-nato", Faction.NATO, "a")
    rusa_force, rusa_bn = _formation("sf-rusa", "bn-rusa", Faction.RUSSIA, "b")
    return CampaignState(
        campaign_name="S9A",
        map_id="s9a-test",
        map_metadata={
            "operational_graph": str(graph_path.resolve()),
            "operational_maneuver_enabled": True,
        },
        factions={
            Faction.NATO.value: FactionState(Faction.NATO),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA),
        },
        formations={
            "toe-nato": Formation(
                "toe-nato",
                "NATO",
                Faction.NATO,
                "usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-rusa": Formation(
                "toe-rusa",
                "Russia",
                Faction.RUSSIA,
                "rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "A", Faction.NATO, neighbors=["b"]),
            "b": Province("b", "B", Faction.RUSSIA, neighbors=["a", "c", "d"]),
            "c": Province("c", "C", Faction.RUSSIA, neighbors=["b"]),
            "d": Province("d", "D", Faction.RUSSIA, neighbors=["b"]),
        },
        battalions={nato_bn.battalion_id: nato_bn, rusa_bn.battalion_id: rusa_bn},
        strategic_formations={
            nato_force.strategic_formation_id: nato_force,
            rusa_force.strategic_formation_id: rusa_force,
        },
        schema_version=8,
    )


class OperationalS9AOriginTests(unittest.TestCase):
    def test_origin_helpers_use_existing_compatibility_key(self) -> None:
        state = CampaignState(campaign_name="S9A origin")

        record_retreat_origin_node(state, "sf-n", "node-a")

        self.assertEqual("operational_edge_retreat_nodes", RETREAT_ORIGIN_NODES_KEY)
        self.assertEqual(
            {"sf-n": "node-a"},
            state.map_metadata["operational_edge_retreat_nodes"],
        )
        self.assertEqual("node-a", retreat_origin_node(state, "sf-n"))

        clear_retreat_origin_node(state, "sf-n")
        self.assertIsNone(retreat_origin_node(state, "sf-n"))

        record_retreat_origin_node(state, "sf-a", "node-a")
        record_retreat_origin_node(state, "sf-b", "node-b")
        clear_retreat_origin_nodes(state)
        self.assertEqual({}, state.map_metadata[RETREAT_ORIGIN_NODES_KEY])

    def test_node_contact_save_load_preserves_exact_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            edge_ab = stable_edge_id("corridor", node_a, node_b)
            issue_move_order(
                state,
                "sf-nato",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[edge_ab],
                order_id="ord-node-contact",
            )
            commit_move_orders(
                state,
                faction=Faction.NATO.value,
                locked_stance=FormationStance.OPERATIONAL.value,
            )
            activate_committed_orders(state)

            report = advance_operational_tick(state)

            self.assertTrue(report["battle_id"])
            self.assertEqual(node_a, retreat_origin_node(state, "sf-nato"))
            save_path = root / "campaign.json"
            save_campaign(state, save_path)
            loaded = load_campaign(save_path)
            self.assertEqual(node_a, retreat_origin_node(loaded, "sf-nato"))


if __name__ == "__main__":
    unittest.main()
