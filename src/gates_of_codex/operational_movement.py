from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from .models import CampaignState, StrategicFormation
from .operational_position import (
    load_operational_graph_for_state,
    province_anchor_position,
)
from .operational_schema import (
    COST_MILLI_UNITY,
    PROGRESS_MILLI_MAX,
    FormationOperationalPosition,
    FormationStance,
    MoveOrderStatus,
    OperationalMoveOrder,
    OperationalRouteEdge,
    PositionMode,
    require_strict_int,
)

# Campaign clock keys in map_metadata (stable, no schema field required on CampaignState).
OPERATIONAL_CLOCK_KEY = "operational_clock"

_LOCKED_STATUSES = frozenset(
    {
        MoveOrderStatus.COMMITTED.value,
        MoveOrderStatus.ACTIVE.value,
    }
)
_APPROVED_STANCES = frozenset(item.value for item in FormationStance)


def move_order_to_dict(order: OperationalMoveOrder | None) -> dict[str, Any] | None:
    if order is None:
        return None
    return {
        "order_id": order.order_id,
        "formation_id": order.formation_id,
        "path_node_ids": list(order.path_node_ids),
        "path_edge_ids": list(order.path_edge_ids),
        "destination_site_id": order.destination_site_id,
        "issued_tick": int(order.issued_tick),
        "status": order.status,
        "committed_turn": order.committed_turn,
        "locked_stance": order.locked_stance,
    }


def move_order_from_dict(raw: Any) -> OperationalMoveOrder | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("move_order must be an object or null")
    if not raw:
        return None
    committed = raw.get("committed_turn")
    if committed is not None:
        committed = require_strict_int(committed, name="committed_turn", minimum=0)
    locked_stance = (
        None if raw.get("locked_stance") in (None, "") else str(raw.get("locked_stance"))
    )
    if locked_stance is not None and locked_stance not in _APPROVED_STANCES:
        raise ValueError(
            f"locked_stance must be one of {sorted(_APPROVED_STANCES)}, got {locked_stance!r}"
        )
    return OperationalMoveOrder(
        order_id=str(raw.get("order_id", "")),
        formation_id=str(raw.get("formation_id", "")),
        path_node_ids=[str(item) for item in raw.get("path_node_ids", [])],
        path_edge_ids=[str(item) for item in raw.get("path_edge_ids", [])],
        destination_site_id=(
            None
            if raw.get("destination_site_id") in (None, "")
            else str(raw.get("destination_site_id"))
        ),
        issued_tick=require_strict_int(raw.get("issued_tick", 0), name="issued_tick", minimum=0),
        status=str(raw.get("status", MoveOrderStatus.DRAFT.value)),
        committed_turn=committed,
        locked_stance=locked_stance,
    )


def get_operational_clock(state: CampaignState) -> dict[str, int]:
    raw = state.map_metadata.get(OPERATIONAL_CLOCK_KEY)
    if not isinstance(raw, dict):
        return {"global_tick": 0, "tick_in_turn": 0}
    return {
        "global_tick": int(raw.get("global_tick", 0)),
        "tick_in_turn": int(raw.get("tick_in_turn", 0)),
    }


def set_operational_clock(
    state: CampaignState, *, global_tick: int, tick_in_turn: int
) -> None:
    state.map_metadata[OPERATIONAL_CLOCK_KEY] = {
        "global_tick": int(global_tick),
        "tick_in_turn": int(tick_in_turn),
    }


def ticks_per_strategic_turn(state: CampaignState) -> int:
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return 10
    rules = graph.get("rules") or {}
    try:
        return max(1, int(rules.get("ticks_per_strategic_turn", 10)))
    except (TypeError, ValueError):
        return 10


