from __future__ import annotations

from pathlib import Path

from gates_of_codex.actor_ai_economy import run_actor_ai_economy
from gates_of_codex.actor_economy import ACTOR_CONTENT_KEY, settle_actor_round_economy
from gates_of_codex.core_player_economy import (
    CORE_2028_POWER_IDS,
    CORE_PLAYER_ECONOMY_IDEM_MARKER,
    CORE_PLAYER_ECONOMY_KEY,
    CORE_PLAYER_ECONOMY_SCHEMA,
    core_economy_actor_id,
    migrate_core_player_economy_v1,
)
from gates_of_codex.frontend_actor_force import (
    apply_recruit_command,
    apply_repair_command,
    apply_research_command,
    build_actor_force_panel,
)
from gates_of_codex.frontend_commands import _apply_one
from gates_of_codex.models import Faction
from gates_of_codex.player_shell import continue_campaign, create_new_campaign, resolve_campaign_paths
from gates_of_codex.scenario_2028_core import CORE_2028_STARTING_TREASURY
from gates_of_codex.state_io import load_campaign, save_campaign
from gates_of_codex.strategic_actors import ACTOR_RUNTIME_KEY
from test_p2_earth3_campaign_bootstrap import _resolved_catalog

EARTH3_ACTIVE_START = {
    "usa": 600,
    "deu": 450,
    "pol": 450,
    "ukr": 600,
    "rus": 750,
}
LEGACY_RESEARCH_PROBES = {
    "usa": "actor:usa:unit:legacy_union_probe",
    "deu": "actor:deu:unit:legacy_union_probe",
    "pol": "actor:pol:unit:legacy_union_probe",
    "rus": "actor:rus:unit:legacy_union_probe",
}


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


def _fold_sources(stamp: dict, power_id: str) -> dict[str, int]:
    fold = stamp["folds"][power_id]
    return {row["actor_id"]: int(row["resources"]) for row in fold["sources"]}


def _assert_complete_stamp(stamp: object) -> dict:
    assert isinstance(stamp, dict)
    assert stamp["schema"] == CORE_PLAYER_ECONOMY_SCHEMA
    assert stamp["idempotence_marker"] == CORE_PLAYER_ECONOMY_IDEM_MARKER
    assert set(stamp["folds"]) == set(CORE_2028_POWER_IDS)
    return stamp


def _assert_no_cross_coalition_fold(stamp: dict) -> None:
    nato_sources = set(_fold_sources(stamp, "nato"))
    rusa_sources = set(_fold_sources(stamp, "rusa"))
    ukr_sources = set(_fold_sources(stamp, "ukr"))
    prc_sources = set(_fold_sources(stamp, "prc"))
    assert "rus" not in nato_sources
    assert {"usa", "deu", "pol"}.isdisjoint(rusa_sources)
    assert {"usa", "deu", "pol", "rus"}.isdisjoint(ukr_sources)
    assert {"usa", "deu", "pol", "rus"}.isdisjoint(prc_sources)
    assert "nato" not in rusa_sources | ukr_sources | prc_sources
    assert "rusa" not in nato_sources | ukr_sources | prc_sources


def _strip_to_legacy_core_shape(state, *, keep_overlays: frozenset[str]) -> None:
    runtime = _runtime(state)
    content = state.map_metadata[ACTOR_CONTENT_KEY]
    selected = str(runtime["selected_actor_id"])
    remove = [token for token in ("nato", "rusa") if token not in keep_overlays]
    for actor_id, row in runtime["actors"].items():
        if actor_id in EARTH3_ACTIVE_START:
            row["resources"] = EARTH3_ACTIVE_START[actor_id]
        elif actor_id in keep_overlays:
            row["resources"] = CORE_2028_STARTING_TREASURY[actor_id]
        elif actor_id == selected and selected in CORE_2028_POWER_IDS:
            row["resources"] = CORE_2028_STARTING_TREASURY[selected]
        if actor_id in LEGACY_RESEARCH_PROBES:
            row["researched_keys"] = sorted(
                set(row.get("researched_keys") or []) | {LEGACY_RESEARCH_PROBES[actor_id]}
            )
    for overlay in remove:
        runtime["actors"].pop(overlay, None)
        content["actors"].pop(overlay, None)
    content["actor_count"] = len(content["actors"])
    state.map_metadata.pop(CORE_PLAYER_ECONOMY_KEY, None)


