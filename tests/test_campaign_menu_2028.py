from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from gates_of_codex import campaign_menu
from gates_of_codex.earth3_fixture_authority import earth3_requires_stack
from gates_of_codex.local_discovery import detect_launch_paths
from gates_of_codex.models import Faction
from gates_of_codex.scenario import DEFAULT_SCENARIO_ID


def test_menu_exposes_exact_core_and_expanded_new_campaign_profiles() -> None:
    model = campaign_menu.CampaignMenuModel()
    assert tuple(scenario_id for scenario_id, _ in model.scenarios()) == (
        "ww3_2028_core",
        "ww3_2028_expanded",
    )
    assert model.scenarios()[0][0] == DEFAULT_SCENARIO_ID == "ww3_2028_core"


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


def test_local_scanner_finds_stack_profile_godot_and_last_campaign(tmp_path: Path) -> None:
    repository = tmp_path / "Gates-of-Code-X"
    (repository / "config").mkdir(parents=True)
    (repository / "config" / "mod-stack.windows.json").write_text("{}", encoding="utf-8")
    (repository / "godot").mkdir()
    (repository / "godot" / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    steam = tmp_path / "Steam"
    game = steam / "steamapps" / "common" / "Call to Arms - Gates of Hell"
    game.mkdir(parents=True)
    workshop = steam / "steamapps" / "workshop" / "content" / "400750"
    west81 = workshop / "2897299509"
    codex = workshop / "3261086933"
    ai_overhaul = workshop / "3636883799"
    for layer in (west81, codex, ai_overhaul):
        layer.mkdir(parents=True)

    local = tmp_path / "Local"
    profile = local / "digitalmindsoft" / "gates of hell" / "profiles" / "46383268"
    profile.mkdir(parents=True)

    previous_campaign = local / "GatesOfCodeX" / "campaigns" / "ww3-core-test" / "campaign.json"
    previous_campaign.parent.mkdir(parents=True)
    previous_campaign.write_text(
        json.dumps(
            {
                "game_directory": str(game),
                "profile_directory": str(profile),
                "map_metadata": {},
            }
        ),
        encoding="utf-8",
    )
    pointer = local / "GatesOfCodeX" / "last_campaign.json"
    pointer.write_text(
        json.dumps(
            {
                "schema": "gates-of-codex.player-last-campaign",
                "schema_version": 1,
                "campaign_path": str(previous_campaign),
            }
        ),
        encoding="utf-8",
    )

    godot_root = tmp_path / "Godot Engine"
    godot_root.mkdir()
    godot = godot_root / "Godot_v4.7-stable_win64.exe"
    godot.write_bytes(b"")

    discovered = detect_launch_paths(
        "ww3_2028_expanded",
        environ={"LOCALAPPDATA": str(local)},
        repo_root=repository,
        steam_roots=(steam,),
        local_app_data=local,
        godot_search_roots=(godot_root,),
    )

    assert discovered.ready is True
    assert discovered.missing == ()
    assert discovered.stack_config == str((repository / "config" / "mod-stack.windows.json").resolve())
    assert discovered.game_directory == str(game.resolve())
    assert discovered.profile_directory == str(profile.resolve())
    assert discovered.godot_executable == str(godot.resolve())
    assert discovered.godot_project == str((repository / "godot").resolve())
    assert discovered.continue_campaign_file == str(previous_campaign.resolve())
    assert discovered.campaign_file == str(
        (local / "GatesOfCodeX" / "campaigns" / "ww3_2028_expanded" / "campaign.json").resolve(
            strict=False
        )
    )

    environment = dict(discovered.environment)
    assert environment["GOH_VANILLA_ROOT"] == str(game.resolve())
    assert environment["WEST81_ROOT"] == str(west81.resolve())
    assert environment["CODEX_ROOT"] == str(codex.resolve())
    assert environment["CODEX_AI_OVERHAUL_ROOT"] == str(ai_overhaul.resolve())
    assert environment["GATES_CODEX_ROOT"] == str(repository.resolve())
    assert environment["GATES_OF_CODEX_GODOT"] == str(godot.resolve())


def test_local_scanner_reports_missing_layers_without_guessing(tmp_path: Path) -> None:
    local = tmp_path / "Local"
    local.mkdir()
    discovered = detect_launch_paths(
        "ww3_2028_core",
        environ={"LOCALAPPDATA": str(local)},
        repo_root=tmp_path / "missing-repo",
        steam_roots=(),
        local_app_data=local,
        godot_search_roots=(),
    )

    assert discovered.ready is False
    assert "Gates of Hell" in discovered.missing
    assert "Code:X" in discovered.missing
    assert "Godot 4.7" in discovered.missing
    assert discovered.campaign_file.endswith("ww3_2028_core/campaign.json")


def test_menu_module_is_headless_importable() -> None:
    # tkinter is intentionally imported only inside main(), so CI/native model
    # tests can validate the player menu contract without requiring a display.
    assert campaign_menu.CampaignMenuModel is not None
