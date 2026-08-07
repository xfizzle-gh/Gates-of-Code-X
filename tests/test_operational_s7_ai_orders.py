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
from gates_of_codex.operational_ai import (
    find_operational_path,
    operational_graph_authority_present,
    plan_and_issue_operational_orders,
    _build_graph_indexes,
)
from gates_of_codex.operational_capture import (
    advance_site_capture,
    ensure_site_control_state,
    get_site_control_state,
)
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    advance_operational_ticks,
    commit_formation_move_order,
    commit_move_orders,
    commit_move_orders_detailed,
    issue_move_order,
    resolve_strategic_turn_movement,
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
    stable_site_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_ai import StrategicAI


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


def _edge(
    a: str,
    b: str,
    *,
    cost: int = COST_MILLI_UNITY,
    enabled: bool = True,
    bidirectional: bool = True,
    kind: str = "road",
    authority: str = "authored",
    metadata: dict | None = None,
    legacy_crossing_type: str | None = None,
) -> dict:
    na, nb = stable_node_id(a), stable_node_id(b)
    return {
        "edge_id": stable_edge_id(kind if kind != "road" else "corridor", na, nb)
        if kind in {"strait", "ferry", "sea_lane"}
        else stable_edge_id("corridor", na, nb),
        "a": na,
        "b": nb,
        "kind": kind if kind != "road" else "corridor",
        "authority": authority,
        "length_px": 100,
        "base_move_points_milli": COST_MILLI_UNITY,
        "movement_cost_milli": cost,
        "requires_port": False,
        "can_be_blockaded": False,
        "traversal_enabled": enabled,
        "bidirectional": bidirectional,
        "province_ids": [a, b],
        "legacy_crossing_type": legacy_crossing_type,
        "metadata": dict(metadata or {}),
    }


def _site(pid: str) -> dict:
    nid = stable_node_id(pid)
    return {
        "site_id": stable_site_id(pid, "control", "anchor"),
        "display_name": f"{pid} control",
        "kind": "objective",
        "province_id": pid,
        "pixel": [0, 0],
        "route_node_id": nid,
        "control_weight_milli": COST_MILLI_UNITY,
        "capture_threshold_milli": COST_MILLI_UNITY,
        "owner_faction": None,
        "metadata": {},
    }


def _graph(
    *,
    ab_enabled: bool = True,
    ab_bidirectional: bool = True,
    ab_meta: dict | None = None,
    ab_kind: str = "road",
    include_disabled_ac: bool = True,
    ab_cost: int = COST_MILLI_UNITY,
) -> dict:
    edges = [
        _edge(
            "a",
            "b",
            cost=ab_cost,
            enabled=ab_enabled,
            bidirectional=ab_bidirectional,
            kind=ab_kind if ab_kind != "road" else "corridor",
            metadata=ab_meta,
            legacy_crossing_type="strait" if ab_kind == "strait" else None,
        ),
        _edge("b", "c", cost=COST_MILLI_UNITY, enabled=True),
    ]
    if include_disabled_ac:
        edges.append(
            _edge("a", "c", enabled=False, authority="candidate", kind="corridor")
        )
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s7_test",
        "rules": {
            "ticks_per_strategic_turn": 10,
            "capture_hold_ticks": 2,
            "max_friendly_formations_per_node": 3,
        },
        "sites": [_site("a"), _site("b"), _site("c")],
        "nodes": [
            _node("a", pixel=[0, 0]),
            _node("b", pixel=[1000, 0]),
            _node("c", pixel=[2000, 0]),
        ],
        "edges": edges,
        "metadata": {},
    }


def _bn(bid: str, faction: Faction, province: str, fid: str) -> Battalion:
    toe = "toe-nato" if faction == Faction.NATO else "toe-rusa"
    return Battalion(
        battalion_id=bid,
        faction=faction,
        province_id=province,
        formation_id=toe,
        roster=[BattalionRosterEntry("t", 1, category="tank")],
        authorized_roster=[BattalionRosterEntry("t", 1, category="tank")],
        strategic_formation_id=fid,
        movement_remaining=1,
        condition=100,
    )


def _force(fid: str, faction: Faction, province: str, bn: str) -> StrategicFormation:
    toe = "toe-nato" if faction == Faction.NATO else "toe-rusa"
    return StrategicFormation(
        strategic_formation_id=fid,
        display_name=fid,
        faction=faction,
        province_id=province,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=[bn],
        template_formation_id=toe,
        stance=FormationStance.OPERATIONAL.value,
        position=FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(province),
            progress_milli=0,
        ),
    )


