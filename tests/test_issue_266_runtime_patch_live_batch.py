from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from gates_of_codex import command_cycle_perf
from gates_of_codex.command_cycle_perf import (
    _is_live_move_batch,
    _runtime_patch_only,
    _should_persist_runtime_snapshot,
    _snapshot_patch_only,
    measured_apply_frontend_commands,
)
from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op
from gates_of_codex.frontend import build_frontend_snapshot
from gates_of_codex.frontend_runtime_patch import apply_runtime_patch_to_snapshot
from gates_of_codex.operational_schema import stable_edge_id, stable_node_id
from gates_of_codex.state_io import load_campaign, save_campaign
from tests.test_s10_frontend_presentation_contract import (
    _create_prepared_contact,
    _state,
)


ROOT = Path(__file__).resolve().parents[1]
DYNAMIC_KEYS = (
    "factions",
    "objectives",
    "strategic_formations",
    "commanders",
    "battalions",
    "battalion_stacks",
    "stack_presentations",
    "battalion_presentations",
    "strategic_formation_presentations",
    "pending_battle",
    "front_options",
    "operational_orders",
    "fog_of_war",
    "last_known_contacts",
)
CONTROL_IGNORE = {
    "python_executable",
    "campaign_path",
    "snapshot_path",
    "commands_path",
}


def _move_batch(*, locked_stance: str = "operational") -> list[dict[str, Any]]:
    node_a, node_b = stable_node_id("a"), stable_node_id("b")
    return [
        {
            "op": "issue_move_order",
            "formation": "sf-n",
            "path_node_ids": [node_a, node_b],
            "path_edge_ids": [stable_edge_id("corridor", node_a, node_b)],
        },
        {"op": "commit_move_orders", "faction": "nato", "locked_stance": locked_stance},
    ]


def apply_runtime_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    return apply_runtime_patch_to_snapshot(base, patch)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in CONTROL_IGNORE
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _force(snapshot: dict[str, Any], formation_id: str) -> dict[str, Any]:
    for row in snapshot.get("strategic_formations") or []:
        if isinstance(row, dict) and str(row.get("id")) == formation_id:
            return row
    raise AssertionError(f"missing formation {formation_id}")


class LiveBatchRoutingTests(unittest.TestCase):
    def test_exact_live_batch_is_runtime_patch_not_snapshot_fast(self) -> None:
        batch = _move_batch()
        self.assertTrue(_is_live_move_batch(batch))
        self.assertTrue(_runtime_patch_only(batch))
        self.assertFalse(_snapshot_patch_only(batch))
        self.assertTrue(_snapshot_patch_only([{"op": "issue_move_order"}]))
        self.assertTrue(_snapshot_patch_only([{"op": "cancel_move_order"}]))
        self.assertFalse(_runtime_patch_only([{"op": "issue_move_order"}]))
        self.assertFalse(
            _runtime_patch_only(
                [{"op": "issue_move_order"}, {"op": "commit_move_orders"}, {"op": "refresh"}]
            )
        )
        self.assertTrue(_runtime_patch_only([{"op": "auto_resolve"}]))
        self.assertFalse(_runtime_patch_only([{"op": "refresh"}]))

    def test_commit_is_not_in_snapshot_patch_ops(self) -> None:
        self.assertNotIn("commit_move_orders", command_cycle_perf._SNAPSHOT_PATCH_OPS)

    def test_persist_only_live_batch_and_auto_resolve(self) -> None:
        self.assertTrue(_should_persist_runtime_snapshot(_move_batch()))
        self.assertTrue(_should_persist_runtime_snapshot([{"op": "auto_resolve"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "end_player_round"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "refresh"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "issue_move_order"}]))
        self.assertFalse(_should_persist_runtime_snapshot([{"op": "upgrade_site"}]))

    def test_godot_selects_runtime_patch_before_issue_lightweight_path(self) -> None:
        source = (ROOT / "godot/scripts/main_perf_measured.gd").read_text(encoding="utf-8")
        dispatch = source.split("func _on_command_finished(", 1)[1]
        runtime_at = dispatch.index("_is_live_move_batch(commands)")
        light_at = dispatch.index("_is_lightweight_order_op(op)")
        self.assertLess(runtime_at, light_at)


