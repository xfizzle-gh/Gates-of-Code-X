from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.earth3_bootstrap import Earth3BootstrapError
from gates_of_codex.frontend_commands import _apply_one
from gates_of_codex.models import Faction
from gates_of_codex.state_io import campaign_from_dict
from gates_of_codex.strategic_ai import StrategicAI
from gates_of_codex.supply import refresh_all_supply, supply_status_for_faction

from test_p2_earth3_campaign_bootstrap import _campaign


class P2PersistedP1AuthorityTests(unittest.TestCase):
    def test_p2_state_validation_rejects_persisted_p1_authority_tampering(self) -> None:
        mutations = (
            lambda state: state.map_metadata.__setitem__("manifest_sha256", "0" * 64),
            lambda state: state.provinces["e3_0592"].metadata.__setitem__("source_id", -1),
            lambda state: state.provinces["e3_0592"].metadata.__setitem__("selectable", False),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                state = _campaign()
                mutate(state)
                with self.assertRaises(Earth3BootstrapError):
                    state.validate()

    def test_p2_state_validation_rejects_reciprocal_topology_tampering(self) -> None:
        state = _campaign()
        province = next(
            value for value in state.provinces.values() if value.neighbors
        )
        neighbor_id = province.neighbors[0]
        province.neighbors.remove(neighbor_id)
        state.provinces[neighbor_id].neighbors.remove(province.province_id)
        with self.assertRaisesRegex(Earth3BootstrapError, "topology"):
            state.validate()

    def test_p2_load_rejects_persisted_p1_metadata_tampering(self) -> None:
        payload = _campaign().to_dict()
        payload["map_metadata"]["dataset_sha256"] = "f" * 64
        with self.assertRaises(Earth3BootstrapError):
            campaign_from_dict(payload)


class P2StrictActorAuthorityTests(unittest.TestCase):
    def test_same_side_formation_actor_swap_is_rejected_without_normalization(self) -> None:
        state = _campaign()
        force = state.strategic_formations["sf_deu_berlin"]
        force.actor_id = "usa"
        with self.assertRaisesRegex(Earth3BootstrapError, "actor assignment"):
            state.validate()
        self.assertEqual("usa", force.actor_id)

    def test_missing_actor_and_opening_province_actor_swap_are_rejected(self) -> None:
        state = _campaign()
        state.strategic_formations["sf_pol_vilnius"].actor_id = ""
        with self.assertRaisesRegex(Earth3BootstrapError, "missing or invalid"):
            state.validate()

        state = _campaign()
        state.provinces["e3_0592"].metadata["owner_actor_id"] = "usa"
        with self.assertRaisesRegex(Earth3BootstrapError, "province actor assignment"):
            state.validate()

    def test_reinforcement_and_roster_cross_actor_leakage_is_rejected(self) -> None:
        state = _campaign()
        runtime = state.map_metadata["actor_content_runtime"]
        usa_unit = next(iter(runtime["actors"]["usa"]["units"]))
        runtime["reinforcement_pool"] = [
            {
                "actor_id": "usa",
                "strategic_formation_id": "sf_deu_berlin",
                "unit_name": usa_unit,
                "quantity": 1,
                "category": "infantry",
                "unit_cost": 1,
            }
        ]
        with self.assertRaisesRegex(Earth3BootstrapError, "actor/formation"):
            state.validate()

        state = _campaign()
        runtime = state.map_metadata["actor_content_runtime"]
        usa_unit = next(iter(runtime["actors"]["usa"]["units"]))
        battalion = state.battalions["bn_sf_deu_berlin"]
        battalion.roster[0].unit_name = usa_unit
        with self.assertRaisesRegex(Earth3BootstrapError, "crosses actor authority"):
            state.validate()


class P2ActorRepairTests(unittest.TestCase):
    def test_frontend_repair_charges_only_owning_actor_at_installed_cost(self) -> None:
        state = _campaign()
        battalion = state.battalions["bn_sf_deu_berlin"]
        battalion.condition = 90
        runtime = state.map_metadata["actor_content_runtime"]
        actor_runtime = state.map_metadata["strategic_actor_runtime"]["actors"]
        deu_before = actor_runtime["deu"]["resources"]
        usa_before = actor_runtime["usa"]["resources"]
        tactical_before = state.factions[Faction.NATO.value].resources
        expected_cost = max(
            1,
            sum(
                runtime["actors"]["deu"]["units"][entry.unit_name]["repair_cost_per_point"]
                * entry.quantity
                for entry in battalion.roster
            ),
        )

        result = _apply_one(
            state,
            "repair",
            {"actor": "deu", "formation_id": "sf_deu_berlin", "points": 1},
        )
        actor_after = state.map_metadata["strategic_actor_runtime"]["actors"]

        self.assertTrue(result.ok)
        self.assertEqual(expected_cost, result.data["cost"])
        self.assertEqual(deu_before - expected_cost, actor_after["deu"]["resources"])
        self.assertEqual(usa_before, actor_after["usa"]["resources"])
        self.assertEqual(tactical_before, state.factions[Faction.NATO.value].resources)

    def test_frontend_repair_rejects_insufficient_owning_actor_funds_without_mutation(self) -> None:
        state = _campaign()
        battalion = state.battalions["bn_sf_pol_vilnius"]
        battalion.condition = 90
        actors = state.map_metadata["strategic_actor_runtime"]["actors"]
        actors["pol"]["resources"] = 0
        usa_before = actors["usa"]["resources"]
        with self.assertRaisesRegex(ValueError, "Insufficient resources"):
            _apply_one(
                state,
                "repair",
                {"actor": "pol", "formation_id": "sf_pol_vilnius", "points": 1},
            )
        self.assertEqual(90, battalion.condition)
        self.assertEqual(0, actors["pol"]["resources"])
        self.assertEqual(usa_before, actors["usa"]["resources"])


class P2SupplyBoundaryTests(unittest.TestCase):
    @staticmethod
    def _supply_snapshot(state) -> dict[str, tuple]:
        return {
            key: (
                battalion.supply,
                battalion.condition,
                tuple((row.unit_name, row.quantity) for row in battalion.roster),
                battalion.encircled_turns,
                battalion.movement_remaining,
                battalion.combat_actions_remaining,
            )
            for key, battalion in state.battalions.items()
        }

    def test_supply_status_and_refresh_remain_disabled_until_p3(self) -> None:
        state = _campaign()
        before = self._supply_snapshot(state)
        report = supply_status_for_faction(state, Faction.NATO)
        self.assertEqual("none_until_p3", report.authority)
        self.assertEqual((), report.sources)
        self.assertIsNone(report.reachable_provinces)
        refresh_all_supply(state)
        self.assertEqual(before, self._supply_snapshot(state))

    def test_full_round_does_not_apply_adjacency_supply_or_attrition(self) -> None:
        state = _campaign()
        actors = state.map_metadata["strategic_actor_runtime"]["actors"]
        for actor in actors.values():
            actor["resources"] = max(int(actor["resources"]), 1_000_000)
        before = self._supply_snapshot(state)
        starting_turn = state.turn_number
        engine = CampaignEngine(state)
        for _ in range(8):
            engine.end_turn()
            if state.turn_number > starting_turn:
                break
        self.assertGreater(state.turn_number, starting_turn)
        self.assertEqual(before, self._supply_snapshot(state))


class P2ActorAIEconomyDispatchTests(unittest.TestCase):
    def test_actor_runtime_ai_economy_runs_without_legacy_catalogs(self) -> None:
        state = _campaign()
        self.assertFalse(state.unit_economy)
        self.assertFalse(state.research_nodes)
        action = {
            "action": "research",
            "formation_id": "sf_ukr_kyiv",
            "key": "actor:ukr:root",
        }
        with patch(
            "gates_of_codex.strategic_ai.run_ai_economy",
            return_value=[copy.deepcopy(action)],
        ) as economy, patch(
            "gates_of_codex.strategic_ai.run_ai_construction",
            return_value=None,
        ):
            actions = StrategicAI(state).take_turn(Faction.UKRAINE)
        economy.assert_called_once_with(state, Faction.UKRAINE)
        self.assertEqual("research", actions[0].action)
        self.assertEqual("sf_ukr_kyiv", actions[0].battalion_id)


if __name__ == "__main__":
    unittest.main()
