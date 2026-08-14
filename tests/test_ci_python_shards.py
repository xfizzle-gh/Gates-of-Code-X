from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_broken_discovery_fails_before_every_core_lane_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "test_broken.py").write_text(
                "def this_will_not_parse(:\n    pass\n",
                encoding="utf-8",
            )

            for lane in range(len(SHARDS.CI_CORE_LANES)):
                with self.subTest(lane=lane):
                    with mock.patch.object(
                        SHARDS,
                        "current_ci_core_lane",
                        return_value=lane,
                    ) as lane_selector:
                        with self.assertRaisesRegex(
                            SHARDS.DiscoveryError,
                            "unittest discovery failed before CI sharding",
                        ):
                            SHARDS.main(
                                [
                                    "--start-dir",
                                    str(root),
                                    "--shard",
                                    "core",
                                ]
                            )
                        lane_selector.assert_not_called()

    def test_checked_in_workflow_matches_core_lane_contract(self) -> None:
        SHARDS.verify_workflow_core_lane_contract(
            ROOT / ".github" / "workflows" / "gates-of-codex.yml"
        )

    def test_removing_any_workflow_core_lane_fails_closed(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "gates-of-codex.yml").read_text(
            encoding="utf-8"
        )
        for lane, (job_id, _system, _runner, _version) in enumerate(
            SHARDS.CI_CORE_LANES
        ):
            with self.subTest(lane=lane, job_id=job_id):
                mutated = workflow.replace(
                    f"  {job_id}:\n",
                    f"  removed-{job_id}:\n",
                    1,
                )
                self.assertNotEqual(workflow, mutated)
                with tempfile.TemporaryDirectory() as temp_dir:
                    workflow_path = Path(temp_dir) / "workflow.yml"
                    workflow_path.write_text(mutated, encoding="utf-8")
                    with self.assertRaisesRegex(
                        SHARDS.WorkflowLaneContractError,
                        "workflow job is missing",
                    ):
                        SHARDS.verify_workflow_core_lane_contract(workflow_path)

    def test_workflow_runtime_drift_fails_closed(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "gates-of-codex.yml").read_text(
            encoding="utf-8"
        )
        job_id, _system, _runner, _version = SHARDS.CI_CORE_LANES[0]
        start = workflow.index(f"  {job_id}:\n")
        next_job = workflow.index("\n  python-shards-ubuntu-313:\n", start)
        block = workflow[start:next_job]
        mutated_block = block.replace('python-version: "3.11"', 'python-version: "3.12"', 1)
        self.assertNotEqual(block, mutated_block)
        mutated = workflow[:start] + mutated_block + workflow[next_job:]

        with tempfile.TemporaryDirectory() as temp_dir:
            workflow_path = Path(temp_dir) / "workflow.yml"
            workflow_path.write_text(mutated, encoding="utf-8")
            with self.assertRaisesRegex(
                SHARDS.WorkflowLaneContractError,
                "Python mismatch",
            ):
                SHARDS.verify_workflow_core_lane_contract(workflow_path)


if __name__ == "__main__":
    unittest.main()
