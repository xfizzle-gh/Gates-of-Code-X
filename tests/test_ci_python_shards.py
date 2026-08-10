from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "run_python_test_shard.py"
SPEC = importlib.util.spec_from_file_location("run_python_test_shard", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Could not load CI shard runner from {MODULE_PATH}")
SHARDS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHARDS)


class PythonShardClassificationTests(unittest.TestCase):
    def test_p1_and_p2_modules_are_in_authority_bootstrap_shard(self) -> None:
        for test_id in (
            "test_p1_earth3_campaign_authority.AuthorityTests.test_exact_bytes",
            "tests.test_p2_earth3_campaign_bootstrap.BootstrapTests.test_build",
            "test_p2_identity_downgrade_guard.IdentityTests.test_tamper",
        ):
            with self.subTest(test_id=test_id):
                self.assertEqual(
                    "earth3-authority-bootstrap",
                    SHARDS.classify_test_id(test_id),
                )

    def test_only_real_p4_production_class_uses_p4_shard(self) -> None:
        self.assertEqual(
            "p4-production-launch",
            SHARDS.classify_test_id(
                "test_p4_player_shell.Earth3ProductionLaunchTests."
                "test_one_player_command_creates_earth3_campaign_and_snapshot"
            ),
        )
        self.assertEqual(
            "core",
            SHARDS.classify_test_id(
                "test_p4_player_shell.PlayerCommandAuthorityTests."
                "test_replayed_command_id_cannot_apply_twice"
            ),
        )
        self.assertEqual(
            "core",
            SHARDS.classify_test_id(
                "test_p4_path_canonicalization.PathCanonicalizationTests.test_windows_alias"
            ),
        )

    def test_unclassified_tests_fall_into_core(self) -> None:
        self.assertEqual(
            "core",
            SHARDS.classify_test_id(
                "test_operational_s7_ai_orders.AIOrderTests.test_route"
            ),
        )

    def test_explicit_overlap_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "multiple explicit CI shards"):
            SHARDS.classify_test_id(
                "test_p1_fake.Earth3ProductionLaunchTests.test_overlap"
            )

    def test_duplicate_discovery_ids_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate IDs"):
            SHARDS.partition_ids(
                [
                    "test_alpha.AlphaTests.test_one",
                    "test_alpha.AlphaTests.test_one",
                ]
            )

    def test_partition_is_complete_and_pairwise_disjoint(self) -> None:
        ids = [
            "test_alpha.AlphaTests.test_one",
            "test_p1_alpha.P1Tests.test_one",
            "test_p2_beta.P2Tests.test_two",
            "test_p4_player_shell.Earth3ProductionLaunchTests.test_real",
            "test_p4_player_shell.PlayerCommandAuthorityTests.test_fast",
        ]
        partition = SHARDS.partition_ids(ids)
        flattened = [
            test_id
            for shard in SHARDS.SHARDS
            for test_id in partition[shard]
        ]
        self.assertCountEqual(ids, flattened)
        self.assertEqual(len(ids), len(set(flattened)))
        self.assertEqual(
            {"test_p1_alpha.P1Tests.test_one", "test_p2_beta.P2Tests.test_two"},
            set(partition["earth3-authority-bootstrap"]),
        )
        self.assertEqual(
            {"test_p4_player_shell.Earth3ProductionLaunchTests.test_real"},
            set(partition["p4-production-launch"]),
        )

    def test_repository_discovery_preserves_package_import_context(self) -> None:
        tests = SHARDS.discover_tests(ROOT / "tests")
        ids = [test.id() for test in tests]
        failed_imports = [
            test_id
            for test_id in ids
            if test_id.startswith("unittest.loader._FailedTest.")
        ]
        self.assertEqual([], failed_imports)
        self.assertTrue(
            any("test_operational_s9a_authority" in test_id for test_id in ids),
            "known tests.* fixture-import consumer was not discovered",
        )
        self.assertTrue(
            any("test_s11_frontend" in test_id for test_id in ids),
            "known tests.* fixture-import consumer was not discovered",
        )


if __name__ == "__main__":
    unittest.main()
