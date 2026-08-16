from __future__ import annotations

import copy
from types import SimpleNamespace

from gates_of_codex.models import Faction
from gates_of_codex.scenario import get_scenario
from gates_of_codex.scenario_2028_expanded import (
    apply_expanded_2028_projection,
    restore_core_2028_projection,
)
from gates_of_codex.strategic_actors import EngineTacticalSide, StrategicActorState


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


def _province(
    province_id: str,
    sovereign: str,
    controller: str,
) -> SimpleNamespace:
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


def _state() -> SimpleNamespace:
    provinces = {
        "pol": _province("pol", "POL", "nato"),
        "ukr": _province("ukr", "UKR", "ukr"),
        "occ": _province("occ", "UKR", "rusa"),
        "blr": _province("blr", "BLR", "prc"),
        "srb": _province("srb", "SRB", "neutral"),
    }
    return SimpleNamespace(
        provinces=provinces,
        map_metadata={"ww3_2028_controller_profile": "core"},
        selected_faction=Faction.NATO,
        current_faction=Faction.NATO,
        schema_version=9,
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


def _core_snapshot(state: SimpleNamespace) -> dict[str, object]:
    return {
        "schema_version": state.schema_version,
        "selected_faction": state.selected_faction,
        "current_faction": state.current_faction,
        "map_metadata": copy.deepcopy(state.map_metadata),
        "provinces": {
            key: {
                "owner": province.owner,
                "metadata": copy.deepcopy(province.metadata),
            }
            for key, province in state.provinces.items()
        },
    }


def test_expanded_projection_uses_national_actor_where_supported() -> None:
    state = _state()
    apply_expanded_2028_projection(state, _actors())
    assert state.provinces["pol"].metadata["military_controller"] == "pol"
    assert state.provinces["ukr"].metadata["military_controller"] == "ukr"
    assert state.provinces["occ"].metadata["military_controller"] == "rus"
    assert state.provinces["blr"].metadata["military_controller"] == "prc"
    assert state.provinces["blr"].metadata["sovereign_owner"] == "BLR"
    assert state.provinces["srb"].owner == Faction.NEUTRAL
    assert state.provinces["srb"].metadata["owner_actor_id"] == "srb"
    assert state.provinces["srb"].metadata["military_controller"] == "neutral"


def test_core_to_expanded_to_core_restores_controller_state_cleanly() -> None:
    state = _state()
    before = _core_snapshot(state)
    apply_expanded_2028_projection(state, _actors())
    restore_core_2028_projection(state)
    assert _core_snapshot(state) == before
    for province in state.provinces.values():
        assert "expanded_controller_actor_id" not in province.metadata


def test_expanded_projection_leaves_nonselectable_water_untouched() -> None:
    state = _state()
    state.provinces["water"] = SimpleNamespace(
        province_id="water",
        owner=Faction.NEUTRAL,
        metadata={"is_water": True, "selectable": False, "terrain_id": 0},
    )
    before = _core_snapshot(state)
    apply_expanded_2028_projection(state, _actors())
    assert state.provinces["water"].owner == Faction.NEUTRAL
    assert state.provinces["water"].metadata == before["provinces"]["water"]["metadata"]
    restore_core_2028_projection(state)
    assert _core_snapshot(state) == before


def test_expanded_scenario_shares_exact_world_authority_with_core() -> None:
    core = get_scenario("ww3_2028_core")
    expanded = get_scenario("ww3_2028_expanded")
    assert expanded.shared_world_authority_id == core.shared_world_authority_id
    assert expanded.shared_world_authority_id == "earth3_ww3_2028_v1"
    assert expanded.actor_catalog_id == "expanded_nations_2028"
    assert expanded.status == "development"