def issue_move_order(
    state: CampaignState,
    formation_id: str,
    *,
    path_node_ids: list[str],
    path_edge_ids: list[str],
    destination_site_id: str | None = None,
    order_id: str | None = None,
) -> OperationalMoveOrder:
    """Create/replace a draft move order on a strategic formation (S3).

    Committed/active orders are locked and cannot be overwritten.
    """
    force = _require_formation(state, formation_id)
    existing = force.move_order
    if existing is not None and existing.status in _LOCKED_STATUSES:
        raise ValueError(
            f"formation {formation_id} has a {existing.status} order; "
            "committed movement cannot be changed or reversed"
        )
    graph = load_operational_graph_for_state(state)
    if graph is None:
        raise ValueError("operational graph unavailable; cannot issue graph move orders")
    node_ids, edge_ids, edges_by_id, nodes_by_id = _indexes(graph)
    site_ids = {str(site.get("site_id")) for site in graph.get("sites") or [] if site.get("site_id")}
    clock = get_operational_clock(state)
    order = OperationalMoveOrder(
        order_id=order_id or f"ord-{uuid.uuid4().hex[:12]}",
        formation_id=formation_id,
        path_node_ids=list(path_node_ids),
        path_edge_ids=list(path_edge_ids),
        destination_site_id=destination_site_id,
        issued_tick=int(clock["global_tick"]),
        status=MoveOrderStatus.DRAFT.value,
    )
    _validate_order_against_graph(
        order,
        force=force,
        node_ids=node_ids,
        edge_ids=edge_ids,
        site_ids=site_ids,
        edges_by_id=edges_by_id,
        nodes_by_id=nodes_by_id,
        require_start_match=True,
    )
    force.move_order = order
    return order


def cancel_move_order(state: CampaignState, formation_id: str) -> OperationalMoveOrder | None:
    """Cancel a draft order only. Committed/active orders are locked."""
    force = _require_formation(state, formation_id)
    order = force.move_order
    if order is None:
        return None
    if order.status in _LOCKED_STATUSES:
        raise ValueError(
            f"formation {formation_id} has a {order.status} order; "
            "committed movement cannot be cancelled"
        )
    if order.status in {
        MoveOrderStatus.COMPLETED.value,
        MoveOrderStatus.CANCELLED.value,
        MoveOrderStatus.BLOCKED.value,
    }:
        # Terminal / non-planning: clear slot.
        force.move_order = None
        return order
    if order.status == MoveOrderStatus.DRAFT.value:
        force.move_order = None
        return order
    raise ValueError(f"cannot cancel move order in status {order.status}")


def commit_move_orders(
    state: CampaignState,
    *,
    faction: str | None = None,
    locked_stance: str = FormationStance.OPERATIONAL.value,
) -> list[str]:
    """Promote draft orders to committed for the current strategic turn."""
    if locked_stance not in _APPROVED_STANCES:
        raise ValueError(
            f"locked_stance must be one of {sorted(_APPROVED_STANCES)}, got {locked_stance!r}"
        )
    committed_ids: list[str] = []
    turn = int(state.turn_number)
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if faction is not None and force.faction.value != faction:
            continue
        order = force.move_order
        if order is None or order.status != MoveOrderStatus.DRAFT.value:
            continue
        force.move_order = replace(
            order,
            status=MoveOrderStatus.COMMITTED.value,
            committed_turn=turn,
            locked_stance=str(locked_stance),
        )
        committed_ids.append(force.strategic_formation_id)
    return committed_ids


def activate_committed_orders(state: CampaignState) -> int:
    """Promote committed orders due for this resolution to active.

    Activates orders whose ``committed_turn`` is unset or ``<=`` the current
    campaign turn (orders locked during turn N resolve when turn N ends).
    Future-dated commits (``committed_turn > turn``) stay waiting.
    """
    count = 0
    turn = int(state.turn_number)
    for force in state.strategic_formations.values():
        order = force.move_order
        if order is None:
            continue
        if order.status != MoveOrderStatus.COMMITTED.value:
            continue
        if order.committed_turn is not None and int(order.committed_turn) > turn:
            continue
        force.move_order = replace(order, status=MoveOrderStatus.ACTIVE.value)
        count += 1
    return count


