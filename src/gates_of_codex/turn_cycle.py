from __future__ import annotations

"""Player-facing strategic round cycling for issue #207.

The campaign engine remains the authority for faction order, round rollover,
movement resolution, economy, and pending battles. This module only composes
those existing operations into the player action people expect from "End Turn":
end the human faction, execute each AI faction, and stop when control returns to
the selected faction or a pending battle interrupts the cycle.
"""

import random
import time
from typing import Any

from .actor_ai_economy import defer_actor_ai_assignment_full_validation
from .campaign import CampaignEngine
from .end_turn_economy_report import (
    ai_economy_actions_present,
    build_end_turn_economy_report,
)
from .models import CampaignState
from .round_economy_validation import (
    defer_actor_round_settlement_full_validation,
    install_round_economy_validation_coalescing,
)
from .strategic_ai import StrategicAI
from .strategic_actors import ensure_strategic_actor_runtime


PLAYER_ROUND_OP = "end_player_round"


def _ms(seconds: float) -> float:
    return round(max(0.0, seconds) * 1000.0, 3)


def _prevalidated_campaign_engine(state: CampaignState) -> CampaignEngine:
    """Build the round engine without revalidating an already-authoritative state.

    The frontend command engine enters ``end_player_round`` with state obtained
    from ``load_campaign`` or the persistent daemon's still-valid lease of that
    same state. Both paths have already completed the full normalization and
    validation contract. Re-running ``CampaignEngine.__init__`` here previously
    repeated that full validation immediately before the round, costing roughly
    two seconds on production Earth3.

    Keep this constructor private to the frontend-round seam. Direct callers of
    ``end_player_round`` still use the normal validating CampaignEngine path.
    """

    engine = CampaignEngine.__new__(CampaignEngine)
    engine.state = state
    engine._random = random.Random()  # type: ignore[attr-defined]
    engine._removal_witnesses_by_formation = {}  # type: ignore[attr-defined]
    engine._confirmed_removed_by_observer = {}  # type: ignore[attr-defined]
    return engine


def _will_roll_round(engine: CampaignEngine) -> bool:
    """Mirror CampaignEngine.end_turn's active-seat rollover decision."""

    active = [
        faction
        for faction in CampaignEngine.TURN_ORDER
        if faction.value in engine.state.factions
        and not engine.state.factions[faction.value].is_eliminated
    ]
    if not active:
        return False
    try:
        index = active.index(engine.state.current_faction)
    except ValueError:
        return True
    return index == len(active) - 1


