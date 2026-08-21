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
            },
            payload["observed"],
        )
        self.assertEqual(3, harness.DEFAULT_CI_TURNS)
        self.assertEqual(12, harness.DEFAULT_LONG_TURNS)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(harness.TURNS_ENV, None)
            self.assertEqual(12, harness._default_turns())
        probe = harness._scenario_probe()
        self.assertTrue(probe["earth3_v1"])
        self.assertEqual("earth3_v1", probe["default_scenario_id"])
        self.assertFalse(probe["ww3_2028_core"]["in_registry"])

    def test_harness_fails_closed_when_persist_gate_drifts(self) -> None:
        _ensure_src_path()
        harness = _load_harness()
        with patch(
            "gates_of_codex.command_cycle_perf._should_persist_runtime_snapshot",
            return_value=True,
        ):
            with self.assertRaises(harness.PersistSeamError):
                harness.persist_gate_contract()

    def test_three_turn_s10_smoke_writes_report_without_goh(self) -> None:
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
        self.assertFalse(report["goh_invoked"])
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
        self.assertIn("ww3_2028_core", gap_ids)
        self.assertIn("frontend_victory_defeat", gap_ids)
        self.assertIn("auto_resolve_default_ui", gap_ids)
        self.assertTrue(report["victory_api"]["evaluate_campaign_outcome_exists"])
        self.assertFalse(report["victory_api"]["frontend_victory_op"])

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

    def test_optional_earth3_soak_runs_only_when_env_requests_it(self) -> None:
        if str(os.environ.get("GOC_AUTO_RESOLVE_SOAK", "")).strip() not in {
            "1",
            "true",
            "yes",
        }:
            self.skipTest(
                "set GOC_AUTO_RESOLVE_SOAK=1 to run the long earth3_v1 soak"
            )
        _ensure_src_path()
        harness = _load_harness()
        turns = harness._default_turns()
        if turns < 8:
            turns = 12
        with tempfile.TemporaryDirectory() as temporary:
            report = harness.run_soak(
                turns=turns,
                work_dir=Path(temporary),
                fixture="earth3_v1",
                use_daemon=True,
                write_full_snapshot=False,
            )
        self.assertTrue(report["ok"], report.get("fatal"))
        self.assertGreaterEqual(report["turns_completed"], 8)
        self.assertEqual("earth3_v1", report["scenario_id"])
        self.assertFalse(report["goh_invoked"])
