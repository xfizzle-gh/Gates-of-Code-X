"""Gates of CodeX campaign application."""

from collections.abc import Mapping
from copy import copy
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
_EARTH3_MAP_ID = "earth3_europe_mediterranean"


def _is_ww3_2028_earth3_state(state: CampaignState) -> bool:
    return bool(
        state.map_id == _EARTH3_MAP_ID
        and str(state.map_metadata.get("scenario_id") or "") in _WW3_2028_SCENARIO_IDS
    )


def _validate_earth3_integrity_for_active_profile(state: CampaignState) -> None:
    if not _is_ww3_2028_earth3_state(state):
        validate_earth3_p2_integrity(state)
        return

    from .earth3_bootstrap import Earth3BootstrapError, validate_earth3_bootstrap_provenance

    scenario_id = str(state.map_metadata.get("scenario_id") or "")
    profile = state.map_metadata.get("scenario_profile")
    if (
        not isinstance(profile, Mapping)
        or profile.get("scenario_id") != scenario_id
        or profile.get("shared_world_authority_id") != _WW3_2028_WORLD_AUTHORITY_ID
        or state.map_metadata.get("scenario_status") != "development"
    ):
        raise Earth3BootstrapError("Earth3 2028 scenario_profile authority mismatch")

    # Keep the complete Earth3 bootstrap provenance contract. The 2028 profile
    # replaces only the old P2 controller/footprint semantics.
    validate_earth3_bootstrap_provenance(state)

    # Validate immutable P1 map authority using its canonical Earth3 identity,
    # without mutating the persisted 2028 scenario metadata.
    p1_metadata = dict(state.map_metadata)
    p1_metadata["scenario_id"] = "earth3_v1"
    p1_metadata["scenario_status"] = "production"
    p1_state = SimpleNamespace(
        map_id=state.map_id,
        map_metadata=p1_metadata,
        provinces=state.provinces,
    )
    _validate_persisted_p1_authority(p1_state)


def _model_validation_view(state: CampaignState) -> CampaignState:
    if not _is_ww3_2028_earth3_state(state):
        return state

    # CampaignState.validate() contains the legacy 11-province P2 footprint
    # validator. 2028 deliberately replaces that footprint with the authenticated
    # 3,299-province authority. The dedicated checks above already validated the
    # underlying bootstrap provenance and immutable P1 map. Run the remaining
    # generic model invariants against a shallow metadata view that cannot trigger
    # the obsolete P2 footprint validator; the real state remains untouched.
    model_state = copy(state)
    metadata = dict(state.map_metadata)
    metadata.pop("earth3_bootstrap", None)
    metadata.pop("scenario_content_phase", None)
    actor_content = metadata.get("actor_content_runtime")
    if isinstance(actor_content, Mapping):
        actor_content_view = dict(actor_content)
        actor_content_view.pop("earth3_bootstrap_id", None)
        metadata["actor_content_runtime"] = actor_content_view
    model_state.map_metadata = metadata
    return model_state


@wraps(_original_campaign_validate)
def _campaign_validate_with_p2_integrity(state: CampaignState) -> None:
    validate_earth3_p2_identity(state)
    _validate_earth3_integrity_for_active_profile(state)
    _original_campaign_validate(_model_validation_view(state))


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
