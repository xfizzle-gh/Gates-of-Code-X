from __future__ import annotations

"""Player-facing strategic round cycling for issue #207.

The campaign engine remains the authority for faction order, round rollover,
movement resolution, economy, and pending battles. This module only composes
those existing operations into the player action people expect from "End Turn":
end the human faction, execute each AI faction, and stop when control returns to
the selected faction or a pending battle interrupts the cycle.
"""

import time
from typing import Any

from .campaign import CampaignEngine
from .models import CampaignState
from .strategic_ai import StrategicAI
from .strategic_actors import ensure_strategic_actor_runtime


PLAYER_ROUND_OP = "end_player_round"


def _ms(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000.0, 3)


def end_player_round(state: CampaignState) -> dict[str, Any]:
    """Advance from the current seat back to the selected human faction.

    If called on the selected faction, that faction is ended first. If a save is
    already sitting on an AI faction, the operation resumes from that faction.
    AI turns are taken through ``StrategicAI`` and advancement always goes
    through ``CampaignEngine.end_turn``. A pending battle stops the loop without
    attempting another turn, preserving the normal modal battle gate.
    """

    from .observation import (
        ObservationMutationContext,
        merge_observation_mutation_contexts,
    )

    if state.pending_battle is not None:
        raise RuntimeError("Cannot end player round with a pending battle")

    selected = state.selected_faction
    selected_state = state.factions.get(selected.value)
    if selected_state is None or selected_state.is_eliminated:
        raise RuntimeError(f"Selected faction is not active: {selected.value}")

    engine = CampaignEngine(state)
    starting_turn = int(state.turn_number)
    ai_factions: list[str] = []
    observation_context = ObservationMutationContext()
    perf = {
        "selected_end_turn_ms": 0.0,
        "selected_actor_runtime_ms": 0.0,
        "ai_take_turn_ms": {},
        "ai_end_turn_ms": {},
        "ai_actor_runtime_ms": {},
    }

    # The human has finished planning. Move to the first active AI seat.
    if state.current_faction == selected:
        started = time.perf_counter()
        engine.end_turn()
        perf["selected_end_turn_ms"] = _ms(time.perf_counter() - started)

        started = time.perf_counter()
        ensure_strategic_actor_runtime(state)
        perf["selected_actor_runtime_ms"] = _ms(time.perf_counter() - started)

    # Resume/cycle every active non-player faction. CampaignEngine owns the
    # canonical TURN_ORDER and skips eliminated factions when advancing.
    guard = max(1, len(CampaignEngine.TURN_ORDER) + 1)
    steps = 0
    while (
        state.pending_battle is None
        and state.current_faction != selected
        and steps < guard
    ):
        faction = state.current_faction
        faction_state = state.factions.get(faction.value)
        if faction_state is None or faction_state.is_eliminated:
            # Defensive recovery for malformed/legacy current-faction pointers;
            # the engine will advance to the next active seat.
            started = time.perf_counter()
            engine.end_turn()
            perf["ai_end_turn_ms"][faction.value] = _ms(
                time.perf_counter() - started
            )

            started = time.perf_counter()
            ensure_strategic_actor_runtime(state)
            perf["ai_actor_runtime_ms"][faction.value] = _ms(
                time.perf_counter() - started
            )
            steps += 1
            continue

        ai = StrategicAI(state)
        started = time.perf_counter()
        ai.take_turn(faction)
        perf["ai_take_turn_ms"][faction.value] = _ms(
            time.perf_counter() - started
        )
        observation_context = merge_observation_mutation_contexts(
            observation_context,
            ai.observation_context,
        )
        ai_factions.append(faction.value)
        if state.pending_battle is not None:
            break

        started = time.perf_counter()
        engine.end_turn()
        perf["ai_end_turn_ms"][faction.value] = _ms(
            time.perf_counter() - started
        )

        started = time.perf_counter()
        ensure_strategic_actor_runtime(state)
        perf["ai_actor_runtime_ms"][faction.value] = _ms(
            time.perf_counter() - started
        )
        steps += 1

    if state.pending_battle is None and state.current_faction != selected:
        raise RuntimeError(
            "Player round did not return to selected faction within canonical turn order"
        )

    observation_context = merge_observation_mutation_contexts(
        observation_context,
        engine.observation_context,
    )
    perf["ai_take_turn_total_ms"] = round(
        sum(float(value) for value in perf["ai_take_turn_ms"].values()), 3
    )
    perf["advance_turn_total_ms"] = round(
        float(perf["selected_end_turn_ms"])
        + sum(float(value) for value in perf["ai_end_turn_ms"].values()),
        3,
    )
    perf["actor_runtime_total_ms"] = round(
        float(perf["selected_actor_runtime_ms"])
        + sum(float(value) for value in perf["ai_actor_runtime_ms"].values()),
        3,
    )

    return {
        "selected_faction": selected.value,
        "current_faction": state.current_faction.value,
        "ai_factions": ai_factions,
        "starting_turn": starting_turn,
        "turn_number": int(state.turn_number),
        "pending_battle": state.pending_battle is not None,
        "perf_turn_cycle": perf,
        # ``apply_frontend_commands`` consumes and removes this private key
        # before publishing the command result, exactly like the existing
        # ``run_ai`` path. Combining AI seats must not lose S11 witness state.
        "_observation_context": observation_context,
    }


def install_frontend_turn_cycle_op() -> None:
    """Register the runtime-only frontend op without changing P5's command API.

    PR #213 is stacked after P5, so the maintenance operation is installed by
    the optimized runtime entrypoint. Existing frontend commands retain their
    exact implementation and all P5 handoff/import behavior remains untouched.
    """

    from . import frontend_commands as commands

    current = commands._apply_one
    if bool(getattr(current, "_goc_issue_207_turn_cycle", False)):
        return

    def _apply_with_player_round(
        state: CampaignState,
        op: str,
        raw: dict[str, Any],
    ):
        if op != PLAYER_ROUND_OP:
            return current(state, op, raw)
        data = end_player_round(state)
        return commands.CommandResult(
            op=PLAYER_ROUND_OP,
            ok=True,
            detail=(
                "player round complete"
                if not data["pending_battle"]
                else "player round paused for pending battle"
            ),
            data=data,
        )

    _apply_with_player_round._goc_issue_207_turn_cycle = True  # type: ignore[attr-defined]
    commands._apply_one = _apply_with_player_round
