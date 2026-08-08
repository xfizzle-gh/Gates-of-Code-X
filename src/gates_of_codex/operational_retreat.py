from __future__ import annotations

from dataclasses import dataclass

from .diplomacy import are_allied, is_friendly_owner
from .models import CampaignState, StrategicFormation
from .operational_position import load_operational_graph_for_state
from .operational_schema import (
    PROGRESS_MILLI_MAX,
    EdgeKind,
    OperationalRouteEdge,
    require_strict_int,
)


RETREAT_ORIGIN_NODES_KEY = "operational_edge_retreat_nodes"
TRAPPED_NO_LEGAL_RETREAT = "trapped_no_legal_retreat"
_UNRESOLVED_RETREAT_EDGE_KINDS = frozenset(
    {
        EdgeKind.FERRY.value,
        EdgeKind.FERRY_OR_SEA_LANE.value,
        EdgeKind.SEA_LANE.value,
    }
)


@dataclass(frozen=True, slots=True)
class OperationalRetreatCandidate:
    node_id: str
    province_id: str
    edge_id: str
    supplied: bool
    movement_cost: int

    @property
    def rank_key(self) -> tuple[int, int, str]:
        return (0 if self.supplied else 1, self.movement_cost, self.node_id)


@dataclass(frozen=True, slots=True)
class OperationalRetreatResolution:
    formation_id: str
    destination_node_id: str | None = None
    destination_province_id: str | None = None
    reason: str = ""

    @property
    def eliminated(self) -> bool:
        return self.reason == TRAPPED_NO_LEGAL_RETREAT


def record_retreat_origin_node(
    state: CampaignState,
    formation_id: str,
    node_id: str,
) -> None:
    """Persist one formation's exact last legal node for battle finalization."""
    force_id = str(formation_id).strip()
    origin_node_id = str(node_id).strip()
    if not force_id or not origin_node_id:
        return
    store = state.map_metadata.setdefault(RETREAT_ORIGIN_NODES_KEY, {})
    if isinstance(store, dict):
        store[force_id] = origin_node_id


def retreat_origin_node(state: CampaignState, formation_id: str) -> str | None:
    """Return a formation's recorded pre-contact node, if one is persisted."""
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if not isinstance(store, dict):
        return None
    value = str(store.get(str(formation_id)) or "").strip()
    return value or None


def clear_retreat_origin_node(state: CampaignState, formation_id: str) -> None:
    """Clear one formation's recorded pre-contact node without inventing state."""
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if isinstance(store, dict):
        store.pop(str(formation_id), None)


def clear_retreat_origin_nodes(state: CampaignState) -> None:
    """Clear all recorded pre-contact nodes after atomic battle finalization."""
    store = state.map_metadata.get(RETREAT_ORIGIN_NODES_KEY)
    if isinstance(store, dict):
        store.clear()


def resolve_operational_retreat(
    state: CampaignState,
    formation_id: str,
    *,
    encounter_node_id: str | None,
    encounter_edge_id: str | None,
    encounter_progress_milli: int | None,
) -> OperationalRetreatResolution:
    """Select one graph-valid adjacent retreat without mutating campaign state."""
    force = state.strategic_formations.get(str(formation_id))
    if force is None:
        raise KeyError(f"Unknown strategic formation: {formation_id}")
    graph = load_operational_graph_for_state(state)
    if graph is None:
        return _trapped(force)

    from .operational_movement import _indexes

    _node_ids, _edge_ids, edges, nodes = _indexes(graph)
    supplied_nodes = _supplied_node_ids(state, force)
    participant_ids = _pending_participant_formation_ids(state)
    recorded = retreat_origin_node(state, force.strategic_formation_id)

    preferred = _recorded_origin_candidate(
        state,
        force,
        recorded_node_id=recorded,
        encounter_node_id=_clean_id(encounter_node_id),
        encounter_edge_id=_clean_id(encounter_edge_id),
        encounter_progress_milli=encounter_progress_milli,
        nodes=nodes,
        edges=edges,
        supplied_nodes=supplied_nodes,
        participant_ids=participant_ids,
    )
    if preferred is not None:
        return _resolution(force, preferred)

    candidates: list[OperationalRetreatCandidate] = []
    edge_id = _clean_id(encounter_edge_id)
    node_id = _clean_id(encounter_node_id)
    if edge_id:
        edge = edges.get(edge_id)
        if edge is not None:
            progress = require_strict_int(
                encounter_progress_milli,
                name="encounter_progress_milli",
                minimum=0,
                maximum=PROGRESS_MILLI_MAX,
            )
            for destination, segment, origin in (
                (edge.a, progress, edge.b),
                (edge.b, PROGRESS_MILLI_MAX - progress, edge.a),
            ):
                candidate = _candidate_for_hop(
                    state,
                    force,
                    edge=edge,
                    origin_node_id=origin,
                    destination_node_id=destination,
                    movement_cost=_segment_cost(edge.movement_cost_milli, segment),
                    nodes=nodes,
                    supplied_nodes=supplied_nodes,
                    participant_ids=participant_ids,
                    contact_progress=progress,
                    ignore_direction=False,
                )
                if candidate is not None:
                    candidates.append(candidate)
    elif node_id and node_id in nodes:
        for candidate_edge in sorted(edges.values(), key=lambda item: item.edge_id):
            if node_id not in {candidate_edge.a, candidate_edge.b}:
                continue
            destination = (
                candidate_edge.b if node_id == candidate_edge.a else candidate_edge.a
            )
            candidate = _candidate_for_hop(
                state,
                force,
                edge=candidate_edge,
                origin_node_id=node_id,
                destination_node_id=destination,
                movement_cost=candidate_edge.movement_cost_milli,
                nodes=nodes,
                supplied_nodes=supplied_nodes,
                participant_ids=participant_ids,
                contact_progress=None,
                ignore_direction=False,
            )
            if candidate is not None:
                candidates.append(candidate)

    reduced = _reduce_parallel_candidates(candidates)
    if not reduced:
        return _trapped(force)
    return _resolution(force, min(reduced, key=lambda item: item.rank_key))


