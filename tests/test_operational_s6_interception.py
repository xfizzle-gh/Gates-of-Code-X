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


def _add_force(
    state: CampaignState, fid: str, bid: str, faction: Faction, province: str
) -> None:
    state.battalions[bid] = _bn(bid, faction, province, fid)
    state.strategic_formations[fid] = _force(fid, faction, province, bid)


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
            self.assertEqual(ENCOUNTER_KIND_NODE_SIMULTANEOUS, report.get("swept_kind"))
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual(
                ENCOUNTER_KIND_NODE_SIMULTANEOUS, state.pending_battle.encounter_kind
            )
            self.assertEqual(nb, state.pending_battle.encounter_node_id)

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

    def test_faster_rear_does_not_reach_no_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # Genuinely faster rear (forced march) still cannot close the gap this tick.
            # cost 5000 → operational delta 200, forced-march delta 300.
            # rear@0 v=300, front@600 v=200 → catch t=600/100=6 > 1.
            state = _state(Path(temporary), _graph(ab_cost=5000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            for fid, prog in (("sf-n", 0), ("sf-r", 600)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=nb,
                )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="r"
            )
            for fid, prog in (("sf-n", 0), ("sf-r", 600)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=nb,
                )
            commit_move_orders(
                state, faction="nato", locked_stance=FormationStance.FORCED_MARCH.value
            )
            commit_move_orders(
                state, faction="rusa", locked_stance=FormationStance.OPERATIONAL.value
            )
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertIsNone(state.pending_battle)
            # Rear advanced farther than front but did not meet.
            n_pos = state.strategic_formations["sf-n"].position
            r_pos = state.strategic_formations["sf-r"].position
            assert n_pos is not None and r_pos is not None
            self.assertEqual(PositionMode.ON_EDGE.value, n_pos.mode)
            self.assertEqual(PositionMode.ON_EDGE.value, r_pos.mode)
            self.assertGreater(n_pos.progress_milli, 0)
            self.assertLess(n_pos.progress_milli, r_pos.progress_milli)

    def test_exact_progress_ally_joins_edge_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Ally already at exact meeting progress (canonical 500 → form prog 500 toward b)
            state.battalions["bn-ally"] = _bn("bn-ally", Faction.NATO, "a", "sf-ally")
            state.strategic_formations["sf-ally"] = _force(
                "sf-ally", Faction.NATO, "a", "bn-ally"
            )
            state.strategic_formations["sf-ally"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=500,
                facing_node_id=nb,
            )
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
            # Restore ally exact progress after any hydrate
            state.strategic_formations["sf-ally"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=500,
                facing_node_id=nb,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            atk = {p.battalion_id for p in state.pending_battle.attacking_participants}
            self.assertIn("bn-ally", atk | {p.battalion_id for p in state.pending_battle.defending_participants})

    def test_same_edge_elsewhere_ally_does_not_join(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            state.battalions["bn-ally"] = _bn("bn-ally", Faction.NATO, "a", "sf-ally")
            state.strategic_formations["sf-ally"] = _force(
                "sf-ally", Faction.NATO, "a", "bn-ally"
            )
            # Ally on same edge but at progress 50 (canonical 50), not contact 500
            state.strategic_formations["sf-ally"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=50,
                facing_node_id=nb,
            )
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
            state.strategic_formations["sf-ally"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=50,
                facing_node_id=nb,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            ids = {p.battalion_id for p in state.pending_battle.attacking_participants} | {
                p.battalion_id for p in state.pending_battle.defending_participants
            }
            self.assertNotIn("bn-ally", ids)

    def test_rational_earliest_contact_selection(self) -> None:
        from gates_of_codex.operational_interception import (
            ContactCandidate,
            select_primary_contact,
        )

        # Collision under old floor(time * 10_000_000) key (both floor to 0),
        # but 2/20000003 < 1/10000001 exactly.
        early = ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CROSS,
            time_num=2,
            time_den=20_000_003,
            edge_id="z-edge",
            node_id="",
            progress_canonical=900,
            attacker_id="z1",
            defender_id="z2",
            participant_ids=("z1", "z2"),
        )
        late = ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CROSS,
            time_num=1,
            time_den=10_000_001,
            edge_id="a-edge",
            node_id="",
            progress_canonical=1,
            attacker_id="a1",
            defender_id="a2",
            participant_ids=("a1", "a2"),
        )
        old_early = early.time_num * 10_000_000 // early.time_den
        old_late = late.time_num * 10_000_000 // late.time_den
        self.assertEqual(0, old_early)
        self.assertEqual(0, old_late)  # old key collides
        self.assertTrue(early.time_less_than(late))
        # If times were treated equal, tie-break would pick a-edge; exact must pick early.
        self.assertIs(select_primary_contact([late, early]), early)

    def test_site_capture_paused_during_edge_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
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
            report = advance_operational_tick(state)
            self.assertIsNotNone(state.pending_battle)
            self.assertFalse(report.get("capture", {}).get("advanced"))

    def test_tick_halts_for_nonparticipants_after_contact(self) -> None:
        """Single-battle model: nonparticipants do not continue moving this tick."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
            # Third formation moving a→b from node, would arrive if tick continued.
            state.battalions["bn-x"] = _bn("bn-x", Faction.NATO, "a", "sf-x")
            state.strategic_formations["sf-x"] = _force("sf-x", Faction.NATO, "a", "bn-x")
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
            issue_move_order(
                state, "sf-x", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="x"
            )
            for fid, face, prog in (("sf-n", nb, 200), ("sf-r", na, 200)):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            state.strategic_formations["sf-x"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=na, progress_milli=0
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertIsNotNone(state.pending_battle)
            # Nonparticipant still at origin node (did not move this tick).
            x = state.strategic_formations["sf-x"]
            assert x.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, x.position.mode)
            self.assertEqual(na, x.position.node_id)

    def test_encounter_contract_rejects_mixed_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
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
            # Edge kind with node id set — invalid.
            payload["pending_battle"]["encounter_node_id"] = "op-node-a-anchor"
            from gates_of_codex.state_io import campaign_from_dict

            with self.assertRaises(ValueError):
                campaign_from_dict(payload)
            payload["pending_battle"]["encounter_node_id"] = ""
            payload["pending_battle"]["encounter_kind"] = "node_contact"
            payload["pending_battle"]["encounter_edge_id"] = edge
            with self.assertRaises(ValueError):
                campaign_from_dict(payload)

    def test_retreat_metadata_cleared_after_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
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
            self.assertTrue(
                state.map_metadata.get("operational_edge_retreat_nodes")
            )
            CampaignEngine(state, random_seed=1).apply_battle_result(Faction.NATO)
            store = state.map_metadata.get("operational_edge_retreat_nodes") or {}
            self.assertNotIn("sf-n", store)
            self.assertNotIn("sf-r", store)

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

    def test_endpoint_overshoot_uses_true_velocity(self) -> None:
        """Force at 900 with delta 500 meets opposing force using real exit time."""
        with tempfile.TemporaryDirectory() as temporary:
            # cost 1000 → delta 1000/tick
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # NATO at canonical 900 toward B (form prog 900), exits at t=100/1000=0.1
            # Russia at canonical 1000 toward A (form prog 0 facing A), starts at B end
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=900,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=na,
            )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nb, na], path_edge_ids=[edge], order_id="r"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=900,
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
            report = advance_operational_tick(state)
            # Meet: 900+t*1000 = 1000+t*(-1000) => 900+1000t=1000-1000t => 2000t=100 => t=1/20
            self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, report.get("swept_kind"))
            assert state.pending_battle is not None
            self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, state.pending_battle.encounter_kind)
            # Contact near 950
            self.assertGreaterEqual(state.pending_battle.encounter_progress_milli, 900)
            self.assertLessEqual(state.pending_battle.encounter_progress_milli, 1000)

    def test_static_t0_beats_later_edge_contact(self) -> None:
        """t=0 static node contact wins over a real later edge cross in one tick."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            edge_ab = stable_edge_id("corridor", na, nb)
            edge_bc = stable_edge_id("corridor", nb, nc)
            # Hostile already sharing node a at t=0
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=na, progress_milli=0
            )
            state.strategic_formations["sf-n"].province_id = "a"
            state.battalions["bn-n"].province_id = "a"
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=na, progress_milli=0
            )
            state.strategic_formations["sf-r"].province_id = "a"
            state.battalions["bn-r"].province_id = "a"
            # Separate pair that would edge-cross mid-tick on b-c
            _add_force(state, "sf-n2", "bn-n2", Faction.NATO, "b")
            _add_force(state, "sf-r2", "bn-r2", Faction.RUSSIA, "c")
            state.strategic_formations["sf-n2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nc,
            )
            state.strategic_formations["sf-r2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n2", path_node_ids=[nb, nc], path_edge_ids=[edge_bc], order_id="n2"
            )
            issue_move_order(
                state, "sf-r2", path_node_ids=[nc, nb], path_edge_ids=[edge_bc], order_id="r2"
            )
            state.strategic_formations["sf-n2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nc,
            )
            state.strategic_formations["sf-r2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nb,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertEqual("node_contact", report.get("swept_kind"))
            assert state.pending_battle is not None
            self.assertEqual("node_contact", state.pending_battle.encounter_kind)
            self.assertEqual(na, state.pending_battle.encounter_node_id)
            # Edge pair never advanced
            n2 = state.strategic_formations["sf-n2"]
            assert n2.position is not None
            self.assertEqual(PositionMode.ON_EDGE.value, n2.position.mode)
            self.assertEqual(0, n2.position.progress_milli)
            self.assertNotIn("bn-n2", {
                p.battalion_id for p in state.pending_battle.attacking_participants
            } | {
                p.battalion_id for p in state.pending_battle.defending_participants
            })

    def test_early_node_entry_beats_later_edge_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            edge_ab = stable_edge_id("corridor", na, nb)
            edge_bc = stable_edge_id("corridor", nb, nc)
            # Enemy holds b; NATO near B end arrives at t=100/1000
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-r"].province_id = "b"
            state.battalions["bn-r"].province_id = "b"
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=900,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge_ab], order_id="n"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=900,
                facing_node_id=nb,
            )
            # Later edge cross on b-c at t=0.5
            _add_force(state, "sf-n2", "bn-n2", Faction.NATO, "b")
            _add_force(state, "sf-r2", "bn-r2", Faction.RUSSIA, "c")
            state.strategic_formations["sf-n2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nc,
            )
            state.strategic_formations["sf-r2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n2", path_node_ids=[nb, nc], path_edge_ids=[edge_bc], order_id="n2"
            )
            issue_move_order(
                state, "sf-r2", path_node_ids=[nc, nb], path_edge_ids=[edge_bc], order_id="r2"
            )
            state.strategic_formations["sf-n2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nc,
            )
            state.strategic_formations["sf-r2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nb,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertEqual("node_contact", report.get("swept_kind"))
            assert state.pending_battle is not None
            self.assertEqual(nb, state.pending_battle.encounter_node_id)
            self.assertEqual("b", state.strategic_formations["sf-n"].province_id)
            # Later edge movers unmoved, not in battle
            self.assertEqual(0, state.strategic_formations["sf-n2"].position.progress_milli)
            ids = {
                p.battalion_id for p in state.pending_battle.attacking_participants
            } | {
                p.battalion_id for p in state.pending_battle.defending_participants
            }
            self.assertIn("bn-n", ids)
            self.assertNotIn("bn-n2", ids)

    def test_different_arrival_fractions_only_earliest_applies(self) -> None:
        """Early arrival joins battle; later same-node arrival stays put, not in battle."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Enemy at b
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-r"].province_id = "b"
            state.battalions["bn-r"].province_id = "b"
            # Early NATO: start 750 → arrives t=250/1000
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=750,
                facing_node_id=nb,
            )
            # Late NATO ally: start 250 → arrives t=750/1000
            _add_force(state, "sf-n2", "bn-n2", Faction.NATO, "a")
            state.strategic_formations["sf-n2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=250,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            issue_move_order(
                state, "sf-n2", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n2"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=750,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-n2"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=250,
                facing_node_id=nb,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            self.assertEqual("node_contact", state.pending_battle.encounter_kind)
            self.assertEqual(nb, state.pending_battle.encounter_node_id)
            # Early arrival placed at b
            n_pos = state.strategic_formations["sf-n"].position
            assert n_pos is not None
            self.assertEqual(PositionMode.AT_NODE.value, n_pos.mode)
            self.assertEqual(nb, n_pos.node_id)
            # Late arrival still on edge at prior progress
            n2_pos = state.strategic_formations["sf-n2"].position
            assert n2_pos is not None
            self.assertEqual(PositionMode.ON_EDGE.value, n2_pos.mode)
            self.assertEqual(250, n2_pos.progress_milli)
            ids = {
                p.battalion_id for p in state.pending_battle.attacking_participants
            } | {
                p.battalion_id for p in state.pending_battle.defending_participants
            }
            self.assertIn("bn-n", ids)
            self.assertNotIn("bn-n2", ids)

    def test_equivalent_unreduced_fractions_resolve_simultaneously(self) -> None:
        """1/2 and 2/4 arrival times group as one simultaneous contact."""
        with tempfile.TemporaryDirectory() as temporary:
            # Two edges into b with different costs so raw fractions differ but reduce equal.
            graph = _graph(ab_cost=1000)
            # Override a-b cost 1000, add faster alternate via custom cost on a path —
            # use a-b for force at 500 (arrives 500/1000=1/2) and second force with
            # forced_march is messy; instead place two hostiles arriving with
            # remaining/delta = 500/1000 and 1000/2000 via different edge costs.
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            # Make b-c cost 500 → delta 2000/tick
            for edge in graph["edges"]:
                if edge["a"] == nb and edge["b"] == nc:
                    edge["movement_cost_milli"] = 500
            state = _state(Path(temporary), graph)
            edge_ab = stable_edge_id("corridor", na, nb)
            edge_bc = stable_edge_id("corridor", nb, nc)
            # Hostile pair arrive at b at equivalent times from opposite sides.
            # NATO on a-b at prog 500 facing b → remaining 500, v=1000 → t=1/2
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=500,
                facing_node_id=nb,
            )
            # Russia on b-c: facing b means toward a endpoint of edge b-c.
            # Edge b-c: a=nb, b=nc. Facing nb → direction -1, form progress from nc end.
            # At form progress 0 facing nb → canonical 1000 (at nc). Wait facing nb means
            # going toward nb, start at nc side: progress 0 facing nb is leaving nc toward nb.
            # canonical = 1000 - 0 = 1000 if facing a? 
            # formation progress is distance along facing. facing nb (edge.a): canonical = progress.
            # Actually _canonical: facing edge.b → progress; facing edge.a → 1000-progress.
            # Facing nb=edge.a of b-c → canonical = 1000 - form_progress.
            # Start at nc (form 0 facing nb): canonical 1000. velocity toward a = -2000.
            # remaining to a = 1000, mag=2000 → t=1000/2000=1/2.
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].province_id = "c"
            state.battalions["bn-r"].province_id = "c"
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge_ab], order_id="n"
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[nc, nb], path_edge_ids=[edge_bc], order_id="r"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=500,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_bc,
                progress_milli=0,
                facing_node_id=nb,
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            # Insertion-order independence: reverse formation id sort by renaming is hard;
            # run detect twice with reversed interval list.
            from gates_of_codex.operational_interception import (
                compute_movement_intervals,
                detect_swept_contacts,
                select_primary_contact,
                normalize_rational,
            )
            from gates_of_codex.operational_position import load_operational_graph_for_state
            from gates_of_codex.operational_movement import _indexes

            g = load_operational_graph_for_state(state)
            assert g is not None
            _, _, edges_by_id, nodes_by_id = _indexes(g)
            iv = compute_movement_intervals(
                state, edges_by_id=edges_by_id, nodes_by_id=nodes_by_id
            )
            times = {
                (i.formation_id, normalize_rational(i.arrival_time_num, i.arrival_time_den))
                for i in iv
                if i.arrives_node and i.arrival_time_num is not None
            }
            self.assertEqual({("sf-n", (1, 2)), ("sf-r", (1, 2))}, times)
            forward = detect_swept_contacts(
                state, iv, edges_by_id=edges_by_id, nodes_by_id=nodes_by_id
            )
            reverse = detect_swept_contacts(
                state, list(reversed(iv)), edges_by_id=edges_by_id, nodes_by_id=nodes_by_id
            )
            p1 = select_primary_contact(forward)
            p2 = select_primary_contact(list(reversed(reverse)))
            assert p1 is not None and p2 is not None
            self.assertEqual(ENCOUNTER_KIND_NODE_SIMULTANEOUS, p1.kind)
            self.assertEqual(p1.kind, p2.kind)
            self.assertEqual(set(p1.participant_ids), set(p2.participant_ids))
            self.assertEqual((p1.time_num, p1.time_den), (1, 2))
            self.assertEqual((p2.time_num, p2.time_den), (1, 2))
            report = advance_operational_tick(state)
            self.assertEqual(ENCOUNTER_KIND_NODE_SIMULTANEOUS, report.get("swept_kind"))
            assert state.pending_battle is not None
            ids = {
                p.battalion_id for p in state.pending_battle.attacking_participants
            } | {
                p.battalion_id for p in state.pending_battle.defending_participants
            }
            self.assertEqual({"bn-n", "bn-r"}, ids)
            # Both arrived at b
            for fid in ("sf-n", "sf-r"):
                pos = state.strategic_formations[fid].position
                assert pos is not None
                self.assertEqual(PositionMode.AT_NODE.value, pos.mode)
                self.assertEqual(nb, pos.node_id)

    def test_equal_time_node_vs_edge_tie_is_order_independent(self) -> None:
        from gates_of_codex.operational_interception import (
            ContactCandidate,
            ENCOUNTER_KIND_EDGE_CROSS,
            ENCOUNTER_KIND_NODE_CONTACT,
            select_primary_contact,
        )

        edge = "op-edge-z"
        node = "op-node-m"
        edge_c = ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CROSS,
            time_num=1,
            time_den=2,
            edge_id=edge,
            node_id="",
            progress_canonical=500,
            attacker_id="sf-a",
            defender_id="sf-b",
            participant_ids=("sf-a", "sf-b"),
        )
        node_c = ContactCandidate(
            kind=ENCOUNTER_KIND_NODE_CONTACT,
            time_num=1,
            time_den=2,
            edge_id="",
            node_id=node,
            progress_canonical=0,
            attacker_id="sf-c",
            defender_id="sf-d",
            participant_ids=("sf-c", "sf-d"),
        )
        # Raw IDs only (already type-qualified); no e:/n: prefix bias.
        self.assertEqual(edge, edge_c.location_key())
        self.assertEqual(node, node_c.location_key())
        # Lexicographic: "op-edge-z" < "op-node-m" → edge contact wins.
        self.assertLess(edge_c.location_key(), node_c.location_key())
        expected = edge_c
        primary_ab = select_primary_contact([edge_c, node_c])
        primary_ba = select_primary_contact([node_c, edge_c])
        self.assertIsNotNone(primary_ab)
        self.assertEqual(expected.tie_key(), primary_ab.tie_key())
        self.assertEqual(expected.tie_key(), primary_ba.tie_key())
        self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, primary_ab.kind)
        self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, primary_ba.kind)
        self.assertEqual(edge, primary_ab.location_key())
        self.assertEqual(edge, primary_ba.location_key())

    def test_moving_hostile_catches_stationary_on_edge_no_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Stationary Russia on edge at 600 with no move order.
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].move_order = None
            state.strategic_formations["sf-r"].province_id = "a"
            state.battalions["bn-r"].province_id = "a"
            # Moving NATO from 0 catches at t=0.6
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            # Keep Russia stationary after issue side-effects.
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            state.strategic_formations["sf-r"].move_order = None
            commit_move_orders(state, faction="nato")
            activate_committed_orders(state)
            state.strategic_formations["sf-r"].move_order = None
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            report = advance_operational_tick(state)
            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
            assert state.pending_battle is not None
            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, state.pending_battle.encounter_kind)
            self.assertEqual(edge, state.pending_battle.encounter_edge_id)
            self.assertEqual(600, state.pending_battle.encounter_progress_milli)
            ids = {
                p.battalion_id for p in state.pending_battle.attacking_participants
            } | {
                p.battalion_id for p in state.pending_battle.defending_participants
            }
            self.assertEqual({"bn-n", "bn-r"}, ids)
            # Stationary force never moved before stop.
            r_pos = state.strategic_formations["sf-r"].position
            assert r_pos is not None
            self.assertEqual(PositionMode.ON_EDGE.value, r_pos.mode)
            self.assertEqual(600, r_pos.progress_milli)

    def test_moving_hostile_catches_stationary_on_edge_blocked_order(self) -> None:
        from dataclasses import replace as dc_replace

        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Russia mid-edge with a blocked order (not active).
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-r", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="r"
            )
            commit_move_orders(state, faction="rusa")
            activate_committed_orders(state)
            r_order = state.strategic_formations["sf-r"].move_order
            assert r_order is not None
            state.strategic_formations["sf-r"].move_order = dc_replace(
                r_order, status=MoveOrderStatus.BLOCKED.value
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            # Moving NATO from 0.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            issue_move_order(
                state, "sf-n", path_node_ids=[na, nb], path_edge_ids=[edge], order_id="n"
            )
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )
            # Re-assert Russia stays blocked + stationary after NATO issue.
            state.strategic_formations["sf-r"].move_order = dc_replace(
                state.strategic_formations["sf-r"].move_order,
                status=MoveOrderStatus.BLOCKED.value,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            commit_move_orders(state, faction="nato")
            activate_committed_orders(state)
            state.strategic_formations["sf-r"].move_order = dc_replace(
                state.strategic_formations["sf-r"].move_order,
                status=MoveOrderStatus.BLOCKED.value,
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            report = advance_operational_tick(state)
            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
            assert state.pending_battle is not None
            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, state.pending_battle.encounter_kind)
            self.assertEqual(600, state.pending_battle.encounter_progress_milli)
            ids = {
                p.battalion_id for p in state.pending_battle.attacking_participants
            } | {
                p.battalion_id for p in state.pending_battle.defending_participants
            }
            self.assertEqual({"bn-n", "bn-r"}, ids)
            r_order = state.strategic_formations["sf-r"].move_order
            assert r_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, r_order.status)

    def test_empty_string_progress_and_pixel_rejected(self) -> None:
        from gates_of_codex.state_io import campaign_from_dict

        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000))
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
            payload["pending_battle"]["encounter_progress_milli"] = ""
            with self.assertRaises(ValueError):
                campaign_from_dict(payload)
            payload = state.to_dict()
            payload["pending_battle"]["encounter_pixel"] = ""
            with self.assertRaises(ValueError):
                campaign_from_dict(payload)
            payload = state.to_dict()
            payload["pending_battle"]["encounter_pixel"] = ["", 1]
            with self.assertRaises(ValueError):
                campaign_from_dict(payload)


if __name__ == "__main__":
    unittest.main()
