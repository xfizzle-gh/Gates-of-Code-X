from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from .diplomacy import are_allied
from .models import CampaignState, Faction, StrategicFormation
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

ENCOUNTER_KIND_EDGE_CROSS = "edge_cross"
ENCOUNTER_KIND_EDGE_CATCHUP = "edge_catchup"
ENCOUNTER_KIND_NODE_SIMULTANEOUS = "node_simultaneous"
ENCOUNTER_KIND_NODE_CONTACT = "node_contact"  # existing static/entry


@dataclass(slots=True)
class MovementInterval:
    """Intended movement for one formation over one tick (pre-mutation snapshot).

    Edge motion uses raw signed velocity in canonical A→B space. Endpoint clamping
    does not stretch velocity over the full tick: exit/arrival times are exact
    rationals when the formation leaves the edge before t=1.
    """

    formation_id: str
    faction: Faction
    edge_id: str | None
    # Canonical A→B progress at t=0 on the active edge (None if not edge-active).
    start_canonical: int | None
    # Raw signed velocity (canonical milli per full tick), before endpoint clamp.
    velocity_canonical: int
    # Clamped end position if the force stayed on-edge the whole tick (for apply).
    end_canonical: int | None
    # +1 toward B, -1 toward A, 0 stationary
    direction: int
    facing_node_id: str | None
    start_node_id: str | None
    end_node_id: str | None
    arrives_node: bool
    # Exact rational time on [0,1] when the force exits the edge / arrives at node.
    # None if it remains on-edge for the full tick (exit_time = 1/1).
    exit_time_num: int | None
    exit_time_den: int | None
    arrival_time_num: int | None
    arrival_time_den: int | None
    origin_province_id: str
    path_origin_node: str | None  # last legal node before current edge hop
    # Stationary on a node at tick start (for t=0 static contact).
    stationary_node_id: str | None = None


@dataclass(slots=True)
class ContactCandidate:
    kind: str
    time_num: int  # numerator for time in [0, denom]
    time_den: int  # denominator (>0); contact time = num/den within tick
    edge_id: str
    node_id: str
    progress_canonical: int  # 0..1000 on edge; 0 for node
    attacker_id: str
    defender_id: str
    participant_ids: tuple[str, ...]
    # Exact previous legal node for each participant (edge retreat).
    retreat_nodes: tuple[tuple[str, str], ...] = ()  # (formation_id, node_id)

    def time_less_than(self, other: "ContactCandidate") -> bool:
        """Exact rational comparison: self.time < other.time via cross-multiply."""
        # a/b < c/d  iff  a*d < c*b  (all non-negative, dens > 0)
        return self.time_num * other.time_den < other.time_num * self.time_den

    def time_equal(self, other: "ContactCandidate") -> bool:
        return self.time_num * other.time_den == other.time_num * self.time_den

    def location_key(self) -> str:
        """Raw edge_id or node_id (IDs are already type-qualified)."""
        return self.edge_id or self.node_id or ""

    def tie_key(self) -> tuple:
        return (
            self.location_key(),
            int(self.progress_canonical),
            self.kind,
            tuple(sorted(self.participant_ids)),
        )


def compute_movement_intervals(
    state: CampaignState,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[MovementInterval]:
    """Compute intended intervals from a frozen snapshot.

    Active movers emit velocity-bearing intervals. Every valid ON_EDGE formation
    without an active order also emits a zero-velocity interval so stationary
    hostiles participate in edge cross/catch-up detection (they never move in
    the normal application phase).
    """
    intervals: list[MovementInterval] = []
    active_ids: set[str] = set()
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        order = force.move_order
        if order is None or order.status != MoveOrderStatus.ACTIVE.value:
            continue
        interval = _interval_for_formation(
            force, order, edges_by_id=edges_by_id, nodes_by_id=nodes_by_id
        )
        if interval is not None:
            intervals.append(interval)
            active_ids.add(force.strategic_formation_id)
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda value: value.strategic_formation_id,
    ):
        if force.strategic_formation_id in active_ids:
            continue
        stationary = _stationary_on_edge_interval(
            force, edges_by_id=edges_by_id
        )
        if stationary is not None:
            intervals.append(stationary)
    return intervals


