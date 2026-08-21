from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from gates_of_codex.campaign import CampaignEngine
from gates_of_codex.campaign_rules import (
    CAMPAIGN_RULES_KEY,
    DEFAULT_HOLD_WEEKS,
    DEFAULT_START_YEAR,
    GRADE_DECISIVE_DEFEAT,
    GRADE_DECISIVE_VICTORY,
    GRADE_DEFEAT,
    GRADE_STALEMATE,
    GRADE_VICTORY,
    PACK_ID_2028_CORE,
    PACK_ID_EARTH3,
    SCENARIO_ID_2028_EXPANDED,
    UNAVAILABLE_EXPANDED_REASON,
    VICTORY_GRADES,
    VICTORY_MODEL_P9,
    CampaignRulesError,
    _validate_2028_core_pack,
    _validate_objective_pack,
    calendar_from_turn,
    campaign_play_blocked,
    campaign_presentation,
    campaign_rules,
    conclude_campaign,
    continue_playing,
    ensure_campaign_rules,
    known_objective_scenario_ids,
    load_campaign_rules_contract,
    load_objective_pack,
    normalize_length_preset,
    objective_pack_for_state,
    player_actor_id,
    record_auto_resolve_result,
    require_available_victory_pack,
    resolve_objective_pack_id,
)
from gates_of_codex.command_cycle_perf import _should_persist_runtime_snapshot
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA_VERSION,
    build_frontend_runtime_patch,
)
from gates_of_codex.frontend_snapshot_slim import slim_unused_frontend_fields
from gates_of_codex.models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    BattleParticipant,
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

    def test_objective_packs_bind_by_scenario_id_not_faction_names(self) -> None:
        contract = load_campaign_rules_contract()
        resolution = contract["objective_pack_resolution"]
        self.assertEqual("refuse", resolution["unknown_scenario"])
        self.assertEqual(PACK_ID_EARTH3, resolution["default_when_scenario_id_omitted"])
        self.assertEqual(PACK_ID_EARTH3, resolve_objective_pack_id(""))
        self.assertEqual(PACK_ID_EARTH3, resolve_objective_pack_id("earth3_v1"))
        self.assertEqual(PACK_ID_EARTH3, resolve_objective_pack_id("earth3_native_acceptance"))
        self.assertEqual(PACK_ID_EARTH3, resolve_objective_pack_id("legacy_goe_europe"))
        self.assertEqual(PACK_ID_EARTH3, resolve_objective_pack_id("legacy_goe_europe_mediterranean"))
        self.assertEqual(PACK_ID_2028_CORE, resolve_objective_pack_id("ww3_2028_core"))
        self.assertIn("ww3_2028_core", known_objective_scenario_ids())
        self.assertIn(SCENARIO_ID_2028_EXPANDED, known_objective_scenario_ids())
        self.assertNotIn(SCENARIO_ID_2028_EXPANDED, resolution["packs"])
        self.assertIn(SCENARIO_ID_2028_EXPANDED, resolution["unavailable_scenario_ids"])
        with self.assertRaisesRegex(ValueError, "registered but unavailable"):
            resolve_objective_pack_id("ww3_2028_expanded")
        with self.assertRaisesRegex(ValueError, "Unknown campaign scenario 'ww3_1991_fantasy'"):
            resolve_objective_pack_id("ww3_1991_fantasy")
        core = load_objective_pack(PACK_ID_2028_CORE)
        self.assertEqual(["ww3_2028_core"], core["scenario_ids"])
        self.assertNotIn(SCENARIO_ID_2028_EXPANDED, core["scenario_ids"])
        self.assertEqual("nato", core["actor_faction"]["nato"])
        self.assertEqual("rusa", core["player_actor_by_faction"]["rusa"])
        self.assertEqual({"nato", "ukr", "rusa", "prc"}, {row["owner_id"] for row in core["national_objectives"]})
        earth3 = load_objective_pack(PACK_ID_EARTH3)
        self.assertEqual("usa", earth3["player_actor_by_faction"]["nato"])
        self.assertEqual("rus", earth3["player_actor_by_faction"]["rusa"])


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
        self._assert_opposing_contract_player_facing_defeat(outcome, state)
        with self.assertRaisesRegex(ValueError, "only available after victory"):
            continue_playing(state)
        snapshot = {
            "campaign": {
                **campaign_presentation(state),
                "outcome": asdict(outcome),
            }
        }
        model = _campaign_rules_result_model(snapshot)
        self.assertTrue(model["visible"])
        self.assertFalse(model["victory"])
        self.assertFalse(model["show_continue"])
        self.assertEqual("Defeat", model["grade_label"])
        self.assertNotIn(model["grade"], VICTORY_GRADES)
        presenter = (
            Path(__file__).resolve().parents[1]
            / "godot"
            / "scripts"
            / "presentation"
            / "campaign_rules_presenter.gd"
        ).read_text(encoding="utf-8")
        self.assertIn("static func result_model(snapshot: Dictionary)", presenter)
        self.assertIn('faction_result != "defeat"', presenter)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opposing-defeat.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        restored = evaluate_campaign_outcome(loaded)
        self._assert_opposing_contract_player_facing_defeat(restored, loaded)
        with self.assertRaisesRegex(ValueError, "only available after victory"):
            continue_playing(loaded)

    def _assert_opposing_contract_player_facing_defeat(self, outcome, state) -> None:
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertEqual(GRADE_DEFEAT, outcome.grade)
        self.assertNotIn(outcome.grade, VICTORY_GRADES)
        self.assertEqual("eastern-coalition", outcome.winner_coalition)
        self.assertEqual("western-coalition", outcome.loser_coalition)
        self.assertEqual("incomplete", outcome.coalition_result)
        self.assertEqual("incomplete", outcome.national_result)
        self.assertNotEqual("victory", outcome.coalition_result)
        self.assertNotEqual("victory", outcome.national_result)
        self.assertIn("opposing coalition", outcome.reason)
        self.assertFalse(state.map_metadata[CAMPAIGN_RULES_KEY].get("continue_playing"))
        locked = state.map_metadata[CAMPAIGN_RULES_KEY].get("locked_result") or {}
        self.assertEqual("defeat", locked.get("selected_faction_result"))
        self.assertEqual(GRADE_DEFEAT, locked.get("grade"))
        self.assertEqual("incomplete", locked.get("coalition_result"))
        self.assertEqual("incomplete", locked.get("national_result"))

    def test_opposing_contract_does_not_copy_vacuous_layer_victory(self) -> None:
        """required_*=0 makes _layer_result return victory; player-facing fields must not."""

        from gates_of_codex.campaign_rules import (
            _layer_result,
            _player_facing_layer_result,
        )

        state = _ukraine_player_state()
        rules = state.map_metadata[CAMPAIGN_RULES_KEY]
        rules["required_war_aims"] = 0
        rules["required_national"] = 0
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "coalition_war_aim"))
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "national_contribution"))
        self.assertEqual(
            "defeat",
            _player_facing_layer_result(
                state, Faction.UKRAINE, "coalition_war_aim", selected_result="defeat"
            ),
        )
        self.assertEqual(
            "defeat",
            _player_facing_layer_result(
                state, Faction.UKRAINE, "national_contribution", selected_result="defeat"
            ),
        )
        self.assertEqual(
            "victory",
            _player_facing_layer_result(
                state, Faction.UKRAINE, "coalition_war_aim", selected_result="victory"
            ),
        )

    def test_opposing_contract_does_not_report_own_completed_layers_as_victory(self) -> None:
        """Eastern sorts first. Own completed layers stay selected-player defeat, not victory."""

        from gates_of_codex.campaign_rules import _layer_result, update_momentum

        state = _ukraine_player_state()
        _grant_ukraine_national_hold(state)
        for row in state.map_metadata["operational_objectives"]:
            if row["id"] in {"aim-west", "aim-east", "nat-ukr", "nat-rus"}:
                row["completed"] = True
                row["progress"] = int(row.get("required") or 1)
        _boost_momentum(state, "rusa", wins=8)
        _boost_momentum(state, "ukr", wins=6)
        update_momentum(state)
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "coalition_war_aim"))
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "national_contribution"))
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertEqual(GRADE_DEFEAT, outcome.grade)
        self.assertEqual("eastern-coalition", outcome.winner_coalition)
        self.assertEqual("western-coalition", outcome.loser_coalition)
        self.assertEqual("defeat", outcome.coalition_result)
        self.assertEqual("defeat", outcome.national_result)
        self.assertNotEqual("victory", outcome.coalition_result)
        self.assertNotEqual("victory", outcome.national_result)
        with self.assertRaisesRegex(ValueError, "only available after victory"):
            continue_playing(state)
        snapshot = {
            "campaign": {
                **campaign_presentation(state),
                "outcome": asdict(outcome),
            }
        }
        model = _campaign_rules_result_model(snapshot)
        self.assertFalse(model["victory"])
        self.assertFalse(model["show_continue"])
        self.assertEqual("defeat", model["coalition_result"])
        self.assertEqual("defeat", model["national_result"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "own-layer-defeat.json"
            save_campaign(state, path)
            loaded = load_campaign(path)
        restored = evaluate_campaign_outcome(loaded)
        self.assertEqual("defeat", restored.selected_faction_result)
        self.assertEqual(GRADE_DEFEAT, restored.grade)
        self.assertEqual("defeat", restored.coalition_result)
        self.assertEqual("defeat", restored.national_result)

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
        self._assert_opposing_contract_player_facing_defeat(restored_defeat, loaded_defeat)

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
        self._assert_opposing_contract_player_facing_defeat(ai_defeat, opposing)

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

    def test_campaign_play_blocked_without_map_metadata_is_not_blocked(self) -> None:
        """End Turn stubs and legacy states without map_metadata must not crash."""

        from types import SimpleNamespace

        stub = SimpleNamespace()
        self.assertFalse(campaign_play_blocked(stub))  # type: ignore[arg-type]
        self.assertEqual({}, campaign_rules(stub))  # type: ignore[arg-type]

    def test_end_player_round_can_lock_time_limit_without_already_complete(self) -> None:
        """UKR is not last in TURN_ORDER. Crossing the cap must not abort the round."""

        from gates_of_codex.turn_cycle import end_player_round

        state = _ukraine_player_state()
        state.turn_number = int(state.map_metadata[CAMPAIGN_RULES_KEY]["turn_cap"])
        state.current_faction = Faction.UKRAINE
        report = end_player_round(state)
        self.assertFalse(report["pending_battle"])
        outcome = state.map_metadata.get("campaign_outcome") or {}
        self.assertEqual("complete", outcome.get("status"))
        self.assertTrue(campaign_play_blocked(state))
        self.assertGreater(
            int(state.turn_number),
            int(state.map_metadata[CAMPAIGN_RULES_KEY]["turn_cap"]),
        )

    def test_zero_required_war_aims_can_lock_victory_without_coalition_aim(self) -> None:
        """Explicit required_war_aims=0 must not be treated as 1 by ``or 1``."""

        from gates_of_codex.campaign_rules import (
            _layer_result,
            _owner_victory_report,
            _required_count,
            update_momentum,
        )

        self.assertEqual(0, _required_count({"required_war_aims": 0}, "required_war_aims"))
        self.assertEqual(1, _required_count({}, "required_war_aims"))
        self.assertEqual(1, _required_count({"required_war_aims": None}, "required_war_aims"))

        state = _ukraine_player_state()
        state.provinces["x"].owner = Faction.RUSSIA
        _grant_ukraine_national_hold(state)
        _hold_weeks(state, 4)
        _boost_momentum(state, "ukr", wins=6)
        update_momentum(state)
        rules = state.map_metadata[CAMPAIGN_RULES_KEY]
        rules["required_war_aims"] = 0
        rules["thresholds"]["victory"] = 1
        self.assertFalse(_objective(state, "aim-west")["completed"])
        self.assertTrue(_objective(state, "nat-ukr")["completed"])
        report = _owner_victory_report(
            state,
            "western-coalition",
            {Faction.NATO, Faction.UKRAINE},
            Faction.UKRAINE,
        )
        self.assertIsNotNone(report)
        self.assertIn(report["grade"], {GRADE_VICTORY, GRADE_DECISIVE_VICTORY})
        self.assertEqual("victory", report["national_result"])
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "coalition_war_aim"))
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "national_contribution"))

    def test_time_limit_honors_zero_required_war_aims(self) -> None:
        from gates_of_codex.campaign_rules import _layer_result, _time_limit_grade, update_momentum

        state = _ukraine_player_state()
        state.provinces["x"].owner = Faction.RUSSIA
        _grant_ukraine_national_hold(state)
        _hold_weeks(state, 4)
        _boost_momentum(state, "ukr", wins=6)
        update_momentum(state)
        rules = state.map_metadata[CAMPAIGN_RULES_KEY]
        rules["required_war_aims"] = 0
        rules["thresholds"]["victory"] = 1
        state.turn_number = int(rules["turn_cap"]) + 1
        self.assertFalse(_objective(state, "aim-west")["completed"])
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "coalition_war_aim"))
        self.assertEqual("victory", _layer_result(state, Faction.UKRAINE, "national_contribution"))
        self.assertEqual(
            GRADE_VICTORY,
            _time_limit_grade(state, Faction.UKRAINE, rules["thresholds"]),
        )

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

    def test_continue_playing_rejects_contradictory_defeat_tuple(self) -> None:
        """selected_faction_result=defeat must block Continue even if grade leaked victory."""

        state = _ukraine_player_state()
        evaluate_campaign_outcome(state)
        leaked = {
            "status": "complete",
            "winner_coalition": "eastern-coalition",
            "loser_coalition": "western-coalition",
            "reason": "campaign victory: required war aims and national contribution before the turn cap",
            "selected_faction_result": "defeat",
            "grade": GRADE_VICTORY,
            "coalition_result": "victory",
            "national_result": "victory",
            "continue_playing": False,
            "concluded": False,
            "momentum": 60,
        }
        state.map_metadata["campaign_outcome"] = dict(leaked)
        state.map_metadata[CAMPAIGN_RULES_KEY]["result_locked"] = True
        state.map_metadata[CAMPAIGN_RULES_KEY]["locked_result"] = dict(leaked)
        with self.assertRaisesRegex(ValueError, "only available after victory"):
            continue_playing(state)
        model = _campaign_rules_result_model(
            {"campaign": {**campaign_presentation(state), "outcome": leaked}}
        )
        self.assertFalse(model["victory"])
        self.assertFalse(model["show_continue"])

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

    def test_presentation_does_not_initialize_campaign_rules(self) -> None:
        state = CampaignState(
            campaign_name="presentation-purity",
            selected_faction=Faction.NATO,
            current_faction=Faction.NATO,
            factions={"nato": FactionState(Faction.NATO, resources=0)},
            provinces={"p": Province("p", "P", Faction.NATO, [])},
        )
        before = copy.deepcopy(state.to_dict())
        presentation = campaign_presentation(state)
        self.assertEqual("2028-W01", presentation["calendar"]["label"])
        self.assertEqual(before, state.to_dict())
        self.assertNotIn(CAMPAIGN_RULES_KEY, state.map_metadata)

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


