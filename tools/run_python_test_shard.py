from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "gates-of-codex.yml"

SHARDS = (
    "core",
    "earth3-authority-bootstrap",
    "p4-production-launch",
)

# job id, platform.system(), runs-on label, Python major/minor
CI_CORE_LANES = (
    ("python-shards-ubuntu-311", "Linux", "ubuntu-latest", (3, 11)),
    ("python-shards-ubuntu-313", "Linux", "ubuntu-latest", (3, 13)),
    ("python-shards-windows-311", "Windows", "windows-latest", (3, 11)),
    ("python-shards-windows-313", "Windows", "windows-latest", (3, 13)),
)


class DiscoveryError(RuntimeError):
    """Canonical unittest discovery failed before tests could be sharded."""


class WorkflowLaneContractError(RuntimeError):
    """The workflow no longer matches the Python core-lane contract."""


def _module_name(test_id: str) -> str:
    parts = test_id.rsplit(".", 2)
    if len(parts) < 3:
        return test_id.split(".", 1)[0]
    return parts[0].split(".")[-1]


def _class_key(test_id: str) -> str:
    parts = test_id.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else test_id


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


def partition_core_ci_lanes(
    core_ids: Iterable[str],
    *,
    lane_count: int = len(CI_CORE_LANES),
) -> tuple[tuple[str, ...], ...]:
    """Split core tests into deterministic class-preserving CI lanes.

    The workflow already launches four core jobs for Linux/Windows x Python
    3.11/3.13. Historically every job reran the complete core suite. CI now
    treats those existing jobs as four disjoint lanes so the aggregate matrix
    still covers every core test exactly once without adding runners.

    Tests from one unittest class stay together so setUpClass/tearDownClass
    semantics remain intact. Classes are greedily balanced by test count with
    deterministic tie-breaking.
    """

    if lane_count < 1:
        raise ValueError("lane_count must be positive")

    ids = tuple(core_ids)
    duplicates = sorted(test_id for test_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"Core CI lane input contains duplicate IDs: {duplicates}")

    groups: dict[str, list[str]] = defaultdict(list)
    for test_id in ids:
        groups[_class_key(test_id)].append(test_id)

    lanes: list[list[str]] = [[] for _ in range(lane_count)]
    lane_sizes = [0] * lane_count
    ordered_groups = sorted(
        groups.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    for _, group_ids in ordered_groups:
        lane = min(range(lane_count), key=lambda index: (lane_sizes[index], index))
        ordered_ids = sorted(group_ids)
        lanes[lane].extend(ordered_ids)
        lane_sizes[lane] += len(ordered_ids)

    assigned = [test_id for lane in lanes for test_id in lane]
    if set(assigned) != set(ids) or len(assigned) != len(ids):
        missing = sorted(set(ids) - set(assigned))
        extras = sorted(set(assigned) - set(ids))
        raise ValueError(
            "Core CI lane partition does not exactly cover the core shard; "
            f"missing={missing}, extras={extras}"
        )
    overlaps = sorted(
        test_id for test_id, count in Counter(assigned).items() if count != 1
    )
    if overlaps:
        raise ValueError(f"Core CI lane partition is not pairwise disjoint: {overlaps}")

    return tuple(tuple(lane) for lane in lanes)


def _workflow_job_blocks(text: str) -> dict[str, str]:
    headers = list(re.finditer(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", text))
    blocks: dict[str, str] = {}
    for index, match in enumerate(headers):
        start = match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        blocks[match.group(1)] = text[start:end]
    return blocks


def verify_workflow_core_lane_contract(workflow_path: Path = WORKFLOW_PATH) -> None:
    """Fail if workflow core jobs drift from the lane map used by Python.

    This check deliberately reads the checked-in workflow rather than trusting
    the Python constant alone. Removing a workflow job, removing ``core`` from
    its shard matrix, changing its runner, or changing its Python version makes
    every surviving ``--verify-partition`` invocation fail closed.
    """

    text = workflow_path.read_text(encoding="utf-8")
    blocks = _workflow_job_blocks(text)

    identities = [(system, version) for _, system, _, version in CI_CORE_LANES]
    if len(set(identities)) != len(identities):
        raise WorkflowLaneContractError(
            f"CI_CORE_LANES contains duplicate runtime identities: {identities}"
        )

    for lane, (job_id, _system, runner, (major, minor)) in enumerate(CI_CORE_LANES):
        block = blocks.get(job_id)
        if block is None:
            raise WorkflowLaneContractError(
                f"Core lane {lane} workflow job is missing: {job_id}"
            )

        runners = re.findall(r"(?m)^    runs-on:\s*([^\s#]+)\s*$", block)
        if runners != [runner]:
            raise WorkflowLaneContractError(
                f"Core lane {lane} {job_id} runs-on mismatch: "
                f"expected {runner!r}, found {runners!r}"
            )

        versions = re.findall(
            r"(?m)^\s+python-version:\s*[\"']?([^\"'\s#]+)[\"']?\s*$",
            block,
        )
        expected_version = f"{major}.{minor}"
        if versions != [expected_version]:
            raise WorkflowLaneContractError(
                f"Core lane {lane} {job_id} Python mismatch: "
                f"expected {expected_version!r}, found {versions!r}"
            )

        shard_rows = re.findall(r"(?m)^        shard:\s*\[([^\]]+)\]\s*$", block)
        if len(shard_rows) != 1:
            raise WorkflowLaneContractError(
                f"Core lane {lane} {job_id} must define exactly one inline shard matrix"
            )
        shards = {part.strip() for part in shard_rows[0].split(",")}
        if "core" not in shards:
            raise WorkflowLaneContractError(
                f"Core lane {lane} {job_id} no longer schedules the core shard"
            )


def current_ci_core_lane() -> int | None:
    """Return this GitHub Actions runner's core lane, or None outside CI."""

    if os.environ.get("GITHUB_ACTIONS", "").casefold() != "true":
        return None

    identity = (platform.system(), (sys.version_info.major, sys.version_info.minor))
    for lane, (_job_id, system, _runner, version) in enumerate(CI_CORE_LANES):
        if identity == (system, version):
            return lane

    supported = ", ".join(
        f"{system} {major}.{minor}"
        for _job_id, system, _runner, (major, minor) in CI_CORE_LANES
    )
    raise RuntimeError(
        f"Unsupported GitHub Actions core lane {identity!r}; expected one of: {supported}"
    )


def _walk_suite(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _walk_suite(item)
        else:
            yield item


def discover_tests(start_dir: Path) -> list[unittest.TestCase]:
    # ``python -m unittest discover -s tests`` runs with the repository root on
    # sys.path because Python is executing a module from the working directory.
    # Executing this repository-owned runner as ``python tools/...`` instead puts
    # only ``tools/`` at sys.path[0]. Preserve the old canonical import context so
    # tests that intentionally share fixtures via ``tests.test_*`` resolve exactly
    # as they did before sharding.
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    # A fresh loader is required here. ``unittest`` converts import/syntax errors
    # during discovery into _FailedTest instances and records the real error text
    # on TestLoader.errors. Those failures must abort before shard/lane filtering,
    # otherwise an environment-specific _FailedTest could be assigned to another
    # lane and silently disappear from the runner where discovery actually broke.
    loader = unittest.TestLoader()
    suite = loader.discover(str(start_dir), pattern="test*.py")
    tests = list(_walk_suite(suite))
    failed_test_ids = [
        test.id()
        for test in tests
        if test.__class__.__module__ == "unittest.loader"
        and test.__class__.__name__ == "_FailedTest"
    ]
    if loader.errors or failed_test_ids:
        detail = "\n\n".join(loader.errors) if loader.errors else ""
        failed = ", ".join(failed_test_ids) if failed_test_ids else "<unknown>"
        raise DiscoveryError(
            "unittest discovery failed before CI sharding; "
            f"failed_tests={failed}\n{detail}"
        )
    return tests


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

    core_lanes = partition_core_ci_lanes(partition["core"])
    for lane, ids in enumerate(core_lanes):
        job_id, system, _runner, (major, minor) = CI_CORE_LANES[lane]
        print(
            "python-test-partition: "
            f"core-lane={lane} job={job_id} runner={system}-{major}.{minor} "
            f"count={len(ids)} sha256={_digest(ids)}"
        )


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
        help=(
            "Prove every discovered test belongs to exactly one logical shard, "
            "that core is exactly covered by the four existing CI matrix lanes, "
            "and that the checked-in workflow still schedules all four lanes."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.shard and not args.verify_partition:
        raise SystemExit("Specify --verify-partition and/or --shard")

    start_dir = Path(args.start_dir)
    if not start_dir.is_absolute():
        start_dir = ROOT / start_dir
    if not start_dir.is_dir():
        raise SystemExit(f"Test discovery directory does not exist: {start_dir}")

    if args.verify_partition or os.environ.get("GITHUB_ACTIONS", "").casefold() == "true":
        verify_workflow_core_lane_contract()

    # Discovery must complete successfully before any partition or lane is chosen.
    tests = discover_tests(start_dir)
    partition, selected = _partition_tests(tests)
    if args.verify_partition:
        print_partition(partition)

    if not args.shard:
        return 0

    shard_tests = selected[args.shard]
    lane = None
    if args.shard == "core":
        lane = current_ci_core_lane()
        if lane is not None:
            core_lanes = partition_core_ci_lanes(partition["core"])
            lane_ids = set(core_lanes[lane])
            shard_tests = [test for test in shard_tests if test.id() in lane_ids]

    lane_text = f" core-lane={lane}" if lane is not None else ""
    print(
        f"python-test-shard: running shard={args.shard}{lane_text} "
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
