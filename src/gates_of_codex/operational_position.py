from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import CampaignState, StrategicFormation
from .operational_schema import (
    FormationOperationalPosition,
    OperationalRouteEdge,
    PositionMode,
    stable_node_id,
)

OPERATIONAL_POSITION_SCHEMA_VERSION = 7
MIGRATION_RECORD_KEY = "operational_position_migration"

# map_id -> path relative to repo root (package parent).
_GRAPH_RELATIVE_PATHS: dict[str, str] = {
    "europe_mediterranean_from_goe": (
        "godot/assets/maps/europe_mediterranean/from_goe/operational/operational_graph.json"
    ),
}

_REPO_ROOT = Path(__file__).resolve().parents[2]


def province_anchor_position(province_id: str) -> FormationOperationalPosition:
    """M1 default: highest-weight site node when present; else province anchor node."""
    return FormationOperationalPosition(
        mode=PositionMode.AT_NODE.value,
        node_id=stable_node_id(province_id, "anchor"),
        edge_id=None,
        progress_milli=0,
        facing_node_id=None,
    )


def position_to_dict(position: FormationOperationalPosition | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "mode": position.mode,
        "node_id": position.node_id,
        "edge_id": position.edge_id,
        "progress_milli": int(position.progress_milli),
        "facing_node_id": position.facing_node_id,
    }


def position_from_dict(raw: Any) -> FormationOperationalPosition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("position must be an object or null")
    if not raw:
        return None
    return FormationOperationalPosition(
        mode=str(raw.get("mode", PositionMode.AT_NODE.value)),
        node_id=None if raw.get("node_id") in (None, "") else str(raw.get("node_id")),
        edge_id=None if raw.get("edge_id") in (None, "") else str(raw.get("edge_id")),
        progress_milli=int(raw.get("progress_milli", 0)),
        facing_node_id=(
            None if raw.get("facing_node_id") in (None, "") else str(raw.get("facing_node_id"))
        ),
    )


def place_formation_at_province_anchor(force: StrategicFormation) -> FormationOperationalPosition:
    """Set formation position to the province migration anchor (M1)."""
    position = province_anchor_position(force.province_id)
    force.position = position
    return position


def ensure_operational_positions(state: CampaignState) -> dict:
    """Hydrate missing/invalid operational positions (S2 / M1).

    - Does not invent sites or edges.
    - Places each strategic formation at its province anchor node when needed.
    - Keeps writing province_id for legacy systems (unchanged here).
    - Idempotent: valid positions are left alone; re-run yields stable serialization.
    - No movement resolution, capture, interception, or AI.
    """
    from .force_migration import ensure_strategic_formations

    ensure_strategic_formations(state)
    incoming_schema = int(state.schema_version)
    graph = load_operational_graph_payload(state.map_id)
    node_ids, edge_ids, edges_by_id, nodes_by_id = _graph_indexes(graph)

    hydrated = 0
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if _position_is_valid(
            force.position,
            province_id=force.province_id,
            node_ids=node_ids,
            edge_ids=edge_ids,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
            require_graph=graph is not None,
        ):
            continue
        # Prefer highest-weight site node in province when graph has sites; else anchor.
        force.position = _migration_position_for_province(
            force.province_id,
            graph=graph,
            nodes_by_id=nodes_by_id,
        )
        hydrated += 1

    state.schema_version = max(state.schema_version, OPERATIONAL_POSITION_SCHEMA_VERSION)
    if MIGRATION_RECORD_KEY not in state.map_metadata:
        state.map_metadata[MIGRATION_RECORD_KEY] = _stable_migration_record(
            incoming_schema, map_id=state.map_id, graph_loaded=graph is not None
        )
    record = state.map_metadata[MIGRATION_RECORD_KEY]
    # Keep a deterministic hydrated counter only on first write; do not thrash on reload.
    if "hydrated_on_first_pass" not in record:
        record["hydrated_on_first_pass"] = hydrated
    return record


