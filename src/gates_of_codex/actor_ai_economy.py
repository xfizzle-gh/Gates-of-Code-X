from __future__ import annotations

from dataclasses import asdict

from .actor_economy import (
    actor_recruitment_offers,
    available_actor_research,
    assign_actor_reinforcements,
    purchase_actor_reinforcements,
    purchase_actor_research,
    repair_actor_formation,
)
from .models import CampaignState, Faction
from .strategic_actors import ensure_strategic_actor_runtime


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
            key=lambda force: (force.condition_summary, force.strategic_formation_id),
        )
        if not formations:
            continue

        damaged = next((force for force in formations if force.condition_summary < 85), None)
        if damaged is not None:
            try:
                result = repair_actor_formation(state, damaged.strategic_formation_id)
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
            for offer in actor_recruitment_offers(state, target.strategic_formation_id)
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
            transfer = assign_actor_reinforcements(
                state,
                target.strategic_formation_id,
                offer.unit_name,
                1,
                battalion_id=_single_battalion_id(state, target.battalion_ids),
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


def _single_battalion_id(state: CampaignState, battalion_ids: list[str]) -> str | None:
    available = sorted(item for item in battalion_ids if item in state.battalions)
    return available[0] if len(available) == 1 else None
