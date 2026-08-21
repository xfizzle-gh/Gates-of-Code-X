from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.campaign_rules import (
    CAMPAIGN_RULES_KEY,
    DEFAULT_HOLD_WEEKS,
    DEFAULT_START_YEAR,
    GRADE_DECISIVE_DEFEAT,
    GRADE_DEFEAT,
    GRADE_STALEMATE,
    GRADE_VICTORY,
    VICTORY_MODEL_P9,
    calendar_from_turn,
    campaign_play_blocked,
    campaign_presentation,
    conclude_campaign,
    continue_playing,
    ensure_campaign_rules,
    load_campaign_rules_contract,
    normalize_length_preset,
    record_auto_resolve_result,
)
from gates_of_codex.command_cycle_perf import _should_persist_runtime_snapshot
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA_VERSION,
    build_frontend_runtime_patch,
)
from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Formation,
    PendingBattle,
    Province,
    ResearchNode,
    UnitEconomy,
)
from gates_of_codex.player_shell import LENGTH_PRESET_CHOICES, build_play_parser
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic import (
    ensure_strategic_layer,
    evaluate_campaign_outcome,
    update_operational_objectives,
)


class CampaignRulesContractTests(unittest.TestCase):
    def test_locked_preset_table_matches_issue_75(self) -> None:
        contract = load_campaign_rules_contract()
        self.assertEqual(2028, contract["calendar"]["start_year"])
        self.assertEqual(52, contract["calendar"]["turns_per_year"])
        self.assertEqual(4, contract["calendar"]["default_hold_weeks"])
        self.assertEqual(DEFAULT_HOLD_WEEKS, 4)
        self.assertEqual(DEFAULT_START_YEAR, 2028)
        self.assertEqual(52, contract["presets"]["short"]["turn_cap"])
        self.assertEqual(104, contract["presets"]["medium"]["turn_cap"])
        self.assertEqual(156, contract["presets"]["long"]["turn_cap"])
        self.assertEqual(LENGTH_PRESET_CHOICES, ("short", "medium", "long"))

    def test_calendar_derives_week_and_year_from_turn_number(self) -> None:
        self.assertEqual("2028-W01", calendar_from_turn(1)["label"])
        self.assertEqual({"start_year": 2028, "turns_per_year": 52, "year": 2028, "week": 52, "label": "2028-W52"}, calendar_from_turn(52))
        week1_2029 = calendar_from_turn(53)
        self.assertEqual(2029, week1_2029["year"])
        self.assertEqual(1, week1_2029["week"])
        self.assertEqual("2030-W01", calendar_from_turn(105)["label"])

    def test_unknown_preset_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown campaign length preset"):
            normalize_length_preset("endless")


