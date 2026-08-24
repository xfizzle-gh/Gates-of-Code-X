from __future__ import annotations

from pathlib import Path

import pytest

from gates_of_codex.actor_economy import ACTOR_CONTENT_KEY
from gates_of_codex.frontend_actor_force import (
    apply_assign_command,
    apply_recruit_command,
    apply_repair_command,
    apply_research_command,
    build_actor_force_panel,
)
from gates_of_codex.models import Faction
from gates_of_codex.player_shell import continue_campaign, create_new_campaign, resolve_campaign_paths
from gates_of_codex.scenario_selection import apply_new_campaign_actor
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import ACTOR_RUNTIME_KEY
from test_p2_earth3_campaign_bootstrap import _resolved_catalog


def _runtime(state) -> dict:
    runtime = state.map_metadata.get(ACTOR_RUNTIME_KEY)
    assert isinstance(runtime, dict)
    return runtime


def _resources(state, actor_id: str) -> int:
    return int(_runtime(state)["actors"][actor_id]["resources"])


def _set_resources(state, actor_id: str, amount: int) -> None:
    _runtime(state)["actors"][actor_id]["resources"] = amount


def _force_for_actor(state, actor_id: str):
    force = next(
        (
            item
            for item in state.strategic_formations.values()
            if item.actor_id == actor_id and item.battalion_ids
        ),
        None,
    )
    assert force is not None, actor_id
    return force


def _prepare_repairable(state, force) -> None:
    battalion = state.battalions[force.battalion_ids[0]]
    battalion.condition = 90
    battalion.supply = 80
    battalion.encircled_turns = 0


def _unlocked_offer(state, formation_id: str, panel: dict) -> dict:
    offers = [row for row in panel["recruitment_offers"] if row.get("unlocked")]
    if not offers:
        research = [row for row in panel["available_research"] if int(row.get("cost") or 0) >= 0]
        assert research, formation_id
        chosen = min(research, key=lambda row: (int(row["cost"]), row["key"]))
        apply_research_command(
            state,
            {"formation": formation_id, "key": chosen["key"], "actor": "nato"},
        )
        panel = build_actor_force_panel(state, {"actor": "nato", "formation": formation_id})
        offers = [row for row in panel["recruitment_offers"] if row.get("unlocked")]
    assert offers, formation_id
    return min(offers, key=lambda row: (int(row["purchase_cost"]), row["unit_name"]))


@pytest.fixture(scope="module")
def core_nato_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("core_nato") / "campaign.json"
    create_new_campaign(
        paths=resolve_campaign_paths(path),
        scenario_id="ww3_2028_core",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    return path


@pytest.fixture
def core_nato(core_nato_path: Path):
    return load_campaign(core_nato_path)


@pytest.fixture(scope="module")
def expanded_pol_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("expanded_pol") / "campaign.json"
    state = create_new_campaign(
        paths=resolve_campaign_paths(path),
        scenario_id="ww3_2028_expanded",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    apply_new_campaign_actor(state, "ww3_2028_expanded", "pol")
    save_campaign(state, path)
    return path


@pytest.fixture
def expanded_pol(expanded_pol_path: Path):
    return load_campaign(expanded_pol_path)


def test_core_nato_polish_force_panel_and_economy(core_nato) -> None:
    state = core_nato
    polish = _force_for_actor(state, "pol")
    german = _force_for_actor(state, "deu")
    assert polish.actor_id == "pol"
    assert german.actor_id == "deu"
    assert polish.faction == Faction.NATO
    _set_resources(state, "pol", 50_000)
    _set_resources(state, "deu", 40_000)
    _set_resources(state, "usa", 30_000)
    _set_resources(state, "nato", 25_000)
    before = {key: _resources(state, key) for key in ("pol", "deu", "usa", "nato")}

    panel = build_actor_force_panel(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "battalion": polish.battalion_ids[0],
        },
    )
    assert panel["can_manage_formation"] is True
    assert panel["command_actor_id"] == "nato"
    assert panel["actor_id"] == "nato"
    assert panel["formation_actor_id"] == "pol"
    assert panel["resources"] == before["nato"]
    assert panel["blocked_reasons"] == []
    assert panel["recruitment_offers"]
    assert {row["actor_id"] for row in panel["recruitment_offers"]} == {"pol"}

    offer = _unlocked_offer(state, polish.strategic_formation_id, panel)
    recruit = apply_recruit_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    assert recruit["actor_id"] == "pol"
    pool = state.map_metadata[ACTOR_CONTENT_KEY]["reinforcement_pool"]
    assert pool
    assert all(entry["actor_id"] == "pol" for entry in pool)
    assert all(entry["strategic_formation_id"] == polish.strategic_formation_id for entry in pool)

    assigned = apply_assign_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "battalion": polish.battalion_ids[0],
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    assert assigned["actor_id"] == "pol"

    _prepare_repairable(state, polish)
    repaired = apply_repair_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "battalion": polish.battalion_ids[0],
            "points": 1,
        },
    )
    assert repaired["actor_id"] == "pol"
    assert repaired["points_repaired"] == 1
    assert state.battalions[polish.battalion_ids[0]].condition == 91
    assert _resources(state, "nato") < before["nato"]
    assert _resources(state, "pol") == before["pol"]
    assert _resources(state, "deu") == before["deu"]
    assert _resources(state, "usa") == before["usa"]


