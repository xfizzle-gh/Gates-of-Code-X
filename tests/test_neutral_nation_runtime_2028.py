from __future__ import annotations

from types import SimpleNamespace

import pytest

from gates_of_codex.models import Faction
from gates_of_codex.neutral_nation_runtime import (
    NeutralNationRuntimeError,
    advance_neutral_garrison_recovery,
    capture_garrison_battle_state,
    declare_neutral_nation_hostile,
    garrison_is_mobilized_against,
    nation_is_hostile_to,
    province_is_hostile_to,
    validate_neutral_nation_runtime,
)
from gates_of_codex.neutral_nation_runtime_hooks import _attacker_identity


def _province(province_id: str, sovereign: str) -> SimpleNamespace:
    return SimpleNamespace(
        province_id=province_id,
        owner=Faction.NEUTRAL,
        metadata={
            "sovereign_owner": sovereign,
            "military_controller": "neutral",
            "core_controller": "neutral",
        },
    )


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        turn_number=4,
        provinces={
            "e3_0100": _province("e3_0100", "SRB"),
            "e3_0101": _province("e3_0101", "SRB"),
            "e3_0200": _province("e3_0200", "CHE"),
        },
        battalions={},
        strategic_formations={},
        map_metadata={"scenario_id": "ww3_2028_core"},
    )


def _seed_recovery_authority(state: SimpleNamespace) -> None:
    state.map_metadata["neutral_garrison_runtime"] = {
        "schema_version": 1,
        "encounters": {},
        "provinces": {
            "e3_0100": {
                "province_id": "e3_0100",
                "defeated": True,
                "readiness_milli": 0,
                "roster": [],
                "selection": {
                    "province_id": "e3_0100",
                    "units": [
                        {"unit_name": "srb_inf", "quantity": 3, "category": "infantry"},
                        {"unit_name": "srb_at", "quantity": 2, "category": "support"},
                    ],
                },
            }
        },
    }


def _stub_authenticated_48(monkeypatch, calls: list[object] | None = None) -> None:
    from gates_of_codex import neutral_garrison

    def fake_validate(state) -> None:
        if calls is not None:
            calls.append(state)

    monkeypatch.setattr(neutral_garrison, "validate_neutral_garrison_runtime", fake_validate)


def test_first_attack_mobilizes_entire_sovereign_nation_only_against_attacker() -> None:
    state = _state()
    before = {key: province.owner for key, province in state.provinces.items()}
    record = declare_neutral_nation_hostile(state, "e3_0100", "nato")
    assert record is not None
    assert record["province_ids"] == ["e3_0100", "e3_0101"]
    assert record["mobilized_province_ids"] == ["e3_0100", "e3_0101"]
    assert record["hostile_to"] == ["nato"]
    assert nation_is_hostile_to(state, "SRB", "nato") is True
    assert nation_is_hostile_to(state, "SRB", "ukr") is False
    assert nation_is_hostile_to(state, "CHE", "nato") is False
    assert province_is_hostile_to(state, "e3_0101", "nato") is True
    assert garrison_is_mobilized_against(state, "e3_0101", "nato") is True
    assert garrison_is_mobilized_against(state, "e3_0200", "nato") is False
    assert {key: province.owner for key, province in state.provinces.items()} == before
    assert state.provinces["e3_0100"].metadata["sovereign_owner"] == "SRB"
    validate_neutral_nation_runtime(state)


def test_second_province_consumes_nation_wide_hostility_before_it_is_attacked() -> None:
    state = _state()
    declare_neutral_nation_hostile(state, "e3_0100", "nato")
    assert province_is_hostile_to(state, "e3_0101", "nato") is True
    assert state.provinces["e3_0101"].metadata["neutral_hostile_to_actor_ids"] == ["nato"]
    assert state.provinces["e3_0101"].metadata["neutral_garrison_mobilized_against"] == ["nato"]

    record = declare_neutral_nation_hostile(state, "e3_0101", "nato")
    assert record is not None
    assert record["first_hostile_turn_by_attacker"] == {"nato": 4}
    assert record["mobilized_province_ids"] == ["e3_0100", "e3_0101"]
    validate_neutral_nation_runtime(state)


def test_second_attacker_is_added_without_coalition_side_effects() -> None:
    state = _state()
    declare_neutral_nation_hostile(state, "e3_0100", "nato")
    declare_neutral_nation_hostile(state, "e3_0101", "rusa")
    record = state.map_metadata["neutral_nation_runtime"]["nations"]["SRB"]
    assert record["hostile_to"] == ["nato", "rusa"]
    assert state.provinces["e3_0101"].metadata["neutral_hostile_to_actor_ids"] == ["nato", "rusa"]
    assert "alliances" not in state.map_metadata["neutral_nation_runtime"]


def test_expanded_attack_uses_national_actor_not_tactical_coalition() -> None:
    state = _state()
    state.map_metadata["scenario_id"] = "ww3_2028_expanded"
    state.strategic_formations["sf_pol"] = SimpleNamespace(actor_id="pol")
    attacker = SimpleNamespace(
        strategic_formation_id="sf_pol",
        faction=Faction.NATO,
    )
    attacker_id = _attacker_identity(state, attacker)
    assert attacker_id == "pol"
    declare_neutral_nation_hostile(state, "e3_0100", attacker_id)
    assert nation_is_hostile_to(state, "SRB", "pol") is True
    assert nation_is_hostile_to(state, "SRB", "nato") is False


