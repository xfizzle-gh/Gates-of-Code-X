from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.models import Alliance, Faction, FormationOperationalPosition, PositionMode
from gates_of_codex.observation import refresh_all_observer_knowledge
from gates_of_codex.operational_movement import (
    commit_formation_move_order,
    issue_move_order,
)
from tests.test_s11_detection import _site, _state


class S11FrontendTests(unittest.TestCase):
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
