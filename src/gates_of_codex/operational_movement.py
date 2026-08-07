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
    rejections_out: list[dict[str, str]] | None = None,
) -> list[str]:
    """Promote draft orders to committed (two-phase).

    Phase A — legality (graph/path/direction/authority/metadata/stance) for all
    drafts in stable formation-id order. Invalid drafts are blocked and never
    consume destination capacity.

    Phase B — destination capacity among only Phase-A-valid candidates, counting
    existing allied committed/active reservations plus this pass's commits.

    Optional ``rejections_out`` receives ``{formation_id, reason}`` rows with
    stable reason tokens. Return value remains the committed formation id list.
    """
    report = commit_move_orders_detailed(
        state, faction=faction, locked_stance=locked_stance
    )
    if rejections_out is not None:
        rejections_out.extend(report["rejected"])
    return list(report["committed"])


def commit_move_orders_detailed(
    state: CampaignState,
    *,
    faction: str | None = None,
    locked_stance: str = FormationStance.OPERATIONAL.value,
) -> dict[str, Any]:
    """Two-phase bulk commit with stable rejection reasons.

    Returns ``{"committed": [formation_id, ...], "rejected": [{"formation_id", "reason"}, ...]}``.
    """
    if locked_stance not in _APPROVED_STANCES:
        raise ValueError(
            f"locked_stance must be one of {sorted(_APPROVED_STANCES)}, got {locked_stance!r}"
        )
    locked = str(locked_stance)
    turn = int(state.turn_number)
    rejected: list[dict[str, str]] = []
    # Phase A — legality only (no capacity).
    valid: list[tuple[StrategicFormation, OperationalMoveOrder]] = []
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if faction is not None and force.faction.value != faction:
            continue
        order = force.move_order
        if order is None or order.status != MoveOrderStatus.DRAFT.value:
            continue
        try:
            validate_order_legality_for_commit(
                state, force, order, locked_stance=locked
            )
        except ValueError as exc:
            reason = classify_commit_rejection(exc)
            force.move_order = _as_blocked(order)
            rejected.append(
                {"formation_id": force.strategic_formation_id, "reason": reason}
            )
            continue
        valid.append((force, order))

    # Phase B — capacity among valid candidates only. Each successful commit
    # becomes a live committed reservation for the next candidate (no batch
    # double-count). Invalid drafts were already removed in Phase A.
    committed_ids: list[str] = []
    for force, order in valid:
        dest = str(order.path_node_ids[-1]) if order.path_node_ids else ""
        if not dest or not can_reserve_destination(
            state,
            force,
            dest,
            include_drafts=False,
        ):
            force.move_order = _as_blocked(order)
            rejected.append(
                {
                    "formation_id": force.strategic_formation_id,
                    "reason": "destination_capacity",
                }
            )
            continue
        force.move_order = replace(
            order,
            status=MoveOrderStatus.COMMITTED.value,
            committed_turn=turn,
            locked_stance=locked,
        )
        committed_ids.append(force.strategic_formation_id)
    return {"committed": committed_ids, "rejected": rejected}


def commit_formation_move_order(
    state: CampaignState,
    formation_id: str,
    *,
    locked_stance: str = FormationStance.OPERATIONAL.value,
    batch_reservations: dict[str, int] | None = None,
) -> None:
    """Commit one formation's draft after shared validation.

    Raises ``ValueError`` with a stable reason token on rejection.
    """
    if locked_stance not in _APPROVED_STANCES:
        raise ValueError(
            f"locked_stance must be one of {sorted(_APPROVED_STANCES)}, got {locked_stance!r}"
        )
    force = _require_formation(state, formation_id)
    order = force.move_order
    if order is None or order.status != MoveOrderStatus.DRAFT.value:
        raise ValueError("no_draft_order")
    locked = str(locked_stance)
    validate_order_legality_for_commit(
        state, force, order, locked_stance=locked
    )
    reservations = batch_reservations if batch_reservations is not None else {}
    if not order.path_node_ids:
        raise ValueError("invalid_path")
    dest = str(order.path_node_ids[-1])
    if not can_reserve_destination(
        state,
        force,
        dest,
        batch_reservations=reservations,
        include_drafts=False,
    ):
        raise ValueError("destination_capacity")
    force.move_order = replace(
        order,
        status=MoveOrderStatus.COMMITTED.value,
        committed_turn=int(state.turn_number),
        locked_stance=locked,
    )
    # Committed order is live in state; callers must not also bump batch_reservations.


