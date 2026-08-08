from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


def render_faction_summary(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Resolved national faction wiring",
        "",
        f"Wiring signature: `{payload['wiring_signature']}`",
        f"Stack signature: `{payload['stack_signature']}`",
        f"Actors: **{payload['actor_count']}**",
        f"Errors: **{payload['error_count']}**",
        f"Warnings: **{payload['warning_count']}**",
        "",
        "Code:X is authoritative for modern content. West81 entries are retained as explicit legacy or reserve sources. Strategic actor IDs never replace the four GoH tactical export sides.",
        "",
        "## Actor matrix",
        "",
        "| Actor | Type | Export side | Roster | Units | Modern | Legacy | Virtual | Research | Missing categories |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for actor in payload["actors"]:
        missing = ", ".join(actor["missing_categories"]) or "none"
        lines.append(
            f"| {actor['display_name']} | {actor['actor_type']} | `{actor['tactical_side']}` | "
            f"{actor['roster_class']} | {actor['unit_count']} | {actor['modern_unit_count']} | "
            f"{actor['legacy_unit_count']} | {actor['virtual_unit_count']} | "
            f"{actor['research_node_count']} | {missing} |"
        )
    lines.extend(["", "## Per-actor details", ""])
    for actor in payload["actors"]:
        lines.extend([
            f"### {actor['display_name']} (`{actor['actor_id']}`)",
            "",
            f"- Actor type: `{actor['actor_type']}`",
            f"- Coalition: `{actor['coalition_id']}`",
            f"- Tactical export side: `{actor['tactical_side']}`",
            f"- Roster class: `{actor['roster_class']}`",
            f"- Research mode: `{actor['research_mode']}`",
            f"- Components: {', '.join(f'`{item}`' for item in actor['components'])}",
            f"- Unit count: {actor['unit_count']}",
            f"- Research nodes: {actor['research_node_count']}",
            f"- Category coverage: {', '.join(f'{key}={value}' for key, value in actor['category_counts'].items()) or 'none'}",
            f"- Missing required categories: {', '.join(actor['missing_categories']) or 'none'}",
        ])
        for component in actor.get("component_metadata", []):
            if component.get("research_label"):
                lines.append(
                    f"- Component branch: `{component['component_id']}` = "
                    f"{component['research_label']} "
                    f"(`{component['provenance_policy']}`)"
                )
        if actor.get("host_actor_id"):
            lines.append(f"- Host actor: `{actor['host_actor_id']}`")
        for note in actor.get("notes", []):
            lines.append(f"- Note: {note}")
        lines.append("")
    lines.extend(["## Resolution problems", ""])
    if not payload["problems"]:
        lines.append("No resolution problems were detected.")
    else:
        for problem in payload["problems"]:
            actor = problem["actor_id"] or "shared"
            component = problem["component_id"] or "none"
            lines.append(f"- **{problem['severity'].upper()}** `{actor}` / `{component}`: {problem['message']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gates-of-codex-factions")
    parser.add_argument("--stack", action="append", default=[])
    parser.add_argument("--stack-config")
    parser.add_argument("--manifest")
    parser.add_argument("--output", default="docs/audits/resolved-factions.json")
    parser.add_argument("--summary", default="docs/audits/resolved-factions.md")
    args = parser.parse_args(argv)

    from .faction_wiring_compiler import FactionWiringCompiler
    from .faction_wiring_manifest import load_faction_manifest
    from .modstack import resolve_stack

    stack = resolve_stack(args.stack, config=args.stack_config)
    compiler = FactionWiringCompiler(stack, manifest=load_faction_manifest(args.manifest))
    payload = compiler.write(args.output, args.summary)
    print(json.dumps({
        "ok": payload["error_count"] == 0,
        "actor_count": payload["actor_count"],
        "error_count": payload["error_count"],
        "warning_count": payload["warning_count"],
        "wiring_signature": payload["wiring_signature"],
        "output": str(Path(args.output)),
        "summary": str(Path(args.summary)),
    }, indent=2))
    return 0 if payload["error_count"] == 0 else 1
