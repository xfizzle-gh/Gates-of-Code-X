from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.models import Faction
from gates_of_codex.operational_interception import (
    ENCOUNTER_KIND_EDGE_CATCHUP,
    ENCOUNTER_KIND_EDGE_CROSS,
)
from gates_of_codex.operational_movement import (
    activate_committed_orders,
    advance_operational_tick,
    commit_move_orders,
    issue_move_order,
)
from gates_of_codex.operational_schema import (
    FormationOperationalPosition,
    FormationStance,
    MoveOrderStatus,
    PositionMode,
    stable_edge_id,
    stable_node_id,
)
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_operational_s6_interception import _add_force, _graph, _state
from tests import test_operational_s9a_retreat as s9a_fixture


class OperationalS9BEdgeBlockingTests(unittest.TestCase):
    STANCES = (
        FormationStance.OPERATIONAL.value,
        FormationStance.AMBUSH.value,
        FormationStance.ENTRENCHED.value,
        FormationStance.FORCED_MARCH.value,
        FormationStance.REFIT_RESUPPLY.value,
    )

    def _stationary_contact_state(
        self,
        root: Path,
        *,
        blocker_stance: str,
        reverse_facing: bool = False,
        destroyed: bool = False,
        one_way: bool = False,
    ):
        graph = _graph(ab_cost=1000)
        graph["edges"][0]["bidirectional"] = not one_way
        state = _state(root, graph)
        na, nb = stable_node_id("a"), stable_node_id("b")
        edge = stable_edge_id("corridor", na, nb)

        blocker_facing = na if reverse_facing else nb
        blocker_progress = 400 if reverse_facing else 600
        blocker_position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=edge,
            progress_milli=blocker_progress,
            facing_node_id=blocker_facing,
        )
        mover_position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=edge,
            progress_milli=0,
            facing_node_id=nb,
        )

        blocker = state.strategic_formations["sf-r"]
        blocker.position = blocker_position
        blocker.move_order = None
        blocker.stance = blocker_stance
        blocker.province_id = "a"
        state.battalions["bn-r"].province_id = "a"
        if destroyed:
            state.battalions["bn-r"].roster = []

        mover = state.strategic_formations["sf-n"]
        mover.position = mover_position
        issue_move_order(
            state,
            "sf-n",
            path_node_ids=[na, nb],
            path_edge_ids=[edge],
            order_id="s9b-edge-mover",
        )
        mover.position = mover_position
        blocker.position = blocker_position
        blocker.move_order = None
        blocker.stance = blocker_stance
        commit_move_orders(
            state,
            faction=state.strategic_formations["sf-n"].faction.value,
            locked_stance=FormationStance.OPERATIONAL.value,
        )
        activate_committed_orders(state)
        mover.position = mover_position
        blocker.position = blocker_position
        blocker.move_order = None
        blocker.stance = blocker_stance
        return state, edge, na, nb

    def test_s9b_all_stances_block_stationary_edge_and_lose_remaining_tick(self) -> None:
        for stance in self.STANCES:
            with self.subTest(stance=stance), tempfile.TemporaryDirectory() as temporary:
                state, edge, _na, _nb = self._stationary_contact_state(
                    Path(temporary), blocker_stance=stance
                )

                report = advance_operational_tick(state)

                self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
                self.assertEqual([], report.get("moved"))
                self.assertIsNotNone(state.pending_battle)
                assert state.pending_battle is not None
                self.assertEqual(edge, state.pending_battle.encounter_edge_id)
                self.assertEqual(600, state.pending_battle.encounter_progress_milli)
                self.assertEqual(
                    {"bn-n", "bn-r"},
                    {
                        participant.battalion_id
                        for participant in (
                            state.pending_battle.attacking_participants
                            + state.pending_battle.defending_participants
                        )
                    },
                )

                mover = state.strategic_formations["sf-n"]
                blocker = state.strategic_formations["sf-r"]
                assert mover.position is not None and blocker.position is not None
                self.assertEqual(600, mover.position.progress_milli)
                self.assertEqual(600, blocker.position.progress_milli)
                assert mover.move_order is not None
                self.assertEqual(MoveOrderStatus.BLOCKED.value, mover.move_order.status)
                expected_stance = (
                    FormationStance.OPERATIONAL.value
                    if stance == FormationStance.REFIT_RESUPPLY.value
                    else stance
                )
                self.assertEqual(expected_stance, blocker.stance)

                frozen = (
                    (
                        mover.position.mode,
                        mover.position.edge_id,
                        mover.position.progress_milli,
                        mover.position.facing_node_id,
                    ),
                    (
                        blocker.position.mode,
                        blocker.position.edge_id,
                        blocker.position.progress_milli,
                        blocker.position.facing_node_id,
                    ),
                )
                second = advance_operational_tick(state)
                self.assertFalse(second["advanced"])
                self.assertEqual("pending_battle", second["reason"])
                self.assertEqual(
                    frozen,
                    (
                        (
                            mover.position.mode,
                            mover.position.edge_id,
                            mover.position.progress_milli,
                            mover.position.facing_node_id,
                        ),
                        (
                            blocker.position.mode,
                            blocker.position.edge_id,
                            blocker.position.progress_milli,
                            blocker.position.facing_node_id,
                        ),
                    ),
                )

    def test_s9b_one_way_edge_contact_uses_legal_interval_despite_reverse_facing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, edge, na, _nb = self._stationary_contact_state(
                Path(temporary),
                blocker_stance=FormationStance.OPERATIONAL.value,
                reverse_facing=True,
                one_way=True,
            )

            report = advance_operational_tick(state)

            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertEqual(edge, state.pending_battle.encounter_edge_id)
            self.assertEqual(600, state.pending_battle.encounter_progress_milli)
            blocker = state.strategic_formations["sf-r"]
            assert blocker.position is not None
            self.assertEqual(na, blocker.position.facing_node_id)
            self.assertEqual(400, blocker.position.progress_milli)

    def test_s9b_destroyed_stationary_edge_occupant_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, _edge, _na, nb = self._stationary_contact_state(
                Path(temporary),
                blocker_stance=FormationStance.OPERATIONAL.value,
                destroyed=True,
            )

            report = advance_operational_tick(state)

            self.assertIsNone(state.pending_battle)
            self.assertNotEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
            mover = state.strategic_formations["sf-n"]
            assert mover.position is not None
            self.assertEqual(PositionMode.AT_NODE.value, mover.position.mode)
            self.assertEqual(nb, mover.position.node_id)

    def test_s9b_active_refit_order_blocks_on_edge_and_is_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = _state(Path(temporary), _graph(ab_cost=1000))
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)

            issue_move_order(
                state,
                "sf-r",
                path_node_ids=[nb, na],
                path_edge_ids=[edge],
                order_id="s9b-refit-blocker",
            )
            commit_move_orders(
                state,
                faction=Faction.RUSSIA.value,
                locked_stance=FormationStance.REFIT_RESUPPLY.value,
            )
            issue_move_order(
                state,
                "sf-n",
                path_node_ids=[na, nb],
                path_edge_ids=[edge],
                order_id="s9b-refit-contact-mover",
            )
            commit_move_orders(
                state,
                faction=Faction.NATO.value,
                locked_stance=FormationStance.OPERATIONAL.value,
            )
            activate_committed_orders(state)

            blocker = state.strategic_formations["sf-r"]
            blocker.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=400,
                facing_node_id=na,
            )
            blocker.stance = FormationStance.REFIT_RESUPPLY.value
            mover = state.strategic_formations["sf-n"]
            mover.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=0,
                facing_node_id=nb,
            )

            report = advance_operational_tick(state)

            self.assertEqual(ENCOUNTER_KIND_EDGE_CROSS, report.get("swept_kind"))
            self.assertIsNotNone(state.pending_battle)
            self.assertEqual(FormationStance.OPERATIONAL.value, blocker.stance)
            assert blocker.move_order is not None
            self.assertEqual(FormationStance.OPERATIONAL.value, blocker.move_order.locked_stance)
            self.assertEqual(MoveOrderStatus.BLOCKED.value, blocker.move_order.status)

    def test_s9b_refit_ally_at_edge_contact_joins_and_is_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state, edge, _na, nb = self._stationary_contact_state(
                Path(temporary), blocker_stance=FormationStance.OPERATIONAL.value
            )
            _add_force(state, "sf-ally", "bn-ally", Faction.NATO, "a")
            ally = state.strategic_formations["sf-ally"]
            ally.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id=edge,
                progress_milli=600,
                facing_node_id=nb,
            )
            ally.stance = FormationStance.REFIT_RESUPPLY.value

            report = advance_operational_tick(state)

            self.assertEqual(ENCOUNTER_KIND_EDGE_CATCHUP, report.get("swept_kind"))
            self.assertIsNotNone(state.pending_battle)
            assert state.pending_battle is not None
            self.assertIn(
                "bn-ally",
                {
                    participant.battalion_id
                    for participant in state.pending_battle.attacking_participants
                },
            )
            self.assertEqual(FormationStance.OPERATIONAL.value, ally.stance)