def validate_order_legality_for_commit(
    state: CampaignState,
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    locked_stance: str,
) -> None:
    """Phase-A gates: path legality + stance (no capacity)."""
    if locked_stance not in _APPROVED_STANCES:
        raise ValueError(
            f"locked_stance must be one of {sorted(_APPROVED_STANCES)}, got {locked_stance!r}"
        )
    graph = load_operational_graph_for_state(state)
    if graph is None:
        raise ValueError("no_graph")
    node_ids, edge_ids, edges_by_id, nodes_by_id = _indexes(graph)
    site_ids = {
        str(site.get("site_id"))
        for site in graph.get("sites") or []
        if site.get("site_id")
    }
    try:
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
    except ValueError as exc:
        raise ValueError(classify_commit_rejection(exc)) from exc
    assert_stance_route_legal(
        state, force, order, locked_stance=str(locked_stance)
    )
    if not order.path_node_ids or not order.path_edge_ids:
        raise ValueError("invalid_path")


def validate_order_for_commit(
    state: CampaignState,
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    locked_stance: str,
    batch_reservations: dict[str, int] | None = None,
) -> None:
    """Full pre-commit gates (legality + capacity). Raises stable reason tokens."""
    validate_order_legality_for_commit(
        state, force, order, locked_stance=locked_stance
    )
    dest = str(order.path_node_ids[-1])
    if not can_reserve_destination(
        state,
        force,
        dest,
        batch_reservations=batch_reservations,
        include_drafts=False,
    ):
        raise ValueError("destination_capacity")


