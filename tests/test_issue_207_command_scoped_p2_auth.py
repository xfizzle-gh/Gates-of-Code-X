from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gates_of_codex import command_cycle_perf, command_scoped_p2_auth, earth3_bootstrap


ROOT = Path(__file__).resolve().parents[1]


class CommandScopedP2AuthorityTests(unittest.TestCase):
    def test_one_command_reuses_one_authenticated_bundle_and_restores_loader(self) -> None:
        calls = {"auth": 0}

        def fake_auth(*, authority_root=None):
            calls["auth"] += 1
            return SimpleNamespace(
                authority_root=None if authority_root is None else str(authority_root),
                documents={"rows": [{"id": "a"}]},
            )

        def action():
            first = earth3_bootstrap.load_earth3_bootstrap()
            first.documents["rows"].append({"id": "mutated-by-caller"})
            second = earth3_bootstrap.load_earth3_bootstrap()
            third = earth3_bootstrap.load_earth3_bootstrap()
            self.assertEqual([{"id": "a"}], second.documents["rows"])
            self.assertEqual([{"id": "a"}], third.documents["rows"])
            return "ok"

        with patch.object(earth3_bootstrap, "load_earth3_bootstrap", fake_auth):
            result, stats = command_scoped_p2_auth._run_with_command_scoped_p2_auth(action)
            self.assertIs(earth3_bootstrap.load_earth3_bootstrap, fake_auth)
            earth3_bootstrap.load_earth3_bootstrap()

        self.assertEqual("ok", result)
        self.assertEqual(2, calls["auth"])
        self.assertEqual({"loads": 1, "hits": 2}, stats)

    def test_explicit_authority_roots_are_cached_separately(self) -> None:
        calls: list[str] = []

        def fake_auth(*, authority_root=None):
            calls.append("<default>" if authority_root is None else str(authority_root))
            return SimpleNamespace(documents={"rows": []})

        def action():
            earth3_bootstrap.load_earth3_bootstrap()
            earth3_bootstrap.load_earth3_bootstrap(authority_root=Path("one"))
            earth3_bootstrap.load_earth3_bootstrap(authority_root=Path("one"))
            earth3_bootstrap.load_earth3_bootstrap(authority_root=Path("two"))
            return None

        with patch.object(earth3_bootstrap, "load_earth3_bootstrap", fake_auth):
            _result, stats = command_scoped_p2_auth._run_with_command_scoped_p2_auth(action)

        self.assertEqual(3, len(calls))
        self.assertEqual({"loads": 3, "hits": 1}, stats)

    def test_fast_path_installer_registers_p2_command_cache_after_measured_layer(self) -> None:
        source = (ROOT / "src/gates_of_codex/fast_entrypoint.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("install_command_scoped_p2_auth", source)
        self.assertLess(
            source.index("install_command_cycle_perf_path()"),
            source.index("install_command_scoped_p2_auth()"),
        )

    def test_diagnostic_counters_do_not_change_stable_timing_contract(self) -> None:
        self.assertNotIn("p2_auth_loads", command_cycle_perf.timing_keys())
        self.assertNotIn("p2_auth_cache_hits", command_cycle_perf.timing_keys())


if __name__ == "__main__":
    unittest.main()
