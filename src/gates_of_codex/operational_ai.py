from __future__ import annotations

from collections import defaultdict
import copy
import json
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




@dataclass(frozen=True, slots=True)
class OperationalPlanningView:
    """Immutable serialized planning input with no CampaignState reference."""

    faction: str
    campaign_payload_json: str
    visible_subject_keys: tuple[str, ...]
    fog_of_war_enabled: bool


@dataclass(frozen=True, slots=True)
class OperationalIntent:
    formation_id: str
    action: str
    battalion_id: str
    origin_province_id: str | None
    target_province_id: str | None
    details_json: str
    path_node_ids: tuple[str, ...] = ()
    path_edge_ids: tuple[str, ...] = ()
    order_id: str = ""
    locked_stance: str = ""


def build_operational_planning_view(
    state: CampaignState,
    faction: Faction,
) -> OperationalPlanningView:
    """Build a detached canonical planning payload containing only permitted data."""
    if not state.fog_of_war_enabled:
        payload = copy.deepcopy(state.to_dict())
        visible = tuple(sorted(state.strategic_formations))
    else:
        payload, visible = _fog_filtered_planning_payload(state, faction)
    # The planner never receives a mutable CampaignState, callbacks, or live collections.
    return OperationalPlanningView(
        faction=faction.value,
        campaign_payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        visible_subject_keys=visible,
        fog_of_war_enabled=bool(state.fog_of_war_enabled),
    )


def plan_operational_intents(
    view: OperationalPlanningView,
    faction: Faction,
    seed: int = 0,
) -> tuple[OperationalIntent, ...]:
    """Pure planner over a detached restricted view."""
    if faction.value != view.faction:
        raise ValueError("planning_view_faction_mismatch")
    from .state_io import campaign_from_dict

    planning_state = campaign_from_dict(json.loads(view.campaign_payload_json))
    actions = _plan_and_issue_on_state(planning_state, faction, seed=seed)
    intents: list[OperationalIntent] = []
    for action in actions:
        formation_id = str(action.details.get("formation_id") or "")
        force = planning_state.strategic_formations.get(formation_id)
        order = force.move_order if force is not None else None
        intents.append(
            OperationalIntent(
                formation_id=formation_id,
                action=action.action,
                battalion_id=action.battalion_id,
                origin_province_id=action.origin_province_id,
                target_province_id=action.target_province_id,
                details_json=json.dumps(action.details, sort_keys=True, separators=(",", ":")),
                path_node_ids=tuple(order.path_node_ids) if order is not None else (),
                path_edge_ids=tuple(order.path_edge_ids) if order is not None else (),
                order_id=str(order.order_id) if order is not None else "",
                locked_stance=str(order.locked_stance or "") if order is not None else "",
            )
        )
    return tuple(intents)


def validate_and_commit_operational_intents(
    state: CampaignState,
    faction: Faction,
    intents: tuple[OperationalIntent, ...] | list[OperationalIntent],
) -> list[StrategicAction]:
    """Use truth only to validate/commit intents in their existing order."""
    actions: list[StrategicAction] = []
    batch_reservations: dict[str, int] = {}
    for intent in intents:
        details = json.loads(intent.details_json)
        if intent.action != "operational_move":
            actions.append(
                StrategicAction(
                    battalion_id=intent.battalion_id,
                    action=intent.action,
                    origin_province_id=intent.origin_province_id,
                    target_province_id=intent.target_province_id,
                    details=details,
                )
            )
            continue
        force = state.strategic_formations.get(intent.formation_id)
        if force is None or force.faction != faction:
            actions.append(
                StrategicAction(
                    battalion_id=intent.battalion_id,
                    action="reject",
                    origin_province_id=intent.origin_province_id,
                    target_province_id=intent.target_province_id,
                    details={"formation_id": intent.formation_id, "reason": "route_unavailable"},
                )
            )
            continue
        previous_order = copy.deepcopy(force.move_order)
        previous_reservations = dict(batch_reservations)
        try:
            order = issue_move_order(
                state,
                intent.formation_id,
                path_node_ids=list(intent.path_node_ids),
                path_edge_ids=list(intent.path_edge_ids),
                order_id=intent.order_id,
            )
            commit_formation_move_order(
                state,
                intent.formation_id,
                locked_stance=intent.locked_stance or None,
                batch_reservations=batch_reservations,
            )
            details["order_id"] = order.order_id
            actions.append(
                StrategicAction(
                    battalion_id=intent.battalion_id,
                    action="operational_move",
                    origin_province_id=intent.origin_province_id,
                    target_province_id=intent.target_province_id,
                    details=details,
                )
            )
        except ValueError:
            force.move_order = previous_order
            batch_reservations.clear()
            batch_reservations.update(previous_reservations)
            actions.append(
                StrategicAction(
                    battalion_id=intent.battalion_id,
                    action="reject",
                    origin_province_id=intent.origin_province_id,
                    target_province_id=intent.target_province_id,
                    details={"formation_id": intent.formation_id, "reason": "route_unavailable"},
                )
            )
    return actions


