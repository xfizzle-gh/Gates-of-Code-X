from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, frontend, frontend_commands, persistent_backend
from gates_of_codex.command_cycle_perf import (
    _RUNTIME_PATCH_OPS,
    _should_persist_runtime_snapshot,
    _runtime_patch_only,
    _verify_only,
)
from gates_of_codex.frontend import write_frontend_snapshot
from gates_of_codex.frontend_commands import READ_ONLY_OPS, apply_frontend_commands
from gates_of_codex.frontend_runtime_patch import RUNTIME_PATCH_SCHEMA
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_issue_149_persistent_backend_repair import (
    _ensure_worktree_import_path,
    _parse_forward,
    _pid_alive,
    _write_commands,
)
from tests.test_s10_frontend_presentation_contract import _state


ROOT = Path(__file__).resolve().parents[1]
WARM_SPEND_OPS = ("research", "recruit", "assign", "repair", "upgrade_site")
COLD_OPS = (
    "handoff",
    "import_battle",
    "restore_backup",
    "reset_test_campaign",
    "end_turn",
    "run_ai",
    "construct",
)


def _fake_apply_for(op: str):
    def fake_apply(campaign_path, *, commands, commands_path, snapshot_path):
        frontend_commands.save_campaign(object(), campaign_path)
        frontend.write_frontend_snapshot(
            object(), snapshot_path, campaign_path=campaign_path
        )
        return {
            "ok": True,
            "campaign_path": str(campaign_path),
            "snapshot_path": str(snapshot_path),
            "commands_applied": 1,
            "results": [
                {
                    "op": op,
                    "ok": True,
                    "detail": f"{op} applied",
                    "data": {"op": op},
                }
            ],
        }

    return fake_apply


class WarmForceSpendAllowlistTests(unittest.TestCase):
    def test_daemon_keeps_force_spend_and_panel_on_the_lease(self) -> None:
        for op in ("actor_force_panel", *WARM_SPEND_OPS):
            self.assertIn(op, persistent_backend.SUPPORTED_OPS)
        for op in COLD_OPS:
            self.assertNotIn(op, persistent_backend.SUPPORTED_OPS)

    def test_spend_ops_are_runtime_patches_and_panel_is_read_only(self) -> None:
        self.assertTrue(_verify_only([{"op": "actor_force_panel"}]))
        self.assertFalse(_runtime_patch_only([{"op": "actor_force_panel"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "actor_force_panel"}]))
        self.assertIn("actor_force_panel", READ_ONLY_OPS)
        for op in WARM_SPEND_OPS:
            self.assertIn(op, _RUNTIME_PATCH_OPS)
            self.assertTrue(_runtime_patch_only([{"op": op}]))
            self.assertFalse(_verify_only([{"op": op}]))
            self.assertFalse(_should_persist_runtime_snapshot([{"op": op}]))

    def test_apply_skips_save_and_snapshot_for_every_read_only_op(self) -> None:
        source = (
            ROOT / "src/gates_of_codex/frontend_commands.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "all(item.op in READ_ONLY_OPS for item in results)",
            source,
        )
        self.assertNotIn('all(item.op == "query_supply" for item in results)', source)