class OperationalS9BFinalizationTests(unittest.TestCase):
    def _node_battle(self, root: Path):
        state = s9a_fixture._state(root)
        helper = s9a_fixture.OperationalS9AFinalizationTests()
        helper._node_battle(state)
        return state

    def _set_forced_march(self, state, formation_id: str) -> None:
        force = state.strategic_formations[formation_id]
        force.stance = FormationStance.FORCED_MARCH.value
        if force.move_order is not None:
            force.move_order = replace(
                force.move_order,
                locked_stance=FormationStance.FORCED_MARCH.value,
            )

    def _assert_operational(self, state, formation_id: str) -> None:
        force = state.strategic_formations[formation_id]
        self.assertEqual(FormationStance.OPERATIONAL.value, force.stance)
        if force.move_order is not None:
            self.assertEqual(
                FormationStance.OPERATIONAL.value,
                force.move_order.locked_stance,
            )

    def test_s9b_internal_result_resets_forced_march_for_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = self._node_battle(Path(temporary))
            self._set_forced_march(state, "sf-nato")
            self._set_forced_march(state, "sf-rusa")

            CampaignEngine(state, random_seed=0).apply_battle_result(Faction.RUSSIA)

            self._assert_operational(state, "sf-nato")
            self._assert_operational(state, "sf-rusa")

    def test_s9b_external_result_resets_forced_march_for_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = self._node_battle(Path(temporary))
            self._set_forced_march(state, "sf-nato")
            self._set_forced_march(state, "sf-rusa")

            CampaignEngine(state, random_seed=0).apply_external_battle_result(
                Faction.RUSSIA,
                survivors={},
            )

            self._assert_operational(state, "sf-nato")
            self._assert_operational(state, "sf-rusa")

    def test_s9b_external_result_preserves_winning_entrenched_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = self._node_battle(Path(temporary))
            nato = state.strategic_formations["sf-nato"]
            rusa = state.strategic_formations["sf-rusa"]
            nato.stance = FormationStance.ENTRENCHED.value
            rusa.stance = FormationStance.ENTRENCHED.value
            assert nato.move_order is not None
            nato.move_order = replace(
                nato.move_order,
                locked_stance=FormationStance.ENTRENCHED.value,
            )

            CampaignEngine(state, random_seed=0).apply_external_battle_result(
                Faction.RUSSIA,
                survivors={},
            )

            self.assertEqual(FormationStance.OPERATIONAL.value, nato.stance)
            self.assertEqual(FormationStance.ENTRENCHED.value, rusa.stance)


