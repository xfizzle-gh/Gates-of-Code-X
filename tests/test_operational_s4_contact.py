from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
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
    advance_operational_ticks,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_position import (
    clear_operational_graph_cache,
    ensure_operational_positions,
)
from gates_of_codex.operational_schema import (
    COST_MILLI_UNITY,
    FormationStance,
    FormationOperationalPosition,
    MoveOrderStatus,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.europe import build_goe_europe_campaign


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
        roster=[BattalionRosterEntry("tank(x)", 2, category="tank")],
        authorized_roster=[BattalionRosterEntry("tank(x)", 2, category="tank")],
    )


def _force(fid: str, faction: Faction, province: str, bn_ids: list[str]) -> StrategicFormation:
    return StrategicFormation(
        strategic_formation_id=fid,
        display_name=fid,
        faction=faction,
        province_id=province,
        echelon=ForceEchelon.BATTALION,
        battalion_ids=list(bn_ids),
        template_formation_id="toe-nato" if faction == Faction.NATO else "toe-rusa",
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
        "bn-nato-a": _bn("bn-nato-a", Faction.NATO, "a"),
        "bn-nato-b": _bn("bn-nato-b", Faction.NATO, "a"),
    }
    forces = {
        "sf-nato": _force("sf-nato", Faction.NATO, "a", ["bn-nato-a", "bn-nato-b"]),
    }
    battalions["bn-nato-a"].strategic_formation_id = "sf-nato"
    battalions["bn-nato-b"].strategic_formation_id = "sf-nato"
    if with_enemy:
        battalions["bn-rusa-a"] = _bn("bn-rusa-a", Faction.RUSSIA, "b")
        battalions["bn-rusa-b"] = _bn("bn-rusa-b", Faction.RUSSIA, "b")
        forces["sf-rusa"] = _force(
            "sf-rusa", Faction.RUSSIA, "b", ["bn-rusa-a", "bn-rusa-b"]
        )
        battalions["bn-rusa-a"].strategic_formation_id = "sf-rusa"
        battalions["bn-rusa-b"].strategic_formation_id = "sf-rusa"
    state = CampaignState(
        campaign_name="S4",
        map_id="s4_test",
        map_metadata={
            "operational_graph": str(graph_path.resolve()),
            "operational_maneuver_enabled": True,
        },
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
    for force in state.strategic_formations.values():
        force.position = FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=stable_node_id(force.province_id),
            progress_milli=0,
        )
    return state