def ensure_move_orders(state: CampaignState) -> dict[str, Any]:
    """Idempotent graph-aware validation of saved move orders.

    When the graph is available: validate each order (path, traversal, direction,
    commitment shape). Malformed orders become ``blocked`` (not silently dropped).
    When the graph is unavailable: leave all orders completely unchanged.
    """
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {"validated": False, "reason": "no_graph", "blocked": []}
    node_ids, edge_ids, edges_by_id, nodes_by_id = _indexes(graph)
    site_ids = {str(site.get("site_id")) for site in graph.get("sites") or [] if site.get("site_id")}
    blocked: list[str] = []
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        order = force.move_order
        if order is None:
            continue
        if order.status in {
            MoveOrderStatus.COMPLETED.value,
            MoveOrderStatus.CANCELLED.value,
        }:
            continue
        try:
            _validate_order_against_graph(
                order,
                force=force,
                node_ids=node_ids,
                edge_ids=edge_ids,
                site_ids=site_ids,
                edges_by_id=edges_by_id,
                nodes_by_id=nodes_by_id,
                # Mid-path active orders need not start at path[0].
                require_start_match=order.status == MoveOrderStatus.DRAFT.value,
            )
            if order.formation_id and order.formation_id != force.strategic_formation_id:
                raise ValueError("formation_id mismatch")
        except (TypeError, ValueError, KeyError):
            force.move_order = _as_blocked(order)
            blocked.append(force.strategic_formation_id)
    return {"validated": True, "blocked": blocked}


def advance_operational_tick(state: CampaignState) -> dict[str, Any]:
    """Advance all active orders by one operational tick.

    S4: enemy node contact stops movement and may create a pending battle.
    Friendly stack caps block entry. Full edge interception is out of scope.
    """
    if state.pending_battle is not None:
        return {
            "advanced": False,
            "reason": "pending_battle",
            "moved": [],
            "contacts": [],
        }
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {"advanced": False, "reason": "no_graph", "moved": [], "contacts": []}

    from .operational_contact import detect_static_node_contacts

    # Active movers resolve first (stack-cap / entry contact), then residual static contacts.
    _node_ids, _edge_ids, edges_by_id, nodes_by_id = _indexes(graph)
    moved: list[str] = []
    contacts: list[str] = []
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if state.pending_battle is not None:
            break
        order = force.move_order
        if order is None or order.status != MoveOrderStatus.ACTIVE.value:
            continue
        if _advance_formation_one_tick(
            state,
            force,
            order,
            edges_by_id=edges_by_id,
            nodes_by_id=nodes_by_id,
            contacts_out=contacts,
        ):
            moved.append(force.strategic_formation_id)

    static_contacts: list[str] = []
    if state.pending_battle is None:
        static_contacts = detect_static_node_contacts(state)
        if static_contacts:
            contacts.extend(static_contacts)

    capture_report: dict[str, Any] = {"advanced": False}
    if state.pending_battle is None:
        from .operational_capture import advance_site_capture

        capture_report = advance_site_capture(state)

    clock = get_operational_clock(state)
    ticks_n = ticks_per_strategic_turn(state)
    global_tick = int(clock["global_tick"]) + 1
    tick_in_turn = (int(clock["tick_in_turn"]) + 1) % ticks_n
    set_operational_clock(state, global_tick=global_tick, tick_in_turn=tick_in_turn)
    return {
        "advanced": True,
        "global_tick": global_tick,
        "tick_in_turn": tick_in_turn,
        "moved": moved,
        "contacts": contacts,
        "battle_id": state.pending_battle.battle_id if state.pending_battle else "",
        "static_contact": bool(static_contacts),
        "capture": capture_report,
    }


def advance_operational_ticks(state: CampaignState, count: int | None = None) -> dict[str, Any]:
    n = ticks_per_strategic_turn(state) if count is None else max(0, int(count))
    reports: list[dict[str, Any]] = []
    for _ in range(n):
        report = advance_operational_tick(state)
        reports.append(report)
        if state.pending_battle is not None:
            break
        if not report.get("advanced") and report.get("reason") in {
            "no_graph",
            "pending_battle",
            "static_contact",
        }:
            break
    return {"ticks": len(reports), "reports": reports}