def _state(tmp: Path, graph: dict | None = None) -> CampaignState:
    g = graph or _graph()
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / "operational_graph.json"
    path.write_text(json.dumps(g), encoding="utf-8")
    state = CampaignState(
        campaign_name="S7",
        map_id="s7_test",
        map_metadata={
            "operational_graph": str(path.resolve()),
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
            "a": Province("a", "A", owner=Faction.RUSSIA, neighbors=["b"], x=0, y=0),
            "b": Province("b", "B", owner=Faction.NEUTRAL, neighbors=["a", "c"], x=100, y=0),
            "c": Province("c", "C", owner=Faction.NATO, neighbors=["b"], x=200, y=0),
        },
        battalions={
            "bn-r": _bn("bn-r", Faction.RUSSIA, "a", "sf-r"),
            "bn-n": _bn("bn-n", Faction.NATO, "c", "sf-n"),
        },
        strategic_formations={
            "sf-r": _force("sf-r", Faction.RUSSIA, "a", "bn-r"),
            "sf-n": _force("sf-n", Faction.NATO, "c", "bn-n"),
        },
        schema_version=7,
        turn_number=1,
        selected_faction=Faction.RUSSIA,
        current_faction=Faction.RUSSIA,
    )
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    ensure_site_control_state(state)
    # Restore explicit positions after hydrate.
    state.strategic_formations["sf-r"].position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value, node_id=stable_node_id("a"), progress_milli=0
    )
    state.strategic_formations["sf-n"].position = FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value, node_id=stable_node_id("c"), progress_milli=0
    )
    return state


