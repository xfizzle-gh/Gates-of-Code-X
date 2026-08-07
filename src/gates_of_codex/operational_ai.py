from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any

from .diplomacy import are_allied, is_friendly_owner
from .models import CampaignState, Faction, StrategicFormation
from .operational_capture import list_control_sites
from .operational_contact import (
    can_enter_node_friendly_stack,
    enemy_formations_at_node,
    formation_at_node_id,
    formations_at_node,
    node_is_contested,
)
from .operational_movement import commit_move_orders, issue_move_order
from .operational_position import load_operational_graph_for_state
from .operational_schema import (
    FormationStance,
    MoveOrderStatus,
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
        )
        actions.append(action)
    return actions


def find_operational_path(
    *,
    start_node: str,
    goal_node: str,
    adjacency: dict[str, list[_Hop]],
) -> _Path | None:
    """Deterministic least-cost path. Ties broken by edge_id path then node path."""
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
            nxt = hop.dest
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
) -> StrategicAction:
    fid = force.strategic_formation_id
    bn = force.battalion_ids[0] if force.battalion_ids else ""
    stance = _effective_stance(force)

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

    start = _formation_start_node(force, edges_by_id=edges_by_id)
    if start is None:
        return StrategicAction(
            battalion_id=bn,
            action="hold",
            origin_province_id=force.province_id,
            details={"formation_id": fid, "reason": "no_start_node"},
        )

    goals = _ranked_goals(
        state,
        force,
        start_node=start,
        adjacency=adjacency,
        nodes_by_id=nodes_by_id,
        stance=stance,
    )
    for priority, goal_node, goal_kind in goals:
        if goal_node == start:
            continue
        if not can_enter_node_friendly_stack(state, force, goal_node):
            # Destination full for friendlies — stable reject, try next goal.
            continue
        if stance == FormationStance.FORCED_MARCH.value:
            # Existing contract: forced march does not deliberately attack.
            if enemy_formations_at_node(
                state, goal_node, faction=force.faction, excluding_formation_id=fid
            ):
                continue
        path = find_operational_path(
            start_node=start, goal_node=goal_node, adjacency=adjacency
        )
        if path is None or not path.edge_ids:
            continue
        try:
            order = issue_move_order(
                state,
                fid,
                path_node_ids=list(path.node_ids),
                path_edge_ids=list(path.edge_ids),
                order_id=_stable_order_id(state, fid, goal_node),
            )
        except ValueError as exc:
            return StrategicAction(
                battalion_id=bn,
                action="reject",
                origin_province_id=force.province_id,
                target_province_id=str(
                    (nodes_by_id.get(goal_node) or {}).get("province_id") or ""
                ),
                details={
                    "formation_id": fid,
                    "reason": "issue_rejected",
                    "error": str(exc),
                    "goal_node": goal_node,
                    "goal_kind": goal_kind,
                },
            )
        commit_move_orders(
            state,
            faction=force.faction.value,
            locked_stance=stance
            if stance in {item.value for item in FormationStance}
            else FormationStance.OPERATIONAL.value,
        )
        dest_province = str(
            (nodes_by_id.get(goal_node) or {}).get("province_id") or force.province_id
        )
        return StrategicAction(
            battalion_id=bn,
            action="operational_move",
            origin_province_id=force.province_id,
            target_province_id=dest_province,
            details={
                "formation_id": fid,
                "goal_node": goal_node,
                "goal_kind": goal_kind,
                "priority": priority,
                "path_node_ids": list(path.node_ids),
                "path_edge_ids": list(path.edge_ids),
                "order_id": order.order_id,
                "locked_stance": stance
                if stance in {item.value for item in FormationStance}
                else FormationStance.OPERATIONAL.value,
            },
        )

    return StrategicAction(
        battalion_id=bn,
        action="hold",
        origin_province_id=force.province_id,
        details={"formation_id": fid, "reason": "no_valid_route"},
    )


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
    pos = force.position
    if pos is None:
        return None
    if pos.mode == PositionMode.AT_NODE.value and pos.node_id:
        return str(pos.node_id)
    if pos.mode == PositionMode.ON_EDGE.value and pos.edge_id:
        edge = edges_by_id.get(str(pos.edge_id))
        if edge is None:
            return None
        facing = str(pos.facing_node_id or "")
        if facing in {edge.a, edge.b}:
            # Path must start at an endpoint; prefer the origin side (not facing).
            return edge.b if facing == edge.a else edge.a
        return edge.a
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
        if not _edge_legally_usable(edge):
            continue
        cost = max(1, int(edge.movement_cost_milli))
        # Bidirectional or one-way a→b only.
        adjacency[edge.a].append(_Hop(edge_id=edge.edge_id, dest=edge.b, cost=cost))
        if edge.bidirectional:
            adjacency[edge.b].append(_Hop(edge_id=edge.edge_id, dest=edge.a, cost=cost))
    # Stable neighbor order for equal-cost expansion.
    for node_id in list(adjacency):
        adjacency[node_id] = sorted(
            adjacency[node_id], key=lambda hop: (hop.edge_id, hop.dest)
        )
    return edges_by_id, nodes_by_id, dict(adjacency)


def _edge_legally_usable(edge: OperationalRouteEdge) -> bool:
    """Authored-enabled edges only; honor existing block metadata."""
    if not edge.traversal_enabled:
        return False
    meta = edge.metadata or {}
    for key in ("blocked", "blockaded", "closed", "disabled"):
        if bool(meta.get(key)):
            return False
    # Candidate corridors must never be treated as authority.
    if str(edge.authority) == "candidate":
        return False
    return True


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
