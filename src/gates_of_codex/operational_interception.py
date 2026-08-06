from __future__ import annotations

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
    """Intended movement for one formation over one tick (pre-mutation snapshot)."""

    formation_id: str
    faction: Faction
    edge_id: str | None
    # Canonical A→B progress at tick start/end (0..1000). None if not on that edge.
    start_canonical: int | None
    end_canonical: int | None
    # +1 moving toward B, -1 toward A, 0 stationary on edge/node
    direction: int
    facing_node_id: str | None
    start_node_id: str | None
    end_node_id: str | None
    arrives_node: bool
    origin_province_id: str
    path_origin_node: str | None  # last legal node before current edge hop


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

    def sort_key(self) -> tuple:
        return (
            self.time_num * 10_000_000 // max(1, self.time_den),  # comparable earliest
            self.edge_id or "",
            self.node_id or "",
            self.progress_canonical,
            tuple(sorted(self.participant_ids)),
        )


def compute_movement_intervals(
    state: CampaignState,
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[MovementInterval]:
    """Compute intended intervals from a frozen snapshot of active movers."""
    intervals: list[MovementInterval] = []
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
    return intervals


def detect_swept_contacts(
    state: CampaignState,
    intervals: list[MovementInterval],
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
) -> list[ContactCandidate]:
    """Detect hostile swept contacts from intended intervals (order-independent)."""
    contacts: list[ContactCandidate] = []
    # Edge pairs
    by_edge: dict[str, list[MovementInterval]] = {}
    for item in intervals:
        if item.edge_id and item.start_canonical is not None and item.end_canonical is not None:
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
    # Simultaneous node arrivals among movers
    arrivals: dict[str, list[MovementInterval]] = {}
    for item in intervals:
        if item.arrives_node and item.end_node_id:
            arrivals.setdefault(item.end_node_id, []).append(item)
    for node_id in sorted(arrivals):
        group = sorted(arrivals[node_id], key=lambda value: value.formation_id)
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                if left.faction == right.faction or are_allied(
                    state, left.faction, right.faction
                ):
                    continue
                attacker, defender = _node_attacker_defender(state, left, right, node_id)
                contacts.append(
                    ContactCandidate(
                        kind=ENCOUNTER_KIND_NODE_SIMULTANEOUS,
                        time_num=1,
                        time_den=1,  # end of tick arrival
                        edge_id="",
                        node_id=node_id,
                        progress_canonical=0,
                        attacker_id=attacker.formation_id,
                        defender_id=defender.formation_id,
                        participant_ids=tuple(
                            sorted((attacker.formation_id, defender.formation_id))
                        ),
                    )
                )
    contacts.sort(key=lambda item: item.sort_key())
    return contacts


def select_primary_contact(contacts: list[ContactCandidate]) -> ContactCandidate | None:
    if not contacts:
        return None
    return sorted(contacts, key=lambda item: item.sort_key())[0]


def apply_edge_contact_stop(
    state: CampaignState,
    contact: ContactCandidate,
    intervals: list[MovementInterval],
    *,
    edges_by_id: dict[str, OperationalRouteEdge],
    nodes_by_id: dict[str, dict[str, Any]],
) -> None:
    """Stop participating formations at the canonical contact progress on the edge."""
    by_id = {item.formation_id: item for item in intervals}
    edge = edges_by_id[contact.edge_id]
    for fid in contact.participant_ids:
        force = state.strategic_formations.get(fid)
        interval = by_id.get(fid)
        if force is None or interval is None:
            continue
        facing = interval.facing_node_id
        if facing not in {edge.a, edge.b}:
            facing = edge.b if interval.direction >= 0 else edge.a
        # Convert canonical progress to formation progress (0 at origin endpoint).
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
        # Completed or blocked path — still record node occupation for simultaneous arrival.
        if position.mode == PositionMode.AT_NODE.value and position.node_id:
            return MovementInterval(
                formation_id=force.strategic_formation_id,
                faction=force.faction,
                edge_id=None,
                start_canonical=None,
                end_canonical=None,
                direction=0,
                facing_node_id=None,
                start_node_id=str(position.node_id),
                end_node_id=str(position.node_id),
                arrives_node=False,
                origin_province_id=force.province_id,
                path_origin_node=str(position.node_id),
            )
        return None

    edge_id = order.path_edge_ids[edge_index]
    edge = edges_by_id.get(edge_id)
    if edge is None:
        return None
    dest_node = order.path_node_ids[edge_index + 1]
    origin_node = order.path_node_ids[edge_index]

    # Starting placement on edge
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
        delta = 0
    else:
        delta = max(1, (base_mp * stance_milli) // cost)

    if direction > 0:
        end_c = min(PROGRESS_MILLI_MAX, start_c + delta)
    else:
        end_c = max(0, start_c - delta)

    arrives = (direction > 0 and end_c >= PROGRESS_MILLI_MAX) or (
        direction < 0 and end_c <= 0
    )
    end_node = dest_node if arrives else None
    return MovementInterval(
        formation_id=force.strategic_formation_id,
        faction=force.faction,
        edge_id=edge_id,
        start_canonical=start_c,
        end_canonical=end_c,
        direction=direction,
        facing_node_id=facing,
        start_node_id=origin_node if position.mode == PositionMode.AT_NODE.value else None,
        end_node_id=end_node,
        arrives_node=bool(arrives),
        origin_province_id=force.province_id,
        path_origin_node=origin_node,
    )


def _edge_pair_contact(
    left: MovementInterval, right: MovementInterval
) -> ContactCandidate | None:
    assert left.edge_id and right.edge_id and left.edge_id == right.edge_id
    s1, e1, d1 = left.start_canonical, left.end_canonical, left.direction
    s2, e2, d2 = right.start_canonical, right.end_canonical, right.direction
    if s1 is None or e1 is None or s2 is None or e2 is None:
        return None
    # Opposing directions → possible cross
    if d1 * d2 < 0:
        # Normalize so A moves toward B (increasing)
        if d1 < 0:
            s1, e1, s2, e2 = s2, e2, s1, e1
            left, right = right, left
            d1, d2 = -d2, -d1
        # left increasing s1→e1, right decreasing s2→e2
        if s1 >= s2:
            return None  # already passed or same point without closing
        # Meet if end ranges cross: left reaches >= right's end and right reaches <= left's end
        # Contact time t in [0,1]: s1 + t*(e1-s1) = s2 + t*(e2-s2)
        den = (e1 - s1) - (e2 - s2)
        if den <= 0:
            return None
        num = s2 - s1
        if num < 0 or num > den:
            return None
        progress = s1 + (e1 - s1) * num // den
        progress = max(0, min(PROGRESS_MILLI_MAX, progress))
        # Attacker: the one that entered the edge more recently is ambiguous;
        # use formation moving toward the other's start (left as increasing primary).
        # Spec: opposing cross — choose attacker by sorted formation id for stability
        # without combat modifier; document owner-less edge.
        ids = sorted((left.formation_id, right.formation_id))
        return ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CROSS,
            time_num=num,
            time_den=den,
            edge_id=str(left.edge_id),
            node_id="",
            progress_canonical=progress,
            attacker_id=ids[0],
            defender_id=ids[1],
            participant_ids=tuple(ids),
        )

    # Same direction catch-up
    if d1 == 0 or d2 == 0 or d1 != d2:
        return None
    # Both increasing
    if d1 > 0:
        # Identify rear (smaller start) and front (larger start)
        if s1 < s2:
            rear, front = left, right
            sr, er, sf, ef = s1, e1, s2, e2
        elif s2 < s1:
            rear, front = right, left
            sr, er, sf, ef = s2, e2, s1, e1
        else:
            return None
        dr, df = er - sr, ef - sf
        if dr <= df:
            return None  # rear not faster
        # Catch if rear ends at/ past front's path: er >= ef and starts behind
        num = sf - sr
        den = dr - df
        if num < 0 or den <= 0 or num > den:
            # Also allow catch if er >= sf and intervals overlap at end
            if er < sf:
                return None
            # If rear overshoots front start but formula out of range, clamp meeting
            if er >= ef and sr < sf:
                progress = ef  # catch at front end position
                return ContactCandidate(
                    kind=ENCOUNTER_KIND_EDGE_CATCHUP,
                    time_num=1,
                    time_den=1,
                    edge_id=str(left.edge_id),
                    node_id="",
                    progress_canonical=progress,
                    attacker_id=rear.formation_id,
                    defender_id=front.formation_id,
                    participant_ids=tuple(sorted((rear.formation_id, front.formation_id))),
                )
            return None
        progress = sr + dr * num // den
        progress = max(0, min(PROGRESS_MILLI_MAX, progress))
        return ContactCandidate(
            kind=ENCOUNTER_KIND_EDGE_CATCHUP,
            time_num=num,
            time_den=den,
            edge_id=str(left.edge_id),
            node_id="",
            progress_canonical=progress,
            attacker_id=rear.formation_id,
            defender_id=front.formation_id,
            participant_ids=tuple(sorted((rear.formation_id, front.formation_id))),
        )

    # Both decreasing (toward A): rear has larger start canonical
    if s1 > s2:
        rear, front = left, right
        sr, er, sf, ef = s1, e1, s2, e2
    elif s2 > s1:
        rear, front = right, left
        sr, er, sf, ef = s2, e2, s1, e1
    else:
        return None
    # deltas negative; speed magnitude
    dr, df = sr - er, sf - ef  # positive magnitudes
    if dr <= df:
        return None
    num = sr - sf
    den = dr - df
    if num < 0 or den <= 0 or num > den:
        if er <= sf and sr > sf:
            progress = ef
            return ContactCandidate(
                kind=ENCOUNTER_KIND_EDGE_CATCHUP,
                time_num=1,
                time_den=1,
                edge_id=str(left.edge_id),
                node_id="",
                progress_canonical=progress,
                attacker_id=rear.formation_id,
                defender_id=front.formation_id,
                participant_ids=tuple(sorted((rear.formation_id, front.formation_id))),
            )
        return None
    progress = sr - dr * num // den
    progress = max(0, min(PROGRESS_MILLI_MAX, progress))
    return ContactCandidate(
        kind=ENCOUNTER_KIND_EDGE_CATCHUP,
        time_num=num,
        time_den=den,
        edge_id=str(left.edge_id),
        node_id="",
        progress_canonical=progress,
        attacker_id=rear.formation_id,
        defender_id=front.formation_id,
        participant_ids=tuple(sorted((rear.formation_id, front.formation_id))),
    )


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
