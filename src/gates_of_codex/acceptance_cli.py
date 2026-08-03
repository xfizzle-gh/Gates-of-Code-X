from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .acceptance import (
    backup_existing_files,
    discover_maps,
    prepare_tactical_handoff,
    restore_backup,
    validate_live_installation,
    verify_tactical_result,
    write_acceptance_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gates-of-codex-live",
        description="Validate and safely hand Gates of CodeX battles to an installed GoH and Code:X setup.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    maps = sub.add_parser("maps", help="Discover valid tactical map identifiers")
    maps.add_argument("--game", required=True)
    maps.add_argument("--codex", required=True)
    maps.add_argument("--contains")

    validate = sub.add_parser("validate", help="Validate the installed game and Code:X data")
    validate.add_argument("--game", required=True)
    validate.add_argument("--codex", required=True)
    validate.add_argument("--profile")
    validate.add_argument("--output")

    backup = sub.add_parser("backup", help="Back up existing campaign and tactical files")
    backup.add_argument("paths", nargs="+")
    backup.add_argument("--backup-root")
    backup.add_argument("--label", default="manual")

    restore = sub.add_parser("restore", help="Restore files from a Gates of CodeX backup")
    restore.add_argument("backup")

    handoff = sub.add_parser("handoff", help="Validate, back up, export, optionally install, and launch")
    handoff.add_argument("campaign")
    handoff.add_argument("--game", required=True)
    handoff.add_argument("--codex", required=True)
    handoff.add_argument("--save", required=True)
    handoff.add_argument("--map", required=True)
    handoff.add_argument("--profile")
    handoff.add_argument("--install-save")
    handoff.add_argument("--backup-root")
    handoff.add_argument("--launch", action="store_true")

    verify = sub.add_parser("verify", help="Verify that GoH completed and rewrote the tactical save")
    verify.add_argument("campaign")
    verify.add_argument("--save", required=True)
    verify.add_argument("--codex")
    verify.add_argument("--output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "maps":
        values = discover_maps(args.game, args.codex)
        if args.contains:
            needle = args.contains.lower()
            values = [value for value in values if needle in value.identifier.lower()]
        print(json.dumps([asdict(value) for value in values], indent=2))
        return 0 if values else 1
    if args.command == "validate":
        report = validate_live_installation(args.game, args.codex, args.profile)
        payload = report.to_dict()
        if args.output:
            with open(args.output, "w", encoding="utf-8") as destination:
                json.dump(payload, destination, indent=2)
                destination.write("\n")
        print(json.dumps(payload, indent=2))
        return 0 if report.ok else 1
    if args.command == "backup":
        record = backup_existing_files(args.paths, backup_root=args.backup_root, label=args.label)
        print(json.dumps(asdict(record), indent=2))
        return 0
    if args.command == "restore":
        restored = restore_backup(args.backup)
        print(json.dumps([str(value) for value in restored], indent=2))
        return 0
    if args.command == "handoff":
        result = prepare_tactical_handoff(
            args.campaign,
            game_directory=args.game,
            code_x_directory=args.codex,
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
        report = verify_tactical_result(
            args.campaign,
            save_path=args.save,
            code_x_directory=args.codex,
        )
        if args.output:
            write_acceptance_report(report, args.output)
        print(json.dumps(asdict(report), indent=2))
        return 0 if report.ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
