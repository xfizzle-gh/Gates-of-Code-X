from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace as dc_replace
from heapq import heappop, heappush
from typing import Any

from .diplomacy import are_allied, is_friendly_owner
from .models import CampaignState, Faction, StrategicFormation
from .operational_capture import list_control_sites
from .operational_contact import (
    enemy_formations_at_node,
    formation_at_node_id,
    formations_at_node,
    node_is_contested,
)
from .operational_movement import (
    assert_stance_route_legal,
    can_reserve_destination,
    cancel_move_order,
    commit_formation_move_order,
    edge_is_traversable,
    issue_move_order,
)
from .operational_position import load_operational_graph_for_state
from .operational_schema import (
    FormationStance,
    MoveOrderStatus,
    OperationalMoveOrder,
    OperationalRouteEdge,
    PositionMode,
)
from .strategic_ai import StrategicAction

# Stances that must not receive a new movement order this slice.
_HOLD_STANCES = frozenset(
    {
        FormationStance.ENTRENCHED.value,
        FormationStance.REFIT_RESUPPLY.value,
        "entrenched",
        "refit_resupply",
    }
)
_LOCKED_ORDER = frozenset(
    {
        MoveOrderStatus.COMMITTED.value,
        MoveOrderStatus.ACTIVE.value,
    }
)


@dataclass(frozen=True, slots=True)
class _Hop:
    edge_id: str
    dest: str
    cost: int


@dataclass(frozen=True, slots=True)
class _Path:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    cost: int


def operational_graph_authority_present(state: CampaignState) -> bool:
    """True when the campaign has a loadable operational route graph."""
    return load_operational_graph_for_state(state) is not None


def plan_and_issue_operational_orders(
    state: CampaignState,
    faction: Faction,
    *,
    seed: int = 0,
) -> list[StrategicAction]:
    """Deterministic graph-native AI orders for one faction.

    Uses the same issue/commit path as the player. Does not advance ticks or
    mutate positions directly. ``seed`` is reserved for future ranking noise and
    is folded into stable order ids only (no RNG).
    """
    del seed  # determinism: no stochastic ranking in S7
    if state.pending_battle is not None:
        return [
            StrategicAction(
                battalion_id="",
                action="hold_pending_battle",
                details={"reason": "pending_battle"},
            )
        ]
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return []

    edges_by_id, nodes_by_id, adjacency = _build_graph_indexes(graph)
    actions: list[StrategicAction] = []
    batch_reservations: dict[str, int] = {}
    forces = sorted(
        (
            force
            for force in state.strategic_formations.values()
            if force.faction == faction
        ),
        key=lambda value: value.strategic_formation_id,
    )
    for force in forces:
        action = _plan_one_formation(
            state,
            force,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
            adjacency=adjacency,
            batch_reservations=batch_reservations,
        )
        actions.append(action)
    return actions


def find_operational_path(
    *,
    start_node: str,
    goal_node: str,
    adjacency: dict[str, list[_Hop]],
    forbidden_nodes: set[str] | frozenset[str] | None = None,
    forbidden_edges: set[str] | frozenset[str] | None = None,
) -> _Path | None:
    """Deterministic least-cost path. Ties broken by edge_id path then node path.

    ``forbidden_nodes`` / ``forbidden_edges`` are never entered (used for ON_EDGE
    tails so the planner cannot reverse back through the occupied prefix).
    """
    blocked_nodes = set(forbidden_nodes or ())
    blocked_edges = set(forbidden_edges or ())
    if start_node in blocked_nodes:
        return None
    if goal_node in blocked_nodes:
        return None
    if start_node == goal_node:
        return _Path(node_ids=(start_node,), edge_ids=(), cost=0)
    # heap: (cost, edge_ids_key, node_ids_key, node)
    heap: list[tuple[int, tuple[str, ...], tuple[str, ...], str]] = []
    heappush(heap, (0, (), (start_node,), start_node))
    best: dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]] = {
        start_node: (0, (), (start_node,))
    }
    came_from: dict[str, tuple[str, str]] = {}

    while heap:
        cost, edge_key, node_key, node = heappop(heap)
        recorded = best.get(node)
        if recorded is None or (cost, edge_key, node_key) != recorded:
            continue
        if node == goal_node:
            return _reconstruct_path(came_from, start_node, goal_node, cost)
        for hop in adjacency.get(node, ()):
            if hop.edge_id in blocked_edges:
                continue
            nxt = hop.dest
            if nxt in blocked_nodes:
                continue
            new_cost = cost + hop.cost
            new_edge_key = edge_key + (hop.edge_id,)
            new_node_key = node_key + (nxt,)
            candidate = (new_cost, new_edge_key, new_node_key)
            prev = best.get(nxt)
            if prev is not None and candidate >= prev:
                continue
            best[nxt] = candidate
            came_from[nxt] = (node, hop.edge_id)
            heappush(heap, (new_cost, new_edge_key, new_node_key, nxt))
    return None


