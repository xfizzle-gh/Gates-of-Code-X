from __future__ import annotations

import argparse
import json
import sys

from . import cli
from .doctor import diagnose


def _doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex doctor")
    parser.add_argument("--game")
    parser.add_argument("--codex")
    parser.add_argument("--profile")
    return parser


def _run_doctor(arguments: list[str]) -> int:
    args = _doctor_parser().parse_args(arguments)
    report = diagnose(
        code_x_directory=args.codex,
        game_directory=args.game,
        profile_directory=args.profile,
    )
    print(json.dumps({
        "ok": report.ok,
        "games": [str(path) for path in report.game_directories],
        "codex": [str(path) for path in report.code_x_directories],
        "profiles": [str(path) for path in report.profile_directories],
        "units": report.unit_counts,
        "errors": report.errors,
    }, indent=2))
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "doctor":
        return _run_doctor(arguments[1:])
    return cli.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
