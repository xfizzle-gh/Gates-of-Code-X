#!/usr/bin/env python3
"""Deterministic, GUI-free OpenGS-derived generator for Gates Gate 1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from gate1_common import AUTHORITATIVE_OUTPUTS, Gate1Error, SeedLedger, canonical_json_bytes, load_recipe
from gate1_pipeline import benchmark, compare_runs, generate, inspect_output


def print_json(value: object) -> None:
    sys.stdout.buffer.write(canonical_json_bytes(value))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-recipe")
    validate.add_argument("recipe", type=Path)
    generate_cmd = sub.add_parser("generate")
    generate_cmd.add_argument("recipe", type=Path)
    generate_cmd.add_argument("--output", type=Path, required=True)
    inspect = sub.add_parser("inspect-output")
    inspect.add_argument("output", type=Path)
    compare = sub.add_parser("compare-runs")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    bench = sub.add_parser("benchmark")
    bench.add_argument("recipe", type=Path)
    bench.add_argument("--output", type=Path, required=True)
    bench.add_argument("--repetitions", type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-recipe":
            recipe, inputs = load_recipe(args.recipe)
            print_json({"ok": True, "recipe_id": recipe["recipe_id"], "inputs": {k: v.sha256 for k, v in sorted(inputs.items())}})
        elif args.command == "generate":
            print_json(generate(args.recipe, args.output))
        elif args.command == "inspect-output":
            print_json(inspect_output(args.output))
        elif args.command == "compare-runs":
            result = compare_runs(args.left, args.right)
            print_json(result)
            if not result["identical"]:
                return 2
        elif args.command == "benchmark":
            result = benchmark(args.recipe, args.output, args.repetitions)
            print_json(result)
            if not result["all_identical"]:
                return 2
        return 0
    except Gate1Error as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