def _plan_one_formation(
    state: CampaignState,
    force: StrategicFormation,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
    adjacency: dict[str, list[_Hop]],
    batch_reservations: dict[str, int],
) -> StrategicAction:
    fid = force.strategic_formation_id
    bn = force.battalion_ids[0] if force.battalion_ids else ""
    stance = _effective_stance(force)
    locked = (
        stance
        if stance in {item.value for item in FormationStance}
        else FormationStance.OPERATIONAL.value
    )

    if force.move_order is not None and force.move_order.status in _LOCKED_ORDER:
        return StrategicAction(
            battalion_id=bn,
            action="hold_locked_order",
            origin_province_id=force.province_id,
            details={
                "formation_id": fid,
                "reason": "committed_or_active_order",
                "order_status": force.move_order.status,
            },
        )

    if stance in _HOLD_STANCES:
        return StrategicAction(
            battalion_id=bn,
            action="hold",
            origin_province_id=force.province_id,
            details={
                "formation_id": fid,
                "reason": "stance_hold",
                "stance": stance,
            },
        )

    edge_prefix = _on_edge_route_prefix(force, edges_by_id=edges_by_id)
    if edge_prefix is not None:
        # Must finish the occupied edge in facing direction before any branch.
        search_start = edge_prefix["facing"]
        progress_before = int(edge_prefix["progress"])
    else:
        search_start = _formation_start_node(force, edges_by_id=edges_by_id)
        progress_before = 0
    if search_start is None:
        return StrategicAction(
            battalion_id=bn,
            action="hold",
            origin_province_id=force.province_id,
            details={"formation_id": fid, "reason": "no_start_node"},
        )

    goals = _ranked_goals(
        state,
        force,
        start_node=search_start,
        adjacency=adjacency,
        nodes_by_id=nodes_by_id,
        stance=stance,
    )
    # Completing the current edge (destination = facing) is always a candidate
    # when already ON_EDGE, even if facing is not a ranked objective site.
    if edge_prefix is not None:
        facing = edge_prefix["facing"]
        if not any(g[1] == facing for g in goals):
            goals = [(3, facing, "edge_continuation")] + list(goals)
            goals = sorted(goals, key=lambda row: (row[0], row[1]))

    last_reject_reason = (
        "no_valid_forward_continuation"
        if edge_prefix is not None
        else "no_valid_route"
    )
    for priority, goal_node, goal_kind in goals:
        built = _build_route_for_goal(
            start_search=search_start,
            goal_node=goal_node,
            adjacency=adjacency,
            edge_prefix=edge_prefix,
        )
        if built is None:
            continue
        path_nodes, path_edges = built
        if len(path_edges) < 1:
            continue
        if not can_reserve_destination(
            state,
            force,
            path_nodes[-1],
            batch_reservations=batch_reservations,
            include_drafts=False,
        ):
            last_reject_reason = "destination_capacity"
            continue
        probe = OperationalMoveOrder(
            order_id="probe",
            formation_id=fid,
            path_node_ids=list(path_nodes),
            path_edge_ids=list(path_edges),
            issued_tick=0,
            status=MoveOrderStatus.DRAFT.value,
        )
        try:
            assert_stance_route_legal(
                state, force, probe, locked_stance=locked
            )
        except ValueError as exc:
            last_reject_reason = str(exc) or "forced_march_hostile_path"
            continue
        try:
            order = issue_move_order(
                state,
                fid,
                path_node_ids=list(path_nodes),
                path_edge_ids=list(path_edges),
                order_id=_stable_order_id(state, fid, goal_node),
            )
            # Preserve ON_EDGE progress — issue must not reset position.
            if edge_prefix is not None and force.position is not None:
                force.position = dc_replace(
                    force.position, progress_milli=progress_before
                )
            commit_formation_move_order(
                state,
                fid,
                locked_stance=locked,
                batch_reservations=batch_reservations,
            )
        except ValueError as exc:
            from .operational_movement import classify_commit_rejection

            reason = classify_commit_rejection(exc)
            last_reject_reason = reason
            try:
                cancel_move_order(state, fid)
            except ValueError:
                force.move_order = None
            if reason in {
                "destination_capacity",
                "forced_march_hostile_path",
                "on_edge_desync",
                "no_valid_forward_continuation",
            }:
                continue
            return StrategicAction(
                battalion_id=bn,
                action="reject",
                origin_province_id=force.province_id,
                target_province_id=str(
                    (nodes_by_id.get(goal_node) or {}).get("province_id") or ""
                ),
                details={
                    "formation_id": fid,
                    "reason": reason,
                    "goal_node": goal_node,
                    "goal_kind": goal_kind,
                },
            )
        # Re-assert progress after commit (commit must not touch position).
        if edge_prefix is not None and force.position is not None:
            assert force.position.progress_milli == progress_before
        dest_province = str(
            (nodes_by_id.get(path_nodes[-1]) or {}).get("province_id")
            or force.province_id
        )
        return StrategicAction(
            battalion_id=bn,
            action="operational_move",
            origin_province_id=force.province_id,
            target_province_id=dest_province,
            details={
                "formation_id": fid,
                "goal_node": path_nodes[-1],
                "goal_kind": goal_kind,
                "priority": priority,
                "path_node_ids": list(path_nodes),
                "path_edge_ids": list(path_edges),
                "order_id": order.order_id,
                "locked_stance": locked,
                "progress_milli": progress_before,
            },
        )

    return StrategicAction(
        battalion_id=bn,
        action="hold"
        if last_reject_reason
        in {"no_valid_route", "no_valid_forward_continuation"}
        else "reject",
        origin_province_id=force.province_id,
        details={"formation_id": fid, "reason": last_reject_reason},
    )


