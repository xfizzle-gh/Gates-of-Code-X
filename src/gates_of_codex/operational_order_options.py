"""Legal graph-native move orders projected for the player movement surface.

The player-facing movement UI must offer exactly the orders the authoritative
commit path will accept. Every route here is built from the authenticated
operational graph with the same deterministic pathfinder the operational AI
uses, and is then run through the same gates ``commit_move_orders`` runs, so a
target that renders is a target that commits.

Province polygon adjacency is never consulted: an edge that is not present and
traversal-enabled in the authenticated graph can never become a player route,
and an edge that is present but disabled, candidate-authority or
metadata-blocked is rejected by the shared traversal gate.
"""

from __future__ import annotations

from typing import Any

from .models import CampaignState, Faction, StrategicFormation
from .operational_schema import (
    FormationStance,
    MoveOrderStatus,
    OperationalMoveOrder,
    OperationalRouteEdge,
    PositionMode,
)

#: Orders in these statuses are locked: ``issue_move_order`` refuses to replace
#: them, so the formation has no selectable targets until resolution clears it.
LOCKED_ORDER_STATUSES = frozenset(
    {MoveOrderStatus.COMMITTED.value, MoveOrderStatus.ACTIVE.value}
)

#: Placeholder identity for validation-only orders. Preview orders are never
#: stored on the campaign, so they must not consume a real order id.
_PREVIEW_ORDER_ID = "preview-order"


def list_operational_move_options(
    state: CampaignState,
    faction: Faction | None = None,
    *,
    locked_stance: str = FormationStance.OPERATIONAL.value,
) -> list[dict[str, Any]]:
    """Return every legal graph route for ``faction``'s strategic formations.

    One row per (formation, destination node) using the deterministic least-cost
    allowlisted route. Returns an empty list when the campaign carries no
    operational graph authority; a missing graph is never silently replaced by
    province adjacency.
    """
    from .operational_ai import _build_graph_indexes
    from .operational_contact import formation_is_combat_capable
    from .operational_movement import (
        can_reserve_destination,
        validate_order_legality_for_commit,
    )
    from .operational_position import load_operational_graph_for_state

    if state.pending_battle is not None:
        # A pending battle halts operational resolution, so no order issued now
        # could ever run. Offering targets would be a dead control.
        return []
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return []
    edges_by_id, nodes_by_id, adjacency = _build_graph_indexes(graph)
    active = faction or state.current_faction

    options: list[dict[str, Any]] = []
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if force.faction != active:
            continue
        if not formation_is_combat_capable(state, force):
            continue
        order = force.move_order
        if order is not None and order.status in LOCKED_ORDER_STATUSES:
            continue
        for path_node_ids, path_edge_ids in _candidate_routes(
            force, adjacency=adjacency, edges_by_id=edges_by_id
        ):
            candidate = OperationalMoveOrder(
                order_id=_PREVIEW_ORDER_ID,
                formation_id=force.strategic_formation_id,
                path_node_ids=list(path_node_ids),
                path_edge_ids=list(path_edge_ids),
                destination_site_id=None,
                issued_tick=0,
                status=MoveOrderStatus.DRAFT.value,
            )
            try:
                validate_order_legality_for_commit(
                    state,
                    force,
                    candidate,
                    locked_stance=locked_stance,
                    graph=graph,
                )
            except (KeyError, TypeError, ValueError):
                continue
            destination_node = str(candidate.path_node_ids[-1])
            if not can_reserve_destination(
                state, force, destination_node, include_drafts=False, graph=graph
            ):
                continue
            options.append(
                _option_row(
                    state,
                    force,
                    candidate,
                    edges_by_id=edges_by_id,
                    nodes_by_id=nodes_by_id,
                    locked_stance=locked_stance,
                )
            )
    return options


