from __future__ import annotations

import ast
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from gates_of_codex import persistent_backend
from gates_of_codex.command_cycle_perf import (
    _LIVE_MOVE_BATCH,
    _RUNTIME_PATCH_OPS,
    _SNAPSHOT_PATCH_OPS,
    _should_persist_runtime_snapshot,
    _snapshot_patch_only,
    _runtime_patch_only,
)
from gates_of_codex.frontend import write_frontend_snapshot
from gates_of_codex.frontend_runtime_patch import (
    RUNTIME_PATCH_SCHEMA,
    RUNTIME_PATCH_SCHEMA_VERSION,
)
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_s10_frontend_presentation_contract import _state


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# #149 force-loop economy ops. Recruit/research/assign are CLI/Python-only on
# main b5320ce; draft #276 adds their frontend commands. Do not allowlist them
# here until they exist as frontend ops on the stacked base.
ISSUE_149_FORCE_LOOP_OPS = frozenset({"repair", "recruit", "research", "assign"})


def _ensure_worktree_import_path() -> None:
    src = str(SRC)
    current = os.environ.get("PYTHONPATH", "")
    parts = [item for item in current.split(os.pathsep) if item]
    if src not in parts:
        os.environ["PYTHONPATH"] = src + (os.pathsep + current if current else "")
    if src not in sys.path:
        sys.path.insert(0, src)


def _literal_string_set(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Set):
        values = node.elts
    elif isinstance(node, (ast.List, ast.Tuple)):
        values = node.elts
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set"}
        and node.args
    ):
        return _literal_string_set(node.args[0])
    else:
        raise AssertionError(f"unsupported AST node for string set: {type(node)!r}")
    result: set[str] = set()
    for item in values:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            raise AssertionError("expected string literals in allowlist")
        result.add(item.value)
    return result


def _frontend_command_handlers() -> set[str]:
    source = (ROOT / "src/gates_of_codex/frontend_commands.py").read_text(
        encoding="utf-8"
    )
    return set(re.findall(r'if op == "([a-z_]+)"', source))


def _frontend_control_supported_ops() -> set[str]:
    source = (ROOT / "src/gates_of_codex/frontend.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "_control_block":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Dict):
                continue
            for key, value in zip(child.keys, child.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "supported_ops"
                    and isinstance(value, ast.List)
                ):
                    return _literal_string_set(value)
    raise AssertionError("frontend _control_block supported_ops not found")


def _command_cycle_named_set(name: str) -> set[str]:
    source = (ROOT / "src/gates_of_codex/command_cycle_perf.py").read_text(
        encoding="utf-8"
    )
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return _literal_string_set(node.value)
    raise AssertionError(f"{name} not found in command_cycle_perf.py")


def _write_commands(path: Path, commands: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"commands": commands}, indent=2) + "\n", encoding="utf-8")


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


class Issue149FrontendForceLoopDiscoveryTests(unittest.TestCase):
    def test_only_repair_is_a_frontend_force_loop_op_on_this_base(self) -> None:
        handlers = _frontend_command_handlers()
        control_ops = _frontend_control_supported_ops()
        frontend_force_ops = ISSUE_149_FORCE_LOOP_OPS & handlers & control_ops
        self.assertEqual({"repair"}, frontend_force_ops)
        for op in ("recruit", "research", "assign"):
            self.assertNotIn(op, handlers)
            self.assertNotIn(op, control_ops)


class Issue149PersistentBackendRepairAllowlistTests(unittest.TestCase):
    def test_daemon_accepts_repair_and_leaves_non_frontend_force_ops_closed(self) -> None:
        self.assertIn("repair", persistent_backend.SUPPORTED_OPS)
        for op in ("recruit", "research", "assign"):
            self.assertNotIn(op, persistent_backend.SUPPORTED_OPS)
        for op in (
            "handoff",
            "import_battle",
            "restore_backup",
            "reset_test_campaign",
            "end_turn",
            "run_ai",
            "construct",
        ):
            self.assertNotIn(op, persistent_backend.SUPPORTED_OPS)

    def test_repair_stays_full_refresh_and_does_not_persist_a_runtime_snapshot(self) -> None:
        repair = [{"op": "repair"}]
        self.assertFalse(_should_persist_runtime_snapshot(repair))
        self.assertFalse(_runtime_patch_only(repair))
        self.assertFalse(_snapshot_patch_only(repair))
        self.assertNotIn("repair", _RUNTIME_PATCH_OPS)
        self.assertNotIn("repair", _SNAPSHOT_PATCH_OPS)
        self.assertNotIn("refresh", _RUNTIME_PATCH_OPS)
        self.assertNotIn("refresh", _SNAPSHOT_PATCH_OPS)
        self.assertEqual(("issue_move_order", "commit_move_orders"), _LIVE_MOVE_BATCH)
        self.assertTrue(
            _should_persist_runtime_snapshot(
                [{"op": "issue_move_order"}, {"op": "commit_move_orders"}]
            )
        )
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "end_player_round"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertEqual("gates-of-codex.frontend-runtime-patch", RUNTIME_PATCH_SCHEMA)
        self.assertEqual(1, RUNTIME_PATCH_SCHEMA_VERSION)
        self.assertEqual({"end_player_round", "auto_resolve"}, _command_cycle_named_set("_RUNTIME_PATCH_OPS"))
        self.assertEqual(
            {"issue_move_order", "cancel_move_order"},
            _command_cycle_named_set("_SNAPSHOT_PATCH_OPS"),
        )


class Issue149PersistentBackendRepairDaemonTests(unittest.TestCase):
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

    def _write_damaged_s10(self) -> None:
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

    def test_repair_is_handled_on_warm_daemon_as_full_refresh_without_runtime_persist(
        self,
    ) -> None:
        self._write_damaged_s10()
        before_snapshot = self.snapshot.read_bytes()
        self.assertEqual(
            "gates-of-codex.frontend",
            json.loads(before_snapshot.decode("utf-8"))["schema"],
        )
        self._start_daemon()
        report = self._apply(
            [{"op": "repair", "formation": "toe-nato", "points": 15}]
        )
        self.assertTrue(report.get("ok"), report)
        self.assertEqual(
            [str(row.get("op")) for row in report.get("results") or []],
            ["repair"],
        )
        self.assertTrue(all(bool(row.get("ok")) for row in report.get("results") or []))
        timings = report.get("timings") or {}
        self.assertFalse(timings.get("runtime_patch_fast_path"))
        self.assertFalse(timings.get("snapshot_fast_path"))
        self.assertNotIn("frontend_patch", report)

        after_snapshot = json.loads(self.snapshot.read_text(encoding="utf-8"))
        self.assertEqual("gates-of-codex.frontend", after_snapshot["schema"])
        self.assertNotEqual(before_snapshot, self.snapshot.read_bytes())
        self.assertNotEqual(RUNTIME_PATCH_SCHEMA, after_snapshot["schema"])

        state = load_campaign(self.campaign)
        self.assertEqual(80, state.battalions["bn-n"].condition)
        repair_row = (report.get("results") or [])[0]
        self.assertEqual(15, repair_row["data"]["points_repaired"])
        self.assertEqual(80, repair_row["data"]["condition"])