def resolve_strategic_turn_movement(state: CampaignState) -> dict[str, Any]:
    """Full strategic-turn movement resolve: commit drafts → activate → N ticks.

    Called once per strategic round rollover (not per faction end_turn).
    Skips entirely when no operational graph is available.
    """
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return {"resolved": False, "reason": "no_graph"}
    ensure_move_orders(state)
    committed = commit_move_orders(state)
    activated = activate_committed_orders(state)
    clock = get_operational_clock(state)
    set_operational_clock(state, global_tick=int(clock["global_tick"]), tick_in_turn=0)
    batch = advance_operational_ticks(state, ticks_per_strategic_turn(state))
    return {
        "resolved": True,
        "committed_formations": committed,
        "activated": activated,
        "ticks": batch["ticks"],
    }


def sync_province_from_position(state: CampaignState, force: StrategicFormation) -> None:
    """Derive province_id from operational position and co-locate battalions.

    On-edge positions keep the **origin** endpoint province until the formation
    arrives at the destination node.
    """
    graph = load_operational_graph_for_state(state)
    if graph is None or force.position is None:
        return
    _, _, edges_by_id, nodes_by_id = _indexes(graph)
    province_id = _province_for_position(
        force.position, nodes_by_id=nodes_by_id, edges_by_id=edges_by_id
    )
    if not province_id or province_id not in state.provinces:
        return
    force.province_id = province_id
    for battalion_id in force.battalion_ids:
        battalion = state.battalions.get(battalion_id)
        if battalion is not None:
            battalion.province_id = province_id


def _advance_formation_one_tick(
    state: CampaignState,
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
    contacts_out: list[str] | None = None,
) -> bool:
    from .operational_contact import inspect_node_entry, resolve_node_entry_contact

    if force.position is None:
        force.position = province_anchor_position(force.province_id)
    position = force.position
    assert position is not None

    edge_index, desync = _current_edge_index(position, order)
    if desync:
        force.move_order = _as_blocked(order)
        return False
    if edge_index is None:
        # True arrival at final path node only.
        if (
            position.mode == PositionMode.AT_NODE.value
            and order.path_node_ids
            and str(position.node_id) == order.path_node_ids[-1]
        ):
            force.move_order = replace(order, status=MoveOrderStatus.COMPLETED.value)
            force.movement_state = "at_anchor"
            sync_province_from_position(state, force)
            return False
        force.move_order = _as_blocked(order)
        return False

    edge_id = order.path_edge_ids[edge_index]
    edge = edges_by_id.get(edge_id)
    if edge is None:
        force.move_order = _as_blocked(order)
        return False
    dest_node = order.path_node_ids[edge_index + 1]
    origin_node = order.path_node_ids[edge_index]

    # Enter edge if still at origin node.
    if position.mode == PositionMode.AT_NODE.value:
        if position.node_id != origin_node:
            force.move_order = _as_blocked(order)
            return False
        try:
            _assert_edge_direction(edge, origin=origin_node, dest=dest_node)
        except ValueError:
            force.move_order = _as_blocked(order)
            return False
        position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=edge_id,
            progress_milli=0,
            facing_node_id=dest_node,
        )
        force.position = position
        force.movement_state = "on_route"
        # Stay on origin province while on edge (including progress 0).
        sync_province_from_position(state, force)

    if position.mode != PositionMode.ON_EDGE.value or position.edge_id != edge_id:
        force.move_order = _as_blocked(order)
        return False

    cost = max(1, int(edge.movement_cost_milli))
    base_mp = max(1, int(edge.base_move_points_milli or COST_MILLI_UNITY))
    stance_milli = _stance_speed_milli(order.locked_stance)
    if stance_milli <= 0:
        return False
    delta = max(1, (base_mp * stance_milli) // cost)
    new_progress = int(position.progress_milli) + delta
    if new_progress >= PROGRESS_MILLI_MAX:
        # Capture pre-entry province before destination sync (handoff/reporting).
        origin_province_id = force.province_id
        # Pre-check stack only (no battle yet) before committing to the node.
        pre = inspect_node_entry(state, force, dest_node)
        if pre["reason"] == "friendly_stack_cap":
            # Deterministic snap back to last legal node (this hop's origin).
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=origin_node,
                progress_milli=0,
            )
            force.movement_state = "at_anchor"
            force.move_order = _as_blocked(order)
            sync_province_from_position(state, force)
            return False
        force.position = FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=dest_node,
            progress_milli=0,
        )
        force.movement_state = "at_anchor"
        sync_province_from_position(state, force)
        contact = resolve_node_entry_contact(
            state,
            force,
            dest_node,
            create_battle=True,
            origin_province_id=origin_province_id,
        )
        if contact["reason"] == "enemy_contact":
            force.move_order = _as_blocked(order)
            if contacts_out is not None:
                contacts_out.append(force.strategic_formation_id)
                contacts_out.extend(contact.get("enemies") or [])
            return True
        if contact["reason"] == "invalid_contact_roster":
            # Empty/invalid enemy roster: refuse co-location deadlock — snap back.
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=origin_node,
                progress_milli=0,
            )
            force.movement_state = "at_anchor"
            force.move_order = _as_blocked(order)
            sync_province_from_position(state, force)
            return False
        if edge_index + 1 >= len(order.path_edge_ids):
            force.move_order = replace(order, status=MoveOrderStatus.COMPLETED.value)
        return True

    force.position = FormationOperationalPosition(
        mode=PositionMode.ON_EDGE.value,
        edge_id=edge_id,
        progress_milli=new_progress,
        facing_node_id=dest_node,
    )
    force.movement_state = "on_route"
    # Still origin province until node arrival.
    sync_province_from_position(state, force)
    return True