def _candidate_routes(
    force: StrategicFormation,
    *,
    adjacency: dict[str, list[Any]],
    edges_by_id: dict[str, OperationalRouteEdge],
) -> list[tuple[list[str], list[str]]]:
    """Enumerate the least-cost allowlisted route to every reachable node.

    Node-anchored formations route from their node. Formations already on an
    edge must first finish that edge in the direction they face, so their routes
    carry the occupied hop as a mandatory prefix and may never re-enter it.
    """
    from .operational_ai import find_operational_path

    position = force.position
    if position is None:
        return []

    prefix_nodes: list[str] = []
    prefix_edges: list[str] = []
    forbidden_nodes: set[str] = set()
    forbidden_edges: set[str] = set()

    if position.mode == PositionMode.AT_NODE.value:
        start = str(position.node_id or "")
        if not start:
            return []
    elif position.mode == PositionMode.ON_EDGE.value:
        edge = edges_by_id.get(str(position.edge_id or ""))
        facing = str(position.facing_node_id or "")
        if edge is None or facing not in {edge.a, edge.b}:
            return []
        origin = edge.b if facing == edge.a else edge.a
        start = facing
        prefix_nodes = [origin]
        prefix_edges = [edge.edge_id]
        forbidden_nodes = {origin}
        forbidden_edges = {edge.edge_id}
    else:
        return []

    routes: list[tuple[list[str], list[str]]] = []
    if prefix_nodes:
        # Finishing the occupied edge is itself a legal order.
        routes.append(([prefix_nodes[0], start], list(prefix_edges)))
    for goal in sorted(adjacency):
        if goal == start or goal in forbidden_nodes:
            continue
        path = find_operational_path(
            start_node=start,
            goal_node=goal,
            adjacency=adjacency,
            forbidden_nodes=forbidden_nodes,
            forbidden_edges=forbidden_edges,
        )
        if path is None or not path.edge_ids:
            continue
        routes.append(
            (
                prefix_nodes + [str(item) for item in path.node_ids],
                prefix_edges + [str(item) for item in path.edge_ids],
            )
        )
    return routes


def _option_row(
    state: CampaignState,
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
    locked_stance: str,
) -> dict[str, Any]:
    origin_node = str(order.path_node_ids[0])
    target_node = str(order.path_node_ids[-1])
    first_edge = edges_by_id[str(order.path_edge_ids[0])]
    final_edge = edges_by_id[str(order.path_edge_ids[-1])]
    origin_province = _node_province(nodes_by_id, origin_node)
    target_province = _node_province(nodes_by_id, target_node)
    return {
        "formation_id": force.strategic_formation_id,
        "formation_display_name": force.display_name,
        "faction": force.faction.value,
        "origin_node_id": origin_node,
        "origin_province_id": origin_province,
        "origin_province_name": _province_name(state, origin_province),
        "target_node_id": target_node,
        "target_province_id": target_province,
        "target_province_name": _province_name(state, target_province),
        # Route identity for presentation caches; the path arrays stay canonical.
        "edge_id": final_edge.edge_id,
        "first_edge_id": first_edge.edge_id,
        "edge_kind": final_edge.kind,
        "edge_authority": final_edge.authority,
        "hop_count": len(order.path_edge_ids),
        "route_cost_milli": sum(
            int(edges_by_id[str(edge_id)].movement_cost_milli)
            for edge_id in order.path_edge_ids
        ),
        "path_node_ids": [str(item) for item in order.path_node_ids],
        "path_edge_ids": [str(item) for item in order.path_edge_ids],
        "locked_stance": str(locked_stance),
    }


def _node_province(nodes_by_id: dict[str, dict[str, Any]], node_id: str) -> str:
    node = nodes_by_id.get(str(node_id)) or {}
    return str(node.get("province_id") or "")


def _province_name(state: CampaignState, province_id: str) -> str:
    province = state.provinces.get(str(province_id))
    if province is None:
        return str(province_id)
    return str(province.display_name or province_id)
