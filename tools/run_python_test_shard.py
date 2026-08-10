from __future__ import annotations

import argparse
import hashlib
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

SHARDS = (
    "core",
    "earth3-authority-bootstrap",
    "p4-production-launch",
)


def _module_name(test_id: str) -> str:
    parts = test_id.rsplit(".", 2)
    if len(parts) < 3:
        return test_id.split(".", 1)[0]
    return parts[0].split(".")[-1]


def _explicit_matches(test_id: str) -> list[str]:
    matches: list[str] = []
    module = _module_name(test_id)
    if module.startswith(("test_p1_", "test_p2_")):
        matches.append("earth3-authority-bootstrap")
    if ".Earth3ProductionLaunchTests." in test_id:
        matches.append("p4-production-launch")
    return matches


def classify_test_id(test_id: str) -> str:
    matches = _explicit_matches(test_id)
    if len(matches) > 1:
        raise ValueError(
            f"Test {test_id!r} matches multiple explicit CI shards: {matches}"
        )
    return matches[0] if matches else "core"


def partition_ids(test_ids: Iterable[str]) -> dict[str, tuple[str, ...]]:
    ids = tuple(test_ids)
    duplicates = sorted(test_id for test_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"Canonical unittest discovery returned duplicate IDs: {duplicates}")

    result: dict[str, list[str]] = {name: [] for name in SHARDS}
    for test_id in ids:
        shard = classify_test_id(test_id)
        if shard not in result:
            raise ValueError(f"Test {test_id!r} was assigned to unknown shard {shard!r}")
        result[shard].append(test_id)

    assigned = [test_id for values in result.values() for test_id in values]
    if set(assigned) != set(ids) or len(assigned) != len(ids):
        missing = sorted(set(ids) - set(assigned))
        extras = sorted(set(assigned) - set(ids))
        raise ValueError(
            "CI shard partition does not exactly cover canonical discovery; "
            f"missing={missing}, extras={extras}"
        )

    memberships = Counter(assigned)
    overlaps = sorted(test_id for test_id, count in memberships.items() if count != 1)
    if overlaps:
        raise ValueError(f"CI shard partition is not pairwise disjoint: {overlaps}")

    return {name: tuple(values) for name, values in result.items()}


def _walk_suite(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _walk_suite(item)
        else:
            yield item


def discover_tests(start_dir: Path) -> list[unittest.TestCase]:
    loader = unittest.defaultTestLoader
    suite = loader.discover(str(start_dir), pattern="test*.py")
    return list(_walk_suite(suite))


def _partition_tests(
    tests: list[unittest.TestCase],
) -> tuple[dict[str, tuple[str, ...]], dict[str, list[unittest.TestCase]]]:
    ids = [test.id() for test in tests]
    partition = partition_ids(ids)
    by_id = {test.id(): test for test in tests}
    selected = {
        shard: [by_id[test_id] for test_id in test_ids]
        for shard, test_ids in partition.items()
    }
    return partition, selected


def _digest(test_ids: Iterable[str]) -> str:
    body = "\n".join(sorted(test_ids)).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def print_partition(partition: dict[str, tuple[str, ...]]) -> None:
    all_ids = tuple(test_id for shard in SHARDS for test_id in partition[shard])
    print(
        "python-test-partition: "
        f"discovered={len(all_ids)} sha256={_digest(all_ids)}"
    )
    for shard in SHARDS:
        ids = partition[shard]
        print(f"python-test-partition: shard={shard} count={len(ids)} sha256={_digest(ids)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and execute deterministic unittest CI shards."
    )
    parser.add_argument(
        "--start-dir",
        default="tests",
        help="Canonical unittest discovery directory (default: tests).",
    )
    parser.add_argument("--shard", choices=SHARDS)
    parser.add_argument(
        "--verify-partition",
        action="store_true",
        help="Prove every discovered test belongs to exactly one shard and print counts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.shard and not args.verify_partition:
        raise SystemExit("Specify --verify-partition and/or --shard")

    start_dir = Path(args.start_dir)
    if not start_dir.is_dir():
        raise SystemExit(f"Test discovery directory does not exist: {start_dir}")

    tests = discover_tests(start_dir)
    partition, selected = _partition_tests(tests)
    if args.verify_partition:
        print_partition(partition)

    if not args.shard:
        return 0

    shard_tests = selected[args.shard]
    print(
        f"python-test-shard: running shard={args.shard} "
        f"count={len(shard_tests)} total={len(tests)}"
    )
    if not shard_tests:
        print(f"python-test-shard: shard={args.shard} is empty on this revision")
        return 0

    suite = unittest.TestSuite(shard_tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