def classify_commit_rejection(exc: BaseException) -> str:
    """Map validator errors to stable bulk-commit reason tokens."""
    msg = str(exc)
    if msg in {
        "destination_capacity",
        "forced_march_hostile_path",
        "candidate_edge",
        "metadata_blocked",
        "one_way_reverse",
        "invalid_path",
        "no_graph",
        "no_draft_order",
        "empty_path",
        "on_edge_desync",
        "on_edge_reverse",
    }:
        return msg
    lower = msg.lower()
    if "forced_march" in lower:
        return "forced_march_hostile_path"
    if "destination_capacity" in lower or "capacity" in lower:
        return "destination_capacity"
    if "candidate" in lower:
        return "candidate_edge"
    if any(k in lower for k in ("blocked", "blockaded", "closed", "disabled")):
        return "metadata_blocked"
    if "one-way" in lower or "one_way" in lower:
        return "one_way_reverse"
    if "on_edge_reverse" in lower:
        return "on_edge_reverse"
    if "on_edge" in lower or "facing" in lower or "current edge" in lower:
        return "on_edge_desync"
    return "invalid_path"


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
    """Advance all active orders by one operational tick (two-phase swept contact).

    Phase 1: compute intended intervals from a frozen snapshot and detect contacts.
    Phase 2: apply the primary contact (if any) or normal movement, then static
    node contacts and site capture when no battle is pending.
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

    from .operational_contact import (
        detect_static_node_contacts,
        try_create_edge_contact_battle,
    )
    from .operational_interception import (
        ENCOUNTER_KIND_EDGE_CATCHUP,
        ENCOUNTER_KIND_EDGE_CROSS,
        ENCOUNTER_KIND_NODE_SIMULTANEOUS,
        apply_edge_contact_stop,
        compute_movement_intervals,
        detect_swept_contacts,
        encounter_pixel_for_edge,
        encounter_province_for_edge,
        select_primary_contact,
    )

    _node_ids, _edge_ids, edges_by_id, nodes_by_id = _indexes(graph)
    # Phase 1 — frozen snapshot intervals (no mutations yet).
    intervals = compute_movement_intervals(
        state, edges_by_id=edges_by_id, nodes_by_id=nodes_by_id
    )
    swept = detect_swept_contacts(
        state, intervals, edges_by_id=edges_by_id, nodes_by_id=nodes_by_id
    )
    primary = select_primary_contact(swept)
    moved: list[str] = []
    contacts: list[str] = []
    skipped: set[str] = set()

    # Single-battle model: earliest contact consumes the entire remaining tick.
    # Non-participants do not continue moving once a battle is created.
    if primary is not None and primary.kind in {
        ENCOUNTER_KIND_EDGE_CROSS,
        ENCOUNTER_KIND_EDGE_CATCHUP,
    }:
        from .operational_interception import expand_edge_participants_exact

        edge = edges_by_id[primary.edge_id]
        expanded = expand_edge_participants_exact(
            state,
            edge=edge,
            progress_canonical=primary.progress_canonical,
            seed_ids=primary.participant_ids,
        )
        expanded = tuple(sorted(set(expanded) | set(primary.participant_ids)))
        # Stationary exact-progress allies need retreat endpoints too.
        retreat_extra: list[tuple[str, str]] = []
        for fid in expanded:
            if any(a == fid for a, _ in primary.retreat_nodes):
                continue
            force = state.strategic_formations.get(fid)
            if force is None or force.position is None:
                continue
            # Prefer non-facing endpoint as last legal node when already on edge.
            if force.position.mode == PositionMode.ON_EDGE.value and force.position.facing_node_id:
                facing = str(force.position.facing_node_id)
                origin = edge.b if facing == edge.a else edge.a
                retreat_extra.append((fid, origin))
        if retreat_extra:
            primary = replace(
                primary,
                retreat_nodes=tuple(
                    sorted(set(primary.retreat_nodes) | set(retreat_extra))
                ),
            )

        attacker = state.strategic_formations.get(primary.attacker_id)
        defender = state.strategic_formations.get(primary.defender_id)
        snapshot = _snapshot_formation_locations(state, expanded)
        if attacker is not None and defender is not None:
            # Preflight every expanded participant has a valid battalion roster.
            preflight_ok = True
            for fid in expanded:
                force = state.strategic_formations.get(fid)
                if force is None or not any(
                    bid in state.battalions for bid in force.battalion_ids
                ):
                    preflight_ok = False
                    break
            if preflight_ok:
                apply_edge_contact_stop(
                    state,
                    primary,
                    intervals,
                    edges_by_id=edges_by_id,
                    nodes_by_id=nodes_by_id,
                    participant_ids=expanded,
                )
                pixel = encounter_pixel_for_edge(
                    edge=edge,
                    nodes_by_id=nodes_by_id,
                    progress_canonical=primary.progress_canonical,
                )
                province_id = encounter_province_for_edge(
                    edge=edge,
                    nodes_by_id=nodes_by_id,
                    progress_canonical=primary.progress_canonical,
                )
                atk_interval = next(
                    (
                        item
                        for item in intervals
                        if item.formation_id == primary.attacker_id
                    ),
                    None,
                )
                battle = try_create_edge_contact_battle(
                    state,
                    attacker=attacker,
                    defender=defender,
                    edge_id=primary.edge_id,
                    progress_canonical=primary.progress_canonical,
                    encounter_kind=primary.kind,
                    encounter_pixel=pixel,
                    encounter_province_id=province_id,
                    origin_province_id=(
                        atk_interval.origin_province_id if atk_interval else None
                    ),
                    participant_ids=expanded,
                    edge=edge,
                )
                if battle is None:
                    _restore_formation_locations(state, snapshot)
                else:
                    contacts.extend(expanded)
                    skipped.update(expanded)
    elif primary is not None and primary.kind in {
        ENCOUNTER_KIND_NODE_SIMULTANEOUS,
        "node_contact",
    }:
        from .operational_interception import (
            apply_simultaneous_node_arrivals,
            arrival_matches_contact_time,
            reject_overflow_arrivals_at_node,
        )
        from .operational_contact import try_create_node_contact_battle

        # Only intervals arriving at the selected candidate's exact time.
        same_time_arrivals = [
            i for i in intervals if arrival_matches_contact_time(i, primary)
        ]
        has_arrivals = bool(same_time_arrivals)
        # Snapshot participants + same-time arrivals + later same-node arrivals
        # (later ones may be stack-cap rejected when static t=0 wins).
        arrival_extra = tuple(
            i.formation_id
            for i in intervals
            if i.arrives_node and i.end_node_id == primary.node_id
        )
        snap_ids = tuple(sorted(set(primary.participant_ids) | set(arrival_extra)))
        node_snapshot = _snapshot_formation_locations(state, snap_ids)
        if primary.kind == ENCOUNTER_KIND_NODE_SIMULTANEOUS or has_arrivals:
            created, rejected = apply_simultaneous_node_arrivals(
                state,
                primary,
                intervals,
                edges_by_id=edges_by_id,
                nodes_by_id=nodes_by_id,
            )
            if created:
                contacts.extend(primary.participant_ids)
                skipped.update(primary.participant_ids)
                skipped.update(rejected)
                # Later arrivals at this node (different time) do not move or join.
                for item in intervals:
                    if (
                        item.arrives_node
                        and item.end_node_id == primary.node_id
                        and item.formation_id not in skipped
                        and not arrival_matches_contact_time(item, primary)
                    ):
                        skipped.add(item.formation_id)
            else:
                _restore_formation_locations(state, node_snapshot)
        else:
            # Pure t=0 static co-location — no movement mutations for occupants.
            atk = state.strategic_formations.get(primary.attacker_id)
            dfn = state.strategic_formations.get(primary.defender_id)
            if atk is not None and dfn is not None:
                battle = try_create_node_contact_battle(
                    state,
                    atk,
                    dfn,
                    node_id=primary.node_id,
                    origin_province_id=atk.province_id,
                )
                if battle is not None:
                    contacts.extend(primary.participant_ids)
                    skipped.update(primary.participant_ids)
                    # Later same-tick arrivals still suffer stack-cap denial.
                    rejected = reject_overflow_arrivals_at_node(
                        state,
                        node_id=primary.node_id,
                        intervals=intervals,
                        nodes_by_id=nodes_by_id,
                    )
                    skipped.update(rejected)
                    # Non-overflow later arrivals remain at prior legal position.
                    for item in intervals:
                        if (
                            item.arrives_node
                            and item.end_node_id == primary.node_id
                            and item.formation_id not in skipped
                        ):
                            skipped.add(item.formation_id)
                else:
                    _restore_formation_locations(state, node_snapshot)

    # Remaining movers only when no battle was created this tick.
    if state.pending_battle is None:
        for force in sorted(
            state.strategic_formations.values(),
            key=lambda value: value.strategic_formation_id,
        ):
            if state.pending_battle is not None:
                break
            if force.strategic_formation_id in skipped:
                continue
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
        "swept_kind": primary.kind if primary else "",
    }


def _snapshot_formation_locations(
    state: CampaignState, formation_ids: tuple[str, ...] | list[str]
) -> dict[str, dict[str, Any]]:
    """Deep snapshot of formation/battalion location fields for transactional rollback."""
    snap: dict[str, dict[str, Any]] = {"formations": {}, "battalions": {}, "retreat": {}}
    retreat_store = state.map_metadata.get("operational_edge_retreat_nodes")
    if isinstance(retreat_store, dict):
        snap["retreat"] = {
            str(k): str(v)
            for k, v in retreat_store.items()
            if str(k) in set(formation_ids)
        }
    for fid in formation_ids:
        force = state.strategic_formations.get(fid)
        if force is None:
            continue
        pos = force.position
        snap["formations"][fid] = {
            "province_id": force.province_id,
            "movement_state": force.movement_state,
            "position": None
            if pos is None
            else {
                "mode": pos.mode,
                "node_id": pos.node_id,
                "edge_id": pos.edge_id,
                "progress_milli": pos.progress_milli,
                "facing_node_id": pos.facing_node_id,
            },
            "move_order_status": None
            if force.move_order is None
            else force.move_order.status,
        }
        for bid in force.battalion_ids:
            bn = state.battalions.get(bid)
            if bn is None:
                continue
            snap["battalions"][bid] = {
                "province_id": bn.province_id,
                "strategic_formation_id": bn.strategic_formation_id,
            }
    return snap


def _restore_formation_locations(
    state: CampaignState, snapshot: dict[str, dict[str, Any]]
) -> None:
    """Restore formation/battalion location fields after a failed edge-contact apply."""
    for fid, row in (snapshot.get("formations") or {}).items():
        force = state.strategic_formations.get(fid)
        if force is None:
            continue
        force.province_id = str(row["province_id"])
        force.movement_state = str(row["movement_state"])
        pos_row = row.get("position")
        if pos_row is None:
            force.position = None
        else:
            force.position = FormationOperationalPosition(
                mode=str(pos_row["mode"]),
                node_id=pos_row.get("node_id"),
                edge_id=pos_row.get("edge_id"),
                progress_milli=int(pos_row.get("progress_milli") or 0),
                facing_node_id=pos_row.get("facing_node_id"),
            )
        if force.move_order is not None and row.get("move_order_status"):
            force.move_order = replace(
                force.move_order, status=str(row["move_order_status"])
            )
    for bid, row in (snapshot.get("battalions") or {}).items():
        bn = state.battalions.get(bid)
        if bn is None:
            continue
        bn.province_id = str(row["province_id"])
        bn.strategic_formation_id = str(row["strategic_formation_id"])
    # Restore retreat metadata subset.
    store = state.map_metadata.get("operational_edge_retreat_nodes")
    if isinstance(store, dict):
        # Drop keys we may have written for these formations, then restore snapshot.
        for fid in snapshot.get("formations") or {}:
            store.pop(str(fid), None)
        for fid, node_id in (snapshot.get("retreat") or {}).items():
            store[str(fid)] = str(node_id)


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
    # Tick-time safety: same traversal authority as issue/commit.
    try:
        assert_edge_hop_legal(edge, origin=origin_node, dest=dest_node)
    except ValueError:
        force.move_order = _as_blocked(order)
        return False

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


_BLOCK_METADATA_KEYS = ("blocked", "blockaded", "closed", "disabled")


def edge_is_traversable(edge: OperationalRouteEdge) -> bool:
    """True when an edge may be used by player or AI movement authority."""
    try:
        assert_edge_traversable(edge)
    except ValueError:
        return False
    return True


def assert_edge_traversable(edge: OperationalRouteEdge) -> None:
    """Shared edge gate: enabled, non-candidate, not metadata-blocked."""
    if not edge.traversal_enabled:
        raise ValueError("invalid_path")
    if str(edge.authority) == "candidate":
        raise ValueError("candidate_edge")
    meta = edge.metadata or {}
    for key in _BLOCK_METADATA_KEYS:
        if bool(meta.get(key)):
            raise ValueError("metadata_blocked")


def assert_edge_hop_legal(
    edge: OperationalRouteEdge, *, origin: str, dest: str
) -> None:
    """Shared hop gate: traversable + direction."""
    assert_edge_traversable(edge)
    _assert_edge_direction(edge, origin=origin, dest=dest)


def assert_path_edges_legal(
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> None:
    """Validate every hop on an order path under shared traversal authority."""
    for index, edge_id in enumerate(order.path_edge_ids):
        edge = edges_by_id[edge_id]
        origin = order.path_node_ids[index]
        dest = order.path_node_ids[index + 1]
        assert_edge_hop_legal(edge, origin=origin, dest=dest)


def assert_stance_route_legal(
    state: CampaignState,
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    locked_stance: str,
) -> None:
    """Stance-aware route gates shared by player commit and AI planning."""
    if locked_stance != FormationStance.FORCED_MARCH.value:
        return
    from .operational_contact import enemy_formations_at_node

    # Forced March must not deliberately initiate contact: every node after
    # the route origin must be free of known hostiles.
    for node_id in order.path_node_ids[1:]:
        enemies = enemy_formations_at_node(
            state,
            str(node_id),
            faction=force.faction,
            excluding_formation_id=force.strategic_formation_id,
        )
        if enemies:
            raise ValueError("forced_march_hostile_path")


def destination_reservation_count(
    state: CampaignState,
    node_id: str,
    *,
    faction,
    excluding_formation_id: str | None = None,
    batch_reservations: dict[str, int] | None = None,
    include_drafts: bool = False,
) -> int:
    """Friendly occupants + allied destination claims.

    By default only committed/active orders reserve capacity (drafts that later
    fail legality must not consume slots). Set ``include_drafts=True`` only for
    advisory previews.
    """
    from .diplomacy import are_allied
    from .operational_contact import (
        formation_at_node_id,
        friendly_formations_at_node,
    )

    node = str(node_id)
    friends = friendly_formations_at_node(
        state,
        node,
        faction=faction,
        excluding_formation_id=excluding_formation_id,
    )
    count = len(friends)
    reserving_statuses = {
        MoveOrderStatus.COMMITTED.value,
        MoveOrderStatus.ACTIVE.value,
    }
    if include_drafts:
        reserving_statuses.add(MoveOrderStatus.DRAFT.value)
    claimed: set[str] = {f.strategic_formation_id for f in friends}
    for other in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        oid = other.strategic_formation_id
        if excluding_formation_id and oid == excluding_formation_id:
            continue
        if oid in claimed:
            continue
        if other.faction != faction and not are_allied(state, faction, other.faction):
            continue
        # Already occupying destination counted above.
        if formation_at_node_id(other) == node:
            continue
        order = other.move_order
        if order is None or order.status not in reserving_statuses:
            continue
        if not order.path_node_ids:
            continue
        if str(order.path_node_ids[-1]) != node:
            continue
        claimed.add(oid)
        count += 1
    if batch_reservations:
        count += int(batch_reservations.get(node, 0))
    return count


def can_reserve_destination(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
    *,
    batch_reservations: dict[str, int] | None = None,
    include_drafts: bool = False,
) -> bool:
    """True if force may claim destination without exceeding friendly capacity."""
    from .operational_contact import (
        formation_at_node_id,
        max_friendly_formations_per_node,
    )

    node = str(node_id)
    if formation_at_node_id(force) == node:
        return True
    used = destination_reservation_count(
        state,
        node,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
        batch_reservations=batch_reservations,
        include_drafts=include_drafts,
    )
    return used < max_friendly_formations_per_node(state)


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
    assert_path_edges_legal(order, edges_by_id=edges_by_id)
    if require_start_match:
        _assert_order_starts_at_formation(
            force, order, nodes_by_id=nodes_by_id, edges_by_id=edges_by_id
        )


def _assert_path_legal_for_s3(
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> None:
    """Backward-compatible alias for shared path edge legality."""
    assert_path_edges_legal(order, edges_by_id=edges_by_id)


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
        raise ValueError("one_way_reverse")


def _assert_order_starts_at_formation(
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
    edges_by_id: dict[str, OperationalRouteEdge],
) -> None:
    if force.position is None:
        return
    if not order.path_node_ids:
        raise ValueError("invalid_path")
    start = order.path_node_ids[0]
    pos = force.position
    if pos.mode == PositionMode.AT_NODE.value:
        if pos.node_id != start:
            raise ValueError("invalid_path")
        return
    if pos.mode == PositionMode.ON_EDGE.value:
        # Mandatory continuation of the occupied edge in facing direction.
        assert_on_edge_order_continuation(
            force, order, edges_by_id=edges_by_id
        )
        return
    raise ValueError("invalid_path")


def assert_on_edge_order_continuation(
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> None:
    """ON_EDGE drafts must keep the current edge as hop 0 in facing direction.

    The tail after the facing node must not reverse to the origin, reuse the
    occupied edge, or repeat any prefix node/edge.
    """
    pos = force.position
    if pos is None or pos.mode != PositionMode.ON_EDGE.value:
        raise ValueError("on_edge_desync")
    edge_id = str(pos.edge_id or "")
    edge = edges_by_id.get(edge_id)
    if edge is None:
        raise ValueError("on_edge_desync")
    facing = str(pos.facing_node_id or "")
    if facing not in {edge.a, edge.b}:
        raise ValueError("on_edge_desync")
    origin = edge.b if facing == edge.a else edge.a
    if not order.path_node_ids or not order.path_edge_ids:
        raise ValueError("on_edge_desync")
    if str(order.path_edge_ids[0]) != edge_id:
        raise ValueError("on_edge_desync")
    if str(order.path_node_ids[0]) != origin:
        raise ValueError("on_edge_desync")
    if len(order.path_node_ids) < 2 or str(order.path_node_ids[1]) != facing:
        raise ValueError("on_edge_desync")
    # Direction of first hop must match facing.
    assert_edge_hop_legal(edge, origin=origin, dest=facing)
    assert_on_edge_tail_no_reverse(
        order, origin=origin, facing=facing, occupied_edge_id=edge_id
    )


def assert_on_edge_tail_no_reverse(
    order: OperationalMoveOrder,
    *,
    origin: str,
    facing: str,
    occupied_edge_id: str,
) -> None:
    """Reject tails that reverse through the ON_EDGE prefix (stable token)."""
    nodes = [str(n) for n in order.path_node_ids]
    edges = [str(e) for e in order.path_edge_ids]
    if len(nodes) != len(edges) + 1:
        raise ValueError("invalid_path")
    # No repeated nodes or edges anywhere on the route.
    if len(nodes) != len(set(nodes)):
        raise ValueError("on_edge_reverse")
    if len(edges) != len(set(edges)):
        raise ValueError("on_edge_reverse")
    # Origin only at index 0; occupied edge only at hop 0.
    if origin in nodes[1:]:
        raise ValueError("on_edge_reverse")
    if occupied_edge_id in edges[1:]:
        raise ValueError("on_edge_reverse")
    # Immediate reversal facing → origin.
    if len(nodes) >= 3 and nodes[2] == origin:
        raise ValueError("on_edge_reverse")
    # Any hop that re-enters the occupied edge endpoints against facing.
    for index in range(1, len(edges)):
        a, b = nodes[index], nodes[index + 1]
        if {a, b} == {origin, facing}:
            raise ValueError("on_edge_reverse")


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
