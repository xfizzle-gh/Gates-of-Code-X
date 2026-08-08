from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .expanded_nations_models import (
    ACTIVATION_SCHEMA,
    ACTIVATION_VERSION,
    CANONICAL_INF_INCLUDES,
    ExpandedNationsError,
    GENERATED_MARKER,
    ProjectedOpponentUnit,
    ProjectedResearchNode,
    ProjectedUnit,
    sha256_bytes,
)


def render_units_file(actor: Mapping[str, Any], projected_units: Sequence[ProjectedUnit], body: str) -> str:
    return (
        f"{GENERATED_MARKER}\n"
        f"; actor_id={actor['actor_id']}\n"
        f"; display_name={actor['display_name']}\n"
        f"; tactical_side={actor['tactical_side']}\n"
        f"; unit_count={len(projected_units)}\n"
        "; Source definitions are generated locally from the active installed stack.\n"
        "; No upstream file is modified and no upstream definition is committed here.\n\n"
        + body
    )


def render_opponent_units_file(
    actor: Mapping[str, Any],
    projected_units: Sequence[ProjectedOpponentUnit],
    body: str,
) -> str:
    return (
        f"{GENERATED_MARKER}\n"
        f"; selected_actor_id={actor['actor_id']}\n"
        f"; excluded_tactical_side={actor['tactical_side']}\n"
        f"; opponent_entry_count={len(projected_units)}\n"
        "; Non-selected tactical-side definitions are preserved from the effective Core roster.\n"
        "; Entries for the selected tactical side are intentionally excluded.\n\n"
        + body
    )


def render_roster_file(actor: Mapping[str, Any]) -> str:
    lines = [
        ";sdl",
        GENERATED_MARKER,
        f"; actor_id={actor['actor_id']}",
        f"; tactical_side={actor['tactical_side']}",
        "{units",
        '\t(include "conquest/settings.set")',
        "",
    ]
    lines.extend(f'\t(include "{value}")' for value in CANONICAL_INF_INCLUDES)
    lines.extend([
        "",
        '\t(include "conquest/goc_opponent_units.set")',
        '\t(include "conquest/goc_active_actor_units.set")',
        "}",
        "",
    ])
    return "\n".join(lines)


def project_research_nodes(actor: Mapping[str, Any]) -> list[ProjectedResearchNode]:
    nodes = topological_research_nodes(actor)
    node_ids: dict[str, str] = {}
    unit_ids: set[str] = set()
    for node in nodes:
        unlock_units = [str(item) for item in node.get("unlock_units", [])]
        if len(unlock_units) == 1:
            engine_id = unlock_units[0]
            if engine_id in unit_ids:
                raise ExpandedNationsError(
                    f"Actor {actor['actor_id']} research unlocks unit more than once: {engine_id}"
                )
            unit_ids.add(engine_id)
        elif not unlock_units:
            digest = hashlib.sha256(str(node["key"]).encode("utf-8")).hexdigest()[:12]
            engine_id = f"goc_{actor['actor_id']}_tech_{digest}"
        else:
            raise ExpandedNationsError(
                f"Actor research node {node['key']} unlocks multiple units and cannot be projected"
            )
        if engine_id in node_ids.values():
            raise ExpandedNationsError(f"Duplicate projected research ID: {engine_id}")
        node_ids[str(node["key"])] = engine_id

    projected: list[ProjectedResearchNode] = []
    for node in nodes:
        key = str(node["key"])
        prerequisites = [str(item) for item in node.get("prerequisites", [])]
        required = node_ids[prerequisites[0]] if prerequisites else ""
        cost = int(node.get("cost", 0))
        if cost < 0:
            raise ExpandedNationsError(f"Research node {key} has negative cost")
        unlock_units = [str(item) for item in node.get("unlock_units", [])]
        projected.append(
            ProjectedResearchNode(
                key=key,
                engine_id=node_ids[key],
                required_engine_id=required,
                cost=cost,
                unlock_unit=unlock_units[0] if unlock_units else None,
            )
        )
    return projected


