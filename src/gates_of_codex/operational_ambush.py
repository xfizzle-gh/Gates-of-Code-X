from __future__ import annotations

from collections.abc import Iterable

from .models import CampaignState, StrategicFormation
from .operational_schema import FormationStance, MoveOrderStatus, PositionMode

AMBUSH_STRENGTH_MULTIPLIER_MILLI = 1150
STRENGTH_MULTIPLIER_MILLI_UNITY = 1000


def apply_strength_multiplier_milli(
    base_strength_milli: int,
    multiplier_milli: int,
) -> int:
    """Apply an exact milli multiplier with deterministic floor rounding."""
    from .operational_schema import require_strict_int

    base = require_strict_int(
        base_strength_milli,
        name="base_strength_milli",
        minimum=0,
    )
    multiplier = require_strict_int(
        multiplier_milli,
        name="strength_multiplier_milli",
        minimum=0,
    )
    return base * multiplier // STRENGTH_MULTIPLIER_MILLI_UNITY


def effective_operational_stance(force: StrategicFormation) -> str:
    order = force.move_order
    if (
        order is not None
        and order.status
        in {
            MoveOrderStatus.COMMITTED.value,
            MoveOrderStatus.ACTIVE.value,
        }
        and order.locked_stance
    ):
        return order.locked_stance
    if force.stance in {"", "standard", "normal"}:
        return FormationStance.OPERATIONAL.value
    return force.stance


def refresh_ambush_readiness(
    state: CampaignState,
    *,
    completed_tick: int,
    moved_formation_ids: Iterable[str] = (),
) -> None:
    moved = set(moved_formation_ids)
    pending_ids = _pending_formation_ids(state)
    for force in sorted(
        state.strategic_formations.values(),
        key=lambda item: item.strategic_formation_id,
    ):
        eligible = (
            force.strategic_formation_id not in moved
            and force.strategic_formation_id not in pending_ids
            and effective_operational_stance(force) == FormationStance.AMBUSH.value
            and _has_fixed_position(force)
            and any(bid in state.battalions for bid in force.battalion_ids)
        )
        if not eligible:
            force.ambush_ready_tick = None
        elif force.ambush_ready_tick is None:
            force.ambush_ready_tick = completed_tick


def apply_pending_battle_ambush(
    state: CampaignState,
    *,
    initiating_formation_ids: Iterable[str] = (),
) -> None:
    pending = state.pending_battle
    if pending is None:
        return
    from .operational_movement import get_operational_clock

    initiators = set(initiating_formation_ids)
    current_tick = int(get_operational_clock(state)["global_tick"])
    participants = pending.attacking_participants + pending.defending_participants
    if any(
        participant.contact_initiator
        or participant.ambush_triggered
        or participant.ambush_readiness_consumed
        for participant in participants
    ):
        return
    formation_by_battalion = {
        battalion_id: force
        for force in state.strategic_formations.values()
        for battalion_id in force.battalion_ids
    }
    metadata_by_formation: dict[str, tuple[bool, bool, bool]] = {}
    for participant in participants:
        force = formation_by_battalion.get(participant.battalion_id)
        if force is None:
            continue
        formation_id = force.strategic_formation_id
        if formation_id not in metadata_by_formation:
            initiator = formation_id in initiators
            consumed = force.ambush_ready_tick is not None
            eligible = (
                consumed
                and force.ambush_ready_tick <= current_tick
                and not initiator
                and effective_operational_stance(force)
                == FormationStance.AMBUSH.value
                and _has_fixed_position(force)
            )
            metadata_by_formation[formation_id] = (initiator, eligible, consumed)

        initiator, eligible, consumed = metadata_by_formation[formation_id]
        participant.contact_initiator = initiator
        participant.ambush_eligible = eligible
        participant.ambush_triggered = eligible
        participant.ambush_strength_multiplier_milli = (
            AMBUSH_STRENGTH_MULTIPLIER_MILLI
            if eligible
            else STRENGTH_MULTIPLIER_MILLI_UNITY
        )
        participant.ambush_readiness_consumed = consumed

    for formation_id in sorted(metadata_by_formation):
        force = state.strategic_formations.get(formation_id)
        if force is not None:
            force.ambush_ready_tick = None


def _has_fixed_position(force: StrategicFormation) -> bool:
    position = force.position
    if position is None:
        return False
    if position.mode == PositionMode.AT_NODE.value:
        return bool(position.node_id)
    if position.mode == PositionMode.ON_EDGE.value:
        return bool(position.edge_id and position.facing_node_id)
    return False


def _pending_formation_ids(state: CampaignState) -> set[str]:
    pending = state.pending_battle
    if pending is None:
        return set()
    battalion_ids = {
        participant.battalion_id
        for participant in (
            *pending.attacking_participants,
            *pending.defending_participants,
        )
    }
    return {
        battalion.strategic_formation_id
        for bid in battalion_ids
        if (battalion := state.battalions.get(bid)) is not None
        and battalion.strategic_formation_id
    }
