from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict, fields
from pathlib import Path

from gates_of_codex.models import (
    BattleParticipant,
    Faction,
    FormationOperationalPosition,
    PendingBattle,
    PositionMode,
)
from gates_of_codex.observation import refresh_all_observer_knowledge
from gates_of_codex.operational_movement import (
    commit_formation_move_order,
    issue_move_order,
)
from gates_of_codex.operational_ai import (
    OperationalIntent,
    OperationalPlanningView,
    build_operational_planning_view,
    plan_operational_intents,
    validate_and_commit_operational_intents,
)
from tests.test_s11_detection import _site, _state


class S11OperationalAITests(unittest.TestCase):
    def test_view_has_no_campaign_reference_or_callbacks_and_hides_contact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            state.formations["toe-rusa"].notes = "secret-enemy-doctrine"
            state.map_metadata["last_round_economy"] = [
                {"faction": "rusa", "secret_enemy_resources": 999999}
            ]
            state.map_metadata["unit_presentations"] = {
                "bn-enemy-c": {"secret_enemy_card": True}
            }
            view = build_operational_planning_view(state, Faction.NATO)
            self.assertIsInstance(view, OperationalPlanningView)
            self.assertNotIn("state", {field.name for field in fields(view)})
            self.assertNotIn("enemy-c", view.campaign_payload_json)
            self.assertNotIn("toe-rusa", view.campaign_payload_json)
            self.assertNotIn("secret-enemy-doctrine", view.campaign_payload_json)
            self.assertNotIn("secret_enemy_resources", view.campaign_payload_json)
            self.assertNotIn("secret_enemy_card", view.campaign_payload_json)
            self.assertIn("contact-", view.campaign_payload_json)
            self.assertFalse(any(callable(getattr(view, field.name)) for field in fields(view)))

    def test_identical_visible_view_yields_identical_intents_despite_hidden_truth(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            refresh_all_observer_knowledge(state)
            state.map_metadata["operational_site_control"]["obs"]["controller_faction"] = "rusa"
            state.strategic_formations["enemy-c"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id="nb", progress_milli=0
            )
            view_a = build_operational_planning_view(state, Faction.NATO)
            state.strategic_formations["enemy-c"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id="nc", progress_milli=0
            )
            view_b = build_operational_planning_view(state, Faction.NATO)
            self.assertEqual(view_a.campaign_payload_json, view_b.campaign_payload_json)
            self.assertEqual(
                plan_operational_intents(view_a, Faction.NATO, 7),
                plan_operational_intents(view_b, Faction.NATO, 7),
            )

    def test_planning_is_pure_and_executor_does_not_retarget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            before = json.dumps(state.to_dict(), sort_keys=True)
            view = build_operational_planning_view(state, Faction.NATO)
            _ = plan_operational_intents(view, Faction.NATO, 1)
            self.assertEqual(before, json.dumps(state.to_dict(), sort_keys=True))

            bad = OperationalIntent(
                formation_id="recon-a",
                action="operational_move",
                battalion_id="bn-recon-a",
                origin_province_id="a",
                target_province_id="c",
                details_json='{"formation_id":"recon-a"}',
                path_node_ids=("na", "nc"),
                path_edge_ids=("missing-edge",),
                order_id="ord-bad",
                locked_stance="operational",
            )
            actions = validate_and_commit_operational_intents(state, Faction.NATO, [bad])
            self.assertEqual("reject", actions[0].action)
            self.assertEqual("route_unavailable", actions[0].details["reason"])
            self.assertIsNone(state.strategic_formations["recon-a"].move_order)



    def test_contact_on_edge_uses_public_canonical_position_without_direction_leak(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            enemy = state.strategic_formations["enemy-c"]
            enemy.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id="ebc",
                facing_node_id="nc",
                progress_milli=875,
            )
            view = build_operational_planning_view(state, Faction.NATO)
            payload = json.loads(view.campaign_payload_json)
            contacts = [
                row for key, row in payload["strategic_formations"].items()
                if key.startswith("contact-")
            ]
            self.assertEqual(1, len(contacts))
            self.assertEqual(
                {
                    "mode": "on_edge",
                    "node_id": None,
                    "edge_id": "ebc",
                    "progress_milli": 500,
                    "facing_node_id": "nb",
                },
                contacts[0]["position"],
            )
            self.assertNotIn('"progress_milli":875', view.campaign_payload_json)

    def test_executor_rejection_preserves_preexisting_locked_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            issue_move_order(
                state,
                "recon-a",
                path_node_ids=["na", "nb"],
                path_edge_ids=["eab"],
                order_id="existing-order",
            )
            commit_formation_move_order(
                state, "recon-a", locked_stance="operational"
            )
            before = json.dumps(
                asdict(state.strategic_formations["recon-a"].move_order),
                sort_keys=True,
            )
            bad = OperationalIntent(
                formation_id="recon-a",
                action="operational_move",
                battalion_id="bn-recon-a",
                origin_province_id="a",
                target_province_id="c",
                details_json='{"formation_id":"recon-a"}',
                path_node_ids=("na", "nc"),
                path_edge_ids=("missing-edge",),
                order_id="replacement-order",
                locked_stance="operational",
            )
            result = validate_and_commit_operational_intents(
                state, Faction.NATO, [bad]
            )
            self.assertEqual("reject", result[0].action)
            order = state.strategic_formations["recon-a"].move_order
            self.assertIsNotNone(order)
            after = json.dumps(asdict(order), sort_keys=True)
            self.assertEqual(before, after)

    def test_pending_direct_contact_remains_plannable_without_hidden_reranking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            enemy = state.strategic_formations["enemy-c"]
            enemy.province_id = "a"
            enemy.position.node_id = "na"
            state.battalions["bn-enemy-c"].province_id = "a"
            state.pending_battle = PendingBattle(
                battle_id="battle-direct",
                origin_province_id="a",
                target_province_id="a",
                attacker_faction=Faction.NATO,
                defender_faction=Faction.RUSSIA,
                attacking_participants=[
                    BattleParticipant(
                        "bn-recon-a", Faction.NATO, "primary", is_primary=True
                    )
                ],
                defending_participants=[
                    BattleParticipant(
                        "bn-enemy-c", Faction.RUSSIA, "primary", is_primary=True
                    )
                ],
                player_faction=Faction.NATO,
                player_is_attacker=True,
                encounter_node_id="na",
                encounter_kind="node_contact",
                attacker_formation_id="recon-a",
                defender_formation_id="enemy-c",
            )
            view = build_operational_planning_view(state, Faction.NATO)
            payload = json.loads(view.campaign_payload_json)
            self.assertIsNone(payload["pending_battle"])
            self.assertTrue(payload["map_metadata"]["operational_pause"])
            intents = plan_operational_intents(view, Faction.NATO, 0)
            self.assertEqual(1, len(intents))
            self.assertEqual("hold_pending_battle", intents[0].action)

    def test_unrelated_pending_battle_is_only_a_public_pause_marker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.factions["ukr"] = type(state.factions["nato"])(Faction.UKRAINE)
            state.map_metadata["operational_edge_retreat_nodes"] = {
                "hidden-retreat-formation": "hidden-retreat-node"
            }
            state.pending_battle = PendingBattle(
                battle_id="hidden-battle-id",
                origin_province_id="hidden-origin",
                target_province_id="hidden-target",
                attacker_faction=Faction.NATO,
                defender_faction=Faction.RUSSIA,
                attacking_participants=[
                    BattleParticipant(
                        "bn-recon-a", Faction.NATO, "hidden-stage",
                        contact_initiator=True, ambush_triggered=True,
                    )
                ],
                defending_participants=[
                    BattleParticipant("bn-enemy-c", Faction.RUSSIA, "hidden-defender")
                ],
                player_faction=Faction.NATO,
                player_is_attacker=True,
                encounter_node_id="hidden-node",
                encounter_kind="hidden-ambush",
                attacker_formation_id="recon-a",
                defender_formation_id="enemy-c",
                encounter_edge_id="hidden-edge",
                encounter_progress_milli=777,
                encounter_pixel=[99, 88],
            )
            view = build_operational_planning_view(state, Faction.UKRAINE)
            payload = json.loads(view.campaign_payload_json)
            self.assertIsNone(payload["pending_battle"])
            self.assertTrue(payload["map_metadata"]["operational_pause"])
            for secret in (
                "hidden-battle-id", "hidden-origin", "hidden-target",
                "hidden-stage", "hidden-defender", "hidden-node",
                "hidden-edge", "hidden-ambush", '"progress_milli":777',
                '"contact_initiator":true', '"ambush_triggered":true',
                "hidden-retreat-formation", "hidden-retreat-node",
            ):
                self.assertNotIn(secret, view.campaign_payload_json)
            intents = plan_operational_intents(view, Faction.UKRAINE, 0)
            self.assertEqual("hold_pending_battle", intents[0].action)

    def test_fog_off_uses_complete_two_stage_view(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.fog_of_war_enabled = False
            view = build_operational_planning_view(state, Faction.NATO)
            self.assertFalse(view.fog_of_war_enabled)
            self.assertIn("enemy-c", view.campaign_payload_json)
            self.assertEqual(tuple(sorted(state.strategic_formations)), view.visible_subject_keys)


if __name__ == "__main__":
    unittest.main()