def test_core_nato_german_force_panel_and_economy(core_nato) -> None:
    state = core_nato
    german = _force_for_actor(state, "deu")
    _set_resources(state, "deu", 50_000)
    _set_resources(state, "nato", 20_000)
    _set_resources(state, "pol", 20_000)
    before = {key: _resources(state, key) for key in ("deu", "nato", "pol")}
    panel = build_actor_force_panel(
        state,
        {"actor": "nato", "formation": german.strategic_formation_id},
    )
    assert panel["can_manage_formation"] is True
    assert panel["actor_id"] == "nato"
    assert panel["formation_actor_id"] == "deu"
    assert panel["command_actor_id"] == "nato"
    offer = _unlocked_offer(state, german.strategic_formation_id, panel)
    apply_recruit_command(
        state,
        {
            "actor": "nato",
            "formation": german.strategic_formation_id,
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    apply_assign_command(
        state,
        {
            "actor": "nato",
            "formation": german.strategic_formation_id,
            "battalion": german.battalion_ids[0],
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    _prepare_repairable(state, german)
    repaired = apply_repair_command(
        state,
        {
            "actor": "nato",
            "formation": german.strategic_formation_id,
            "battalion": german.battalion_ids[0],
            "points": 1,
        },
    )
    assert repaired["actor_id"] == "deu"
    assert _resources(state, "nato") < before["nato"]
    assert _resources(state, "deu") == before["deu"]
    assert _resources(state, "pol") == before["pol"]


def test_core_same_faction_foreign_coalition_is_rejected(core_nato) -> None:
    state = core_nato
    polish = _force_for_actor(state, "pol")
    _set_resources(state, "pol", 50_000)
    _set_resources(state, "nato", 50_000)
    _runtime(state)["actors"]["pol"]["coalition_id"] = "nonaligned"
    assert _runtime(state)["actors"]["nato"]["coalition_id"] != "nonaligned"
    before = {key: _resources(state, key) for key in ("pol", "nato")}
    panel = build_actor_force_panel(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "battalion": polish.battalion_ids[0],
        },
    )
    assert panel["can_manage_formation"] is False
    assert panel["recruitment_offers"] == []
    assert panel["reinforcement_pool"] == []
    assert panel["available_research"] == []
    assert panel["repair"]["can_repair"] is False
    assert panel["repair"]["points_needed"] == 0
    assert panel["actor_id"] == "nato"
    with pytest.raises(ValueError, match="command authority"):
        apply_recruit_command(
            state,
            {
                "actor": "nato",
                "formation": polish.strategic_formation_id,
                "unit": "fixture_pol",
                "quantity": 1,
            },
        )
    with pytest.raises(ValueError, match="command authority"):
        apply_assign_command(
            state,
            {
                "actor": "nato",
                "formation": polish.strategic_formation_id,
                "battalion": polish.battalion_ids[0],
                "unit": "fixture_pol",
                "quantity": 1,
            },
        )
    _prepare_repairable(state, polish)
    with pytest.raises(ValueError, match="command authority"):
        apply_repair_command(
            state,
            {
                "actor": "nato",
                "formation": polish.strategic_formation_id,
                "battalion": polish.battalion_ids[0],
                "points": 1,
            },
        )
    assert state.battalions[polish.battalion_ids[0]].condition == 90
    assert _resources(state, "pol") == before["pol"]
    assert _resources(state, "nato") == before["nato"]


def test_core_nato_rejects_russian_formation_and_spoils(core_nato) -> None:
    state = core_nato
    russian = _force_for_actor(state, "rus")
    polish = _force_for_actor(state, "pol")
    _set_resources(state, "rus", 50_000)
    _set_resources(state, "pol", 50_000)
    _set_resources(state, "nato", 50_000)
    before = {key: _resources(state, key) for key in ("rus", "pol", "nato")}
    rus_condition = state.battalions[russian.battalion_ids[0]].condition
    panel = build_actor_force_panel(
        state,
        {"actor": "nato", "formation": russian.strategic_formation_id},
    )
    assert panel["can_manage_formation"] is False
    assert panel["recruitment_offers"] == []
    assert panel["reinforcement_pool"] == []
    assert panel["actor_id"] == "nato"
    assert panel["resources"] == before["nato"]
    assert "rus" not in {row.get("actor_id") for row in panel["available_research"]}

    for payload in (
        {"actor": "nato", "formation": russian.strategic_formation_id, "unit": "fixture_rus"},
        {"actor": "pol", "formation": russian.strategic_formation_id, "unit": "fixture_rus"},
        {"actor": "rus", "formation": russian.strategic_formation_id, "unit": "fixture_rus"},
    ):
        with pytest.raises(ValueError, match="command authority"):
            apply_recruit_command(state, payload)
    _prepare_repairable(state, russian)
    with pytest.raises(ValueError, match="command authority"):
        apply_repair_command(
            state,
            {
                "actor": "pol",
                "formation": russian.strategic_formation_id,
                "battalion": russian.battalion_ids[0],
                "points": 1,
            },
        )
    assert state.battalions[russian.battalion_ids[0]].condition == 90
    assert _resources(state, "rus") == before["rus"]
    assert _resources(state, "pol") == before["pol"]
    assert _resources(state, "nato") == before["nato"]
    assert polish.actor_id == "pol"


@pytest.mark.parametrize("player", ("ukr", "rusa"))
def test_core_other_powers_manage_representative_formations(tmp_path: Path, player: str) -> None:
    from gates_of_codex.frontend_actor_force import player_may_command_formation

    path = tmp_path / f"{player}.json"
    state = create_new_campaign(
        paths=resolve_campaign_paths(path),
        scenario_id="ww3_2028_core",
        faction=player,
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    force = next(
        (
            item
            for item in state.strategic_formations.values()
            if item.battalion_ids and player_may_command_formation(state, item.strategic_formation_id)
        ),
        None,
    )
    assert force is not None, player
    from gates_of_codex.core_player_economy import core_economy_actor_id

    economy_actor = core_economy_actor_id(state, force.actor_id)
    _set_resources(state, economy_actor, 50_000)
    panel = build_actor_force_panel(
        state,
        {"actor": player, "formation": force.strategic_formation_id},
    )
    assert panel["can_manage_formation"] is True
    assert panel["command_actor_id"] == player
    assert panel["actor_id"] == economy_actor
    before = _resources(state, economy_actor)
    _prepare_repairable(state, force)
    repaired = apply_repair_command(
        state,
        {
            "actor": player,
            "formation": force.strategic_formation_id,
            "battalion": force.battalion_ids[0],
            "points": 1,
        },
    )
    assert repaired["actor_id"] == force.actor_id
    assert _resources(state, economy_actor) < before


def test_core_prc_has_no_starter_force_and_cannot_manage_foreign(tmp_path: Path) -> None:
    from gates_of_codex.frontend_actor_force import player_may_command_formation

    path = tmp_path / "prc.json"
    state = create_new_campaign(
        paths=resolve_campaign_paths(path),
        scenario_id="ww3_2028_core",
        faction="prc",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    assert not any(item.faction == Faction.PRC and item.battalion_ids for item in state.strategic_formations.values())
    assert not any(
        item.battalion_ids and player_may_command_formation(state, item.strategic_formation_id)
        for item in state.strategic_formations.values()
    )
    foreign = next(item for item in state.strategic_formations.values() if item.battalion_ids)
    with pytest.raises(ValueError, match="command authority"):
        apply_repair_command(
            state,
            {
                "actor": "prc",
                "formation": foreign.strategic_formation_id,
                "battalion": foreign.battalion_ids[0],
                "points": 1,
            },
        )


def test_expanded_poland_isolation(expanded_pol) -> None:
    state = expanded_pol
    polish = _force_for_actor(state, "pol")
    german = _force_for_actor(state, "deu")
    _set_resources(state, "pol", 50_000)
    _set_resources(state, "deu", 50_000)
    before = {key: _resources(state, key) for key in ("pol", "deu")}
    own = build_actor_force_panel(
        state,
        {"actor": "pol", "formation": polish.strategic_formation_id},
    )
    assert own["can_manage_formation"] is True
    assert own["actor_id"] == "pol"
    foreign = build_actor_force_panel(
        state,
        {"actor": "pol", "formation": german.strategic_formation_id},
    )
    assert foreign["can_manage_formation"] is False
    assert foreign["recruitment_offers"] == []
    with pytest.raises(ValueError, match="command authority"):
        apply_recruit_command(
            state,
            {
                "actor": "pol",
                "formation": german.strategic_formation_id,
                "unit": "fixture_deu",
            },
        )
    with pytest.raises(ValueError, match="command authority"):
        apply_recruit_command(
            state,
            {
                "actor": "deu",
                "formation": german.strategic_formation_id,
                "unit": "fixture_deu",
            },
        )
    _prepare_repairable(state, polish)
    repaired = apply_repair_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "battalion": polish.battalion_ids[0],
            "points": 1,
        },
    )
    assert repaired["actor_id"] == "pol"
    assert _resources(state, "pol") < before["pol"]
    assert _resources(state, "deu") == before["deu"]


def test_core_nato_research_and_recruit_spend_nato_not_national_wallets(core_nato) -> None:
    state = core_nato
    polish = _force_for_actor(state, "pol")
    german = _force_for_actor(state, "deu")
    _set_resources(state, "nato", 50_000)
    _set_resources(state, "pol", 0)
    _set_resources(state, "deu", 0)
    _set_resources(state, "usa", 0)
    before = {key: _resources(state, key) for key in ("nato", "pol", "deu", "usa")}
    panel = build_actor_force_panel(
        state,
        {"actor": "pol", "formation": polish.strategic_formation_id},
    )
    assert panel["actor_id"] == "nato"
    assert panel["resources"] == before["nato"]
    research = [row for row in panel["available_research"] if int(row.get("cost") or 0) > 0]
    assert research
    chosen = min(research, key=lambda row: (int(row["cost"]), row["key"]))
    assert chosen["key"].startswith("actor:pol:")
    purchased = apply_research_command(
        state,
        {"actor": "usa", "formation": polish.strategic_formation_id, "key": chosen["key"]},
    )
    assert purchased["actor_id"] == "nato"
    assert chosen["key"] in _runtime(state)["actors"]["nato"]["researched_keys"]
    assert _resources(state, "nato") == before["nato"] - int(purchased["cost"])
    assert _resources(state, "pol") == 0
    assert _resources(state, "usa") == 0

    panel = build_actor_force_panel(
        state,
        {"actor": "nato", "formation": polish.strategic_formation_id},
    )
    offer = _unlocked_offer(state, polish.strategic_formation_id, panel)
    apply_recruit_command(
        state,
        {
            "actor": "pol",
            "formation": polish.strategic_formation_id,
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    german_panel = build_actor_force_panel(
        state,
        {"actor": "nato", "formation": german.strategic_formation_id},
    )
    german_offer = _unlocked_offer(state, german.strategic_formation_id, german_panel)
    apply_recruit_command(
        state,
        {
            "actor": "deu",
            "formation": german.strategic_formation_id,
            "unit": german_offer["unit_name"],
            "quantity": 1,
        },
    )
    assert _resources(state, "nato") < before["nato"] - int(purchased["cost"])
    assert _resources(state, "pol") == 0
    assert _resources(state, "deu") == 0
    assert _resources(state, "usa") == 0


def test_save_continue_preserves_core_authority(core_nato_path: Path, tmp_path: Path) -> None:
    state = load_campaign(core_nato_path)
    polish = _force_for_actor(state, "pol")
    _set_resources(state, "nato", 50_000)
    _set_resources(state, "pol", 50_000)
    panel = build_actor_force_panel(
        state,
        {"actor": "nato", "formation": polish.strategic_formation_id},
    )
    offer = _unlocked_offer(state, polish.strategic_formation_id, panel)
    apply_recruit_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    destination = tmp_path / "continued.json"
    save_campaign(state, destination)
    loaded = continue_campaign(paths=resolve_campaign_paths(destination))
    assert loaded.strategic_formations[polish.strategic_formation_id].actor_id == "pol"
    assert _runtime(loaded)["selected_actor_id"] == "nato"
    resumed = build_actor_force_panel(
        loaded,
        {"actor": "nato", "formation": polish.strategic_formation_id},
    )
    assert resumed["can_manage_formation"] is True
    assert resumed["actor_id"] == "nato"
    assert resumed["formation_actor_id"] == "pol"
    assert any(entry["actor_id"] == "pol" for entry in resumed["reinforcement_pool"])