class OperationalS4ContactTests(unittest.TestCase):
    def test_hostile_occupant_blocks_node_entry_for_every_stance(self) -> None:
        """A combat-capable hostile is solid at a node regardless of its stance."""
        for stance in FormationStance:
            with self.subTest(stance=stance.value), tempfile.TemporaryDirectory() as temporary:
                state = _state(Path(temporary), with_enemy=True)
                na, nb = stable_node_id("a"), stable_node_id("b")
                edge = stable_edge_id("corridor", na, nb)
                blocker = state.strategic_formations["sf-rusa"]
                blocker.stance = stance.value
                issue_move_order(
                    state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
                )
                commit_move_orders(state)
                activate_committed_orders(state)

                report = advance_operational_tick(state)

                self.assertEqual("node_contact", report["swept_kind"])
                assert state.pending_battle is not None
                self.assertEqual(nb, state.pending_battle.encounter_node_id)
                mover = state.strategic_formations["sf-nato"]
                assert mover.position is not None and mover.move_order is not None
                self.assertEqual(nb, mover.position.node_id)
                self.assertEqual(MoveOrderStatus.BLOCKED.value, mover.move_order.status)
                if stance == FormationStance.ENTRENCHED:
                    self.assertEqual(FormationStance.ENTRENCHED.value, blocker.stance)
                if stance == FormationStance.AMBUSH:
                    self.assertEqual(FormationStance.AMBUSH.value, blocker.stance)

    def test_static_hostile_co_location_creates_contact_for_every_stance(self) -> None:
        """Static node contact uses occupancy, not either side's stance."""
        for stance in FormationStance:
            with self.subTest(stance=stance.value), tempfile.TemporaryDirectory() as temporary:
                state = _state(Path(temporary), with_enemy=True)
                nb = stable_node_id("b")
                attacker = state.strategic_formations["sf-nato"]
                attacker.position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
                )
                attacker.province_id = "b"
                attacker.stance = stance.value
                for battalion_id in attacker.battalion_ids:
                    state.battalions[battalion_id].province_id = "b"
                state.strategic_formations["sf-rusa"].stance = stance.value

                report = advance_operational_tick(state)

                self.assertEqual("node_contact", report["swept_kind"])
                assert state.pending_battle is not None
                self.assertEqual(ENCOUNTER_KIND_NODE_CONTACT, state.pending_battle.encounter_kind)
                self.assertEqual(nb, state.pending_battle.encounter_node_id)
                if stance == FormationStance.ENTRENCHED:
                    self.assertEqual(FormationStance.ENTRENCHED.value, attacker.stance)
                if stance == FormationStance.AMBUSH:
                    self.assertEqual(FormationStance.AMBUSH.value, attacker.stance)

    def test_friendly_and_allied_node_occupants_do_not_create_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=False)
            state.battalions["bn-ally"] = _bn("bn-ally", Faction.NATO, "b")
            state.battalions["bn-ally"].strategic_formation_id = "sf-ally"
            state.strategic_formations["sf-ally"] = _force(
                "sf-ally", Faction.NATO, "b", ["bn-ally"]
            )
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)

            report = advance_operational_tick(state)

            self.assertEqual("", report["swept_kind"])
            self.assertIsNone(state.pending_battle)
            mover = state.strategic_formations["sf-nato"]
            assert mover.position is not None and mover.move_order is not None
            self.assertEqual(nb, mover.position.node_id)
            self.assertEqual(MoveOrderStatus.COMPLETED.value, mover.move_order.status)

    def test_non_combat_capable_hostile_occupants_do_not_block_entry(self) -> None:
        """Empty and destroyed formations are not hostile contact blockers."""
        for representation in ("empty_roster", "destroyed_battalion"):
            with self.subTest(representation=representation), tempfile.TemporaryDirectory() as temporary:
                state = _state(Path(temporary), with_enemy=True)
                blocker = state.strategic_formations["sf-rusa"]
                if representation == "empty_roster":
                    for battalion_id in blocker.battalion_ids:
                        state.battalions[battalion_id].roster = []
                else:
                    for battalion_id in blocker.battalion_ids:
                        state.battalions[battalion_id].roster = [
                            BattalionRosterEntry("tank(x)", 0, category="tank")
                        ]
                state.validate()
                na, nb = stable_node_id("a"), stable_node_id("b")
                edge = stable_edge_id("corridor", na, nb)
                issue_move_order(
                    state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
                )
                commit_move_orders(state)
                activate_committed_orders(state)

                report = advance_operational_tick(state)

                self.assertEqual("", report["swept_kind"])
                self.assertIsNone(state.pending_battle)
                mover = state.strategic_formations["sf-nato"]
                assert mover.position is not None and mover.move_order is not None
                self.assertEqual(nb, mover.position.node_id)
                self.assertEqual(MoveOrderStatus.COMPLETED.value, mover.move_order.status)

    def test_non_combat_capable_hostile_arrival_does_not_seed_node_contact(self) -> None:
        """A destroyed mover neither blocks nor enters a node-contact battle roster."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            mover = state.strategic_formations["sf-rusa"]
            for battalion_id in mover.battalion_ids:
                state.battalions[battalion_id].roster = []
            state.validate()
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-rusa", path_node_ids=[nb, na], path_edge_ids=[edge]
            )
            commit_move_orders(state, faction=Faction.RUSSIA.value)
            activate_committed_orders(state)

            report = advance_operational_tick(state)

            self.assertEqual("", report["swept_kind"])
            self.assertIsNone(state.pending_battle)
            assert mover.position is not None and mover.move_order is not None
            self.assertEqual(na, mover.position.node_id)
            self.assertEqual(MoveOrderStatus.COMPLETED.value, mover.move_order.status)

    def test_node_contact_immediately_interrupts_refit_for_all_participants(self) -> None:
        """Mover, stationary blocker, and coalition ally leave refit as battle opens."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            state.battalions["bn-rusa-c"] = _bn("bn-rusa-c", Faction.RUSSIA, "b")
            state.battalions["bn-rusa-c"].strategic_formation_id = "sf-rusa-2"
            state.strategic_formations["sf-rusa-2"] = _force(
                "sf-rusa-2", Faction.RUSSIA, "b", ["bn-rusa-c"]
            )
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            for formation_id in ("sf-nato", "sf-rusa", "sf-rusa-2"):
                state.strategic_formations[formation_id].stance = FormationStance.REFIT_RESUPPLY.value
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state, locked_stance=FormationStance.REFIT_RESUPPLY.value)
            activate_committed_orders(state)

            advance_operational_tick(state)
            self.assertIsNone(state.pending_battle)
            advance_operational_tick(state)

            assert state.pending_battle is not None
            participant_ids = {
                part.battalion_id
                for part in (
                    state.pending_battle.attacking_participants
                    + state.pending_battle.defending_participants
                )
            }
            self.assertEqual(
                {"bn-nato-a", "bn-nato-b", "bn-rusa-a", "bn-rusa-b", "bn-rusa-c"},
                participant_ids,
            )
            for formation_id in ("sf-nato", "sf-rusa", "sf-rusa-2"):
                force = state.strategic_formations[formation_id]
                self.assertEqual(FormationStance.OPERATIONAL.value, force.stance)
            mover_order = state.strategic_formations["sf-nato"].move_order
            assert mover_order is not None
            self.assertEqual(FormationStance.OPERATIONAL.value, mover_order.locked_stance)

    def test_forced_march_stops_at_contact_without_extra_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            graph_path = Path(state.map_metadata["operational_graph"])
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["nodes"].append(_node("c", pixel=[200, 0]))
            graph["edges"].append(_edge("b", "c"))
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            clear_operational_graph_cache()
            state.provinces["c"] = Province("c", "C", owner=Faction.NATO, neighbors=["b"], x=200, y=0)
            state.provinces["b"].neighbors.append("c")
            na, nb, nc = stable_node_id("a"), stable_node_id("b"), stable_node_id("c")
            edge_ab = stable_edge_id("corridor", na, nb)
            edge_bc = stable_edge_id("corridor", nb, nc)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb, nc], path_edge_ids=[edge_ab, edge_bc]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            mover = state.strategic_formations["sf-nato"]
            mover.stance = FormationStance.FORCED_MARCH.value
            assert mover.move_order is not None
            mover.move_order = replace(
                mover.move_order, locked_stance=FormationStance.FORCED_MARCH.value
            )

            report = advance_operational_tick(state)

            assert state.pending_battle is not None
            self.assertEqual("node_contact", report["swept_kind"])
            self.assertEqual(nb, state.pending_battle.encounter_node_id)
            assert mover.position is not None and mover.move_order is not None
            self.assertEqual(nb, mover.position.node_id)
            self.assertNotEqual(nc, mover.position.node_id)
            self.assertEqual(MoveOrderStatus.BLOCKED.value, mover.move_order.status)

    def test_enemy_node_entry_preserves_origin_and_all_battalions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            # Second Russian formation already holding b (same side, multi-formation defense).
            state.battalions["bn-rusa-c"] = _bn("bn-rusa-c", Faction.RUSSIA, "b")
            state.battalions["bn-rusa-c"].strategic_formation_id = "sf-rusa-2"
            state.strategic_formations["sf-rusa-2"] = _force(
                "sf-rusa-2", Faction.RUSSIA, "b", ["bn-rusa-c"]
            )
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
            pb = state.pending_battle
            self.assertEqual(ENCOUNTER_KIND_NODE_CONTACT, pb.encounter_kind)
            self.assertEqual(nb, pb.encounter_node_id)
            # Origin is pre-entry province a, not destination b.
            self.assertEqual("a", pb.origin_province_id)
            self.assertEqual("b", pb.target_province_id)
            atk_ids = {p.battalion_id for p in pb.attacking_participants}
            def_ids = {p.battalion_id for p in pb.defending_participants}
            self.assertEqual({"bn-nato-a", "bn-nato-b"}, atk_ids)
            self.assertEqual({"bn-rusa-a", "bn-rusa-b", "bn-rusa-c"}, def_ids)
            nato = state.strategic_formations["sf-nato"]
            assert nato.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, nato.move_order.status)
            self.assertTrue(node_is_contested(state, nb))

    def test_static_contact_includes_all_allied_formations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            nb = stable_node_id("b")
            # Two NATO formations + two Russian formations already on b.
            state.battalions["bn-ally"] = _bn("bn-ally", Faction.NATO, "b")
            state.battalions["bn-ally"].strategic_formation_id = "sf-ally"
            state.strategic_formations["sf-ally"] = _force(
                "sf-ally", Faction.NATO, "b", ["bn-ally"]
            )
            state.battalions["bn-rusa-c"] = _bn("bn-rusa-c", Faction.RUSSIA, "b")
            state.battalions["bn-rusa-c"].strategic_formation_id = "sf-rusa-2"
            state.strategic_formations["sf-rusa-2"] = _force(
                "sf-rusa-2", Faction.RUSSIA, "b", ["bn-rusa-c"]
            )
            for fid in ("sf-nato", "sf-ally"):
                state.strategic_formations[fid].position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
                )
                state.strategic_formations[fid].province_id = "b"
            for bid in ("bn-nato-a", "bn-nato-b", "bn-ally"):
                state.battalions[bid].province_id = "b"
            report = advance_operational_tick(state)
            self.assertTrue(report.get("static_contact") or report.get("battle_id"))
            assert state.pending_battle is not None
            atk_ids = {p.battalion_id for p in state.pending_battle.attacking_participants}
            def_ids = {p.battalion_id for p in state.pending_battle.defending_participants}
            self.assertEqual({"bn-nato-a", "bn-nato-b", "bn-ally"}, atk_ids)
            self.assertEqual({"bn-rusa-a", "bn-rusa-b", "bn-rusa-c"}, def_ids)

    def test_resolve_battle_updates_all_participants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            atk_before = {
                bn.battalion_id: bn.unit_count
                for bn in state.battalions.values()
                if bn.faction == Faction.NATO
            }
            engine = CampaignEngine(state, random_seed=1)
            winner = engine.auto_resolve_pending_battle()
            self.assertIn(winner, {Faction.NATO, Faction.RUSSIA})
            self.assertIsNone(state.pending_battle)
            # All original NATO battalions still tracked or removed coherently.
            for bid in atk_before:
                bn = state.battalions.get(bid)
                if bn is not None:
                    self.assertLessEqual(bn.unit_count, atk_before[bid])
            state.validate()

    def test_static_co_location_opens_battle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            nb = stable_node_id("b")
            state.strategic_formations["sf-nato"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id=nb, progress_milli=0
            )
            state.strategic_formations["sf-nato"].province_id = "b"
            for bid in ("bn-nato-a", "bn-nato-b"):
                state.battalions[bid].province_id = "b"
            report = advance_operational_tick(state)
            self.assertTrue(report.get("static_contact") or report.get("battle_id"))
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            # Owner (Russia) defends; NATO attacks.
            self.assertEqual(Faction.NATO, state.pending_battle.attacker_faction)
            self.assertEqual(Faction.RUSSIA, state.pending_battle.defender_faction)

    def test_friendly_stack_cap_snaps_to_origin_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=False)
            nb = stable_node_id("b")
            na = stable_node_id("a")
            for index in range(3):
                bid = f"bn-f{index}"
                fid = f"sf-f{index}"
                state.battalions[bid] = _bn(bid, Faction.NATO, "b")
                state.battalions[bid].strategic_formation_id = fid
                state.strategic_formations[fid] = _force(fid, Faction.NATO, "b", [bid])
            self.assertEqual(3, len(formations_at_node(state, nb)))
            mover = state.strategic_formations["sf-nato"]
            self.assertFalse(can_enter_node_friendly_stack(state, mover, nb))
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            nato = state.strategic_formations["sf-nato"]
            assert nato.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, nato.position.mode)
            self.assertEqual(na, nato.position.node_id)
            self.assertEqual("a", nato.province_id)
            assert nato.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, nato.move_order.status)
            self.assertIsNone(state.pending_battle)

    def test_legacy_map_still_rejects_mixed_faction_province(self) -> None:
        state = build_goe_europe_campaign()
        ensure_strategic_formations(state)
        # Clear operational positions so mixed presence is not granted.
        for force in state.strategic_formations.values():
            force.position = None
        state.map_metadata.pop("operational_graph", None)
        battalions = sorted(state.battalions.values(), key=lambda value: value.battalion_id)
        first = battalions[0]
        hostile = next(value for value in battalions[1:] if value.faction != first.faction)
        hostile.province_id = first.province_id
        force = state.strategic_formations.get(hostile.strategic_formation_id)
        if force is not None:
            force.province_id = first.province_id
            force.position = None
        with self.assertRaisesRegex(ValueError, "multiple factions"):
            state.validate()

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
            self.assertEqual("a", reloaded.pending_battle.origin_province_id)
            self.assertGreaterEqual(len(reloaded.pending_battle.attacking_participants), 2)
            self.assertGreaterEqual(len(reloaded.pending_battle.defending_participants), 2)

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
            batch = advance_operational_ticks(state, 10)
            self.assertLess(batch["ticks"], 10)
            self.assertIsNotNone(state.pending_battle)

    def test_multi_battalion_formation_retreats_once_to_origin(self) -> None:
        """Three-battalion mover loses entry contact → one hop back to origin, cohesive."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            # Add third battalion to NATO mover.
            state.battalions["bn-nato-c"] = _bn("bn-nato-c", Faction.NATO, "a")
            state.battalions["bn-nato-c"].strategic_formation_id = "sf-nato"
            state.strategic_formations["sf-nato"].battalion_ids.append("bn-nato-c")
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            self.assertEqual("a", state.pending_battle.origin_province_id)
            # Force defender win.
            engine = CampaignEngine(state, random_seed=0)
            # Deterministic: apply defender victory directly.
            engine.apply_battle_result(Faction.RUSSIA)
            force = state.strategic_formations.get("sf-nato")
            if force is None:
                # Entire formation destroyed is acceptable only if no survivors.
                self.assertFalse(
                    any(bn.faction == Faction.NATO for bn in state.battalions.values())
                )
                return
            # Exactly one retreat hop to origin province a.
            self.assertEqual("a", force.province_id)
            member_provinces = {
                state.battalions[bid].province_id
                for bid in force.battalion_ids
                if bid in state.battalions
            }
            self.assertEqual({"a"}, member_provinces)
            assert force.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, force.position.mode)
            self.assertEqual(stable_node_id("a"), force.position.node_id)
            assert force.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, force.move_order.status)

    def test_allied_attackers_retreat_independently_once_each(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            nb = stable_node_id("b")
            # Ally already on b; main force enters from a then both lose.
            state.battalions["bn-ally"] = _bn("bn-ally", Faction.NATO, "b")
            state.battalions["bn-ally"].strategic_formation_id = "sf-ally"
            state.strategic_formations["sf-ally"] = _force(
                "sf-ally", Faction.NATO, "b", ["bn-ally"]
            )
            state.provinces["c"] = Province(
                "c", "C", owner=Faction.NATO, neighbors=["b"], x=200, y=0
            )
            state.provinces["b"].neighbors = ["a", "c"]
            na = stable_node_id("a")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None
            CampaignEngine(state, random_seed=0).apply_battle_result(Faction.RUSSIA)
            mover = state.strategic_formations.get("sf-nato")
            ally = state.strategic_formations.get("sf-ally")
            if mover is not None:
                self.assertEqual("a", mover.province_id)
            if ally is not None:
                # Ally was already on b; retreats once to a friendly neighbor (a or c).
                self.assertIn(ally.province_id, {"a", "c"})
                self.assertNotEqual("b", ally.province_id)

    def test_stack_cap_blocks_contested_entry_without_joining_battle(self) -> None:
        """3 friendlies + enemy on B: fourth friendly is snapped back, not in battle."""
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), with_enemy=True)
            nb = stable_node_id("b")
            na = stable_node_id("a")
            # Three friendly NATO formations already on B with the enemy.
            for index in range(3):
                bid = f"bn-hold{index}"
                fid = f"sf-hold{index}"
                state.battalions[bid] = _bn(bid, Faction.NATO, "b")
                state.battalions[bid].strategic_formation_id = fid
                state.strategic_formations[fid] = _force(fid, Faction.NATO, "b", [bid])
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state, "sf-nato", path_node_ids=[na, nb], path_edge_ids=[edge]
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            report = advance_operational_tick(state)
            self.assertTrue(report["advanced"])
            nato = state.strategic_formations["sf-nato"]
            assert nato.position is not None
            # Fourth friendly denied by cap even though enemies occupy B.
            self.assertEqual(na, nato.position.node_id)
            self.assertEqual("a", nato.province_id)
            assert nato.move_order is not None
            self.assertEqual(MoveOrderStatus.BLOCKED.value, nato.move_order.status)
            # Static contact among the three holders + enemy may open a battle afterward.
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            atk = {p.battalion_id for p in state.pending_battle.attacking_participants}
            dfn = {p.battalion_id for p in state.pending_battle.defending_participants}
            self.assertNotIn("bn-nato-a", atk | dfn)
            self.assertNotIn("bn-nato-b", atk | dfn)
            self.assertTrue({"bn-hold0", "bn-hold1", "bn-hold2"} & atk)

    def test_stale_positions_without_graph_do_not_allow_mixed_presence(self) -> None:
        state = build_goe_europe_campaign()
        ensure_strategic_formations(state)
        # Stale positions + no resolvable graph/flag must not unlock mixed presence.
        for force in state.strategic_formations.values():
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id(force.province_id),
                progress_milli=0,
            )
        state.map_metadata.pop("operational_graph", None)
        state.map_metadata.pop("operational_maneuver_enabled", None)
        battalions = sorted(state.battalions.values(), key=lambda value: value.battalion_id)
        first = battalions[0]
        hostile = next(value for value in battalions[1:] if value.faction != first.faction)
        hostile.province_id = first.province_id
        force = state.strategic_formations.get(hostile.strategic_formation_id)
        if force is not None:
            force.province_id = first.province_id
        with self.assertRaisesRegex(ValueError, "multiple factions"):
            state.validate()


if __name__ == "__main__":
    unittest.main()
