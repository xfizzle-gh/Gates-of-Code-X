from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, persistent_backend
from gates_of_codex.frontend import write_frontend_snapshot
from gates_of_codex.state_io import save_campaign
from tests.test_issue_266_persistent_backend_warm_lease import (
    _ensure_worktree_import_path,
    _parse_forward,
    _write_commands,
)
from tests.test_s10_frontend_presentation_contract import _state


ROOT = Path(__file__).resolve().parents[1]
LEASE_KEYS = (
    "lease_path",
    "lease_hit",
    "session_pid",
    "source_commit",
    "source_commit_match",
    "cached_state_present",
    "campaign_fingerprint_match",
    "reload_reason",
)


class LeasePathDiagnosticsTests(unittest.TestCase):
    def test_timing_contract_includes_lease_diagnostics(self) -> None:
        keys = command_cycle_perf.timing_keys()
        for key in LEASE_KEYS:
            self.assertIn(key, keys)

    def test_one_shot_apply_reports_not_leased(self) -> None:
        persistent_backend.reset_lease_diagnostics()
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            snapshot = Path(temporary) / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text("{}\n", encoding="utf-8")

            def fake_apply(campaign_path, *, commands, commands_path, snapshot_path):
                return {
                    "ok": True,
                    "campaign_path": str(campaign_path),
                    "snapshot_path": str(snapshot_path),
                    "commands_applied": 1,
                    "results": [{"op": "refresh", "ok": True, "detail": "refreshed", "data": {}}],
                }

            with patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "refresh"}],
                    snapshot_path=snapshot,
                )
        timings = report["timings"]
        self.assertEqual("one_shot_fallback", timings["lease_path"])
        self.assertFalse(timings["lease_hit"])
        self.assertEqual(0, timings["session_pid"])
        self.assertEqual("not_leased", timings["reload_reason"])
        self.assertFalse(timings["cached_state_present"])
        self.assertFalse(timings["campaign_fingerprint_match"])

    def test_forward_without_session_records_no_session(self) -> None:
        persistent_backend.reset_lease_diagnostics()
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            campaign.write_text("{}\n", encoding="utf-8")
            forwarded = persistent_backend.try_forward_apply_frontend(
                [
                    "apply-frontend",
                    str(campaign),
                    "--snapshot",
                    str(Path(temporary) / "campaign_snapshot.json"),
                    "--commands",
                    str(Path(temporary) / "frontend_commands.json"),
                ]
            )
        self.assertIsNone(forwarded)
        diagnostics = persistent_backend.lease_diagnostics_for_timings()
        self.assertEqual("one_shot_fallback", diagnostics["lease_path"])
        self.assertEqual("no_session", diagnostics["reload_reason"])
        self.assertFalse(diagnostics["lease_hit"])
        self.assertEqual(0, diagnostics["session_pid"])

    def test_godot_perf_line_prints_lease_fields(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn("lease_path", source)
        self.assertIn("reload_reason", source)
        self.assertIn("lease_hit", source)
        self.assertIn("session_pid", source)
        self.assertIn("source_commit_match", source)
        self.assertIn("cached_state_present", source)
        self.assertIn("campaign_fingerprint_match", source)
        self.assertIn("commit_match=%s", source)
        self.assertIn("cached=%s", source)
        self.assertIn("fingerprint=%s", source)


class DaemonLeaseDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_worktree_import_path()
        self._temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._temp.name)
        self.campaign = self.root / "campaign.json"
        self.snapshot = self.root / "campaign_snapshot.json"
        self.commands = self.root / "frontend_commands.json"
        self._daemon_pid: int | None = None

    def tearDown(self) -> None:
        pid = self._daemon_pid
        if pid:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    capture_output=True,
                    check=False,
                )
            else:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
        self._temp.cleanup()

    def _apply(self, commands: list[dict]) -> dict:
        _write_commands(self.commands, commands)
        return _parse_forward(
            persistent_backend.try_forward_apply_frontend(
                [
                    "apply-frontend",
                    str(self.campaign),
                    "--snapshot",
                    str(self.snapshot),
                    "--commands",
                    str(self.commands),
                ]
            )
        )

    def test_warm_daemon_followup_reports_cache_hit(self) -> None:
        state = _state(self.root)
        save_campaign(state, self.campaign)
        write_frontend_snapshot(state, self.snapshot, campaign_path=self.campaign)
        started = persistent_backend.ensure_backend_session(
            self.campaign, self.snapshot
        )
        self.assertTrue(started)
        session = persistent_backend._read_session(self.campaign)
        self.assertIsNotNone(session)
        assert session is not None
        self._daemon_pid = int(session["pid"])
        first = self._apply([{"op": "refresh"}])
        self.assertTrue(first.get("ok"))
        follow = self._apply([{"op": "refresh"}])
        timings = follow["timings"]
        self.assertEqual("persistent_forward", timings["lease_path"])
        self.assertTrue(timings["lease_hit"])
        self.assertEqual(self._daemon_pid, timings["session_pid"])
        self.assertTrue(timings["source_commit_match"])
        self.assertTrue(timings["cached_state_present"])
        self.assertTrue(timings["campaign_fingerprint_match"])
        self.assertEqual("cache_hit", timings["reload_reason"])
        self.assertTrue(str(timings["source_commit"]))
