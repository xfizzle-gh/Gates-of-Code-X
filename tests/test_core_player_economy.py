from __future__ import annotations

from pathlib import Path

from gates_of_codex.actor_ai_economy import run_actor_ai_economy
from gates_of_codex.actor_economy import settle_actor_round_economy
from gates_of_codex.core_player_economy import (
    CORE_PLAYER_ECONOMY_KEY,
    core_economy_actor_id,
    migrate_core_player_economy_v1,
)
from gates_of_codex.frontend_actor_force import apply_research_command, build_actor_force_panel
from gates_of_codex.frontend_commands import _apply_one
from gates_of_codex.models import Faction
from gates_of_codex.player_shell import create_new_campaign, resolve_campaign_paths
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


def _core_campaign(tmp_path: Path, player: str):
    path = tmp_path / f"{player}.json"
    return create_new_campaign(
        paths=resolve_campaign_paths(path),
        scenario_id="ww3_2028_core",
        faction=player,
        force=True,
        resolved_catalog=_resolved_catalog(),
    )


def test_core_economy_maps_nationals_to_power_and_leaves_expanded(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    assert core_economy_actor_id(state, "pol") == "nato"
    assert core_economy_actor_id(state, "deu") == "nato"
    assert core_economy_actor_id(state, "usa") == "nato"
    assert core_economy_actor_id(state, "nato") == "nato"
    assert core_economy_actor_id(state, "rus") == "rusa"
    assert core_economy_actor_id(state, "ukr") == "ukr"

    expanded = create_new_campaign(
        paths=resolve_campaign_paths(tmp_path / "expanded.json"),
        scenario_id="ww3_2028_expanded",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    from gates_of_codex.scenario_selection import apply_new_campaign_actor

    apply_new_campaign_actor(expanded, "ww3_2028_expanded", "pol")
    assert core_economy_actor_id(expanded, "pol") == "pol"
    assert core_economy_actor_id(expanded, "deu") == "deu"


def test_core_migration_is_idempotent_and_does_not_fold_wallets(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    stamp = state.map_metadata.get(CORE_PLAYER_ECONOMY_KEY)
    assert isinstance(stamp, dict)
    assert stamp["resources_folded"] is False
    nato_before = _resources(state, "nato")
    pol_before = _resources(state, "pol")
    again = migrate_core_player_economy_v1(state)
    assert again == stamp
    assert _resources(state, "nato") == nato_before
    assert _resources(state, "pol") == pol_before

    path = tmp_path / "legacy.json"
    del state.map_metadata[CORE_PLAYER_ECONOMY_KEY]
    extra = "actor:pol:unit:legacy_unlock"
    _runtime(state)["actors"]["pol"]["researched_keys"] = sorted(
        set(_runtime(state)["actors"]["pol"]["researched_keys"]) | {extra}
    )
    save_campaign(state, path)
    loaded = load_campaign(path)
    assert loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY]["schema"] == 1
    assert extra in _runtime(loaded)["actors"]["nato"]["researched_keys"]
    assert extra in _runtime(loaded)["actors"]["pol"]["researched_keys"]
    assert _resources(loaded, "nato") == nato_before
    second = load_campaign(path)
    assert second.map_metadata[CORE_PLAYER_ECONOMY_KEY] == loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY]


def test_core_ukr_rusa_prc_representative_paths(tmp_path: Path) -> None:
    ukr = _core_campaign(tmp_path, "ukr")
    force = next(
        item
        for item in ukr.strategic_formations.values()
        if item.actor_id == "ukr" and item.battalion_ids
    )
    _set_resources(ukr, "ukr", 50_000)
    panel = build_actor_force_panel(ukr, {"actor": "nato", "formation": force.strategic_formation_id})
    assert panel["actor_id"] == "ukr"
    assert panel["can_manage_formation"] is True
    research = [row for row in panel["available_research"] if int(row.get("cost") or 0) > 0]
    if research:
        chosen = min(research, key=lambda row: (int(row["cost"]), row["key"]))
        before = _resources(ukr, "ukr")
        purchased = apply_research_command(
            ukr,
            {"actor": "pol", "formation": force.strategic_formation_id, "key": chosen["key"]},
        )
        assert purchased["actor_id"] == "ukr"
        assert _resources(ukr, "ukr") == before - int(purchased["cost"])

    rusa = _core_campaign(tmp_path, "rusa")
    rus_force = next(
        item
        for item in rusa.strategic_formations.values()
        if item.actor_id == "rus" and item.battalion_ids
    )
    _set_resources(rusa, "rusa", 40_000)
    rus_before = _resources(rusa, "rus")
    panel = build_actor_force_panel(
        rusa,
        {"actor": "rus", "formation": rus_force.strategic_formation_id},
    )
    assert panel["actor_id"] == "rusa"
    assert panel["formation_actor_id"] == "rus"
    from gates_of_codex.frontend_actor_force import apply_repair_command

    battalion = rusa.battalions[rus_force.battalion_ids[0]]
    battalion.condition = 90
    battalion.supply = 80
    battalion.encircled_turns = 0
    apply_repair_command(
        rusa,
        {
            "actor": "rus",
            "formation": rus_force.strategic_formation_id,
            "battalion": rus_force.battalion_ids[0],
            "points": 1,
        },
    )
    assert _resources(rusa, "rusa") < 40_000
    assert _resources(rusa, "rus") == rus_before

    prc = _core_campaign(tmp_path, "prc")
    assert _runtime(prc)["selected_actor_id"] == "prc"
    polish = next(item for item in prc.strategic_formations.values() if item.battalion_ids)
    from gates_of_codex.frontend_actor_force import apply_repair_command as repair

    try:
        repair(
            prc,
            {
                "actor": "prc",
                "formation": polish.strategic_formation_id,
                "battalion": polish.battalion_ids[0],
                "points": 1,
            },
        )
        raise AssertionError("PRC must not manage a foreign formation")
    except ValueError as exc:
        assert "command authority" in str(exc)


def test_core_ai_cannot_spend_player_nato_treasury(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    _set_resources(state, "nato", 12_000)
    _set_resources(state, "rusa", 12_000)
    _set_resources(state, "rus", 12_000)
    before_nato = _resources(state, "nato")
    before_rusa = _resources(state, "rusa")
    run_actor_ai_economy(state, Faction.RUSSIA)
    assert _resources(state, "nato") == before_nato
    assert _resources(state, "rusa") <= before_rusa


def test_core_settlement_charges_nato_not_polish_wallet(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    nato_before = _resources(state, "nato")
    pol_before = _resources(state, "pol")
    reports = {item.actor_id: item for item in settle_actor_round_economy(state)}
    assert reports["nato"].maintenance_due > 0
    assert reports["pol"].maintenance_due == 0
    assert _resources(state, "nato") < nato_before
    assert _resources(state, "pol") == pol_before


def test_core_site_upgrade_ignores_payload_spoof(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    province_id = next(
        pid
        for pid, province in state.provinces.items()
        if str(province.metadata.get("owner_actor_id") or "") == "pol"
        and province.owner == Faction.NATO
    )
    _set_resources(state, "nato", 5_000)
    _set_resources(state, "pol", 5_000)
    before_pol = _resources(state, "pol")
    result = _apply_one(
        state,
        "upgrade_site",
        {
            "op": "upgrade_site",
            "province": province_id,
            "actor": "pol",
        },
    )
    assert result.ok is True
    assert _resources(state, "nato") == 5_000 - 400
    assert _resources(state, "pol") == before_pol
