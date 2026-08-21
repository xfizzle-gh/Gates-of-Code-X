from __future__ import annotations

from typing import Any

from .models import CampaignState
from .neutral_nation_runtime import (
    advance_neutral_garrison_recovery,
    capture_garrison_battle_state,
    declare_neutral_nation_hostile,
    validate_neutral_nation_runtime,
)


def _attacker_identity(state: CampaignState, attacker: Any) -> str:
    """Resolve the strategic attacker identity without broadening hostility.

    Core campaigns intentionally fall back to the four campaign factions. In
    Expanded mode a battalion's strategic formation carries the persistent
    national actor identity, so Poland attacking a neutral creates hostility to
    Poland rather than to every NATO actor.
    """

    if attacker is None:
        return ""
    formation_id = str(getattr(attacker, "strategic_formation_id", "") or "")
    if formation_id:
        formation = state.strategic_formations.get(formation_id)
        actor_id = str(getattr(formation, "actor_id", "") or "").strip()
        if actor_id:
            return actor_id
    return str(getattr(getattr(attacker, "faction", None), "value", ""))


def install_neutral_nation_runtime_hooks() -> None:
    """Install 2028-only hooks around the existing #48 and turn authorities.

    The wrappers are global but every mutation is gated by the persisted 2028
    scenario identity. Non-2028 campaigns therefore retain their existing
    behavior byte-for-byte at the data-contract level.
    """

    from . import neutral_garrison as garrison
    from .campaign import CampaignEngine

    maybe_attach = garrison.maybe_attach_neutral_garrison
    if not bool(getattr(maybe_attach, "_goc_225_neutral_nation", False)):

        def _attach_with_nation_hostility(
            state: CampaignState,
            province_id: str,
            *args: Any,
            **kwargs: Any,
        ):
            pending = maybe_attach(state, province_id, *args, **kwargs)
            if pending is not None:
                attacker = kwargs.get("attacker")
                if attacker is None and args:
                    attacker = args[0]
                declare_neutral_nation_hostile(
                    state,
                    province_id,
                    _attacker_identity(state, attacker),
                )
            return pending

        _attach_with_nation_hostility._goc_225_neutral_nation = True  # type: ignore[attr-defined]
        garrison.maybe_attach_neutral_garrison = _attach_with_nation_hostility

    sync_after_battle = garrison.sync_neutral_garrison_after_battle
    if not bool(getattr(sync_after_battle, "_goc_225_neutral_nation", False)):

        def _sync_with_capacity_capture(
            state: CampaignState,
            pending: Any,
            winner: Any,
        ) -> None:
            sync_after_battle(state, pending, winner)
            capture_garrison_battle_state(state, str(pending.target_province_id))
            validate_neutral_nation_runtime(state)

        _sync_with_capacity_capture._goc_225_neutral_nation = True  # type: ignore[attr-defined]
        garrison.sync_neutral_garrison_after_battle = _sync_with_capacity_capture

    end_turn = CampaignEngine.end_turn
    if not bool(getattr(end_turn, "_goc_225_neutral_nation", False)):

        def _end_turn_with_neutral_recovery(self: Any, *args: Any, **kwargs: Any):
            before = int(self.state.turn_number)
            result = end_turn(self, *args, **kwargs)
            if int(self.state.turn_number) > before:
                changed = advance_neutral_garrison_recovery(self.state)
                if changed:
                    garrison.validate_neutral_garrison_runtime(self.state)
                    validate_neutral_nation_runtime(self.state)
            return result

        _end_turn_with_neutral_recovery._goc_225_neutral_nation = True  # type: ignore[attr-defined]
        CampaignEngine.end_turn = _end_turn_with_neutral_recovery