def _legacy_continue(tmp_path: Path, player: str, *, keep_overlays: frozenset[str]):
    paths = resolve_campaign_paths(tmp_path / f"legacy_{player}.json")
    state = create_new_campaign(
        paths=paths,
        scenario_id="ww3_2028_core",
        faction=player,
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    _strip_to_legacy_core_shape(state, keep_overlays=keep_overlays)
    save_campaign(state, paths.campaign)
    return paths, continue_campaign(paths=paths)


def test_core_migration_folds_once_and_is_idempotent(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    stamp = _assert_complete_stamp(state.map_metadata.get(CORE_PLAYER_ECONOMY_KEY))
    assert _resources(state, "nato") == 2100
    assert _resources(state, "pol") == 0
    assert _resources(state, "deu") == 0
    assert _resources(state, "usa") == 0
    assert _resources(state, "rusa") == 750
    assert _resources(state, "rus") == 0
    nato_sources = _fold_sources(stamp, "nato")
    assert nato_sources["usa"] == 600
    assert nato_sources["deu"] == 450
    assert nato_sources["pol"] == 450
    assert stamp["folds"]["nato"]["source_resources_total"] == 1500
    assert stamp["folds"]["nato"]["core_resources_before"] == 600
    assert stamp["folds"]["nato"]["core_resources_after"] == 2100
    _assert_no_cross_coalition_fold(stamp)

    again = migrate_core_player_economy_v1(state)
    assert again == stamp
    assert _resources(state, "nato") == 2100
    assert _resources(state, "pol") == 0

    path = tmp_path / "folded.json"
    save_campaign(state, path)
    first_bytes = path.read_bytes()
    loaded = load_campaign(path)
    assert loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY] == stamp
    assert _resources(loaded, "nato") == 2100
    save_campaign(loaded, path)
    assert path.read_bytes() == first_bytes
    second = load_campaign(path)
    assert second.map_metadata[CORE_PLAYER_ECONOMY_KEY] == stamp
    assert _resources(second, "nato") == 2100


def test_schema_1_stamp_does_not_skip_required_fold_or_research(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    runtime = _runtime(state)
    for actor_id, amount in EARTH3_ACTIVE_START.items():
        runtime["actors"][actor_id]["resources"] = amount
    runtime["actors"]["nato"]["resources"] = CORE_2028_STARTING_TREASURY["nato"]
    runtime["actors"]["rusa"]["resources"] = CORE_2028_STARTING_TREASURY["rusa"]
    extra = "actor:pol:unit:schema1_union_probe"
    runtime["actors"]["pol"]["researched_keys"] = sorted(
        set(runtime["actors"]["pol"]["researched_keys"]) | {extra}
    )
    state.map_metadata[CORE_PLAYER_ECONOMY_KEY] = {
        "schema": 1,
        "authority_rule": "core_power_per_coalition_side",
        "resources_folded": False,
        "constituent_wallets": "inert_preserved",
        "research_keys_unioned_from": [],
    }
    path = tmp_path / "schema1.json"
    save_campaign(state, path)
    loaded = load_campaign(path)
    stamp = _assert_complete_stamp(loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY])
    assert extra in _runtime(loaded)["actors"]["nato"]["researched_keys"]
    assert extra in _runtime(loaded)["actors"]["pol"]["researched_keys"]
    assert "pol" in stamp["folds"]["nato"]["research_keys_unioned_from"]
    assert _resources(loaded, "nato") == 2100
    assert _resources(loaded, "pol") == 0
    save_campaign(loaded, path)
    first_bytes = path.read_bytes()
    second = load_campaign(path)
    save_campaign(second, path)
    assert path.read_bytes() == first_bytes
    assert _resources(second, "nato") == 2100


def test_legacy_nato_continue_folds_once_and_does_not_double(tmp_path: Path) -> None:
    paths, loaded = _legacy_continue(tmp_path, "nato", keep_overlays=frozenset({"nato"}))
    stamp = _assert_complete_stamp(loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY])
    assert "nato" in _runtime(loaded)["actors"]
    assert "rusa" in _runtime(loaded)["actors"]
    assert core_economy_actor_id(loaded, "pol") == "nato"
    assert core_economy_actor_id(loaded, "deu") == "nato"
    assert core_economy_actor_id(loaded, "usa") == "nato"
    assert core_economy_actor_id(loaded, "rus") == "rusa"
    assert _resources(loaded, "nato") == 2100
    assert _resources(loaded, "rusa") == 750
    assert _resources(loaded, "ukr") == 600
    assert _resources(loaded, "prc") == 0
    nato_sources = _fold_sources(stamp, "nato")
    assert nato_sources["usa"] == 600
    assert nato_sources["deu"] == 450
    assert nato_sources["pol"] == 450
    assert stamp["folds"]["nato"]["source_resources_total"] == 1500
    assert stamp["folds"]["rusa"]["core_resources_before"] == 0
    assert stamp["folds"]["rusa"]["core_resources_after"] == 750
    _assert_no_cross_coalition_fold(stamp)
    for actor_id, key in LEGACY_RESEARCH_PROBES.items():
        power = "rusa" if actor_id == "rus" else "nato"
        assert key in _runtime(loaded)["actors"][actor_id]["researched_keys"]
        assert key in _runtime(loaded)["actors"][power]["researched_keys"]

    first_bytes = paths.campaign.read_bytes()
    continued = continue_campaign(paths=paths)
    assert paths.campaign.read_bytes() == first_bytes
    assert _resources(continued, "nato") == 2100
    assert _resources(continued, "rusa") == 750
    assert continued.map_metadata[CORE_PLAYER_ECONOMY_KEY] == stamp


