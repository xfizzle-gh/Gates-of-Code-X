from __future__ import annotations

from collections.abc import Iterable

from .models import CampaignState, StrategicFormation
from .operational_schema import FormationStance, MoveOrderStatus, PositionMode


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
        for participant in (*pending.attacker_participants, *pending.defender_participants)
    }
    return {
        battalion.strategic_formation_id
        for bid in battalion_ids
        if (battalion := state.battalions.get(bid)) is not None
        and battalion.strategic_formation_id
    }
