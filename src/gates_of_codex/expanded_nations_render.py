from __future__ import annotations

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


def render_units_file(
    actor: Mapping[str, Any],
    projected_units: Sequence[ProjectedUnit],
    body: str,
) -> str:
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
        "; Entries for the selected tactical-side family are intentionally excluded.\n\n"
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
    lines.extend(
        [
            "",
            '\t(include "conquest/goc_opponent_units.set")',
            '\t(include "conquest/goc_active_actor_units.set")',
            "}",
            "",
        ]
    )
    return "\n".join(lines)


def project_research_nodes(actor: Mapping[str, Any]) -> list[ProjectedResearchNode]:
    """Collapse compiler-only graph nodes into native purchase nodes."""

    ordered = topological_research_nodes(actor)
    by_key = {str(row["key"]): row for row in ordered}
    order_index = {str(row["key"]): index for index, row in enumerate(ordered)}
    unit_nodes = [
        row for row in ordered if len([str(item) for item in row.get("unlock_units", [])]) == 1
    ]
    if len(unit_nodes) != int(actor.get("unit_count", -1)):
        raise ExpandedNationsError(
            f"Actor {actor['actor_id']} native research has {len(unit_nodes)} purchase nodes, "
            f"expected {actor.get('unit_count')}"
        )

    ancestors: dict[str, list[str]] = {}
    for node in unit_nodes:
        key = str(node["key"])
        ancestors[key] = _ancestor_chain(key, by_key)

    assigned_costs = {str(node["key"]): int(node.get("cost", 0)) for node in unit_nodes}
    for node in ordered:
        key = str(node["key"])
        unlocks = [str(item) for item in node.get("unlock_units", [])]
        cost = int(node.get("cost", 0))
        if cost < 0:
            raise ExpandedNationsError(f"Research node {key} has negative cost")
        if unlocks:
            if len(unlocks) != 1:
                raise ExpandedNationsError(
                    f"Actor research node {key} unlocks multiple units and cannot be projected"
                )
            continue
        descendants = [
            str(candidate["key"])
            for candidate in unit_nodes
            if key in ancestors[str(candidate["key"])]
        ]
        if not descendants:
            if cost:
                raise ExpandedNationsError(
                    f"Research node {key} has cost {cost} but no purchase descendant"
                )
            continue
        owner = min(descendants, key=lambda item: order_index[item])
        assigned_costs[owner] += cost

    projected: list[ProjectedResearchNode] = []
    seen_units: set[str] = set()
    for node in unit_nodes:
        key = str(node["key"])
        unlock = str(node["unlock_units"][0])
        if unlock in seen_units:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} research unlocks unit more than once: {unlock}"
            )
        seen_units.add(unlock)
        required = ""
        for ancestor_key in ancestors[key]:
            ancestor = by_key[ancestor_key]
            ancestor_unlocks = [str(item) for item in ancestor.get("unlock_units", [])]
            if ancestor_unlocks:
                if len(ancestor_unlocks) != 1:
                    raise ExpandedNationsError(
                        f"Actor research node {ancestor_key} unlocks multiple units"
                    )
                required = ancestor_unlocks[0]
                break
        projected.append(
            ProjectedResearchNode(
                key=key,
                engine_id=unlock,
                required_engine_id=required,
                cost=assigned_costs[key],
                unlock_unit=unlock,
            )
        )

    expected_units = {str(row["unit_name"]) for row in actor["units"]}
    if seen_units != expected_units:
        raise ExpandedNationsError(
            f"Actor {actor['actor_id']} native research/unit mismatch; "
            f"missing={sorted(expected_units - seen_units)}; "
            f"extra={sorted(seen_units - expected_units)}"
        )
    return projected


def _ancestor_chain(
    key: str,
    nodes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    chain: list[str] = []
    current = key
    guard: set[str] = set()
    while current:
        if current in guard:
            raise ExpandedNationsError(f"Research graph contains a cycle at {current}")
        guard.add(current)
        prerequisites = [str(item) for item in nodes[current].get("prerequisites", [])]
        if len(prerequisites) > 1:
            raise ExpandedNationsError(
                f"Research node {current} has multiple prerequisites"
            )
        if not prerequisites:
            break
        current = prerequisites[0]
        if current not in nodes:
            raise ExpandedNationsError(
                f"Research node {key} has missing prerequisite {current}"
            )
        chain.append(current)
    return chain


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
        "; Actor-scoped native purchase progression.",
    ]
    columns = 14
    for index, node in enumerate(nodes):
        x = 1 + 2 * (index % columns)
        y = 3 + 2 * (index // columns)
        metadata = json.dumps(
            asdict(node),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        lines.append(f"; goc-node {metadata}")
        if node.unlock_unit is None:
            raise ExpandedNationsError(
                f"Native research node {node.key} has no purchase unlock"
            )
        lines.append(
            f'{{"{node.engine_id}" requires "{node.required_engine_id}" '
            f"costs {node.cost} position {x} {y}}}"
        )
    lines.append("")
    return "\n".join(lines)


def topological_research_nodes(actor: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = {str(row["key"]): row for row in actor["research_nodes"]}
    if len(nodes) != len(actor["research_nodes"]):
        raise ExpandedNationsError(
            f"Actor {actor['actor_id']} has duplicate research keys"
        )
    for key, node in nodes.items():
        if not key.startswith(f"actor:{actor['actor_id']}:"):
            raise ExpandedNationsError(f"Actor research key is not actor-scoped: {key}")
        prerequisites = [str(item) for item in node.get("prerequisites", [])]
        if len(prerequisites) > 1:
            raise ExpandedNationsError(f"Research node {key} has multiple prerequisites")
        missing = [item for item in prerequisites if item not in nodes]
        if missing:
            raise ExpandedNationsError(
                f"Research node {key} has missing prerequisites {missing}"
            )
    remaining = set(nodes)
    completed: set[str] = set()
    ordered: list[Mapping[str, Any]] = []
    while remaining:
        ready = sorted(
            key
            for key in remaining
            if set(str(item) for item in nodes[key].get("prerequisites", [])).issubset(
                completed
            )
        )
        if not ready:
            raise ExpandedNationsError(
                f"Actor {actor['actor_id']} research graph contains a cycle"
            )
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
            for path, data in sorted(
                outputs.items(), key=lambda item: item[0].as_posix()
            )
        },
        "units": [asdict(item) for item in projected_units],
    }
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return sha256_bytes(canonical.encode("utf-8"))