class OperationalS9BDerivedPersistenceTests(unittest.TestCase):
    def _edge_state(self, root: Path):
        helper = OperationalS9BEdgeBlockingTests()
        return helper._stationary_contact_state(
            root,
            blocker_stance=FormationStance.OPERATIONAL.value,
        )

    def _contact_snapshot(self, state, report: dict) -> dict:
        pending = state.pending_battle
        participants = []
        if pending is not None:
            participants = sorted(
                (
                    side,
                    participant.battalion_id,
                    participant.faction.value,
                )
                for side, rows in (
                    ("attacker", pending.attacking_participants),
                    ("defender", pending.defending_participants),
                )
                for participant in rows
            )
        return {
            "kind": pending.encounter_kind if pending is not None else "",
            "participants": participants,
            "edge": pending.encounter_edge_id if pending is not None else "",
            "progress": (
                pending.encounter_progress_milli if pending is not None else None
            ),
            "positions": {
                formation_id: (
                    force.position.mode if force.position is not None else None,
                    force.position.node_id if force.position is not None else None,
                    force.position.edge_id if force.position is not None else None,
                    force.position.progress_milli if force.position is not None else None,
                    force.position.facing_node_id if force.position is not None else None,
                )
                for formation_id, force in sorted(state.strategic_formations.items())
            },
            "orders": {
                formation_id: (
                    force.move_order.status if force.move_order is not None else None,
                    (
                        force.move_order.locked_stance
                        if force.move_order is not None
                        else None
                    ),
                )
                for formation_id, force in sorted(state.strategic_formations.items())
            },
            "stances": {
                formation_id: force.stance
                for formation_id, force in sorted(state.strategic_formations.items())
            },
            "tick": {
                "advanced": report.get("advanced"),
                "swept_kind": report.get("swept_kind"),
                "moved": sorted(report.get("moved") or []),
                "reason": report.get("reason"),
            },
        }

    def test_s9b_save_load_reconstructs_blocking_from_position_without_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, _edge, _na, _nb = self._edge_state(root)
            payload = state.to_dict()
            for row in payload["strategic_formations"].values():
                self.assertFalse(
                    any("block" in str(key).lower() for key in row),
                    row,
                )
            self.assertNotIn("is_blocking", json.dumps(payload, sort_keys=True))

            campaign_path = root / "campaign.json"
            save_campaign(state, campaign_path)
            loaded = load_campaign(campaign_path)

            original_report = advance_operational_tick(state)
            loaded_report = advance_operational_tick(loaded)

            self.assertEqual(
                self._contact_snapshot(state, original_report),
                self._contact_snapshot(loaded, loaded_report),
            )

    def test_s9b_moving_removing_or_changing_side_clears_edge_obstruction(self) -> None:
        for clearing in ("move_away", "remove", "change_side"):
            with self.subTest(clearing=clearing), tempfile.TemporaryDirectory() as temporary:
                state, _edge, _na, nb = self._edge_state(Path(temporary))
                blocker = state.strategic_formations["sf-r"]
                if clearing == "move_away":
                    blocker.position = FormationOperationalPosition(
                        mode=PositionMode.AT_NODE.value,
                        node_id=stable_node_id("c"),
                        progress_milli=0,
                    )
                    blocker.province_id = "c"
                    state.battalions["bn-r"].province_id = "c"
                elif clearing == "remove":
                    CampaignEngine(state)._eliminate_formation(
                        "sf-r",
                        reason="surrendered",
                    )
                else:
                    blocker.faction = Faction.NATO
                    state.battalions["bn-r"].faction = Faction.NATO

                report = advance_operational_tick(state)

                self.assertIsNone(state.pending_battle)
                self.assertNotEqual(
                    ENCOUNTER_KIND_EDGE_CATCHUP,
                    report.get("swept_kind"),
                )
                mover = state.strategic_formations["sf-n"]
                assert mover.position is not None
                self.assertEqual(PositionMode.AT_NODE.value, mover.position.mode)
                self.assertEqual(nb, mover.position.node_id)

    def test_s9b_retreat_clears_node_obstruction_for_following_movement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = s9a_fixture._state(Path(temporary))
            helper = s9a_fixture.OperationalS9AFinalizationTests()
            helper._node_battle(state)

            CampaignEngine(state, random_seed=0).apply_battle_result(Faction.NATO)

            self.assertNotEqual(
                stable_node_id("b"),
                state.strategic_formations["sf-rusa"].position.node_id,
            )
            follow = s9a_fixture._add_force(
                state,
                "sf-follow",
                "bn-follow",
                Faction.NATO,
                "a",
            )
            na, nb = stable_node_id("a"), stable_node_id("b")
            edge = stable_edge_id("corridor", na, nb)
            issue_move_order(
                state,
                follow.strategic_formation_id,
                path_node_ids=[na, nb],
                path_edge_ids=[edge],
                order_id="s9b-follow-after-retreat",
            )
            commit_move_orders(state, faction=Faction.NATO.value)
            activate_committed_orders(state)

            report = advance_operational_tick(state)

            self.assertIsNone(state.pending_battle)
            self.assertNotEqual("node_contact", report.get("swept_kind"))
            assert follow.position is not None
            self.assertEqual(nb, follow.position.node_id)

    def test_s9b_cut_off_and_grace_formations_still_block(self) -> None:
        supply_shapes = (
            {
                "supplied": False,
                "cut_off": True,
                "grace_ticks_remaining": 0,
            },
            {
                "supplied": True,
                "cut_off": False,
                "grace_ticks_remaining": 1,
            },
        )
        for shape in supply_shapes:
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as temporary:
                state, _edge, _na, _nb = self._edge_state(Path(temporary))
                blocker = state.strategic_formations["sf-r"]
                blocker.supplied = shape["supplied"]
                blocker.cut_off = shape["cut_off"]
                blocker.source_hub_id = None
                blocker.route_cost = None
                blocker.grace_ticks_remaining = shape["grace_ticks_remaining"]
                state.validate()

                report = advance_operational_tick(state)

                self.assertEqual(
                    ENCOUNTER_KIND_EDGE_CATCHUP,
                    report.get("swept_kind"),
                )
                self.assertIsNotNone(state.pending_battle)

    def test_s9b_repeated_runs_and_insertion_order_are_identical(self) -> None:
        snapshots = []
        for reverse in (False, True, False):
            with tempfile.TemporaryDirectory() as temporary:
                state, _edge, _na, _nb = self._edge_state(Path(temporary))
                if reverse:
                    state.strategic_formations = dict(
                        reversed(list(state.strategic_formations.items()))
                    )
                report = advance_operational_tick(state)
                snapshots.append(self._contact_snapshot(state, report))

        self.assertEqual(snapshots[0], snapshots[1])
        self.assertEqual(snapshots[0], snapshots[2])


if __name__ == "__main__":
    unittest.main()
