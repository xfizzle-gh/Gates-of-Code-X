from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.frontend_commands import apply_frontend_commands
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
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    advance_operational_ticks,
    cancel_move_order,
    commit_move_orders,
    ensure_move_orders,
    issue_move_order,
    resolve_strategic_turn_movement,
)
from gates_of_codex.operational_position import ensure_operational_positions, province_anchor_position
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    FormationOperationalPosition,
    MoveOrderStatus,
    OperationalMoveOrder,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign


def _node(province_id: str, *, pixel: list[int], suffix: str = "anchor") -> dict:
    return {
        "node_id": stable_node_id(province_id, suffix),
        "display_name": f"{province_id} {suffix}",
        "pixel": pixel,
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
    cost: int = COST_MILLI_UNITY,
    enabled: bool = True,
    bidirectional: bool = True,
) -> dict:
    na = stable_node_id(a, "anchor")
    nb = stable_node_id(b, "anchor")
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
        "traversal_enabled": enabled,
        "bidirectional": bidirectional,
        "province_ids": [a, b],
        "legacy_crossing_type": None,
        "metadata": {},
    }


def _graph_three_provinces(*, ab_cost: int = COST_MILLI_UNITY) -> dict:
    return {
        "schema": "gates-of-codex.operational-graph",
        "schema_version": 2,
        "map_id": "s3_test",
        "rules": {"ticks_per_strategic_turn": 10},
        "sites": [],
        "nodes": [
            _node("a", pixel=[0, 0]),
            _node("b", pixel=[100, 0]),
            _node("c", pixel=[200, 0]),
        ],
        "edges": [
            _edge("a", "b", cost=ab_cost, enabled=True),
            _edge("b", "c", cost=COST_MILLI_UNITY, enabled=True),
            _edge("a", "c", cost=COST_MILLI_UNITY, enabled=False),  # candidate-like disabled
        ],
        "metadata": {},
    }


def _state_with_graph(graph: dict, tmp: Path) -> CampaignState:
    tmp.mkdir(parents=True, exist_ok=True)
    graph_path = tmp / "operational_graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    state = CampaignState(
        campaign_name="S3",
        map_id="s3_test",
        map_metadata={"operational_graph": str(graph_path.resolve())},
        factions={
            Faction.NATO.value: FactionState(Faction.NATO, resources=500, is_human_controlled=True)
        },
        formations={
            "toe": Formation(
                formation_id="toe",
                display_name="T",
                faction=Faction.NATO,
                nation="usa",
                kind=FormationKind.ARMORED_BRIGADE,
            )
        },
        provinces={
            "a": Province("a", "A", owner=Faction.NATO, neighbors=["b"], x=0, y=0),
            "b": Province("b", "B", owner=Faction.NATO, neighbors=["a", "c"], x=100, y=0),
            "c": Province("c", "C", owner=Faction.NATO, neighbors=["b"], x=200, y=0),
        },
        battalions={
            "bn-1": Battalion(
                battalion_id="bn-1",
                faction=Faction.NATO,
                province_id="a",
                formation_id="toe",
                roster=[BattalionRosterEntry("tank(nato)", 1, category="tank")],
                authorized_roster=[BattalionRosterEntry("tank(nato)", 1, category="tank")],
                is_player_controlled=True,
            )
        },
        schema_version=6,
        turn_number=1,
    )
    ensure_strategic_formations(state)
    ensure_operational_positions(state)
    return state


