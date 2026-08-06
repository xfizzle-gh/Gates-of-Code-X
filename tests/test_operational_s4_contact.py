from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.force_migration import ensure_strategic_formations
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
from gates_of_codex.operational_contact import (
    ENCOUNTER_KIND_NODE_CONTACT,
    can_enter_node_friendly_stack,
    formations_at_node,
    node_is_contested,
)
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_position import ensure_operational_positions
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    FormationOperationalPosition,
    MoveOrderStatus,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


def _node(province_id: str, *, pixel: list[int]) -> dict:
    return {
        "node_id": stable_node_id(province_id, "anchor"),
        "display_name": province_id,
        "pixel": pixel,
        "province_id": province_id,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _edge(a: str, b: str, *, cost: int = COST_MILLI_UNITY) -> dict:
    na, nb = stable_node_id(a), stable_node_id(b)
    return {
        "edge_id": stable_edge_id("corridor", na, nb),
        "a": na,
        "b": nb,
        "kind": "corridor",
        "authority": "authored",
        "length_px": 100,
        "base_move_points_milli": COST_MILLI_UNITY,
        "movement_cost_milli": cost,
        "requires_port": False,
        "can_be_blockaded": False,
        "traversal_enabled": True,
        "bidirectional": True,
        "province_ids": [a, b],
        "legacy_crossing_type": None,
        "metadata": {},
    }


def _graph() -> dict:
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s4_test",
        "rules": {
            "ticks_per_strategic_turn": 10,
            "max_friendly_formations_per_node": 3,
        },
        "sites": [],
        "nodes": [_node("a", pixel=[0, 0]), _node("b", pixel=[100, 0])],
        "edges": [_edge("a", "b")],
        "metadata": {},
    }


def _bn(bid: str, faction: Faction, province: str) -> Battalion:
    toe = "toe-nato" if faction == Faction.NATO else "toe-rusa"
    return Battalion(
        battalion_id=bid,
        faction=faction,
        province_id=province,
        formation_id=toe,
        roster=[BattalionRosterEntry("tank(x)", 1, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank(x)", 1, category="tank")],
    )


def _force(fid: str, faction: Faction, province: str, bn_ids: list[str]) -> StrategicFormation:
    return StrategicFormation(
        strategic_formation_id=fid,
        display_name=fid,
        faction=faction,
        province_id=province,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=list(bn_ids),
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province),
            progress_milli=0,
        ),
    )


def _state(tmp: Path, *, with_enemy: bool = True) -> CampaignState:
    graph_path = tmp / "operational_graph.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")
    battalions = {
        "bn-nato": _bn("bn-nato", Faction.NATO, "a"),
    }
    forces = {
        "sf-nato": _force("sf-nato", Faction.NATO, "a", ["bn-nato"]),
    }
    battalions["bn-nato"].strategic_formation_id = "sf-nato"
    if with_enemy:
        battalions["bn-rusa"] = _bn("bn-rusa", Faction.RUSSIA, "b")
        forces["sf-rusa"] = _force("sf-rusa", Faction.RUSSIA, "b", ["bn-rusa"])
        battalions["bn-rusa"].strategic_formation_id = "sf-rusa"
    state = CampaignState(
        campaign_name="S4",
        map_id="s4_test",
        map_metadata={"operational_graph": str(graph_path.resolve())},
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=500, is_human_controlled=True),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=500),
        },
        formations={
            "toe-nato": Formation(
                formation_id="toe-nato",
                display_name="NATO T",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-rusa": Formation(
                formation_id="toe-rusa",
                display_name="RUSA T",
                faction=Faction.RUSSIA,
                nation="rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "A", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
            "b": Province("b", "B", owner=Faction.RUSSIA, neighbors=["a"], x=100, y=0),
        },
        battalions=battalions,
        strategic_formations=forces,
        schema_version=7,
        turn_number=1,
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
    )
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    # Re-apply positions after hydrate (anchors).
    for force in state.strategic_formations.values():
        force.position = FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(force.province_id),
            progress_milli=0,
        )
    return state


class OperationalS4ContactTests(unittest.TestCase):
    def test_enemy_node_entry_stops_and_creates_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertTrue(report["advanced"])
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual(ENCOUNTER_KIND_NODE_CONTACT, state.pending_battle.encounter_kind)
            self.assertEqual(nb, state.pending_battle.encounter_node_id)
            self.assertEqual("sf-nato", state.pending_battle.attacker_formation_id)
            self.assertEqual("sf-rusa", state.pending_battle.defender_formation_id)
            nato = state.strategic_formations["sf-nato"]
            assert nato.position is not None
            self.assertEqual(nb, nato.position.node_id)
            assert nato.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, nato.move_order.status)
            self.assertTrue(node_is_contested(state, nb))

    def test_static_co_location_opens_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            nb = stable_node_id("b")
            # Place NATO on same node as Russia without moving.
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            state.battalions["bn-nato"].province_id = "b"
            report = advance_operational_tick(state)
            self.assertEqual("static_contact", report.get("reason"))
            self.assertIsNotNone(state.pending_battle)

    def test_friendly_stack_cap_blocks_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=False)
            nb = stable_node_id("b")
            # Three friendlies already on b.
            for index in range(3):
                bid = f"bn-f{index}"
                fid = f"sf-f{index}"
                state.battalions[bid] = _bn(bid, Faction.NATO, "b")
                state.battalions[bid].strategic_formation_id = fid
                state.strategic_formations[fid] = _force(fid, Faction.NATO, "b", [bid])
            self.assertEqual(3, len(formations_at_node(state, nb)))
            mover = state.strategic_formations["sf-nato"]
            self.assertFalse(can_enter_node_friendly_stack(state, mover, nb))
            na = stable_node_id("a")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            nato = state.strategic_formations["sf-nato"]
            assert nato.position is not None
            # Did not enter b; stayed off the destination node.
            self.assertNotEqual(nb, nato.position.node_id)
            assert nato.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, nato.move_order.status)
            self.assertIsNone(state.pending_battle)

    def test_friendly_cooperation_under_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=False)
            nb = stable_node_id("b")
            state.battalions["bn-f0"] = _bn("bn-f0", Faction.NATO, "b")
            state.battalions["bn-f0"].strategic_formation_id = "sf-f0"
            state.strategic_formations["sf-f0"] = _force(
                "sf-f0", Faction.NATO, "b", ["bn-f0"]
            )
            na = stable_node_id("a")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            nato = state.strategic_formations["sf-nato"]
            assert nato.position is not None
            self.assertEqual(nb, nato.position.node_id)
            assert nato.move_order is not None
            self.assertEqual(MoveOrderStatus.COMPLETED.value, nato.move_order.status)
            self.assertIsNone(state.pending_battle)
            self.assertEqual(2, len(formations_at_node(state, nb)))

    def test_pending_battle_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root, with_enemy=True)
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            path = root / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            self.assertIsNotNone(reloaded.pending_battle)
            assert reloaded.pending_battle is not None
            self.assertEqual(ENCOUNTER_KIND_NODE_CONTACT, reloaded.pending_battle.encounter_kind)
            self.assertEqual(nb, reloaded.pending_battle.encounter_node_id)

    def test_ticks_stop_after_contact_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            from gates_of_codex.operational_movement import advance_operational_ticks

            batch = advance_operational_ticks(state, 10)
            self.assertLess(batch["ticks"], 10)
            self.assertIsNotNone(state.pending_battle)


if __name__ == "__main__":
    unittest.main()
