from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .models import CampaignState, Faction
from .scenario_2028_core import build_ww3_2028_core_campaign
from .strategic_actors import (
    ACTOR_ALIASES,
    ACTOR_MIGRATION_KEY,
    ACTOR_RUNTIME_KEY,
    StrategicActorState,
    install_bundled_strategic_actors,
)


EXPANDED_2028_SCENARIO_ID = "ww3_2028_expanded"
EXPANDED_2028_ACTOR_CATALOG_ID = "expanded_nations_2028"
EXPANDED_2028_ACTOR_CATALOG_VERSION = "1"
RESTORE_KEY = "ww3_2028_expanded_restore"


class Expanded2028ProjectionError(ValueError):
    """The audited Expanded Nations catalog cannot represent the 2028 controller."""


def _alias_actor_id(value: str) -> str:
    token = str(value or "").strip().lower()
    return ACTOR_ALIASES.get(token, token)


def _campaign_faction(actor: StrategicActorState) -> Faction:
    return actor.tactical_side.campaign_faction()


def _fallback_actor_for_faction(
    actors: Mapping[str, StrategicActorState],
    faction: Faction,
) -> str:
    preferred = {
        Faction.NATO: "nato",
        Faction.UKRAINE: "ukr",
        Faction.RUSSIA: "rus",
        Faction.PRC: "prc",
    }.get(faction)
    if preferred and preferred in actors and _campaign_faction(actors[preferred]) == faction:
        return preferred
    matches = sorted(
        actor_id
        for actor_id, actor in actors.items()
        if _campaign_faction(actor) == faction
    )
    if not matches:
        raise Expanded2028ProjectionError(
            f"expanded_2028_missing_actor_for_faction:{faction.value}"
        )
    return matches[0]


def _controller_actor_id(
    province: Any,
    actors: Mapping[str, StrategicActorState],
) -> str:
    core_controller = str(province.metadata.get("core_controller") or "")
    sovereign = _alias_actor_id(str(province.metadata.get("sovereign_owner") or ""))
    if core_controller == Faction.NEUTRAL.value:
        return sovereign if sovereign in actors else ""

    faction = Faction(core_controller)
    if faction == Faction.NATO and sovereign in actors:
        actor = actors[sovereign]
        if _campaign_faction(actor) == Faction.NATO:
            return sovereign
    return _fallback_actor_for_faction(actors, faction)


def _snapshot_for_restore(state: CampaignState) -> dict[str, Any]:
    if RESTORE_KEY in state.map_metadata:
        raise Expanded2028ProjectionError("expanded_2028_projection_already_active")
    province_metadata = {
        province_id: {
            "owner_actor_id_present": "owner_actor_id" in province.metadata,
            "owner_actor_id": copy.deepcopy(province.metadata.get("owner_actor_id")),
            "military_controller": copy.deepcopy(province.metadata.get("military_controller")),
            "controller_profile": copy.deepcopy(province.metadata.get("controller_profile")),
        }
        for province_id, province in state.provinces.items()
    }
    return {
        "schema_version": int(state.schema_version),
        "selected_faction": state.selected_faction.value,
        "current_faction": state.current_faction.value,
        "actor_runtime_present": ACTOR_RUNTIME_KEY in state.map_metadata,
        "actor_runtime": copy.deepcopy(state.map_metadata.get(ACTOR_RUNTIME_KEY)),
        "actor_migration_present": ACTOR_MIGRATION_KEY in state.map_metadata,
        "actor_migration": copy.deepcopy(state.map_metadata.get(ACTOR_MIGRATION_KEY)),
        "province_metadata": province_metadata,
    }


def _is_nonselectable(province: Any) -> bool:
    return province.metadata.get("selectable") is False


