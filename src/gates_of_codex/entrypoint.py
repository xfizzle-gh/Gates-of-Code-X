from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import cli
from .codex.catalog import CodeXCatalogScanner
from .doctor import diagnose
from .economy import initialize_economy
from .goe_source_audit import write_goe_source_audit
from .models import Faction
from .modstack import resolve_stack, stack_to_strings
from .scenario import load_bundled_scenario
from .service import GatesOfCodeXService
from .stack_acceptance import validate_mod_stack
from .starter import populate_starter_rosters, set_player_faction
from .state_io import save_campaign
from .strategic import evaluate_campaign_outcome


FACTION_CHOICES = ["nato", "ukr", "rusa", "prc"]


def _add_stack_arguments(parser: argparse.ArgumentParser, *, require_codex: bool = True) -> None:
    parser.add_argument("--codex", required=require_codex)
    parser.add_argument("--stack", action="append", default=[])
    parser.add_argument("--stack-config")


def _doctor_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex doctor")
    parser.add_argument("--game")
    _add_stack_arguments(parser, require_codex=False)
    parser.add_argument("--profile")
    return parser


def _run_doctor(arguments: list[str]) -> int:
    args = _doctor_parser().parse_args(arguments)
    if args.stack or args.stack_config:
        if not args.game or not args.codex:
            raise SystemExit("doctor with --stack or --stack-config requires --game and --codex")
        report = validate_mod_stack(
            args.game,
            args.codex,
            resource_stack=args.stack,
            stack_config=args.stack_config,
            profile_directory=args.profile,
        )
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ok else 1
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


def _run_scan(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gates-of-codex scan")
    _add_stack_arguments(parser)
    parser.add_argument("--output")
    args = parser.parse_args(arguments)
    stack = resolve_stack(args.stack, config=args.stack_config, fallback=args.codex)
    catalog = CodeXCatalogScanner().scan_stack(stack)
    if args.output:
        catalog.save(args.output)
    print(json.dumps({
        "resource_stack": catalog.resource_stack,
        "signature": catalog.signature,
        "units": {faction: len(catalog.by_faction(faction)) for faction in FACTION_CHOICES},
    }, indent=2))
    return 0


def _run_audit_goe_provinces(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gates-of-codex audit-goe-provinces")
    parser.add_argument("--output", default="docs/audits/goe-province-detailed.json")
    parser.add_argument("--summary", default="docs/audits/goe-province-detailed.md")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="omit the 517 per-province mapping rows from JSON output",
    )
    args = parser.parse_args(arguments)
    payload = write_goe_source_audit(
        args.output,
        args.summary,
        include_mappings=not args.summary_only,
    )
    coverage = payload["mapping_coverage"]
    print(json.dumps({
        "ok": True,
        "output": str(Path(args.output)),
        "summary": str(Path(args.summary)),
        "province_count": payload["province_count"],
        "unique_rgb_count": payload["source_inventory"]["marker_id_database"]["unique_rgb_count"],
        "mapped_graph_records": coverage["mapped_graph_records"],
        "unmapped_graph_records": coverage["unmapped_graph_records"],
    }, indent=2))
    return 0


def _run_new(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gates-of-codex new")
    _add_stack_arguments(parser)
    parser.add_argument("--output", default="campaign.json")
    parser.add_argument("--faction", choices=FACTION_CHOICES, default="nato")
    parser.add_argument("--game", help="GoH install directory persisted on the campaign")
    parser.add_argument("--profile", help="GoH profile directory persisted on the campaign")
    parser.add_argument("--map", help="Preferred tactical map id persisted on the campaign")
    parser.add_argument(
        "--install-directory",
        help="Profile campaign folder for Conquest installs (defaults to <profile>/campaign)",
    )
    args = parser.parse_args(arguments)
    stack = resolve_stack(args.stack, config=args.stack_config, fallback=args.codex)
    catalog = CodeXCatalogScanner().scan_stack(stack)
    state = load_bundled_scenario()
    state.code_x_directory = str(Path(args.codex).resolve())
    state.map_metadata["resource_stack"] = stack_to_strings(stack)
    if args.game:
        state.game_directory = str(Path(args.game).expanduser().resolve())
    if args.profile:
        state.profile_directory = str(Path(args.profile).expanduser().resolve())
    if args.map:
        state.map_metadata["preferred_map"] = args.map
    if args.install_directory:
        state.map_metadata["install_directory"] = str(Path(args.install_directory).expanduser().resolve())
    elif args.profile:
        campaign_dir = Path(args.profile).expanduser().resolve() / "campaign"
        if campaign_dir.is_dir():
            state.map_metadata["install_directory"] = str(campaign_dir)
    if args.stack_config:
        state.map_metadata["stack_config"] = str(Path(args.stack_config).expanduser().resolve())
    set_player_faction(state, Faction(args.faction))
    populate_starter_rosters(state, catalog)
    initialize_economy(state, catalog)
    evaluate_campaign_outcome(state)
    save_campaign(state, args.output)
    print(args.output)
    return 0


def _run_export(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="gates-of-codex export-battle")
    parser.add_argument("campaign")
    _add_stack_arguments(parser)
    parser.add_argument("--save", required=True)
    parser.add_argument("--map", required=True)
    args = parser.parse_args(arguments)
    stack = resolve_stack(args.stack, config=args.stack_config, fallback=args.codex)
    manifest = GatesOfCodeXService().export_battle(
        args.campaign,
        code_x_directory=args.codex,
        resource_stack=stack,
        save_path=args.save,
        map_name=args.map,
    )
    print(json.dumps(asdict(manifest), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return cli.main(arguments)
    command, remainder = arguments[0], arguments[1:]
    if command == "doctor":
        return _run_doctor(remainder)
    if command == "scan":
        return _run_scan(remainder)
    if command == "audit-goe-provinces":
        return _run_audit_goe_provinces(remainder)
    if command == "new":
        return _run_new(remainder)
    if command == "export-battle":
        return _run_export(remainder)
    return cli.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
