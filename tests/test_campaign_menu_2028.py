from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from gates_of_codex import campaign_menu
from gates_of_codex.earth3_fixture_authority import earth3_requires_stack
from gates_of_codex.models import Faction


def test_menu_exposes_exact_core_and_expanded_new_campaign_profiles() -> None:
    model = campaign_menu.CampaignMenuModel()
    assert tuple(scenario_id for scenario_id, _ in model.scenarios()) == (
        "ww3_2028_core",
        "ww3_2028_expanded",
    )


def test_2028_player_scenarios_inherit_earth3_stack_authority_requirement() -> None:
    assert earth3_requires_stack("ww3_2028_core") is True
    assert earth3_requires_stack("ww3_2028_expanded") is True


def test_core_menu_exposes_exact_four_playable_actors() -> None:
    model = campaign_menu.CampaignMenuModel()
    assert tuple(choice.actor_id for choice in model.playable_actors("ww3_2028_core")) == (
        "nato",
        "ukr",
        "rusa",
        "prc",
    )


def test_expanded_menu_never_offers_strategic_only_actor_as_playable() -> None:
    model = campaign_menu.CampaignMenuModel()
    all_choices = model.actors("ww3_2028_expanded")
    playable = model.playable_actors("ww3_2028_expanded")
    assert all(choice.playable and not choice.strategic_only for choice in playable)
    assert {choice.actor_id for choice in playable}.isdisjoint(
        {choice.actor_id for choice in all_choices if choice.strategic_only}
    )


def test_expanded_new_campaign_maps_engine_side_to_four_seat_campaign_faction() -> None:
    model = campaign_menu.CampaignMenuModel()
    poland = next(
        choice for choice in model.playable_actors("ww3_2028_expanded") if choice.actor_id == "pol"
    )
    assert poland.tactical_side == "goc_pol"
    assert campaign_menu.campaign_faction_for_choice(poland) == "nato"

    prc = next(
        choice for choice in model.playable_actors("ww3_2028_expanded") if choice.actor_id == "prc"
    )
    assert campaign_menu.campaign_faction_for_choice(prc) == "prc"


def test_continue_summary_uses_persisted_scenario_and_actor(monkeypatch, tmp_path: Path) -> None:
    state = SimpleNamespace(
        map_metadata={
            "scenario_id": "ww3_2028_expanded",
            "scenario_profile": {"scenario_id": "ww3_2028_expanded"},
            "selected_scenario_actor_id": "pol",
        },
        selected_faction=Faction.NATO,
    )
    monkeypatch.setattr(campaign_menu, "load_campaign", lambda _path: state)
    summary = campaign_menu.CampaignMenuModel().continue_summary(tmp_path / "campaign.json")
    assert summary.scenario_id == "ww3_2028_expanded"
    assert summary.actor_id == "pol"
    assert summary.scenario_label


def test_menu_module_is_headless_importable() -> None:
    # tkinter is intentionally imported only inside main(), so CI/native model
    # tests can validate the player menu contract without requiring a display.
    assert campaign_menu.CampaignMenuModel is not None
