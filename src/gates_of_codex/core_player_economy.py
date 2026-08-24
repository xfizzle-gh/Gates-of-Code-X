from __future__ import annotations

"""Core player-economy authority for ww3_2028_core.

Selected Core powers (nato/ukr/rusa/prc) own treasury, research state, and
ordinary strategic spend. National actors remain content/formation identity.
Expanded Nations is unchanged: each national actor keeps its own wallet.

Continue migration establishes every required Core-power overlay, unions
constituent research keys, then folds constituent treasuries into the matching
Core wallet exactly once. The resulting starting balance is a later explicit
balance issue if it proves unsuitable; money is not made inaccessible.
"""

from typing import Any, Mapping

from .models import CampaignState
from .strategic_actors import (
    ACTOR_RUNTIME_KEY,
    ensure_strategic_actor_runtime,
    validate_strategic_actor_runtime,
)

CORE_PLAYER_ECONOMY_KEY = "core_player_economy_v1"
CORE_PLAYER_ECONOMY_SCHEMA = 2
CORE_PLAYER_ECONOMY_IDEM_MARKER = "core_player_economy_v1_complete"
CORE_2028_POWER_IDS = ("nato", "ukr", "rusa", "prc")
CORE_COALITION_TO_POWER = {
    "atlantic": "nato",
    "eurasian": "rusa",
    "ukrainian": "ukr",
    "prc_aligned": "prc",
}
_FOLD_FIELDS = (
    "sources",
    "source_resources_total",
    "core_resources_before",
    "core_resources_after",
    "research_keys_unioned_from",
)


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
    After Continue migration, every Core coalition side has its power actor.
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


def _stamp_is_complete(stamp: Any, actors: Mapping[str, Any]) -> bool:
    if not isinstance(stamp, dict):
        return False
    try:
        schema = int(stamp.get("schema") or 0)
    except (TypeError, ValueError):
        return False
    if schema < CORE_PLAYER_ECONOMY_SCHEMA:
        return False
    if stamp.get("idempotence_marker") != CORE_PLAYER_ECONOMY_IDEM_MARKER:
        return False
    folds = stamp.get("folds")
    if not isinstance(folds, dict):
        return False
    for power_id in CORE_2028_POWER_IDS:
        if power_id not in actors:
            return False
        fold = folds.get(power_id)
        if not isinstance(fold, dict):
            return False
        if any(field not in fold for field in _FOLD_FIELDS):
            return False
        if not isinstance(fold.get("sources"), list):
            return False
    return True


def _fold_core_power(state: CampaignState, actors: dict[str, Any], power_id: str) -> dict[str, Any]:
    power = actors[power_id]
    sources: list[dict[str, Any]] = []
    unioned_from: list[str] = []
    merged_keys = set(power.researched_keys)
    before_resources = int(power.resources)
    added = 0
    for content_id in sorted(actors):
        if content_id == power_id:
            continue
        if core_economy_actor_id(state, content_id) != power_id:
            continue
        content = actors[content_id]
        source_resources = int(content.resources)
        sources.append({"actor_id": content_id, "resources": source_resources})
        added += source_resources
        content.resources = 0
        new_keys = set(content.researched_keys) - merged_keys
        if new_keys:
            unioned_from.append(content_id)
        merged_keys |= set(content.researched_keys)
    power.resources = before_resources + added
    power.researched_keys = sorted(merged_keys)
    return {
        "sources": sources,
        "source_resources_total": added,
        "core_resources_before": before_resources,
        "core_resources_after": int(power.resources),
        "research_keys_unioned_from": unioned_from,
    }


def migrate_core_player_economy_v1(state: CampaignState) -> dict[str, Any] | None:
    """Establish Core authorities, union research, and fold treasuries once.

    Explicit rule:
    - required NATO/RUSA overlays are created before any stamp is written
    - constituent research keys are unioned onto the matching Core power
    - constituent treasuries fold into that Core power exactly once
    - constituent rows stay serialized at 0 so a later load cannot fold twice
    - schema-1 ``resources_folded=false`` stamps are incomplete and are upgraded
    - second load is a no-op
    """

    if not is_core_2028_campaign(state):
        return None

    actors = ensure_strategic_actor_runtime(state)
    existing = state.map_metadata.get(CORE_PLAYER_ECONOMY_KEY)
    if _stamp_is_complete(existing, actors):
        return dict(existing)

    from .scenario_2028_core import ensure_core_2028_power_overlays

    ensure_core_2028_power_overlays(state)
    actors = ensure_strategic_actor_runtime(state)
    missing = [power_id for power_id in CORE_2028_POWER_IDS if power_id not in actors]
    if missing:
        raise ValueError(f"core_player_economy_missing_power:{','.join(missing)}")

    folds = {
        power_id: _fold_core_power(state, actors, power_id)
        for power_id in CORE_2028_POWER_IDS
    }

    raw = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    if not isinstance(raw, dict):
        raise ValueError("Strategic actor runtime is not installed")
    raw["actors"] = {key: actors[key].to_dict() for key in sorted(actors)}
    validate_strategic_actor_runtime(state)

    stamp = {
        "schema": CORE_PLAYER_ECONOMY_SCHEMA,
        "authority_rule": "core_power_per_coalition_side",
        "idempotence_marker": CORE_PLAYER_ECONOMY_IDEM_MARKER,
        "folds": folds,
    }
    state.map_metadata[CORE_PLAYER_ECONOMY_KEY] = stamp
    return stamp