class WarmForceSpendMeasuredPublicationTests(unittest.TestCase):
    def test_spend_ops_compact_save_and_emit_runtime_patch_without_snapshot_rewrite(
        self,
    ) -> None:
        for op in WARM_SPEND_OPS:
            with self.subTest(op=op), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                campaign = root / "campaign.json"
                snapshot = root / "campaign_snapshot.json"
                campaign.write_text("{}\n", encoding="utf-8")
                snapshot.write_text('{"static":"unchanged"}\n', encoding="utf-8")
                calls = {"save": 0, "full_snapshot": 0, "runtime_patch": 0}

                def fake_save(
                    _state,
                    path,
                    *,
                    observation_context=None,
                    subphase_seconds=None,
                ):
                    calls["save"] += 1
                    Path(path).write_text('{"saved":true}\n', encoding="utf-8")
                    return Path(path)

                def fake_full_snapshot(_state, path, *, campaign_path=None, environ=None):
                    calls["full_snapshot"] += 1
                    Path(path).write_text('{"rewritten":true}\n', encoding="utf-8")
                    return Path(path)

                def fake_runtime_patch(
                    _state, *, campaign_path=None, snapshot_path=None, environ=None
                ):
                    calls["runtime_patch"] += 1
                    return {
                        "schema": RUNTIME_PATCH_SCHEMA,
                        "schema_version": 1,
                        "merge": {"campaign": {"turn_number": 1}},
                        "replace": {"acting_actor": {"resources": 1}},
                    }

                with (
                    patch.object(
                        command_cycle_perf, "_ORIGINAL_APPLY", _fake_apply_for(op)
                    ),
                    patch.object(command_cycle_perf, "_compact_save_campaign", fake_save),
                    patch.object(frontend, "write_frontend_snapshot", fake_full_snapshot),
                    patch(
                        "gates_of_codex.frontend_runtime_patch.build_frontend_runtime_patch",
                        side_effect=fake_runtime_patch,
                    ),
                ):
                    report = command_cycle_perf.measured_apply_frontend_commands(
                        campaign,
                        commands=[{"op": op}],
                        snapshot_path=snapshot,
                    )

                self.assertEqual(1, calls["save"], op)
                self.assertEqual(0, calls["full_snapshot"], op)
                self.assertEqual(1, calls["runtime_patch"], op)
                self.assertEqual(
                    '{"static":"unchanged"}\n', snapshot.read_text(encoding="utf-8")
                )
                self.assertEqual(RUNTIME_PATCH_SCHEMA, report["frontend_patch"]["schema"])
                timings = report["timings"]
                self.assertTrue(timings["runtime_patch_fast_path"], op)
                self.assertFalse(timings["read_only_fast_path"], op)
                self.assertFalse(timings["snapshot_fast_path"], op)
                self.assertTrue(timings["compact_save_path"], op)
                self.assertGreaterEqual(timings["total_ms"], 0.0)
                self.assertIn("load_ms", timings)
                self.assertIn("mutate_ms", timings)
                self.assertIn("save_ms", timings)
                self.assertIn("snapshot_ms", timings)

    def test_actor_force_panel_is_read_only_and_does_not_touch_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            campaign.write_text("{}\n", encoding="utf-8")
            snapshot.write_text('{"existing":true}\n', encoding="utf-8")

            with (
                patch.object(
                    command_cycle_perf,
                    "_ORIGINAL_APPLY",
                    _fake_apply_for("actor_force_panel"),
                ),
                patch.object(
                    frontend_commands,
                    "save_campaign",
                    side_effect=AssertionError("actor_force_panel must not save campaign"),
                ),
                patch.object(
                    frontend,
                    "write_frontend_snapshot",
                    side_effect=AssertionError(
                        "actor_force_panel must not publish snapshot"
                    ),
                ),
                patch.object(
                    command_cycle_perf,
                    "_compact_save_campaign",
                    side_effect=AssertionError(
                        "actor_force_panel must not compact-save campaign"
                    ),
                ),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "actor_force_panel", "formation": "sf-n"}],
                    snapshot_path=snapshot,
                )

            timings = report["timings"]
            self.assertTrue(timings["read_only_fast_path"])
            self.assertFalse(timings["runtime_patch_fast_path"])
            self.assertFalse(timings["compact_save_path"])
            self.assertEqual(0.0, timings["save_ms"])
            self.assertEqual(0.0, timings["snapshot_ms"])
            self.assertGreaterEqual(timings["total_ms"], 0.0)
            self.assertEqual(b"{}\n", campaign.read_bytes())
            self.assertEqual(b'{"existing":true}\n', snapshot.read_bytes())
            self.assertNotIn("frontend_patch", report)


