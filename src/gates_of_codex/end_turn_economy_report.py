from __future__ import annotations

"""Player-visible End Turn earn/spend report from the existing #149 settlement.

``CampaignEngine.end_turn`` already calls ``settle_round_economy``, which
delegates to ``settle_actor_round_economy`` when actor content is installed.
This module does not resettle. It reads the same ``last_round_economy`` rows
that settlement already wrote and surfaces only the acting / selected actor.

AI seats keep using ``StrategicAI.take_turn`` -> ``run_ai_economy``. The
optional other-actors line is a fail-closed boolean from those already-produced
economy actions. It never names foreign actors, units, research keys, or
treasuries.
"""

from typing import Any

from .frontend_actor_force import actor_content_installed, build_acting_actor_presentation
from .models import CampaignState
from .strategic_ai import StrategicAction


ECONOMY_REPORT_SCHEMA = "gates-of-codex.end-turn-economy-report"
ECONOMY_REPORT_SCHEMA_VERSION = 1
OTHER_ACTORS_SUMMARY = "Other actors acted."
SETTLE_ACTOR_SOURCE = "settle_actor_round_economy"
SETTLE_LEGACY_SOURCE = "settle_round_economy"
_AI_ECONOMY_ACTIONS = frozenset(
    {
        "actor_research",
        "actor_recruit",
        "actor_repair",
        "research",
        "recruit",
        "repair",
    }
)


def ai_economy_actions_present(actions: list[StrategicAction] | None) -> bool:
    """True only when take_turn already produced research/recruit/repair."""

    if not actions:
        return False
    return any(str(action.action) in _AI_ECONOMY_ACTIONS for action in actions)


def _presentation_metadata(state: CampaignState) -> dict[str, Any] | None:
    """Return CampaignState presentation metadata, or None when absent.

    A real ``CampaignState`` always carries ``map_metadata`` (empty dict by
    default). Missing or non-dict metadata is not a campaign presentation
    surface; callers must fail-closed instead of inventing numbers.
    """

    metadata = getattr(state, "map_metadata", None)
    return metadata if isinstance(metadata, dict) else None


def _selected_faction_id(state: CampaignState) -> str:
    selected = getattr(state, "selected_faction", None)
    value = getattr(selected, "value", selected)
    return str(value or "").strip()


def _legacy_faction_economy(faction_state: Any) -> tuple[int, int, int] | None:
    """Income, maintenance, treasury from a real FactionState only."""

    if faction_state is None:
        return None
    income = getattr(faction_state, "income_last_round", None)
    maintenance = getattr(faction_state, "maintenance_last_round", None)
    treasury = getattr(faction_state, "resources", None)
    if income is None or maintenance is None or treasury is None:
        return None
    return int(income), int(maintenance), int(treasury)


def build_end_turn_economy_report(
    state: CampaignState,
    *,
    starting_turn: int,
    other_actors_acted: bool = False,
) -> dict[str, Any]:
    """Compact acting-actor report after ``end_player_round``.

    Numbers are published only when this cycle rolled the round
    (``turn_number`` advanced) and real settlement/presentation fields exist.
    Stale previous-round rows are not reused. Missing CampaignState
    presentation metadata is an unsettled no-op, not a crash.
    """

    settled = int(state.turn_number) > int(starting_turn)
    acted = bool(other_actors_acted)
    if _presentation_metadata(state) is None:
        selected = _selected_faction_id(state)
        return _unsettled_payload(
            actor_id=selected,
            display_name=selected,
            other_actors_acted=acted,
        )
    actor = build_acting_actor_presentation(state) or {}
    if actor_content_installed(state):
        return _actor_report(
            state,
            actor=actor,
            settled=settled,
            other_actors_acted=acted,
        )
    return _legacy_report(
        state,
        actor=actor,
        settled=settled,
        other_actors_acted=acted,
    )


def _actor_report(
    state: CampaignState,
    *,
    actor: dict[str, Any],
    settled: bool,
    other_actors_acted: bool,
) -> dict[str, Any]:
    actor_id = str(actor.get("actor_id") or "").strip()
    last = _actor_last_round_row(state, actor_id) if settled and actor_id else {}
    if settled and last:
        return _settled_payload(
            source=SETTLE_ACTOR_SOURCE,
            actor_id=actor_id,
            display_name=str(actor.get("display_name") or actor_id),
            income=int(last.get("income") or 0),
            maintenance_due=int(last.get("maintenance_due") or 0),
            maintenance_paid=int(last.get("maintenance_paid") or 0),
            shortfall=int(last.get("shortfall") or 0),
            treasury=int(last.get("resources_remaining") or 0),
            other_actors_acted=other_actors_acted,
        )
    return _unsettled_payload(
        actor_id=actor_id,
        display_name=str(actor.get("display_name") or actor_id),
        other_actors_acted=other_actors_acted,
    )


