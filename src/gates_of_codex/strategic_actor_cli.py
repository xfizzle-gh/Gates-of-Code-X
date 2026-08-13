from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .faction_wiring_manifest import load_faction_manifest
from .state_io import load_campaign, save_campaign
from .strategic_actors import (
    install_bundled_strategic_actors,
    set_selected_actor,
    strategic_actor_snapshot,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gates-of-codex-actors")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list bundled strategic actors")
    list_parser.add_argument("--playable-only", action="store_true")

    install_parser = subparsers.add_parser(
        "install",
        help="install the bundled actor catalog into a campaign and select an actor",
    )
    install_parser.add_argument("campaign")
    install_parser.add_argument("--actor", required=True)
    install_parser.add_argument("--output")

    select_parser = subparsers.add_parser("select", help="select an installed strategic actor")
    select_parser.add_argument("campaign")
    select_parser.add_argument("--actor", required=True)
    select_parser.add_argument("--output")

    snapshot_parser = subparsers.add_parser("snapshot", help="print persisted strategic actor state")
    snapshot_parser.add_argument("campaign")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list":
        manifest = load_faction_manifest()
        actors = [
            actor
            for actor in manifest["actors"]
            if not args.playable_only or actor["playable"]
        ]
        print(json.dumps({
            "actor_count": len(actors),
            "actors": [
                {
                    "actor_id": actor["actor_id"],
                    "display_name": actor["display_name"],
                    "actor_type": actor["actor_type"],
                    "coalition_id": actor["coalition_id"],
                    "tactical_side": actor["tactical_side"],
                    "playable": actor["playable"],
                    "host_actor_id": actor.get("host_actor_id"),
                    "roster_class": actor["roster_class"],
                }
                for actor in actors
            ],
        }, indent=2))
        return 0

    campaign_path = Path(args.campaign)
    state = load_campaign(campaign_path)
    if args.command == "install":
        install_bundled_strategic_actors(state, selected_actor_id=args.actor)
        destination = Path(args.output or campaign_path)
        save_campaign(state, destination)
        print(json.dumps({
            "ok": True,
            "output": str(destination),
            **strategic_actor_snapshot(state),
        }, indent=2))
        return 0
    if args.command == "select":
        actor = set_selected_actor(state, args.actor)
        destination = Path(args.output or campaign_path)
        save_campaign(state, destination)
        print(json.dumps({
            "ok": True,
            "output": str(destination),
            "selected_actor_id": actor.actor_id,
            "selected_faction": actor.tactical_side.campaign_faction().value,
        }, indent=2))
        return 0
    if args.command == "snapshot":
        print(json.dumps(strategic_actor_snapshot(state), indent=2))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