class CampaignRules2028PackTests(unittest.TestCase):
    def test_unknown_scenario_refuses_to_start(self) -> None:
        state = _rules_state()
        state.map_metadata["scenario_id"] = "ww3_1991_fantasy"
        with self.assertRaisesRegex(ValueError, "Unknown campaign scenario 'ww3_1991_fantasy'"):
            ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)

    def test_scenario_profile_mismatch_refuses_to_start(self) -> None:
        state = _rules_state()
        state.map_metadata["scenario_id"] = "ww3_2028_core"
        state.map_metadata["scenario_profile"] = {"scenario_id": "earth3_v1"}
        with self.assertRaisesRegex(ValueError, "scenario_id mismatch"):
            ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)

    def test_four_power_factions_with_earth3_id_do_not_select_2028_pack(self) -> None:
        state = _rules_state()
        state.map_metadata["scenario_id"] = "earth3_v1"
        ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)
        self.assertEqual(PACK_ID_EARTH3, state.map_metadata[CAMPAIGN_RULES_KEY]["objective_pack_id"])
        self.assertEqual("usa", player_actor_id(state))
        self.assertEqual("usa", objective_pack_for_state(state)["player_actor_by_faction"]["nato"])
        ids = {row["id"] for row in state.map_metadata["operational_objectives"]}
        self.assertNotIn("aim_2028_west_donbas", ids)
        self.assertNotIn("nat_2028_nato_berlin", ids)

    def test_earth3_fixture_nationals_still_inject_on_earth3_scenario(self) -> None:
        state = _earth3_location_state(scenario_id="earth3_v1")
        ids = {row["id"] for row in state.map_metadata["operational_objectives"]}
        self.assertIn("nat_usa_berlin_hub", ids)
        self.assertIn("nat_ukr_kyiv", ids)
        self.assertIn("nat_rus_rostov", ids)
        self.assertNotIn("nat_2028_nato_berlin", ids)
        self.assertEqual("usa", _objective(state, "nat_usa_berlin_hub")["owner_id"])

    def test_core_settings_load_four_power_aims(self) -> None:
        state = _earth3_location_state(scenario_id="ww3_2028_core")
        self.assertEqual(PACK_ID_2028_CORE, state.map_metadata[CAMPAIGN_RULES_KEY]["objective_pack_id"])
        self.assertEqual("nato", player_actor_id(state))
        ids = {row["id"] for row in state.map_metadata["operational_objectives"]}
        self.assertEqual(
            {
                "aim_2028_west_donbas",
                "aim_2028_east_kyiv_vilnius",
                "nat_2028_nato_berlin",
                "nat_2028_ukr_kyiv",
                "nat_2028_rusa_rostov",
                "nat_2028_prc_vilnius",
            },
            ids,
        )
        self.assertEqual("nato", _objective(state, "nat_2028_nato_berlin")["owner_id"])
        self.assertEqual("rusa", _objective(state, "nat_2028_rusa_rostov")["owner_id"])
        self.assertEqual("prc", _objective(state, "nat_2028_prc_vilnius")["owner_id"])
        self.assertNotIn("nat_usa_berlin", ids)
        self.assertNotIn("nat_rus_rostov", ids)
        for row in state.map_metadata["operational_objectives"]:
            self.assertEqual(4, row["hold_weeks"])
            self.assertIn(row["layer"], {"coalition_war_aim", "national_contribution"})

    def test_expanded_creates_without_victory_pack_and_skips_terminal_evaluation(self) -> None:
        state = _rules_state(p9=False)
        state.map_metadata.pop(CAMPAIGN_RULES_KEY, None)
        state.map_metadata["scenario_id"] = SCENARIO_ID_2028_EXPANDED
        rules = ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)
        self.assertNotIn("objective_pack_id", rules)
        self.assertNotEqual(PACK_ID_2028_CORE, rules.get("objective_pack_id"))
        self.assertNotEqual(PACK_ID_EARTH3, rules.get("objective_pack_id"))
        self.assertEqual("short", rules["length_preset"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("active", outcome.status)
        self.assertEqual("active", outcome.selected_faction_result)
        self.assertEqual("", outcome.grade)
        self.assertNotIn("objective_pack_id", state.map_metadata.get(CAMPAIGN_RULES_KEY) or {})
        with self.assertRaisesRegex(CampaignRulesError, "Core-four pack"):
            require_available_victory_pack(state)
        pending = PendingBattle(
            battle_id="expanded-playable",
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
        self.assertEqual(
            1,
            state.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"]["nato"],
        )
        self.assertNotIn("objective_pack_id", state.map_metadata.get(CAMPAIGN_RULES_KEY) or {})

    def test_expanded_auto_resolve_clears_battle_without_terminal_victory(self) -> None:
        """Unmocked: Expanded pending battle Auto-Resolves and stays playable."""

        state = _earth3_location_state(scenario_id=SCENARIO_ID_2028_EXPANDED)
        self.assertNotIn(
            "objective_pack_id",
            state.map_metadata.get(CAMPAIGN_RULES_KEY) or {},
        )
        state.pending_battle = PendingBattle(
            battle_id="expanded-ar",
            origin_province_id="e3_0592",
            target_province_id="e3_2793",
            attacker_faction=Faction.NATO,
            defender_faction=Faction.RUSSIA,
            attacking_participants=[
                BattleParticipant("nato-1", Faction.NATO, "committed", is_primary=True)
            ],
            defending_participants=[
                BattleParticipant("rusa-1", Faction.RUSSIA, "committed", is_primary=True)
            ],
            player_faction=Faction.NATO,
            player_is_attacker=True,
        )
        winner = CampaignEngine(state).auto_resolve_pending_battle()
        self.assertIn(winner, {Faction.NATO, Faction.RUSSIA})
        self.assertIsNone(state.pending_battle)
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("active", outcome.status)
        self.assertEqual("active", outcome.selected_faction_result)
        self.assertEqual("", outcome.grade)
        self.assertFalse(campaign_play_blocked(state))
        self.assertNotIn(
            "objective_pack_id",
            state.map_metadata.get(CAMPAIGN_RULES_KEY) or {},
        )
        with self.assertRaisesRegex(CampaignRulesError, "unavailable"):
            require_available_victory_pack(state)
        next_faction = CampaignEngine(state).end_turn()
        self.assertIn(next_faction, set(CampaignEngine.TURN_ORDER))
        self.assertFalse(campaign_play_blocked(state))

    def test_expanded_refuses_stamped_core_or_earth3_victory_pack(self) -> None:
        state = _rules_state(p9=False)
        state.map_metadata.pop(CAMPAIGN_RULES_KEY, None)
        state.map_metadata["scenario_id"] = SCENARIO_ID_2028_EXPANDED
        state.map_metadata[CAMPAIGN_RULES_KEY] = {"objective_pack_id": PACK_ID_2028_CORE}
        with self.assertRaisesRegex(CampaignRulesError, "does not match scenario"):
            ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)
        state.map_metadata[CAMPAIGN_RULES_KEY] = {"objective_pack_id": PACK_ID_EARTH3}
        with self.assertRaisesRegex(CampaignRulesError, "does not match scenario"):
            ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)

    def test_expanded_unavailable_reason_does_not_claim_core_four_coverage(self) -> None:
        reason = load_campaign_rules_contract()["objective_pack_resolution"][
            "unavailable_scenario_ids"
        ][SCENARIO_ID_2028_EXPANDED]
        self.assertIn("Poland", reason)
        self.assertIn("DPRK", reason)
        self.assertEqual(UNAVAILABLE_EXPANDED_REASON, reason)
        with self.assertRaisesRegex(CampaignRulesError, r"Poland|France|Germany|Serbia|DPRK"):
            resolve_objective_pack_id(SCENARIO_ID_2028_EXPANDED)

    def test_core_four_validation_is_not_imposed_on_non_core_packs(self) -> None:
        future = {
            "schema_version": 1,
            "pack_id": "ww3_2028_future_example",
            "scenario_ids": ["ww3_2028_future_example"],
            "actor_faction": {"pol": "nato", "fra": "nato", "deu": "nato", "srb": "rusa", "dprk": "rusa"},
            "player_actor_by_faction": {"nato": "pol", "rusa": "srb"},
            "war_aims": [
                {
                    "id": "aim_future_example",
                    "owner_id": "western_coalition",
                    "hold_weeks": 4,
                }
            ],
            "national_objectives": [
                {
                    "id": "nat_pol_warsaw",
                    "owner_id": "pol",
                    "hold_weeks": 4,
                }
            ],
        }
        _validate_objective_pack(future, expected_pack_id="ww3_2028_future_example")
        with self.assertRaisesRegex(CampaignRulesError, r"must map actor 'nato'|nato, ukr, rusa, and prc"):
            _validate_2028_core_pack(future)

    def test_core_campaign_can_win_and_lose_in_p9_engine(self) -> None:
        winning = _earth3_location_state(scenario_id="ww3_2028_core")
        for _ in range(4):
            evaluate_campaign_outcome(winning, advance_hold=True)
        self.assertTrue(_objective(winning, "aim_2028_west_donbas")["completed"])
        self.assertTrue(_objective(winning, "nat_2028_nato_berlin")["completed"])
        winning.map_metadata[CAMPAIGN_RULES_KEY]["events"]["major_auto_resolve_wins"] = {"nato": 6}
        outcome = evaluate_campaign_outcome(winning)
        self.assertEqual("complete", outcome.status)
        self.assertIn(outcome.grade, {GRADE_VICTORY, "decisive_victory"})
        self.assertEqual("victory", outcome.selected_faction_result)
        self.assertEqual("victory", outcome.national_result)

        losing = _earth3_location_state(scenario_id="ww3_2028_core")
        losing.provinces["e3_0592"].owner = Faction.RUSSIA
        for week in range(3):
            self.assertEqual("active", evaluate_campaign_outcome(losing, advance_hold=True).status, week)
        defeat = evaluate_campaign_outcome(losing, advance_hold=True)
        self.assertEqual("complete", defeat.status)
        self.assertEqual("defeat", defeat.selected_faction_result)
        self.assertEqual(GRADE_DEFEAT, defeat.grade)
        self.assertIn("capital or control hub", defeat.reason)

    def test_core_allied_national_success_does_not_end_ukraine_campaign(self) -> None:
        """Human UKR on Core-four: Western aims + NATO national, UKR national incomplete => ACTIVE."""

        state = _earth3_location_state(scenario_id="ww3_2028_core", selected=Faction.UKRAINE)
        state.provinces["e3_1937"].owner = Faction.NATO
        _hold_weeks(state, 4)
        _boost_momentum(state, "nato", wins=6)
        self.assertTrue(_objective(state, "aim_2028_west_donbas")["completed"])
        self.assertTrue(_objective(state, "nat_2028_nato_berlin")["completed"])
        self.assertFalse(_objective(state, "nat_2028_ukr_kyiv")["completed"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("active", outcome.status)
        self.assertEqual("active", outcome.selected_faction_result)
        self.assertFalse(campaign_play_blocked(state))
        self.assertNotEqual("defeat", outcome.selected_faction_result)

    def test_core_ukraine_victory_requires_own_national_contribution(self) -> None:
        """Human UKR on Core-four: Western aims + UKR national + threshold => VICTORY."""

        state = _earth3_location_state(scenario_id="ww3_2028_core", selected=Faction.UKRAINE)
        _hold_weeks(state, 4)
        _boost_momentum(state, "ukr", wins=6)
        self.assertTrue(_objective(state, "aim_2028_west_donbas")["completed"])
        self.assertTrue(_objective(state, "nat_2028_ukr_kyiv")["completed"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("victory", outcome.selected_faction_result)
        self.assertIn(outcome.grade, {GRADE_VICTORY, "decisive_victory"})
        self.assertEqual("victory", outcome.national_result)
        self.assertEqual("victory", outcome.coalition_result)

    def test_core_opposing_coalition_contract_defeats_ukraine_player(self) -> None:
        """Eastern Core-four contract => human UKR DEFEAT."""

        state = _earth3_location_state(scenario_id="ww3_2028_core", selected=Faction.UKRAINE)
        # Keep UKR off the hub-loss path so this asserts the opposing-contract result.
        hubs = dict(state.map_metadata[CAMPAIGN_RULES_KEY].get("actor_hubs") or {})
        hubs["ukr"] = []
        state.map_metadata[CAMPAIGN_RULES_KEY]["actor_hubs"] = hubs
        for province_id in ("e3_0442", "e3_1937", "e3_2794", "e3_3380"):
            state.provinces[province_id].owner = Faction.RUSSIA
        _hold_weeks(state, 4)
        _boost_momentum(state, "rusa", wins=8)
        self.assertTrue(_objective(state, "aim_2028_east_kyiv_vilnius")["completed"])
        self.assertTrue(_objective(state, "nat_2028_rusa_rostov")["completed"])
        outcome = evaluate_campaign_outcome(state)
        self.assertEqual("complete", outcome.status)
        self.assertEqual("defeat", outcome.selected_faction_result)
        self.assertEqual("eastern-coalition", outcome.winner_coalition)

    def test_snapshot_exposes_2028_aims_without_slim_metadata(self) -> None:
        state = _earth3_location_state(scenario_id="ww3_2028_core")
        evaluate_campaign_outcome(state)
        snapshot = build_frontend_snapshot(state)
        objectives = snapshot["objectives"]
        self.assertTrue(objectives)
        donbas = next(row for row in objectives if row["id"] == "aim_2028_west_donbas")
        self.assertEqual("Secure Donetsk and Luhansk", donbas["display_name"])
        self.assertEqual("coalition_war_aim", donbas["layer"])
        self.assertEqual(2, donbas["required"])
        self.assertNotIn("threshold", donbas)
        kyiv = next(row for row in objectives if row["id"] == "nat_2028_ukr_kyiv")
        self.assertEqual("Defend Kyiv", kyiv["display_name"])
        self.assertEqual("national_contribution", kyiv["layer"])
        slimmed = slim_unused_frontend_fields(copy.deepcopy(snapshot))
        metadata = slimmed["campaign"]["map_metadata"]
        self.assertNotIn("operational_objectives", metadata)
        self.assertEqual("ww3_2028_core", slimmed["application"]["scenario_id"])
        self.assertTrue(
            any(row["id"] == "aim_2028_west_donbas" for row in slimmed["objectives"])
        )
        patch = build_frontend_runtime_patch(state)
        self.assertEqual(1, RUNTIME_PATCH_SCHEMA_VERSION)
        self.assertEqual(1, patch["schema_version"])
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "continue_playing"}]))
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))


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


