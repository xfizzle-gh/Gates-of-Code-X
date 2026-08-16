from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from gates_of_codex.models import Faction
from gates_of_codex.neutral_nation_runtime import (
    advance_neutral_garrison_recovery,
    capture_garrison_battle_state,
    garrison_is_mobilized_against,
    nation_is_hostile_to,
    validate_neutral_nation_runtime,
)
from gates_of_codex.scenario import get_scenario, load_legacy_test_scenario
from gates_of_codex.scenario_2028_acceptance import (
    Scenario2028AcceptanceError,
    cross_mode_contract_report,
    load_acceptance_gate,
    validate_acceptance_gate,
)
from gates_of_codex.scenario_2028_authority import load_province_authority
from gates_of_codex.scenario_2028_expanded import (
    apply_expanded_2028_projection,
    restore_core_2028_projection,
)
from gates_of_codex.scenario_profile import (
    ScenarioProfileError,
    require_compatible_scenario_profile,
    stamp_scenario_profile,
)
from gates_of_codex.scenario_selection import (
    apply_new_campaign_actor,
    new_campaign_scenarios,
    persisted_actor_id,
    scenario_actor_choices,
)
from gates_of_codex.state_io import campaign_from_dict, save_campaign
from gates_of_codex.strategic_actors import (
    EngineTacticalSide,
    StrategicActorState,
)
from test_p2_earth3_campaign_bootstrap import _resolved_catalog


ROOT = Path(__file__).resolve().parents[1]


def _actor(actor_id: str, side: str, *, playable: bool = True) -> StrategicActorState:
    return StrategicActorState(
        actor_id=actor_id,
        display_name=actor_id.upper(),
        short_name=actor_id.upper(),
        actor_type="sovereign",
        coalition_id="test",
        tactical_side=EngineTacticalSide(side),
        playable=playable,
        roster_class="compatibility",
    )


def _province(province_id: str, sovereign: str, controller: str) -> SimpleNamespace:
    return SimpleNamespace(
        province_id=province_id,
        owner=Faction(controller),
        metadata={
            "sovereign_owner": sovereign,
            "military_controller": controller,
            "core_controller": controller,
            "controller_profile": "core",
        },
    )


def _cross_mode_state() -> SimpleNamespace:
    return SimpleNamespace(
        turn_number=2,
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
        schema_version=9,
        battalions={},
        strategic_formations={},
        provinces={
            "pol": _province("pol", "POL", "nato"),
            "ukr": _province("ukr", "UKR", "ukr"),
            "occ": _province("occ", "UKR", "rusa"),
            "blr": _province("blr", "BLR", "prc"),
            "srb_a": _province("srb_a", "SRB", "neutral"),
            "srb_b": _province("srb_b", "SRB", "neutral"),
        },
        map_metadata={
            "scenario_id": "ww3_2028_core",
            "ww3_2028_controller_profile": "core",
        },
    )


def _actors() -> dict[str, StrategicActorState]:
    return {
        "nato": _actor("nato", "nato"),
        "pol": _actor("pol", "nato"),
        "ukr": _actor("ukr", "ukr"),
        "rus": _actor("rus", "rusa"),
        "prc": _actor("prc", "prc"),
        "srb": _actor("srb", "neutral", playable=False),
    }


def _controller_snapshot(state: SimpleNamespace) -> dict[str, object]:
    return {
        province_id: {
            "owner": province.owner.value,
            "metadata": copy.deepcopy(province.metadata),
        }
        for province_id, province in state.provinces.items()
    }


def test_core_and_expanded_share_world_authority_but_not_actor_catalog() -> None:
    report = cross_mode_contract_report()
    assert report["scenario_year"] == 2028
    assert report["shared_world_authority"] is True
    assert report["distinct_actor_catalogs"] is True
    assert report["core"]["world_authority_id"] == "earth3_ww3_2028_v1"
    assert report["expanded"]["world_authority_id"] == "earth3_ww3_2028_v1"


def test_new_campaign_cross_mode_selector_is_scenario_first() -> None:
    scenarios = new_campaign_scenarios()
    assert [row.scenario_id for row in scenarios] == [
        "ww3_2028_core",
        "ww3_2028_expanded",
    ]
    assert [row.actor_id for row in scenario_actor_choices("ww3_2028_core")] == [
        "nato",
        "ukr",
        "rusa",
        "prc",
    ]
    expanded = scenario_actor_choices("ww3_2028_expanded")
    assert any(row.playable for row in expanded)
    assert any(row.strategic_only for row in expanded)


