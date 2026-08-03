from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.codex.catalog import CodeXCatalog, UnitDefinition
from gates_of_codex.economy import (
    assign_reinforcements,
    available_research,
    category_research_key,
    formation_recruitment_offers,
    initialize_economy,
    purchase_reinforcements,
    purchase_research,
    repair_formation,
    run_ai_economy,
    settle_round_economy,
)
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.starter import populate_starter_rosters
from gates_of_codex.state_io import load_campaign, save_campaign


class CampaignEconomyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = self._catalog()
        self.state = load_bundled_scenario()
        populate_starter_rosters(self.state, self.catalog)
        initialize_economy(self.state, self.catalog)
        for faction_state in self.state.factions.values():
            faction_state.resources = 5000

    @staticmethod
    def _catalog() -> CodeXCatalog:
        units: dict[str, UnitDefinition] = {}
        for side in ("nato", "ukr", "rusa", "prc"):
            units[f"rifle({side})"] = UnitDefinition(
                name=f"rifle({side})",
                side=side,
                members={f"rifleman_{side}": 6},
                category="infantry",
                manpower_estimate=6,
            )
            units[f"recon({side})"] = UnitDefinition(
                name=f"recon({side})",
                side=side,
                members={f"scout_{side}": 4},
                category="recon",
                manpower_estimate=4,
            )
            units[f"vehicle({side})"] = UnitDefinition(
                name=f"vehicle({side})",
                side=side,
                vehicles=[f"truck_{side}"],
                category="vehicle",
            )
            units[f"ifv({side})"] = UnitDefinition(
                name=f"ifv({side})",
                side=side,
                vehicles=[f"ifv_{side}"],
                category="ifv",
            )
            units[f"tank({side})"] = UnitDefinition(
                name=f"tank({side})",
                side=side,
                vehicles=[f"tank_{side}"],
                category="tank",
            )
            units[f"artillery({side})"] = UnitDefinition(
                name=f"artillery({side})",
                side=side,
                vehicles=[f"gun_{side}"],
                category="artillery",
            )
            units[f"airdefense({side})"] = UnitDefinition(
                name=f"airdefense({side})",
                side=side,
                vehicles=[f"sam_{side}"],
                category="air_defense",
            )
            units[f"special({side})"] = UnitDefinition(
                name=f"special({side})",
                side=side,
                members={f"specialist_{side}": 5},
                category="infantry",
                manpower_estimate=5,
                doctrine=f"rapid_assault_{side}",
                doctrine_cost=2,
            )
        return CodeXCatalog(units=units, signature="economy-fixture")

    def test_initialization_persists_catalog_and_authorized_strength(self) -> None:
        self.assertEqual("economy-fixture", self.state.catalog_signature)
        self.assertTrue(self.state.research_nodes)
        self.assertTrue(self.state.unit_economy)
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC):
            self.assertIn(
                category_research_key(faction, "infantry"),
                self.state.factions[faction.value].researched_keys,
            )
        for battalion in self.state.battalions.values():
            self.assertEqual(battalion.unit_count, battalion.authorized_unit_count)

    def test_research_prerequisites_unlock_tank_recruitment(self) -> None:
        faction = Faction.NATO
        faction_state = self.state.factions[faction.value]
        faction_state.researched_keys = [category_research_key(faction, "infantry")]
        tank_key = category_research_key(faction, "tank")
        with self.assertRaises(ValueError):
            purchase_research(self.state, faction, tank_key)
        purchase_research(self.state, faction, category_research_key(faction, "vehicle"))
        purchase_research(self.state, faction, category_research_key(faction, "ifv"))
        purchase_research(self.state, faction, tank_key)
        offers = formation_recruitment_offers(self.state, "nato-us-armored")
        tank = next(offer for offer in offers if offer.unit_name == "tank(nato)")
        self.assertTrue(tank.unlocked)
        self.assertFalse(tank.missing_research)

    def test_purchase_pool_transfer_replaces_losses_before_expansion(self) -> None:
        faction = Faction.NATO
        faction_state = self.state.factions[faction.value]
        faction_state.researched_keys = [category_research_key(faction, "infantry")]
        for category in ("vehicle", "ifv", "tank"):
            purchase_research(self.state, faction, category_research_key(faction, category))
        battalion = next(
            value for value in self.state.battalions.values()
            if value.formation_id == "nato-us-armored"
        )
        original_authorized = battalion.authorized_unit_count
        purchase_reinforcements(self.state, "nato-us-armored", "tank(nato)", 2)
        transfer = assign_reinforcements(self.state, "nato-us-armored", "tank(nato)", 2)
        self.assertEqual(0, transfer.replacements)
        self.assertEqual(2, transfer.expansion)
        self.assertEqual(original_authorized + 2, battalion.authorized_unit_count)

        tank_entry = next(entry for entry in battalion.roster if entry.unit_name == "tank(nato)")
        tank_entry.quantity -= 1
        self.assertEqual(1, battalion.replacement_deficit)
        purchase_reinforcements(self.state, "nato-us-armored", "tank(nato)", 1)
        replacement = assign_reinforcements(self.state, "nato-us-armored", "tank(nato)", 1)
        self.assertEqual(1, replacement.replacements)
        self.assertEqual(0, replacement.expansion)
        self.assertEqual(0, battalion.replacement_deficit)

    def test_repair_spends_resources_and_restores_condition(self) -> None:
        battalion = next(
            value for value in self.state.battalions.values()
            if value.formation_id == "nato-us-armored"
        )
        battalion.condition = 65
        battalion.supply = 100
        before = self.state.factions["nato"].resources
        result = repair_formation(self.state, "nato-us-armored", 15)
        self.assertEqual(80, battalion.condition)
        self.assertEqual(15, result.points_repaired)
        self.assertGreater(result.cost, 0)
        self.assertEqual(before - result.cost, self.state.factions["nato"].resources)

    def test_round_economy_records_income_and_maintenance(self) -> None:
        reports = settle_round_economy(self.state)
        nato = next(report for report in reports if report.faction == "nato")
        self.assertGreater(nato.income, 0)
        self.assertGreater(nato.maintenance_due, 0)
        self.assertEqual(nato.income, self.state.factions["nato"].income_last_round)
        self.assertEqual(nato.maintenance_paid, self.state.factions["nato"].maintenance_last_round)
        self.assertIn("last_round_economy", self.state.map_metadata)

    def test_ai_economy_performs_deterministic_progression(self) -> None:
        faction = Faction.UKRAINE
        faction_state = self.state.factions[faction.value]
        faction_state.researched_keys = [category_research_key(faction, "infantry")]
        battalion = next(value for value in self.state.battalions.values() if value.faction == faction)
        battalion.condition = 70
        actions = run_ai_economy(self.state, faction)
        self.assertTrue(actions)
        self.assertTrue(any(action["action"] in {"research", "repair", "recruit"} for action in actions))
        self.state.validate()

    def test_economy_state_round_trip(self) -> None:
        purchase_reinforcements(self.state, "nato-us-armored", "rifle(nato)", 1)
        battalion = next(
            value for value in self.state.battalions.values()
            if value.formation_id == "nato-us-armored"
        )
        battalion.condition = 77
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            save_campaign(self.state, path)
            loaded = load_campaign(path)
        self.assertEqual("economy-fixture", loaded.catalog_signature)
        self.assertEqual(77, loaded.battalions[battalion.battalion_id].condition)
        self.assertEqual(1, loaded.factions["nato"].reinforcement_pool[0].quantity)
        self.assertTrue(loaded.research_nodes)
        self.assertTrue(loaded.unit_economy)

    def test_available_research_excludes_completed_nodes(self) -> None:
        faction = Faction.PRC
        completed = set(self.state.factions[faction.value].researched_keys)
        available = available_research(self.state, faction)
        self.assertTrue(all(node.key not in completed for node in available))
        self.assertTrue(all(set(node.prerequisites).issubset(completed) for node in available))


if __name__ == "__main__":
    unittest.main()