def test_legacy_rusa_continue_folds_once_and_does_not_double(tmp_path: Path) -> None:
    paths, loaded = _legacy_continue(tmp_path, "rusa", keep_overlays=frozenset({"rusa"}))
    stamp = _assert_complete_stamp(loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY])
    assert core_economy_actor_id(loaded, "rus") == "rusa"
    assert core_economy_actor_id(loaded, "pol") == "nato"
    assert _resources(loaded, "rusa") == 1500
    assert _resources(loaded, "nato") == 1500
    assert _resources(loaded, "rus") == 0
    assert _fold_sources(stamp, "rusa")["rus"] == 750
    assert stamp["folds"]["rusa"]["source_resources_total"] == 750
    assert stamp["folds"]["rusa"]["core_resources_before"] == 750
    assert stamp["folds"]["nato"]["core_resources_before"] == 0
    assert stamp["folds"]["nato"]["core_resources_after"] == 1500
    _assert_no_cross_coalition_fold(stamp)
    first_bytes = paths.campaign.read_bytes()
    continued = continue_campaign(paths=paths)
    assert paths.campaign.read_bytes() == first_bytes
    assert _resources(continued, "rusa") == 1500
    assert _resources(continued, "nato") == 1500


def test_legacy_ukr_continue_does_not_fold_unrelated_actors(tmp_path: Path) -> None:
    paths, loaded = _legacy_continue(tmp_path, "ukr", keep_overlays=frozenset())
    stamp = _assert_complete_stamp(loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY])
    assert "nato" in _runtime(loaded)["actors"]
    assert "rusa" in _runtime(loaded)["actors"]
    assert core_economy_actor_id(loaded, "ukr") == "ukr"
    assert core_economy_actor_id(loaded, "pol") == "nato"
    assert core_economy_actor_id(loaded, "rus") == "rusa"
    assert _resources(loaded, "ukr") == 600
    assert _resources(loaded, "nato") == 1500
    assert _resources(loaded, "rusa") == 750
    assert _resources(loaded, "prc") == 0
    assert stamp["folds"]["ukr"]["source_resources_total"] == 0
    assert stamp["folds"]["ukr"]["core_resources_after"] == 600
    _assert_no_cross_coalition_fold(stamp)
    _set_resources(loaded, "nato", 12_000)
    _set_resources(loaded, "rusa", 12_000)
    before_nato = _resources(loaded, "nato")
    before_rusa = _resources(loaded, "rusa")
    run_actor_ai_economy(loaded, Faction.RUSSIA)
    assert _resources(loaded, "nato") == before_nato
    assert _resources(loaded, "rusa") <= before_rusa
    assert _resources(loaded, "rus") == 0
    first_bytes = paths.campaign.read_bytes()
    continued = continue_campaign(paths=paths)
    assert paths.campaign.read_bytes() == first_bytes
    assert _resources(continued, "ukr") == 600


