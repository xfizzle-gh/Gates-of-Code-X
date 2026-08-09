from __future__ import annotations

import inspect
import sys
from collections.abc import Mapping

from .models import CampaignState, Faction


EARTH3_MAP_ID = "earth3_europe_mediterranean"
EARTH3_P2_BOOTSTRAP_ID = "earth3_v1_campaign_bootstrap"
EARTH3_P2_CONTENT_PHASE = "p2_campaign_bootstrap"

_P2_FORMATION_IDS = frozenset(
    {
        "sf_deu_berlin",
        "sf_usa_tallinn",
        "sf_usa_riga",
        "sf_pol_vilnius",
        "sf_ukr_kyiv",
        "sf_ukr_odesa",
        "sf_ukr_kherson",
        "sf_ukr_zaporizhzhia",
        "sf_rus_rostov",
        "sf_rus_luhansk",
        "sf_rus_donetsk",
    }
)

_P2_OPENING_PROVINCE_IDS = frozenset(
    {
        "e3_0592",
        "e3_0513",
        "e3_0504",
        "e3_0442",
        "e3_1937",
        "e3_1749",
        "e3_1208",
        "e3_1962",
        "e3_2793",
        "e3_2794",
        "e3_3380",
    }
)


def is_earth3_p2_bearing_state(state: CampaignState) -> bool:
    """Identify P2 from durable state structure, not removable identity markers."""
    if state.map_id != EARTH3_MAP_ID:
        return False

    metadata = state.map_metadata
    if "earth3_bootstrap" in metadata:
        return True
    if isinstance(metadata.get("actor_content_runtime"), Mapping):
        return True
    if isinstance(metadata.get("strategic_actor_runtime"), Mapping):
        return True
    if _P2_FORMATION_IDS.intersection(state.strategic_formations):
        return True

    for province_id in _P2_OPENING_PROVINCE_IDS:
        province = state.provinces.get(province_id)
        if province is None:
            continue
        if province.owner != Faction.NEUTRAL:
            return True
        if province.metadata.get("owner_actor_id") not in (None, ""):
            return True
        if bool(province.metadata.get("scenario_actionable")):
            return True
    return False


def validate_earth3_p2_identity(state: CampaignState) -> None:
    """Reject P2-bearing states whose complete persisted identity was removed or altered."""
    if not is_earth3_p2_bearing_state(state):
        return

    metadata = state.map_metadata
    if _trusted_builder_intermediate_validation(metadata):
        return

    from .earth3_bootstrap import Earth3BootstrapError

    bootstrap = metadata.get("earth3_bootstrap")
    if not isinstance(bootstrap, Mapping):
        raise Earth3BootstrapError("Earth3 bootstrap provenance is missing")
    if bootstrap.get("bootstrap_id") != EARTH3_P2_BOOTSTRAP_ID:
        raise Earth3BootstrapError("Earth3 bootstrap identity mismatch")

    if "scenario_content_phase" not in metadata:
        raise Earth3BootstrapError("Earth3 P2 content-phase provenance is missing")
    if metadata.get("scenario_content_phase") != EARTH3_P2_CONTENT_PHASE:
        raise Earth3BootstrapError("Earth3 P2 content-phase identity mismatch")

    actor_content = metadata.get("actor_content_runtime")
    if not isinstance(actor_content, Mapping):
        raise Earth3BootstrapError("Earth3 P2 actor-content provenance is missing")
    if actor_content.get("earth3_bootstrap_id") != EARTH3_P2_BOOTSTRAP_ID:
        raise Earth3BootstrapError("Earth3 P2 actor-content identity mismatch")


def _trusted_builder_intermediate_validation(metadata: Mapping[str, object]) -> bool:
    """Allow only the exact loaded builder's non-persistable intermediate validation."""
    if "earth3_bootstrap" in metadata or "scenario_content_phase" in metadata:
        return False
    actor_content = metadata.get("actor_content_runtime")
    if not isinstance(actor_content, Mapping):
        return False
    if actor_content.get("earth3_bootstrap_id") is not None:
        return False

    module = sys.modules.get("gates_of_codex.earth3_bootstrap")
    builder = None if module is None else getattr(module, "build_earth3_v1_campaign", None)
    builder_code = getattr(builder, "__code__", None)
    if builder_code is None:
        return False

    frame = inspect.currentframe()
    try:
        frame = None if frame is None else frame.f_back
        while frame is not None:
            if frame.f_code is builder_code:
                return True
            frame = frame.f_back
    finally:
        del frame
    return False
