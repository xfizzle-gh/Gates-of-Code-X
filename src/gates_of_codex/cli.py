from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .campaign import CampaignEngine
from .codex.catalog import CodeXCatalogScanner
from .doctor import diagnose
from .economy import (
    assign_reinforcements,
    available_research,
    formation_recruitment_offers,
    initialize_economy,
    purchase_reinforcements,
    purchase_research,
    repair_formation,
)
from .frontend import write_frontend_snapshot
from .frontend_commands import apply_frontend_commands, default_commands_path
from .launcher import launch_game
from .models import Faction
from .scenario import DEFAULT_SCENARIO_ID, build_scenario, get_scenario
from .service import GatesOfCodeXService
from .starter import populate_starter_rosters, set_player_faction
from .state_io import load_campaign, save_campaign
from .strategic import (
    BUILDING_RULES,
    build_infrastructure,
    construction_options,
    evaluate_campaign_outcome,
    update_operational_objectives,
)
from .strategic_ai import StrategicAI
from .play_context import list_front_options
from .supply import refresh_supply_for_faction, supply_status_for_faction


FACTION_CHOICES = ["nato", "ukr", "rusa", "prc"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--codex")
    scan = sub.add_parser("scan")
    scan.add_argument("--codex", required=True)
    scan.add_argument("--output")
    new = sub.add_parser("new")
    new.add_argument("campaign", nargs="?")
    new.add_argument("--codex")
    new.add_argument("--output")
    new.add_argument("--scenario", default=DEFAULT_SCENARIO_ID)
    new.add_argument(
        "--stack-config",
        help="Validated active-stack config required to materialize Earth3 P2 rosters",
    )
    new.add_argument("--faction", choices=FACTION_CHOICES, default="nato")
    new.add_argument("--fog-of-war", choices=["on", "off"], default="off")
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
    supply = sub.add_parser("supply-status")
    supply.add_argument("campaign")
    supply.add_argument("--faction", choices=FACTION_CHOICES)
    supply.add_argument("--refresh", action="store_true")
    ai = sub.add_parser("run-ai-turn")
    ai.add_argument("campaign")
    ai.add_argument("--faction", choices=FACTION_CHOICES, required=True)
    ai.add_argument("--seed", type=int, default=0)
    ai.add_argument("--advance-turn", action="store_true")
    economy = sub.add_parser("economy-status")
    economy.add_argument("campaign")
    economy.add_argument("--faction", choices=FACTION_CHOICES)
    research_status = sub.add_parser("research-status")
    research_status.add_argument("campaign")
    research_status.add_argument("--faction", choices=FACTION_CHOICES, required=True)
    research = sub.add_parser("research")
    research.add_argument("campaign")
    research.add_argument("--faction", choices=FACTION_CHOICES, required=True)
    research.add_argument("--key", required=True)
    recruits = sub.add_parser("list-recruits")
    recruits.add_argument("campaign")
    recruits.add_argument("--formation", required=True)
    recruits.add_argument("--contains", help="Only show unit names containing this text")
    recruits.add_argument("--limit", type=int, default=0, help="Max rows to print (0 = all)")
    recruit = sub.add_parser("recruit")
    recruit.add_argument("campaign")
    recruit.add_argument("--formation", required=True)
    recruit.add_argument("--unit", required=True)
    recruit.add_argument("--quantity", type=int, default=1)
    assign = sub.add_parser("assign-reinforcements")
    assign.add_argument("campaign")
    assign.add_argument("--formation", required=True)
    assign.add_argument("--unit", required=True)
    assign.add_argument("--quantity", type=int, default=1)
    repair = sub.add_parser("repair")
    repair.add_argument("campaign")
    repair.add_argument("--formation", required=True)
    repair.add_argument("--points", type=int)
    construction_status = sub.add_parser("construction-status")
    construction_status.add_argument("campaign")
    construction_status.add_argument("province")
    construction_status.add_argument("--faction", choices=FACTION_CHOICES)
    construct = sub.add_parser("construct")
    construct.add_argument("campaign")
    construct.add_argument("province")
    construct.add_argument("building", choices=sorted(BUILDING_RULES))
    construct.add_argument("--faction", choices=FACTION_CHOICES)
    objectives = sub.add_parser("objectives")
    objectives.add_argument("campaign")
    campaign_status = sub.add_parser("campaign-status")
    campaign_status.add_argument("campaign")
    front = sub.add_parser("front", help="List legal moves and attacks for the current faction")
    front.add_argument("campaign")
    front.add_argument("--faction", choices=FACTION_CHOICES)
    front.add_argument("--kind", choices=["battle", "capture", "neutral", "move"])
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
    apply_frontend = sub.add_parser(
        "apply-frontend",
        help="Apply Godot frontend command queue and refresh the snapshot",
    )
    apply_frontend.add_argument("campaign")
    apply_frontend.add_argument("--snapshot", default="godot/campaign_snapshot.json")
    apply_frontend.add_argument("--commands", help="Defaults to <snapshot-dir>/frontend_commands.json")
    play = sub.add_parser(
        "play",
        help="Launch or continue a playable campaign in the Godot strategic application",
        add_help=False,
    )
    play.add_argument("play_args", nargs=argparse.REMAINDER)
    launch = sub.add_parser("launch")
    launch.add_argument("--game", required=True)
    ui = sub.add_parser("ui")
    ui.add_argument("campaign", nargs="?")
    return parser


def _new_campaign_output(args) -> str:
    positional = str(args.campaign).strip() if args.campaign else ""
    flagged = str(args.output).strip() if args.output else ""
    if positional and flagged and Path(positional) != Path(flagged):
        raise ValueError(
            "new campaign output was provided both positionally and with --output"
        )
    return flagged or positional or "campaign.json"


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
        print(json.dumps({faction: len(catalog.by_faction(faction)) for faction in FACTION_CHOICES}, indent=2))
        return 0
    if args.command == "new":
        definition = get_scenario(args.scenario)
        output = _new_campaign_output(args)
        if definition.status == "legacy" and not args.codex:
            raise ValueError(
                f"--codex is required when creating legacy scenario {definition.scenario_id}"
            )
        builder_options = (
            {"stack_config": args.stack_config}
            if definition.scenario_id == DEFAULT_SCENARIO_ID
            else {}
        )
        state = build_scenario(args.scenario, **builder_options)
        if (
            definition.scenario_id == DEFAULT_SCENARIO_ID
            and args.faction != Faction.NATO.value
        ):
            raise ValueError(
                "Earth3 P2 human seat is fixed to the usa actor on the NATO tactical side"
            )
        if args.codex:
            state.code_x_directory = str(Path(args.codex).resolve())
        set_player_faction(state, Faction(args.faction))
        state.fog_of_war_enabled = args.fog_of_war == "on"
        if definition.status == "legacy":
            catalog = CodeXCatalogScanner().scan(args.codex)
            populate_starter_rosters(state, catalog)
            initialize_economy(state, catalog)
            evaluate_campaign_outcome(state)
        save_campaign(state, output)
        print(output)
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
        engine = CampaignEngine(state)
        winner = engine.auto_resolve_pending_battle()
        save_campaign(
            state,
            args.campaign,
            observation_context=engine.observation_context,
        )
        print(winner.value)
        return 0
    if args.command == "end-turn":
        state = load_campaign(args.campaign)
        next_faction = CampaignEngine(state).end_turn()
        save_campaign(state, args.campaign)
        print(next_faction.value)
        return 0
    if args.command == "supply-status":
        state = load_campaign(args.campaign)
        factions = [Faction(args.faction)] if args.faction else [
            faction for faction in CampaignEngine.TURN_ORDER if faction.value in state.factions
        ]
        payload = []
        for faction in factions:
            if args.refresh:
                report = refresh_supply_for_faction(state, faction)
            else:
                report = supply_status_for_faction(state, faction)
            row = asdict(report)
            battalions = sorted(
                (
                    value
                    for value in state.battalions.values()
                    if value.faction == faction
                ),
                key=lambda value: value.battalion_id,
            )
            row["supply"] = {
                value.battalion_id: value.supply for value in battalions
            }
            row["encircled_turns"] = {
                value.battalion_id: value.encircled_turns
                for value in battalions
            }
            payload.append(row)
        if args.refresh:
            save_campaign(state, args.campaign)
        print(json.dumps(payload, indent=2))
        return 0
    if args.command == "run-ai-turn":
        state = load_campaign(args.campaign)
        faction = Faction(args.faction)
        ai = StrategicAI(state, random_seed=args.seed)
        actions = ai.take_turn(faction)
        next_faction = None
        if args.advance_turn:
            if state.current_faction != faction:
                raise ValueError(
                    f"Cannot advance {faction.value}; current faction is {state.current_faction.value}"
                )
            next_faction = CampaignEngine(state).end_turn().value
        save_campaign(
            state,
            args.campaign,
            observation_context=ai.observation_context,
        )
        print(json.dumps({
            "faction": faction.value,
            "actions": [asdict(action) for action in actions],
            "next_faction": next_faction,
        }, indent=2))
        return 0
    if args.command == "economy-status":
        state = load_campaign(args.campaign)
        selected = [args.faction] if args.faction else sorted(state.factions)
        payload = []
        for faction_id in selected:
            faction_state = state.factions[faction_id]
            battalions = [value for value in state.battalions.values() if value.faction.value == faction_id]
            payload.append({
                "faction": faction_id,
                "resources": faction_state.resources,
                "income_last_round": faction_state.income_last_round,
                "maintenance_last_round": faction_state.maintenance_last_round,
                "researched": len(faction_state.researched_keys),
                "reinforcement_pool": [asdict(entry) for entry in faction_state.reinforcement_pool],
                "formations": [
                    {
                        "formation_id": value.formation_id,
                        "unit_count": value.unit_count,
                        "authorized_unit_count": value.authorized_unit_count,
                        "replacement_deficit": value.replacement_deficit,
                        "condition": value.condition,
                    }
                    for value in sorted(battalions, key=lambda item: item.formation_id)
                ],
            })
        print(json.dumps(payload, indent=2))
        return 0
    if args.command == "research-status":
        state = load_campaign(args.campaign)
        faction = Faction(args.faction)
        faction_state = state.factions[faction.value]
        print(json.dumps({
            "faction": faction.value,
            "resources": faction_state.resources,
            "completed": sorted(faction_state.researched_keys),
            "available": [asdict(node) for node in available_research(state, faction)],
        }, indent=2))
        return 0
    if args.command == "research":
        state = load_campaign(args.campaign)
        result = purchase_research(state, Faction(args.faction), args.key)
        save_campaign(state, args.campaign)
        print(json.dumps(asdict(result), indent=2))
        return 0
    if args.command == "list-recruits":
        state = load_campaign(args.campaign)
        offers = [asdict(offer) for offer in formation_recruitment_offers(state, args.formation)]
        if args.contains:
            needle = args.contains.lower()
            offers = [offer for offer in offers if needle in str(offer.get("unit_name", "")).lower()]
        if args.limit and args.limit > 0:
            offers = offers[: args.limit]
        print(json.dumps(offers, indent=2))
        return 0
    if args.command == "recruit":
        state = load_campaign(args.campaign)
        entry = purchase_reinforcements(state, args.formation, args.unit, args.quantity)
        save_campaign(state, args.campaign)
        print(json.dumps(asdict(entry), indent=2))
        return 0
    if args.command == "assign-reinforcements":
        state = load_campaign(args.campaign)
        result = assign_reinforcements(state, args.formation, args.unit, args.quantity)
        save_campaign(state, args.campaign)
        print(json.dumps(asdict(result), indent=2))
        return 0
    if args.command == "repair":
        state = load_campaign(args.campaign)
        result = repair_formation(state, args.formation, args.points)
        save_campaign(state, args.campaign)
        print(json.dumps(asdict(result), indent=2))
        return 0
    if args.command == "construction-status":
        state = load_campaign(args.campaign)
        faction = Faction(args.faction) if args.faction else state.current_faction
        print(json.dumps({
            "faction": faction.value,
            "province": args.province,
            "options": construction_options(state, faction, args.province),
        }, indent=2))
        return 0
    if args.command == "construct":
        state = load_campaign(args.campaign)
        faction = Faction(args.faction) if args.faction else state.current_faction
        result = build_infrastructure(state, faction, args.province, args.building)
        save_campaign(state, args.campaign)
        print(json.dumps(asdict(result), indent=2))
        return 0
    if args.command == "objectives":
        state = load_campaign(args.campaign)
        print(json.dumps(update_operational_objectives(state), indent=2))
        save_campaign(state, args.campaign)
        return 0
    if args.command == "campaign-status":
        state = load_campaign(args.campaign)
        outcome = evaluate_campaign_outcome(state)
        print(json.dumps({
            "outcome": asdict(outcome),
            "objectives": update_operational_objectives(state),
            "factions": {
                faction_id: {
                    "eliminated": faction_state.is_eliminated,
                    "resources": faction_state.resources,
                }
                for faction_id, faction_state in sorted(state.factions.items())
            },
        }, indent=2))
        save_campaign(state, args.campaign)
        return 0
    if args.command == "front":
        state = load_campaign(args.campaign)
        faction = Faction(args.faction) if args.faction else None
        options = list_front_options(state, faction)
        if args.kind:
            options = [row for row in options if row.get("kind") == args.kind]
        print(json.dumps({
            "current_faction": state.current_faction.value,
            "turn_number": state.turn_number,
            "pending_battle": state.pending_battle.battle_id if state.pending_battle else None,
            "options": options,
        }, indent=2))
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
        state = load_campaign(args.campaign)
        output = write_frontend_snapshot(state, args.output, campaign_path=args.campaign)
        print(output)
        return 0
    if args.command == "apply-frontend":
        snapshot = Path(args.snapshot)
        commands = Path(args.commands) if args.commands else default_commands_path(snapshot)
        result = apply_frontend_commands(
            args.campaign,
            commands_path=commands,
            snapshot_path=snapshot,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.command == "play":
        from .player_shell import main as play_main

        return play_main(args.play_args)
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