def _stationary_on_edge_interval(
    force: StrategicFormation,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> MovementInterval | None:
    """Zero-velocity interval for a formation already on an edge (any order state)."""
    position = force.position
    if position is None or position.mode != PositionMode.ON_EDGE.value:
        return None
    edge_id = str(position.edge_id or "")
    if not edge_id:
        return None
    edge = edges_by_id.get(edge_id)
    if edge is None:
        return None
    facing = str(position.facing_node_id or "")
    if facing not in {edge.a, edge.b}:
        # Infer facing toward B when missing/invalid so progress is still canonical.
        facing = edge.b
    start_c = _canonical_from_formation_progress(
        int(position.progress_milli), facing=facing, edge=edge
    )
    # Previous legal node: the endpoint they are not facing (entry/origin side).
    path_origin = edge.a if facing == edge.b else edge.b
    direction = 1 if facing == edge.b else -1
    return MovementInterval(
        formation_id=force.strategic_formation_id,
        faction=force.faction,
        edge_id=edge_id,
        start_canonical=start_c,
        velocity_canonical=0,
        end_canonical=start_c,
        direction=direction,
        facing_node_id=facing,
        start_node_id=None,
        end_node_id=None,
        arrives_node=False,
        exit_time_num=None,
        exit_time_den=None,
        arrival_time_num=None,
        arrival_time_den=None,
        origin_province_id=force.province_id,
        path_origin_node=path_origin,
        stationary_node_id=None,
    )


def detect_swept_contacts(
    state: CampaignState,
    intervals: list[MovementInterval],
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[ContactCandidate]:
    """Detect hostile swept contacts from intended intervals (order-independent)."""
    contacts: list[ContactCandidate] = []
    nodes_by_id = nodes_by_id or {}

    # t=0 static hostile co-location already on nodes.
    by_node_static: dict[str, list[MovementInterval]] = {}
    for item in intervals:
        if item.stationary_node_id:
            by_node_static.setdefault(item.stationary_node_id, []).append(item)
    # Also include non-movers already at nodes from state.
    from .operational_contact import formation_at_node_id, formations_at_node

    occupied_nodes = {
        nid
        for force in state.strategic_formations.values()
        if (nid := formation_at_node_id(force))
    }
    for node_id in sorted(occupied_nodes):
        present = formations_at_node(state, node_id)
        if len(present) < 2:
            continue
        has_hostile = False
        seed_atk = seed_def = None
        for i, left in enumerate(present):
            for right in present[i + 1 :]:
                if left.faction == right.faction or are_allied(
                    state, left.faction, right.faction
                ):
                    continue
                has_hostile = True
                from .operational_contact import choose_static_attacker_defender

                province_id = str(
                    (nodes_by_id.get(node_id) or {}).get("province_id")
                    or left.province_id
                )
                seed_atk, seed_def = choose_static_attacker_defender(
                    state, left, right, node_province_id=province_id
                )
                break
            if has_hostile:
                break
        if not has_hostile or seed_atk is None or seed_def is None:
            continue
        contacts.append(
            ContactCandidate(
                kind=ENCOUNTER_KIND_NODE_CONTACT,
                time_num=0,
                time_den=1,
                edge_id="",
                node_id=node_id,
                progress_canonical=0,
                attacker_id=seed_atk.strategic_formation_id,
                defender_id=seed_def.strategic_formation_id,
                participant_ids=tuple(
                    sorted(f.strategic_formation_id for f in present)
                ),
            )
        )

    # Edge pairs — true velocity, before either exits the edge.
    # Include v=0 on-edge forces (stationary front for catch-up).
    by_edge: dict[str, list[MovementInterval]] = {}
    for item in intervals:
        if item.edge_id and item.start_canonical is not None:
            by_edge.setdefault(item.edge_id, []).append(item)
    for edge_id in sorted(by_edge):
        group = sorted(by_edge[edge_id], key=lambda value: value.formation_id)
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                if left.faction == right.faction or are_allied(
                    state, left.faction, right.faction
                ):
                    continue
                contact = _edge_pair_contact(left, right)
                if contact is not None:
                    contacts.append(contact)

    # Node arrivals grouped by (destination, gcd-normalized exact arrival time).
    arrival_groups: dict[tuple[str, int, int], list[MovementInterval]] = {}
    for item in intervals:
        if not item.arrives_node or not item.end_node_id:
            continue
        if item.arrival_time_num is None or item.arrival_time_den is None:
            continue
        t_num, t_den = normalize_rational(item.arrival_time_num, item.arrival_time_den)
        key = (item.end_node_id, t_num, t_den)
        arrival_groups.setdefault(key, []).append(item)

    for (node_id, t_num, t_den), group in sorted(
        arrival_groups.items(),
        key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]),
    ):
        group = sorted(group, key=lambda value: value.formation_id)
        # Occupants already at node (entry contact against existing hostiles).
        already = {
            f.strategic_formation_id: f for f in formations_at_node(state, node_id)
        }
        # Simultaneous: 2+ arrivals at same exact time with hostile pair among them
        # or vs already-present hostiles.
        combined_ids = {item.formation_id for item in group} | set(already)
        if len(combined_ids) < 2 and len(group) < 1:
            continue

        # Build seed hostile pair using destination province owner-defends.
        province_id = str((nodes_by_id.get(node_id) or {}).get("province_id") or "")
        present_forces: list[StrategicFormation] = []
        for fid in sorted(combined_ids):
            force = state.strategic_formations.get(fid)
            if force is not None:
                present_forces.append(force)
        seed_atk = seed_def = None
        for i, left in enumerate(present_forces):
            for right in present_forces[i + 1 :]:
                if left.faction == right.faction or are_allied(
                    state, left.faction, right.faction
                ):
                    continue
                from .operational_contact import choose_static_attacker_defender

                seed_atk, seed_def = choose_static_attacker_defender(
                    state, left, right, node_province_id=province_id
                )
                break
            if seed_atk is not None:
                break
        if seed_atk is None or seed_def is None:
            continue

        # Classify: all-arrival simultaneous vs entry against occupant.
        arrival_ids = {item.formation_id for item in group}
        already_ids = set(already)
        if len(group) >= 2 and _hostile_in_set(state, group):
            kind = ENCOUNTER_KIND_NODE_SIMULTANEOUS
            participants = tuple(sorted(arrival_ids | already_ids))
        elif already_ids and any(
            not are_allied(
                state,
                state.strategic_formations[aid].faction,
                state.strategic_formations[bid].faction,
            )
            and state.strategic_formations[aid].faction
            != state.strategic_formations[bid].faction
            for aid in arrival_ids
            if aid in state.strategic_formations
            for bid in already_ids
            if bid in state.strategic_formations
        ):
            kind = ENCOUNTER_KIND_NODE_CONTACT
            participants = tuple(sorted(arrival_ids | already_ids))
        elif len(group) >= 2:
            kind = ENCOUNTER_KIND_NODE_SIMULTANEOUS
            participants = tuple(sorted(arrival_ids | already_ids))
        else:
            kind = ENCOUNTER_KIND_NODE_CONTACT
            participants = tuple(sorted(arrival_ids | already_ids))

        retreat = tuple(
            (item.formation_id, item.path_origin_node or item.start_node_id or "")
            for item in group
            if (item.path_origin_node or item.start_node_id)
        )
        contacts.append(
            ContactCandidate(
                kind=kind,
                time_num=t_num,
                time_den=t_den,
                edge_id="",
                node_id=node_id,
                progress_canonical=0,
                attacker_id=seed_atk.strategic_formation_id,
                defender_id=seed_def.strategic_formation_id,
                participant_ids=participants,
                retreat_nodes=tuple((fid, nid) for fid, nid in retreat if nid),
            )
        )
    return contacts


