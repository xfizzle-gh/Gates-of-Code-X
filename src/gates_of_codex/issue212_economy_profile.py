from __future__ import annotations

"""Focused #212 economy profiler for owner-readiness work.

This module is diagnostic-only. It wraps the exact actor-economy helpers and
CampaignState.validate without changing their inputs, outputs, ordering, or
error behavior. Timing events are emitted only while the existing measured
frontend-command context is active, so ordinary gameplay semantics remain
unchanged.
"""

import functools
import time
from typing import Any, Callable

from .command_scoped_p2_auth import _AI_PROFILE_EVENTS


_INSTALLED = False


def _subject(args: tuple[Any, ...]) -> str:
    if len(args) < 2:
        return ""
    value = args[1]
    return str(getattr(value, "value", value))


def _profiled(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        events = _AI_PROFILE_EVENTS.get()
        if events is None:
            return function(*args, **kwargs)
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            events.append(
                {
                    "phase": name,
                    "faction": _subject(args),
                    "ms": round((time.perf_counter() - started) * 1000.0, 3),
                }
            )

    wrapped._goc_issue212_economy_profiled = True  # type: ignore[attr-defined]
    return wrapped


def _wrap(target: Any, attribute: str, label: str) -> None:
    current = getattr(target, attribute)
    if bool(getattr(current, "_goc_issue212_economy_profiled", False)):
        return
    setattr(target, attribute, _profiled(label, current))


def install_issue212_economy_profiler() -> None:
    """Install nested economy timings once in the packaged backend process."""

    global _INSTALLED
    if _INSTALLED:
        return

    from . import actor_ai_economy, actor_economy, models

    # actor_ai_economy imported these helpers directly, so wrap that module's
    # bound references to measure exactly what the AI turn calls.
    for attribute, label in (
        ("ensure_strategic_actor_runtime", "economy_actor_runtime"),
        ("available_actor_research", "economy_research_scan"),
        ("repair_actor_formation", "economy_repair"),
        ("actor_recruitment_offers", "economy_offer_scan"),
        ("purchase_actor_reinforcements", "economy_reinforcement_purchase"),
        ("assign_actor_reinforcements", "economy_reinforcement_assign"),
    ):
        _wrap(actor_ai_economy, attribute, label)

    # These nested validators are resolved from actor_economy globals at call
    # time. CampaignState.validate captures every full-state validation reached
    # from economy helpers and will make repeated validation immediately visible.
    _wrap(actor_economy, "validate_actor_content_runtime", "economy_actor_content_validate")
    _wrap(models.CampaignState, "validate", "economy_campaign_validate")

    _INSTALLED = True