class WarmForceSpendUnmeasuredApplyTests(unittest.TestCase):
    def test_unmeasured_actor_force_panel_does_not_rewrite_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            root = Path(temporary)
            campaign = root / "campaign.json"
            snapshot = root / "campaign_snapshot.json"
            state = _state(root)
            save_campaign(state, campaign)
            write_frontend_snapshot(state, snapshot, campaign_path=campaign)
            before_campaign = campaign.read_bytes()
            before_snapshot = snapshot.read_bytes()
            report = apply_frontend_commands(
                campaign,
                commands=[
                    {
                        "op": "actor_force_panel",
                        "faction": "nato",
                        "formation": "sf-n",
                        "battalion": "bn-n",
                    }
                ],
                snapshot_path=snapshot,
            )
            self.assertTrue(report["ok"], report)
            self.assertEqual("actor_force_panel", report["results"][0]["op"])
            self.assertTrue(report["results"][0]["ok"])
            self.assertEqual("nato", report["results"][0]["data"]["actor_id"])
            self.assertEqual(before_campaign, campaign.read_bytes())
            self.assertEqual(before_snapshot, snapshot.read_bytes())


class WarmForceSpendGodotTests(unittest.TestCase):
    def test_measured_godot_routes_panel_and_spend_without_full_snapshot_parse(
        self,
    ) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(
            encoding="utf-8"
        )
        self.assertIn('"research"', source)
        self.assertIn('"recruit"', source)
        self.assertIn('"assign"', source)
        self.assertIn('"repair"', source)
        self.assertIn('"upgrade_site"', source)
        finished = source.split("func _on_command_finished(", 1)[1]
        self.assertIn('op == "actor_force_panel"', finished)
        self.assertIn("_consume_fast_command_result(", finished)
        consume = source.split("func _consume_runtime_patch_result(", 1)[1].split(
            "func _on_command_finished(", 1
        )[0]
        self.assertNotIn("_try_build_snapshot_state", consume)
        self.assertIn("request_force_panel()", consume)
        self.assertIn('"upgrade_site"', consume)
        fast = source.split("func _consume_fast_command_result(", 1)[1].split(
            "func _consume_runtime_patch_result(", 1
        )[0]
        self.assertIn('_capture_force_panel(backend_payload)', fast)
        self.assertIn("_append_backend_timing(backend_payload)", consume)
        self.assertIn("_append_backend_timing(backend_payload)", fast)