def _hostile_in_set(state: CampaignState, group: list[MovementInterval]) -> bool:
    for i, left in enumerate(group):
        for right in group[i + 1 :]:
            if left.faction != right.faction and not are_allied(
                state, left.faction, right.faction
            ):
                return True
    return False


def select_primary_contact(contacts: list[ContactCandidate]) -> ContactCandidate | None:
    """Earliest exact rational time, then stable location/progress/formation ties."""
    if not contacts:
        return None
    best = contacts[0]
    for item in contacts[1:]:
        if item.time_less_than(best):
            best = item
        elif item.time_equal(best) and item.tie_key() < best.tie_key():
            best = item
    return best


def normalize_rational(num: int, den: int) -> tuple[int, int]:
    """Reduce num/den by gcd. Denominator stays positive."""
    n = int(num)
    d = int(den)
    if d == 0:
        raise ValueError("rational denominator must be non-zero")
    if d < 0:
        n, d = -n, -d
    if n == 0:
        return 0, 1
    g = math.gcd(abs(n), d)
    return n // g, d // g


def rational_equal(a_num: int, a_den: int, b_num: int, b_den: int) -> bool:
    """Exact equality of non-negative rationals via cross-multiply."""
    return int(a_num) * int(b_den) == int(b_num) * int(a_den)


def arrival_matches_contact_time(item: MovementInterval, contact: ContactCandidate) -> bool:
    """True when the interval arrives at the contact node at the contact's exact time."""
    if not item.arrives_node or item.end_node_id != contact.node_id:
        return False
    if item.arrival_time_num is None or item.arrival_time_den is None:
        return False
    return rational_equal(
        item.arrival_time_num,
        item.arrival_time_den,
        contact.time_num,
        contact.time_den,
    )


def formation_canonical_on_edge(
    force: StrategicFormation,
    *,
    edge: OperationalRouteEdge,
) -> int | None:
    """Canonical A→B progress for a formation currently on ``edge``, or None."""
    pos = force.position
    if pos is None or pos.mode != PositionMode.ON_EDGE.value:
        return None
    if str(pos.edge_id) != edge.edge_id:
        return None
    facing = str(pos.facing_node_id or "")
    return _canonical_from_formation_progress(
        int(pos.progress_milli), facing=facing, edge=edge
    )


