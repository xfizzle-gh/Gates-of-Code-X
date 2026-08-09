"""Gates of CodeX campaign application."""

from functools import wraps

from .models import (
    Alliance,
    Battalion,
    BattalionRosterEntry,
    CampaignState,
    Faction,
    FactionState,
    Formation,
    FormationKind,
    PendingBattle,
    Province,
    ReinforcementPoolEntry,
    ResearchNode,
    UnitEconomy,
)
from .p2_identity import (
    allow_p2_intermediate_validation,
    validate_earth3_p2_identity,
)
from .p2_integrity import validate_earth3_p2_integrity


_original_campaign_validate = CampaignState.validate


@wraps(_original_campaign_validate)
def _campaign_validate_with_p2_integrity(state: CampaignState) -> None:
    validate_earth3_p2_identity(state)
    validate_earth3_p2_integrity(state)
    _original_campaign_validate(state)


CampaignState.validate = _campaign_validate_with_p2_integrity

# Actor-content installation performs one internal state.validate() before the
# Earth3 P2 builder finalizes its three persisted identity markers. Wrap that
# construction-only call in a process-local, state-bound context; normal save
# loading and every validation after installation remain strict.
from . import actor_economy as _actor_economy  # noqa: E402

_original_install_actor_content = _actor_economy.install_actor_content


@wraps(_original_install_actor_content)
def _install_actor_content_with_p2_context(state: CampaignState, *args, **kwargs):
    with allow_p2_intermediate_validation(state):
        return _original_install_actor_content(state, *args, **kwargs)


_actor_economy.install_actor_content = _install_actor_content_with_p2_context

__all__ = [
    "Alliance",
    "Battalion",
    "BattalionRosterEntry",
    "CampaignState",
    "Faction",
    "FactionState",
    "Formation",
    "FormationKind",
    "PendingBattle",
    "Province",
    "ReinforcementPoolEntry",
    "ResearchNode",
    "UnitEconomy",
]

__version__ = "0.11.0"
