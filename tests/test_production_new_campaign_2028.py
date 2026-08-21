from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from gates_of_codex.cli import build_parser
from gates_of_codex.frontend import _player_launch_block
from gates_of_codex.models import Faction
from gates_of_codex.player_shell import (
    PlayerShellError,
    build_play_parser,
    create_new_campaign,
    continue_campaign,
    resolve_campaign_paths,
)
from gates_of_codex.scenario import DEFAULT_SCENARIO_ID, EARTH3_V1_SCENARIO_ID, get_scenario
from gates_of_codex.scenario_selection import (
    NEW_CAMPAIGN_SCENARIO_IDS,
    PRODUCTION_NEW_CAMPAIGN_SCENARIO_ID,
    persisted_actor_id,
    persisted_scenario_id,
    scenario_actor_choices,
)
from gates_of_codex.state_io import save_campaign
from test_p2_earth3_campaign_bootstrap import _resolved_catalog


def _play_args(*values: str):
    return build_play_parser().parse_args(list(values))


def test_play_and_cli_new_omit_scenario_resolve_to_2028_core() -> None:
    assert DEFAULT_SCENARIO_ID == PRODUCTION_NEW_CAMPAIGN_SCENARIO_ID
    assert DEFAULT_SCENARIO_ID == NEW_CAMPAIGN_SCENARIO_IDS[0]
    assert _play_args("--new").scenario == "ww3_2028_core"
    assert build_parser().parse_args(["new"]).scenario == "ww3_2028_core"
    assert _play_args("--new", "--scenario", "ww3_2028_expanded").scenario == (
        "ww3_2028_expanded"
    )
    assert _play_args("--new", "--scenario", "earth3_v1").scenario == "earth3_v1"
    assert get_scenario(EARTH3_V1_SCENARIO_ID).scenario_id == "earth3_v1"
    assert EARTH3_V1_SCENARIO_ID not in NEW_CAMPAIGN_SCENARIO_IDS


def test_godot_new_campaign_args_default_to_2028_core_and_continue_keeps_persisted(
    tmp_path: Path,
) -> None:
    campaign = tmp_path / "campaign.json"
    campaign.write_text("{}", encoding="utf-8")
    missing = SimpleNamespace(
        map_metadata={},
        selected_faction=Faction.NATO,
        difficulty="normal",
        fog_of_war_enabled=False,
        game_directory="",
        profile_directory="",
    )
    play = _player_launch_block(missing, campaign)
    assert play["new_args"][play["new_args"].index("--scenario") + 1] == "ww3_2028_core"
    assert "--scenario" not in play["continue_args"]

    expanded = SimpleNamespace(
        map_metadata={"scenario_id": "ww3_2028_expanded"},
        selected_faction=Faction.NATO,
        difficulty="normal",
        fog_of_war_enabled=False,
        game_directory="",
        profile_directory="",
    )
    expanded_play = _player_launch_block(expanded, campaign)
    assert (
        expanded_play["new_args"][expanded_play["new_args"].index("--scenario") + 1]
        == "ww3_2028_expanded"
    )
    assert (
        expanded_play["continue_args"][
            expanded_play["continue_args"].index("--scenario") + 1
        ]
        == "ww3_2028_expanded"
    )

    fixture = SimpleNamespace(
        map_metadata={"scenario_id": "earth3_v1"},
        selected_faction=Faction.NATO,
        difficulty="normal",
        fog_of_war_enabled=False,
        game_directory="",
        profile_directory="",
    )
    fixture_play = _player_launch_block(fixture, campaign)
    assert (
        fixture_play["new_args"][fixture_play["new_args"].index("--scenario") + 1]
        == "earth3_v1"
    )
    assert (
        fixture_play["continue_args"][fixture_play["continue_args"].index("--scenario") + 1]
        == "earth3_v1"
    )