def _campaign_rules_result_model(snapshot: dict) -> dict:
    """Apply CampaignRulesPresenter.result_model victory/continue rules."""

    campaign = snapshot.get("campaign") or {}
    row = campaign.get("outcome") or {}
    if not isinstance(row, dict):
        return {"visible": False}
    status = str(row.get("status") or "active")
    continue_playing_flag = bool(campaign.get("continue_playing", row.get("continue_playing", False)))
    concluded = bool(campaign.get("concluded", row.get("concluded", False)))
    grade = str(row.get("grade") or "").strip()
    if status != "complete" and not grade:
        return {"visible": False, "continue_playing": continue_playing_flag, "concluded": concluded}
    faction_result = str(row.get("selected_faction_result") or "")
    victory = (grade in VICTORY_GRADES or faction_result == "victory") and faction_result != "defeat"
    labels = {
        "decisive_victory": "Decisive Victory",
        "victory": "Victory",
        "negotiated_advantage": "Negotiated Advantage",
        "stalemate": "Stalemate",
        "defeat": "Defeat",
        "decisive_defeat": "Decisive Defeat",
    }
    return {
        "visible": (not continue_playing_flag) or concluded,
        "grade": grade,
        "grade_label": labels.get(grade, grade or "Complete"),
        "show_continue": victory and not continue_playing_flag and not concluded,
        "victory": victory,
        "coalition_result": str(row.get("coalition_result") or ""),
        "national_result": str(row.get("national_result") or ""),
    }


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