def plan_and_issue_operational_orders(
    state: CampaignState,
    faction: Faction,
    *,
    seed: int = 0,
) -> list[StrategicAction]:
    view = build_operational_planning_view(state, faction)
    intents = plan_operational_intents(view, faction, seed)
    return validate_and_commit_operational_intents(state, faction, intents)


def _fog_filtered_planning_payload(
    state: CampaignState,
    faction: Faction,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    from .observation import current_and_last_known_records, observer_factions

    coalition = observer_factions(state, faction)
    current, stale = current_and_last_known_records(state, faction)
    payload = copy.deepcopy(state.to_dict())
    payload["fog_of_war_enabled"] = False
    payload["knowledge_by_observer"] = {}

    friendly_force_ids = {
        force.strategic_formation_id
        for force in state.strategic_formations.values()
        if force.faction in coalition
    }
    friendly_battalion_ids = {
        battalion_id
        for force_id in friendly_force_ids
        for battalion_id in state.strategic_formations[force_id].battalion_ids
    }
    payload["strategic_formations"] = {
        key: value for key, value in payload.get("strategic_formations", {}).items()
        if key in friendly_force_ids
    }
    payload["battalions"] = {
        key: value for key, value in payload.get("battalions", {}).items()
        if key in friendly_battalion_ids
    }
    payload["commanders"] = {
        key: value for key, value in payload.get("commanders", {}).items()
        if value.get("assigned_strategic_formation_id") in friendly_force_ids
        or value.get("assigned_battalion_id") in friendly_battalion_ids
    }
    friendly_template_ids = {
        force.template_formation_id
        for force in state.strategic_formations.values()
        if force.faction in coalition and force.template_formation_id
    }
    payload["formations"] = {
        key: value for key, value in payload.get("formations", {}).items()
        if key in friendly_template_ids
    }
    payload["research_nodes"] = {
        key: value for key, value in payload.get("research_nodes", {}).items()
        if Faction(value.get("faction")) in coalition
    }
    payload["unit_economy"] = {
        key: value for key, value in payload.get("unit_economy", {}).items()
        if Faction(value.get("faction")) in coalition
    }
    for faction_id, row in list(payload.get("factions", {}).items()):
        if Faction(faction_id) in coalition:
            continue
        payload["factions"][faction_id] = {
            "faction": faction_id,
            "resources": 0,
            "researched_keys": [],
            "recruited_pool": [],
            "reinforcement_pool": [],
            "income_last_round": 0,
            "maintenance_last_round": 0,
            "is_human_controlled": False,
            "is_eliminated": bool(row.get("is_eliminated", False)),
        }
    for province_id, row in payload.get("provinces", {}).items():
        try:
            owner = Faction(row.get("owner", "neutral"))
        except ValueError:
            owner = Faction.NEUTRAL
        if owner not in coalition:
            metadata = row.get("metadata", {})
            row["metadata"] = {
                key: value for key, value in metadata.items()
                if key in {"id_color", "name_source"}
            }
            row["fortification"] = 0
            row["resource_yield"] = 0
    # Hidden dynamic site progress is not part of the planning view.
    metadata = payload.get("map_metadata", {})
    if isinstance(metadata, dict):
        metadata.pop("operational_site_control", None)
        metadata.pop("strategic_actor_runtime", None)
        metadata.pop("actor_content_runtime", None)
        metadata.pop("last_round_economy", None)
        metadata.pop("unit_presentations", None)

    graph = load_operational_graph_for_state(state)
    public_edge_facing: dict[str, str] = {}
    if graph is not None:
        for edge in graph.get("edges", []):
            if not isinstance(edge, dict):
                continue
            edge_id = str(edge.get("edge_id") or "")
            endpoints = sorted(
                item
                for item in (
                    str(edge.get("a") or ""),
                    str(edge.get("b") or ""),
                )
                if item
            )
            if edge_id and endpoints:
                public_edge_facing[edge_id] = endpoints[0]

    hostile_factions = sorted(
        (item for item in state.factions if Faction(item) not in coalition)
    )
    generic_hostile = hostile_factions[0] if hostile_factions else Faction.RUSSIA.value
    records = list(current.values()) + list(stale)
    visible_keys: list[str] = sorted(friendly_force_ids)
    seen_subjects: set[str] = set()
    for record in sorted(records, key=lambda row: row.record_key):
        if record.subject_formation_id in seen_subjects:
            continue
        seen_subjects.add(record.subject_formation_id)
        planning_id = (
            record.subject_formation_id
            if record.tier.value != "contact"
            else record.opaque_contact_id
        )
        battalion_id = f"planning-{planning_id}"
        position = None
        if record.last_seen_node_id:
            position = {
                "mode": "at_node", "node_id": record.last_seen_node_id,
                "edge_id": None, "progress_milli": 0, "facing_node_id": None,
            }
        elif (
            record.last_seen_edge_id
            and record.last_seen_edge_id in public_edge_facing
        ):
            position = {
                "mode": "on_edge", "node_id": None,
                "edge_id": record.last_seen_edge_id, "progress_milli": 500,
                # Contact/identified direction is hidden. Use a public-graph-only
                # canonical endpoint so the detached planning state remains valid
                # without encoding the subject's true direction.
                "facing_node_id": public_edge_facing[record.last_seen_edge_id],
            }
        faction_id = record.faction_id or generic_hostile
        payload["strategic_formations"][planning_id] = {
            "strategic_formation_id": planning_id,
            "display_name": record.display_name or "Unidentified contact",
            "faction": faction_id,
            "province_id": record.last_seen_province_id,
            "echelon": record.echelon or "battalion",
            "commander_id": None,
            "battalion_ids": [battalion_id],
            "template_formation_id": "",
            "stack_order": 0,
            "movement_state": "observed_contact",
            "stance": "standard",
            "actor_id": record.actor_id if record.tier.value != "contact" else "",
            "condition_summary": 100,
            "supply_summary": 100,
            "experience_summary": 0,
            "is_player_controlled": False,
            "position": position,
            "move_order": None,
            "supplied": True,
            "cut_off": False,
            "source_hub_id": None,
            "route_cost": None,
            "grace_ticks_remaining": 0,
            "last_supply_refresh_tick": None,
            "last_supply_refresh_turn": None,
            "last_grace_consuming_tick": None,
            "ambush_ready_tick": None,
            "recon_capability": False,
        }
        payload["battalions"][battalion_id] = {
            "battalion_id": battalion_id,
            "faction": faction_id,
            "province_id": record.last_seen_province_id,
            "battalion_type": "combined_arms",
            "roster": [{"unit_name": "observed-contact", "quantity": 1, "stage": "", "category": "unknown", "preserved_objects": []}],
            "authorized_roster": [{"unit_name": "observed-contact", "quantity": 1, "stage": "", "category": "unknown", "preserved_objects": []}],
            "formation_id": "",
            "strategic_formation_id": planning_id,
            "commander_id": None,
            "is_player_controlled": False,
            "movement_remaining": 0,
            "combat_actions_remaining": 0,
            "supply": 100,
            "condition": 100,
            "experience": 0,
            "encircled_turns": 0,
        }
        visible_keys.append(planning_id)
    return payload, tuple(sorted(visible_keys))


def _plan_and_issue_on_state(
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