class LiveBatchParityTests(unittest.TestCase):
    def _prepare(self, root: Path, *, prepared_contact: bool = False) -> tuple[Path, Path, dict[str, Any]]:
        state = _state(root)
        if prepared_contact:
            _create_prepared_contact(state)
        campaign = root / "campaign.json"
        snapshot = root / "campaign_snapshot.json"
        save_campaign(state, campaign)
        before = build_frontend_snapshot(state, campaign_path=campaign)
        snapshot.write_text(json.dumps(before), encoding="utf-8")
        return campaign, snapshot, before

    def _apply(self, campaign: Path, snapshot: Path, commands: list[dict[str, Any]]) -> dict[str, Any]:
        return measured_apply_frontend_commands(
            campaign,
            commands=commands,
            snapshot_path=snapshot,
        )

    def test_successful_issue_commit_matches_full_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign, snapshot_path, before = self._prepare(Path(temporary))
            report = self._apply(campaign, snapshot_path, _move_batch())
            self.assertTrue(report.get("ok"))
            self.assertTrue(report["timings"]["runtime_patch_fast_path"])
            self.assertFalse(report["timings"]["snapshot_fast_path"])
            persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "committed",
                (_force(persisted, "sf-n").get("move_order") or {}).get("status"),
            )
            patched = apply_runtime_patch(before, report["frontend_patch"])
            full = build_frontend_snapshot(load_campaign(campaign), campaign_path=campaign)
            order = _force(patched, "sf-n").get("move_order") or {}
            self.assertEqual("committed", order.get("status"))
            self.assertIsNotNone(order.get("committed_turn"))
            self.assertEqual("operational", order.get("locked_stance"))
            self.assertEqual(
                [stable_node_id("a"), stable_node_id("b")],
                order.get("path_node_ids"),
            )
            self._assert_dynamic_parity(patched, full)

    def test_rejected_commit_matches_blocked_full_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign, snapshot_path, before = self._prepare(Path(temporary))
            report = self._apply(
                campaign,
                snapshot_path,
                _move_batch(locked_stance="refit_resupply"),
            )
            self.assertTrue(report.get("ok"))
            patched = apply_runtime_patch(before, report["frontend_patch"])
            full = build_frontend_snapshot(load_campaign(campaign), campaign_path=campaign)
            patched_order = _force(patched, "sf-n").get("move_order") or {}
            full_order = _force(full, "sf-n").get("move_order") or {}
            self.assertEqual(full_order.get("status"), patched_order.get("status"))
            self.assertNotEqual("draft", patched_order.get("status"))
            self.assertEqual(full_order, patched_order)
            self._assert_dynamic_parity(patched, full)

    def test_auto_resolve_patch_matches_full_snapshot_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign, snapshot_path, before = self._prepare(
                Path(temporary), prepared_contact=True
            )
            self.assertIsNotNone(before.get("pending_battle"))
            report = self._apply(campaign, snapshot_path, [{"op": "auto_resolve"}])
            self.assertTrue(report.get("ok"))
            self.assertTrue(report["timings"]["runtime_patch_fast_path"])
            persisted = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertIsNone(persisted.get("pending_battle"))
            state = load_campaign(campaign)
            self.assertIsNone(state.pending_battle)
            patched = apply_runtime_patch(before, report["frontend_patch"])
            self.assertIsNone(patched.get("pending_battle"))
            restarted = build_frontend_snapshot(state, campaign_path=campaign)
            self.assertIsNone(restarted.get("pending_battle"))
            self._assert_dynamic_parity(patched, restarted)
            self.assertIn("winner", (report.get("results") or [{}])[0].get("data") or {})

    def test_end_player_round_leaves_snapshot_file_untouched(self) -> None:
        install_frontend_turn_cycle_op()
        with tempfile.TemporaryDirectory() as temporary:
            campaign, snapshot_path, _before = self._prepare(Path(temporary))
            before_bytes = snapshot_path.read_bytes()
            report = self._apply(campaign, snapshot_path, [{"op": "end_player_round"}])
            self.assertTrue(report.get("ok"), report)
            self.assertTrue(report["timings"]["runtime_patch_fast_path"])
            self.assertEqual(before_bytes, snapshot_path.read_bytes())

    def _assert_dynamic_parity(self, patched: dict[str, Any], full: dict[str, Any]) -> None:
        for key in DYNAMIC_KEYS:
            self.assertEqual(
                _normalize(patched.get(key)),
                _normalize(full.get(key)),
                key,
            )
        for key in ("turn_number", "current_faction", "selected_faction", "operational_clock"):
            self.assertEqual(
                _normalize((patched.get("campaign") or {}).get(key)),
                _normalize((full.get("campaign") or {}).get(key)),
                f"campaign.{key}",
            )
        patched_forces = {
            str(row.get("id")): row
            for row in patched.get("strategic_formations") or []
            if isinstance(row, dict)
        }
        full_forces = {
            str(row.get("id")): row
            for row in full.get("strategic_formations") or []
            if isinstance(row, dict)
        }
        self.assertEqual(set(patched_forces), set(full_forces))
        for identity, row in full_forces.items():
            self.assertEqual(
                _normalize(patched_forces[identity].get("move_order")),
                _normalize(row.get("move_order")),
                f"{identity}.move_order",
            )
            self.assertEqual(
                _normalize(patched_forces[identity].get("position")),
                _normalize(row.get("position")),
                f"{identity}.position",
            )
            self.assertEqual(
                patched_forces[identity].get("province_id"),
                row.get("province_id"),
                f"{identity}.province_id",
            )


if __name__ == "__main__":
    unittest.main()
