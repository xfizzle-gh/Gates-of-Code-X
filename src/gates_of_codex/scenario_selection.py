from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .faction_wiring_manifest import load_faction_manifest, validate_faction_manifest
from .models import CampaignState, Faction
from .scenario import get_scenario


NEW_CAMPAIGN_SCENARIO_IDS = ("ww3_2028_core", "ww3_2028_expanded")
PRODUCTION_NEW_CAMPAIGN_SCENARIO_ID = NEW_CAMPAIGN_SCENARIO_IDS[0]
EXPLICIT_FIXTURE_SCENARIO_IDS = frozenset(
    {
        "earth3_v1",
        "earth3_native_acceptance",
        "legacy_goe_europe",
        "legacy_goe_europe_mediterranean",
    }
)
CORE_2028_ACTORS = (
    ("nato", "NATO"),
    ("ukr", "Ukraine"),
    ("rusa", "Russia"),
    ("prc", "PRC"),
)
SELECTION_METADATA_KEY = "scenario_selection"


class ScenarioSelectionError(ValueError):
    """A New Campaign scenario/actor choice is unavailable or non-playable."""


@dataclass(frozen=True, slots=True)
class ScenarioChoice:
    scenario_id: str
    display_name: str
    profile: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ActorChoice:
    actor_id: str
    display_name: str
    playable: bool
    strategic_only: bool
    tactical_side: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_new_campaign_scenario_id(current_scenario_id: str = "") -> str:
    """Return the scenario a production New Campaign should create.

    The locked 2028 Core profile is the omitted/unknown default. An explicit
    Expanded pick or a named debug/legacy fixture is reused rather than silently
    rewritten. Continue must use persisted identity, not this resolver.
    """
    token = str(current_scenario_id or "").strip()
    if token in NEW_CAMPAIGN_SCENARIO_IDS or token in EXPLICIT_FIXTURE_SCENARIO_IDS:
        return token
    return PRODUCTION_NEW_CAMPAIGN_SCENARIO_ID


def new_campaign_scenarios() -> tuple[ScenarioChoice, ...]:
    return tuple(
        ScenarioChoice(
            scenario_id=scenario_id,
            display_name=get_scenario(scenario_id).display_name,
            profile="core" if scenario_id.endswith("_core") else "expanded",
        )
        for scenario_id in NEW_CAMPAIGN_SCENARIO_IDS
    )


def scenario_actor_choices(scenario_id: str) -> tuple[ActorChoice, ...]:
    if scenario_id == "ww3_2028_core":
        return tuple(
            ActorChoice(
                actor_id=actor_id,
                display_name=display_name,
                playable=True,
                strategic_only=False,
                tactical_side=actor_id,
            )
            for actor_id, display_name in CORE_2028_ACTORS
        )
    if scenario_id != "ww3_2028_expanded":
        raise ScenarioSelectionError(f"scenario_not_in_new_campaign_selector:{scenario_id}")

    manifest = load_faction_manifest()
    validate_faction_manifest(manifest)
    choices: list[ActorChoice] = []
    for row in manifest["actors"]:
        playable = bool(row["playable"])
        choices.append(
            ActorChoice(
                actor_id=str(row["actor_id"]),
                display_name=str(row["display_name"]),
                playable=playable,
                strategic_only=not playable,
                tactical_side=str(row["tactical_side"]),
            )
        )
    return tuple(sorted(choices, key=lambda item: (not item.playable, item.display_name, item.actor_id)))


def require_playable_actor(scenario_id: str, actor_id: str) -> ActorChoice:
    token = str(actor_id or "").strip()
    if not token:
        raise ScenarioSelectionError("new_campaign_actor_required")
    for choice in scenario_actor_choices(scenario_id):
        if choice.actor_id == token:
            if not choice.playable:
                raise ScenarioSelectionError(f"strategic_only_actor_not_playable:{token}")
            return choice
    raise ScenarioSelectionError(f"unknown_scenario_actor:{scenario_id}:{token}")


def apply_new_campaign_actor(
    state: CampaignState,
    scenario_id: str,
    actor_id: str,
) -> ActorChoice:
    choice = require_playable_actor(scenario_id, actor_id)
    if scenario_id == "ww3_2028_core":
        from .scenario_2028_core import bind_core_2028_selected_actor
        from .starter import set_player_faction

        set_player_faction(state, Faction(choice.actor_id))
        bind_core_2028_selected_actor(state, choice.actor_id)
    elif scenario_id == "ww3_2028_expanded":
        from .strategic_actors import set_selected_actor

        set_selected_actor(state, choice.actor_id)
    else:
        raise ScenarioSelectionError(f"scenario_not_in_new_campaign_selector:{scenario_id}")
    state.map_metadata["selected_scenario_actor_id"] = choice.actor_id
    stamp_scenario_selection_projection(state)
    return choice


def persisted_scenario_id(state: CampaignState) -> str:
    profile = state.map_metadata.get("scenario_profile")
    if isinstance(profile, dict):
        value = str(profile.get("scenario_id") or "").strip()
        if value:
            return value
    value = str(state.map_metadata.get("scenario_id") or "").strip()
    if not value:
        raise ScenarioSelectionError("persisted_scenario_id_missing")
    return value


def persisted_actor_id(state: CampaignState) -> str:
    explicit = str(state.map_metadata.get("selected_scenario_actor_id") or "").strip()
    if explicit:
        return explicit
    runtime = state.map_metadata.get("strategic_actor_runtime")
    if isinstance(runtime, dict):
        selected = str(runtime.get("selected_actor_id") or "").strip()
        if selected:
            return selected
    return state.selected_faction.value


def active_scenario_label(state: CampaignState) -> str:
    scenario_id = persisted_scenario_id(state)
    return get_scenario(scenario_id).display_name


def scenario_selection_projection(state: CampaignState | None = None) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "new_campaign": [choice.to_dict() for choice in new_campaign_scenarios()],
        "actors": {
            scenario_id: [choice.to_dict() for choice in scenario_actor_choices(scenario_id)]
            for scenario_id in NEW_CAMPAIGN_SCENARIO_IDS
        },
    }
    if state is not None:
        projection["active_scenario_id"] = persisted_scenario_id(state)
        projection["active_scenario_label"] = active_scenario_label(state)
        projection["active_actor_id"] = persisted_actor_id(state)
        projection["continue_uses_persisted_scenario"] = True
    return projection


def stamp_scenario_selection_projection(state: CampaignState) -> dict[str, Any]:
    projection = scenario_selection_projection(state)
    state.map_metadata[SELECTION_METADATA_KEY] = projection
    return projection
