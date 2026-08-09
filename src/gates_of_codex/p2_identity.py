from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from .models import CampaignState, Faction


EARTH3_MAP_ID = "earth3_europe_mediterranean"
EARTH3_P2_BOOTSTRAP_ID = "earth3_v1_campaign_bootstrap"
EARTH3_P2_CONTENT_PHASE = "p2_campaign_bootstrap"

_P2_CONSTRUCTION_KEY = "_earth3_p2_construction_token"
_P2_CONSTRUCTION_TOKEN = object()

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


@contextmanager
def allow_p2_intermediate_validation(state: CampaignState) -> Iterator[None]:
    """Allow only one in-memory installer validation before P2 markers exist.

    The sentinel is an object-identity token that JSON cannot serialize or forge. It
    is attached only to the exact state being installed and is removed in ``finally``
    before the builder's final strict validation and before the state can be returned.
    """

    metadata = state.map_metadata
    if _P2_CONSTRUCTION_KEY in metadata:
        raise RuntimeError("Earth3 P2 construction validation is already active")
    metadata[_P2_CONSTRUCTION_KEY] = _P2_CONSTRUCTION_TOKEN
    try:
        yield
    finally:
        if metadata.get(_P2_CONSTRUCTION_KEY) is _P2_CONSTRUCTION_TOKEN:
            metadata.pop(_P2_CONSTRUCTION_KEY, None)


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
    if _trusted_installer_intermediate_validation(state):
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


def _trusted_installer_intermediate_validation(state: CampaignState) -> bool:
    """Allow only the exact state carrying this process's unforgeable token."""
    metadata = state.map_metadata
    if metadata.get(_P2_CONSTRUCTION_KEY) is not _P2_CONSTRUCTION_TOKEN:
        return False
    if "earth3_bootstrap" in metadata or "scenario_content_phase" in metadata:
        return False
    actor_content = metadata.get("actor_content_runtime")
    if not isinstance(actor_content, Mapping):
        return False
    return actor_content.get("earth3_bootstrap_id") is None