def test_2028_core_allows_profile_actors_earth3_v1_seat_stays_nato(tmp_path: Path) -> None:
    core_paths = resolve_campaign_paths(tmp_path / "core.json")
    with pytest.raises(PlayerShellError, match="NATO"):
        create_new_campaign(
            paths=resolve_campaign_paths(tmp_path / "earth3.json"),
            scenario_id="earth3_v1",
            faction="ukr",
            resolved_catalog={},
        )
    state = create_new_campaign(
        paths=core_paths,
        faction="ukr",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    assert state.map_metadata["scenario_id"] == "ww3_2028_core"
    assert persisted_scenario_id(state) == "ww3_2028_core"
    assert persisted_actor_id(state) == "ukr"
    assert state.selected_faction == Faction.UKRAINE
    assert [choice.actor_id for choice in scenario_actor_choices("ww3_2028_core")] == [
        "nato",
        "ukr",
        "rusa",
        "prc",
    ]
    assert all(
        not choice.actor_id.startswith("goc_")
        for choice in scenario_actor_choices("ww3_2028_core")
    )


def test_production_new_campaign_and_continue_yield_2028_core(tmp_path: Path) -> None:
    paths = resolve_campaign_paths(tmp_path / "campaign.json")
    created = create_new_campaign(
        paths=paths,
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    assert created.map_metadata["scenario_id"] == "ww3_2028_core"
    assert created.map_metadata["scenario_status"] == "production"
    assert get_scenario(created.map_metadata["scenario_id"]).status == "production"
    assert get_scenario(DEFAULT_SCENARIO_ID).status == "production"
    assert created.map_metadata["scenario_profile"]["scenario_id"] == "ww3_2028_core"
    assert created.map_metadata["scenario_profile"]["actor_catalog_id"] == "core_2028"
    assert persisted_actor_id(created) == "nato"
    assert created.map_metadata["ww3_2028_controller_profile"] == "core"
    save_campaign(created, paths.campaign)

    continued = continue_campaign(paths=paths)
    assert persisted_scenario_id(continued) == "ww3_2028_core"
    assert continued.map_metadata["scenario_id"] == "ww3_2028_core"
    assert persisted_actor_id(continued) == "nato"
    assert continued.map_metadata["scenario_selection"]["continue_uses_persisted_scenario"] is True


def test_explicit_expanded_and_earth3_v1_fixture_remain_available(tmp_path: Path) -> None:
    expanded_paths = resolve_campaign_paths(tmp_path / "expanded.json")
    expanded = create_new_campaign(
        paths=expanded_paths,
        scenario_id="ww3_2028_expanded",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    assert expanded.map_metadata["scenario_id"] == "ww3_2028_expanded"
    assert expanded.map_metadata["scenario_status"] == "development"
    assert get_scenario("ww3_2028_expanded").status == "development"
    assert expanded.map_metadata["scenario_profile"]["actor_catalog_id"] == (
        "expanded_nations_2028"
    )
    assert expanded.map_metadata["ww3_2028_controller_profile"] == "expanded"
    expanded_rules = expanded.map_metadata.get("campaign_rules") or {}
    assert "objective_pack_id" not in expanded_rules
    assert expanded_rules.get("objective_pack_id") not in {"ww3_2028_core", "earth3_v1"}

    fixture_paths = resolve_campaign_paths(tmp_path / "earth3.json")
    fixture = create_new_campaign(
        paths=fixture_paths,
        scenario_id="earth3_v1",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    assert fixture.map_metadata["scenario_id"] == "earth3_v1"
    assert fixture.map_metadata.get("ww3_2028_controller_profile") in {None, ""}


def test_expanded_auto_resolve_stays_playable_without_victory_pack(tmp_path: Path) -> None:
    """Unmocked Expanded New Campaign → pending battle → Auto-Resolve → playable."""

    from gates_of_codex.campaign import CampaignEngine
    from gates_of_codex.campaign_rules import (
        CAMPAIGN_RULES_KEY,
        CampaignRulesError,
        campaign_play_blocked,
        require_available_victory_pack,
        resolve_objective_pack_id,
    )
    from gates_of_codex.models import BattleParticipant, Faction, PendingBattle
    from gates_of_codex.strategic import evaluate_campaign_outcome

    paths = resolve_campaign_paths(tmp_path / "expanded-ar.json")
    state = create_new_campaign(
        paths=paths,
        scenario_id="ww3_2028_expanded",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    rules = state.map_metadata.get(CAMPAIGN_RULES_KEY) or {}
    assert "objective_pack_id" not in rules
    assert rules.get("objective_pack_id") not in {"ww3_2028_core", "earth3_v1"}

    attacker = next(
        battalion
        for battalion in state.battalions.values()
        if battalion.faction == Faction.NATO and battalion.unit_count > 0
    )
    defender = next(
        battalion
        for battalion in state.battalions.values()
        if battalion.faction == Faction.RUSSIA and battalion.unit_count > 0
    )
    state.pending_battle = PendingBattle(
        battle_id="expanded-production-ar",
        origin_province_id=attacker.province_id,
        target_province_id=defender.province_id,
        attacker_faction=Faction.NATO,
        defender_faction=Faction.RUSSIA,
        attacking_participants=[
            BattleParticipant(attacker.battalion_id, Faction.NATO, "committed", is_primary=True)
        ],
        defending_participants=[
            BattleParticipant(defender.battalion_id, Faction.RUSSIA, "committed", is_primary=True)
        ],
        player_faction=Faction.NATO,
        player_is_attacker=True,
    )
    winner = CampaignEngine(state).auto_resolve_pending_battle()
    assert winner in {Faction.NATO, Faction.RUSSIA}
    assert state.pending_battle is None
    outcome = evaluate_campaign_outcome(state)
    assert outcome.status == "active"
    assert outcome.selected_faction_result == "active"
    assert outcome.grade == ""
    assert not campaign_play_blocked(state)
    assert "objective_pack_id" not in (state.map_metadata.get(CAMPAIGN_RULES_KEY) or {})
    with pytest.raises(CampaignRulesError, match="unavailable"):
        require_available_victory_pack(state)
    with pytest.raises(CampaignRulesError, match="Core-four pack"):
        resolve_objective_pack_id("ww3_2028_expanded")
    CampaignEngine(state).end_turn()
    assert not campaign_play_blocked(state)


def test_persist_seam_untouched_by_production_default() -> None:
    from gates_of_codex.command_cycle_perf import (
        _LIVE_MOVE_BATCH,
        _RUNTIME_PATCH_OPS,
        _SNAPSHOT_PATCH_OPS,
        _should_persist_runtime_snapshot,
    )
    from gates_of_codex.frontend_runtime_patch import (
        RUNTIME_PATCH_SCHEMA,
        RUNTIME_PATCH_SCHEMA_VERSION,
    )

    assert _LIVE_MOVE_BATCH == ("issue_move_order", "commit_move_orders")
    assert "refresh" not in _RUNTIME_PATCH_OPS
    assert "refresh" not in _SNAPSHOT_PATCH_OPS
    assert _should_persist_runtime_snapshot(
        [{"op": "issue_move_order"}, {"op": "commit_move_orders"}]
    )
    assert _should_persist_runtime_snapshot([{"op": "auto_resolve"}])
    assert not _should_persist_runtime_snapshot([{"op": "refresh"}])
    assert RUNTIME_PATCH_SCHEMA == "gates-of-codex.frontend-runtime-patch"
    assert RUNTIME_PATCH_SCHEMA_VERSION == 1
