from __future__ import annotations

import argparse
import json
from typing import Sequence

from .expanded_nations import (
    activate_from_stack_config,
    compile_resolved_factions,
    deactivate_actor_projection,
    launch_expanded_nation,
    verify_actor_projection,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gates-of-codex-expanded",
        description="Activate one actor-specific native Gates of Hell roster and research projection.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="compile and list playable actors")
    list_parser.add_argument("--stack-config", required=True)

    activate = subparsers.add_parser("activate", help="activate one Expanded Nations actor")
    activate.add_argument("--stack-config", required=True)
    activate.add_argument("--actor", required=True)
    activate.add_argument("--gates-root")

    launch = subparsers.add_parser("launch", help="activate one actor and launch Gates of Hell")
    launch.add_argument("--stack-config", required=True)
    launch.add_argument("--actor", required=True)
    launch.add_argument("--game", required=True)
    launch.add_argument("--gates-root")
    launch.add_argument("game_args", nargs=argparse.REMAINDER)

    verify = subparsers.add_parser("verify", help="verify the active actor projection")
    verify.add_argument("--gates-root", required=True)

    core = subparsers.add_parser("core", help="remove the projection and restore inherited Core Code:X")
    core.add_argument("--gates-root", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "list":
        _, payload = compile_resolved_factions(args.stack_config)
        actors = [
            {
                "actor_id": row["actor_id"],
                "display_name": row["display_name"],
                "tactical_side": row["tactical_side"],
                "roster_class": row["roster_class"],
                "unit_count": row["unit_count"],
                "research_node_count": row["research_node_count"],
            }
            for row in payload["actors"]
            if row["playable"]
        ]
        print(json.dumps({"actor_count": len(actors), "actors": actors}, indent=2))
        return 0
    if args.command == "activate":
        result = activate_from_stack_config(
            args.stack_config,
            args.actor,
            gates_root=args.gates_root,
        )
        print(json.dumps({"ok": True, "mode": "expanded", **result.to_dict()}, indent=2))
        return 0
    if args.command == "launch":
        result = launch_expanded_nation(
            args.stack_config,
            args.actor,
            args.game,
            gates_root=args.gates_root,
            extra_args=args.game_args,
        )
        print(json.dumps({"ok": True, "mode": "expanded", "launched": True, **result.to_dict()}, indent=2))
        return 0
    if args.command == "verify":
        print(json.dumps({"ok": True, **verify_actor_projection(args.gates_root)}, indent=2))
        return 0
    if args.command == "core":
        changed = deactivate_actor_projection(args.gates_root)
        print(json.dumps({"ok": True, "mode": "core", "projection_removed": changed}, indent=2))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