class WarmForceSpendDaemonTests(unittest.TestCase):
    def setUp(self) -> None:
        _ensure_worktree_import_path()
        self._temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._temp.name)
        self.campaign = self.root / "campaign.json"
        self.snapshot = self.root / "campaign_snapshot.json"
        self.commands = self.root / "frontend_commands.json"
        self._daemon_pid: int | None = None

    def tearDown(self) -> None:
        self._stop_daemon()
        self._temp.cleanup()

    def _stop_daemon(self) -> None:
        pid = self._daemon_pid
        session_path = persistent_backend._session_path(self.campaign)
        if pid is None and session_path.is_file():
            try:
                pid = int(json.loads(session_path.read_text(encoding="utf-8")).get("pid") or 0)
            except (OSError, ValueError):
                pid = None
        if pid:
            if os.name == "nt":
                subprocess.run(
                    ["tasklist", "/PID", str(pid), "/F", "/T"],
                    capture_output=True,
                    check=False,
                )
            else:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if not _pid_alive(pid):
                    break
                time.sleep(0.05)
        self._daemon_pid = None

    def _write_s10(self) -> None:
        state = _state(self.root)
        state.battalions["bn-n"].condition = 65
        save_campaign(state, self.campaign)
        write_frontend_snapshot(state, self.snapshot, campaign_path=self.campaign)
        _write_commands(self.commands, [])

    def _start_daemon(self) -> None:
        started = persistent_backend.ensure_backend_session(self.campaign, self.snapshot)
        self.assertTrue(started, "session-backend failed to become healthy")
        session = persistent_backend._read_session(self.campaign)
        self.assertIsNotNone(session)
        assert session is not None
        self._daemon_pid = int(session["pid"])

    def _apply(self, commands: list[dict]) -> dict:
        _write_commands(self.commands, commands)
        forwarded = persistent_backend.try_forward_apply_frontend(
            [
                "apply-frontend",
                str(self.campaign),
                "--snapshot",
                str(self.snapshot),
                "--commands",
                str(self.commands),
            ]
        )
        return _parse_forward(forwarded)

    def test_panel_and_repair_stay_on_the_lease_without_snapshot_rewrite(self) -> None:
        self._write_s10()
        before_snapshot = self.snapshot.read_bytes()
        self._start_daemon()

        panel = self._apply(
            [
                {
                    "op": "actor_force_panel",
                    "faction": "nato",
                    "formation": "sf-n",
                    "battalion": "bn-n",
                }
            ]
        )
        self.assertTrue(panel.get("ok"), panel)
        panel_timings = panel.get("timings") or {}
        self.assertTrue(panel_timings.get("read_only_fast_path"), panel_timings)
        self.assertFalse(panel_timings.get("runtime_patch_fast_path"), panel_timings)
        self.assertEqual(0.0, panel_timings.get("save_ms"))
        self.assertEqual(0.0, panel_timings.get("snapshot_ms"))
        self.assertGreaterEqual(panel_timings.get("total_ms"), 0.0)
        self.assertEqual("nato", (panel.get("results") or [])[0]["data"]["actor_id"])
        self.assertEqual(before_snapshot, self.snapshot.read_bytes())

        repair = self._apply(
            [{"op": "repair", "formation": "toe-nato", "points": 15}]
        )
        self.assertTrue(repair.get("ok"), repair)
        repair_timings = repair.get("timings") or {}
        self.assertTrue(repair_timings.get("runtime_patch_fast_path"), repair_timings)
        self.assertFalse(repair_timings.get("read_only_fast_path"), repair_timings)
        self.assertEqual(
            RUNTIME_PATCH_SCHEMA,
            (repair.get("frontend_patch") or {}).get("schema"),
        )
        self.assertGreater(repair_timings.get("save_ms"), 0.0)
        self.assertGreaterEqual(repair_timings.get("total_ms"), repair_timings.get("save_ms"))
        self.assertEqual(before_snapshot, self.snapshot.read_bytes())
        self.assertEqual(80, load_campaign(self.campaign).battalions["bn-n"].condition)

        again = self._apply(
            [
                {
                    "op": "actor_force_panel",
                    "faction": "nato",
                    "formation": "sf-n",
                    "battalion": "bn-n",
                }
            ]
        )
        self.assertTrue(again.get("ok"), again)
        self.assertTrue((again.get("timings") or {}).get("read_only_fast_path"))
        self.assertEqual(before_snapshot, self.snapshot.read_bytes())
        self.assertEqual("nato", (again.get("results") or [])[0]["data"]["actor_id"])

        # Backend input→response latency is measured here. Native Godot
        # input→visible HUD latency remains an owner-machine measurement via
        # the existing GOC_PERF log line.
        print(
            "WARM_FORCE_SPEND_LATENCY "
            f"panel_total_ms={panel_timings.get('total_ms')} "
            f"repair_total_ms={repair_timings.get('total_ms')} "
            f"repair_save_ms={repair_timings.get('save_ms')} "
            f"repair_snapshot_ms={repair_timings.get('snapshot_ms')}"
        )

    def test_construct_still_falls_off_the_lease(self) -> None:
        self._write_s10()
        self._start_daemon()
        self.assertTrue(
            self._apply(
                [
                    {
                        "op": "actor_force_panel",
                        "faction": "nato",
                        "formation": "sf-n",
                    }
                ]
            ).get("ok")
        )
        _write_commands(self.commands, [{"op": "construct", "province": "a"}])
        forwarded = persistent_backend.try_forward_apply_frontend(
            [
                "apply-frontend",
                str(self.campaign),
                "--snapshot",
                str(self.snapshot),
                "--commands",
                str(self.commands),
            ]
        )
        self.assertIsNone(forwarded)
        recovered = self._apply(
            [
                {
                    "op": "actor_force_panel",
                    "faction": "nato",
                    "formation": "sf-n",
                }
            ]
        )
        self.assertTrue(recovered.get("ok"), recovered)


if __name__ == "__main__":
    unittest.main()