def _recorded_origin_candidate(
    state: CampaignState,
    force: StrategicFormation,
    *,
    recorded_node_id: str | None,
    encounter_node_id: str | None,
    encounter_edge_id: str | None,
    encounter_progress_milli: int | None,
    nodes: dict[str, dict],
    edges: dict[str, OperationalRouteEdge],
    supplied_nodes: set[str],
    participant_ids: set[str],
) -> OperationalRetreatCandidate | None:
    if not recorded_node_id or recorded_node_id not in nodes:
        return None
    if encounter_edge_id:
        edge = edges.get(encounter_edge_id)
        if edge is None or recorded_node_id not in {edge.a, edge.b}:
            return None
        progress = require_strict_int(
            encounter_progress_milli,
            name="encounter_progress_milli",
            minimum=0,
            maximum=PROGRESS_MILLI_MAX,
        )
        if recorded_node_id == edge.a:
            origin, segment = edge.b, progress
        else:
            origin, segment = edge.a, PROGRESS_MILLI_MAX - progress
        return _candidate_for_hop(
            state,
            force,
            edge=edge,
            origin_node_id=origin,
            destination_node_id=recorded_node_id,
            movement_cost=_segment_cost(edge.movement_cost_milli, segment),
            nodes=nodes,
            supplied_nodes=supplied_nodes,
            participant_ids=participant_ids,
            contact_progress=progress,
            ignore_direction=True,
        )
    if not encounter_node_id or encounter_node_id not in nodes:
        return None
    candidates: list[OperationalRetreatCandidate] = []
    for edge in sorted(edges.values(), key=lambda item: item.edge_id):
        if {edge.a, edge.b} != {encounter_node_id, recorded_node_id}:
            continue
        candidate = _candidate_for_hop(
            state,
            force,
            edge=edge,
            origin_node_id=encounter_node_id,
            destination_node_id=recorded_node_id,
            movement_cost=edge.movement_cost_milli,
            nodes=nodes,
            supplied_nodes=supplied_nodes,
            participant_ids=participant_ids,
            contact_progress=None,
            ignore_direction=False,
        )
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.movement_cost, item.edge_id))


def _candidate_for_hop(
    state: CampaignState,
    force: StrategicFormation,
    *,
    edge: OperationalRouteEdge,
    origin_node_id: str,
    destination_node_id: str,
    movement_cost: int,
    nodes: dict[str, dict],
    supplied_nodes: set[str],
    participant_ids: set[str],
    contact_progress: int | None,
    ignore_direction: bool,
) -> OperationalRetreatCandidate | None:
    from .operational_movement import assert_edge_hop_legal, assert_edge_traversable

    if edge.kind in _UNRESOLVED_RETREAT_EDGE_KINDS:
        return None
    try:
        if ignore_direction:
            assert_edge_traversable(edge)
        else:
            assert_edge_hop_legal(
                edge,
                origin=origin_node_id,
                dest=destination_node_id,
            )
    except ValueError:
        return None
    node = nodes.get(destination_node_id)
    if node is None or not _node_is_eligible(state, force, destination_node_id, node):
        return None
    if _hostile_on_retreat_segment(
        state,
        force,
        edge=edge,
        destination_node_id=destination_node_id,
        contact_progress=contact_progress,
        participant_ids=participant_ids,
    ):
        return None
    province_id = str(node.get("province_id") or "").strip()
    return OperationalRetreatCandidate(
        node_id=destination_node_id,
        province_id=province_id,
        edge_id=edge.edge_id,
        supplied=(
            destination_node_id in supplied_nodes
            or _same_faction_supplied_occupant(state, force, destination_node_id)
        ),
        movement_cost=require_strict_int(
            movement_cost,
            name="retreat_movement_cost",
            minimum=0,
        ),
    )