def _current_edge_index(
    position: FormationOperationalPosition,
    order: OperationalMoveOrder,
) -> tuple[int | None, bool]:
    """Return (edge_index, desync).

    ``edge_index is None`` and ``desync is False`` means true completion at final node.
    ``desync is True`` means position/path mismatch → must block, never complete.
    """
    if not order.path_edge_ids or not order.path_node_ids:
        return None, True
    if position.mode == PositionMode.ON_EDGE.value:
        try:
            index = order.path_edge_ids.index(str(position.edge_id))
        except ValueError:
            return None, True
        # Facing should match path destination for this hop.
        expected_dest = order.path_node_ids[index + 1]
        if position.facing_node_id and str(position.facing_node_id) != expected_dest:
            return None, True
        return index, False
    if position.mode == PositionMode.AT_NODE.value:
        node_id = str(position.node_id)
        if node_id == order.path_node_ids[-1]:
            return None, False
        for index, path_node in enumerate(order.path_node_ids[:-1]):
            if path_node == node_id:
                return index, False
        return None, True
    return None, True


def _as_blocked(order: OperationalMoveOrder) -> OperationalMoveOrder:
    """Mark blocked with a valid commitment pair (both present, or neither)."""
    has_turn = order.committed_turn is not None
    has_stance = order.locked_stance is not None
    if has_turn and has_stance:
        return replace(order, status=MoveOrderStatus.BLOCKED.value)
    return replace(
        order,
        status=MoveOrderStatus.BLOCKED.value,
        committed_turn=None,
        locked_stance=None,
    )


def _stance_speed_milli(stance: str | None) -> int:
    """Speed multiplier in milli (1000 = 1.0x)."""
    if stance == FormationStance.FORCED_MARCH.value:
        return 1500
    if stance == FormationStance.ENTRENCHED.value:
        return 0
    if stance == FormationStance.REFIT_RESUPPLY.value:
        return 500
    return COST_MILLI_UNITY