def end_player_round(
    state: CampaignState,
    *,
    prevalidated: bool = False,
) -> dict[str, Any]:
    """Advance from the current seat back to the selected human faction.

    If called on the selected faction, that faction is ended first. If a save is
    already sitting on an AI faction, the operation resumes from that faction.
    AI turns are taken through ``StrategicAI`` and advancement always goes
    through ``CampaignEngine.end_turn``. A pending battle stops the loop without
    attempting another turn, preserving the normal modal battle gate.

    Production operational campaigns reuse the already-validated campaign engine
    as the AI driver's movement engine. This avoids constructing and fully
    validating the same 3.5k-province state once per AI seat. The installed
    frontend command seam also marks its loaded/leased state as prevalidated, so
    the round engine itself does not repeat the same full validation a second
    time. Direct callers retain the validating constructor by default. Legacy
    adjacency AI retains one engine per AI to preserve its independent seeded
    battle RNG.

    AI reinforcement assignment retains its focused actor-content validation but
    coalesces its redundant whole-campaign validation across the atomic player
    round. If any assignment used that path, one explicit CampaignState.validate
    runs immediately before the final active faction triggers round rollover.

    The prevalidated atomic frontend path also coalesces actor round settlement's
    second whole-campaign validation. Settlement still runs its focused actor-
    content authority check immediately, while the command's authoritative save
    runs the exact CampaignState.validate() after all rollover mutations and
    before the canonical campaign is atomically replaced. Direct/public turn and
    economy callers retain eager settlement validation.
    """

    from .campaign_rules import campaign_play_blocked
    from .observation import (
        ObservationMutationContext,
        merge_observation_mutation_contexts,
    )
    from .operational_ai import operational_graph_authority_present

    if state.pending_battle is not None:
        raise RuntimeError("Cannot end player round with a pending battle")

    selected = state.selected_faction
    selected_state = state.factions.get(selected.value)
    if selected_state is None or selected_state.is_eliminated:
        raise RuntimeError(f"Selected faction is not active: {selected.value}")

    engine_started = time.perf_counter()
    engine = (
        _prevalidated_campaign_engine(state)
        if prevalidated
        else CampaignEngine(state)
    )
    engine_init_ms = _ms(time.perf_counter() - engine_started)
    starting_turn = int(state.turn_number)
    ai_factions: list[str] = []
    other_actors_acted = False
    observation_context = ObservationMutationContext()
    deferred_assignment_count = 0
    perf = {
        "engine_init_ms": engine_init_ms,
        "engine_prevalidated": bool(prevalidated),
        "selected_end_turn_ms": 0.0,
        "selected_actor_runtime_ms": 0.0,
        "ai_take_turn_ms": {},
        "ai_end_turn_ms": {},
        "ai_actor_runtime_ms": {},
        "shared_operational_ai": False,
        "deferred_actor_assignment_count": 0,
        "deferred_round_settlement_count": 0,
        "pre_round_validation_ms": 0.0,
    }

    # On graph-native campaigns StrategicAI never uses CampaignEngine's legacy
    # move/attack RNG path. Reuse the round engine rather than paying another
    # CampaignEngine.__init__ + full state validation once per AI seat.
    shared_operational_ai = (
        StrategicAI(state, engine=engine)
        if operational_graph_authority_present(state)
        else None
    )
    perf["shared_operational_ai"] = shared_operational_ai is not None

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
        and not campaign_play_blocked(state)
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

        ai = shared_operational_ai or StrategicAI(state)
        started = time.perf_counter()
        with defer_actor_ai_assignment_full_validation() as deferred:
            actions = ai.take_turn(faction)
        if ai_economy_actions_present(actions):
            other_actors_acted = True
        deferred_assignment_count += int(deferred["assignments"])
        perf["deferred_actor_assignment_count"] = deferred_assignment_count
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

        will_roll_round = _will_roll_round(engine)

        # The deferred assignment path has already performed its focused
        # actor-content validation. Before global rollover authorities consume
        # the accumulated AI state, run the exact full campaign validator once.
        if deferred_assignment_count and will_roll_round:
            started = time.perf_counter()
            state.validate()
            perf["pre_round_validation_ms"] = _ms(
                time.perf_counter() - started
            )
            deferred_assignment_count = 0

        started = time.perf_counter()
        if prevalidated and will_roll_round:
            with defer_actor_round_settlement_full_validation() as settlement:
                engine.end_turn()
            perf["deferred_round_settlement_count"] += int(
                settlement["settlements"]
            )
        else:
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
        if not campaign_play_blocked(state):
            raise RuntimeError(
                "Player round did not return to selected faction within canonical turn order"
            )

    observation_context = merge_observation_mutation_contexts(
        observation_context,
        engine.observation_context,
    )
    perf["ai_take_turn_total_ms"] = round(
        sum(float(value) for value in perf["ai_take_turn_ms"].values()),
        3,
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
        "economy_report": build_end_turn_economy_report(
            state,
            starting_turn=starting_turn,
            other_actors_acted=other_actors_acted,
        ),
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

    # Install before command_scoped_p2_auth wraps economy settlement for timing,
    # so deferred settlements remain visible in round_advance_events.
    install_round_economy_validation_coalescing()

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
        # apply_frontend_commands obtained this state from authoritative
        # load_campaign, or the persistent backend leased the same still-valid
        # state after a successful authoritative save. Do not immediately repeat
        # the full CampaignEngine constructor validation.
        data = end_player_round(state, prevalidated=True)
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
