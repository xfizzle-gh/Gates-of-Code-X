"""Gates of CodeX campaign application."""

from collections.abc import Mapping
from functools import wraps
from types import SimpleNamespace

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
from .p2_identity import validate_earth3_p2_identity
from .p2_integrity import _validate_persisted_p1_authority, validate_earth3_p2_integrity


_original_campaign_validate = CampaignState.validate
_WW3_2028_SCENARIO_IDS = frozenset({"ww3_2028_core", "ww3_2028_expanded"})
_WW3_2028_WORLD_AUTHORITY_ID = "earth3_ww3_2028_v1"


def _validate_earth3_integrity_for_active_profile(state: CampaignState) -> None:
    scenario_id = str(state.map_metadata.get("scenario_id") or "")
    if scenario_id not in _WW3_2028_SCENARIO_IDS:
        validate_earth3_p2_integrity(state)
        return

    from .earth3_bootstrap import Earth3BootstrapError

    profile = state.map_metadata.get("scenario_profile")
    if (
        not isinstance(profile, Mapping)
        or profile.get("scenario_id") != scenario_id
        or profile.get("shared_world_authority_id") != _WW3_2028_WORLD_AUTHORITY_ID
        or state.map_metadata.get("scenario_status") != "development"
    ):
        raise Earth3BootstrapError("Earth3 2028 persisted scenario authority mismatch")

    # The 2028 profiles deliberately replace P2 actor/province ownership while
    # retaining the immutable Earth3 P1 map authority. Validate that immutable
    # authority against a metadata view using its original Earth3 identity;
    # do not re-apply the obsolete P2 actor-assignment contract to the 2028
    # controller projection.
    p1_metadata = dict(state.map_metadata)
    p1_metadata["scenario_id"] = "earth3_v1"
    p1_metadata["scenario_status"] = "production"
    p1_state = SimpleNamespace(
        map_id=state.map_id,
        map_metadata=p1_metadata,
        provinces=state.provinces,
    )
    _validate_persisted_p1_authority(p1_state)


@wraps(_original_campaign_validate)
def _campaign_validate_with_p2_integrity(state: CampaignState) -> None:
    validate_earth3_p2_identity(state)
    _validate_earth3_integrity_for_active_profile(state)
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

__version__ = "0.16.0"
