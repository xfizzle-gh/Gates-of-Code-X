from __future__ import annotations

"""Core player-economy authority for ww3_2028_core.

Selected Core powers (nato/ukr/rusa/prc) own treasury, research state, and
ordinary strategic spend. National actors remain content/formation identity.
Expanded Nations is unchanged: each national actor keeps its own wallet.
"""

from typing import Any

from .models import CampaignState
from .strategic_actors import (
    ACTOR_RUNTIME_KEY,
    ensure_strategic_actor_runtime,
    validate_strategic_actor_runtime,
)

CORE_PLAYER_ECONOMY_KEY = "core_player_economy_v1"
CORE_PLAYER_ECONOMY_SCHEMA = 1
CORE_2028_POWER_IDS = ("nato", "ukr", "rusa", "prc")
CORE_COALITION_TO_POWER = {
    "atlantic": "nato",
    "eurasian": "rusa",
    "ukrainian": "ukr",
    "prc_aligned": "prc",
}


def is_core_2028_campaign(state: CampaignState) -> bool:
    profile = state.map_metadata.get("scenario_profile")
    if isinstance(profile, dict):
        scenario_id = str(profile.get("scenario_id") or "").strip()
        if scenario_id:
            return scenario_id == "ww3_2028_core"
    return str(state.map_metadata.get("scenario_id") or "").strip() == "ww3_2028_core"


def core_economy_actor_id(state: CampaignState, content_actor_id: str) -> str:
    """Return the Core spend/research authority for a content actor.

    Expanded and non-Core campaigns return ``content_actor_id`` unchanged.
    If the matching Core power overlay is absent (legacy Continue), the
    content actor remains the economy actor.
    """

    token = str(content_actor_id or "").strip()
    if not token or not is_core_2028_campaign(state):
        return token
    if token in CORE_2028_POWER_IDS:
        return token
    actors = ensure_strategic_actor_runtime(state)
    content = actors.get(token)
    if content is None:
        return token
    power_id = CORE_COALITION_TO_POWER.get(str(content.coalition_id or "").strip())
    if not power_id or power_id not in actors:
        return token
    power = actors[power_id]
    if power.tactical_side.campaign_faction() != content.tactical_side.campaign_faction():
        return token
    return power_id


def migrate_core_player_economy_v1(state: CampaignState) -> dict[str, Any] | None:
    """Stamp Core economy authority without folding starting treasuries.

    Explicit rule:
    - player-visible treasury stays the selected Core power's ``resources``
    - constituent wallets are preserved but inert for Core spend
    - constituent ``researched_keys`` are unioned onto the matching Core power
    - second load is a no-op
    """

    if not is_core_2028_campaign(state):
        return None
    existing = state.map_metadata.get(CORE_PLAYER_ECONOMY_KEY)
    if isinstance(existing, dict) and int(existing.get("schema") or 0) == CORE_PLAYER_ECONOMY_SCHEMA:
        return dict(existing)

    actors = ensure_strategic_actor_runtime(state)
    unioned_from: list[str] = []
    for content_id in sorted(actors):
        if content_id in CORE_2028_POWER_IDS:
            continue
        power_id = core_economy_actor_id(state, content_id)
        if power_id == content_id or power_id not in actors:
            continue
        content = actors[content_id]
        power = actors[power_id]
        before = set(power.researched_keys)
        merged = sorted(before | set(content.researched_keys))
        if merged != sorted(before):
            unioned_from.append(content_id)
        power.researched_keys = merged

    raw = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if not isinstance(raw, dict):
        raise ValueError("Strategic actor runtime is not installed")
    raw["actors"] = {key: actors[key].to_dict() for key in sorted(actors)}
    validate_strategic_actor_runtime(state)

    stamp = {
        "schema": CORE_PLAYER_ECONOMY_SCHEMA,
        "authority_rule": "core_power_per_coalition_side",
        "resources_folded": False,
        "constituent_wallets": "inert_preserved",
        "research_keys_unioned_from": unioned_from,
    }
    state.map_metadata[CORE_PLAYER_ECONOMY_KEY] = stamp
    return stamp
