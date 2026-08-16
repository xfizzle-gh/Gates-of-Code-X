from __future__ import annotations

from types import SimpleNamespace

import pytest

from gates_of_codex.models import Faction
from gates_of_codex.scenario import get_scenario
from gates_of_codex.scenario_2028_authority import (
    UKRAINE_FRONT_METHOD,
    Scenario2028AuthorityError,
)
from gates_of_codex.scenario_2028_core import apply_core_2028_control


def _province(province_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        province_id=province_id,
        owner=Faction.NEUTRAL,
        metadata={},
    )


def _state() -> SimpleNamespace:
    provinces = {
        f"e3_{index:04d}": _province(f"e3_{index:04d}")
        for index in range(1, 5)
    }
    return SimpleNamespace(provinces=provinces, map_metadata={})


def _row(province_id: str, sovereign_owner: str, controller: str) -> dict[str, object]:
    row: dict[str, object] = {
        "province_id": province_id,
        "sovereign_owner": sovereign_owner,
        "military_controller": controller,
        "core_controller": controller,
        "expanded_controller": controller,
        "garrison_actor": None,
        "neighbors": [],
        "hostile_neighbors": [],
        "metrics": {"graph_degree": 0, "selectable_degree": 0},
        "strategic": {"is_chokepoint": False, "strategic_value": 0},
    }
    if sovereign_owner == "UKR":
        row.update(
            {
                "front_reference_date": "2026-08-12",
                "front_source": "deepstate_approximate",
                "front_method": UKRAINE_FRONT_METHOD,
            }
        )
    return row


def _rows() -> list[dict[str, object]]:
    return [
        _row("e3_0001", "BLR", "prc"),
        _row("e3_0002", "UKR", "ukr"),
        _row("e3_0003", "POL", "nato"),
        _row("e3_0004", "RUS", "rusa"),
    ]


def test_core_projection_keeps_sovereignty_separate_from_control() -> None:
    state = _state()
    apply_core_2028_control(state, _rows(), expected_count=4)
    belarus = state.provinces["e3_0001"]
    assert belarus.metadata["sovereign_owner"] == "BLR"
    assert belarus.metadata["military_controller"] == "prc"
    assert belarus.metadata["controller_profile"] == "core"
    assert belarus.owner == Faction.PRC


def test_core_projection_contains_only_locked_core_controller_factions() -> None:
    state = _state()
    apply_core_2028_control(state, _rows(), expected_count=4)
    assert {province.owner for province in state.provinces.values()} == {
        Faction.NATO,
        Faction.UKRAINE,
        Faction.RUSSIA,
        Faction.PRC,
    }


def test_core_projection_rejects_unknown_earth3_ids() -> None:
    state = _state()
    rows = _rows()
    rows[3]["province_id"] = "e3_9999"
    with pytest.raises(Scenario2028AuthorityError, match="unknown_earth3_ids"):
        apply_core_2028_control(state, rows, expected_count=4)


def test_core_scenario_registry_persists_locked_profile_identity() -> None:
    definition = get_scenario("ww3_2028_core")
    assert definition.status == "development"
    assert definition.shared_world_authority_id == "earth3_ww3_2028_v1"
    assert definition.actor_catalog_id == "core_2028"
    assert definition.actor_catalog_compatibility_version == "1"
    assert "config/earth3/ww3_2028_province_authority.json" in definition.required_asset_authority