def _legacy_report(
    state: CampaignState,
    *,
    actor: dict[str, Any],
    settled: bool,
    other_actors_acted: bool,
) -> dict[str, Any]:
    selected = _selected_faction_id(state)
    last = _faction_last_round_row(state, selected) if settled else {}
    factions = getattr(state, "factions", None) or {}
    faction_economy = _legacy_faction_economy(
        factions.get(selected) if isinstance(factions, dict) else None
    )
    if settled and last:
        return _settled_payload(
            source=SETTLE_LEGACY_SOURCE,
            actor_id=str(actor.get("actor_id") or selected),
            display_name=str(actor.get("display_name") or selected),
            income=int(last.get("income") or 0),
            maintenance_due=int(last.get("maintenance_due") or 0),
            maintenance_paid=int(last.get("maintenance_paid") or 0),
            shortfall=int(last.get("shortfall") or 0),
            treasury=int(last.get("resources_remaining") or 0),
            other_actors_acted=other_actors_acted,
        )
    if settled and faction_economy is not None:
        income, maintenance, treasury = faction_economy
        return _settled_payload(
            source=SETTLE_LEGACY_SOURCE,
            actor_id=str(actor.get("actor_id") or selected),
            display_name=str(actor.get("display_name") or selected),
            income=income,
            maintenance_due=maintenance,
            maintenance_paid=maintenance,
            shortfall=0,
            treasury=treasury,
            other_actors_acted=other_actors_acted,
        )
    return _unsettled_payload(
        actor_id=str(actor.get("actor_id") or selected),
        display_name=str(actor.get("display_name") or selected),
        other_actors_acted=other_actors_acted,
    )


def _actor_last_round_row(state: CampaignState, actor_id: str) -> dict[str, Any]:
    metadata = _presentation_metadata(state) or {}
    content = metadata.get("actor_content_runtime")
    if not isinstance(content, dict):
        return {}
    for report in content.get("last_round_economy") or []:
        if isinstance(report, dict) and str(report.get("actor_id") or "") == actor_id:
            return report
    return {}


def _faction_last_round_row(state: CampaignState, faction_id: str) -> dict[str, Any]:
    metadata = _presentation_metadata(state) or {}
    for report in metadata.get("last_round_economy") or []:
        if isinstance(report, dict) and str(report.get("faction") or "") == faction_id:
            return report
    return {}


def _settled_payload(
    *,
    source: str,
    actor_id: str,
    display_name: str,
    income: int,
    maintenance_due: int,
    maintenance_paid: int,
    shortfall: int,
    treasury: int,
    other_actors_acted: bool,
) -> dict[str, Any]:
    return {
        "schema": ECONOMY_REPORT_SCHEMA,
        "schema_version": ECONOMY_REPORT_SCHEMA_VERSION,
        "settled": True,
        "source": source,
        "actor_id": actor_id,
        "display_name": display_name,
        "income": int(income),
        "maintenance": int(maintenance_due),
        "maintenance_due": int(maintenance_due),
        "maintenance_paid": int(maintenance_paid),
        "shortfall": int(shortfall),
        "net": int(income) - int(maintenance_due),
        "treasury": int(treasury),
        "other_actors_acted": bool(other_actors_acted),
        "other_actors_summary": OTHER_ACTORS_SUMMARY if other_actors_acted else "",
    }


def _unsettled_payload(
    *,
    actor_id: str,
    display_name: str,
    other_actors_acted: bool,
) -> dict[str, Any]:
    return {
        "schema": ECONOMY_REPORT_SCHEMA,
        "schema_version": ECONOMY_REPORT_SCHEMA_VERSION,
        "settled": False,
        "source": "",
        "actor_id": actor_id,
        "display_name": display_name,
        "other_actors_acted": bool(other_actors_acted),
        "other_actors_summary": OTHER_ACTORS_SUMMARY if other_actors_acted else "",
    }
