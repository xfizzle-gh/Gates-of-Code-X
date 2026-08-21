from __future__ import annotations

from types import SimpleNamespace

import pytest

from gates_of_codex.models import Faction
from gates_of_codex.scenario import DEFAULT_SCENARIO_ID
from gates_of_codex.scenario_selection import (
    PRODUCTION_NEW_CAMPAIGN_SCENARIO_ID,
    ScenarioSelectionError,
    active_scenario_label,
    new_campaign_scenarios,
    persisted_actor_id,
    persisted_scenario_id,
    require_playable_actor,
    resolve_new_campaign_scenario_id,
    scenario_actor_choices,
    scenario_selection_projection,
    stamp_scenario_selection_projection,
)


def _state(scenario_id: str, *, actor_id: str = "nato") -> SimpleNamespace:
    return SimpleNamespace(
        map_metadata={
            "scenario_id": scenario_id,
            "scenario_profile": {
                "scenario_id": scenario_id,
            },
            "selected_scenario_actor_id": actor_id,
        },
        selected_faction=Faction.NATO,
    )


def test_production_new_campaign_default_is_locked_2028_core() -> None:
    assert DEFAULT_SCENARIO_ID == PRODUCTION_NEW_CAMPAIGN_SCENARIO_ID == "ww3_2028_core"
    assert resolve_new_campaign_scenario_id("") == "ww3_2028_core"
    assert resolve_new_campaign_scenario_id("unknown_profile") == "ww3_2028_core"
    assert resolve_new_campaign_scenario_id("ww3_2028_core") == "ww3_2028_core"
    assert resolve_new_campaign_scenario_id("ww3_2028_expanded") == "ww3_2028_expanded"
    assert resolve_new_campaign_scenario_id("earth3_v1") == "earth3_v1"
    assert resolve_new_campaign_scenario_id("earth3_native_acceptance") == (
        "earth3_native_acceptance"
    )


def test_new_campaign_selector_offers_core_then_expanded_world_profiles() -> None:
    choices = new_campaign_scenarios()
    assert [choice.scenario_id for choice in choices] == [
        "ww3_2028_core",
        "ww3_2028_expanded",
    ]
    assert [choice.profile for choice in choices] == ["core", "expanded"]


def test_core_selector_is_exactly_four_playable_campaign_powers() -> None:
    choices = scenario_actor_choices("ww3_2028_core")
    assert [choice.actor_id for choice in choices] == ["nato", "ukr", "rusa", "prc"]
    assert len(choices) == 4
    assert all(choice.playable and not choice.strategic_only for choice in choices)


def test_expanded_selector_distinguishes_playable_and_strategic_only_actors() -> None:
    choices = scenario_actor_choices("ww3_2028_expanded")
    assert choices
    assert any(choice.playable for choice in choices)
    strategic_only = [choice for choice in choices if choice.strategic_only]
    assert strategic_only
    assert all(not choice.playable for choice in strategic_only)
    with pytest.raises(ScenarioSelectionError, match="strategic_only_actor_not_playable"):
        require_playable_actor("ww3_2028_expanded", strategic_only[0].actor_id)


def test_continue_projection_uses_persisted_scenario_and_actor_identity() -> None:
    state = _state("ww3_2028_expanded", actor_id="pol")
    projection = scenario_selection_projection(state)
    assert persisted_scenario_id(state) == "ww3_2028_expanded"
    assert persisted_actor_id(state) == "pol"
    assert projection["active_scenario_id"] == "ww3_2028_expanded"
    assert projection["active_actor_id"] == "pol"
    assert projection["continue_uses_persisted_scenario"] is True
    assert projection["active_scenario_label"] == active_scenario_label(state)


def test_strategic_metadata_projection_identifies_active_scenario() -> None:
    state = _state("ww3_2028_core", actor_id="ukr")
    projection = stamp_scenario_selection_projection(state)
    assert state.map_metadata["scenario_selection"] == projection
    assert projection["active_scenario_id"] == "ww3_2028_core"
    assert projection["active_actor_id"] == "ukr"
    assert "2028" in projection["active_scenario_label"]