def _validate_order_against_graph(
    order: OperationalMoveOrder,
    *,
    force: StrategicFormation,
    node_ids: set[str],
    edge_ids: set[str],
    site_ids: set[str],
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
    require_start_match: bool,
) -> None:
    order.validate(
        node_ids=node_ids,
        edge_ids=edge_ids,
        site_ids=site_ids,
        edges_by_id=edges_by_id,
    )
    _assert_path_legal_for_s3(order, edges_by_id=edges_by_id)
    if require_start_match:
        _assert_order_starts_at_formation(
            force, order, nodes_by_id=nodes_by_id, edges_by_id=edges_by_id
        )


def _assert_path_legal_for_s3(
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> None:
    """S3: traversal_enabled only; respect one-way edges."""
    for index, edge_id in enumerate(order.path_edge_ids):
        edge = edges_by_id[edge_id]
        if not edge.traversal_enabled:
            raise ValueError(
                f"path edge {edge_id} is not traversal_enabled "
                "(candidate corridors are not gameplay-authoritative in S3)"
            )
        origin = order.path_node_ids[index]
        dest = order.path_node_ids[index + 1]
        _assert_edge_direction(edge, origin=origin, dest=dest)


def _assert_edge_direction(
    edge: OperationalRouteEdge, *, origin: str, dest: str
) -> None:
    endpoints = {edge.a, edge.b}
    if origin not in endpoints or dest not in endpoints or origin == dest:
        raise ValueError(f"edge {edge.edge_id} does not connect {origin} -> {dest}")
    if edge.bidirectional:
        return
    # One-way: only a → b is legal (canonical authored direction).
    if not (origin == edge.a and dest == edge.b):
        raise ValueError(
            f"edge {edge.edge_id} is one-way ({edge.a} -> {edge.b}); "
            f"cannot traverse {origin} -> {dest}"
        )


def _assert_order_starts_at_formation(
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
    edges_by_id: dict[str, OperationalRouteEdge],
) -> None:
    if force.position is None:
        return
    start = order.path_node_ids[0]
    pos = force.position
    if pos.mode == PositionMode.AT_NODE.value:
        if pos.node_id != start:
            raise ValueError(
                f"order path must start at formation node {pos.node_id}, got {start}"
            )
        return
    if pos.mode == PositionMode.ON_EDGE.value:
        edge = edges_by_id.get(str(pos.edge_id))
        if edge is None:
            raise ValueError("formation is on unknown edge")
        if start not in {edge.a, edge.b}:
            raise ValueError(
                "order path must start at an endpoint of the formation's current edge"
            )


def _province_for_position(
    position: FormationOperationalPosition,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
    edges_by_id: dict[str, OperationalRouteEdge],
) -> str | None:
    if position.mode == PositionMode.AT_NODE.value:
        node = nodes_by_id.get(str(position.node_id))
        return None if node is None else str(node.get("province_id") or "") or None
    if position.mode == PositionMode.ON_EDGE.value:
        edge = edges_by_id.get(str(position.edge_id))
        if edge is None:
            return None
        # Remain on origin province until destination node arrival.
        facing = str(position.facing_node_id or "")
        origin = edge.b if facing == edge.a else edge.a
        if facing and facing in {edge.a, edge.b}:
            origin = edge.b if facing == edge.a else edge.a
        node = nodes_by_id.get(origin)
        if node is not None:
            return str(node.get("province_id") or "") or None
    return None


def _require_formation(state: CampaignState, formation_id: str) -> StrategicFormation:
    force = state.strategic_formations.get(formation_id)
    if force is None:
        raise KeyError(f"Unknown strategic formation: {formation_id}")
    return force


def _indexes(graph: dict[str, Any]) -> tuple[
    set[str],
    set[str],
    dict[str, OperationalRouteEdge],
    dict[str, dict[str, Any]],
]:
    nodes_by_id = {str(node["node_id"]): node for node in graph.get("nodes") or []}
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
    return set(nodes_by_id), set(edges_by_id), edges_by_id, nodes_by_id
