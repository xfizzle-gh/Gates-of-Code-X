from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .acceptance import backup_existing_files, restore_backup, write_acceptance_report
from .first_engine_test import DEFAULT_INSTALL_NAME, DEFAULT_TEST_MAP, run_first_engine_test
from .map_discovery import discover_maps
from .modstack import resolve_stack
from .profiles import discover_profile_locations
from .stack_acceptance import (
    prepare_stack_handoff,
    validate_mod_stack,
    verify_stack_result,
)


def _add_stack_arguments(parser: argparse.ArgumentParser, *, require_codex: bool = True) -> None:
    parser.add_argument("--codex", required=require_codex, help="Primary Code:X mod directory")
    parser.add_argument(
        "--stack",
        action="append",
        default=[],
        help="Ordered mod/resource layer, low to high priority. Repeat for every layer.",
    )
    parser.add_argument("--stack-config", help="JSON file containing an ordered layers array")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gates-of-codex-live",
        description="Validate and safely hand Gates of CodeX battles to an installed GoH mod stack.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    maps = sub.add_parser("maps", help="Discover playable tactical map roots")
    maps.add_argument("--game", required=True)
    _add_stack_arguments(maps)
    maps.add_argument("--contains")

    profiles = sub.add_parser("profiles", help="Discover GoH profile roots and likely save directories")
    profiles.add_argument(
        "--search-root",
        action="append",
        default=[],
        help="Optional bounded directory to search. Repeat for additional roots.",
    )
    profiles.add_argument("--max-depth", type=int, default=6)
    profiles.add_argument("--output")

    validate = sub.add_parser("validate", help="Validate the installed game and ordered Code:X stack")
    validate.add_argument("--game", required=True)
    _add_stack_arguments(validate)
    validate.add_argument("--profile")
    validate.add_argument("--output")

    first_test = sub.add_parser(
        "first-test",
        help="Create, install, and optionally launch a fresh NATO-versus-Russia engine test",
    )
    first_test.add_argument("--game", required=True)
    _add_stack_arguments(first_test)
    first_test.add_argument("--profile", required=True, help="Selected GoH profile directory")
    first_test.add_argument(
        "--install-directory",
        required=True,
        help="Campaign/save directory inside the selected profile",
    )
    first_test.add_argument("--map", default=DEFAULT_TEST_MAP)
    first_test.add_argument("--install-name", default=DEFAULT_INSTALL_NAME)
    first_test.add_argument("--work-root", default="live")
    first_test.add_argument("--backup-root", default="backups")
    first_test.add_argument("--output")
    first_test.add_argument("--launch", action="store_true")

    backup = sub.add_parser("backup", help="Back up existing campaign and tactical files")
    backup.add_argument("paths", nargs="+")
    backup.add_argument("--backup-root")
    backup.add_argument("--label", default="manual")

    restore = sub.add_parser("restore", help="Restore files from a Gates of CodeX backup")
    restore.add_argument("backup")

    handoff = sub.add_parser("handoff", help="Validate, back up, export, optionally install, and launch")
    handoff.add_argument("campaign")
    handoff.add_argument("--game", required=True)
    _add_stack_arguments(handoff)
    handoff.add_argument("--save", required=True)
    handoff.add_argument("--map", required=True)
    handoff.add_argument("--profile")
    handoff.add_argument("--install-save")
    handoff.add_argument("--backup-root")
    handoff.add_argument("--launch", action="store_true")

    verify = sub.add_parser("verify", help="Verify that GoH completed and rewrote the tactical save")
    verify.add_argument("campaign")
    verify.add_argument("--save", required=True)
    _add_stack_arguments(verify, require_codex=False)
    verify.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "maps":
        stack = resolve_stack(args.stack, config=args.stack_config, fallback=args.codex)
        values = discover_maps(*stack)
        if args.contains:
            needle = args.contains.lower()
            values = [value for value in values if needle in value.identifier.lower()]
        print(json.dumps([asdict(value) for value in values], indent=2))
        return 0 if values else 1
    if args.command == "profiles":
        roots = args.search_root or None
        values = discover_profile_locations(roots, max_depth=max(1, args.max_depth))
        payload = [value.to_dict() for value in values]
        if args.output:
            with open(args.output, "w", encoding="utf-8") as destination:
                json.dump(payload, destination, indent=2)
                destination.write("\n")
        print(json.dumps(payload, indent=2))
        return 0 if values else 1
    if args.command == "validate":
        report = validate_mod_stack(
            args.game,
            args.codex,
            resource_stack=args.stack,
            stack_config=args.stack_config,
            profile_directory=args.profile,
        )
        payload = report.to_dict()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as destination:
                json.dump(payload, destination, indent=2)
                destination.write("\n")
        print(json.dumps(payload, indent=2))
        return 0 if report.ok else 1
    if args.command == "first-test":
        result = run_first_engine_test(
            game_directory=args.game,
            code_x_directory=args.codex,
            profile_directory=args.profile,
            install_directory=args.install_directory,
            resource_stack=args.stack,
            stack_config=args.stack_config,
            work_root=args.work_root,
            map_name=args.map,
            install_name=args.install_name,
            backup_root=args.backup_root,
            launch=args.launch,
        )
        payload = result.to_dict()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as destination:
                json.dump(payload, destination, indent=2)
                destination.write("\n")
        print(json.dumps(payload, indent=2))
        return 0
    if args.command == "backup":
        record = backup_existing_files(args.paths, backup_root=args.backup_root, label=args.label)
        print(json.dumps(asdict(record), indent=2))
        return 0
    if args.command == "restore":
        restored = restore_backup(args.backup)
        print(json.dumps([str(value) for value in restored], indent=2))
        return 0
    if args.command == "handoff":
        result = prepare_stack_handoff(
            args.campaign,
            game_directory=args.game,
            code_x_directory=args.codex,
            resource_stack=args.stack,
            stack_config=args.stack_config,
            save_path=args.save,
            map_name=args.map,
            profile_directory=args.profile,
            install_save_path=args.install_save,
            backup_root=args.backup_root,
            launch=args.launch,
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    if args.command == "verify":
        report = verify_stack_result(
            args.campaign,
            save_path=args.save,
            code_x_directory=args.codex,
            resource_stack=args.stack,
            stack_config=args.stack_config,
        )
        if args.output:
            write_acceptance_report(report, args.output)
        print(json.dumps(asdict(report), indent=2))
        return 0 if report.ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