def _node_is_eligible(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
    node: dict,
) -> bool:
    from .operational_contact import (
        enemy_formations_at_node,
        friendly_formations_at_node,
        max_friendly_formations_per_node,
    )

    province_id = str(node.get("province_id") or "").strip()
    province = state.provinces.get(province_id)
    if province is None or not is_friendly_owner(
        state,
        force.faction,
        province.owner,
    ):
        return False
    if enemy_formations_at_node(
        state,
        node_id,
        faction=force.faction,
        excluding_formation_id=force.strategic_formation_id,
    ):
        return False
    friendly_count = len(
        friendly_formations_at_node(
            state,
            node_id,
            faction=force.faction,
            excluding_formation_id=force.strategic_formation_id,
        )
    )
    return friendly_count < max_friendly_formations_per_node(state)


def _supplied_node_ids(
    state: CampaignState,
    force: StrategicFormation,
) -> set[str]:
    from .operational_supply import (
        compute_operational_supply_routes,
        resolve_operational_supply_sources,
    )

    sources, _diagnostics = resolve_operational_supply_sources(state, force.faction)
    return set(
        compute_operational_supply_routes(state, force.faction, sources)
    )


def _same_faction_supplied_occupant(
    state: CampaignState,
    force: StrategicFormation,
    node_id: str,
) -> bool:
    from .operational_contact import formations_at_node

    return any(
        other.faction == force.faction and other.supplied
        for other in formations_at_node(
            state,
            node_id,
            excluding_formation_id=force.strategic_formation_id,
        )
    )


def _hostile_on_retreat_segment(
    state: CampaignState,
    force: StrategicFormation,
    *,
    edge: OperationalRouteEdge,
    destination_node_id: str,
    contact_progress: int | None,
    participant_ids: set[str],
) -> bool:
    from .operational_interception import formation_canonical_on_edge

    for other in sorted(
        state.strategic_formations.values(),
        key=lambda item: item.strategic_formation_id,
    ):
        if other.strategic_formation_id == force.strategic_formation_id:
            continue
        if other.strategic_formation_id in participant_ids:
            continue
        if other.faction == force.faction or are_allied(
            state,
            force.faction,
            other.faction,
        ):
            continue
        canonical = formation_canonical_on_edge(other, edge=edge)
        if canonical is None:
            continue
        if contact_progress is None:
            return True
        if destination_node_id == edge.a and canonical <= contact_progress:
            return True
        if destination_node_id == edge.b and canonical >= contact_progress:
            return True
    return False


def _pending_participant_formation_ids(state: CampaignState) -> set[str]:
    pending = state.pending_battle
    if pending is None:
        return set()
    formation_ids: set[str] = set()
    for participant in (
        list(pending.attacking_participants) + list(pending.defending_participants)
    ):
        battalion = state.battalions.get(participant.battalion_id)
        if battalion is not None and battalion.strategic_formation_id:
            formation_ids.add(battalion.strategic_formation_id)
    return formation_ids


def _reduce_parallel_candidates(
    candidates: list[OperationalRetreatCandidate],
) -> tuple[OperationalRetreatCandidate, ...]:
    by_node: dict[str, OperationalRetreatCandidate] = {}
    for candidate in sorted(
        candidates,
        key=lambda item: (item.node_id, item.movement_cost, item.edge_id),
    ):
        previous = by_node.get(candidate.node_id)
        if previous is None or (candidate.movement_cost, candidate.edge_id) < (
            previous.movement_cost,
            previous.edge_id,
        ):
            by_node[candidate.node_id] = candidate
    return tuple(by_node[node_id] for node_id in sorted(by_node))


def _segment_cost(edge_cost: int, segment_milli: int) -> int:
    cost = require_strict_int(edge_cost, name="edge_cost", minimum=1)
    segment = require_strict_int(
        segment_milli,
        name="segment_milli",
        minimum=0,
        maximum=PROGRESS_MILLI_MAX,
    )
    return (cost * segment + PROGRESS_MILLI_MAX - 1) // PROGRESS_MILLI_MAX


def _resolution(
    force: StrategicFormation,
    candidate: OperationalRetreatCandidate,
) -> OperationalRetreatResolution:
    return OperationalRetreatResolution(
        formation_id=force.strategic_formation_id,
        destination_node_id=candidate.node_id,
        destination_province_id=candidate.province_id,
    )


def _trapped(force: StrategicFormation) -> OperationalRetreatResolution:
    return OperationalRetreatResolution(
        formation_id=force.strategic_formation_id,
        reason=TRAPPED_NO_LEGAL_RETREAT,
    )


def _clean_id(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None
