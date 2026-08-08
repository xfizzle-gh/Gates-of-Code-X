from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
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
from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.operational_ai import plan_and_issue_operational_orders
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_ambush import (
    apply_pending_battle_ambush,
    apply_strength_multiplier_milli,
    refresh_ambush_readiness,
)
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


def _add_force(
    state: CampaignState,
    formation_id: str,
    battalion_id: str,
    faction: Faction,
    province_id: str,
) -> StrategicFormation:
    battalion = _battalion(
        battalion_id,
        formation_id,
        faction,
        province_id,
    )
    force = _formation(
        formation_id,
        battalion_id,
        faction,
        province_id,
    )
    state.battalions[battalion_id] = battalion
    state.strategic_formations[formation_id] = force
    return force


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

        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            force = state.strategic_formations["sf-n"]
            force.stance = FormationStance.AMBUSH.value
            force.ambush_ready_tick = 0
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                order_id="ord-stance-change",
            )
            commit_move_orders(
                state,
                locked_stance=FormationStance.OPERATIONAL.value,
            )
            self.assertIsNone(force.ambush_ready_tick)


class OperationalS9CAmbushContactTests(unittest.TestCase):
    def test_contact_before_first_complete_stationary_tick_gets_no_bonus(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            force = state.strategic_formations["sf-n"]
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=stable_node_id("b"),
                progress_milli=0,
            )
            force.province_id = "b"
            force.stance = FormationStance.AMBUSH.value
            state.battalions["bn-n"].province_id = "b"

            advance_operational_tick(state)

            assert state.pending_battle is not None
            participant = next(
                item
                for item in (
                    state.pending_battle.attacking_participants
                    + state.pending_battle.defending_participants
                )
                if item.battalion_id == "bn-n"
            )
            self.assertFalse(participant.ambush_eligible)
            self.assertFalse(participant.ambush_triggered)
            self.assertEqual(participant.ambush_strength_multiplier_milli, 1000)
            self.assertIsNone(force.ambush_ready_tick)

    def test_prepared_node_defender_triggers_but_moving_initiator_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            defender = state.strategic_formations["sf-r"]
            defender.stance = FormationStance.AMBUSH.value
            defender.ambush_ready_tick = 0

            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", node_a, node_b)
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[edge],
                order_id="ord-node-contact",
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            report = advance_operational_tick(state)

            self.assertTrue(report["battle_id"])
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            participants = {
                item.battalion_id: item
                for item in (
                    state.pending_battle.attacking_participants
                    + state.pending_battle.defending_participants
                )
            }
            initiator = participants["bn-n"]
            prepared = participants["bn-r"]
            self.assertTrue(initiator.contact_initiator)
            self.assertFalse(initiator.ambush_eligible)
            self.assertFalse(initiator.ambush_triggered)
            self.assertEqual(initiator.ambush_strength_multiplier_milli, 1000)
            self.assertFalse(initiator.ambush_readiness_consumed)
            self.assertFalse(prepared.contact_initiator)
            self.assertTrue(prepared.ambush_eligible)
            self.assertTrue(prepared.ambush_triggered)
            self.assertEqual(prepared.ambush_strength_multiplier_milli, 1150)
            self.assertTrue(prepared.ambush_readiness_consumed)
            self.assertIsNone(defender.ambush_ready_tick)

            before = [
                (
                    item.battalion_id,
                    item.contact_initiator,
                    item.ambush_eligible,
                    item.ambush_triggered,
                    item.ambush_strength_multiplier_milli,
                    item.ambush_readiness_consumed,
                )
                for item in participants.values()
            ]
            apply_pending_battle_ambush(
                state,
                initiating_formation_ids=("sf-n",),
            )
            after = [
                (
                    item.battalion_id,
                    item.contact_initiator,
                    item.ambush_eligible,
                    item.ambush_triggered,
                    item.ambush_strength_multiplier_milli,
                    item.ambush_readiness_consumed,
                )
                for item in participants.values()
            ]
            self.assertEqual(after, before)

    def test_stationary_edge_ambush_uses_s6_contact_and_triggers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", node_a, node_b)
            mover = state.strategic_formations["sf-n"]
            prepared = state.strategic_formations["sf-r"]
            mover.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=node_b,
            )
            prepared.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=400,
                facing_node_id=node_b,
            )
            prepared.province_id = "a"
            state.battalions["bn-r"].province_id = "a"
            prepared.stance = FormationStance.AMBUSH.value
            prepared.ambush_ready_tick = 0
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[edge],
                order_id="ord-edge-contact",
            )
            commit_move_orders(state, faction=Faction.NATO.value)
            activate_committed_orders(state)
            mover.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=node_b,
            )
            prepared.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=400,
                facing_node_id=node_b,
            )
            prepared.move_order = None

            report = advance_operational_tick(state)

            self.assertEqual(report["swept_kind"], "edge_catchup")
            assert state.pending_battle is not None
            participants = {
                item.battalion_id: item
                for item in (
                    state.pending_battle.attacking_participants
                    + state.pending_battle.defending_participants
                )
            }
            self.assertTrue(participants["bn-n"].contact_initiator)
            self.assertFalse(participants["bn-n"].ambush_triggered)
            self.assertFalse(participants["bn-r"].contact_initiator)
            self.assertTrue(participants["bn-r"].ambush_triggered)
            self.assertEqual(
                participants["bn-r"].ambush_strength_multiplier_milli,
                1150,
            )
            self.assertIsNone(prepared.ambush_ready_tick)

    def test_player_ai_save_load_and_insertion_order_have_identical_metadata(
        self,
    ) -> None:
        def run(*, use_ai: bool, reverse: bool, reload: bool) -> tuple:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                state = _state(root)
                if reverse:
                    state.strategic_formations = dict(
                        reversed(list(state.strategic_formations.items()))
                    )
                    state.battalions = dict(reversed(list(state.battalions.items())))
                defender = state.strategic_formations["sf-r"]
                defender.stance = FormationStance.AMBUSH.value
                defender.ambush_ready_tick = 0
                if use_ai:
                    actions = plan_and_issue_operational_orders(state, Faction.NATO)
                    self.assertEqual([action.action for action in actions], ["operational_move"])
                else:
                    node_a, node_b = stable_node_id("a"), stable_node_id("b")
                    issue_move_order(
                        state,
                        "sf-n",
                        path_node_ids=[node_a, node_b],
                        path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                        order_id="ord-player",
                    )
                    commit_move_orders(state)
                activate_committed_orders(state)
                advance_operational_tick(state)
                advance_operational_tick(state)
                if reload:
                    save_path = root / "pending.json"
                    save_campaign(state, save_path)
                    state = load_campaign(save_path)
                assert state.pending_battle is not None
                metadata = sorted(
                    (
                        item.battalion_id,
                        item.contact_initiator,
                        item.ambush_eligible,
                        item.ambush_triggered,
                        item.ambush_strength_multiplier_milli,
                        item.ambush_readiness_consumed,
                    )
                    for item in (
                        state.pending_battle.attacking_participants
                        + state.pending_battle.defending_participants
                    )
                )
                return (
                    state.pending_battle.encounter_kind,
                    metadata,
                    state.strategic_formations["sf-r"].ambush_ready_tick,
                )

        baseline = run(use_ai=False, reverse=False, reload=False)
        self.assertEqual(run(use_ai=True, reverse=False, reload=False), baseline)
        self.assertEqual(run(use_ai=False, reverse=True, reload=True), baseline)
        self.assertEqual(run(use_ai=True, reverse=True, reload=True), baseline)

    def test_each_prepared_formation_gets_own_modifier_without_entrenched_stacking(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            prepared_ids = ("sf-r", "sf-r2")
            _add_force(
                state,
                "sf-r2",
                "bn-r2",
                Faction.RUSSIA,
                "b",
            )
            entrenched = _add_force(
                state,
                "sf-r3",
                "bn-r3",
                Faction.RUSSIA,
                "b",
            )
            for formation_id in prepared_ids:
                force = state.strategic_formations[formation_id]
                force.stance = FormationStance.AMBUSH.value
                force.ambush_ready_tick = 0
            entrenched.stance = FormationStance.ENTRENCHED.value

            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                order_id="ord-multi-ambush",
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            advance_operational_tick(state)

            assert state.pending_battle is not None
            participants = {
                item.battalion_id: item
                for item in (
                    state.pending_battle.attacking_participants
                    + state.pending_battle.defending_participants
                )
            }
            self.assertEqual(
                {
                    battalion_id: participant.ambush_strength_multiplier_milli
                    for battalion_id, participant in participants.items()
                },
                {
                    "bn-n": 1000,
                    "bn-r": 1150,
                    "bn-r2": 1150,
                    "bn-r3": 1000,
                },
            )
            self.assertTrue(participants["bn-r"].ambush_triggered)
            self.assertTrue(participants["bn-r2"].ambush_triggered)
            self.assertFalse(participants["bn-r3"].ambush_triggered)

    def test_friendly_colocation_and_unrelated_battle_do_not_consume_readiness(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            prepared = state.strategic_formations["sf-n"]
            prepared.stance = FormationStance.AMBUSH.value
            prepared.ambush_ready_tick = 0
            _add_force(state, "sf-n-friend", "bn-n-friend", Faction.NATO, "a")
            _add_force(state, "sf-n-other", "bn-n-other", Faction.NATO, "b")

            report = advance_operational_tick(state)

            self.assertTrue(report["battle_id"])
            assert state.pending_battle is not None
            participant_ids = {
                item.battalion_id
                for item in (
                    state.pending_battle.attacking_participants
                    + state.pending_battle.defending_participants
                )
            }
            self.assertNotIn("bn-n", participant_ids)
            self.assertNotIn("bn-n-friend", participant_ids)
            self.assertEqual(prepared.ambush_ready_tick, 0)

    def test_rejected_order_without_battle_does_not_consume_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            prepared = state.strategic_formations["sf-n"]
            prepared.stance = FormationStance.AMBUSH.value
            prepared.ambush_ready_tick = 0
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            order = issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                order_id="ord-rejected",
            )
            prepared.move_order = replace(
                order,
                status=MoveOrderStatus.BLOCKED.value,
            )

            report = advance_operational_tick(state)

            self.assertFalse(report["battle_id"])
            self.assertIsNone(state.pending_battle)
            self.assertEqual(prepared.ambush_ready_tick, 0)

    def test_refit_forced_march_and_entrenched_never_receive_ambush_modifier(
        self,
    ) -> None:
        for stance in (
            FormationStance.REFIT_RESUPPLY.value,
            FormationStance.FORCED_MARCH.value,
            FormationStance.ENTRENCHED.value,
        ):
            with self.subTest(stance=stance), tempfile.TemporaryDirectory() as td:
                state = _state(Path(td))
                defender = state.strategic_formations["sf-r"]
                defender.stance = stance
                defender.ambush_ready_tick = 0
                node_a, node_b = stable_node_id("a"), stable_node_id("b")
                issue_move_order(
                    state,
                    "sf-n",
                    path_node_ids=[node_a, node_b],
                    path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                    order_id=f"ord-{stance}",
                )
                commit_move_orders(state)
                activate_committed_orders(state)
                advance_operational_tick(state)
                advance_operational_tick(state)

                assert state.pending_battle is not None
                participant = next(
                    item
                    for item in state.pending_battle.defending_participants
                    if item.battalion_id == "bn-r"
                )
                self.assertFalse(participant.ambush_eligible)
                self.assertFalse(participant.ambush_triggered)
                self.assertEqual(
                    participant.ambush_strength_multiplier_milli,
                    1000,
                )


class OperationalS9CAmbushStrengthTests(unittest.TestCase):
    def test_1150_multiplier_is_exact_per_participant_before_side_aggregation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            prepared = state.strategic_formations["sf-r"]
            prepared.stance = FormationStance.AMBUSH.value
            prepared.ambush_ready_tick = 0
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                order_id="ord-strength",
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            advance_operational_tick(state)
            assert state.pending_battle is not None

            engine = CampaignEngine(state, random_seed=0)
            self.assertEqual(
                engine._aggregate_participant_strength_milli(
                    state.pending_battle.attacking_participants
                ),
                3000,
            )
            self.assertEqual(
                engine._aggregate_participant_strength_milli(
                    state.pending_battle.defending_participants
                ),
                3450,
            )
            self.assertEqual(apply_strength_multiplier_milli(1001, 1150), 1151)


class OperationalS9CAmbushFinalizationTests(unittest.TestCase):
    def test_only_participating_ambush_resets_to_operational_on_finalization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            prepared = state.strategic_formations["sf-r"]
            prepared.stance = FormationStance.AMBUSH.value
            prepared.ambush_ready_tick = 0
            unrelated = _add_force(
                state,
                "sf-unrelated",
                "bn-unrelated",
                Faction.NATO,
                "a",
            )
            unrelated.stance = FormationStance.AMBUSH.value
            unrelated.ambush_ready_tick = 0
            node_a, node_b = stable_node_id("a"), stable_node_id("b")
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[node_a, node_b],
                path_edge_ids=[stable_edge_id("corridor", node_a, node_b)],
                order_id="ord-finalization",
            )
            commit_move_orders(state)
            activate_committed_orders(state)
            advance_operational_tick(state)
            advance_operational_tick(state)

            CampaignEngine(state, random_seed=0).apply_battle_result(Faction.RUSSIA)

            self.assertEqual(prepared.stance, FormationStance.OPERATIONAL.value)
            self.assertIsNone(prepared.ambush_ready_tick)
            self.assertEqual(unrelated.stance, FormationStance.AMBUSH.value)
            self.assertEqual(unrelated.ambush_ready_tick, 0)

    def test_retreat_and_destruction_leave_no_ambush_readiness(self) -> None:
        for quantity, survives in ((10, True), (1, False)):
            with self.subTest(quantity=quantity), tempfile.TemporaryDirectory() as td:
                state = _state(Path(td))
                force = state.strategic_formations["sf-n"]
                force.position = FormationOperationalPosition(
                    mode=PositionMode.AT_NODE.value,
                    node_id=stable_node_id("b"),
                    progress_milli=0,
                )
                force.province_id = "b"
                force.stance = FormationStance.AMBUSH.value
                force.ambush_ready_tick = 0
                battalion = state.battalions["bn-n"]
                battalion.province_id = "b"
                battalion.roster[0].quantity = quantity
                battalion.authorized_roster[0].quantity = quantity

                advance_operational_tick(state)
                assert state.pending_battle is not None
                ambusher = next(
                    item
                    for item in (
                        state.pending_battle.attacking_participants
                        + state.pending_battle.defending_participants
                    )
                    if item.battalion_id == "bn-n"
                )
                self.assertFalse(ambusher.contact_initiator)
                self.assertTrue(ambusher.ambush_triggered)
                CampaignEngine(state, random_seed=0).apply_battle_result(
                    Faction.RUSSIA
                )

                if survives:
                    self.assertIn("sf-n", state.strategic_formations)
                    retreated = state.strategic_formations["sf-n"]
                    self.assertEqual(retreated.province_id, "a")
                    self.assertIsNone(retreated.ambush_ready_tick)
                    self.assertEqual(
                        retreated.stance,
                        FormationStance.OPERATIONAL.value,
                    )
                else:
                    self.assertNotIn("sf-n", state.strategic_formations)
                    self.assertNotIn("bn-n", state.battalions)


if __name__ == "__main__":
    unittest.main()