def resolve_display_pixel(
    state: CampaignState,
    force: StrategicFormation,
) -> list[int] | None:
    """Pixel for UI draw: node/edge lerp when graph known, else province marker."""
    graph = load_operational_graph_payload(state.map_id)
    if force.position is not None and graph is not None:
        pixel = _pixel_from_position(force.position, graph)
        if pixel is not None:
            return pixel
    province = state.provinces.get(force.province_id)
    if province is None:
        return None
    return [int(round(province.x)), int(round(province.y))]


def load_operational_graph_payload(map_id: str) -> dict[str, Any] | None:
    relative = _GRAPH_RELATIVE_PATHS.get(str(map_id))
    if not relative:
        return None
    path = _REPO_ROOT / relative
    if not path.is_file():
        return None
    return _read_graph_json(str(path))


@lru_cache(maxsize=4)
def _read_graph_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stable_migration_record(incoming_schema: int, *, map_id: str, graph_loaded: bool) -> dict:
    return {
        "schema_version": OPERATIONAL_POSITION_SCHEMA_VERSION,
        "migrated_from_schema": min(incoming_schema, OPERATIONAL_POSITION_SCHEMA_VERSION),
        "map_id": map_id,
        "placement": "province_anchor_or_highest_weight_site",
        "graph_loaded": bool(graph_loaded),
        "note": "S2 M1: strategic formations placed on operational graph; province_id retained.",
    }


def _migration_position_for_province(
    province_id: str,
    *,
    graph: dict[str, Any] | None,
    nodes_by_id: dict[str, dict[str, Any]],
) -> FormationOperationalPosition:
    site_node = _highest_weight_site_node(province_id, graph=graph, nodes_by_id=nodes_by_id)
    if site_node is not None:
        return FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=str(site_node["node_id"]),
            progress_milli=0,
        )
    return province_anchor_position(province_id)


