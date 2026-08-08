from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.models import (
    Alliance,
    BattleParticipant,
    Faction,
    FactionState,
    FormationOperationalPosition,
    PendingBattle,
    PositionMode,
)
from gates_of_codex.observation import refresh_all_observer_knowledge
from gates_of_codex.operational_movement import (
    commit_formation_move_order,
    issue_move_order,
)
from tests.test_s11_detection import _site, _state


class S11FrontendTests(unittest.TestCase):
    @staticmethod
    def _pending_battle(state, *, attacker: Faction = Faction.NATO) -> None:
        defender = Faction.RUSSIA if attacker == Faction.NATO else Faction.NATO
        attacker_id = "bn-recon-a" if attacker == Faction.NATO else "bn-enemy-c"
        defender_id = "bn-enemy-c" if defender == Faction.RUSSIA else "bn-recon-a"
        state.pending_battle = PendingBattle(
            battle_id="secret-battle-id",
            origin_province_id="secret-origin",
            target_province_id="secret-target",
            attacker_faction=attacker,
            defender_faction=defender,
            attacking_participants=[
                BattleParticipant(
                    attacker_id,
                    attacker,
                    "secret-attacker-stage",
                    is_primary=True,
                    contact_initiator=True,
                    ambush_eligible=True,
                    ambush_triggered=True,
                    ambush_strength_multiplier_milli=1500,
                    ambush_readiness_consumed=True,
                )
            ],
            defending_participants=[
                BattleParticipant(
                    defender_id,
                    defender,
                    "secret-defender-stage",
                    is_primary=True,
                )
            ],
            player_faction=attacker,
            player_is_attacker=True,
            encounter_node_id="secret-node",
            encounter_kind="secret-ambush-kind",
            attacker_formation_id="recon-a" if attacker == Faction.NATO else "enemy-c",
            defender_formation_id="enemy-c" if defender == Faction.RUSSIA else "recon-a",
            encounter_edge_id="secret-edge",
            encounter_progress_milli=777,
            encounter_pixel=[321, 654],
        )

    def test_fog_off_keeps_complete_information_and_alliance_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.fog_of_war_enabled = False
            state.alliances = {
                "one": Alliance("one", "One", [Faction.NATO, Faction.RUSSIA]),
                "two": Alliance("two", "Two", [Faction.NATO, Faction.RUSSIA]),
            }
            snapshot = build_frontend_snapshot(state)
            self.assertEqual(14, FRONTEND_SCHEMA_VERSION)
            self.assertEqual(14, snapshot["schema_version"])
            self.assertFalse(snapshot["fog_of_war"]["enabled"])
            self.assertEqual(2, len(snapshot["strategic_formations"]))
            self.assertEqual(2, len(snapshot["battalions"]))

    def test_contact_filters_identity_battalions_and_side_channels(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            state.strategic_formations["enemy-c"].province_id = "b"
            state.strategic_formations["enemy-c"].position.node_id = "nb"
            state.battalions["bn-enemy-c"].province_id = "b"
            state.map_metadata["unit_presentations"] = {
                "bn-enemy-c": {"secret_enemy_presentation": True}
            }
            state.provinces["c"].resource_yield = 777
            state.provinces["c"].fortification = 9
            state.provinces["c"].metadata["secret_enemy_province"] = True
            state.map_metadata["last_round_economy"] = [
                {"faction": "rusa", "resources": 999999}
            ]
            before = json.dumps(state.to_dict(), sort_keys=True)
            snapshot = build_frontend_snapshot(state)
            after = json.dumps(state.to_dict(), sort_keys=True)
            self.assertEqual(before, after)
            self.assertTrue(snapshot["fog_of_war"]["enabled"])
            enemy = [row for row in snapshot["strategic_formations"] if row.get("information_tier") == "contact"]
            self.assertEqual(1, len(enemy))
            row = enemy[0]
            self.assertTrue(row["id"].startswith("contact-"))
            self.assertNotIn("subject_formation_id", row)
            self.assertNotIn("display_name", row)
            self.assertNotIn("faction", row)
            self.assertNotIn("move_order", row)
            self.assertEqual(["bn-recon-a"], [row["id"] for row in snapshot["battalions"]])
            self.assertEqual(["recon-a"], sorted(snapshot["strategic_formation_presentations"]))
            self.assertEqual([], snapshot["front_options"])
            self.assertNotIn("operational_site_control", snapshot["campaign"]["map_metadata"])
            self.assertNotIn("unit_presentations", snapshot["campaign"]["map_metadata"])
            self.assertNotIn("last_round_economy", snapshot["campaign"]["map_metadata"])
            serialized = json.dumps(snapshot, sort_keys=True)
            self.assertNotIn("enemy-c", serialized)
            self.assertNotIn("bn-enemy-c", serialized)
            self.assertNotIn("toe-rusa", serialized)
            self.assertNotIn("secret_enemy_presentation", serialized)
            self.assertNotIn("secret_enemy_province", serialized)
            enemy_province = next(
                item for item in snapshot["provinces"] if item["id"] == "c"
            )
            self.assertNotIn("resource_yield", enemy_province)
            self.assertNotIn("fortification", enemy_province)

    def test_identified_and_assessed_fields_are_tier_limited(self) -> None:
        sites = [
            _site("obs", "nb", "b", "observation"),
            _site("cmd", "nb", "b", "command"),
        ]
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=sites)
            state.strategic_formations["recon-a"].recon_capability = False
            snapshot = build_frontend_snapshot(state)
            row = next(item for item in snapshot["strategic_formations"] if item.get("faction") == "rusa")
            self.assertEqual("identified", row["information_tier"])
            self.assertIn("display_name", row)
            self.assertNotIn("strength_band", row)
            self.assertNotIn("condition_summary", row)
            self.assertEqual(["toe-nato"], [item["id"] for item in snapshot["formations"]])
            self.assertNotIn("enemy-c", snapshot["strategic_formation_presentations"])

            state.strategic_formations["recon-a"].recon_capability = True
            state.strategic_formations["enemy-c"].province_id = "b"
            state.strategic_formations["enemy-c"].position.node_id = "nb"
            state.battalions["bn-enemy-c"].province_id = "b"
            snapshot = build_frontend_snapshot(state)
            row = next(item for item in snapshot["strategic_formations"] if item.get("faction") == "rusa")
            self.assertEqual("assessed", row["information_tier"])
            self.assertIn("strength_band", row)
            self.assertNotIn("condition_summary", row)
            self.assertNotIn("move_order", row)



    def test_fully_observed_enemy_still_hides_orders_and_doctrine_side_channels(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.formations["toe-rusa"].notes = "secret-enemy-doctrine"
            issue_move_order(
                state,
                "enemy-c",
                path_node_ids=["nc", "nb"],
                path_edge_ids=["ebc"],
                order_id="secret-enemy-order",
            )
            commit_formation_move_order(
                state, "enemy-c", locked_stance="operational"
            )
            friendly = state.strategic_formations["recon-a"]
            friendly.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id="nc", progress_milli=0
            )
            friendly.province_id = "c"
            state.battalions["bn-recon-a"].province_id = "c"

            snapshot = build_frontend_snapshot(state)
            enemy_row = next(
                row for row in snapshot["strategic_formations"]
                if row.get("id") == "enemy-c"
            )
            self.assertEqual("fully_observed", enemy_row["information_tier"])
            self.assertNotIn("move_order", enemy_row)
            self.assertNotIn(
                "move_order",
                snapshot["strategic_formation_presentations"]["enemy-c"],
            )
            enemy_template = next(
                row for row in snapshot["formations"] if row["id"] == "toe-rusa"
            )
            self.assertNotIn("notes", enemy_template)
            self.assertNotIn("recruitment_offers", enemy_template)
            serialized = json.dumps(snapshot, sort_keys=True)
            self.assertNotIn("secret-enemy-order", serialized)
            self.assertNotIn("secret-enemy-doctrine", serialized)

    def test_ai_active_enemy_options_never_enter_human_fog_snapshot(self) -> None:
        for kind, owner in (("move", Faction.RUSSIA), ("capture", Faction.NATO)):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                state = _state(Path(td))
                state.current_faction = Faction.RUSSIA
                state.provinces["b"].owner = owner
                # Direct observation permits exact enemy presentation, never command authority.
                friendly = state.strategic_formations["recon-a"]
                friendly.position.node_id = "nc"
                friendly.province_id = "c"
                state.battalions["bn-recon-a"].province_id = "c"
                snapshot = build_frontend_snapshot(state)

                self.assertEqual([], snapshot["front_options"])
                enemy = snapshot["battalion_presentations"]["bn-enemy-c"]
                self.assertFalse(enemy["can_act"])
                self.assertEqual(0, enemy["legal_option_count"])
                self.assertEqual([], enemy["legal_options"])
                self.assertFalse(
                    snapshot["strategic_formation_presentations"]["enemy-c"]["can_act"]
                )
                serialized = json.dumps(snapshot, sort_keys=True)
                for secret in (
                    "move bn-enemy-c b",
                    '"origin": "c"',
                    '"target": "b"',
                    '"battalion_id": "bn-enemy-c"',
                ):
                    self.assertNotIn(secret, serialized)

                state.fog_of_war_enabled = False
                fog_off = build_frontend_snapshot(state)
                option = next(
                    row for row in fog_off["front_options"]
                    if row["battalion_id"] == "bn-enemy-c"
                )
                self.assertEqual(kind, option["kind"])
                self.assertEqual([], option["enemies"])
                self.assertEqual("c", option["origin"])
                self.assertEqual("b", option["target"])

    def test_pending_battle_full_contract_only_for_participating_observer(self) -> None:
        for observer, attacker in (
            (Faction.NATO, Faction.NATO),
            (Faction.RUSSIA, Faction.NATO),
        ):
            with self.subTest(observer=observer.value), tempfile.TemporaryDirectory() as td:
                state = _state(Path(td))
                state.factions["nato"].is_human_controlled = observer == Faction.NATO
                state.factions["rusa"].is_human_controlled = observer == Faction.RUSSIA
                self._pending_battle(state, attacker=attacker)
                pending = build_frontend_snapshot(state)["pending_battle"]
                self.assertEqual("secret-battle-id", pending["id"])
                self.assertIn("attacking_participants", pending)
                self.assertEqual(777, pending["encounter_progress_milli"])

        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            state.factions["nato"].is_human_controlled = False
            state.factions["ukr"] = FactionState(
                Faction.UKRAINE, is_human_controlled=True
            )
            state.map_metadata["operational_edge_retreat_nodes"] = {
                "secret-retreat-formation": "secret-retreat-node"
            }
            self._pending_battle(state)
            snapshot = build_frontend_snapshot(state)
            pending = snapshot["pending_battle"]
            self.assertEqual({"operational_pause": True}, pending)
            serialized = json.dumps(snapshot, sort_keys=True)
            for secret in (
                "secret-battle-id",
                "bn-recon-a",
                "bn-enemy-c",
                "secret-origin",
                "secret-target",
                "secret-node",
                "secret-edge",
                "777",
                "contact_initiator",
                "ambush",
                "secret-attacker-stage",
                "secret-retreat-formation",
                "secret-retreat-node",
            ):
                self.assertNotIn(secret, serialized)

    def test_stale_fully_observed_edge_uses_recorded_progress(self) -> None:
        cases = ((0, 100), (250, 125), (500, 150), (750, 175), (1000, 200))
        for progress, expected_x in cases:
            with self.subTest(progress=progress), tempfile.TemporaryDirectory() as td:
                state = _state(Path(td))
                graph_path = Path(state.map_metadata["operational_graph"])
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                for node in graph["nodes"]:
                    if node["node_id"] == "nb":
                        node["pixel"] = [100, 20]
                    elif node["node_id"] == "nc":
                        node["pixel"] = [200, 20]
                graph_path.write_text(json.dumps(graph), encoding="utf-8")
                enemy = state.strategic_formations["enemy-c"]
                enemy.position = FormationOperationalPosition(
                    mode=PositionMode.ON_EDGE.value,
                    edge_id="ebc",
                    facing_node_id="nc",
                    progress_milli=progress,
                )
                self._pending_battle(state)
                refresh_all_observer_knowledge(state)
                state.pending_battle = None
                state.strategic_formations["recon-a"].recon_capability = False

                stale = build_frontend_snapshot(state)["last_known_contacts"]
                self.assertEqual(1, len(stale))
                self.assertEqual(progress, stale[0]["last_seen_progress_milli"])
                self.assertEqual([expected_x, 20], stale[0]["display_pixel"])

    def test_reversed_edge_and_lower_tiers_do_not_infer_exact_progress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            graph_path = Path(state.map_metadata["operational_graph"])
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            for node in graph["nodes"]:
                if node["node_id"] == "nb":
                    node["pixel"] = [100, 20]
                elif node["node_id"] == "nc":
                    node["pixel"] = [200, 20]
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            state.strategic_formations["recon-a"].recon_capability = False
            enemy = state.strategic_formations["enemy-c"]
            enemy.position = FormationOperationalPosition(
                mode=PositionMode.ON_EDGE.value,
                edge_id="ebc",
                facing_node_id="nb",
                progress_milli=250,
            )
            self._pending_battle(state)
            refresh_all_observer_knowledge(state)
            state.pending_battle = None
            state.map_metadata["operational_site_control"]["obs"][
                "controller_faction"
            ] = "rusa"
            stale = build_frontend_snapshot(state)["last_known_contacts"][0]
            self.assertEqual([175, 20], stale["display_pixel"])

            state.map_metadata["operational_site_control"]["obs"][
                "controller_faction"
            ] = "nato"
            current = next(
                row for row in build_frontend_snapshot(state)["strategic_formations"]
                if row.get("id") == "enemy-c"
            )
            self.assertEqual("identified", current["information_tier"])
            self.assertEqual([150, 20], current["display_pixel"])
            self.assertNotIn("last_seen_progress_milli", current)

    def test_stack_summary_is_omitted_when_it_would_aggregate_hidden_enemy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td))
            graph_path = Path(state.map_metadata["operational_graph"])
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph["nodes"].append({
                "node_id": "na-hidden",
                "display_name": "hidden",
                "pixel": [2, 2],
                "province_id": "a",
                "site_id": None,
                "kind": "anchor",
                "terrain": "plain",
                "metadata": {},
            })
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            enemy = state.strategic_formations["enemy-c"]
            enemy.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id="na-hidden",
                progress_milli=0,
            )
            enemy.province_id = "a"
            state.battalions["bn-enemy-c"].province_id = "a"

            snapshot = build_frontend_snapshot(state)
            self.assertEqual(
                ["bn-recon-a"], snapshot["battalion_stacks"]["a"]
            )
            self.assertNotIn("a", snapshot["stack_presentations"])
            self.assertNotIn("enemy-c", json.dumps(snapshot, sort_keys=True))

    def test_known_identity_is_not_forgotten_when_current_detection_drops_to_contact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            enemy = state.strategic_formations["enemy-c"]
            enemy.position.node_id = "na"
            refresh_all_observer_knowledge(state)

            enemy.position.node_id = "nb"
            enemy.province_id = "b"
            state.battalions["bn-enemy-c"].province_id = "b"
            snapshot = build_frontend_snapshot(state)
            row = next(
                item for item in snapshot["strategic_formations"]
                if item.get("id") == "enemy-c"
            )
            self.assertEqual("identified", row["information_tier"])
            self.assertEqual("enemy-c", row["display_name"])
            self.assertEqual("rusa", row["faction"])
            self.assertNotIn("strength_band", row)

    def test_stale_contact_stays_at_last_observed_location(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            state = _state(Path(td), sites=[_site("obs", "nb", "b", "observation")])
            state.strategic_formations["recon-a"].recon_capability = False
            refresh_all_observer_knowledge(state)
            state.strategic_formations["enemy-c"].position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value, node_id="na", progress_milli=0
            )
            state.map_metadata["operational_site_control"]["obs"]["controller_faction"] = "rusa"
            # No persisted refresh: snapshot is a pure read of current + retained last-known.
            snapshot = build_frontend_snapshot(state)
            stale = snapshot["last_known_contacts"]
            self.assertEqual(1, len(stale))
            self.assertEqual("nc", stale[0]["last_seen_node_id"])
            self.assertEqual([0, 0], stale[0]["display_pixel"])


if __name__ == "__main__":
    unittest.main()