def render_research_file(
    actor: Mapping[str, Any],
    projected_nodes: Sequence[ProjectedResearchNode] | None = None,
) -> str:
    nodes = list(projected_nodes or project_research_nodes(actor))
    lines = [
        GENERATED_MARKER,
        f"; actor_id={actor['actor_id']}",
        f"; display_name={actor['display_name']}",
        f"; tactical_side={actor['tactical_side']}",
        f"; research_node_count={len(nodes)}",
        "{IconGap 30}",
        "",
        "; Standard Conquest reinforcement and defense progression.",
        '{ tech "reinforcement_stage_1" requires "" costs 0 position 0 0}',
        '{ tech "reinforcement_stage_2" requires "reinforcement_stage_1" costs 1 position 1 0}',
        '{ tech "reinforcement_stage_3" requires "reinforcement_stage_2" costs 2 position 2 0}',
        '{ tech "reinforcement_stage_4" requires "reinforcement_stage_3" costs 5 position 3 0}',
        '{ tech "reinforcement_stage_5" requires "reinforcement_stage_4" costs 7 position 4 0}',
        '{ tech "defense_level_1" requires "reinforcement_stage_2" costs 1 position 7 0}',
        '{ tech "defense_level_2" requires "defense_level_1" costs 5 position 8 0}',
        '{ tech "defense_level_3" requires "defense_level_2" costs 7 position 9 0}',
        "",
        "; Actor-scoped research projection.",
    ]
    columns = 14
    for index, node in enumerate(nodes):
        x = 1 + 2 * (index % columns)
        y = 3 + 2 * (index // columns)
        metadata = json.dumps(asdict(node), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        lines.append(f"; goc-node {metadata}")
        if node.unlock_unit is not None:
            lines.append(
                f'{{"{node.engine_id}" requires "{node.required_engine_id}" '
                f"costs {node.cost} position {x} {y}}}"
            )
        else:
            lines.append(
                f'{{ tech "{node.engine_id}" requires "{node.required_engine_id}" '
                f"costs {node.cost} position {x} {y}}}"
            )
    lines.append("")
    return "\n".join(lines)


def topological_research_nodes(actor: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = {str(row["key"]): row for row in actor["research_nodes"]}
    if len(nodes) != len(actor["research_nodes"]):
        raise ExpandedNationsError(f"Actor {actor['actor_id']} has duplicate research keys")
    for key, node in nodes.items():
        if not key.startswith(f"actor:{actor['actor_id']}:"):
            raise ExpandedNationsError(f"Actor research key is not actor-scoped: {key}")
        prerequisites = [str(item) for item in node.get("prerequisites", [])]
        if len(prerequisites) > 1:
            raise ExpandedNationsError(f"Research node {key} has multiple prerequisites")
        missing = [item for item in prerequisites if item not in nodes]
        if missing:
            raise ExpandedNationsError(f"Research node {key} has missing prerequisites {missing}")
    remaining = set(nodes)
    completed: set[str] = set()
    ordered: list[Mapping[str, Any]] = []
    while remaining:
        ready = sorted(
            key for key in remaining
            if set(str(item) for item in nodes[key].get("prerequisites", [])).issubset(completed)
        )
        if not ready:
            raise ExpandedNationsError(f"Actor {actor['actor_id']} research graph contains a cycle")
        for key in ready:
            ordered.append(nodes[key])
            completed.add(key)
            remaining.remove(key)
    return ordered


def projection_signature(
    actor: Mapping[str, Any],
    payload: Mapping[str, Any],
    outputs: Mapping[Path, bytes],
    projected_units: Sequence[ProjectedUnit],
) -> str:
    value = {
        "schema": ACTIVATION_SCHEMA,
        "schema_version": ACTIVATION_VERSION,
        "actor_id": actor["actor_id"],
        "tactical_side": actor["tactical_side"],
        "wiring_signature": payload["wiring_signature"],
        "outputs": {
            path.as_posix(): sha256_bytes(data)
            for path, data in sorted(outputs.items(), key=lambda item: item[0].as_posix())
        },
        "units": [asdict(item) for item in projected_units],
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(canonical.encode("utf-8"))
