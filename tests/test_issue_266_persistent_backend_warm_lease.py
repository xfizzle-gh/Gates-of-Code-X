from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from gates_of_codex import persistent_backend
from gates_of_codex.frontend import write_frontend_snapshot
from gates_of_codex.operational_schema import stable_edge_id, stable_node_id
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_s10_frontend_presentation_contract import (
    _create_prepared_contact,
    _state,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
WARM_LOAD_MS = 25.0


def _ensure_worktree_import_path() -> None:
    src = str(SRC)
    current = os.environ.get("PYTHONPATH", "")
    parts = [item for item in current.split(os.pathsep) if item]
    if src not in parts:
        os.environ["PYTHONPATH"] = src + (os.pathsep + current if current else "")
    if src not in sys.path:
        sys.path.insert(0, src)


def _write_commands(path: Path, commands: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"commands": commands}, indent=2) + "\n", encoding="utf-8")


def _s10_move_batch() -> list[dict[str, Any]]:
    node_a, node_b = stable_node_id("a"), stable_node_id("b")
    return [
        {
            "op": "issue_move_order",
            "formation": "sf-n",
            "path_node_ids": [node_a, node_b],
            "path_edge_ids": [stable_edge_id("corridor", node_a, node_b)],
        },
        {"op": "commit_move_orders", "faction": "nato", "locked_stance": "operational"},
    ]


def _parse_forward(result: tuple[int, str] | None) -> dict[str, Any]:
    if result is None:
        raise AssertionError("daemon did not handle apply")
    exit_code, stdout = result
    payload = json.loads(stdout)
    payload["_exit_code"] = exit_code
    return payload


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class PersistentBackendWarmLeaseTests(unittest.TestCase):
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
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
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

    def _write_s10(self, *, prepared_contact: bool = False) -> None:
        state = _state(self.root)
        if prepared_contact:
            _create_prepared_contact(state)
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

    def _apply(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
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

    def test_live_issue_commit_batch_keeps_lease_warm(self) -> None:
        self._write_s10()
        before = persistent_backend._fingerprint(self.campaign)
        self._start_daemon()
        moved = self._apply(_s10_move_batch())
        self.assertTrue(moved.get("ok"))
        self.assertEqual(
            [str(row.get("op")) for row in moved.get("results") or []],
            ["issue_move_order", "commit_move_orders"],
        )
        self.assertTrue(all(bool(row.get("ok")) for row in moved.get("results") or []))
        after = persistent_backend._fingerprint(self.campaign)
        self.assertNotEqual(before[2], after[2])
        state = load_campaign(self.campaign)
        order = state.strategic_formations["sf-n"].move_order
        self.assertIsNotNone(order)
        assert order is not None
        self.assertEqual(order.status, "committed")
        follow = self._apply([{"op": "end_player_round"}])
        self.assertTrue(follow.get("ok"))
        self.assertEqual(
            [str(row.get("op")) for row in follow.get("results") or []],
            ["end_player_round"],
        )
        load_ms = float((follow.get("timings") or {}).get("load_ms", 999.0))
        self.assertLess(load_ms, WARM_LOAD_MS, load_ms)

    def test_warm_refresh_does_not_invalidate_lease(self) -> None:
        self._write_s10()
        self._start_daemon()
        first = self._apply([{"op": "refresh"}])
        self.assertTrue(first.get("ok"))
        second = self._apply([{"op": "refresh"}])
        self.assertTrue(second.get("ok"))
        follow = self._apply([{"op": "end_player_round"}])
        self.assertTrue(follow.get("ok"))
        self.assertLess(float((follow.get("timings") or {}).get("load_ms", 999.0)), WARM_LOAD_MS)

    def test_prepared_auto_resolve_stays_on_daemon(self) -> None:
        self._write_s10(prepared_contact=True)
        self.assertIsNotNone(load_campaign(self.campaign).pending_battle)
        self._start_daemon()
        resolved = self._apply([{"op": "auto_resolve"}])
        self.assertTrue(resolved.get("ok"))
        self.assertEqual(
            [str(row.get("op")) for row in resolved.get("results") or []],
            ["auto_resolve"],
        )
        self.assertIsNone(load_campaign(self.campaign).pending_battle)
        follow = self._apply([{"op": "refresh"}])
        self.assertTrue(follow.get("ok"))
        self.assertLess(float((follow.get("timings") or {}).get("load_ms", 999.0)), WARM_LOAD_MS)

    def test_failed_mutation_drops_lease_and_reloads_disk(self) -> None:
        self._write_s10()
        self._start_daemon()
        failed = self._apply(
            [
                *_s10_move_batch()[:1],
                {
                    "op": "issue_move_order",
                    "formation": "missing-force",
                    "path_node_ids": [stable_node_id("a"), stable_node_id("b")],
                    "path_edge_ids": [
                        stable_edge_id("corridor", stable_node_id("a"), stable_node_id("b"))
                    ],
                },
            ]
        )
        self.assertFalse(failed.get("ok"))
        state = load_campaign(self.campaign)
        self.assertIsNone(state.strategic_formations["sf-n"].move_order)
        follow = self._apply([{"op": "refresh"}])
        self.assertTrue(follow.get("ok"))
        state = load_campaign(self.campaign)
        self.assertIsNone(state.strategic_formations["sf-n"].move_order)

    def test_same_size_external_rewrite_is_caught_before_reuse(self) -> None:
        self._write_s10()
        self._start_daemon()
        self.assertTrue(self._apply([{"op": "refresh"}]).get("ok"))
        raw = self.campaign.read_bytes()
        old = b"S10 presentation contract"
        new = b"S10 presentation CONTRAKT"
        self.assertEqual(len(old), len(new))
        self.assertIn(old, raw)
        self.campaign.write_bytes(raw.replace(old, new, 1))
        self.assertEqual(len(raw), self.campaign.stat().st_size)
        follow = self._apply([{"op": "refresh"}])
        self.assertTrue(follow.get("ok"))
        self.assertEqual(load_campaign(self.campaign).campaign_name, "S10 presentation CONTRAKT")

    def test_unsupported_op_invalidates_and_does_not_handle(self) -> None:
        self._write_s10()
        self._start_daemon()
        self.assertTrue(self._apply([{"op": "refresh"}]).get("ok"))
        _write_commands(self.commands, [{"op": "handoff"}])
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
        recovered = self._apply([{"op": "refresh"}])
        self.assertTrue(recovered.get("ok"))

    def test_source_commit_mismatch_fails_closed_before_dispatch(self) -> None:
        self._write_s10()
        self._start_daemon()
        session_path = persistent_backend._session_path(self.campaign)
        payload = json.loads(session_path.read_text(encoding="utf-8"))
        payload["source_commit"] = "a" * 40
        session_path.write_text(json.dumps(payload), encoding="utf-8")
        _write_commands(self.commands, [{"op": "refresh"}])
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
        self.assertFalse(session_path.exists())


if __name__ == "__main__":
    unittest.main()
