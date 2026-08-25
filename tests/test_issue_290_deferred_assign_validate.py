from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from gates_of_codex import frontend_commands, persistent_backend
from gates_of_codex.actor_economy import (
    available_actor_research,
    install_actor_content,
    purchase_actor_reinforcements,
    purchase_actor_research,
)
from gates_of_codex.force_migration import ensure_strategic_formations
from gates_of_codex.frontend import write_frontend_snapshot
from gates_of_codex.models import Faction
from gates_of_codex.scenario import load_bundled_scenario
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import assign_strategic_formation_actor
from tests.test_actor_economy import _resolved_payload, _single_battalion_force


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _write_commands(path: Path, commands: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"commands": commands}, indent=2) + "\n", encoding="utf-8")


def _prepared_assign_state():
    state = load_bundled_scenario("legacy_goe_europe")
    ensure_strategic_formations(state)
    install_actor_content(state, _resolved_payload(), selected_actor_id="fra")
    force = _single_battalion_force(state, Faction.NATO)
    assign_strategic_formation_actor(state, force.strategic_formation_id, "fra")
    research = available_actor_research(state, "fra")
    purchase_actor_research(state, "fra", research[0].key)
    purchase_actor_reinforcements(state, force.strategic_formation_id, "fixture_fra", 1)
    return state, force


class DeferredAssignValidationTests(unittest.TestCase):
    def test_authoritative_save_rejects_post_assign_invalid_state_and_keeps_bytes(self) -> None:
        state, force = _prepared_assign_state()
        battalion_id = force.battalion_ids[0]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            save_campaign(state, campaign)
            write_frontend_snapshot(state, snapshot, campaign_path=campaign)
            before = campaign.read_bytes()
            original = frontend_commands._apply_one

            def corrupt_after_assign(candidate, op, raw):
                result = original(candidate, op, raw)
                if result.ok and op == "assign":
                    candidate.turn_number = 0
                return result

            with patch.object(frontend_commands, "_apply_one", corrupt_after_assign):
                with self.assertRaises(ValueError) as caught:
                    frontend_commands.apply_frontend_commands(
                        campaign,
                        commands=[
                            {
                                "op": "assign",
                                "actor": "fra",
                                "formation": force.strategic_formation_id,
                                "battalion": battalion_id,
                                "unit": "fixture_fra",
                                "quantity": 1,
                            }
                        ],
                        snapshot_path=snapshot,
                    )
            self.assertIn("turn_number", str(caught.exception))
            self.assertEqual(before, campaign.read_bytes())
            reloaded = load_campaign(campaign)
            self.assertGreaterEqual(reloaded.turn_number, 1)
            pool = reloaded.map_metadata["actor_content_runtime"]["reinforcement_pool"]
            self.assertEqual(pool[0]["quantity"], 1)

    def test_daemon_discards_lease_when_save_validate_fails_after_assign(self) -> None:
        state, force = _prepared_assign_state()
        battalion_id = force.battalion_ids[0]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            commands = root / "frontend_commands.json"
            save_campaign(state, campaign)
            write_frontend_snapshot(state, snapshot, campaign_path=campaign)
            before = campaign.read_bytes()
            hook = root / "sitecustomize.py"
            hook.write_text(
                "import os\n"
                "from gates_of_codex import frontend_commands\n"
                "\n"
                "_original = frontend_commands._apply_one\n"
                "\n"
                "def _corrupt(state, op, raw):\n"
                "    result = _original(state, op, raw)\n"
                "    if result.ok and op == 'assign':\n"
                "        state.turn_number = 0\n"
                "    return result\n"
                "\n"
                "if os.environ.get('GOC_TEST_CORRUPT_AFTER_ASSIGN') == '1':\n"
                "    frontend_commands._apply_one = _corrupt\n",
                encoding="utf-8",
            )
            previous_pythonpath = os.environ.get("PYTHONPATH", "")
            os.environ["PYTHONPATH"] = str(root) + os.pathsep + str(SRC) + (
                os.pathsep + previous_pythonpath if previous_pythonpath else ""
            )
            os.environ["GOC_TEST_CORRUPT_AFTER_ASSIGN"] = "1"
            daemon_pid = None
            try:
                started = persistent_backend.ensure_backend_session(campaign, snapshot)
                self.assertTrue(started)
                session = persistent_backend._read_session(campaign)
                self.assertIsNotNone(session)
                assert session is not None
                daemon_pid = int(session["pid"])
                _write_commands(
                    commands,
                    [
                        {
                            "op": "assign",
                            "actor": "fra",
                            "formation": force.strategic_formation_id,
                            "battalion": battalion_id,
                            "unit": "fixture_fra",
                            "quantity": 1,
                        }
                    ],
                )
                forwarded = persistent_backend.try_forward_apply_frontend(
                    [
                        "apply-frontend",
                        str(campaign),
                        "--snapshot",
                        str(snapshot),
                        "--commands",
                        str(commands),
                    ]
                )
                if forwarded is not None:
                    _exit_code, stdout = forwarded
                    if stdout.strip():
                        payload = json.loads(stdout)
                        self.assertFalse(bool(payload.get("ok", True)))
                self.assertEqual(before, campaign.read_bytes())
                os.environ.pop("GOC_TEST_CORRUPT_AFTER_ASSIGN", None)
                follow_commands = [{"op": "actor_force_panel", "faction": "nato", "formation": force.strategic_formation_id}]
                _write_commands(commands, follow_commands)
                follow = persistent_backend.try_forward_apply_frontend(
                    [
                        "apply-frontend",
                        str(campaign),
                        "--snapshot",
                        str(snapshot),
                        "--commands",
                        str(commands),
                    ]
                )
                if follow is None:
                    from gates_of_codex.command_cycle_perf import install_command_cycle_perf_path

                    install_command_cycle_perf_path()
                    report = frontend_commands.apply_frontend_commands(
                        campaign,
                        commands=follow_commands,
                        snapshot_path=snapshot,
                    )
                    self.assertTrue(report.get("ok"), report)
                    reload_reason = str((report.get("timings") or {}).get("reload_reason") or "")
                    self.assertNotEqual("cache_hit", reload_reason)
                else:
                    _exit_code, stdout = follow
                    payload = json.loads(stdout)
                    self.assertTrue(payload.get("ok"), payload)
                    timings = payload.get("timings") or {}
                    self.assertNotEqual("cache_hit", str(timings.get("reload_reason") or ""))
                reloaded = load_campaign(campaign)
                self.assertGreaterEqual(reloaded.turn_number, 1)
                pool = reloaded.map_metadata["actor_content_runtime"]["reinforcement_pool"]
                self.assertEqual(pool[0]["quantity"], 1)
            finally:
                if daemon_pid:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/PID", str(daemon_pid), "/F", "/T"],
                            capture_output=True,
                            check=False,
                        )
                    else:
                        try:
                            os.kill(daemon_pid, signal.SIGTERM)
                        except OSError:
                            pass
                    deadline = time.monotonic() + 2.0
                    while time.monotonic() < deadline:
                        time.sleep(0.05)
                persistent_backend._drop_session_descriptor(campaign)
                os.environ.pop("GOC_TEST_CORRUPT_AFTER_ASSIGN", None)
                if previous_pythonpath:
                    os.environ["PYTHONPATH"] = previous_pythonpath
                else:
                    os.environ.pop("PYTHONPATH", None)


if __name__ == "__main__":
    unittest.main()