def apply_edge_contact_stop(
    state: CampaignState,
    contact: ContactCandidate,
    intervals: list[MovementInterval],
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
    participant_ids: tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Stop participants at canonical contact progress. Returns retreat node map."""
    by_id = {item.formation_id: item for item in intervals}
    edge = edges_by_id[contact.edge_id]
    ids = participant_ids if participant_ids is not None else contact.participant_ids
    retreat_map: dict[str, str] = dict(contact.retreat_nodes)
    for fid in ids:
        force = state.strategic_formations.get(fid)
        interval = by_id.get(fid)
        if force is None:
            continue
        if interval is not None:
            facing = interval.facing_node_id
            if interval.path_origin_node:
                retreat_map[fid] = interval.path_origin_node
        else:
            facing = force.position.facing_node_id if force.position else None
        if facing not in {edge.a, edge.b}:
            facing = edge.b if (interval is None or interval.direction >= 0) else edge.a
        progress = _formation_progress_from_canonical(
            contact.progress_canonical, facing=str(facing), edge=edge
        )
        force.position = FormationOperationalPosition(
            mode=PositionMode.ON_EDGE.value,
            edge_id=contact.edge_id,
            progress_milli=progress,
            facing_node_id=str(facing),
        )
        force.movement_state = "on_route"
        if force.move_order is not None:
            force.move_order = replace(
                force.move_order, status=MoveOrderStatus.BLOCKED.value
            )
        from .operational_movement import sync_province_from_position

        sync_province_from_position(state, force)
        for battalion_id in force.battalion_ids:
            battalion = state.battalions.get(battalion_id)
            if battalion is not None:
                battalion.province_id = force.province_id
                battalion.strategic_formation_id = force.strategic_formation_id
    # Persist exact retreat nodes for post-battle resolution.
    from .operational_retreat import record_retreat_origin_node

    for fid, node_id in sorted(retreat_map.items()):
        record_retreat_origin_node(state, fid, node_id)
    return retreat_map


def apply_simultaneous_node_arrivals(
    state: CampaignState,
    contact: ContactCandidate,
    intervals: list[MovementInterval],
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
) -> tuple[bool, tuple[str, ...]]:
    """Atomically place accepted arrivals and open one node_simultaneous battle.

    Capacity is validated from the frozen snapshot (pre-mutation). Returns
    (created, rejected_formation_ids). Rejected arrivals stay at their exact
    previous legal node and are blocked (no active retry after the battle).
    """
    from .operational_contact import (
        formations_at_node,
        max_friendly_formations_per_node,
        try_create_node_contact_battle,
        choose_static_attacker_defender,
    )

    node_id = contact.node_id
    by_id = {item.formation_id: item for item in intervals}
    already = {
        f.strategic_formation_id: f for f in formations_at_node(state, node_id)
    }
    # Only arrivals at this node at the selected contact's exact rational time.
    # Later same-node arrivals this tick stay put and do not join the battle.
    arrivals = [
        item
        for item in sorted(intervals, key=lambda value: value.formation_id)
        if arrival_matches_contact_time(item, contact)
    ]
    if not arrivals and not already:
        return False, ()

    accepted, rejected = _partition_arrivals_by_cap(
        state, arrivals=arrivals, already=already
    )

    present_ids = set(already) | {item.formation_id for item in accepted}
    # Need hostile pair in final group.
    present_forces = [
        state.strategic_formations[fid]
        for fid in sorted(present_ids)
        if fid in state.strategic_formations
    ]
    seed_atk = seed_def = None
    province_id = str((nodes_by_id.get(node_id) or {}).get("province_id") or "")
    for i, left in enumerate(present_forces):
        for right in present_forces[i + 1 :]:
            if left.faction == right.faction or are_allied(
                state, left.faction, right.faction
            ):
                continue
            seed_atk, seed_def = choose_static_attacker_defender(
                state, left, right, node_province_id=province_id
            )
            break
        if seed_atk is not None:
            break
    if seed_atk is None or seed_def is None:
        # No battle — leave everyone unmoved (including rejected).
        return False, ()

    # Capture handoff origin before destination province sync.
    origin_by_fid = {
        item.formation_id: item.origin_province_id for item in accepted
    }
    battle_origin = (
        origin_by_fid.get(seed_atk.strategic_formation_id)
        or seed_atk.province_id
    )

    # Place accepted arrivals at destination.
    for item in accepted:
        force = state.strategic_formations[item.formation_id]
        force.position = FormationOperationalPosition(
            mode=PositionMode.AT_NODE.value,
            node_id=node_id,
            progress_milli=0,
        )
        force.movement_state = "at_anchor"
        dest_province = str(
            (nodes_by_id.get(node_id) or {}).get("province_id") or force.province_id
        )
        force.province_id = dest_province
        if force.move_order is not None:
            force.move_order = replace(
                force.move_order, status=MoveOrderStatus.BLOCKED.value
            )
        for battalion_id in force.battalion_ids:
            battalion = state.battalions.get(battalion_id)
            if battalion is not None:
                battalion.province_id = dest_province
                battalion.strategic_formation_id = force.strategic_formation_id

    # Rejected arrivals: exact last legal node, blocked, no retry.
    rejected_ids = _apply_rejected_arrivals(
        state, rejected, nodes_by_id=nodes_by_id
    )

    # Snapshot after capacity decisions but before battle — caller may restore.
    battle = try_create_node_contact_battle(
        state,
        seed_atk,
        seed_def,
        node_id=node_id,
        origin_province_id=battle_origin,
        retreat_origins={
            item.formation_id: item.path_origin_node
            for item in accepted
            if item.path_origin_node
        },
    )
    if battle is None:
        # Caller must restore; signal failure with rejected ids for bookkeeping.
        return False, tuple(sorted(rejected_ids))
    if contact.kind == ENCOUNTER_KIND_NODE_SIMULTANEOUS:
        battle.encounter_kind = ENCOUNTER_KIND_NODE_SIMULTANEOUS
    return True, tuple(sorted(rejected_ids))


def reject_overflow_arrivals_at_node(
    state: CampaignState,
    *,
    node_id: str,
    intervals: list[MovementInterval],
    nodes_by_id: dict[str, dict[str, Any]],
) -> tuple[str, ...]:
    """Snap back + block arrivals that exceed friendly stack cap at ``node_id``.

    Used when an earlier contact (e.g. t=0 static) already opened a battle at the
    node so later arrivals this tick never enter, but capacity denials still apply.
    """
    from .operational_contact import formations_at_node

    already = {
        f.strategic_formation_id: f for f in formations_at_node(state, node_id)
    }
    by_id = {item.formation_id: item for item in intervals}
    arrivals = [
        item
        for item in sorted(intervals, key=lambda value: value.formation_id)
        if item.arrives_node
        and item.end_node_id == node_id
        and item.formation_id not in already
        and item.formation_id in by_id
    ]
    _accepted, rejected = _partition_arrivals_by_cap(
        state, arrivals=arrivals, already=already
    )
    return tuple(sorted(_apply_rejected_arrivals(state, rejected, nodes_by_id=nodes_by_id)))


def _partition_arrivals_by_cap(
    state: CampaignState,
    *,
    arrivals: list[MovementInterval],
    already: dict[str, StrategicFormation],
) -> tuple[list[MovementInterval], list[MovementInterval]]:
    from .operational_contact import max_friendly_formations_per_node

    accepted: list[MovementInterval] = []
    rejected: list[MovementInterval] = []
    tentative: list[tuple[Faction, str]] = []

    def _friend_count(faction: Faction) -> int:
        count = 0
        for force in already.values():
            if force.faction == faction or are_allied(state, faction, force.faction):
                count += 1
        for other_f, _fid in tentative:
            if other_f == faction or are_allied(state, faction, other_f):
                count += 1
        return count

    cap = max_friendly_formations_per_node(state)
    for item in sorted(arrivals, key=lambda value: value.formation_id):
        force = state.strategic_formations.get(item.formation_id)
        if force is None:
            continue
        if item.formation_id in already:
            accepted.append(item)
            continue
        if _friend_count(force.faction) >= cap:
            rejected.append(item)
            continue
        accepted.append(item)
        tentative.append((force.faction, item.formation_id))
    return accepted, rejected


def _apply_rejected_arrivals(
    state: CampaignState,
    rejected: list[MovementInterval],
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    rejected_ids: list[str] = []
    for item in rejected:
        force = state.strategic_formations.get(item.formation_id)
        if force is None:
            continue
        last_node = item.path_origin_node or item.start_node_id
        if last_node:
            force.position = FormationOperationalPosition(
                mode=PositionMode.AT_NODE.value,
                node_id=str(last_node),
                progress_milli=0,
            )
            force.movement_state = "at_anchor"
            origin_province = str(
                (nodes_by_id.get(str(last_node)) or {}).get("province_id")
                or force.province_id
            )
            force.province_id = origin_province
            for battalion_id in force.battalion_ids:
                battalion = state.battalions.get(battalion_id)
                if battalion is not None:
                    battalion.province_id = origin_province
                    battalion.strategic_formation_id = force.strategic_formation_id
        if force.move_order is not None:
            force.move_order = replace(
                force.move_order, status=MoveOrderStatus.BLOCKED.value
            )
        rejected_ids.append(item.formation_id)
    return rejected_ids


def expand_edge_participants_exact(
    state: CampaignState,
    *,
    edge: OperationalRouteEdge,
    progress_canonical: int,
    seed_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Include seeds plus allies already at the exact edge+canonical progress."""
    ids = set(seed_ids)
    for force in state.strategic_formations.values():
        if force.strategic_formation_id in ids:
            continue
        canonical = formation_canonical_on_edge(force, edge=edge)
        if canonical is None or canonical != progress_canonical:
            continue
        # Ally of any seed?
        seed_forces = [
            state.strategic_formations[sid]
            for sid in seed_ids
            if sid in state.strategic_formations
        ]
        for seed in seed_forces:
            if force.faction == seed.faction or are_allied(
                state, force.faction, seed.faction
            ):
                ids.add(force.strategic_formation_id)
                break
    return tuple(sorted(ids))


def encounter_pixel_for_edge(
    *,
    edge: OperationalRouteEdge,
    nodes_by_id: dict[str, dict[str, Any]],
    progress_canonical: int,
) -> list[int]:
    """Integer lerp from edge.a → edge.b at canonical progress."""
    progress = require_strict_int(
        progress_canonical, name="encounter_progress_milli", minimum=0, maximum=PROGRESS_MILLI_MAX
    )
    a = nodes_by_id.get(edge.a) or {}
    b = nodes_by_id.get(edge.b) or {}
    ax, ay = _pixel(a)
    bx, by = _pixel(b)
    x = ax + (bx - ax) * progress // PROGRESS_MILLI_MAX
    y = ay + (by - ay) * progress // PROGRESS_MILLI_MAX
    return [int(x), int(y)]


def encounter_province_for_edge(
    *,
    edge: OperationalRouteEdge,
    nodes_by_id: dict[str, dict[str, Any]],
    progress_canonical: int,
) -> str:
    """Canonical province: endpoint A if progress < 500, else B (stable, not direction-based)."""
    progress = require_strict_int(
        progress_canonical, name="encounter_progress_milli", minimum=0, maximum=PROGRESS_MILLI_MAX
    )
    node_id = edge.a if progress < PROGRESS_MILLI_MAX // 2 else edge.b
    node = nodes_by_id.get(node_id) or {}
    return str(node.get("province_id") or "")


def _interval_for_formation(
    force: StrategicFormation,
    order: OperationalMoveOrder,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
) -> MovementInterval | None:
    from .operational_movement import _current_edge_index, _stance_speed_milli

    position = force.position
    if position is None:
        return None
    edge_index, desync = _current_edge_index(position, order)
    if desync or edge_index is None:
        if position.mode == PositionMode.AT_NODE.value and position.node_id:
            return MovementInterval(
                formation_id=force.strategic_formation_id,
                faction=force.faction,
                edge_id=None,
                start_canonical=None,
                velocity_canonical=0,
                end_canonical=None,
                direction=0,
                facing_node_id=None,
                start_node_id=str(position.node_id),
                end_node_id=str(position.node_id),
                arrives_node=False,
                exit_time_num=None,
                exit_time_den=None,
                arrival_time_num=None,
                arrival_time_den=None,
                origin_province_id=force.province_id,
                path_origin_node=str(position.node_id),
                stationary_node_id=str(position.node_id),
            )
        return None

    edge_id = order.path_edge_ids[edge_index]
    edge = edges_by_id.get(edge_id)
    if edge is None:
        return None
    dest_node = order.path_node_ids[edge_index + 1]
    origin_node = order.path_node_ids[edge_index]

    if position.mode == PositionMode.AT_NODE.value:
        if position.node_id != origin_node:
            return None
        form_progress = 0
        facing = dest_node
    elif position.mode == PositionMode.ON_EDGE.value and position.edge_id == edge_id:
        form_progress = int(position.progress_milli)
        facing = str(position.facing_node_id or dest_node)
    else:
        return None

    start_c = _canonical_from_formation_progress(form_progress, facing=facing, edge=edge)
    direction = 1 if facing == edge.b else -1
    cost = max(1, int(edge.movement_cost_milli))
    base_mp = max(1, int(edge.base_move_points_milli or COST_MILLI_UNITY))
    stance_milli = _stance_speed_milli(order.locked_stance)
    if stance_milli <= 0:
        raw_delta = 0
    else:
        raw_delta = max(1, (base_mp * stance_milli) // cost)

    # Signed velocity in canonical space (full-tick magnitude before clamp).
    velocity = raw_delta if direction > 0 else (-raw_delta if direction < 0 else 0)

    # Exact exit/arrival time if the force reaches the endpoint before t=1.
    # Stored gcd-normalized so 1/2 and 2/4 group identically.
    exit_num = exit_den = None
    arrival_num = arrival_den = None
    arrives = False
    end_node = None
    if velocity > 0:
        remaining = PROGRESS_MILLI_MAX - start_c
        if remaining <= 0:
            end_c = start_c
        elif raw_delta >= remaining:
            # Reaches B at t = remaining/raw_delta
            exit_num, exit_den = normalize_rational(remaining, raw_delta)
            arrival_num, arrival_den = exit_num, exit_den
            end_c = PROGRESS_MILLI_MAX
            arrives = True
            end_node = dest_node
        else:
            end_c = start_c + raw_delta
    elif velocity < 0:
        remaining = start_c  # distance to A
        mag = -velocity
        if remaining <= 0:
            end_c = start_c
        elif mag >= remaining:
            exit_num, exit_den = normalize_rational(remaining, mag)
            arrival_num, arrival_den = exit_num, exit_den
            end_c = 0
            arrives = True
            end_node = dest_node
        else:
            end_c = start_c - mag
    else:
        end_c = start_c

    return MovementInterval(
        formation_id=force.strategic_formation_id,
        faction=force.faction,
        edge_id=edge_id,
        start_canonical=start_c,
        velocity_canonical=velocity,
        end_canonical=end_c,
        direction=direction,
        facing_node_id=facing,
        start_node_id=origin_node if position.mode == PositionMode.AT_NODE.value else None,
        end_node_id=end_node,
        arrives_node=bool(arrives),
        exit_time_num=exit_num,
        exit_time_den=exit_den,
        arrival_time_num=arrival_num,
        arrival_time_den=arrival_den,
        origin_province_id=force.province_id,
        path_origin_node=origin_node,
        stationary_node_id=None,
    )


def _active_until(item: MovementInterval) -> tuple[int, int]:
    """Return (num, den) for the latest t the force is still on-edge this tick."""
    if item.exit_time_num is not None and item.exit_time_den is not None:
        return item.exit_time_num, item.exit_time_den
    return 1, 1


def _time_le(num: int, den: int, limit_num: int, limit_den: int) -> bool:
    """num/den <= limit_num/limit_den (non-negative dens)."""
    return num * limit_den <= limit_num * den


def _time_lt(num: int, den: int, limit_num: int, limit_den: int) -> bool:
    return num * limit_den < limit_num * den


def _edge_pair_contact(
    left: MovementInterval, right: MovementInterval
) -> ContactCandidate | None:
    """Edge contact using true velocity; reject meetings after either exits the edge."""
    assert left.edge_id and right.edge_id and left.edge_id == right.edge_id
    s1, v1 = left.start_canonical, left.velocity_canonical
    s2, v2 = right.start_canonical, right.velocity_canonical
    if s1 is None or s2 is None:
        return None
    if v1 == 0 and v2 == 0:
        return None
    t1_num, t1_den = _active_until(left)
    t2_num, t2_den = _active_until(right)

    # Opposing directions (both must be moving)
    if v1 != 0 and v2 != 0 and v1 * v2 < 0:
        # Normalize: left increasing, right decreasing
        if v1 < 0:
            s1, v1, s2, v2 = s2, v2, s1, v1
            left, right = right, left
            t1_num, t1_den, t2_num, t2_den = t2_num, t2_den, t1_num, t1_den
        if s1 >= s2:
            return None
        # s1 + t*v1 = s2 + t*v2  => t*(v1-v2) = s2-s1
        den = v1 - v2  # v1>0, v2<0 => den > 0
        num = s2 - s1
        if den <= 0 or num < 0:
            return None
        # Require 0 <= t <= 1 and t < exit of each (still on edge)
        if not _time_le(num, den, 1, 1):
            return None
        if not _time_lt(num, den, t1_num, t1_den):
            return None
        if not _time_lt(num, den, t2_num, t2_den):
            return None
        # progress = s1 + t*v1 = s1 + num*v1/den
        progress = s1 + v1 * num // den
        progress = max(0, min(PROGRESS_MILLI_MAX, progress))
        t_num, t_den = normalize_rational(num, den)
        ids = sorted((left.formation_id, right.formation_id))
        return ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CROSS,
            time_num=t_num,
            time_den=t_den,
            edge_id=str(left.edge_id),
            node_id="",
            progress_canonical=progress,
            attacker_id=ids[0],
            defender_id=ids[1],
            participant_ids=tuple(ids),
            retreat_nodes=tuple(
                (fid, nid)
                for fid, nid in (
                    (left.formation_id, left.path_origin_node or ""),
                    (right.formation_id, right.path_origin_node or ""),
                )
                if nid
            ),
        )

    # Same-direction catch-up (true velocity); allow stationary front (v=0).
    if v1 == v2:
        return None
    if (v1 >= 0 and v2 >= 0) and (v1 > 0 or v2 > 0):
        if s1 < s2:
            rear, front = left, right
            sr, vr, sf, vf = s1, v1, s2, v2
        elif s2 < s1:
            rear, front = right, left
            sr, vr, sf, vf = s2, v2, s1, v1
        else:
            return None
        if vr <= vf:
            return None
        # sr + t*vr = sf + t*vf => t = (sf-sr)/(vr-vf)
        num = sf - sr
        den = vr - vf
        if num < 0 or den <= 0:
            return None
        if not _time_le(num, den, 1, 1):
            return None
        r_num, r_den = _active_until(rear)
        f_num, f_den = _active_until(front)
        if not _time_lt(num, den, r_num, r_den):
            return None
        if not _time_lt(num, den, f_num, f_den):
            return None
        progress = sr + vr * num // den
        progress = max(0, min(PROGRESS_MILLI_MAX, progress))
        t_num, t_den = normalize_rational(num, den)
        return ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CATCHUP,
            time_num=t_num,
            time_den=t_den,
            edge_id=str(left.edge_id),
            node_id="",
            progress_canonical=progress,
            attacker_id=rear.formation_id,
            defender_id=front.formation_id,
            participant_ids=tuple(sorted((rear.formation_id, front.formation_id))),
            retreat_nodes=tuple(
                (fid, nid)
                for fid, nid in (
                    (rear.formation_id, rear.path_origin_node or ""),
                    (front.formation_id, front.path_origin_node or ""),
                )
                if nid
            ),
        )

    # Toward A (both negative, or one negative + stationary front).
    if (v1 <= 0 and v2 <= 0) and (v1 < 0 or v2 < 0):
        # Toward A: rear has larger canonical start
        if s1 > s2:
            rear, front = left, right
            sr, vr, sf, vf = s1, v1, s2, v2
        elif s2 > s1:
            rear, front = right, left
            sr, vr, sf, vf = s2, v2, s1, v1
        else:
            return None
        # velocities <= 0; rear faster means more negative (vr < vf)
        if vr >= vf:
            return None
        # sr + t*vr = sf + t*vf => t = (sf-sr)/(vr-vf)
        num = sf - sr  # negative or zero
        den = vr - vf  # negative
        # Flip to positive rationals
        num, den = -num, -den
        if num < 0 or den <= 0:
            return None
        if not _time_le(num, den, 1, 1):
            return None
        r_num, r_den = _active_until(rear)
        f_num, f_den = _active_until(front)
        if not _time_lt(num, den, r_num, r_den):
            return None
        if not _time_lt(num, den, f_num, f_den):
            return None
        progress = sr + rear.velocity_canonical * num // den
        progress = max(0, min(PROGRESS_MILLI_MAX, progress))
        t_num, t_den = normalize_rational(num, den)
        return ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CATCHUP,
            time_num=t_num,
            time_den=t_den,
            edge_id=str(left.edge_id),
            node_id="",
            progress_canonical=progress,
            attacker_id=rear.formation_id,
            defender_id=front.formation_id,
            participant_ids=tuple(sorted((rear.formation_id, front.formation_id))),
            retreat_nodes=tuple(
                (fid, nid)
                for fid, nid in (
                    (rear.formation_id, rear.path_origin_node or ""),
                    (front.formation_id, front.path_origin_node or ""),
                )
                if nid
            ),
        )
    return None


