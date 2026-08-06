from __future__ import annotations

import copy
import json
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
    ForceEchelon,
    Formation,
    FormationKind,
    Province,
    StrategicFormation,
)
from gates_of_codex.operational_interception import (
    ENCOUNTER_KIND_EDGE_CATCHUP,
    ENCOUNTER_KIND_EDGE_CROSS,
    ENCOUNTER_KIND_NODE_SIMULTANEOUS,
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
    FormationStance,
    MoveOrderStatus,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


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


def _node(pid: str, *, pixel: list[int]) -> dict:
    return {
        "node_id": stable_node_id(pid),
        "display_name": pid,
        "pixel": pixel,
        "province_id": pid,
        "site_id": None,
        "kind": "anchor",
        "terrain": "plain",
        "metadata": {},
    }


def _graph(*, ab_cost: int = 2000) -> dict:
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s6_test",
        "rules": {"ticks_per_strategic_turn": 10, "capture_hold_ticks": 2},
        "sites": [],
        "nodes": [_node("a", pixel=[0, 0]), _node("b", pixel=[1000, 0]), _node("c", pixel=[2000, 0])],
        "edges": [_edge("a", "b", cost=ab_cost), _edge("b", "c", cost=ab_cost)],
        "metadata": {},
    }


def _bn(bid: str, faction: Faction, province: str, force_id: str) -> Battalion:
    toe = "toe-nato" if faction == Faction.NATO else "toe-rusa"
    return Battalion(
        battalion_id=bid,
        faction=faction,
        province_id=province,
        formation_id=toe,
        roster=[BattalionRosterEntry("t", 1, category="tank")],
        authorized_roster=[BattalionRosterEntry("t", 1, category="tank")],
        strategic_formation_id=force_id,
    )


def _force(fid: str, faction: Faction, province: str, bn: str) -> StrategicFormation:
    return StrategicFormation(
        strategic_formation_id=fid,
        display_name=fid,
        faction=faction,
        province_id=province,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=[bn],
        template_formation_id="toe-nato" if faction == Faction.NATO else "toe-rusa",
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province),
            progress_milli=0,
        ),
    )


def _state(tmp: Path, graph: dict | None = None) -> CampaignState:
    g = graph or _graph()
    path = tmp / "operational_graph.json"
    path.write_text(json.dumps(g), encoding="utf-8")
    state = CampaignState(
        campaign_name="S6",
        map_id="s6_test",
        map_metadata={
            "operational_graph": str(path.resolve()),
            "operational_maneuver_enabled": True,
        },
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=500, is_human_controlled=True),
            Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=500),
        },
        formations={
            "toe-nato": Formation(
                formation_id="toe-nato",
                display_name="N",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
            "toe-rusa": Formation(
                formation_id="toe-rusa",
                display_name="R",
                faction=Faction.RUSSIA,
                nation="rus",
                kind=FormationKind.ARMORED_BRIGADE,
            ),
        },
        provinces={
            "a": Province("a", "A", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
            "b": Province("b", "B", owner=Faction.NEUTRAL, neighbors=["a", "c"], x=100, y=0),
            "c": Province("c", "C", owner=Faction.RUSSIA, neighbors=["b"], x=200, y=0),
        },
        battalions={
            "bn-n": _bn("bn-n", Faction.NATO, "a", "sf-n"),
            "bn-r": _bn("bn-r", Faction.RUSSIA, "b", "sf-r"),
        },
        strategic_formations={
            "sf-n": _force("sf-n", Faction.NATO, "a", "bn-n"),
            "sf-r": _force("sf-r", Faction.RUSSIA, "b", "bn-r"),
        },
        schema_version=7,
        turn_number=1,
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
    )
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    state.strategic_formations["sf-n"].position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value, node_id=stable_node_id("a"), progress_milli=0
    )
    state.strategic_formations["sf-r"].position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value, node_id=stable_node_id("b"), progress_milli=0
    )
    return state


