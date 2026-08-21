from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from gates_of_codex.actor_economy import ACTOR_CONTENT_KEY, settle_actor_round_economy
from gates_of_codex.command_cycle_perf import (
    _RUNTIME_PATCH_OPS,
    _SNAPSHOT_PATCH_OPS,
    _should_persist_runtime_snapshot,
)
from gates_of_codex.economy import run_ai_economy, settle_round_economy
from gates_of_codex.end_turn_economy_report import (
    ECONOMY_REPORT_SCHEMA,
    ECONOMY_REPORT_SCHEMA_VERSION,
    OTHER_ACTORS_SUMMARY,
    SETTLE_ACTOR_SOURCE,
    ai_economy_actions_present,
    build_end_turn_economy_report,
)
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend_actor_force import build_acting_actor_presentation
from gates_of_codex.frontend_runtime_patch import build_frontend_runtime_patch
from gates_of_codex.models import Faction
from gates_of_codex.persistent_backend import SUPPORTED_OPS
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.strategic_ai import StrategicAI, StrategicAction
from gates_of_codex.strategic_actors import assign_province_actor, ensure_strategic_actor_runtime
from gates_of_codex.turn_cycle import end_player_round

from test_actor_economy import _resolved_payload


class EndTurnEconomyReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(self.state)
        from gates_of_codex.actor_economy import install_actor_content

        install_actor_content(self.state, _resolved_payload(), selected_actor_id="fra")
        self.province = next(
            value for value in self.state.provinces.values() if value.owner == Faction.NATO
        )
        assign_province_actor(self.state, self.province.province_id, "fra")
        actors = self.state.map_metadata["strategic_actor_runtime"]["actors"]
        actors["fra"]["resources"] = 10_000
        actors["deu"]["resources"] = 10_000
        actors["rus"]["resources"] = 10_000

    def test_end_player_round_report_matches_shared_settlement_row(self) -> None:
        with patch(
            "gates_of_codex.turn_cycle.StrategicAI.take_turn",
            autospec=True,
            return_value=[],
        ):
            payload = end_player_round(self.state)

        report = payload["economy_report"]
        rows = self.state.map_metadata[ACTOR_CONTENT_KEY]["last_round_economy"]
        by_actor = {row["actor_id"]: row for row in rows}
        self.assertGreater(len(by_actor), 1, "settlement must write every actor, not only the player")
        self.assertIn("deu", by_actor)
        self.assertIn("rus", by_actor)
        expected = by_actor["fra"]
        self.assertTrue(report["settled"])
        self.assertEqual(SETTLE_ACTOR_SOURCE, report["source"])
        self.assertEqual(ECONOMY_REPORT_SCHEMA, report["schema"])
        self.assertEqual(ECONOMY_REPORT_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual("fra", report["actor_id"])
        self.assertEqual(expected["income"], report["income"])
        self.assertEqual(expected["maintenance_due"], report["maintenance"])
        self.assertEqual(expected["income"] - expected["maintenance_due"], report["net"])
        self.assertEqual(expected["resources_remaining"], report["treasury"])
        self.assertEqual(self.province.resource_yield, report["income"])
        self.assertFalse(report["other_actors_acted"])
        self.assertEqual("", report["other_actors_summary"])
        encoded = str(report)
        self.assertNotIn("deu", encoded)
        self.assertNotIn("rus", encoded)
        self.assertNotIn("fixture_deu", encoded)

    def test_report_builder_does_not_invent_stale_numbers_without_rollover(self) -> None:
        settle_actor_round_economy(self.state)
        stale = build_end_turn_economy_report(
            self.state,
            starting_turn=int(self.state.turn_number),
            other_actors_acted=False,
        )
        self.assertFalse(stale["settled"])
        self.assertEqual("", stale["source"])
        self.assertNotIn("income", stale)
        self.assertNotIn("treasury", stale)

    def test_other_actors_line_uses_existing_take_turn_economy_actions_only(self) -> None:
        research = StrategicAction(
            battalion_id="",
            action="actor_research",
            target_province_id="actor:rus:unit:fixture_rus",
            details={"action": "actor_research", "actor_id": "rus", "key": "actor:rus:unit:fixture_rus"},
        )
        move = StrategicAction("bn-1", "move", "p1", "p2")
        self.assertTrue(ai_economy_actions_present([research]))
        self.assertFalse(ai_economy_actions_present([move]))
        self.assertFalse(ai_economy_actions_present([]))

        with patch(
            "gates_of_codex.turn_cycle.StrategicAI.take_turn",
            autospec=True,
            return_value=[research],
        ):
            payload = end_player_round(self.state)
        report = payload["economy_report"]
        self.assertTrue(report["other_actors_acted"])
        self.assertEqual(OTHER_ACTORS_SUMMARY, report["other_actors_summary"])
        encoded = str(report)
        self.assertNotIn("actor:rus:unit:fixture_rus", encoded)
        self.assertNotIn("fixture_rus", encoded)
        self.assertNotEqual("rus", report["actor_id"])

        fresh = load_bundled_scenario("legacy_goe_europe")
        ensure_strategic_formations(fresh)
        from gates_of_codex.actor_economy import install_actor_content

        install_actor_content(fresh, _resolved_payload(), selected_actor_id="fra")
        assign_province_actor(
            fresh,
            next(value.province_id for value in fresh.provinces.values() if value.owner == Faction.NATO),
            "fra",
        )
        with patch(
            "gates_of_codex.turn_cycle.StrategicAI.take_turn",
            autospec=True,
            return_value=[move],
        ):
            silent = end_player_round(fresh)["economy_report"]
        self.assertFalse(silent["other_actors_acted"])
        self.assertEqual("", silent["other_actors_summary"])

    def test_ai_and_player_share_the_same_149_economy_entrypoints(self) -> None:
        take_turn_source = inspect.getsource(StrategicAI.take_turn)
        self.assertIn("run_ai_economy(self.state, faction)", take_turn_source)
        economy_source = inspect.getsource(settle_round_economy)
        self.assertIn("settle_actor_round_economy", economy_source)
        self.assertIn("actor_content_runtime", economy_source)
        self.assertNotIn("is_human_controlled", economy_source)
        ai_source = inspect.getsource(run_ai_economy)
        self.assertIn("run_actor_ai_economy", ai_source)
        self.assertNotIn("selected_faction", ai_source)

        turn_source = Path(__file__).resolve().parents[1].joinpath(
            "src/gates_of_codex/turn_cycle.py"
        ).read_text(encoding="utf-8")
        self.assertIn("ai.take_turn(faction)", turn_source)
        self.assertIn("build_end_turn_economy_report", turn_source)
        self.assertIn("settle_round_economy", Path(__file__).resolve().parents[1].joinpath(
            "src/gates_of_codex/campaign.py"
        ).read_text(encoding="utf-8"))

        nato_treasury = self.state.factions[Faction.NATO.value].resources
        russia_before = ensure_strategic_actor_runtime(self.state)["rus"].resources
        actions = run_ai_economy(self.state, Faction.RUSSIA)
        self.assertTrue(actions)
        self.assertTrue(all(str(row.get("action", "")).startswith("actor_") for row in actions))
        russia_after = ensure_strategic_actor_runtime(self.state)["rus"].resources
        self.assertLess(russia_after, russia_before)
        self.assertEqual(nato_treasury, self.state.factions[Faction.NATO.value].resources)

        reports = settle_round_economy(self.state)
        actor_ids = {item.actor_id for item in reports}
        self.assertIn("fra", actor_ids)
        self.assertIn("rus", actor_ids)
        self.assertIn("deu", actor_ids)

    def test_runtime_patch_publishes_acting_actor_treasury_from_settlement(self) -> None:
        with patch(
            "gates_of_codex.turn_cycle.StrategicAI.take_turn",
            autospec=True,
            return_value=[],
        ):
            payload = end_player_round(self.state)
        runtime_patch = build_frontend_runtime_patch(self.state)
        acting = runtime_patch["replace"]["acting_actor"]
        self.assertEqual("fra", acting["actor_id"])
        self.assertEqual(payload["economy_report"]["treasury"], acting["resources"])
        self.assertEqual(payload["economy_report"]["income"], acting["income_last_round"])
        hud = build_acting_actor_presentation(self.state)
        self.assertEqual(hud["resources"], acting["resources"])
        self.assertNotIn("roster", acting)

    def test_persist_seam_does_not_absorb_end_player_round(self) -> None:
        self.assertEqual(
            _SNAPSHOT_PATCH_OPS,
            frozenset({"issue_move_order", "cancel_move_order"}),
        )
        self.assertEqual(
            _RUNTIME_PATCH_OPS,
            frozenset({"end_player_round", "auto_resolve"}),
        )
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "end_player_round"}]))
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))
        self.assertIn("end_player_round", SUPPORTED_OPS)
        persist = Path(__file__).resolve().parents[1].joinpath(
            "src/gates_of_codex/command_cycle_perf.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'return _is_live_move_batch(commands) or _command_ops(commands) == ["auto_resolve"]',
            persist,
        )


if __name__ == "__main__":
    unittest.main()
