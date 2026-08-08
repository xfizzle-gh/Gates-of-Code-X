from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .actor_economy import (
    actor_content_snapshot,
    actor_recruitment_offers,
    assign_actor_reinforcements,
    available_actor_research,
    install_actor_content,
    load_resolved_factions,
    purchase_actor_reinforcements,
    purchase_actor_research,
    repair_actor_formation,
    settle_actor_round_economy,
)
from .state_io import load_campaign, save_campaign


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex-actor-economy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser("install", help="install resolved actor rosters and research")
    install.add_argument("campaign")
    install.add_argument("resolved_factions")
    install.add_argument("--actor", required=True)
    install.add_argument("--allow-warnings", action="store_true")
    install.add_argument("--output")

    research_list = subparsers.add_parser("research-list", help="list currently available actor research")
    research_list.add_argument("campaign")
    research_list.add_argument("--actor", required=True)

    research_buy = subparsers.add_parser("research-buy", help="purchase actor research")
    research_buy.add_argument("campaign")
    research_buy.add_argument("--actor", required=True)
    research_buy.add_argument("--key", required=True)
    research_buy.add_argument("--output")

    offers = subparsers.add_parser("offers", help="list national recruitment offers")
    offers.add_argument("campaign")
    offers.add_argument("--formation", required=True)

    buy = subparsers.add_parser("buy", help="purchase actor-scoped reinforcements")
    buy.add_argument("campaign")
    buy.add_argument("--formation", required=True)
    buy.add_argument("--unit", required=True)
    buy.add_argument("--quantity", type=int, default=1)
    buy.add_argument("--output")

    assign = subparsers.add_parser("assign", help="assign actor-scoped reinforcements")
    assign.add_argument("campaign")
    assign.add_argument("--formation", required=True)
    assign.add_argument("--unit", required=True)
    assign.add_argument("--quantity", type=int, default=1)
    assign.add_argument("--battalion")
    assign.add_argument("--output")

    repair = subparsers.add_parser("repair", help="repair a formation from its actor treasury")
    repair.add_argument("campaign")
    repair.add_argument("--formation", required=True)
    repair.add_argument("--points", type=int)
    repair.add_argument("--battalion")
    repair.add_argument("--output")

    settle = subparsers.add_parser("settle", help="settle one actor-economy round")
    settle.add_argument("campaign")
    settle.add_argument("--output")

    snapshot = subparsers.add_parser("snapshot", help="print installed actor content")
    snapshot.add_argument("campaign")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    campaign = Path(args.campaign)
    state = load_campaign(campaign)

    if args.command == "install":
        runtime = install_actor_content(
            state,
            load_resolved_factions(args.resolved_factions),
            selected_actor_id=args.actor,
            allow_warnings=args.allow_warnings,
        )
        destination = _save(state, campaign, args.output)
        result = {
            "ok": True,
            "output": str(destination),
            "actor_count": runtime["actor_count"],
            "wiring_signature": runtime["wiring_signature"],
            "stack_signature": runtime["stack_signature"],
            "migration_exception_count": len(runtime["migration_exceptions"]),
        }
    elif args.command == "research-list":
        result = {
            "actor_id": args.actor,
            "research": [asdict(item) for item in available_actor_research(state, args.actor)],
        }
    elif args.command == "research-buy":
        purchase = purchase_actor_research(state, args.actor, args.key)
        destination = _save(state, campaign, args.output)
        result = {"ok": True, "output": str(destination), **asdict(purchase)}
    elif args.command == "offers":
        result = {
            "strategic_formation_id": args.formation,
            "offers": [asdict(item) for item in actor_recruitment_offers(state, args.formation)],
        }
    elif args.command == "buy":
        purchase = purchase_actor_reinforcements(
            state,
            args.formation,
            args.unit,
            args.quantity,
        )
        destination = _save(state, campaign, args.output)
        result = {"ok": True, "output": str(destination), **asdict(purchase)}
    elif args.command == "assign":
        transfer = assign_actor_reinforcements(
            state,
            args.formation,
            args.unit,
            args.quantity,
            battalion_id=args.battalion,
        )
        destination = _save(state, campaign, args.output)
        result = {"ok": True, "output": str(destination), **asdict(transfer)}
    elif args.command == "repair":
        repair_result = repair_actor_formation(
            state,
            args.formation,
            args.points,
            battalion_id=args.battalion,
        )
        destination = _save(state, campaign, args.output)
        result = {"ok": True, "output": str(destination), **asdict(repair_result)}
    elif args.command == "settle":
        reports = settle_actor_round_economy(state)
        destination = _save(state, campaign, args.output)
        result = {
            "ok": True,
            "output": str(destination),
            "reports": [asdict(item) for item in reports],
        }
    elif args.command == "snapshot":
        result = actor_content_snapshot(state)
    else:
        raise AssertionError(f"Unhandled command: {args.command}")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _save(state, campaign: Path, output: str | None) -> Path:
    destination = Path(output) if output else campaign
    save_campaign(state, destination)
    return destination


if __name__ == "__main__":
    raise SystemExit(main())