class OperationalS6InterceptionTests(unittest.TestCase):
    def test_opposing_edge_cross_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # cost 2000 → each moves 500 canonical per tick
            state = _state(Path(temporary), _graph(ab_cost=2000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Place both on edge moving toward each other.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-n"].province_id = "a"
            state.battalions["bn-n"].province_id = "a"
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=na,
            )
            state.strategic_formations["sf-r"].province_id = "b"
            state.battalions["bn-r"].province_id = "b"
            # Active orders along the edge.
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="ord-n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="ord-r"
            )
            commit_move_orders(state, locked_stance=FormationStance.OPERATIONAL.value)
            activate_committed_orders(state)
            # Both already on edge; re-set positions after issue start checks.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=200,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=200,
                facing_node_id=na,
            )
            report = advance_operational_tick(state)
            self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, report.get("swept_kind"))
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            pb = state.pending_battle
            self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, pb.encounter_kind)
            self.assertEqual(edge, pb.encounter_edge_id)
            self.assertEqual(500, pb.encounter_progress_milli)
            self.assertEqual([500, 0], pb.encounter_pixel)
            for fid in ("sf-n", "sf-r"):
                force = state.strategic_formations[fid]
                assert force.position is not None
                self.assertEqual(PositionMode.ON_EDGE.value, force.position.mode)
                self.assertEqual(edge, force.position.edge_id)
                assert force.move_order is not None
                self.assertEqual(MoveOrderStatus.BLOCKED.value, force.move_order.status)

    def test_insertion_order_independent(self) -> None:
        def run(order_ids: list[str]) -> dict:
            with tempfile.TemporaryDirectory() as temporary:
                state = _state(Path(temporary), _graph(ab_cost=2000))
                na, nb = stable_node_id("a"), stable_node_id("b")
                edge = stable_edge_id("corridor", na, nb)
                # Rebuild formations dict in requested order.
                forces = {fid: state.strategic_formations[fid] for fid in order_ids}
                state.strategic_formations = forces
                for fid, facing, prog, prov in (
                    ("sf-n", nb, 200, "a"),
                    ("sf-r", na, 200, "b"),
                ):
                    state.strategic_formations[fid].position = FormationOperationalPosition(
                        mode=PositionMode.ON_EDGE.value,
                        edge_id=edge,
                        progress_milli=prog,
                        facing_node_id=facing,
                    )
                    state.strategic_formations[fid].province_id = prov
                issue_move_order(
                    state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
                )
                issue_move_order(
                    state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
                )
                # restore on-edge after issue
                state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=200,
                    facing_node_id=nb,
                )
                state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=200,
                    facing_node_id=na,
                )
                commit_move_orders(state)
                activate_committed_orders(state)
                advance_operational_tick(state)
                pb = state.pending_battle
                assert pb is not None
                return {
                    "kind": pb.encounter_kind,
                    "progress": pb.encounter_progress_milli,
                    "pixel": list(pb.encounter_pixel),
                    "atk": pb.attacker_formation_id,
                    "def": pb.defender_formation_id,
                    "edge": pb.encounter_edge_id,
                }

        a = run(["sf-n", "sf-r"])
        b = run(["sf-r", "sf-n"])
        self.assertEqual(a, b)

    def test_no_cross_when_intervals_do_not_meet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=5000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Far apart, small step — no meet.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=na,
            )
            # canonical: n at 0, r at 1000; delta 200 each → ends 200 and 800, no cross
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=na,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertIsNone(state.pending_battle)

    def test_same_direction_catchup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # Fast rear (cost 1000 → delta 1000), slow front (we'll set slow stance via low progress)
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Both toward b; front at 600, rear at 0; rear moves +1000 → catch
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="r"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            # Make front slow via entrenched stance at commit — only sf-r
            commit_move_orders(state, faction="rusa", locked_stance=FormationStance.ENTRENCHED.value)
            commit_move_orders(state, faction="nato", locked_stance=FormationStance.OPERATIONAL.value)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
            assert state.pending_battle is not None
            self.assertEqual("sf-n", state.pending_battle.attacker_formation_id)
            self.assertEqual("sf-r", state.pending_battle.defender_formation_id)

    def test_allied_same_edge_no_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
            # Make both NATO
            state.strategic_formations["sf-r"].faction = Faction.NATO
            state.battalions["bn-r"].faction = Faction.NATO
            state.battalions["bn-r"].formation_id = "toe-nato"
            state.strategic_formations["sf-r"].template_formation_id = "toe-nato"
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
            )
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertIsNone(state.pending_battle)

    def test_simultaneous_node_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            e1 = stable_edge_id("corridor", na, nb)
            e2 = stable_edge_id("corridor", nb, nc)
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nc, progress_milli=0
            )
            state.strategic_formations["sf-r"].province_id = "c"
            state.battalions["bn-r"].province_id = "c"
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[e1], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nc, nb], path_edge_ids=[e2], order_id="r"
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertIn(
                report.get("swept_kind"),
                {ENCOUNTER_KIND_NODE_SIMULTANEOUS, "node_contact", ""},
            )
            self.assertIsNotNone(state.pending_battle)

    def test_edge_battle_save_load_and_frontend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root, _graph(ab_cost=2000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            for fid, face, prog, prov in (
                ("sf-n", nb, 200, "a"),
                ("sf-r", na, 200, "b"),
            ):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
                state.strategic_formations[fid].province_id = prov
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
            )
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            path = root / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            assert reloaded.pending_battle is not None
            self.assertEqual(edge, reloaded.pending_battle.encounter_edge_id)
            self.assertEqual(500, reloaded.pending_battle.encounter_progress_milli)
            self.assertEqual([500, 0], reloaded.pending_battle.encounter_pixel)
            snap = build_frontend_snapshot(reloaded)
            self.assertEqual(12, snap["schema_version"])
            self.assertEqual(FRONTEND_SCHEMA_VERSION, snap["schema_version"])
            pb = snap["pending_battle"]
            self.assertEqual(edge, pb["encounter_edge_id"])
            self.assertEqual(500, pb["encounter_progress_milli"])
            self.assertEqual([500, 0], pb["encounter_pixel"])
            self.assertIsInstance(pb["encounter_pixel"][0], int)

    def test_malformed_encounter_pixel_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
            )
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            payload = state.to_dict()
            payload["pending_battle"]["encounter_pixel"] = ["1", 2]
            with self.assertRaises(ValueError):
                from gates_of_codex.state_io import campaign_from_dict

                campaign_from_dict(payload)
            payload["pending_battle"]["encounter_progress_milli"] = True
            payload["pending_battle"]["encounter_pixel"] = [1, 2]
            with self.assertRaises(ValueError):
                from gates_of_codex.state_io import campaign_from_dict

                campaign_from_dict(payload)

    def test_edge_battle_no_ownership_flip_winner_stays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
            state.provinces["b"].owner = Faction.RUSSIA
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            for fid, face, prog, prov in (
                ("sf-n", nb, 200, "a"),
                ("sf-r", na, 200, "b"),
            ):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
                state.strategic_formations[fid].province_id = prov
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
            )
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            CampaignEngine(state, random_seed=1).apply_battle_result(Faction.NATO)
            self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)
            winner = state.strategic_formations.get("sf-n")
            if winner is not None and winner.position is not None:
                self.assertEqual(PositionMode.ON_EDGE.value, winner.position.mode)
                self.assertEqual(edge, winner.position.edge_id)


if __name__ == "__main__":
    unittest.main()
