from __future__ import annotations

"""End Turn-only round-economy validation coalescing for issue #212.

Public economy settlement remains eager. The installed frontend End Turn command
already enters rollover from a fully validated state and performs an authoritative
save before any canonical write. During that atomic command only, actor settlement
keeps its focused actor-content authority check and defers its redundant whole-
campaign validation to the save path's exact ``CampaignState.validate()``.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any, Iterator

from .actor_economy import (
    ActorRoundEconomyReport,
    _actor_for_battalion,
    _commit_actor_states,
    _runtime,
    validate_actor_content_runtime,
)
from .models import CampaignState
from .strategic_actors import ensure_strategic_actor_runtime


_DEFERRED_SETTLEMENT_TRACKER: ContextVar[dict[str, int] | None] = ContextVar(
    "goc_round_economy_deferred_validation_tracker",
    default=None,
)


@contextmanager
def defer_actor_round_settlement_full_validation() -> Iterator[dict[str, int]]:
    """Defer only actor settlement's redundant full campaign validation.

    This context is used only by the prevalidated atomic frontend End Turn path.
    The settlement still validates actor-content authority immediately. The
    caller's authoritative save must run the exact full campaign validator before
    any canonical write.
    """

    install_round_economy_validation_coalescing()
    tracker = {"settlements": 0}
    token = _DEFERRED_SETTLEMENT_TRACKER.set(tracker)
    try:
        yield tracker
    finally:
        _DEFERRED_SETTLEMENT_TRACKER.reset(token)


def _settle_actor_round_economy_deferred(
    state: CampaignState,
) -> list[ActorRoundEconomyReport]:
    """Exact actor settlement mutation with only final full validation deferred."""

    runtime = _runtime(state)
    actors = ensure_strategic_actor_runtime(state)
    income_by_actor = {actor_id: 0 for actor_id in actors}
    for province in state.provinces.values():
        actor_id = province.metadata.get("owner_actor_id")
        if actor_id in income_by_actor:
            income_by_actor[str(actor_id)] += province.resource_yield

    battalions_by_actor: dict[str, list[Any]] = {actor_id: [] for actor_id in actors}
    for battalion in state.battalions.values():
        actor_id = _actor_for_battalion(state, battalion.battalion_id, actors)
        battalions_by_actor[actor_id].append(battalion)

    reports: list[ActorRoundEconomyReport] = []
    for actor_id in sorted(actors):
        actor = actors[actor_id]
        units = runtime["actors"][actor_id]["units"]
        income = income_by_actor[actor_id]
        maintenance = sum(
            units.get(entry.unit_name, {"maintenance_cost": 2})["maintenance_cost"]
            * entry.quantity
            for battalion in battalions_by_actor[actor_id]
            for entry in battalion.roster
        )
        actor.resources += income
        paid = min(actor.resources, maintenance)
        actor.resources -= paid
        shortfall = maintenance - paid
        if shortfall:
            for battalion in battalions_by_actor[actor_id]:
                battalion.condition = max(25, battalion.condition - 5)
        reports.append(
            ActorRoundEconomyReport(
                actor_id=actor_id,
                income=income,
                maintenance_due=maintenance,
                maintenance_paid=paid,
                shortfall=shortfall,
                resources_remaining=actor.resources,
            )
        )

    _commit_actor_states(state, actors)
    runtime["last_round_economy"] = [asdict(report) for report in reports]

    # The public helper's state.validate() includes this authority check, but it
    # is the only settlement-specific semantic validation needed before the
    # remaining rollover steps consume actor economy state. The exact whole-
    # campaign validator still runs in the authoritative save before atomic write.
    validate_actor_content_runtime(state)
    tracker = _DEFERRED_SETTLEMENT_TRACKER.get()
    if tracker is not None:
        tracker["settlements"] += 1
    return reports


def install_round_economy_validation_coalescing() -> None:
    """Install a ContextVar-gated wrapper while preserving eager public behavior."""

    from . import economy

    current = economy.settle_round_economy
    if bool(getattr(current, "_goc_issue212_settlement_coalesced", False)):
        return

    def settlement_with_atomic_frontend_coalescing(state: CampaignState):
        tracker = _DEFERRED_SETTLEMENT_TRACKER.get()
        if tracker is None or "actor_content_runtime" not in state.map_metadata:
            return current(state)
        return _settle_actor_round_economy_deferred(state)

    settlement_with_atomic_frontend_coalescing._goc_issue212_settlement_coalesced = True  # type: ignore[attr-defined]
    economy.settle_round_economy = settlement_with_atomic_frontend_coalescing