class OperationalS3MovementTests(unittest.TestCase):
    def test_issue_commit_tick_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na = stable_node_id("a")
            nb = stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            order = issue_move_order(
                state,
                force_id,
                path_node_ids=[na, nb],
                path_edge_ids=[edge],
            )
            self.assertEqual(MoveOrderStatus.DRAFT.value, order.status)
            commit_move_orders(state)
            force = state.strategic_formations[force_id]
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.COMMITTED.value, force.move_order.status)
            activate_committed_orders(state)
            self.assertEqual(MoveOrderStatus.ACTIVE.value, force.move_order.status)

            # cost 1000, base 1000 → one tick completes the edge
            report = advance_operational_tick(state)
            self.assertTrue(report["advanced"])
            force = state.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
            self.assertEqual(nb, force.position.node_id)
            self.assertEqual("b", force.province_id)
            self.assertEqual("b", state.battalions["bn-1"].province_id)
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.COMPLETED.value, force.move_order.status)

    def test_mid_edge_progress_and_display_pixel(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            # cost 2000 → first tick reaches progress 500
            state = _state_with_graph(
                _graph_three_provinces(ab_cost=2000), Path(temporary)
            )
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            force = state.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(PositionMode.ON_EDGE.value, force.position.mode)
            self.assertEqual(500, force.position.progress_milli)
            # Origin province until destination node arrival.
            self.assertEqual("a", force.province_id)
            self.assertEqual("a", state.battalions["bn-1"].province_id)
            snapshot = build_frontend_snapshot(state)
            row = next(r for r in snapshot["strategic_formations"] if r["id"] == force_id)
            self.assertEqual([50, 0], row["display_pixel"])
            self.assertEqual(MoveOrderStatus.ACTIVE.value, row["move_order"]["status"])
            self.assertEqual("a", row["province_id"])
            self.assertEqual(13, snapshot["schema_version"])
            self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])

    def test_multi_edge_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            e1 = stable_edge_id("corridor", na, nb)
            e2 = stable_edge_id("corridor", nb, nc)
            issue_move_order(
                state, force_id, path_node_ids=[na, nb, nc], path_edge_ids=[e1, e2]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)  # a→b
            force = state.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(nb, force.position.node_id)
            advance_operational_tick(state)  # b→c
            force = state.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(nc, force.position.node_id)
            self.assertEqual("c", force.province_id)
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.COMPLETED.value, force.move_order.status)

    def test_batch_ticks_match_single(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph_three_provinces(ab_cost=5000)
            state_a = _state_with_graph(g, Path(temporary) / "a")
            state_b = _state_with_graph(g, Path(temporary) / "b")
            for state in (state_a, state_b):
                fid = next(iter(state.strategic_formations))
                na, nb = stable_node_id("a"), stable_node_id("b")
                edge = stable_edge_id("corridor", na, nb)
                issue_move_order(state, fid, path_node_ids=[na, nb], path_edge_ids=[edge])
                commit_move_orders(state)
                activate_committed_orders(state)
            for _ in range(5):
                advance_operational_tick(state_a)
            advance_operational_ticks(state_b, 5)
            fa = next(iter(state_a.strategic_formations.values()))
            fb = next(iter(state_b.strategic_formations.values()))
            self.assertEqual(fa.position, fb.position)
            self.assertEqual(fa.move_order.status if fa.move_order else None, fb.move_order.status if fb.move_order else None)

    def test_rejects_disabled_candidate_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na, nc = stable_node_id("a"), stable_node_id("c")
            disabled = stable_edge_id("corridor", na, nc)
            with self.assertRaises(ValueError):
                issue_move_order(
                    state, force_id, path_node_ids=[na, nc], path_edge_ids=[disabled]
                )

    def test_legacy_adjacency_move_still_works(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            engine = CampaignEngine(state)
            engine.move_or_attack("bn-1", "b")
            force = next(iter(state.strategic_formations.values()))
            self.assertEqual("b", force.province_id)
            assert force.position is not None
            self.assertEqual(stable_node_id("b"), force.position.node_id)

    def test_no_ownership_flip_on_graph_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            state.provinces["b"].owner = Faction.NEUTRAL
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            self.assertEqual(Faction.NEUTRAL, state.provinces["b"].owner)

    def test_round_resolve_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            report = resolve_strategic_turn_movement(state)
            self.assertTrue(report["resolved"])
            force = state.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(nb, force.position.node_id)

    def test_end_turn_round_runs_ticks_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            # Only NATO active → every end_turn is a full round.
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            engine = CampaignEngine(state)
            engine.end_turn()
            force = state.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(nb, force.position.node_id)
            self.assertEqual(2, state.turn_number)

    def test_manual_commit_then_end_turn_activates_and_resolves(self) -> None:
        """issue → manual commit → end turn → activates/moves; not stuck committed."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            self.assertEqual(1, state.turn_number)
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            commit_move_orders(state)
            force = state.strategic_formations[force_id]
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.COMMITTED.value, force.move_order.status)
            self.assertEqual(1, force.move_order.committed_turn)
            CampaignEngine(state).end_turn()
            force = state.strategic_formations[force_id]
            assert force.move_order is not None
            self.assertNotEqual(
                MoveOrderStatus.COMMITTED.value,
                force.move_order.status,
                "order must not remain permanently committed after end_turn",
            )
            self.assertEqual(MoveOrderStatus.COMPLETED.value, force.move_order.status)
            assert force.position is not None
            self.assertEqual(nb, force.position.node_id)
            self.assertEqual("b", force.province_id)
            self.assertEqual(2, state.turn_number)

    def test_save_load_mid_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state_with_graph(_graph_three_provinces(ab_cost=2000), root)
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            path = root / "campaign.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            force = reloaded.strategic_formations[force_id]
            assert force.position is not None
            self.assertEqual(PositionMode.ON_EDGE.value, force.position.mode)
            self.assertEqual(500, force.position.progress_milli)
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.ACTIVE.value, force.move_order.status)

    def test_frontend_command_issue_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = _state_with_graph(_graph_three_provinces(), root)
            campaign = root / "campaign.json"
            save_campaign(state, campaign)
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            result = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "issue_move_order",
                        "formation": force_id,
                        "path_node_ids": [na, nb],
                        "path_edge_ids": [edge],
                    }
                ],
            )
            self.assertTrue(result["ok"])
            reloaded = load_campaign(campaign)
            force = reloaded.strategic_formations[force_id]
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.DRAFT.value, force.move_order.status)

    def test_committed_orders_are_locked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            commit_move_orders(state)
            with self.assertRaises(ValueError):
                cancel_move_order(state, force_id)
            with self.assertRaises(ValueError):
                issue_move_order(
                    state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge]
                )
            activate_committed_orders(state)
            with self.assertRaises(ValueError):
                cancel_move_order(state, force_id)
            with self.assertRaises(ValueError):
                issue_move_order(
                    state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge]
                )

    def test_desync_blocks_not_completes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            force = state.strategic_formations[force_id]
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            edge_ab = stable_edge_id("corridor", na, nb)
            # Order says a→b but formation is at c (desync).
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nc, progress_milli=0
            )
            force.province_id = "c"
            force.move_order = OperationalMoveOrder(
                order_id="ord-desync",
                formation_id=force_id,
                path_node_ids=[na, nb],
                path_edge_ids=[edge_ab],
                status=MoveOrderStatus.ACTIVE.value,
                committed_turn=1,
                locked_stance="operational",
            )
            advance_operational_tick(state)
            force = state.strategic_formations[force_id]
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, force.move_order.status)
            assert force.position is not None
            self.assertEqual(nc, force.position.node_id)

    def test_ensure_move_orders_blocks_stale_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            force = state.strategic_formations[force_id]
            force.move_order = OperationalMoveOrder(
                order_id="ord-stale",
                formation_id=force_id,
                path_node_ids=["missing-node", stable_node_id("b")],
                path_edge_ids=["missing-edge"],
                status=MoveOrderStatus.DRAFT.value,
            )
            report = ensure_move_orders(state)
            self.assertTrue(report["validated"])
            self.assertIn(force_id, report["blocked"])
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, force.move_order.status)
            # Rejected draft → blocked with neither commitment field (schema-valid).
            self.assertIsNone(force.move_order.committed_turn)
            self.assertIsNone(force.move_order.locked_stance)
            path = Path(temporary) / "blocked_draft.json"
            save_campaign(state, path)
            reloaded = load_campaign(path)
            blocked = reloaded.strategic_formations[force_id].move_order
            assert blocked is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, blocked.status)
            self.assertIsNone(blocked.committed_turn)
            self.assertIsNone(blocked.locked_stance)

    def test_legacy_move_rejects_locked_operational_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            commit_move_orders(state)
            engine = CampaignEngine(state)
            with self.assertRaises(ValueError):
                engine.move_or_attack("bn-1", "b")
            activate_committed_orders(state)
            with self.assertRaises(ValueError):
                engine.move_or_attack("bn-1", "b")

    def test_ensure_move_orders_preserves_when_graph_missing(self) -> None:
        state = CampaignState(
            campaign_name="nog",
            map_id="custom",
            factions={Faction.NATO.value: FactionState(Faction.NATO, resources=1)},
            provinces={"a": Province("a", "A", owner=Faction.NATO, neighbors=[], x=0, y=0)},
            battalions={
                "bn": Battalion(
                    battalion_id="bn",
                    faction=Faction.NATO,
                    province_id="a",
                    roster=[BattalionRosterEntry("x", 1)],
                )
            },
            schema_version=6,
        )
        ensure_strategic_formations(state)
        force = next(iter(state.strategic_formations.values()))
        force.move_order = OperationalMoveOrder(
            order_id="ord-keep",
            formation_id=force.strategic_formation_id,
            path_node_ids=["x", "y"],
            path_edge_ids=["e"],
            status=MoveOrderStatus.ACTIVE.value,
            committed_turn=1,
            locked_stance="operational",
        )
        before = force.move_order
        report = ensure_move_orders(state)
        self.assertFalse(report["validated"])
        self.assertIs(before, force.move_order)
        self.assertEqual(MoveOrderStatus.ACTIVE.value, force.move_order.status)

    def test_commit_rejects_invalid_stance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state_with_graph(_graph_three_provinces(), Path(temporary))
            force_id = next(iter(state.strategic_formations))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(state, force_id, path_node_ids=[na, nb], path_edge_ids=[edge])
            with self.assertRaises(ValueError):
                commit_move_orders(state, locked_stance="standard")

    def test_one_way_edge_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            g = _graph_three_provinces()
            # Make a→b one-way only.
            for edge in g["edges"]:
                if set(edge["province_ids"]) == {"a", "b"}:
                    edge["bidirectional"] = False
                    edge["a"] = stable_node_id("a")
                    edge["b"] = stable_node_id("b")
            state = _state_with_graph(g, Path(temporary))
            force_id = next(iter(state.strategic_formations))
            # Place at b and try reverse b→a
            force = state.strategic_formations[force_id]
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id("b"),
                progress_milli=0,
            )
            force.province_id = "b"
            state.battalions["bn-1"].province_id = "b"
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            with self.assertRaises(ValueError):
                issue_move_order(
                    state, force_id, path_node_ids=[nb, na], path_edge_ids=[edge]
                )

    def test_without_graph_resolve_skips(self) -> None:
        state = CampaignState(
            campaign_name="nog",
            map_id="custom",
            factions={Faction.NATO.value: FactionState(Faction.NATO, resources=1)},
            provinces={"a": Province("a", "A", owner=Faction.NATO, neighbors=[], x=0, y=0)},
            battalions={
                "bn": Battalion(
                    battalion_id="bn",
                    faction=Faction.NATO,
                    province_id="a",
                    roster=[BattalionRosterEntry("x", 1)],
                )
            },
            schema_version=6,
        )
        ensure_strategic_formations(state)
        force = next(iter(state.strategic_formations.values()))
        force.position = province_anchor_position("a")
        before = force.position
        report = resolve_strategic_turn_movement(state)
        self.assertFalse(report["resolved"])
        self.assertEqual(before, force.position)


if __name__ == "__main__":
    unittest.main()
