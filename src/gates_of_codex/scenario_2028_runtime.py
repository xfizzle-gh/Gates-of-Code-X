from __future__ import annotations

from collections.abc import Mapping
from functools import wraps

from .models import CampaignState
from .scenario_profile import (
    ScenarioProfileIdentity,
    persisted_scenario_profile,
    require_compatible_scenario_profile,
)


_EXPECTED_PROFILES = {
    "ww3_2028_core": ScenarioProfileIdentity(
        scenario_id="ww3_2028_core",
        scenario_version="1",
        shared_world_authority_id="earth3_ww3_2028_v1",
        actor_catalog_id="core_2028",
        actor_catalog_compatibility_version="1",
    ),
    "ww3_2028_expanded": ScenarioProfileIdentity(
        scenario_id="ww3_2028_expanded",
        scenario_version="1",
        shared_world_authority_id="earth3_ww3_2028_v1",
        actor_catalog_id="expanded_nations_2028",
        actor_catalog_compatibility_version="1",
    ),
}


def persisted_2028_scenario_id(state: CampaignState) -> str:
    profile = persisted_scenario_profile(state)
    if profile is not None:
        return profile.scenario_id
    value = str(state.map_metadata.get("scenario_id") or "").strip()
    return value if value in _EXPECTED_PROFILES else ""


def activate_loaded_2028_contracts(state: CampaignState) -> bool:
    """Reinstall process-local 2028 behavior from persisted campaign identity.

    New Campaign construction installs the neutral runtime hooks in-process. A
    Continue, frontend command, or other fresh Python process instead reaches the
    campaign through campaign deserialization. This seam makes those paths
    equivalent: strict profile compatibility is rechecked and the idempotent D
    hooks are installed before the loaded state is returned to callers.

    Non-2028 campaigns remain untouched.
    """

    raw_profile = state.map_metadata.get("scenario_profile")
    raw_scenario = str(state.map_metadata.get("scenario_id") or "").strip()
    declares_2028 = raw_scenario.startswith("ww3_2028_") or (
        isinstance(raw_profile, Mapping)
        and str(raw_profile.get("scenario_id") or "").startswith("ww3_2028_")
    )
    if not declares_2028:
        return False

    scenario_id = persisted_2028_scenario_id(state)
    expected = _EXPECTED_PROFILES.get(scenario_id)
    if expected is None:
        raise ValueError(f"unsupported_ww3_2028_scenario_profile:{scenario_id or raw_scenario}")
    require_compatible_scenario_profile(
        state,
        expected,
        allow_legacy_unprofiled=False,
    )

    if raw_scenario and raw_scenario != scenario_id:
        raise ValueError(
            f"ww3_2028_scenario_metadata_mismatch:{raw_scenario}:{scenario_id}"
        )

    from .neutral_nation_runtime import validate_neutral_nation_runtime
    from .neutral_nation_runtime_hooks import install_neutral_nation_runtime_hooks

    validate_neutral_nation_runtime(state)
    install_neutral_nation_runtime_hooks()
    return True


def install_state_io_2028_loader_hook() -> None:
    """Make all canonical deserialization paths restore the 2028 runtime contract.

    ``load_campaign`` and every direct ``campaign_from_dict`` caller resolve the
    patched module function after package initialization. The wrapper is
    idempotently installed once per Python process and leaves non-2028 campaigns
    unchanged.
    """

    from . import state_io

    original = state_io.campaign_from_dict
    if bool(getattr(original, "_goc_225_2028_runtime", False)):
        return

    @wraps(original)
    def _campaign_from_dict_with_2028_runtime(data):
        state = original(data)
        activate_loaded_2028_contracts(state)
        return state

    _campaign_from_dict_with_2028_runtime._goc_225_2028_runtime = True  # type: ignore[attr-defined]
    state_io.campaign_from_dict = _campaign_from_dict_with_2028_runtime
