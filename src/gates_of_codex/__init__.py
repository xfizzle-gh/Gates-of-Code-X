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
from .p2_integrity import validate_earth3_p2_integrity


_original_campaign_validate = CampaignState.validate


@wraps(_original_campaign_validate)
def _campaign_validate_with_p2_integrity(state: CampaignState) -> None:
    validate_earth3_p2_integrity(state)
    _original_campaign_validate(state)


CampaignState.validate = _campaign_validate_with_p2_integrity

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
