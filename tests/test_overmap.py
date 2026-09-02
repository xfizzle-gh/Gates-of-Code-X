from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.campaign_loop import finish_player_overmap_turn, overmap_campaign, overmap_turn
from gates_of_codex.europe import build_goe_europe_campaign
from gates_of_codex.forces import ensure_faction_forces
from gates_of_codex.frontend_commands import apply_frontend_commands
from gates_of_codex.models import Battalion, BattalionRosterEntry, CampaignState, Faction, FactionState, Province
from gates_of_codex.play_context import list_front_options
from gates_of_codex.starter import set_player_faction
from gates_of_codex.state_io import load_campaign, save_campaign


class OvermapFourXTests(unittest.TestCase):
    def test_remnant_spawns_when_land_has_no_battalion(self) -> None:
        state = build_goe_europe_campaign()
        rusa = [key for key, value in state.battalions.items() if value.faction == Faction.RUSSIA]
        for key in rusa:
            del state.battalions[key]
        spawned = ensure_faction_forces(state)
        self.assertTrue(spawned)
        self.assertTrue(any(value.faction == Faction.RUSSIA for value in state.battalions.values()))

    def test_remnant_spawns_on_disconnected_ungarrisoned_land(self) -> None:
        state = CampaignState(
            campaign_name="Theaters",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={
                "nato": FactionState(Faction.NATO, is_human_controlled=True),
                "rusa": FactionState(Faction.RUSSIA),
            },
            provinces={
                "uk": Province("uk", "UK", Faction.NATO, []),
                "a": Province("a", "A", Faction.NATO, ["b"]),
                "b": Province("b", "B", Faction.NATO, ["a"]),
                "c": Province("c", "C", Faction.RUSSIA, []),
            },
            battalions={
                "nato-uk": Battalion(
                    "nato-uk",
                    Faction.NATO,
                    "uk",
                    roster=[BattalionRosterEntry("rifle", 1, category="infantry")],
                )
            },
        )
        spawned = ensure_faction_forces(state)
        self.assertTrue(spawned)
        continent = [
            battalion
            for battalion in state.battalions.values()
            if battalion.faction == Faction.NATO and battalion.province_id in {"a", "b"}
        ]
        self.assertTrue(continent)

    def test_twenty_overmap_turns_keep_all_factions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "europe.json"
            state = build_goe_europe_campaign()
            set_player_faction(state, Faction.NATO)
            save_campaign(state, campaign)
            payload = overmap_campaign(campaign, turns=20, seed=4)
            self.assertGreaterEqual(payload["turns_run"], 1)
            if payload.get("status") != "complete":
                self.assertEqual(20, payload["turns_run"])
            restored = load_campaign(campaign)
            counts = {faction.value: 0 for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC)}
            for battalion in restored.battalions.values():
                counts[battalion.faction.value] = counts.get(battalion.faction.value, 0) + 1
            for faction in (Faction.NATO, Faction.UKRAINE, Faction.RUSSIA, Faction.PRC):
                owns = sum(1 for province in restored.provinces.values() if province.owner == faction)
                if owns:
                    self.assertGreaterEqual(counts[faction.value], 1, faction.value)
            self.assertGreaterEqual(restored.turn_number, 2)

    def test_retreat_does_not_stack_on_allied_battalion(self) -> None:
        from gates_of_codex.campaign import CampaignEngine
        from gates_of_codex.control import default_alliances

        state = CampaignState(
            campaign_name="Retreat",
            selected_faction=Faction.NATO,
            current_faction=Faction.UKRAINE,
            factions={
                "nato": FactionState(Faction.NATO, is_human_controlled=True),
                "ukr": FactionState(Faction.UKRAINE),
                "rusa": FactionState(Faction.RUSSIA),
                "prc": FactionState(Faction.PRC),
            },
            alliances=default_alliances(),
            provinces={
                "a": Province("a", "A", Faction.UKRAINE, ["b"]),
                "b": Province("b", "B", Faction.PRC, ["a", "c"]),
                "c": Province("c", "C", Faction.RUSSIA, ["b"]),
            },
            battalions={
                "ukr-1": Battalion(
                    "ukr-1",
                    Faction.UKRAINE,
                    "a",
                    roster=[BattalionRosterEntry("rifle", 4, category="infantry")],
                ),
                "prc-1": Battalion(
                    "prc-1",
                    Faction.PRC,
                    "b",
                    roster=[BattalionRosterEntry("rifle", 1, category="infantry")],
                ),
                "rusa-1": Battalion(
                    "rusa-1",
                    Faction.RUSSIA,
                    "c",
                    roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                ),
            },
        )
        engine = CampaignEngine(state)
        result = engine.move_or_attack("ukr-1", "b")
        self.assertIsNotNone(result.pending_battle)
        engine.apply_battle_result(Faction.UKRAINE)
        self.assertEqual("b", state.battalions["ukr-1"].province_id)
        if "prc-1" in state.battalions:
            self.assertNotEqual("c", state.battalions["prc-1"].province_id)
        occupants = {
            battalion.faction.value
            for battalion in state.battalions.values()
            if battalion.province_id == "c"
        }
        self.assertEqual({"rusa"}, occupants)

    def test_empty_enemy_land_is_captured_without_a_battle(self) -> None:
        state = CampaignState(
            campaign_name="Capture",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={
                "nato": FactionState(Faction.NATO, is_human_controlled=True),
                "rusa": FactionState(Faction.RUSSIA),
            },
            provinces={
                "a": Province("a", "A", Faction.NATO, ["b"]),
                "b": Province("b", "B", Faction.RUSSIA, ["a"]),
            },
            battalions={
                "nato-1": Battalion(
                    "nato-1",
                    Faction.NATO,
                    "a",
                    roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                )
            },
        )
        options = list_front_options(state)
        self.assertEqual(["capture"], [row["kind"] for row in options])
        result = CampaignEngine(state).move_or_attack("nato-1", "b")
        self.assertTrue(result.moved)
        self.assertIsNone(result.pending_battle)
        self.assertIsNone(state.pending_battle)
        self.assertEqual(Faction.NATO, state.provinces["b"].owner)
        self.assertEqual("b", state.battalions["nato-1"].province_id)

    def test_overmap_turn_does_not_idle_move_rear_units(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "front.json"
            state = CampaignState(
                campaign_name="Rear",
                selected_faction=Faction.NATO,
                current_faction=Faction.NATO,
                factions={
                    "nato": FactionState(Faction.NATO, is_human_controlled=True),
                    "ukr": FactionState(Faction.UKRAINE),
                    "rusa": FactionState(Faction.RUSSIA),
                    "prc": FactionState(Faction.PRC),
                },
                provinces={
                    "a": Province("a", "A", Faction.NATO, ["b"]),
                    "b": Province("b", "B", Faction.NATO, ["a"]),
                    "c": Province("c", "C", Faction.RUSSIA, []),
                },
                battalions={
                    "nato-1": Battalion(
                        "nato-1",
                        Faction.NATO,
                        "a",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                    "rusa-1": Battalion(
                        "rusa-1",
                        Faction.RUSSIA,
                        "c",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                },
            )
            save_campaign(state, campaign)
            payload = overmap_turn(campaign, seed=1)
            restored = load_campaign(campaign)
            self.assertEqual("a", restored.battalions["nato-1"].province_id)
            self.assertEqual("nato", restored.current_faction.value)
            self.assertGreaterEqual(restored.turn_number, 2)
            self.assertFalse(any(step.get("op") in {"action", "march"} for step in payload["steps"]))

    def test_overmap_turn_marches_toward_the_front(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "march.json"
            state = CampaignState(
                campaign_name="March",
                selected_faction=Faction.NATO,
                current_faction=Faction.NATO,
                factions={
                    "nato": FactionState(Faction.NATO, is_human_controlled=True),
                    "ukr": FactionState(Faction.UKRAINE),
                    "rusa": FactionState(Faction.RUSSIA),
                    "prc": FactionState(Faction.PRC),
                },
                provinces={
                    "a": Province("a", "A", Faction.NATO, ["b"]),
                    "b": Province("b", "B", Faction.NATO, ["a", "c"]),
                    "c": Province("c", "C", Faction.RUSSIA, ["b"]),
                },
                battalions={
                    "nato-1": Battalion(
                        "nato-1",
                        Faction.NATO,
                        "a",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                    "rusa-1": Battalion(
                        "rusa-1",
                        Faction.RUSSIA,
                        "c",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                },
            )
            save_campaign(state, campaign)
            payload = overmap_turn(campaign, seed=1)
            restored = load_campaign(campaign)
            self.assertEqual("b", restored.battalions["nato-1"].province_id)
            self.assertTrue(any(step.get("op") == "march" for step in payload["steps"]))
            self.assertEqual("nato", restored.current_faction.value)

    def test_next_turn_runs_ai_without_moving_the_player(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "next.json"
            state = CampaignState(
                campaign_name="Next",
                selected_faction=Faction.NATO,
                current_faction=Faction.NATO,
                factions={
                    "nato": FactionState(Faction.NATO, is_human_controlled=True),
                    "ukr": FactionState(Faction.UKRAINE),
                    "rusa": FactionState(Faction.RUSSIA),
                    "prc": FactionState(Faction.PRC),
                },
                provinces={
                    "a": Province("a", "A", Faction.NATO, ["b"]),
                    "b": Province("b", "B", Faction.NATO, ["a", "c"]),
                    "c": Province("c", "C", Faction.RUSSIA, ["b"]),
                },
                battalions={
                    "nato-1": Battalion(
                        "nato-1",
                        Faction.NATO,
                        "a",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                    "rusa-1": Battalion(
                        "rusa-1",
                        Faction.RUSSIA,
                        "c",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                },
            )
            save_campaign(state, campaign)
            payload = finish_player_overmap_turn(campaign, seed=2)
            restored = load_campaign(campaign)
            self.assertEqual("nato", restored.current_faction.value)
            self.assertGreaterEqual(restored.turn_number, 2)
            self.assertEqual("a", restored.battalions["nato-1"].province_id)
            self.assertTrue(any(step.get("op") == "end_player_turn" for step in payload["steps"]))
            self.assertTrue(any(step.get("op") == "advance" for step in payload["steps"]))

    def test_overmap_does_not_autoplay_an_ai_faction(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "ai.json"
            state = CampaignState(
                campaign_name="AI current",
                selected_faction=Faction.NATO,
                current_faction=Faction.UKRAINE,
                factions={
                    "nato": FactionState(Faction.NATO, is_human_controlled=True),
                    "ukr": FactionState(Faction.UKRAINE),
                    "rusa": FactionState(Faction.RUSSIA),
                    "prc": FactionState(Faction.PRC),
                },
                provinces={
                    "a": Province("a", "A", Faction.NATO, []),
                    "b": Province("b", "B", Faction.UKRAINE, ["c"]),
                    "c": Province("c", "C", Faction.RUSSIA, ["b"]),
                    "d": Province("d", "D", Faction.PRC, []),
                },
                battalions={
                    "nato-1": Battalion(
                        "nato-1",
                        Faction.NATO,
                        "a",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                    "ukr-1": Battalion(
                        "ukr-1",
                        Faction.UKRAINE,
                        "b",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                    "rusa-1": Battalion(
                        "rusa-1",
                        Faction.RUSSIA,
                        "c",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                    "prc-1": Battalion(
                        "prc-1",
                        Faction.PRC,
                        "d",
                        roster=[BattalionRosterEntry("rifle", 2, category="infantry")],
                    ),
                },
            )
            save_campaign(state, campaign)
            payload = overmap_turn(campaign, seed=3)
            self.assertFalse(any(step.get("op") in {"action", "march"} for step in payload["steps"]))
            restored = load_campaign(campaign)
            self.assertEqual("nato", restored.current_faction.value)

    def test_frontend_overmap_command_advances_to_player(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            campaign = Path(raw) / "campaign.json"
            state = build_goe_europe_campaign()
            set_player_faction(state, Faction.NATO)
            save_campaign(state, campaign)
            before = load_campaign(campaign).turn_number
            payload = apply_frontend_commands(
                campaign,
                commands=[{"op": "overmap"}],
            )
            after = load_campaign(campaign)
            self.assertTrue(payload["ok"])
            self.assertEqual("nato", after.current_faction.value)
            self.assertGreaterEqual(after.turn_number, before)
            self.assertIsNone(after.pending_battle)


if __name__ == "__main__":
    unittest.main()