def apply_expanded_2028_projection(
    state: CampaignState,
    actors: Mapping[str, StrategicActorState],
) -> CampaignState:
    restore = _snapshot_for_restore(state)
    state.map_metadata[RESTORE_KEY] = restore

    for province_id, province in state.provinces.items():
        if _is_nonselectable(province):
            continue
        core_controller = str(province.metadata.get("core_controller") or "")
        if core_controller not in {faction.value for faction in Faction}:
            raise Expanded2028ProjectionError(
                f"expanded_2028_invalid_core_controller:{province_id}:{core_controller}"
            )
        actor_id = _controller_actor_id(province, actors)
        if core_controller == Faction.NEUTRAL.value:
            province.owner = Faction.NEUTRAL
            province.metadata["military_controller"] = "neutral"
            if actor_id:
                province.metadata["owner_actor_id"] = actor_id
            else:
                province.metadata.pop("owner_actor_id", None)
        else:
            if not actor_id or actor_id not in actors:
                raise Expanded2028ProjectionError(
                    f"expanded_2028_controller_actor_missing:{province_id}"
                )
            actor = actors[actor_id]
            expected = Faction(core_controller)
            actual = _campaign_faction(actor)
            if actual != expected:
                raise Expanded2028ProjectionError(
                    f"expanded_2028_controller_side_mismatch:{province_id}:{actor_id}"
                )
            province.owner = actual
            province.metadata["military_controller"] = actor_id
            province.metadata["owner_actor_id"] = actor_id
        province.metadata["expanded_controller_actor_id"] = actor_id
        province.metadata["controller_profile"] = "expanded"

    state.map_metadata["ww3_2028_controller_profile"] = "expanded"
    state.map_metadata["ww3_2028_expanded_actor_count"] = len(actors)
    state.map_metadata["ww3_2028_expanded_playable_actor_ids"] = sorted(
        actor_id for actor_id, actor in actors.items() if actor.playable
    )
    state.map_metadata["ww3_2028_expanded_strategic_only_actor_ids"] = sorted(
        actor_id for actor_id, actor in actors.items() if not actor.playable
    )
    return state


def restore_core_2028_projection(state: CampaignState) -> CampaignState:
    restore = state.map_metadata.get(RESTORE_KEY)
    if not isinstance(restore, Mapping):
        raise Expanded2028ProjectionError("expanded_2028_restore_state_missing")
    province_snapshot = restore.get("province_metadata")
    if not isinstance(province_snapshot, Mapping):
        raise Expanded2028ProjectionError("expanded_2028_restore_province_snapshot_missing")

    for province_id, province in state.provinces.items():
        if _is_nonselectable(province):
            continue
        prior = province_snapshot.get(province_id)
        if not isinstance(prior, Mapping):
            raise Expanded2028ProjectionError(
                f"expanded_2028_restore_province_missing:{province_id}"
            )
        core_controller = str(province.metadata.get("core_controller") or "")
        province.owner = Faction(core_controller)
        province.metadata["military_controller"] = copy.deepcopy(
            prior.get("military_controller")
        )
        province.metadata["controller_profile"] = copy.deepcopy(
            prior.get("controller_profile")
        )
        province.metadata.pop("expanded_controller_actor_id", None)
        if prior.get("owner_actor_id_present"):
            province.metadata["owner_actor_id"] = copy.deepcopy(prior.get("owner_actor_id"))
        else:
            province.metadata.pop("owner_actor_id", None)

    if restore.get("actor_runtime_present"):
        state.map_metadata[ACTOR_RUNTIME_KEY] = copy.deepcopy(restore.get("actor_runtime"))
    else:
        state.map_metadata.pop(ACTOR_RUNTIME_KEY, None)
    if restore.get("actor_migration_present"):
        state.map_metadata[ACTOR_MIGRATION_KEY] = copy.deepcopy(restore.get("actor_migration"))
    else:
        state.map_metadata.pop(ACTOR_MIGRATION_KEY, None)
    state.selected_faction = Faction(str(restore["selected_faction"]))
    state.current_faction = Faction(str(restore["current_faction"]))
    state.schema_version = int(restore["schema_version"])
    state.map_metadata["ww3_2028_controller_profile"] = "core"
    state.map_metadata.pop("ww3_2028_expanded_actor_count", None)
    state.map_metadata.pop("ww3_2028_expanded_playable_actor_ids", None)
    state.map_metadata.pop("ww3_2028_expanded_strategic_only_actor_ids", None)
    state.map_metadata.pop(RESTORE_KEY, None)
    return state


def build_ww3_2028_expanded_campaign(
    *,
    selected_actor_id: str | None = None,
    **core_options: Any,
) -> CampaignState:
    state = build_ww3_2028_core_campaign(**core_options)
    actors = install_bundled_strategic_actors(
        state,
        selected_actor_id=selected_actor_id,
    )
    apply_expanded_2028_projection(state, actors)
    return state