def _earth3_location_state(*, scenario_id: str, selected: Faction = Faction.NATO) -> CampaignState:
    state = CampaignState(
        campaign_name="2028 pack test",
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
            "e3_0592": Province("e3_0592", "Berlin", Faction.NATO, ["e3_0442"], metadata={"static_supply_source_for": ["nato"]}),
            "e3_0442": Province("e3_0442", "Vilnius", Faction.NATO, ["e3_0592", "e3_1937"]),
            "e3_1937": Province("e3_1937", "Kyiv", Faction.UKRAINE, ["e3_0442", "e3_2794"], metadata={"static_supply_source_for": ["ukr"]}),
            "e3_2794": Province("e3_2794", "Luhansk", Faction.NATO, ["e3_1937", "e3_3380"]),
            "e3_3380": Province("e3_3380", "Donetsk", Faction.NATO, ["e3_2794", "e3_2793"]),
            "e3_2793": Province("e3_2793", "Rostov", Faction.RUSSIA, ["e3_3380"], metadata={"static_supply_source_for": ["rusa"]}),
        },
        battalions={
            "nato-1": Battalion(
                "nato-1",
                Faction.NATO,
                "e3_0592",
                roster=[BattalionRosterEntry("rifle(nato)", 3, category="infantry")],
                authorized_roster=[BattalionRosterEntry("rifle(nato)", 3, category="infantry")],
                formation_id="nato-formation",
            ),
            "rusa-1": Battalion(
                "rusa-1",
                Faction.RUSSIA,
                "e3_2793",
                roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                authorized_roster=[BattalionRosterEntry("rifle(rusa)", 3, category="infantry")],
                formation_id="rusa-formation",
            ),
        },
    )
    state.map_metadata["scenario_id"] = scenario_id
    state.map_metadata["operational_objectives"] = []
    ensure_strategic_layer(state)
    ensure_campaign_rules(state, length_preset="short", victory_model=VICTORY_MODEL_P9)
    state.validate()
    return state


if __name__ == "__main__":
    unittest.main()
