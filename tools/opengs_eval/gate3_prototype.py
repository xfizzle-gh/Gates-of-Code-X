#!/usr/bin/env python3
"""Build and inspect the isolated OpenGS Gate 3 prototype."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from gate3_package import *


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config")
    validate.add_argument("config", type=Path)
    build = sub.add_parser("build-inputs")
    build.add_argument("config", type=Path)
    build.add_argument("--natural-earth-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("config", type=Path)
    run.add_argument("--natural-earth-root", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    inspect = sub.add_parser("inspect-output")
    inspect.add_argument("output", type=Path)
    compare = sub.add_parser("compare-runs")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-config":
            config, digest, _raw = load_config(args.config)
            result = {"ok": True, "candidate_id": config["candidate_id"], "sha256": digest}
        elif args.command == "build-inputs":
            result = build_inputs(args.config, args.natural_earth_root, args.output)
        elif args.command == "run":
            result = run_pipeline(args.config, args.natural_earth_root, args.output)
        elif args.command == "inspect-output":
            result = inspect_package(args.output)
        else:
            result = compare_packages(args.left, args.right)
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except Gate3Error as exc:
        print(f"Gate 3 error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
