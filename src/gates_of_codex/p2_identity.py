from __future__ import annotations

from collections.abc import Mapping

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