class CampaignRulesPlayTests(unittest.TestCase):
    def test_hold_requires_supply_connection_and_four_weeks(self) -> None:
        state = _rules_state()
        evaluate_campaign_outcome(state, advance_hold=True)
        update_operational_objectives(state)
        war_aim = _objective(state, "aim-west")
        self.assertEqual(1, war_aim["target_hold_weeks"]["x"])
        self.assertFalse(war_aim["completed"])

        for _ in range(3):
            evaluate_campaign_outcome(state, advance_hold=True)
        war_aim = _objective(state, "aim-west")
        self.assertEqual(4, war_aim["target_hold_weeks"]["x"])
        self.assertTrue(war_aim["completed"])

        isolated = _rules_state()
        isolated.provinces["x"].neighbors = []
        isolated.provinces["x"].metadata["static_supply_source_for"] = []
        isolated.provinces["x"].metadata["supply_source_for"] = []
        isolated.provinces["a"].neighbors = ["b"]
        evaluate_campaign_outcome(isolated, advance_hold=True)
        self.assertEqual(0, _objective(isolated, "aim-west")["target_hold_weeks"]["x"])
        for _ in range(4):
            evaluate_campaign_outcome(isolated, advance_hold=True)
        self.assertFalse(_objective(isolated, "aim-west")["completed"])

    def test_touching_without_hold_is_not_victory(self) -> None:
        state = _rules_state()
        first = evaluate_campaign_outcome(state, advance_hold=True)
        self.assertEqual("active", first.status)
        self.assertFalse(campaign_play_blocked(state))

    def test_campaign_victory_requires_war_aims_national_and_momentum(self) -> None:
        state = _rules_state()
        for _ in range(4):
            evaluate_campaign_outcome(state, advance_hold=True)
        state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"] = {"nato": 6}
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertIn(outcome.grade, {GRADE_VICTORY, "decisive_victory"})
        self.assertEqual("victory", outcome.selected_faction_result)
        self.assertEqual("victory", outcome.coalition_result)
        self.assertEqual("victory", outcome.national_result)
        self.assertGreaterEqual(outcome.momentum, 45)

    def test_ai_actor_can_win_on_the_same_rules(self) -> None:
        state = _rules_state()
        state.provinces["a"].owner = Faction.RUSSIA
        state.provinces["b"].owner = Faction.RUSSIA
        state.provinces["x"].owner = Faction.RUSSIA
        state.provinces["y"].owner = Faction.RUSSIA
        for _ in range(4):
            evaluate_campaign_outcome(state, advance_hold=True)
        state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"] = {"rusa": 8}
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertEqual("eastern-coalition", outcome.winner_coalition)

    def test_allied_national_success_does_not_end_ukraine_campaign(self) -> None:
        """Human UKR: Western aims + NATO national complete, UKR national incomplete => ACTIVE."""

        state = _ukraine_player_state()
        _hold_weeks(state, 4)
        _boost_momentum(state, "nato", wins=6)
        self.assertTrue(_objective(state, "aim-west")["completed"])
        self.assertTrue(_objective(state, "nat-usa")["completed"])
        self.assertFalse(_objective(state, "nat-ukr")["completed"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("active", outcome.status)
        self.assertEqual("active", outcome.selected_faction_result)
        self.assertFalse(campaign_play_blocked(state))
        self.assertNotEqual("defeat", outcome.selected_faction_result)
        self.assertNotIn(outcome.grade, {GRADE_VICTORY, "decisive_victory", GRADE_DEFEAT})

    def test_ukraine_victory_requires_own_national_contribution(self) -> None:
        """Human UKR: Western aims + UKR national + threshold => VICTORY."""

        state = _ukraine_player_state()
        _grant_ukraine_national_hold(state)
        _hold_weeks(state, 4)
        _boost_momentum(state, "ukr", wins=6)
        self.assertTrue(_objective(state, "aim-west")["completed"])
        self.assertTrue(_objective(state, "nat-ukr")["completed"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("victory", outcome.selected_faction_result)
        self.assertIn(outcome.grade, {GRADE_VICTORY, "decisive_victory"})
        self.assertEqual("western-coalition", outcome.winner_coalition)
        self.assertEqual("victory", outcome.national_result)
        self.assertEqual("victory", outcome.coalition_result)
        self.assertGreaterEqual(outcome.momentum, 45)

    def test_opposing_coalition_contract_defeats_ukraine_player(self) -> None:
        """Eastern coalition accepted victory contract => human UKR DEFEAT."""

        state = _ukraine_player_state()
        for province_id in ("a", "b", "x", "y"):
            state.provinces[province_id].owner = Faction.RUSSIA
        _hold_weeks(state, 4)
        _boost_momentum(state, "rusa", wins=8)
        self.assertTrue(_objective(state, "aim-east")["completed"])
        self.assertTrue(_objective(state, "nat-rus")["completed"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertEqual("eastern-coalition", outcome.winner_coalition)
        self.assertFalse(state.map_metadata[CAMPAIGN_RULES_KEY].get("continue_playing"))

    def test_ukraine_coalition_national_split_survives_save_load(self) -> None:
        """ACTIVE / VICTORY / DEFEAT from the UKR split persist across save/load."""

        active = _ukraine_player_state()
        _hold_weeks(active, 4)
        _boost_momentum(active, "nato", wins=6)
        self.assertEqual("active", evaluate_campaign_outcome(active).status)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "active.json"
            save_campaign(active, path)
            loaded_active = load_campaign(path)
        restored_active = evaluate_campaign_outcome(loaded_active)
        self.assertEqual("active", restored_active.status)
        self.assertEqual("active", restored_active.selected_faction_result)
        self.assertTrue(_objective(loaded_active, "nat-usa")["completed"])
        self.assertFalse(_objective(loaded_active, "nat-ukr")["completed"])
        self.assertFalse(campaign_play_blocked(loaded_active))

        victory = _ukraine_player_state()
        _grant_ukraine_national_hold(victory)
        _hold_weeks(victory, 4)
        _boost_momentum(victory, "ukr", wins=6)
        self.assertEqual("victory", evaluate_campaign_outcome(victory).selected_faction_result)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "victory.json"
            save_campaign(victory, path)
            loaded_victory = load_campaign(path)
        restored_victory = evaluate_campaign_outcome(loaded_victory)
        self.assertEqual("complete", restored_victory.status)
        self.assertEqual("victory", restored_victory.selected_faction_result)
        self.assertIn(restored_victory.grade, {GRADE_VICTORY, "decisive_victory"})

        defeat = _ukraine_player_state()
        for province_id in ("a", "b", "x", "y"):
            defeat.provinces[province_id].owner = Faction.RUSSIA
        _hold_weeks(defeat, 4)
        _boost_momentum(defeat, "rusa", wins=8)
        self.assertEqual("defeat", evaluate_campaign_outcome(defeat).selected_faction_result)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "defeat.json"
            save_campaign(defeat, path)
            loaded_defeat = load_campaign(path)
        restored_defeat = evaluate_campaign_outcome(loaded_defeat)
        self.assertEqual("complete", restored_defeat.status)
        self.assertEqual("defeat", restored_defeat.selected_faction_result)
        self.assertEqual("eastern-coalition", restored_defeat.winner_coalition)

    def test_ai_uses_same_allied_national_and_opposing_contract_rules(self) -> None:
        """AI evaluation uses the same coalition/national split as a human seat."""

        nato_seat = _rules_state()
        _grant_ukraine_national_hold(nato_seat)
        nato_seat.provinces["a"].owner = Faction.UKRAINE
        _hold_weeks(nato_seat, 4)
        _boost_momentum(nato_seat, "ukr", wins=6)
        self.assertTrue(_objective(nato_seat, "aim-west")["completed"])
        self.assertTrue(_objective(nato_seat, "nat-ukr")["completed"])
        self.assertFalse(_objective(nato_seat, "nat-usa")["completed"])
        allied_ai = evaluate_campaign_outcome(nato_seat)
        self.assertEqual("active", allied_ai.status)
        self.assertEqual("active", allied_ai.selected_faction_result)
        self.assertFalse(campaign_play_blocked(nato_seat))

        opposing = _ukraine_player_state()
        opposing.factions["ukr"].is_human_controlled = False
        opposing.factions["nato"].is_human_controlled = False
        for province_id in ("a", "b", "x", "y"):
            opposing.provinces[province_id].owner = Faction.RUSSIA
        _hold_weeks(opposing, 4)
        _boost_momentum(opposing, "rusa", wins=8)
        ai_defeat = evaluate_campaign_outcome(opposing)
        self.assertEqual("complete", ai_defeat.status)
        self.assertEqual("defeat", ai_defeat.selected_faction_result)
        self.assertEqual("eastern-coalition", ai_defeat.winner_coalition)

    def test_capital_loss_defeats_player_after_four_weeks(self) -> None:
        state = _rules_state(hub_province="a")
        state.provinces["a"].owner = Faction.RUSSIA
        for week in range(3):
            outcome = evaluate_campaign_outcome(state, advance_hold=True)
            self.assertEqual("active", outcome.status, week)
        outcome = evaluate_campaign_outcome(state, advance_hold=True)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertEqual(GRADE_DEFEAT, outcome.grade)
        self.assertIn("capital or control hub", outcome.reason)

    def test_momentum_collapse_is_a_reachable_defeat(self) -> None:
        state = _rules_state()
        state.map_metadata[CAMPAIGN_RULES_KEY]["momentum_sources"] = {
            "war_aim_completed": 0,
            "held_strategic_site": 0,
            "supply_connected_gain": 0,
            "major_auto_resolve_victory": 0,
            "formation_loss": -40,
            "lost_capital": 0,
        }
        state.map_metadata[CAMPAIGN_RULES_KEY]["opening_formations"] = {"nato": 4, "rusa": 1}
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertIn(outcome.grade, {GRADE_DEFEAT, GRADE_DECISIVE_DEFEAT})
        self.assertIn("momentum collapsed", outcome.reason)

    def test_time_limit_grades_at_the_turn_cap(self) -> None:
        state = _rules_state()
        state.turn_number = 53
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("time-limit grading at the campaign turn cap", outcome.reason)
        self.assertEqual(GRADE_STALEMATE, outcome.grade)

    def test_continue_playing_after_victory_and_conclude(self) -> None:
        state = _rules_state()
        for _ in range(4):
            evaluate_campaign_outcome(state, advance_hold=True)
        state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"] = {"nato": 6}
        evaluate_campaign_outcome(state)
        self.assertTrue(campaign_play_blocked(state))
        continued = continue_playing(state)
        self.assertTrue(continued["continue_playing"])
        self.assertFalse(campaign_play_blocked(state))
        engine = CampaignEngine(state)
        next_faction = engine.end_turn()
        self.assertEqual(Faction.RUSSIA, next_faction)
        self.assertEqual("complete", state.map_metadata["campaign_outcome"]["status"])
        self.assertIn(state.map_metadata["campaign_outcome"]["grade"], {GRADE_VICTORY, "decisive_victory"})
        concluded = conclude_campaign(state)
        self.assertTrue(concluded["concluded"])
        self.assertTrue(campaign_play_blocked(state))
        with self.assertRaisesRegex(RuntimeError, "already complete"):
            CampaignEngine(state).end_turn()

    def test_continue_playing_rejects_defeat(self) -> None:
        state = _rules_state(hub_province="a")
        state.provinces["a"].owner = Faction.RUSSIA
        for _ in range(4):
            evaluate_campaign_outcome(state, advance_hold=True)
        with self.assertRaisesRegex(ValueError, "only available after victory"):
            continue_playing(state)
        conclude_campaign(state)
        self.assertTrue(state.map_metadata[CAMPAIGN_RULES_KEY]["concluded"])

    def test_save_restore_persists_calendar_objectives_momentum_and_continue(self) -> None:
        state = _rules_state()
        for _ in range(4):
            evaluate_campaign_outcome(state, advance_hold=True)
        state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"] = {"nato": 6}
        evaluate_campaign_outcome(state)
        continue_playing(state)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "campaign.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        rules = loaded.map_metadata[CAMPAIGN_RULES_KEY]
        self.assertEqual("short", rules["length_preset"])
        self.assertEqual(52, rules["turn_cap"])
        self.assertEqual(2028, rules["start_year"])
        self.assertTrue(rules["continue_playing"])
        self.assertTrue(_objective(loaded, "aim-west")["completed"])
        self.assertGreaterEqual(rules["momentum"]["score"], 45)
        self.assertEqual("complete", loaded.map_metadata["campaign_outcome"]["status"])
        presentation = campaign_presentation(loaded)
        self.assertEqual("short", presentation["length_preset"])
        self.assertTrue(presentation["continue_playing"])
        self.assertIn("label", presentation["calendar"])

    def test_snapshot_and_runtime_patch_expose_calendar_without_schema_bump(self) -> None:
        state = _rules_state()
        evaluate_campaign_outcome(state)
        snapshot = build_frontend_snapshot(state)
        campaign = snapshot["campaign"]
        self.assertEqual("2028-W01", campaign["calendar"]["label"])
        self.assertEqual("short", campaign["length_preset"])
        self.assertEqual(52, campaign["turn_cap"])
        self.assertIn("score", campaign["momentum"])
        self.assertEqual(1, RUNTIME_PATCH_SCHEMA_VERSION)
        patch = build_frontend_runtime_patch(state)
        self.assertEqual(1, patch["schema_version"])
        self.assertEqual("2028-W01", patch["merge"]["campaign"]["calendar"]["label"])
        self.assertIn("momentum", patch["merge"]["campaign"])

    def test_campaign_presentation_does_not_mutate_retained_state(self) -> None:
        state = CampaignState(
            campaign_name="presentation-purity",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={
                "nato": FactionState(Faction.NATO, resources=1000),
            },
            provinces={
                "p": Province("p", "P", Faction.NATO, []),
            },
        )
        before = copy.deepcopy(state.to_dict())
        presentation = campaign_presentation(state)
        self.assertEqual("2028-W01", presentation["calendar"]["label"])
        self.assertEqual("medium", presentation["length_preset"])
        self.assertNotIn(CAMPAIGN_RULES_KEY, state.map_metadata)
        self.assertEqual(before, state.to_dict())

    def test_persist_gate_unchanged_for_rules_commands(self) -> None:
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "end_player_round"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "continue_playing"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "conclude_campaign"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertTrue(
            _should_persist_runtime_snapshot(
                [{"op": "issue_move_order"}, {"op": "commit_move_orders"}]
            )
        )
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))

    def test_play_parser_accepts_length_preset_and_fog(self) -> None:
        args = build_play_parser().parse_args(
            ["--new", "--length-preset", "long", "--fog-of-war", "on", "--no-launch"]
        )
        self.assertEqual("long", args.length_preset)
        self.assertEqual("on", args.fog_of_war)

    def test_auto_resolve_major_win_is_recorded_for_attacker(self) -> None:
        state = _rules_state()
        pending = PendingBattle(
            battle_id="b1",
            origin_province_id="a",
            target_province_id="x",
            attacker_faction=Faction.NATO,
            defender_faction=Faction.RUSSIA,
            attacking_participants=[],
            defending_participants=[],
            player_faction=Faction.NATO,
            player_is_attacker=True,
        )
        record_auto_resolve_result(state, Faction.NATO, pending)
        self.assertEqual(1, state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"]["nato"])
        record_auto_resolve_result(state, Faction.RUSSIA, pending)
        self.assertEqual(1, state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"]["nato"])

    def test_legacy_capital_hold_still_works_without_p9_model(self) -> None:
        state = _rules_state(p9=False)
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
        first = evaluate_campaign_outcome(state, advance_hold=True)
        second = evaluate_campaign_outcome(state, advance_hold=True)
        self.assertEqual("active", first.status)
        self.assertEqual("complete", second.status)


def _objective(state: CampaignState, identity: str) -> dict:
    return next(
        row
        for row in state.map_metadata["operational_objectives"]
        if row["id"] == identity
    )


def _hold_weeks(state: CampaignState, weeks: int) -> None:
    for _ in range(weeks):
        evaluate_campaign_outcome(state, advance_hold=True)


def _boost_momentum(state: CampaignState, faction_id: str, *, wins: int) -> None:
    events = state.map_metadata[CAMPAIGN_RULES_KEY].setdefault("events", {})
    wins_by_faction = events.setdefault("major_auto_resolve_wins", {})
    wins_by_faction[faction_id] = wins


def _grant_ukraine_national_hold(state: CampaignState) -> None:
    state.provinces["b"].owner = Faction.UKRAINE
    state.provinces["b"].metadata["static_supply_source_for"] = ["ukr"]


def _ukraine_player_state() -> CampaignState:
    return _rules_state(selected=Faction.UKRAINE)


def _rules_state(
    *,
    hub_province: str | None = None,
    p9: bool = True,
    selected: Faction = Faction.NATO,
) -> CampaignState:
    state = CampaignState(
        campaign_name="Rules test",
        selected_faction=selected,
        current_faction=selected,
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
            "x": Province("x", "X", Faction.NATO, ["a", "y"], metadata={"static_supply_source_for": ["nato"]}),
            "y": Province("y", "Y", Faction.RUSSIA, ["x"], metadata={"static_supply_source_for": ["rusa"]}),
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
                "y",
                roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                authorized_roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                formation_id="rusa-formation",
            ),
        },
    )
    ensure_strategic_layer(state)
    if p9:
        ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)
        if hub_province:
            hubs = dict(state.map_metadata[CAMPAIGN_RULES_KEY].get("actor_hubs") or {})
            hubs["usa"] = [hub_province]
            state.map_metadata[CAMPAIGN_RULES_KEY]["actor_hubs"] = hubs
        state.map_metadata["operational_objectives"] = [
            {
                "id": "aim-west",
                "layer": "coalition_war_aim",
                "coalition": "western-coalition",
                "display_name": "Hold X",
                "kind": "control",
                "targets": ["x"],
                "required": 1,
                "reward_each": 0,
                "primary": True,
                "hold_weeks": 4,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
                "target_hold_weeks": {},
            },
            {
                "id": "nat-usa",
                "layer": "national_contribution",
                "owner_type": "actor",
                "owner_id": "usa",
                "coalition": "western-coalition",
                "display_name": "Hold A",
                "kind": "control",
                "targets": ["a"],
                "required": 1,
                "reward_each": 0,
                "primary": False,
                "hold_weeks": 4,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
                "target_hold_weeks": {},
            },
            {
                "id": "nat-ukr",
                "layer": "national_contribution",
                "owner_type": "actor",
                "owner_id": "ukr",
                "coalition": "western-coalition",
                "display_name": "Hold B",
                "kind": "control",
                "targets": ["b"],
                "required": 1,
                "reward_each": 0,
                "primary": False,
                "hold_weeks": 4,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
                "target_hold_weeks": {},
            },
            {
                "id": "aim-east",
                "layer": "coalition_war_aim",
                "coalition": "eastern-coalition",
                "display_name": "Hold A",
                "kind": "control",
                "targets": ["a"],
                "required": 1,
                "reward_each": 0,
                "primary": True,
                "hold_weeks": 4,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
                "target_hold_weeks": {},
            },
            {
                "id": "nat-rus",
                "layer": "national_contribution",
                "owner_type": "actor",
                "owner_id": "rus",
                "coalition": "eastern-coalition",
                "display_name": "Hold Y",
                "kind": "control",
                "targets": ["y"],
                "required": 1,
                "reward_each": 0,
                "primary": False,
                "hold_weeks": 4,
                "progress": 0,
                "completed": False,
                "completed_turn": 0,
                "rewarded": False,
                "target_hold_weeks": {},
            },
        ]
    state.validate()
    return state


if __name__ == "__main__":
    unittest.main()