def _on_edge_route_prefix(
    force: StrategicFormation,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> dict[str, Any] | None:
    """If ON_EDGE, return mandatory first-hop prefix in facing direction."""
    pos = force.position
    if pos is None or pos.mode != PositionMode.ON_EDGE.value:
        return None
    edge_id = str(pos.edge_id or "")
    edge = edges_by_id.get(edge_id)
    if edge is None:
        return None
    facing = str(pos.facing_node_id or "")
    if facing not in {edge.a, edge.b}:
        return None
    origin = edge.b if facing == edge.a else edge.a
    return {
        "edge_id": edge_id,
        "origin": origin,
        "facing": facing,
        "progress": int(pos.progress_milli),
    }


def _build_route_for_goal(
    *,
    start_search: str,
    goal_node: str,
    adjacency: dict[str, list[_Hop]],
    edge_prefix: dict[str, Any] | None,
) -> tuple[list[str], list[str]] | None:
    """Build full path_node_ids / path_edge_ids, honoring ON_EDGE prefix."""
    if edge_prefix is None:
        if goal_node == start_search:
            return None
        path = find_operational_path(
            start_node=start_search, goal_node=goal_node, adjacency=adjacency
        )
        if path is None or not path.edge_ids:
            return None
        return list(path.node_ids), list(path.edge_ids)

    origin = str(edge_prefix["origin"])
    facing = str(edge_prefix["facing"])
    first_edge = str(edge_prefix["edge_id"])
    if goal_node == facing:
        return [origin, facing], [first_edge]
    if goal_node == origin:
        # Reversal not allowed while ON_EDGE.
        return None
    # Tail must not return to origin, reuse the occupied edge, or revisit prefix.
    tail = find_operational_path(
        start_node=facing,
        goal_node=goal_node,
        adjacency=adjacency,
        forbidden_nodes={origin},
        forbidden_edges={first_edge},
    )
    if tail is None:
        return None
    # facing + tail nodes after facing; edges = first + tail edges
    nodes = [origin, facing] + list(tail.node_ids[1:])
    edges = [first_edge] + list(tail.edge_ids)
    if not edges:
        return None
    # Defensive: no repeated nodes/edges, origin only at index 0.
    if len(nodes) != len(set(nodes)) or len(edges) != len(set(edges)):
        return None
    if origin in nodes[1:]:
        return None
    if first_edge in edges[1:]:
        return None
    return nodes, edges


def _effective_stance(force: StrategicFormation) -> str:
    raw = str(force.stance or "").strip().lower()
    if raw in {item.value for item in FormationStance}:
        return raw
    # Legacy "standard" and unknowns map to operational movement authority.
    if raw in {"", "standard", "normal"}:
        return FormationStance.OPERATIONAL.value
    return raw


def _stable_order_id(state: CampaignState, formation_id: str, goal_node: str) -> str:
    turn = int(state.turn_number)
    # Keep ids filesystem-safe and deterministic.
    safe_goal = goal_node.replace("/", "_")
    return f"ord-ai-{formation_id}-t{turn}-{safe_goal}"


def _formation_start_node(
    force: StrategicFormation,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> str | None:
    """Search start for AT_NODE forces. ON_EDGE uses ``_on_edge_route_prefix``."""
    pos = force.position
    if pos is None:
        return None
    if pos.mode == PositionMode.AT_NODE.value and pos.node_id:
        return str(pos.node_id)
    return None


def _build_graph_indexes(
    graph: dict[str, Any],
) -> tuple[
    dict[str, OperationalRouteEdge],
    dict[str, dict[str, Any]],
    dict[str, list[_Hop]],
]:
    from .operational_movement import _indexes

    _node_ids, _edge_ids, edges_by_id, nodes_by_id = _indexes(graph)
    adjacency: dict[str, list[_Hop]] = defaultdict(list)
    for edge_id in sorted(edges_by_id):
        edge = edges_by_id[edge_id]
        if not edge_is_traversable(edge):
            continue
        cost = max(1, int(edge.movement_cost_milli))
        # Bidirectional or one-way a→b only (direction enforced at hop use).
        adjacency[edge.a].append(_Hop(edge_id=edge.edge_id, dest=edge.b, cost=cost))
        if edge.bidirectional:
            adjacency[edge.b].append(_Hop(edge_id=edge.edge_id, dest=edge.a, cost=cost))
    # Stable neighbor order for equal-cost expansion.
    for node_id in list(adjacency):
        adjacency[node_id] = sorted(
            adjacency[node_id], key=lambda hop: (hop.edge_id, hop.dest)
        )
    return edges_by_id, nodes_by_id, dict(adjacency)


def _ranked_goals(
    state: CampaignState,
    force: StrategicFormation,
    *,
    start_node: str,
    adjacency: dict[str, list[_Hop]],
    nodes_by_id: dict[str, dict[str, Any]],
    stance: str,
) -> list[tuple[int, str, str]]:
    """Return (priority, node_id, kind) sorted ascending priority then node_id."""
    sites = list_control_sites(state)
    goals: list[tuple[int, str, str]] = []

    # (a) hostile or contested control-site nodes
    for site in sites:
        node_id = str(site.get("route_node_id") or "")
        if not node_id or node_id not in nodes_by_id:
            continue
        province_id = str(site.get("province_id") or "")
        owner = _site_owner(state, site, province_id)
        contested = node_is_contested(state, node_id)
        hostile = owner is not None and owner != force.faction and not are_allied(
            state, force.faction, owner
        )
        if owner == Faction.NEUTRAL:
            hostile = True  # contested/neutral objective
        if contested or hostile:
            goals.append((0, node_id, "hostile_or_contested_site"))

    # (b) friendly threatened control-site nodes
    for site in sites:
        node_id = str(site.get("route_node_id") or "")
        if not node_id or node_id not in nodes_by_id:
            continue
        province_id = str(site.get("province_id") or "")
        owner = _site_owner(state, site, province_id)
        if owner is None:
            continue
        if owner != force.faction and not are_allied(state, force.faction, owner):
            continue
        if _node_threatened(state, node_id, faction=force.faction, adjacency=adjacency):
            goals.append((1, node_id, "threatened_friendly_site"))

    # (c) frontier nodes (friendly-owned province adjacent via graph to non-friendly)
    for node_id in sorted(nodes_by_id):
        province_id = str((nodes_by_id[node_id] or {}).get("province_id") or "")
        if not province_id or province_id not in state.provinces:
            continue
        province = state.provinces[province_id]
        if not is_friendly_owner(state, force.faction, province.owner):
            continue
        if _is_frontier_node(
            state,
            node_id,
            faction=force.faction,
            adjacency=adjacency,
            nodes_by_id=nodes_by_id,
        ):
            goals.append((2, node_id, "frontier_node"))

    # De-dupe by node keeping best priority.
    best: dict[str, tuple[int, str, str]] = {}
    for item in goals:
        prev = best.get(item[1])
        if prev is None or item < prev:
            best[item[1]] = item
    ranked = sorted(best.values(), key=lambda row: (row[0], row[1]))

    # Reachability filter with deterministic path presence.
    reachable: list[tuple[int, str, str]] = []
    for item in ranked:
        path = find_operational_path(
            start_node=start_node, goal_node=item[1], adjacency=adjacency
        )
        if path is not None:
            reachable.append(item)
    return reachable


def _site_owner(
    state: CampaignState, site: dict[str, Any], province_id: str
) -> Faction | None:
    from .operational_capture import ensure_site_control_state, get_site_control_state

    ensure_site_control_state(state)
    control = get_site_control_state(state)
    site_id = str(site.get("site_id") or "")
    row = control.get(site_id) if isinstance(control, dict) else None
    if isinstance(row, dict):
        owner_raw = row.get("controller_faction") or row.get("owner_faction")
        if owner_raw:
            try:
                return Faction(str(owner_raw))
            except ValueError:
                pass
    if province_id and province_id in state.provinces:
        return state.provinces[province_id].owner
    return None


def _node_threatened(
    state: CampaignState,
    node_id: str,
    *,
    faction: Faction,
    adjacency: dict[str, list[_Hop]],
) -> bool:
    if enemy_formations_at_node(state, node_id, faction=faction):
        return True
    for hop in adjacency.get(node_id, ()):
        if enemy_formations_at_node(state, hop.dest, faction=faction):
            return True
    return False


def _is_frontier_node(
    state: CampaignState,
    node_id: str,
    *,
    faction: Faction,
    adjacency: dict[str, list[_Hop]],
    nodes_by_id: dict[str, dict[str, Any]],
) -> bool:
    for hop in adjacency.get(node_id, ()):
        other = nodes_by_id.get(hop.dest) or {}
        pid = str(other.get("province_id") or "")
        if not pid or pid not in state.provinces:
            continue
        owner = state.provinces[pid].owner
        if owner == Faction.NEUTRAL or (
            owner != faction and not are_allied(state, faction, owner)
        ):
            return True
    return False


def _reconstruct_path(
    came_from: dict[str, tuple[str, str]],
    start: str,
    goal: str,
    cost: int,
) -> _Path:
    nodes: list[str] = [goal]
    edges: list[str] = []
    cur = goal
    while cur != start:
        prev, edge_id = came_from[cur]
        edges.append(edge_id)
        nodes.append(prev)
        cur = prev
    nodes.reverse()
    edges.reverse()
    return _Path(node_ids=tuple(nodes), edge_ids=tuple(edges), cost=cost)
