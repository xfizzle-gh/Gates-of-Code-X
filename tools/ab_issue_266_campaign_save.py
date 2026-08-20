#!/usr/bin/env python3
"""Owner-size A/B for #266 Slice 4 campaign save.

Compares compact-save timings at two git SHAs on a disposable campaign copy.
Does not invent numbers. Exits 2 if the campaign path is missing.

Required owner-machine usage (never point this at the live owner campaign):

    python tools/ab_issue_266_campaign_save.py \\
        --campaign /path/to/disposable/ww3_2028_core/campaign.json \\
        --base 5abed005ce6574813efc42e8a30a31ec13e32eca \\
        --head HEAD

Reports save_ms, save_validate_ms, save_validate_base_ms, save_encode_ms,
and save_write_ms. This VM does not ship ww3_2028_core; leave the table empty
until the owner runs the harness on a disposable copy.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


BASE_SHA = "5abed005ce6574813efc42e8a30a31ec13e32eca"
METRIC_KEYS = (
    "save_ms",
    "save_validate_ms",
    "save_validate_base_ms",
    "save_encode_ms",
    "save_write_ms",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _ensure_src_path(src_root: Path | None) -> None:
    candidate = str((src_root or (_repo_root() / "src")).resolve())
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _install_runtime() -> None:
    from gates_of_codex import command_cycle_perf, command_scoped_p2_auth
    from gates_of_codex.turn_cycle import install_frontend_turn_cycle_op

    command_cycle_perf.install_command_cycle_perf_path()
    command_scoped_p2_auth.install_command_scoped_p2_auth()
    install_frontend_turn_cycle_op()


def _sample_compact_save(campaign_path: Path, repeats: int) -> dict[str, Any]:
    from gates_of_codex.command_cycle_perf import _compact_save_campaign
    from gates_of_codex.state_io import load_campaign

    state = load_campaign(campaign_path)
    with tempfile.TemporaryDirectory() as temporary:
        destination = Path(temporary) / "campaign.json"
        shutil.copy2(campaign_path, destination)
        _compact_save_campaign(state, destination, subphase_seconds={})
        samples: list[dict[str, float]] = []
        for _ in range(repeats):
            subphase: dict[str, float] = {}
            started = time.perf_counter()
            _compact_save_campaign(state, destination, subphase_seconds=subphase)
            samples.append(
                {
                    "save_ms": (time.perf_counter() - started) * 1000.0,
                    "save_validate_ms": float(subphase.get("validate", 0.0)) * 1000.0,
                    "save_validate_base_ms": float(subphase.get("validate_base", 0.0))
                    * 1000.0,
                    "save_encode_ms": float(subphase.get("encode", 0.0)) * 1000.0,
                    "save_write_ms": float(subphase.get("write", 0.0)) * 1000.0,
                }
            )
    return {
        "repeats": repeats,
        "samples": samples,
        "min": {key: min(row[key] for row in samples) for key in METRIC_KEYS},
        "median": {
            key: statistics.median(row[key] for row in samples) for key in METRIC_KEYS
        },
    }


def measure_current(
    campaign_path: Path,
    *,
    label: str,
    sha: str,
    repeats: int,
    src_root: Path | None = None,
) -> dict[str, Any]:
    _ensure_src_path(src_root)
    _install_runtime()
    payload = _sample_compact_save(campaign_path, repeats)
    payload.update(
        {
            "label": label,
            "sha": sha,
            "campaign": str(campaign_path),
            "campaign_bytes": campaign_path.stat().st_size,
        }
    )
    return payload


def _resolve_sha(repo: Path, spec: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", spec],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _measure_at_sha(
    *,
    repo: Path,
    sha: str,
    label: str,
    campaign_path: Path,
    repeats: int,
) -> dict[str, Any]:
    resolved = _resolve_sha(repo, sha)
    with tempfile.TemporaryDirectory(prefix="goc-266-ab-") as temporary:
        worktree = Path(temporary) / "worktree"
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "worktree",
                "add",
                "--detach",
                str(worktree),
                resolved,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(worktree / "src")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--measure",
                    "--campaign",
                    str(campaign_path),
                    "--label",
                    label,
                    "--sha",
                    resolved,
                    "--repeats",
                    str(repeats),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
        finally:
            subprocess.run(
                ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
                check=False,
                capture_output=True,
                text=True,
            )
    if completed.returncode != 0:
        raise SystemExit(
            f"measure at {resolved} failed ({completed.returncode}):\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def _print_table(rows: list[dict[str, Any]]) -> None:
    headers = ["label", "sha", *METRIC_KEYS]
    print("| " + " | ".join(headers) + " |")
    print("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        values = [row["label"], row["sha"][:12]]
        mins = row["min"]
        for key in METRIC_KEYS:
            values.append(f"{mins[key]:.1f}")
        print("| " + " | ".join(values) + " |")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign",
        type=Path,
        default=os.environ.get("GOC_OWNER_CAMPAIGN"),
        help="Disposable owner campaign.json. Also reads GOC_OWNER_CAMPAIGN.",
    )
    parser.add_argument("--base", default=BASE_SHA)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--label", default="current")
    parser.add_argument("--sha", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.campaign is None:
        print(
            "owner campaign missing: pass --campaign or GOC_OWNER_CAMPAIGN. "
            "ww3_2028_core is not in this repository; this harness does not "
            "invent owner timings.",
            file=sys.stderr,
        )
        return 2
    campaign_path = Path(args.campaign).expanduser().resolve()
    if not campaign_path.is_file():
        print(f"owner campaign missing: {campaign_path}", file=sys.stderr)
        return 2

    repo = _repo_root()
    if args.measure:
        sha = args.sha or _resolve_sha(repo, "HEAD")
        report = measure_current(
            campaign_path,
            label=args.label,
            sha=sha,
            repeats=args.repeats,
        )
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            _print_table([report])
        return 0

    reports = [
        _measure_at_sha(
            repo=repo,
            sha=args.base,
            label="base",
            campaign_path=campaign_path,
            repeats=args.repeats,
        ),
        _measure_at_sha(
            repo=repo,
            sha=args.head,
            label="head",
            campaign_path=campaign_path,
            repeats=args.repeats,
        ),
    ]
    print(json.dumps({"reports": reports}, indent=2, sort_keys=True))
    print()
    _print_table(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
