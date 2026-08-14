from __future__ import annotations

import unittest

from tools.run_python_test_shard import CI_CORE_LANES, partition_core_ci_lanes


class CoreLanePartitionTests(unittest.TestCase):
    def test_core_lanes_are_exact_disjoint_and_class_preserving(self) -> None:
        ids = (
            "tests.test_alpha.AlphaTests.test_a",
            "tests.test_alpha.AlphaTests.test_b",
            "tests.test_alpha.AlphaTests.test_c",
            "tests.test_alpha.BetaTests.test_a",
            "tests.test_beta.GammaTests.test_a",
            "tests.test_beta.GammaTests.test_b",
            "tests.test_gamma.DeltaTests.test_a",
            "tests.test_delta.EpsilonTests.test_a",
            "tests.test_epsilon.ZetaTests.test_a",
        )

        lanes = partition_core_ci_lanes(ids)

        self.assertEqual(len(CI_CORE_LANES), len(lanes))
        flattened = [test_id for lane in lanes for test_id in lane]
        self.assertCountEqual(ids, flattened)
        self.assertEqual(len(flattened), len(set(flattened)))

        class_to_lane: dict[str, int] = {}
        for lane_index, lane in enumerate(lanes):
            for test_id in lane:
                class_key = test_id.rsplit(".", 1)[0]
                previous = class_to_lane.setdefault(class_key, lane_index)
                self.assertEqual(previous, lane_index)

    def test_core_lane_partition_is_deterministic_and_balanced_by_test_count(self) -> None:
        ids = tuple(
            f"tests.test_{class_index}.Class{class_index}.test_{test_index}"
            for class_index, count in enumerate((8, 7, 6, 5, 4, 3, 2, 2, 1, 1))
            for test_index in range(count)
        )

        first = partition_core_ci_lanes(ids)
        second = partition_core_ci_lanes(reversed(ids))

        self.assertEqual(first, second)
        sizes = [len(lane) for lane in first]
        self.assertLessEqual(max(sizes) - min(sizes), 2)

    def test_invalid_lane_count_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "lane_count must be positive"):
            partition_core_ci_lanes(("tests.test_x.X.test_a",), lane_count=0)


if __name__ == "__main__":
    unittest.main()
