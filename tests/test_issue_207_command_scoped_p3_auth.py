from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, earth3_operational


class CommandScopedP3AuthorityTests(unittest.TestCase):
    def test_one_command_reuses_one_authenticated_graph_and_restores_loader(self) -> None:
        calls = {"auth": 0}
        graph = {
            "schema": "test",
            "nodes": [{"node_id": "a"}],
            "edges": [],
            "sites": [],
            "rules": {},
        }

        def fake_auth(*, repository_root=None):
            calls["auth"] += 1
            return {
                **graph,
                "repository_root": None if repository_root is None else str(repository_root),
            }

        def fake_apply(campaign_path, *, commands, commands_path, snapshot_path):
            first = earth3_operational.load_authenticated_p3_graph()
            first["nodes"].append({"node_id": "mutated-by-caller"})
            second = earth3_operational.load_authenticated_p3_graph()
            third = earth3_operational.load_authenticated_p3_graph()
            self.assertEqual([{"node_id": "a"}], second["nodes"])
            self.assertEqual([{"node_id": "a"}], third["nodes"])
            return {
                "ok": True,
                "campaign_path": str(campaign_path),
                "snapshot_path": str(snapshot_path or ""),
                "commands_applied": 1,
                "results": [{"op": "end_player_round", "ok": True, "data": {}}],
            }

        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            campaign.write_text("{}\n", encoding="utf-8")
            with (
                patch.object(earth3_operational, "load_authenticated_p3_graph", fake_auth),
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "end_player_round"}],
                )
                self.assertIs(earth3_operational.load_authenticated_p3_graph, fake_auth)
                earth3_operational.load_authenticated_p3_graph()

        self.assertEqual(2, calls["auth"])
        self.assertEqual(1, report["timings"]["p3_auth_loads"])
        self.assertEqual(2, report["timings"]["p3_auth_cache_hits"])

    def test_explicit_repository_roots_are_cached_separately(self) -> None:
        calls: list[str] = []

        def fake_auth(*, repository_root=None):
            calls.append("<default>" if repository_root is None else str(repository_root))
            return {"nodes": [], "edges": [], "sites": [], "rules": {}}

        def fake_apply(campaign_path, *, commands, commands_path, snapshot_path):
            earth3_operational.load_authenticated_p3_graph()
            earth3_operational.load_authenticated_p3_graph(repository_root=Path("one"))
            earth3_operational.load_authenticated_p3_graph(repository_root=Path("one"))
            earth3_operational.load_authenticated_p3_graph(repository_root=Path("two"))
            return {
                "ok": True,
                "campaign_path": str(campaign_path),
                "snapshot_path": "",
                "commands_applied": 1,
                "results": [{"op": "refresh", "ok": True, "data": {}}],
            }

        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign.json"
            campaign.write_text("{}\n", encoding="utf-8")
            with (
                patch.object(earth3_operational, "load_authenticated_p3_graph", fake_auth),
                patch.object(command_cycle_perf, "_ORIGINAL_APPLY", fake_apply),
            ):
                report = command_cycle_perf.measured_apply_frontend_commands(
                    campaign,
                    commands=[{"op": "refresh"}],
                )

        self.assertEqual(3, len(calls))
        self.assertEqual(3, report["timings"]["p3_auth_loads"])
        self.assertEqual(1, report["timings"]["p3_auth_cache_hits"])

    def test_timing_contract_includes_command_scoped_authority_counts(self) -> None:
        self.assertIn("p3_auth_loads", command_cycle_perf.timing_keys())
        self.assertIn("p3_auth_cache_hits", command_cycle_perf.timing_keys())


if __name__ == "__main__":
    unittest.main()