@pytest.mark.parametrize(
    ("scenario_id", "actor_id", "campaign_faction"),
    [
        ("ww3_2028_core", "nato", "nato"),
        ("ww3_2028_expanded", "pol", "nato"),
    ],
)
def test_new_campaign_save_continue_preserves_exact_profile_actor_and_real_authority(
    tmp_path: Path,
    scenario_id: str,
    actor_id: str,
    campaign_faction: str,
) -> None:
    from gates_of_codex import player_shell

    paths = player_shell.resolve_campaign_paths(tmp_path / f"{scenario_id}.json")
    state = player_shell.create_new_campaign(
        paths=paths,
        scenario_id=scenario_id,
        faction=campaign_faction,
        force=True,
        resolved_catalog=_resolved_catalog(),
    )
    assert len(state.provinces) == 3299
    apply_new_campaign_actor(state, scenario_id, actor_id)
    save_campaign(state, paths.campaign)

    continued = player_shell.continue_campaign(paths=paths)
    assert len(continued.provinces) == 3299
    assert continued.map_metadata["scenario_profile"]["scenario_id"] == scenario_id
    assert continued.map_metadata["scenario_id"] == scenario_id
    assert persisted_actor_id(continued) == actor_id
    assert continued.map_metadata["scenario_selection"]["continue_uses_persisted_scenario"] is True


