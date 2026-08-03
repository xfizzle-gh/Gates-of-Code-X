from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.bridge.scn import CampaignScnBuilder
from gates_of_codex.codex.catalog import CodeXCatalog, UnitDefinition
from gates_of_codex.economy import build_research_nodes, build_unit_economy, initialize_economy
from gates_of_codex.first_engine_test import stage_nato_russia_acceptance_battle
from gates_of_codex.models import BattalionRosterEntry, Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.starter import populate_starter_rosters, set_player_faction


class MaterializableUnitTests(unittest.TestCase):
    def _catalog(self) -> CodeXCatalog:
        units = {
            "m1097_avenger(nato)": UnitDefinition(
                name="m1097_avenger(nato)",
                side="nato",
                category="air_defense",
                type_tags=["AA"],
                source_files=["2:CodeX/script/multiplayer/units/nato/2022s.nato.lua"],
            ),
            "rifle(nato)": UnitDefinition(
                name="rifle(nato)",
                side="nato",
                category="infantry",
                members={"rifleman_nato": 4},
            ),
            "rifle(ukr)": UnitDefinition(
                name="rifle(ukr)",
                side="ukr",
                category="infantry",
                members={"rifleman_ukr": 4},
            ),
            "rifle(rusa)": UnitDefinition(
                name="rifle(rusa)",
                side="rusa",
                category="infantry",
                members={"rifleman_rusa": 4},
            ),
            "rifle(prc)": UnitDefinition(
                name="rifle(prc)",
                side="prc",
                category="infantry",
                members={"rifleman_prc": 4},
            ),
        }
        return CodeXCatalog(units=units, signature="fixture")

    def test_raw_catalog_preserves_incomplete_rows_but_campaign_iteration_filters_them(self) -> None:
        catalog = self._catalog()

        self.assertIn("m1097_avenger(nato)", catalog.units)
        self.assertIn("m1097_avenger(nato)", catalog.to_dict()["units"])
        self.assertEqual(["rifle(nato)"], [unit.name for unit in catalog.by_faction("nato")])
        self.assertEqual(
            ["m1097_avenger(nato)", "rifle(nato)"],
            [unit.name for unit in catalog.raw_by_faction("nato")],
        )

    def test_starter_economy_and_research_exclude_nonmaterializable_unit(self) -> None:
        catalog = self._catalog()
        state = load_bundled_scenario()
        set_player_faction(state, Faction.NATO)
        populate_starter_rosters(state, catalog)
        initialize_economy(state, catalog)

        roster_names = {
            entry.unit_name
            for battalion in state.battalions.values()
            for entry in battalion.roster
        }
        self.assertNotIn("m1097_avenger(nato)", roster_names)
        self.assertNotIn("m1097_avenger(nato)", build_unit_economy(catalog))
        research_unlocks = {
            unit
            for node in build_research_nodes(catalog).values()
            for unit in node.unlock_units
        }
        self.assertNotIn("m1097_avenger(nato)", research_unlocks)

    def test_bridge_preflight_reports_all_nonmaterializable_roster_entries(self) -> None:
        catalog = self._catalog()
        state = load_bundled_scenario()
        set_player_faction(state, Faction.NATO)
        populate_starter_rosters(state, catalog)
        initialize_economy(state, catalog)
        stage_nato_russia_acceptance_battle(state)
        pending = state.pending_battle
        self.assertIsNotNone(pending)
        attacker_id = pending.attacking_participants[0].battalion_id
        state.battalions[attacker_id].roster = [
            BattalionRosterEntry("m1097_avenger(nato)", quantity=1, category="air_defense"),
            BattalionRosterEntry("missing_unit(nato)", quantity=1, category="vehicle"),
        ]

        with tempfile.TemporaryDirectory() as temporary:
            builder = CampaignScnBuilder(catalog, resource_stack=[Path(temporary)])
            with self.assertRaisesRegex(ValueError, r"m1097_avenger[\s\S]*missing_unit"):
                builder.build(state, pending)


if __name__ == "__main__":
    unittest.main()
