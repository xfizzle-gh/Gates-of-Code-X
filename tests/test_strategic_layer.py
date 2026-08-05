from __future__ import annotations

import unittest

from gates_of_codex.cli import build_parser
from gates_of_codex.economy import formation_recruitment_offers
from gates_of_codex.frontend import FRONTEND_SCHEMA_VERSION, build_frontend_snapshot
from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Formation,
    Province,
    ResearchNode,
    UnitEconomy,
)
from gates_of_codex.strategic import (
    build_infrastructure,
    ensure_strategic_layer,
    evaluate_campaign_outcome,
    infrastructure_levels,
    run_ai_construction,
    sync_province_infrastructure_owner,
)


class StrategicLayerTests(unittest.TestCase):
    def test_construction_spends_resources_and_improves_fortification(self) -> None:
        state = self._state()
        result = build_infrastructure(state, Faction.NATO, "a", "fortification")
        self.assertEqual(1, result.level)
        self.assertEqual(140, result.cost)
        self.assertEqual(1860, state.factions["nato"].resources)
        self.assertEqual(1, state.provinces["a"].fortification)

    def test_supply_hub_rebinds_when_province_changes_owner(self) -> None:
        state = self._state()
        build_infrastructure(state, Faction.NATO, "b", "supply_hub")
        self.assertIn("nato", state.provinces["b"].metadata["supply_source_for"])
        state.provinces["b"].owner = Faction.RUSSIA
        sync_province_infrastructure_owner(state.provinces["b"])
        self.assertEqual(["rusa"], state.provinces["b"].metadata["supply_source_for"])

    def test_recruitment_center_discounts_formation_offers(self) -> None:
        state = self._state()
        baseline = formation_recruitment_offers(state, "nato-formation")[0]
        build_infrastructure(state, Faction.NATO, "a", "recruitment_center")
        discounted = formation_recruitment_offers(state, "nato-formation")[0]
        self.assertEqual(100, baseline.purchase_cost)
        self.assertEqual(95, discounted.purchase_cost)
        self.assertAlmostEqual(0.08, discounted.infrastructure_discount)

    def test_objective_completion_rewards_once(self) -> None:
        state = self._state()
        state.map_metadata["operational_objectives"] = [
            {
                "id": "command",
                "coalition": "western-coalition",
                "display_name": "Command",
                "kind": "infrastructure",
                "building": "command_post",
                "required": 1,
                "reward_each": 50,
                "primary": False,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
            }
        ]
        before = state.factions["nato"].resources
        build_infrastructure(state, Faction.NATO, "a", "command_post")
        after_build = state.factions["nato"].resources
        self.assertEqual(before - 260 + 50, after_build)
        evaluate_campaign_outcome(state)
        self.assertEqual(after_build, state.factions["nato"].resources)

    def test_primary_objective_and_capital_hold_complete_campaign(self) -> None:
        state = self._state()
        state.map_metadata["operational_objectives"] = [
            {
                "id": "advance",
                "coalition": "western-coalition",
                "display_name": "Advance",
                "kind": "control",
                "targets": ["x"],
                "required": 1,
                "reward_each": 0,
                "primary": True,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
            }
        ]
        state.map_metadata["coalition_capitals"] = {
            "western-coalition": ["a"],
            "eastern-coalition": ["x"],
        }
        state.provinces["x"].owner = Faction.NATO
        first = evaluate_campaign_outcome(state, advance_hold=True)
        second = evaluate_campaign_outcome(state, advance_hold=True)
        self.assertEqual("active", first.status)
        self.assertEqual("complete", second.status)
        self.assertEqual("western-coalition", second.winner_coalition)
        self.assertEqual("victory", second.selected_faction_result)

    def test_ai_constructs_on_hostile_front(self) -> None:
        state = self._state()
        action = run_ai_construction(state, Faction.NATO)
        self.assertIsNotNone(action)
        self.assertEqual("construct", action["action"])
        self.assertEqual("fortification", action["building"])

    def test_frontend_exports_infrastructure_objectives_and_outcome(self) -> None:
        state = self._state()
        snapshot = build_frontend_snapshot(state)
        self.assertEqual(FRONTEND_SCHEMA_VERSION, snapshot["schema_version"])
        self.assertIn("objectives", snapshot)
        self.assertIn("outcome", snapshot["campaign"])
        self.assertIn("front_options", snapshot)
        self.assertIn("control", snapshot)
        province = next(value for value in snapshot["provinces"] if value["id"] == "a")
        self.assertIn("infrastructure", province)
        self.assertEqual(4, len(province["construction_options"]))

    def test_cli_exposes_strategic_commands(self) -> None:
        construct = build_parser().parse_args(["construct", "campaign.json", "a", "supply_hub"])
        self.assertEqual("construct", construct.command)
        objectives = build_parser().parse_args(["objectives", "campaign.json"])
        self.assertEqual("objectives", objectives.command)
        status = build_parser().parse_args(["campaign-status", "campaign.json"])
        self.assertEqual("campaign-status", status.command)

    @staticmethod
    def _state() -> CampaignState:
        state = CampaignState(
            campaign_name="Strategic test",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={
                "nato": FactionState(Faction.NATO, resources=2000, researched_keys=["core-nato"]),
                "ukr": FactionState(Faction.UKRAINE, resources=2000),
                "rusa": FactionState(Faction.RUSSIA, resources=2000, researched_keys=["core-rusa"]),
                "prc": FactionState(Faction.PRC, resources=2000),
            },
            alliances={
                "western-coalition": Alliance("western-coalition", "Western", [Faction.NATO, Faction.UKRAINE]),
                "eastern-coalition": Alliance("eastern-coalition", "Eastern", [Faction.RUSSIA, Faction.PRC]),
            },
            formations={
                "nato-formation": Formation("nato-formation", "NATO Formation", Faction.NATO, "US", preferred_categories=["infantry"]),
                "rusa-formation": Formation("rusa-formation", "Russian Formation", Faction.RUSSIA, "RU", preferred_categories=["infantry"]),
            },
            research_nodes={
                "core-nato": ResearchNode("core-nato", Faction.NATO, "Core", 0),
                "core-rusa": ResearchNode("core-rusa", Faction.RUSSIA, "Core", 0),
            },
            unit_economy={
                "rifle(nato)": UnitEconomy("rifle(nato)", Faction.NATO, "infantry", 100, 3, 1, ["core-nato"]),
                "rifle(rusa)": UnitEconomy("rifle(rusa)", Faction.RUSSIA, "infantry", 100, 3, 1, ["core-rusa"]),
            },
            provinces={
                "a": Province("a", "A", Faction.NATO, ["b", "x"], metadata={"static_supply_source_for": ["nato"]}),
                "b": Province("b", "B", Faction.NATO, ["a"]),
                "x": Province("x", "X", Faction.RUSSIA, ["a", "y"], metadata={"static_supply_source_for": ["rusa"]}),
                "y": Province("y", "Y", Faction.RUSSIA, ["x"]),
            },
            battalions={
                "nato-1": Battalion(
                    "nato-1",
                    Faction.NATO,
                    "a",
                    roster=[BattalionRosterEntry("rifle(nato)", 3, category="infantry")],
                    authorized_roster=[BattalionRosterEntry("rifle(nato)", 3, category="infantry")],
                    formation_id="nato-formation",
                ),
                "rusa-1": Battalion(
                    "rusa-1",
                    Faction.RUSSIA,
                    "x",
                    roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                    authorized_roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                    formation_id="rusa-formation",
                ),
            },
        )
        ensure_strategic_layer(state)
        for province in state.provinces.values():
            infrastructure_levels(province)
        state.validate()
        return state


if __name__ == "__main__":
    unittest.main()