class OperationalS7AIOrdersTests(unittest.TestCase):
    def test_ai_chooses_authored_legal_route(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=1)
            move = next(a for a in actions if a.action == "operational_move")
            force = state.strategic_formations["sf-r"]
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.COMMITTED.value, force.move_order.status)
            self.assertIn(stable_edge_id("corridor", stable_node_id("a"), stable_node_id("b")), force.move_order.path_edge_ids)
            self.assertEqual("operational_move", move.action)
            self.assertEqual(12, FRONTEND_SCHEMA_VERSION)

    def test_disabled_candidate_corridor_not_used(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            force = state.strategic_formations["sf-r"]
            assert force.move_order is not None
            disabled = stable_edge_id(
                "corridor", stable_node_id("a"), stable_node_id("c")
            )
            self.assertNotIn(disabled, force.move_order.path_edge_ids)
            self.assertTrue(any(a.action == "operational_move" for a in actions))

    def test_one_way_edge_direction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(ab_bidirectional=False, include_disabled_ac=False)
            state = _state(Path(temporary), g)
            # Russia at a may use a→b.
            plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            r_order = state.strategic_formations["sf-r"].move_order
            assert r_order is not None
            self.assertEqual(
                [stable_node_id("a"), stable_node_id("b")],
                r_order.path_node_ids[:2],
            )
            # Reverse hop b→a is absent from adjacency.
            _, _, adj = _build_graph_indexes(g)
            hop_dests_from_b = {h.dest for h in adj.get(stable_node_id("b"), [])}
            self.assertNotIn(stable_node_id("a"), hop_dests_from_b)
            hop_dests_from_a = {h.dest for h in adj.get(stable_node_id("a"), [])}
            self.assertIn(stable_node_id("b"), hop_dests_from_a)
            # Pathfinder cannot reverse the one-way edge.
            reverse = find_operational_path(
                start_node=stable_node_id("b"),
                goal_node=stable_node_id("a"),
                adjacency=adj,
            )
            self.assertIsNone(reverse)

    def test_blocked_edge_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(
                Path(temporary),
                _graph(ab_meta={"blocked": True}, include_disabled_ac=False),
            )
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            force = state.strategic_formations["sf-r"]
            # No path off a when ab blocked and no ac.
            self.assertIsNone(force.move_order)
            self.assertTrue(any(a.action == "hold" for a in actions))

    def test_crossing_edge_used_when_legal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(include_disabled_ac=False)
            na, nb = stable_node_id("a"), stable_node_id("b")
            strait_id = stable_edge_id("strait", na, nb)
            for edge in g["edges"]:
                if edge["a"] == na and edge["b"] == nb:
                    edge["kind"] = "strait"
                    edge["authority"] = "authored"
                    edge["legacy_crossing_type"] = "strait"
                    edge["edge_id"] = strait_id
            state = _state(Path(temporary), g)
            plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            order = state.strategic_formations["sf-r"].move_order
            assert order is not None
            self.assertEqual([strait_id], order.path_edge_ids[:1])
            self.assertEqual(na, order.path_node_ids[0])
            self.assertEqual(nb, order.path_node_ids[1])

    def test_crossing_edge_rejected_when_metadata_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(include_disabled_ac=False)
            na, nb = stable_node_id("a"), stable_node_id("b")
            strait_id = stable_edge_id("strait", na, nb)
            for edge in g["edges"]:
                if edge["a"] == na and edge["b"] == nb:
                    edge["kind"] = "strait"
                    edge["authority"] = "authored"
                    edge["legacy_crossing_type"] = "strait"
                    edge["metadata"] = {"blockaded": True}
                    edge["edge_id"] = strait_id
            state = _state(Path(temporary), g)
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            self.assertIsNone(state.strategic_formations["sf-r"].move_order)
            self.assertEqual("no_valid_route", actions[0].details.get("reason"))

    def test_manual_issue_rejects_enabled_candidate_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(include_disabled_ac=False)
            na, nb = stable_node_id("a"), stable_node_id("b")
            # Accidentally enabled candidate corridor.
            edge_id = stable_edge_id("corridor", na, nb)
            for edge in g["edges"]:
                if edge["edge_id"] == edge_id:
                    edge["authority"] = "candidate"
                    edge["kind"] = "corridor"
                    edge["traversal_enabled"] = True
            state = _state(Path(temporary), g)
            with self.assertRaises(ValueError) as ctx:
                issue_move_order(
                    state,
                    "sf-r",
                    path_node_ids=[na, nb],
                    path_edge_ids=[edge_id],
                    order_id="manual-cand",
                )
            self.assertIn("candidate", str(ctx.exception))

    def test_manual_issue_rejects_metadata_blocked_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(ab_meta={"blocked": True}, include_disabled_ac=False)
            state = _state(Path(temporary), g)
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge_id = stable_edge_id("corridor", na, nb)
            with self.assertRaises(ValueError) as ctx:
                issue_move_order(
                    state,
                    "sf-r",
                    path_node_ids=[na, nb],
                    path_edge_ids=[edge_id],
                    order_id="manual-block",
                )
            self.assertIn("blocked", str(ctx.exception))

    def test_entrenched_holds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            state.strategic_formations["sf-r"].stance = FormationStance.ENTRENCHED.value
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            self.assertIsNone(state.strategic_formations["sf-r"].move_order)
            self.assertEqual("hold", actions[0].action)
            self.assertEqual("stance_hold", actions[0].details["reason"])

    def test_refit_resupply_holds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            state.strategic_formations["sf-r"].stance = FormationStance.REFIT_RESUPPLY.value
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            self.assertIsNone(state.strategic_formations["sf-r"].move_order)
            self.assertEqual("stance_hold", actions[0].details["reason"])

    def test_forced_march_rejects_hostile_intermediate_node(self) -> None:
        """Enemy on intermediate b; farther c is hostile objective — FM must hold."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(include_disabled_ac=False))
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            # Enemy on intermediate node b.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-n"].province_id = "b"
            state.battalions["bn-n"].province_id = "b"
            state.provinces["b"].owner = Faction.NATO
            state.provinces["c"].owner = Faction.NATO
            state.strategic_formations["sf-r"].stance = FormationStance.FORCED_MARCH.value
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            order = state.strategic_formations["sf-r"].move_order
            # No legal non-hostile path through b → hold or reject without hostile nodes.
            if order is None:
                self.assertIn(actions[0].action, {"hold", "reject"})
                self.assertIn(
                    actions[0].details.get("reason"),
                    {"no_valid_route", "forced_march_hostile_path"},
                )
            else:
                self.assertEqual(FormationStance.FORCED_MARCH.value, order.locked_stance)
                for node_id in order.path_node_ids[1:]:
                    self.assertNotEqual(nb, node_id)
                    self.assertFalse(
                        any(
                            f.faction == Faction.NATO
                            for f in state.strategic_formations.values()
                            if f.position
                            and f.position.mode == PositionMode.AT_NODE.value
                            and f.position.node_id == node_id
                        )
                    )

    def test_forced_march_takes_safe_route_not_hostile_branch(self) -> None:
        """With a safe alternate destination, FM commits a path with zero hostiles."""
        with tempfile.TemporaryDirectory() as temporary:
            # Graph: a-b (enemy on b), a-d safe friendly frontier-ish empty.
            g = _graph(include_disabled_ac=False)
            nd = stable_node_id("d")
            g["nodes"].append(_node("d", pixel=[0, 1000]))
            g["sites"].append(_site("d"))
            g["edges"].append(_edge("a", "d", cost=COST_MILLI_UNITY, enabled=True))
            state = _state(Path(temporary), g)
            state.provinces["d"] = Province(
                "d", "D", owner=Faction.NEUTRAL, neighbors=["a"], x=0, y=100
            )
            state.provinces["a"].neighbors = ["b", "d"]
            # Enemy on b blocks a→b→c forced-march attack path.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id("b"),
                progress_milli=0,
            )
            state.strategic_formations["sf-n"].province_id = "b"
            state.battalions["bn-n"].province_id = "b"
            state.provinces["b"].owner = Faction.NATO
            state.provinces["c"].owner = Faction.NATO
            state.strategic_formations["sf-r"].stance = FormationStance.FORCED_MARCH.value
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            order = state.strategic_formations["sf-r"].move_order
            assert order is not None
            self.assertEqual(FormationStance.FORCED_MARCH.value, order.locked_stance)
            self.assertEqual("operational_move", actions[0].action)
            self.assertNotIn(stable_node_id("b"), order.path_node_ids[1:])
            self.assertEqual(nd, order.path_node_ids[-1])
            # Player commit path agrees: cannot commit a→b with FM.
            edge_ab = stable_edge_id(
                "corridor", stable_node_id("a"), stable_node_id("b")
            )
            # Clear and try illegal FM path via shared commit validator.
            state.strategic_formations["sf-r"].move_order = None
            issue_move_order(
                state,
                "sf-r",
                path_node_ids=[stable_node_id("a"), stable_node_id("b")],
                path_edge_ids=[edge_ab],
                order_id="fm-illegal",
            )
            with self.assertRaises(ValueError) as ctx:
                commit_formation_move_order(
                    state,
                    "sf-r",
                    locked_stance=FormationStance.FORCED_MARCH.value,
                )
            self.assertEqual("forced_march_hostile_path", str(ctx.exception))

    def test_destination_capacity_reservations_stable_reject(self) -> None:
        """Four movers target one empty node with cap 3: exactly 3 commit, 1 rejects."""
        with tempfile.TemporaryDirectory() as temporary:
            # Single legal hop a→b only (no alternate destination).
            g = _graph(include_disabled_ac=False)
            nb, nc = stable_node_id("b"), stable_node_id("c")
            g["edges"] = [
                e
                for e in g["edges"]
                if not (
                    {e["a"], e["b"]} == {nb, nc}
                )
            ]
            state = _state(Path(temporary), g)
            del state.strategic_formations["sf-n"]
            del state.battalions["bn-n"]
            # Three more Russia formations at a, all operational.
            for i in range(3):
                bid, fid = f"bn-m{i}", f"sf-m{i}"
                state.battalions[bid] = _bn(bid, Faction.RUSSIA, "a", fid)
                state.strategic_formations[fid] = _force(fid, Faction.RUSSIA, "a", bid)
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value,
                    node_id=stable_node_id("a"),
                    progress_milli=0,
                )
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            committed = [
                a
                for a in actions
                if a.action == "operational_move" and a.details.get("goal_node") == nb
            ]
            rejected = [
                a for a in actions if a.details.get("reason") == "destination_capacity"
            ]
            self.assertEqual(3, len(committed), msg=[(a.action, a.details) for a in actions])
            self.assertEqual(1, len(rejected), msg=[(a.action, a.details) for a in actions])
            self.assertEqual("destination_capacity", rejected[0].details["reason"])
            claiming = [
                f
                for f in state.strategic_formations.values()
                if f.move_order is not None
                and f.move_order.status == MoveOrderStatus.COMMITTED.value
                and f.move_order.path_node_ids
                and f.move_order.path_node_ids[-1] == nb
            ]
            self.assertEqual(3, len(claiming))

    def test_enemy_node_entry_creates_pending_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(include_disabled_ac=False, ab_cost=1000))
            # NATO holds b; Russia attacks toward b.
            state.strategic_formations["sf-n"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id("b"),
                progress_milli=0,
            )
            state.strategic_formations["sf-n"].province_id = "b"
            state.battalions["bn-n"].province_id = "b"
            state.provinces["b"].owner = Faction.NATO
            plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            order = state.strategic_formations["sf-r"].move_order
            assert order is not None
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual("node_contact", state.pending_battle.encounter_kind)

    def test_swept_edge_interception_via_normal_s6_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=2000, include_disabled_ac=False))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            # Exact opposing intervals on the edge (manual orders; S6 path).
            for fid, face, prog, path_nodes in (
                ("sf-r", nb, 200, [na, nb]),
                ("sf-n", na, 200, [nb, na]),
            ):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
                issue_move_order(
                    state,
                    fid,
                    path_node_ids=path_nodes,
                    path_edge_ids=[edge],
                    order_id=f"ord-{fid}",
                )
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id=edge,
                    progress_milli=prog,
                    facing_node_id=face,
                )
            commit_move_orders(state)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertEqual("edge_cross", report.get("swept_kind"))
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual("edge_cross", state.pending_battle.encounter_kind)
            self.assertEqual(edge, state.pending_battle.encounter_edge_id)

    def test_control_site_capture_two_uncontested_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000, include_disabled_ac=False))
            del state.strategic_formations["sf-n"]
            del state.battalions["bn-n"]
            # Only goal is empty neutral b (c is friendly-owned so not hostile).
            state.provinces["c"].owner = Faction.RUSSIA
            site_id = stable_site_id("b", "control", "anchor")
            ensure_site_control_state(state)
            initial_controller = get_site_control_state(state)[site_id]["controller_faction"]
            plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            order = state.strategic_formations["sf-r"].move_order
            assert order is not None
            self.assertEqual(stable_node_id("b"), order.path_node_ids[-1])
            activate_committed_orders(state)
            # Arrival tick also runs one capture advance (tick 1 of 2).
            advance_operational_tick(state)
            self.assertIsNone(state.pending_battle)
            force = state.strategic_formations["sf-r"]
            assert force.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
            self.assertEqual(stable_node_id("b"), force.position.node_id)
            after_tick1 = get_site_control_state(state)[site_id]
            self.assertEqual(initial_controller, after_tick1["controller_faction"])
            self.assertEqual(1, int(after_tick1["progress_ticks"]))
            # Second uncontested capture tick flips controller.
            advance_site_capture(state)
            after_tick2 = get_site_control_state(state)[site_id]
            self.assertEqual(Faction.RUSSIA.value, after_tick2["controller_faction"])
            self.assertNotEqual(initial_controller, after_tick2["controller_faction"])

    def test_no_route_means_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(
                Path(temporary),
                _graph(ab_enabled=False, include_disabled_ac=False),
            )
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            self.assertIsNone(state.strategic_formations["sf-r"].move_order)
            self.assertEqual("no_valid_route", actions[0].details.get("reason"))

    def test_insertion_order_independence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state_a = _state(Path(temporary) / "a")
            state_b = _state(Path(temporary) / "b")
            # Shuffle strategic_formations dict insertion by rebuild.
            items = list(state_b.strategic_formations.items())
            state_b.strategic_formations = dict(reversed(items))
            act_a = plan_and_issue_operational_orders(state_a, Faction.RUSSIA, seed=7)
            act_b = plan_and_issue_operational_orders(state_b, Faction.RUSSIA, seed=7)
            oa = state_a.strategic_formations["sf-r"].move_order
            ob = state_b.strategic_formations["sf-r"].move_order
            self.assertEqual(
                None if oa is None else (oa.path_node_ids, oa.path_edge_ids, oa.status),
                None if ob is None else (ob.path_node_ids, ob.path_edge_ids, ob.status),
            )
            self.assertEqual(
                [(a.action, a.details.get("goal_node"), a.details.get("path_edge_ids")) for a in act_a],
                [(a.action, a.details.get("goal_node"), a.details.get("path_edge_ids")) for a in act_b],
            )

    def test_repeated_run_byte_identical_orders_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = _state(Path(temporary))
            s1 = copy.deepcopy(base)
            s2 = copy.deepcopy(base)
            plan_and_issue_operational_orders(s1, Faction.RUSSIA, seed=3)
            plan_and_issue_operational_orders(s2, Faction.RUSSIA, seed=3)
            self.assertEqual(s1.to_dict(), s2.to_dict())

    def test_save_load_during_committed_ai_movement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state(root)
            plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            path = root / "save.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
            o1 = state.strategic_formations["sf-r"].move_order
            o2 = loaded.strategic_formations["sf-r"].move_order
            assert o1 is not None and o2 is not None
            self.assertEqual(o1.path_node_ids, o2.path_node_ids)
            self.assertEqual(o1.path_edge_ids, o2.path_edge_ids)
            self.assertEqual(o1.status, o2.status)
            self.assertEqual(o1.locked_stance, o2.locked_stance)

    def test_no_legacy_teleport_when_operational_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            self.assertTrue(operational_graph_authority_present(state))
            before_r = state.strategic_formations["sf-r"].province_id
            before_bn = state.battalions["bn-r"].province_id
            actions = StrategicAI(state, random_seed=0).take_turn(Faction.RUSSIA)
            legacy = {"move", "capture", "attack"}
            self.assertFalse(any(a.action in legacy for a in actions))
            self.assertTrue(
                all(
                    a.action
                    in {
                        "operational_move",
                        "hold",
                        "hold_locked_order",
                        "reject",
                        "hold_pending_battle",
                        "economy",
                        "construct",
                    }
                    for a in actions
                )
            )
            self.assertEqual(before_r, state.strategic_formations["sf-r"].province_id)
            self.assertEqual(before_bn, state.battalions["bn-r"].province_id)

    def test_legacy_ai_without_graph(self) -> None:
        state = CampaignState(
            campaign_name="legacy",
            map_id="x",
            map_metadata={},
            factions={
                Faction.NATO.value: FactionState(Faction.NATO, resources=100),
                Faction.RUSSIA.value: FactionState(Faction.RUSSIA, resources=100),
            },
            formations={
                "toe": Formation(
                    formation_id="toe",
                    display_name="T",
                    faction=Faction.RUSSIA,
                    nation="rus",
                    kind=FormationKind.ARMORED_BRIGADE,
                )
            },
            provinces={
                "a": Province("a", "A", owner=Faction.RUSSIA, neighbors=["b"], x=0, y=0),
                "b": Province("b", "B", owner=Faction.NEUTRAL, neighbors=["a"], x=1, y=0),
            },
            battalions={
                "bn": Battalion(
                    battalion_id="bn",
                    faction=Faction.RUSSIA,
                    province_id="a",
                    formation_id="toe",
                    roster=[BattalionRosterEntry("t", 1, category="tank")],
                    authorized_roster=[BattalionRosterEntry("t", 1, category="tank")],
                    movement_remaining=1,
                    condition=100,
                )
            },
            schema_version=7,
            turn_number=1,
        )
        ensure_strategic_formations(state)
        self.assertFalse(operational_graph_authority_present(state))
        actions = StrategicAI(state, random_seed=0).take_turn(Faction.RUSSIA)
        self.assertTrue(any(a.action in {"move", "capture", "hold", "attack"} for a in actions))

    def test_frontend_schema_remains_12(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary))
            plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            snap = build_frontend_snapshot(state)
            self.assertEqual(12, snap["schema_version"])

    def test_strategic_ai_run_end_to_end_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000, include_disabled_ac=False))
            del state.strategic_formations["sf-n"]
            del state.battalions["bn-n"]
            state.provinces["c"].owner = Faction.RUSSIA
            StrategicAI(state, random_seed=0).take_turn(Faction.RUSSIA)
            order = state.strategic_formations["sf-r"].move_order
            assert order is not None
            self.assertEqual(MoveOrderStatus.COMMITTED.value, order.status)
            self.assertEqual(stable_node_id("b"), order.path_node_ids[-1])
            report = resolve_strategic_turn_movement(state)
            self.assertEqual(1, report.get("activated"))
            force = state.strategic_formations["sf-r"]
            assert force.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
            self.assertEqual(stable_node_id("b"), force.position.node_id)
            self.assertEqual(0, force.position.progress_milli)
            self.assertEqual("b", force.province_id)
            self.assertEqual("b", state.battalions["bn-r"].province_id)
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.COMPLETED.value, force.move_order.status)

    def test_on_edge_ai_continues_current_edge_not_branch_from_origin(self) -> None:
        """ON_EDGE at 250 facing B: must keep A-B first; may not branch via A to D."""
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(ab_cost=1000, include_disabled_ac=False)
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            nd = stable_node_id("d")
            edge_ab = stable_edge_id("corridor", na, nb)
            g["nodes"].append(_node("d", pixel=[0, 1000]))
            g["sites"].append(_site("d"))
            g["edges"].append(_edge("a", "d", cost=500, enabled=True))
            state = _state(Path(temporary), g)
            state.provinces["d"] = Province(
                "d", "D", owner=Faction.NEUTRAL, neighbors=["a"], x=0, y=100
            )
            state.provinces["a"].neighbors = ["b", "d"]
            del state.strategic_formations["sf-n"]
            del state.battalions["bn-n"]
            state.provinces["c"].owner = Faction.NATO
            # Attractive short objective d via A, and objective beyond B (c).
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=250,
                facing_node_id=nb,
            )
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            order = state.strategic_formations["sf-r"].move_order
            assert order is not None, actions
            self.assertEqual(MoveOrderStatus.COMMITTED.value, order.status)
            self.assertEqual(edge_ab, order.path_edge_ids[0])
            self.assertEqual([na, nb], order.path_node_ids[:2])
            # Must not start with a-d branch.
            edge_ad = stable_edge_id("corridor", na, nd)
            self.assertNotEqual(edge_ad, order.path_edge_ids[0])
            self.assertNotIn(nd, order.path_node_ids[:2])
            # Progress preserved before resolution.
            pos = state.strategic_formations["sf-r"].position
            assert pos is not None
            self.assertEqual(250, pos.progress_milli)
            self.assertEqual(PositionMode.ON_EDGE.value, pos.mode)
            self.assertEqual(edge_ab, pos.edge_id)
            activate_committed_orders(state)
            # One tick from 250 with cost 1000 → progress 250+1000 clamped/arrive.
            report = advance_operational_tick(state)
            self.assertTrue(report["advanced"])
            force = state.strategic_formations["sf-r"]
            assert force.move_order is not None
            self.assertNotEqual(MoveOrderStatus.BLOCKED.value, force.move_order.status)
            # Advanced from 250: either still on edge past 250 or arrived at B.
            assert force.position is not None
            if force.position.mode == PositionMode.ON_EDGE.value:
                self.assertGreater(force.position.progress_milli, 250)
            else:
                self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
                self.assertEqual(nb, force.position.node_id)

    def test_on_edge_no_valid_forward_continuation_holds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # One-way edge already traversed direction exhausted: facing B but
            # B has no outbound edges and is already owned friendly with no goals.
            g = _graph(ab_bidirectional=False, include_disabled_ac=False, ab_cost=1000)
            # Remove b-c so nothing beyond B.
            nb, nc = stable_node_id("b"), stable_node_id("c")
            g["edges"] = [
                e for e in g["edges"] if {e["a"], e["b"]} != {nb, nc}
            ]
            state = _state(Path(temporary), g)
            del state.strategic_formations["sf-n"]
            del state.battalions["bn-n"]
            state.provinces["b"].owner = Faction.RUSSIA
            state.provinces["c"].owner = Faction.RUSSIA
            na = stable_node_id("a")
            edge_ab = stable_edge_id("corridor", na, nb)
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=250,
                facing_node_id=nb,
            )
            # Completing edge to friendly B is still a valid continuation.
            # Block that by making facing reverse (illegal one-way) — use facing
            # that cannot hop: put force facing A on one-way a→b (reverse illegal).
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=250,
                facing_node_id=na,  # reverse of one-way
            )
            actions = plan_and_issue_operational_orders(state, Faction.RUSSIA, seed=0)
            self.assertIsNone(state.strategic_formations["sf-r"].move_order)
            self.assertIn(
                actions[0].details.get("reason"),
                {
                    "no_valid_forward_continuation",
                    "no_valid_route",
                    "on_edge_desync",
                    "one_way_reverse",
                },
            )
            self.assertEqual(250, state.strategic_formations["sf-r"].position.progress_milli)

    def test_manual_on_edge_draft_must_include_current_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(include_disabled_ac=False)
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            nd = stable_node_id("d")
            edge_ab = stable_edge_id("corridor", na, nb)
            g["nodes"].append(_node("d", pixel=[0, 1000]))
            g["edges"].append(_edge("a", "d", enabled=True))
            state = _state(Path(temporary), g)
            state.provinces["d"] = Province(
                "d", "D", owner=Faction.NEUTRAL, neighbors=["a"], x=0, y=100
            )
            state.strategic_formations["sf-r"].position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge_ab,
                progress_milli=250,
                facing_node_id=nb,
            )
            edge_ad = stable_edge_id("corridor", na, nd)
            with self.assertRaises(ValueError) as ctx:
                issue_move_order(
                    state,
                    "sf-r",
                    path_node_ids=[na, nd],
                    path_edge_ids=[edge_ad],
                    order_id="branch-skip",
                )
            self.assertIn(str(ctx.exception), {"on_edge_desync", "invalid_path"})

    def test_two_phase_commit_invalid_draft_does_not_consume_capacity(self) -> None:
        """cap=1: valid lower-ID commits; invalid higher-ID rejected for legality."""
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph(include_disabled_ac=False)
            g["rules"]["max_friendly_formations_per_node"] = 1
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge_ab = stable_edge_id("corridor", na, nb)
            # Enabled candidate edge for invalid draft (same endpoints, different id).
            bad_edge = {
                "edge_id": "op-edge-bad-candidate",
                "a": na,
                "b": nb,
                "kind": "corridor",
                "authority": "candidate",
                "length_px": 100,
                "base_move_points_milli": COST_MILLI_UNITY,
                "movement_cost_milli": COST_MILLI_UNITY,
                "requires_port": False,
                "can_be_blockaded": False,
                "traversal_enabled": True,
                "bidirectional": True,
                "province_ids": ["a", "b"],
                "legacy_crossing_type": None,
                "metadata": {},
            }
            g["edges"].append(bad_edge)
            state = _state(Path(temporary), g)
            del state.strategic_formations["sf-n"]
            del state.battalions["bn-n"]
            # sf-a valid (lower id), sf-z invalid candidate path (higher id).
            state.battalions["bn-a"] = _bn("bn-a", Faction.RUSSIA, "a", "sf-a")
            state.strategic_formations["sf-a"] = _force("sf-a", Faction.RUSSIA, "a", "bn-a")
            state.battalions["bn-z"] = _bn("bn-z", Faction.RUSSIA, "a", "sf-z")
            state.strategic_formations["sf-z"] = _force("sf-z", Faction.RUSSIA, "a", "bn-z")
            for fid in ("sf-a", "sf-z", "sf-r"):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value, node_id=na, progress_milli=0
                )
            # Remove sf-r from contention.
            del state.strategic_formations["sf-r"]
            del state.battalions["bn-r"]
            issue_move_order(
                state, "sf-a", path_node_ids=[na, nb], path_edge_ids=[edge_ab], order_id="ok"
            )
            # Bypass issue validation by planting an illegal draft directly.
            from gates_of_codex.operational_schema import OperationalMoveOrder

            state.strategic_formations["sf-z"].move_order = OperationalMoveOrder(
                order_id="bad",
                formation_id="sf-z",
                path_node_ids=[na, nb],
                path_edge_ids=["op-edge-bad-candidate"],
                issued_tick=0,
                status=MoveOrderStatus.DRAFT.value,
            )
            # Reverse insertion order of dict.
            items = list(state.strategic_formations.items())
            state.strategic_formations = dict(reversed(items))
            report = commit_move_orders_detailed(state, faction="rusa")
            self.assertEqual(["sf-a"], report["committed"])
            reasons = {r["formation_id"]: r["reason"] for r in report["rejected"]}
            self.assertEqual("candidate_edge", reasons.get("sf-z"))
            self.assertEqual(
                MoveOrderStatus.COMMITTED.value,
                state.strategic_formations["sf-a"].move_order.status,
            )
            self.assertEqual(
                MoveOrderStatus.BLOCKED.value,
                state.strategic_formations["sf-z"].move_order.status,
            )
            # Insertion order independence.
            state2 = _state(Path(temporary) / "b", g)
            del state2.strategic_formations["sf-n"]
            del state2.battalions["bn-n"]
            state2.battalions["bn-a"] = _bn("bn-a", Faction.RUSSIA, "a", "sf-a")
            state2.strategic_formations["sf-a"] = _force("sf-a", Faction.RUSSIA, "a", "bn-a")
            state2.battalions["bn-z"] = _bn("bn-z", Faction.RUSSIA, "a", "sf-z")
            state2.strategic_formations["sf-z"] = _force("sf-z", Faction.RUSSIA, "a", "bn-z")
            del state2.strategic_formations["sf-r"]
            del state2.battalions["bn-r"]
            for fid in ("sf-a", "sf-z"):
                state2.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value, node_id=na, progress_milli=0
                )
            issue_move_order(
                state2, "sf-a", path_node_ids=[na, nb], path_edge_ids=[edge_ab], order_id="ok"
            )
            state2.strategic_formations["sf-z"].move_order = OperationalMoveOrder(
                order_id="bad",
                formation_id="sf-z",
                path_node_ids=[na, nb],
                path_edge_ids=["op-edge-bad-candidate"],
                issued_tick=0,
                status=MoveOrderStatus.DRAFT.value,
            )
            report2 = commit_move_orders_detailed(state2, faction="rusa")
            self.assertEqual(report["committed"], report2["committed"])
            self.assertEqual(
                {r["formation_id"]: r["reason"] for r in report["rejected"]},
                {r["formation_id"]: r["reason"] for r in report2["rejected"]},
            )


if __name__ == "__main__":
    unittest.main()