def test_core_expanded_core_preserves_world_and_real_expanded_hostility_hook(monkeypatch) -> None:
    from gates_of_codex import neutral_garrison as garrison
    from gates_of_codex.campaign import CampaignEngine
    from gates_of_codex.neutral_nation_runtime_hooks import install_neutral_nation_runtime_hooks

    state = _cross_mode_state()
    state.map_metadata["scenario_id"] = "ww3_2028_expanded"
    state.strategic_formations["sf_pol"] = SimpleNamespace(actor_id="pol")
    attacker = SimpleNamespace(strategic_formation_id="sf_pol", faction=Faction.NATO)
    pending = SimpleNamespace(target_province_id="srb_a")

    monkeypatch.setattr(garrison, "maybe_attach_neutral_garrison", lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(garrison, "sync_neutral_garrison_after_battle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(CampaignEngine, "end_turn", lambda *_args, **_kwargs: None)
    install_neutral_nation_runtime_hooks()

    result = garrison.maybe_attach_neutral_garrison(state, "srb_a", attacker=attacker)
    assert result is pending
    garrison.sync_neutral_garrison_after_battle(state, pending, Faction.NATO)
    assert nation_is_hostile_to(state, "SRB", "pol") is True
    assert nation_is_hostile_to(state, "SRB", "nato") is False
    assert garrison_is_mobilized_against(state, "srb_b", "pol") is True
    before = _controller_snapshot(state)
    neutral_before = copy.deepcopy(state.map_metadata["neutral_nation_runtime"])

    apply_expanded_2028_projection(state, _actors())
    assert state.provinces["pol"].metadata["military_controller"] == "pol"
    assert state.provinces["occ"].metadata["military_controller"] == "rus"
    assert state.provinces["blr"].metadata["military_controller"] == "prc"
    assert state.provinces["blr"].metadata["sovereign_owner"] == "BLR"
    assert nation_is_hostile_to(state, "SRB", "pol") is True

    restore_core_2028_projection(state)
    assert _controller_snapshot(state) == before
    assert state.map_metadata["neutral_nation_runtime"] == neutral_before
    assert nation_is_hostile_to(state, "SRB", "pol") is True
    assert nation_is_hostile_to(state, "SRB", "nato") is False
    assert nation_is_hostile_to(state, "SRB", "ukr") is False


def test_core_neutral_battle_hook_uses_four_seat_attacker_identity(monkeypatch) -> None:
    from gates_of_codex import neutral_garrison as garrison
    from gates_of_codex.campaign import CampaignEngine
    from gates_of_codex.neutral_nation_runtime_hooks import install_neutral_nation_runtime_hooks

    state = _cross_mode_state()
    attacker = SimpleNamespace(strategic_formation_id="", faction=Faction.NATO)
    pending = SimpleNamespace(target_province_id="srb_a")
    monkeypatch.setattr(garrison, "maybe_attach_neutral_garrison", lambda *_args, **_kwargs: pending)
    monkeypatch.setattr(garrison, "sync_neutral_garrison_after_battle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(CampaignEngine, "end_turn", lambda *_args, **_kwargs: None)
    install_neutral_nation_runtime_hooks()

    assert garrison.maybe_attach_neutral_garrison(state, "srb_a", attacker=attacker) is pending
    garrison.sync_neutral_garrison_after_battle(state, pending, Faction.NATO)
    assert nation_is_hostile_to(state, "SRB", "nato") is True
    assert garrison_is_mobilized_against(state, "srb_b", "nato") is True


def test_persisted_neutral_recovery_survives_runtime_recreation_and_recovers(monkeypatch) -> None:
    from gates_of_codex import neutral_garrison

    state = _cross_mode_state()
    state.map_metadata["neutral_garrison_runtime"] = {
        "schema_version": 1,
        "encounters": {},
        "provinces": {
            "srb_a": {
                "province_id": "srb_a",
                "defeated": True,
                "readiness_milli": 0,
                "roster": [],
                "selection": {
                    "province_id": "srb_a",
                    "units": [
                        {"unit_name": "srb_inf", "quantity": 2, "category": "infantry"},
                    ],
                },
            },
        },
    }
    capture_garrison_battle_state(state, "srb_a")
    persisted_metadata = copy.deepcopy(state.map_metadata)

    restarted = _cross_mode_state()
    restarted.turn_number = state.turn_number + 1
    restarted.map_metadata = persisted_metadata
    monkeypatch.setattr(neutral_garrison, "validate_neutral_garrison_runtime", lambda _state: None)
    validate_neutral_nation_runtime(restarted)
    assert advance_neutral_garrison_recovery(restarted) == 1
    record = restarted.map_metadata["neutral_garrison_runtime"]["provinces"]["srb_a"]
    assert record["roster"] == [
        {"unit_name": "srb_inf", "quantity": 1, "category": "infantry"},
    ]
    assert restarted.map_metadata["neutral_nation_runtime"]["garrisons"]["srb_a"][
        "capacity_roster"
    ] == [
        {"unit_name": "srb_inf", "quantity": 2, "category": "infantry"},
    ]


def test_expanded_national_battle_pair_restores_exact_core_codex_passthrough(tmp_path: Path) -> None:
    from gates_of_codex.expanded_nations_battle_pair import (
        ENGINE_RUNTIME_RELS,
        materialize_battle_pair,
        restore_battle_pair,
    )

    live = tmp_path / "live"
    baseline: dict[str, bytes] = {}
    for rel in ENGINE_RUNTIME_RELS:
        path = live / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"core-codex-baseline::{rel}\n".encode()
        path.write_bytes(payload)
        baseline[rel] = payload

    result = materialize_battle_pair(
        ROOT,
        attacker_actor_id="pol",
        defender_actor_id="rus",
        output_root=live,
    )
    manifest = result["manifest"]
    assert manifest["attacker_actor_id"] == "pol"
    assert manifest["defender_actor_id"] == "rus"
    assert manifest["attacker_expanded_tactical_side"] == "goc_pol"
    assert manifest["defender_expanded_tactical_side"] == "goc_rus"
    assert result["ok"] is True

    installed = set(manifest["installed_files"])
    restore = restore_battle_pair(live)
    assert not restore["preserved_tampered"]
    for rel, payload in baseline.items():
        assert (live / rel).read_bytes() == payload
    for rel in installed - set(baseline):
        assert not (live / rel).exists()


def test_profile_mismatch_prevents_cross_mode_continue_from_silent_conversion() -> None:
    state = _cross_mode_state()
    core = get_scenario("ww3_2028_core").profile_identity()
    expanded = get_scenario("ww3_2028_expanded").profile_identity()
    stamp_scenario_profile(state, core)
    with pytest.raises(ScenarioProfileError, match="scenario_profile_id_mismatch"):
        require_compatible_scenario_profile(state, expanded)


def test_fresh_process_deserialization_restores_matching_2028_contract() -> None:
    state = load_legacy_test_scenario()
    state.map_metadata["scenario_id"] = "ww3_2028_core"
    stamp_scenario_profile(state, get_scenario("ww3_2028_core").profile_identity())
    loaded = campaign_from_dict(state.to_dict())
    assert loaded.map_metadata["scenario_profile"]["scenario_id"] == "ww3_2028_core"


def test_fresh_process_deserialization_rejects_incompatible_2028_profile() -> None:
    state = load_legacy_test_scenario()
    state.map_metadata["scenario_id"] = "ww3_2028_core"
    stamp_scenario_profile(state, get_scenario("ww3_2028_expanded").profile_identity())
    with pytest.raises(ValueError, match="ww3_2028_scenario_metadata_mismatch|scenario_profile"):
        campaign_from_dict(state.to_dict())


def test_materialized_province_authority_is_authenticated() -> None:
    rows = load_province_authority()
    assert len(rows) == 3299
    assert len({row["province_id"] for row in rows}) == 3299


def test_acceptance_gate_matches_materialized_repository_without_self_approval() -> None:
    gate = load_acceptance_gate()
    status = validate_acceptance_gate(gate)
    assert status.blocked is True
    assert status.province_authority_materialized is True
    assert status.checks["province_authority_materialized"] is True
    assert status.production_authorized is False
    for check in (
        "core_native_smoke_accepted",
        "expanded_native_smoke_accepted",
        "owner_visual_accepted",
        "independent_review_accepted",
    ):
        assert status.checks[check] is False
    assert "materialized" in status.blocker.lower()


def test_materialization_does_not_self_declare_native_owner_or_review_acceptance() -> None:
    status = validate_acceptance_gate(load_acceptance_gate())
    assert status.checks["province_authority_materialized"] is True
    assert status.checks["core_native_smoke_accepted"] is False
    assert status.checks["expanded_native_smoke_accepted"] is False
    assert status.checks["owner_visual_accepted"] is False
    assert status.checks["independent_review_accepted"] is False


def test_gate_cannot_authorize_production_with_any_required_check_false() -> None:
    gate = load_acceptance_gate()
    mutated = copy.deepcopy(gate)
    mutated["production_authorized"] = True
    mutated["status"] = "READY"
    with pytest.raises(Scenario2028AcceptanceError, match="acceptance_gate_authorization_not_derived_from_checks"):
        validate_acceptance_gate(mutated)
