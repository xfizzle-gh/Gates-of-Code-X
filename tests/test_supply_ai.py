from __future__ import annotations

import unittest

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.cli import build_parser
from gates_of_codex.diplomacy import are_allied
from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Province,
)
from gates_of_codex.strategic_ai import StrategicAI
from gates_of_codex.supply import reachable_supply_provinces, refresh_supply_for_faction


class SupplyAndStrategicAITests(unittest.TestCase):
    def test_allied_movement_preserves_province_owner(self) -> None:
        state = self._western_route_state()
        result = CampaignEngine(state).move_or_attack("nato-1", "b")
        self.assertTrue(result.moved)
        self.assertEqual("b", state.battalions["nato-1"].province_id)
        self.assertEqual(Faction.UKRAINE, state.provinces["b"].owner)

    def test_allied_stacking_is_rejected(self) -> None:
        state = self._western_route_state()
        state.battalions["ukr-1"] = Battalion(
            battalion_id="ukr-1",
            faction=Faction.UKRAINE,
            province_id="b",
            roster=[BattalionRosterEntry("ukr", quantity=2, category="infantry")],
        )
        state.validate()
        with self.assertRaisesRegex(ValueError, "Allied province"):
            CampaignEngine(state).move_or_attack("nato-1", "b")

    def test_supply_routes_cross_allied_territory(self) -> None:
        state = self._western_route_state()
        state.battalions["nato-1"].province_id = "c"
        state.battalions["nato-1"].supply = 50
        reachable = reachable_supply_provinces(state, Faction.NATO)
        self.assertEqual({"a", "b", "c"}, reachable)
        report = refresh_supply_for_faction(state, Faction.NATO)
        self.assertEqual(70, state.battalions["nato-1"].supply)
        self.assertEqual(("nato-1",), report.supplied_battalions)
        self.assertEqual(0, state.battalions["nato-1"].encircled_turns)

    def test_isolated_formation_loses_supply_and_takes_attrition(self) -> None:
        state = CampaignState(
            campaign_name="Encirclement",
            factions={
                "nato": FactionState(Faction.NATO),
                "rusa": FactionState(Faction.RUSSIA),
            },
            provinces={
                "a": Province("a", "A", Faction.NATO, ["b"], metadata={"supply_source_for": ["nato"]}),
                "b": Province("b", "B", Faction.NATO, ["a", "c"]),
                "c": Province("c", "C", Faction.RUSSIA, ["b", "d"]),
                "d": Province("d", "D", Faction.NATO, ["c"]),
            },
            battalions={
                "cut-off": Battalion(
                    battalion_id="cut-off",
                    faction=Faction.NATO,
                    province_id="d",
                    roster=[BattalionRosterEntry("rifle", quantity=3, category="infantry")],
                )
            },
        )
        for _ in range(3):
            refresh_supply_for_faction(state, Faction.NATO)
        battalion = state.battalions["cut-off"]
        self.assertEqual(25, battalion.supply)
        self.assertEqual(3, battalion.encircled_turns)
        self.assertEqual(2, battalion.unit_count)

    def test_strategic_ai_captures_adjacent_neutral_province(self) -> None:
        state = CampaignState(
            campaign_name="AI capture",
            current_faction=Faction.RUSSIA,
            factions={"rusa": FactionState(Faction.RUSSIA)},
            provinces={
                "a": Province("a", "A", Faction.RUSSIA, ["b"]),
                "b": Province("b", "B", Faction.NEUTRAL, ["a"]),
            },
            battalions={
                "rusa-1": Battalion(
                    battalion_id="rusa-1",
                    faction=Faction.RUSSIA,
                    province_id="a",
                    roster=[BattalionRosterEntry("rifle", quantity=3, category="infantry")],
                )
            },
        )
        actions = StrategicAI(state, random_seed=3).take_turn(Faction.RUSSIA)
        self.assertEqual("capture", actions[0].action)
        self.assertEqual(Faction.RUSSIA, state.provinces["b"].owner)
        self.assertEqual("b", state.battalions["rusa-1"].province_id)

    def test_strategic_ai_attacks_hostile_formation_and_clears_battle(self) -> None:
        state = CampaignState(
            campaign_name="AI attack",
            current_faction=Faction.RUSSIA,
            selected_faction=Faction.NATO,
            factions={
                "nato": FactionState(Faction.NATO),
                "rusa": FactionState(Faction.RUSSIA),
            },
            provinces={
                "a": Province("a", "A", Faction.RUSSIA, ["b"]),
                "b": Province("b", "B", Faction.NATO, ["a"]),
            },
            battalions={
                "rusa-1": Battalion(
                    battalion_id="rusa-1",
                    faction=Faction.RUSSIA,
                    province_id="a",
                    roster=[BattalionRosterEntry("tank", quantity=4, category="tank")],
                ),
                "nato-1": Battalion(
                    battalion_id="nato-1",
                    faction=Faction.NATO,
                    province_id="b",
                    roster=[BattalionRosterEntry("rifle", quantity=1, category="infantry")],
                ),
            },
        )
        actions = StrategicAI(state, random_seed=1).take_turn(Faction.RUSSIA)
        self.assertEqual("attack", actions[0].action)
        self.assertIsNotNone(actions[0].winner)
        self.assertIsNone(state.pending_battle)

    def test_full_europe_campaign_has_supply_sources_and_frontend_status(self) -> None:
        state = build_goe_europe_campaign()
        self.assertTrue(are_allied(state, Faction.NATO, Faction.UKRAINE))
        self.assertTrue(are_allied(state, Faction.RUSSIA, Faction.PRC))
        for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC):
            self.assertTrue(reachable_supply_provinces(state, faction))
        battalion = next(iter(state.battalions.values()))
        battalion.encircled_turns = 2
        snapshot = build_frontend_snapshot(state)
        exported = next(value for value in snapshot["battalions"] if value["id"] == battalion.battalion_id)
        self.assertEqual(2, exported["encircled_turns"])
        self.assertIn("is_in_supply", exported)

    def test_cli_exposes_supply_and_ai_commands(self) -> None:
        supply = build_parser().parse_args(["supply-status", "campaign.json", "--refresh"])
        self.assertEqual("supply-status", supply.command)
        ai = build_parser().parse_args(
            ["run-ai-turn", "campaign.json", "--faction", "rusa", "--seed", "9"]
        )
        self.assertEqual("run-ai-turn", ai.command)
        self.assertEqual(9, ai.seed)

    @staticmethod
    def _western_route_state() -> CampaignState:
        return CampaignState(
            campaign_name="Western route",
            factions={
                "nato": FactionState(Faction.NATO),
                "ukr": FactionState(Faction.UKRAINE),
            },
            alliances={
                "western": Alliance(
                    alliance_id="western",
                    display_name="Western",
                    factions=[Faction.NATO, Faction.UKRAINE],
                )
            },
            provinces={
                "a": Province("a", "A", Faction.NATO, ["b"], metadata={"supply_source_for": ["nato"]}),
                "b": Province("b", "B", Faction.UKRAINE, ["a", "c"]),
                "c": Province("c", "C", Faction.NATO, ["b"]),
            },
            battalions={
                "nato-1": Battalion(
                    battalion_id="nato-1",
                    faction=Faction.NATO,
                    province_id="a",
                    roster=[BattalionRosterEntry("rifle", quantity=3, category="infantry")],
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
