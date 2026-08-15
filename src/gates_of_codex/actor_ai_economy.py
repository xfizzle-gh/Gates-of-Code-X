from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import Iterator

from .actor_economy import (
    ActorReinforcementTransfer,
    _add_roster_quantity,
    _entry_quantity,
    _force_actor,
    _force_battalion,
    _runtime,
    actor_recruitment_offers,
    available_actor_research,
    assign_actor_reinforcements,
    purchase_actor_reinforcements,
    purchase_actor_research,
    repair_actor_formation,
    validate_actor_content_runtime,
)
from .models import CampaignState, Faction
from .strategic_actors import ensure_strategic_actor_runtime


_DEFERRED_ASSIGNMENT_TRACKER: ContextVar[dict[str, int] | None] = ContextVar(
    "goc_actor_ai_deferred_assignment_tracker",
    default=None,
)


@contextmanager
def defer_actor_ai_assignment_full_validation() -> Iterator[dict[str, int]]:
    """Defer only the redundant whole-campaign validation on AI assignment.

    The assignment still executes the actor-content validator before returning.
    The caller must run one full ``CampaignState.validate()`` before round
    rollover when ``assignments`` is non-zero.
    """

    tracker = {"assignments": 0}
    token = _DEFERRED_ASSIGNMENT_TRACKER.set(tracker)
    try:
        yield tracker
    finally:
        _DEFERRED_ASSIGNMENT_TRACKER.reset(token)


def _assign_actor_reinforcements_deferred(
    state: CampaignState,
    strategic_formation_id: str,
    unit_name: str,
    quantity: int = 1,
    *,
    battalion_id: str | None = None,
) -> ActorReinforcementTransfer:
    """Exact assignment mutation with the final full-state validation deferred."""

    if quantity < 1:
        raise ValueError("Transfer quantity must be positive")
    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    force, actor = _force_actor(state, strategic_formation_id, actors)
    target = _force_battalion(state, force.battalion_ids, battalion_id)
    pool = runtime["reinforcement_pool"]
    entry = next(
        (
            value
            for value in pool
            if value["actor_id"] == actor.actor_id
            and value["strategic_formation_id"] == strategic_formation_id
            and value["unit_name"] == unit_name
        ),
        None,
    )
    if entry is None or entry["quantity"] < quantity:
        available = entry["quantity"] if entry else 0
        raise ValueError(f"Only {available} {unit_name} reinforcement(s) available")
    current = _entry_quantity(target.roster, unit_name)
    authorized = _entry_quantity(target.authorized_roster, unit_name)
    replacements = min(quantity, max(0, authorized - current))
    expansion = quantity - replacements
    _add_roster_quantity(target.roster, unit_name, entry["category"], quantity)
    if expansion:
        _add_roster_quantity(
            target.authorized_roster,
            unit_name,
            entry["category"],
            expansion,
        )
    entry["quantity"] -= quantity
    remaining = entry["quantity"]
    if remaining == 0:
        pool.remove(entry)

    # Preserve the focused runtime authority check from the public helper. Only
    # the expensive whole CampaignState.validate() is coalesced by turn_cycle.
    validate_actor_content_runtime(state)
    tracker = _DEFERRED_ASSIGNMENT_TRACKER.get()
    if tracker is not None:
        tracker["assignments"] += 1
    return ActorReinforcementTransfer(
        actor_id=actor.actor_id,
        strategic_formation_id=strategic_formation_id,
        battalion_id=target.battalion_id,
        unit_name=unit_name,
        quantity=quantity,
        replacements=replacements,
        expansion=expansion,
        pool_remaining=remaining,
    )


def run_actor_ai_economy(state: CampaignState, faction: Faction) -> list[dict]:
    """Run deterministic economy actions for every AI actor on a tactical side.

    A tactical-side AI turn may contain several sovereign or hosted actors. Each
    actor keeps separate research, resources, roster access, and reinforcement
    pools. Human-controlled actors are never modified here.
    """

    actors = ensure_strategic_actor_runtime(state)
    actions: list[dict] = []
    actor_ids = sorted(
        actor.actor_id
        for actor in actors.values()
        if actor.tactical_side.campaign_faction() == faction
        and not actor.is_human_controlled
        and not actor.is_eliminated
    )
    for actor_id in actor_ids:
        actor = actors[actor_id]
        research = available_actor_research(state, actor_id)
        if research:
            candidate = min(research, key=lambda item: (item.cost, item.key))
            if candidate.cost <= max(0, actor.resources // 2):
                result = purchase_actor_research(state, actor_id, candidate.key)
                actions.append({"action": "actor_research", **asdict(result)})

        formations = sorted(
            (
                force
                for force in state.strategic_formations.values()
                if force.actor_id == actor_id and force.faction == faction
            ),
            key=lambda force: (
                force.condition_summary,
                force.strategic_formation_id,
            ),
        )
        if not formations:
            continue

        damaged = next(
            (force for force in formations if force.condition_summary < 85),
            None,
        )
        if damaged is not None:
            try:
                result = repair_actor_formation(
                    state,
                    damaged.strategic_formation_id,
                )
                if result.points_repaired:
                    actions.append({"action": "actor_repair", **asdict(result)})
            except ValueError:
                pass

        target = min(
            formations,
            key=lambda force: (
                sum(
                    state.battalions[battalion_id].unit_count
                    for battalion_id in force.battalion_ids
                    if battalion_id in state.battalions
                ),
                force.strategic_formation_id,
            ),
        )
        offers = [
            offer
            for offer in actor_recruitment_offers(
                state,
                target.strategic_formation_id,
            )
            if offer.unlocked
        ]
        offers.sort(
            key=lambda offer: (
                not offer.preferred,
                offer.purchase_cost,
                offer.unit_name,
            )
        )
        if not offers or offers[0].purchase_cost > actor.resources:
            continue
        offer = offers[0]
        try:
            purchase = purchase_actor_reinforcements(
                state,
                target.strategic_formation_id,
                offer.unit_name,
                1,
            )
            assignment = (
                _assign_actor_reinforcements_deferred
                if _DEFERRED_ASSIGNMENT_TRACKER.get() is not None
                else assign_actor_reinforcements
            )
            transfer = assignment(
                state,
                target.strategic_formation_id,
                offer.unit_name,
                1,
                battalion_id=_single_battalion_id(
                    state,
                    target.battalion_ids,
                ),
            )
        except ValueError:
            continue
        actions.append(
            {
                "action": "actor_recruit",
                **asdict(purchase),
                "transfer": asdict(transfer),
            }
        )
    return actions


def _single_battalion_id(
    state: CampaignState,
    battalion_ids: list[str],
) -> str | None:
    available = sorted(item for item in battalion_ids if item in state.battalions)
    return available[0] if len(available) == 1 else None
