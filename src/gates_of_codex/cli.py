from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .campaign import CampaignEngine
from .codex.catalog import CodeXCatalogScanner
from .doctor import diagnose
from .frontend import write_frontend_snapshot
from .launcher import launch_game
from .models import Faction
from .scenario import load_bundled_scenario
from .service import GatesOfCodeXService
from .starter import populate_starter_rosters, set_player_faction
from .state_io import load_campaign, save_campaign


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--codex")
    scan = sub.add_parser("scan")
    scan.add_argument("--codex", required=True)
    scan.add_argument("--output")
    new = sub.add_parser("new")
    new.add_argument("--codex", required=True)
    new.add_argument("--output", default="campaign.json")
    new.add_argument("--faction", choices=["nato", "ukr", "rusa", "prc"], default="nato")
    show = sub.add_parser("show")
    show.add_argument("campaign")
    move = sub.add_parser("move")
    move.add_argument("campaign")
    move.add_argument("battalion")
    move.add_argument("province")
    auto = sub.add_parser("auto-resolve")
    auto.add_argument("campaign")
    end = sub.add_parser("end-turn")
    end.add_argument("campaign")
    export = sub.add_parser("export-battle")
    export.add_argument("campaign")
    export.add_argument("--codex", required=True)
    export.add_argument("--save", required=True)
    export.add_argument("--map", required=True)
    import_battle = sub.add_parser("import-battle")
    import_battle.add_argument("campaign")
    import_battle.add_argument("--save", required=True)
    frontend = sub.add_parser("export-frontend")
    frontend.add_argument("campaign")
    frontend.add_argument("--output", default="godot/campaign_snapshot.json")
    launch = sub.add_parser("launch")
    launch.add_argument("--game", required=True)
    ui = sub.add_parser("ui")
    ui.add_argument("campaign", nargs="?")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        report = diagnose(args.codex)
        print(json.dumps({
            "ok": report.ok,
            "games": [str(path) for path in report.game_directories],
            "codex": [str(path) for path in report.code_x_directories],
            "profiles": [str(path) for path in report.profile_directories],
            "units": report.unit_counts,
            "errors": report.errors,
        }, indent=2))
        return 0 if report.ok else 1
    if args.command == "scan":
        catalog = CodeXCatalogScanner().scan(args.codex)
        if args.output:
            catalog.save(args.output)
        print(json.dumps({faction: len(catalog.by_faction(faction)) for faction in ("nato", "ukr", "rusa", "prc")}, indent=2))
        return 0
    if args.command == "new":
        state = load_bundled_scenario()
        state.code_x_directory = str(Path(args.codex).resolve())
        set_player_faction(state, Faction(args.faction))
        populate_starter_rosters(state, CodeXCatalogScanner().scan(args.codex))
        save_campaign(state, args.output)
        print(args.output)
        return 0
    if args.command == "show":
        print(json.dumps(load_campaign(args.campaign).to_dict(), indent=2))
        return 0
    if args.command == "move":
        state = load_campaign(args.campaign)
        result = CampaignEngine(state).move_or_attack(args.battalion, args.province)
        save_campaign(state, args.campaign)
        print("battle created" if result.pending_battle else "moved")
        return 0
    if args.command == "auto-resolve":
        state = load_campaign(args.campaign)
        winner = CampaignEngine(state).auto_resolve_pending_battle()
        save_campaign(state, args.campaign)
        print(winner.value)
        return 0
    if args.command == "end-turn":
        state = load_campaign(args.campaign)
        next_faction = CampaignEngine(state).end_turn()
        save_campaign(state, args.campaign)
        print(next_faction.value)
        return 0
    if args.command == "export-battle":
        manifest = GatesOfCodeXService().export_battle(
            args.campaign, code_x_directory=args.codex, save_path=args.save, map_name=args.map
        )
        print(json.dumps(asdict(manifest), indent=2))
        return 0
    if args.command == "import-battle":
        result = GatesOfCodeXService().import_battle(args.campaign, save_path=args.save)
        print(json.dumps({"winner": result.winner.value, "survivors": result.survivor_counts}, indent=2))
        return 0
    if args.command == "export-frontend":
        output = write_frontend_snapshot(load_campaign(args.campaign), args.output)
        print(output)
        return 0
    if args.command == "launch":
        launch_game(args.game)
        return 0
    if args.command == "ui":
        from .gui import main as gui_main
        gui_main(args.campaign)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
