from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from .models import CampaignState


EARTH3_MAP_ID = "earth3_europe_mediterranean"
EARTH3_P2_BOOTSTRAP_ID = "earth3_v1_campaign_bootstrap"
EARTH3_P2_CONTENT_PHASE = "p2_campaign_bootstrap"

# These fields are written only after actor-content installation completes and
# therefore distinguish a persisted P2 campaign from the P1 authority skeleton
# and from the builder's temporary pre-provenance state.
_P2_POST_BOOTSTRAP_METADATA_KEYS = frozenset(
    {
        "earth3_p2_capitals",
        "earth3_p2_site_intents",
        "earth3_p2_deployment_zones",
        "earth3_p2_tactical_map_preferences",
    }
)

_P2_STRATEGIC_FORMATION_IDS = frozenset(
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
_P2_BATTALION_IDS = frozenset(f"bn_{formation_id}" for formation_id in _P2_STRATEGIC_FORMATION_IDS)
_P2_TEMPLATE_FORMATION_IDS = frozenset(
    f"toe_{formation_id}" for formation_id in _P2_STRATEGIC_FORMATION_IDS
)
_P2_COMMANDER_IDS = frozenset(
    formation_id.replace("sf_", "cmd_", 1) for formation_id in _P2_STRATEGIC_FORMATION_IDS
)
_P2_ACTIVE_ACTOR_IDS = frozenset({"usa", "deu", "pol", "ukr", "rus"})
_P2_CONSTRUCTION_STATE_IDS: ContextVar[frozenset[int]] = ContextVar(
    "earth3_p2_construction_state_ids",
    default=frozenset(),
)


def _mapping_keys(value: Any) -> frozenset[str]:
    if not isinstance(value, Mapping):
        return frozenset()
    return frozenset(str(key) for key in value)


@contextmanager
def _trusted_earth3_p2_construction(state: CampaignState) -> Iterator[None]:
    """Exclude one in-memory builder state from persisted P2 recognition."""
    state_ids = _P2_CONSTRUCTION_STATE_IDS.get()
    token = _P2_CONSTRUCTION_STATE_IDS.set(state_ids | {id(state)})
    try:
        yield
    finally:
        _P2_CONSTRUCTION_STATE_IDS.reset(token)


def _has_p2_exclusive_structure(state: CampaignState) -> bool:
    """Recognize retained P2 campaign structure after removable markers are stripped.

    The trusted builder's temporary pre-provenance state is excluded only through
    an in-memory context that cannot be serialized into a campaign save.
    """
    if id(state) in _P2_CONSTRUCTION_STATE_IDS.get():
        return False

    metadata = state.map_metadata
    has_p2_force_structure = bool(
        _P2_STRATEGIC_FORMATION_IDS.intersection(state.strategic_formations)
        or _P2_BATTALION_IDS.intersection(state.battalions)
        or _P2_TEMPLATE_FORMATION_IDS.intersection(state.formations)
        or _P2_COMMANDER_IDS.intersection(state.commanders)
    )

    strategic_runtime = metadata.get("strategic_actor_runtime")
    actor_content = metadata.get("actor_content_runtime")
    has_p2_actor_structure = bool(
        isinstance(strategic_runtime, Mapping)
        and _P2_ACTIVE_ACTOR_IDS.issubset(_mapping_keys(strategic_runtime.get("actors")))
        and isinstance(actor_content, Mapping)
        and _P2_ACTIVE_ACTOR_IDS.issubset(_mapping_keys(actor_content.get("actors")))
    )

    return has_p2_force_structure or has_p2_actor_structure


def is_earth3_p2_bearing_state(state: CampaignState) -> bool:
    """Identify a completed or tampered P2 state independently of its markers."""
    if state.map_id != EARTH3_MAP_ID:
        return False

    metadata = state.map_metadata
    actor_content = metadata.get("actor_content_runtime")
    return bool(
        "earth3_bootstrap" in metadata
        or metadata.get("scenario_content_phase") == EARTH3_P2_CONTENT_PHASE
        or (
            isinstance(actor_content, Mapping)
            and actor_content.get("earth3_bootstrap_id")
            == EARTH3_P2_BOOTSTRAP_ID
        )
        or bool(state.catalog_signature)
        or _P2_POST_BOOTSTRAP_METADATA_KEYS.intersection(metadata)
        or _has_p2_exclusive_structure(state)
    )


def validate_earth3_p2_identity(state: CampaignState) -> None:
    """Reject P2-bearing states whose complete persisted identity is incomplete."""
    if not is_earth3_p2_bearing_state(state):
        return

    from .earth3_bootstrap import Earth3BootstrapError

    metadata = state.map_metadata
    if not state.catalog_signature:
        raise Earth3BootstrapError("Earth3 P2 top-level catalog identity is missing")

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