def _node_attacker_defender(
    state: CampaignState,
    left: MovementInterval,
    right: MovementInterval,
    node_id: str,
) -> tuple[MovementInterval, MovementInterval]:
    from .operational_contact import choose_static_attacker_defender

    fl = state.strategic_formations[left.formation_id]
    fr = state.strategic_formations[right.formation_id]
    province_id = fl.province_id or fr.province_id
    atk_f, def_f = choose_static_attacker_defender(
        state, fl, fr, node_province_id=province_id
    )
    if atk_f.strategic_formation_id == left.formation_id:
        return left, right
    return right, left


def _canonical_from_formation_progress(
    progress: int, *, facing: str, edge: OperationalRouteEdge
) -> int:
    progress = max(0, min(PROGRESS_MILLI_MAX, int(progress)))
    if facing == edge.b:
        return progress  # 0 at A
    if facing == edge.a:
        return PROGRESS_MILLI_MAX - progress  # 0 at B → canonical 1000
    return progress


def _formation_progress_from_canonical(
    canonical: int, *, facing: str, edge: OperationalRouteEdge
) -> int:
    canonical = max(0, min(PROGRESS_MILLI_MAX, int(canonical)))
    if facing == edge.b:
        return canonical
    if facing == edge.a:
        return PROGRESS_MILLI_MAX - canonical
    return canonical


def _pixel(node: dict[str, Any]) -> tuple[int, int]:
    pixel = node.get("pixel") or [0, 0]
    return (
        require_strict_int(pixel[0], name="pixel[0]", minimum=0),
        require_strict_int(pixel[1], name="pixel[1]", minimum=0),
    )