def test_legacy_prc_continue_does_not_fold_unrelated_actors(tmp_path: Path) -> None:
    paths, loaded = _legacy_continue(tmp_path, "prc", keep_overlays=frozenset())
    stamp = _assert_complete_stamp(loaded.map_metadata[CORE_PLAYER_ECONOMY_KEY])
    assert core_economy_actor_id(loaded, "prc") == "prc"
    assert core_economy_actor_id(loaded, "pol") == "nato"
    assert core_economy_actor_id(loaded, "rus") == "rusa"
    assert _resources(loaded, "prc") == 600
    assert _resources(loaded, "nato") == 1500
    assert _resources(loaded, "rusa") == 750
    assert _resources(loaded, "ukr") == 600
    assert stamp["folds"]["prc"]["source_resources_total"] == 0
    assert stamp["folds"]["prc"]["core_resources_after"] == 600
    _assert_no_cross_coalition_fold(stamp)
    first_bytes = paths.campaign.read_bytes()
    continued = continue_campaign(paths=paths)
    assert paths.campaign.read_bytes() == first_bytes
    assert _resources(continued, "prc") == 600


def test_expanded_nations_is_unchanged_by_core_fold(tmp_path: Path) -> None:
    expanded = create_new_campaign(
        paths=resolve_campaign_paths(tmp_path / "expanded.json"),
        scenario_id="ww3_2028_expanded",
        faction="nato",
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    from gates_of_codex.scenario_selection import apply_new_campaign_actor

    apply_new_campaign_actor(expanded, "ww3_2028_expanded", "pol")
    pol_before = _resources(expanded, "pol")
    usa_before = _resources(expanded, "usa")
    assert CORE_PLAYER_ECONOMY_KEY not in expanded.map_metadata
    assert migrate_core_player_economy_v1(expanded) is None
    assert CORE_PLAYER_ECONOMY_KEY not in expanded.map_metadata
    assert _resources(expanded, "pol") == pol_before
    assert _resources(expanded, "usa") == usa_before
    assert core_economy_actor_id(expanded, "pol") == "pol"


def test_folded_core_wallet_is_the_only_spend_target(tmp_path: Path) -> None:
    state = _core_campaign(tmp_path, "nato")
    assert _resources(state, "nato") == 2100
    polish = next(
        item
        for item in state.strategic_formations.values()
        if item.actor_id == "pol" and item.battalion_ids
    )
    _set_resources(state, "nato", 50_000)
    before_nationals = {key: _resources(state, key) for key in ("pol", "deu", "usa", "rus")}
    panel = build_actor_force_panel(
        state,
        {"actor": "nato", "formation": polish.strategic_formation_id},
    )
    research = [row for row in panel["available_research"] if int(row.get("cost") or 0) > 0]
    assert research
    chosen = min(research, key=lambda row: (int(row["cost"]), row["key"]))
    purchased = apply_research_command(
        state,
        {
            "actor": "pol",
            "formation": polish.strategic_formation_id,
            "key": chosen["key"],
        },
    )
    after_research = _resources(state, "nato")
    assert purchased["actor_id"] == "nato"
    assert after_research == 50_000 - int(purchased["cost"])

    offers = [row for row in panel["recruitment_offers"] if row.get("unlocked")]
    if not offers:
        panel = build_actor_force_panel(
            state,
            {"actor": "nato", "formation": polish.strategic_formation_id},
        )
        offers = [row for row in panel["recruitment_offers"] if row.get("unlocked")]
    assert offers
    offer = min(offers, key=lambda row: (int(row["purchase_cost"]), row["unit_name"]))
    apply_recruit_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "unit": offer["unit_name"],
            "quantity": 1,
        },
    )
    after_recruit = _resources(state, "nato")
    assert after_recruit == after_research - int(offer["purchase_cost"])

    battalion = state.battalions[polish.battalion_ids[0]]
    battalion.condition = 90
    battalion.supply = 80
    battalion.encircled_turns = 0
    apply_repair_command(
        state,
        {
            "actor": "nato",
            "formation": polish.strategic_formation_id,
            "battalion": polish.battalion_ids[0],
            "points": 1,
        },
    )
    after_repair = _resources(state, "nato")
    assert after_repair < after_recruit

    reports = {item.actor_id: item for item in settle_actor_round_economy(state)}
    assert reports["nato"].maintenance_due > 0
    assert reports["pol"].maintenance_due == 0
    assert _resources(state, "nato") == after_repair - int(reports["nato"].maintenance_due) + int(
        reports["nato"].income
    )
    for actor_id, amount in before_nationals.items():
        assert _resources(state, actor_id) == amount


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
