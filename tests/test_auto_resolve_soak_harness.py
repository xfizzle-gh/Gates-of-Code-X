from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "auto_resolve_soak_harness.py"
SRC = ROOT / "src"


def _load_harness():
    spec = importlib.util.spec_from_file_location("auto_resolve_soak_harness", HARNESS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {HARNESS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ensure_src_path() -> None:
    src = str(SRC)
    if src not in sys.path:
        sys.path.insert(0, src)
    current = os.environ.get("PYTHONPATH", "")
    parts = [item for item in current.split(os.pathsep) if item]
    if src not in parts:
        os.environ["PYTHONPATH"] = src + (os.pathsep + current if current else "")


class AutoResolveSoakHarnessTests(unittest.TestCase):
    """One class so CI core-lane balancing stays a single small group."""

    def test_persist_gate_and_runtime_patch_schema_remain_exact(self) -> None:
        _ensure_src_path()
        harness = _load_harness()
        payload = harness.persist_gate_contract()
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("gates-of-codex.frontend-runtime-patch", payload["schema"])
        self.assertFalse(payload["refresh_is_runtime_patch_op"])
        self.assertEqual(
            {
                "live_move_batch": True,
                "auto_resolve": True,
                "end_player_round": False,
                "refresh": False,
                "issue_move_order_alone": False,
                "query_supply": False,
                "research": False,
                "recruit": False,
                "assign": False,
                "repair": False,
                "upgrade_site": False,
                "actor_force_panel": False,
            },
            payload["observed"],
        )
        self.assertEqual(3, harness.DEFAULT_CI_TURNS)
        self.assertEqual(10, harness.DEFAULT_LONG_TURNS)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(harness.TURNS_ENV, None)
            self.assertEqual(10, harness._default_turns())
        probe = harness._scenario_probe()
        self.assertTrue(probe["earth3_v1"])
        self.assertEqual("ww3_2028_core", probe["default_scenario_id"])
        self.assertTrue(probe["ww3_2028_core"]["in_registry"])
        self.assertEqual("production", probe["ww3_2028_core"]["status"])

    def test_player_loop_prefers_cheapest_unlock_and_affordable_recruit(self) -> None:
        _ensure_src_path()
        harness = _load_harness()
        panel = {
            "resources": 200,
            "available_research": [
                {"key": "actor:ukr:unit:fixture_ukr_artillery", "cost": 100},
                {"key": "actor:ukr:unit:fixture_ukr_infantry", "cost": 100},
            ],
            "recruitment_offers": [
                {
                    "unit_name": "fixture_ukr_artillery",
                    "purchase_cost": 345,
                    "unlocked": False,
                    "missing_research": ["actor:ukr:unit:fixture_ukr_artillery"],
                    "research_options": ["actor:ukr:unit:fixture_ukr_artillery"],
                },
                {
                    "unit_name": "fixture_ukr_infantry",
                    "purchase_cost": 170,
                    "unlocked": False,
                    "missing_research": ["actor:ukr:unit:fixture_ukr_infantry"],
                    "research_options": ["actor:ukr:unit:fixture_ukr_infantry"],
                },
            ],
        }
        research = harness._cheapest_unlock_research(panel)
        self.assertEqual("actor:ukr:unit:fixture_ukr_infantry", research["key"])
        unlocked = {
            **panel,
            "recruitment_offers": [
                {**panel["recruitment_offers"][0], "unlocked": True},
                {**panel["recruitment_offers"][1], "unlocked": True},
            ],
        }
        offer = harness._cheapest_affordable_offer(unlocked, available=200)
        self.assertEqual("fixture_ukr_infantry", offer["unit_name"])

    def test_harness_fails_closed_when_persist_gate_drifts(self) -> None:
        _ensure_src_path()
        harness = _load_harness()
        with patch(
            "gates_of_codex.command_cycle_perf._should_persist_runtime_snapshot",
            return_value=True,
        ):
            with self.assertRaises(harness.PersistSeamError):
                harness.persist_gate_contract()

    def test_three_turn_s10_smoke_is_not_p10_exit_evidence(self) -> None:
        _ensure_src_path()
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            report = harness.run_soak(
                turns=3,
                work_dir=work,
                fixture="s10",
                use_daemon=True,
                write_full_snapshot=True,
            )
            artifact = harness.write_report(report, work / "auto_resolve_soak.json")
            self.assertTrue(artifact.is_file(), artifact)
            self.assertGreater(artifact.stat().st_size, 0)
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        self.assertTrue(report["ok"], report.get("fatal"))
        self.assertIsNone(report["fatal"])
        self.assertEqual(3, report["turns_completed"])
        self.assertGreaterEqual(report["commands_attempted"], 3)
        self.assertGreaterEqual(report["battles_auto_resolved"], 1)
        self.assertTrue(report["prepared_contact_used"])
        self.assertEqual(0, report["natural_battles_resolved"])
        self.assertFalse(report["p10_exit"])
        self.assertIn("not P10 exit evidence", report["p10_exit_evidence"])
        self.assertFalse(report["goh_invoked"])
        self.assertEqual("parked HOLD — not in this stack", report["goh_parked"]["issue_274"])
        self.assertFalse(report["morale_changed"])
        self.assertTrue(report["runtime_patch_schema_v1"])
        self.assertTrue(report["save_reload"]["performed"])
        self.assertTrue(report["save_reload"]["identity_ok"])
        self.assertEqual("s10_soak_fixture", report["scenario_id"])
        self.assertEqual(payload["turns_completed"], 3)
        rounds = [
            row
            for row in report["commands"]
            if row["ops"] == ["end_player_round"]
        ]
        self.assertTrue(rounds)
        self.assertFalse(rounds[0]["persist_runtime_snapshot"])
        self.assertFalse(rounds[0]["snapshot_changed"])
        auto_rows = [
            row for row in report["commands"] if row["ops"] == ["auto_resolve"]
        ]
        self.assertTrue(auto_rows)
        self.assertTrue(auto_rows[0]["persist_runtime_snapshot"])
        gap_ids = {gap["id"] for gap in report["gaps"]}
        self.assertIn("used_s10_fixture", gap_ids)
        self.assertNotIn("ww3_2028_core", gap_ids)
        self.assertTrue(report["victory_api"]["evaluate_campaign_outcome_exists"])

    def test_documented_cli_smoke_is_optional_subprocess(self) -> None:
        if str(os.environ.get("GOC_AUTO_RESOLVE_SOAK_CLI", "")).strip() not in {
            "1",
            "true",
            "yes",
        }:
            # The in-process 3-turn smoke already covers the player loop.
            # A second subprocess soak would add another ~8s and another
            # daemon spawn to whichever CI core lane draws this class.
            self.skipTest("set GOC_AUTO_RESOLVE_SOAK_CLI=1 to run the CLI subprocess")
        _ensure_src_path()
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            report_path = work / "artifacts" / "auto_resolve_soak.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(HARNESS),
                    "--turns",
                    "3",
                    "--fixture",
                    "s10",
                    "--report",
                    str(report_path),
                    "--work-dir",
                    str(work / "soak"),
                ],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                env={
                    **os.environ,
                    "PYTHONPATH": str(SRC)
                    + (
                        os.pathsep + os.environ["PYTHONPATH"]
                        if os.environ.get("PYTHONPATH")
                        else ""
                    ),
                },
            )
            self.assertEqual(0, completed.returncode, completed.stderr + completed.stdout)
            self.assertTrue(report_path.is_file(), report_path)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertTrue(payload["ok"], payload.get("fatal"))
        self.assertEqual(3, payload["turns_completed"])
        self.assertFalse(payload["p10_exit"])

    def test_optional_2028_acceptance_runs_only_when_env_requests_it(self) -> None:
        if str(os.environ.get("GOC_AUTO_RESOLVE_SOAK", "")).strip() not in {
            "1",
            "true",
            "yes",
        }:
            self.skipTest(
                "set GOC_AUTO_RESOLVE_SOAK=1 to run the ww3_2028_core P10 acceptance soak"
            )
        _ensure_src_path()
        harness = _load_harness()
        with tempfile.TemporaryDirectory() as temporary:
            report = harness.run_soak(
                turns=harness.DEFAULT_LONG_TURNS,
                work_dir=Path(temporary),
                fixture="ww3_2028_core",
                faction="ukr",
                length_preset=harness.P10_ACCEPTANCE_PRESET,
                use_daemon=True,
                write_full_snapshot=False,
            )
        self.assertTrue(report["ok"], report.get("fatal"))
        self.assertEqual("ww3_2028_core", report["scenario_id"])
        self.assertEqual("production", report["scenario_status"])
        self.assertEqual("ukr", report["selected_actor_id"])
        self.assertNotEqual("usa", report["selected_actor_id"])
        self.assertGreaterEqual(report["natural_battles_resolved"], 1)
        self.assertFalse(report["prepared_contact_used"])
        self.assertTrue(report["p10_exit"])
        self.assertIn("naturally produced", report["p10_exit_evidence"])
        self.assertFalse(report["goh_invoked"])
        outcome = report.get("campaign_outcome") or {}
        self.assertEqual("complete", outcome.get("status"))
        self.assertIn(outcome.get("grade"), {"victory", "decisive_victory", "defeat", "decisive_defeat"})
        self.assertIn(outcome.get("selected_faction_result"), {"victory", "defeat"})
        for field in harness.VICTORY_EVIDENCE_FIELDS:
            self.assertIn(field, outcome)
            self.assertIsNotNone(outcome.get(field), field)
        self.assertTrue(outcome.get("matches_authoritative_state"))
        required = report.get("required_capabilities") or {}
        self.assertEqual(set(harness.REQUIRED_P10_CAPABILITIES), set(required))
        self.assertTrue(all(required.values()), required)
        self.assertFalse(report.get("missing_player_loop_capabilities"), report.get("gaps"))
        self.assertTrue(report["continue_identity"]["performed"])
        self.assertEqual("ww3_2028_core", report["continue_identity"]["scenario_id"])
        self.assertEqual("ukr", report["continue_identity"]["selected_actor_id"])

    def test_victory_probe_preserves_authoritative_terminal_fields(self) -> None:
        _ensure_src_path()
        harness = _load_harness()
        fields = harness._outcome_fields(
            {
                "status": "complete",
                "grade": "victory",
                "selected_faction_result": "victory",
                "coalition_result": "incomplete",
                "national_result": "victory",
                "momentum": 8,
                "reason": "campaign victory: required war aims and national contribution before the turn cap",
            }
        )
        self.assertEqual(
            list(harness.VICTORY_EVIDENCE_FIELDS),
            list(fields),
        )
        self.assertEqual("victory", fields["grade"])
        self.assertEqual("victory", fields["national_result"])
        self.assertEqual(8, fields["momentum"])
        self.assertFalse(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "negotiated_advantage",
                    "selected_faction_result": "active",
                }
            )
        )
        self.assertTrue(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "victory",
                    "selected_faction_result": "victory",
                }
            )
        )
        self.assertTrue(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "defeat",
                    "selected_faction_result": "defeat",
                }
            )
        )
        self.assertFalse(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "victory",
                    "selected_faction_result": "defeat",
                    "coalition_result": "victory",
                    "national_result": "victory",
                }
            )
        )
        self.assertFalse(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "decisive_victory",
                    "selected_faction_result": "defeat",
                }
            )
        )
        self.assertFalse(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "defeat",
                    "selected_faction_result": "victory",
                }
            )
        )
        self.assertFalse(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "defeat",
                    "selected_faction_result": "defeat",
                    "coalition_result": "victory",
                    "national_result": "incomplete",
                }
            )
        )
        self.assertFalse(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "defeat",
                    "selected_faction_result": "defeat",
                    "coalition_result": "incomplete",
                    "national_result": "victory",
                }
            )
        )
        self.assertTrue(
            harness._terminal_result_ok(
                {
                    "status": "complete",
                    "grade": "defeat",
                    "selected_faction_result": "defeat",
                    "coalition_result": "incomplete",
                    "national_result": "defeat",
                }
            )
        )
