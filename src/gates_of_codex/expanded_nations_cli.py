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
from .expanded_nations_cost_evidence import (
    generate_cost_evidence_from_stack_config,
    write_cost_evidence,
)
from .expanded_nations_matrix import (
    generate_projection_matrix_from_stack_config,
    write_projection_matrix_evidence,
)
from .expanded_nations_battle_pair import (
    materialize_battle_pair,
    restore_battle_pair,
    verify_battle_pair,
)
from .expanded_nations_static_matrix import (
    build_static_actor_matrix,
    validate_static_actor_matrix,
    write_static_matrix_evidence,
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

    matrix = subparsers.add_parser(
        "matrix",
        help="generate exact-stack evidence for every playable actor and restore Core",
    )
    matrix.add_argument("--stack-config", required=True)
    matrix.add_argument("--gates-root")
    matrix.add_argument("--source-head", required=True)
    matrix.add_argument("--source-repo", help="implementation git checkout for exact-head proof")
    matrix.add_argument("--json-output", required=True)
    matrix.add_argument("--markdown-output", required=True)

    static_matrix = subparsers.add_parser(
        "static-matrix",
        help="#194 static/pre-native matrix from committed authority (no live activation)",
    )
    static_matrix.add_argument("--repo-root", default=".")
    static_matrix.add_argument("--source-head", default="")
    static_matrix.add_argument(
        "--stack-config",
        help="optional mod-stack config used to compile resolved unit/research counts",
    )
    static_matrix.add_argument(
        "--require-resolved-counts",
        action="store_true",
        help="fail if playable actors lack resolved/pack unit and research counts",
    )
    static_matrix.add_argument("--json-output", required=True)
    static_matrix.add_argument("--markdown-output", required=True)

    battle_pair = subparsers.add_parser(
        "battle-pair",
        help="#194 install two-sided Expanded battle pair into engine resource paths",
    )
    battle_pair.add_argument("--attacker", required=True, help="attacker actor_id (e.g. usa)")
    battle_pair.add_argument("--defender", required=True, help="defender actor_id (e.g. fra)")
    battle_pair.add_argument(
        "--gates-root",
        required=True,
        help="destination Gates root receiving packs + engine overlays",
    )
    battle_pair.add_argument(
        "--source-repo",
        default=".",
        help="source checkout providing committed goc_* packs (never mutated when distinct)",
    )
    battle_pair.add_argument(
        "--stack-config",
        help="optional stack config if packs must be materialized into the source repo first",
    )
    battle_pair.add_argument(
        "--aio-conquest-lua",
        help="required with --stack-config to materialize conquest.lua before pair install",
    )

    battle_pair_verify = subparsers.add_parser(
        "battle-pair-verify",
        help="verify the active #194 battle-pair install",
    )
    battle_pair_verify.add_argument("--gates-root", required=True)

    battle_pair_restore = subparsers.add_parser(
        "battle-pair-restore",
        help="restore pre-pair overlays / multi-faction defaults and clear pair manifest",
    )
    battle_pair_restore.add_argument("--gates-root", required=True)

    cost = subparsers.add_parser(
        "cost-evidence",
        help="generate exact-stack native recruitment-cost evidence for all playable actors",
    )
    cost.add_argument("--stack-config", required=True)
    cost.add_argument("--gates-root")
    cost.add_argument("--source-head", required=True)
    cost.add_argument("--source-repo", help="implementation git checkout for exact-head proof")
    cost.add_argument("--json-output", required=True)
    cost.add_argument("--markdown-output", required=True)
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
    if args.command == "cost-evidence":
        matrix = generate_cost_evidence_from_stack_config(
            args.stack_config,
            gates_root=args.gates_root,
            source_head=args.source_head,
            source_repo=getattr(args, "source_repo", None),
        )
        write_cost_evidence(
            matrix,
            json_output=args.json_output,
            markdown_output=args.markdown_output,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "evidence_state": matrix["evidence_state"],
                    "playable_actor_count": matrix["playable_actor_count"],
                    "unintended_zero_total": matrix["unintended_zero_total"],
                    "native_positive_total": matrix.get("native_positive_total"),
                    "native_unknown_numeric_total": matrix.get("native_unknown_numeric_total"),
                    "source_head": matrix["source_head"],
                    "json_output": args.json_output,
                    "markdown_output": args.markdown_output,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "matrix":
        matrix = generate_projection_matrix_from_stack_config(
            args.stack_config,
            gates_root=args.gates_root,
            source_head=args.source_head,
            source_repo=getattr(args, "source_repo", None),
        )
        write_projection_matrix_evidence(
            matrix,
            json_output=args.json_output,
            markdown_output=args.markdown_output,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "core",
                    "playable_actor_count": matrix["playable_actor_count"],
                    "source_head": matrix["source_head"],
                    "wiring_signature": matrix["wiring_signature"],
                    "stack_signature": matrix["stack_signature"],
                    "json_output": args.json_output,
                    "markdown_output": args.markdown_output,
                },
                indent=2,
            )
        )
        return 0
    if args.command == "static-matrix":
        resolved_payload = None
        if getattr(args, "stack_config", None):
            # Compile via FactionWiringCompiler directly so committed production
            # research packs under a Gates checkout do not trip activation-path guards.
            from .faction_wiring_compiler import FactionWiringCompiler
            from .modstack import load_stack_config

            roots = load_stack_config(args.stack_config)
            resolved_payload = FactionWiringCompiler(roots).compile()
        try:
            matrix = build_static_actor_matrix(
                repo_root=args.repo_root,
                source_head=args.source_head,
                resolved_payload=resolved_payload,
                require_resolved_counts=bool(
                    getattr(args, "require_resolved_counts", False)
                    or getattr(args, "stack_config", None)
                ),
            )
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 2
        problems = validate_static_actor_matrix(matrix)
        if problems:
            print(json.dumps({"ok": False, "problems": problems}, indent=2))
            return 2
        write_static_matrix_evidence(
            matrix,
            json_output=args.json_output,
            markdown_output=args.markdown_output,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "static_pre_native",
                    "evidence_state": matrix["evidence_state"],
                    "counts": matrix["counts"],
                    "matrix_signature": matrix["matrix_signature"],
                    "source_head": matrix.get("source_head"),
                    "resolved_payload_present": matrix["authority"]["resolved_payload_present"],
                    "json_output": args.json_output,
                    "markdown_output": args.markdown_output,
                    "native_status": matrix["native_harness"]["status"],
                },
                indent=2,
            )
        )
        return 0
    if args.command == "battle-pair":
        from .expanded_nations_models import ExpandedNationsError
        from .modstack import load_stack_config

        stack = None
        if getattr(args, "stack_config", None):
            stack = load_stack_config(args.stack_config)
        try:
            result = materialize_battle_pair(
                args.source_repo,
                attacker_actor_id=args.attacker,
                defender_actor_id=args.defender,
                resource_stack=stack,
                aio_conquest_lua=getattr(args, "aio_conquest_lua", None),
                output_root=args.gates_root,
                source_pack_root=args.source_repo,
            )
        except ExpandedNationsError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 2
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "battle-pair-verify":
        problems = verify_battle_pair(args.gates_root)
        print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
        return 0 if not problems else 2
    if args.command == "battle-pair-restore":
        result = restore_battle_pair(args.gates_root)
        print(json.dumps(result, indent=2))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