def _highest_weight_site_node(
    province_id: str,
    *,
    graph: dict[str, Any] | None,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if graph is None:
        return None
    sites = [
        site
        for site in graph.get("sites") or []
        if str(site.get("province_id")) == province_id
    ]
    if not sites:
        return None

    def sort_key(site: dict[str, Any]) -> tuple:
        weight = site.get("control_weight", 0)
        try:
            weight_key = -float(weight)
        except (TypeError, ValueError):
            weight_key = 0.0
        return (weight_key, str(site.get("site_id", "")))

    best = sorted(sites, key=sort_key)[0]
    route_node_id = best.get("route_node_id")
    if route_node_id and str(route_node_id) in nodes_by_id:
        return nodes_by_id[str(route_node_id)]
    # Fallback: any node in province tagged with this site.
    site_id = str(best.get("site_id", ""))
    candidates = [
        node
        for node in nodes_by_id.values()
        if str(node.get("province_id")) == province_id and str(node.get("site_id") or "") == site_id
    ]
    if candidates:
        return sorted(candidates, key=lambda node: str(node["node_id"]))[0]
    return None


def _position_is_valid(
    position: FormationOperationalPosition | None,
    *,
    province_id: str,
    node_ids: set[str] | None,
    edge_ids: set[str] | None,
    edges_by_id: dict[str, OperationalRouteEdge] | None,
    nodes_by_id: dict[str, dict[str, Any]] | None,
    require_graph: bool,
) -> bool:
    if position is None:
        return False
    try:
        if require_graph and node_ids is not None and edge_ids is not None and edges_by_id is not None:
            position.validate(node_ids=node_ids, edge_ids=edge_ids, edges_by_id=edges_by_id)
            if position.mode == PositionMode.AT_NODE.value and nodes_by_id is not None:
                node = nodes_by_id.get(str(position.node_id))
                if node is None or str(node.get("province_id")) != province_id:
                    return False
            if position.mode == PositionMode.ON_EDGE.value and nodes_by_id is not None:
                edge = edges_by_id[str(position.edge_id)]
                provinces = {
                    str(nodes_by_id.get(edge.a, {}).get("province_id", "")),
                    str(nodes_by_id.get(edge.b, {}).get("province_id", "")),
                }
                if province_id not in provinces:
                    return False
        else:
            # No graph: accept shape + default anchor node id match when at_node.
            if position.mode == PositionMode.AT_NODE.value:
                if position.node_id != stable_node_id(province_id, "anchor"):
                    # Still accept any non-empty node_id shape for forward-compat.
                    if not position.node_id:
                        return False
                if position.edge_id is not None or position.facing_node_id is not None:
                    return False
                if int(position.progress_milli) != 0:
                    return False
            elif position.mode == PositionMode.ON_EDGE.value:
                if not position.edge_id or not position.facing_node_id or position.node_id is not None:
                    return False
            else:
                return False
    except (TypeError, ValueError):
        return False
    return True


def _graph_indexes(
    graph: dict[str, Any] | None,
) -> tuple[
    set[str] | None,
    set[str] | None,
    dict[str, OperationalRouteEdge] | None,
    dict[str, dict[str, Any]] | None,
]:
    if graph is None:
        return None, None, None, None
    nodes_by_id = {str(node["node_id"]): node for node in graph.get("nodes") or []}
    node_ids = set(nodes_by_id)
    edges_by_id: dict[str, OperationalRouteEdge] = {}
    for edge in graph.get("edges") or []:
        edges_by_id[str(edge["edge_id"])] = OperationalRouteEdge(
            edge_id=str(edge["edge_id"]),
            a=str(edge["a"]),
            b=str(edge["b"]),
            kind=str(edge["kind"]),
            authority=str(edge["authority"]),
            length_px=int(edge["length_px"]),
            base_move_points_milli=int(edge["base_move_points_milli"]),
            movement_cost_milli=int(edge["movement_cost_milli"]),
            requires_port=bool(edge["requires_port"]),
            can_be_blockaded=bool(edge["can_be_blockaded"]),
            traversal_enabled=bool(edge["traversal_enabled"]),
            bidirectional=bool(edge["bidirectional"]),
            province_ids=list(edge.get("province_ids") or []),
            legacy_crossing_type=edge.get("legacy_crossing_type"),
            metadata=dict(edge.get("metadata") or {}),
        )
    return node_ids, set(edges_by_id), edges_by_id, nodes_by_id


def _pixel_from_position(
    position: FormationOperationalPosition,
    graph: dict[str, Any],
) -> list[int] | None:
    nodes = {str(node["node_id"]): node for node in graph.get("nodes") or []}
    if position.mode == PositionMode.AT_NODE.value:
        node = nodes.get(str(position.node_id))
        if node is None:
            return None
        pixel = node.get("pixel") or [0, 0]
        return [int(pixel[0]), int(pixel[1])]
    if position.mode == PositionMode.ON_EDGE.value:
        edges = {str(edge["edge_id"]): edge for edge in graph.get("edges") or []}
        edge = edges.get(str(position.edge_id))
        if edge is None:
            return None
        a = nodes.get(str(edge["a"]))
        b = nodes.get(str(edge["b"]))
        if a is None or b is None:
            return None
        # Facing is destination; progress 0 at the other endpoint.
        facing = str(position.facing_node_id)
        if facing == str(edge["b"]):
            start, end = a, b
        elif facing == str(edge["a"]):
            start, end = b, a
        else:
            start, end = a, b
        t = max(0, min(1000, int(position.progress_milli))) / 1000.0
        sx, sy = start.get("pixel") or [0, 0]
        ex, ey = end.get("pixel") or [0, 0]
        return [int(round(sx + (ex - sx) * t)), int(round(sy + (ey - sy) * t))]
    return None