def test_expanded_neutral_attack_hook_records_pol_and_mobilizes_second_province(monkeypatch) -> None:
    from gates_of_codex import neutral_garrison as garrison
    from gates_of_codex.campaign import CampaignEngine
    from gates_of_codex.neutral_nation_runtime_hooks import install_neutral_nation_runtime_hooks

    state = _state()
    state.map_metadata["scenario_id"] = "ww3_2028_expanded"
    state.strategic_formations["sf_pol"] = SimpleNamespace(actor_id="pol")
    attacker = SimpleNamespace(
        strategic_formation_id="sf_pol",
        faction=Faction.NATO,
    )
    pending = SimpleNamespace(target_province_id="e3_0100")

    def fake_attach(_state, _province_id, *args, **kwargs):
        return pending

    def fake_sync(*args, **kwargs):
        return None

    def fake_end_turn(*args, **kwargs):
        return None

    monkeypatch.setattr(garrison, "maybe_attach_neutral_garrison", fake_attach)
    monkeypatch.setattr(garrison, "sync_neutral_garrison_after_battle", fake_sync)
    monkeypatch.setattr(CampaignEngine, "end_turn", fake_end_turn)
    install_neutral_nation_runtime_hooks()

    result = garrison.maybe_attach_neutral_garrison(
        state,
        "e3_0100",
        attacker=attacker,
    )
    assert result is pending
    assert nation_is_hostile_to(state, "SRB", "pol") is True
    assert nation_is_hostile_to(state, "SRB", "nato") is False
    assert garrison_is_mobilized_against(state, "e3_0101", "pol") is True


def test_core_attack_falls_back_to_campaign_faction_identity() -> None:
    state = _state()
    attacker = SimpleNamespace(
        strategic_formation_id="",
        faction=Faction.NATO,
    )
    assert _attacker_identity(state, attacker) == "nato"


def test_defeated_garrison_recovers_one_authored_unit_per_turn_toward_capacity() -> None:
    state = _state()
    _seed_recovery_authority(state)
    capture_garrison_battle_state(state, "e3_0100")
    state.turn_number += 1
    assert advance_neutral_garrison_recovery(state) == 1
    record = state.map_metadata["neutral_garrison_runtime"]["provinces"]["e3_0100"]
    assert record["defeated"] is False
    assert record["roster"] == [
        {"unit_name": "srb_inf", "quantity": 1, "category": "infantry"},
        {"unit_name": "srb_at", "quantity": 1, "category": "support"},
    ]
    first_readiness = record["readiness_milli"]
    assert 0 < first_readiness < 1000

    state.turn_number += 3
    assert advance_neutral_garrison_recovery(state) == 1
    record = state.map_metadata["neutral_garrison_runtime"]["provinces"]["e3_0100"]
    assert record["roster"] == [
        {"unit_name": "srb_inf", "quantity": 3, "category": "infantry"},
        {"unit_name": "srb_at", "quantity": 2, "category": "support"},
    ]
    assert record["readiness_milli"] == 1000


def test_recovery_is_idempotent_within_same_turn() -> None:
    state = _state()
    _seed_recovery_authority(state)
    state.map_metadata["neutral_garrison_runtime"]["provinces"]["e3_0100"]["selection"]["units"] = [
        {"unit_name": "srb_inf", "quantity": 2, "category": "infantry"}
    ]
    capture_garrison_battle_state(state, "e3_0100")
    state.turn_number += 1
    assert advance_neutral_garrison_recovery(state) == 1
    assert advance_neutral_garrison_recovery(state) == 0


def test_load_validation_authenticates_48_selection_before_recovery(monkeypatch) -> None:
    state = _state()
    _seed_recovery_authority(state)
    capture_garrison_battle_state(state, "e3_0100")
    calls: list[object] = []
    _stub_authenticated_48(monkeypatch, calls)

    validate_neutral_nation_runtime(state)

    assert calls == [state]


def test_load_validation_rejects_tampered_recovery_capacity(monkeypatch) -> None:
    state = _state()
    _seed_recovery_authority(state)
    capture_garrison_battle_state(state, "e3_0100")
    _stub_authenticated_48(monkeypatch)
    state.map_metadata["neutral_nation_runtime"]["garrisons"]["e3_0100"]["capacity_roster"][0]["quantity"] = 99

    with pytest.raises(NeutralNationRuntimeError, match="recovery_capacity_mismatch"):
        validate_neutral_nation_runtime(state)


def test_load_validation_rejects_tampered_recovery_rate(monkeypatch) -> None:
    state = _state()
    _seed_recovery_authority(state)
    capture_garrison_battle_state(state, "e3_0100")
    _stub_authenticated_48(monkeypatch)
    state.map_metadata["neutral_nation_runtime"]["garrisons"]["e3_0100"]["recovery_per_unit_per_turn"] = 7

    with pytest.raises(NeutralNationRuntimeError, match="recovery_rate_invalid"):
        validate_neutral_nation_runtime(state)


def test_load_validation_rejects_future_recovery_turn(monkeypatch) -> None:
    state = _state()
    _seed_recovery_authority(state)
    capture_garrison_battle_state(state, "e3_0100")
    _stub_authenticated_48(monkeypatch)
    state.map_metadata["neutral_nation_runtime"]["garrisons"]["e3_0100"]["last_recovery_turn"] = state.turn_number + 1

    with pytest.raises(NeutralNationRuntimeError, match="recovery_last_turn_in_future"):
        validate_neutral_nation_runtime(state)
